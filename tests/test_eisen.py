import copy
import math
import sys
import tempfile
import unittest
from unittest.mock import patch
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "demo"))
from model import CATEGORIES, clock, loss, metrics, ordered_queue, recoveries, repair_value, review_priority, seed_state, stay_estimate, task_priority
from server import RuleError, Store, apply_action, proposal, public_state, rebalance_queues

AGENT = {"id": "agent", "name": "Hotel agent", "role": "agent"}
MIKE = {"id": "mike", "name": "Mike", "role": "worker"}
SARA = {"id": "sara", "name": "Sara", "role": "worker"}


class WorkflowTests(unittest.TestCase):
    def setUp(self):
        self.state = seed_state(include_extra_reports=False)

    def issue(self, issue_id):
        return next(t for t in self.state["issues"] if t["id"] == issue_id)

    def act(self, action, issue_id=None, actor=AGENT, **data):
        if issue_id:
            data.update(id=issue_id, version=self.issue(issue_id)["version"])
        return apply_action(self.state, actor, {"action": action, **data})

    def assign(self, issue_id, wid):
        option = next(o for o in proposal(self.state, self.issue(issue_id)) if o["worker_id"] == wid)
        return self.act("assign", issue_id, worker_id=wid, position=option["position"], revision=self.state["revision"])

    def test_full_cycle_and_guest_reopen(self):
        self.assign("E-101", "sara")
        queue = sorted((t for t in self.state["issues"] if t["worker_id"] == "sara" and t["status"] == "queued"), key=lambda t: t["queue_order"])
        first = queue[0]["id"]
        self.act("head", first, SARA)
        self.act("start", first, SARA)
        self.act("done", first, SARA)
        self.assertEqual(self.issue(first)["status"], "closed")
        self.assertEqual(len(self.state["snapshots"]), 2)
        self.act("reopen", first, reason="Guest says cooling still fails")
        self.assertEqual(self.issue(first)["status"], "new")
        self.assertIsNone(self.issue(first)["worker_id"])
        self.assertEqual(len(self.issue(first)["closures"]), 1)
        self.assertTrue(any(e["reason"] == "Guest says cooling still fails" for e in self.state["events"] if "reason" in e))

    def test_active_worker_cannot_head_to_another_job(self):
        self.assign("E-101", "mike")
        with self.assertRaises(RuleError):
            self.act("head", "E-101", MIKE)
        self.assertEqual(self.issue("E-103")["status"], "working")
        self.assertEqual(self.issue("E-101")["status"], "queued")

    def test_current_commitment_cannot_be_reassigned(self):
        with self.assertRaises(RuleError):
            self.act("assign", "E-103", worker_id="sara", position=0, revision=self.state["revision"])
        self.act("head", "E-107", SARA)
        with self.assertRaises(RuleError):
            self.act("unassign", "E-107")

    def test_worker_cannot_modify_another_workers_job(self):
        with self.assertRaises(RuleError) as error:
            self.act("done", "E-103", SARA)
        self.assertEqual(error.exception.status, 403)

    def test_workers_cannot_approve_dispatch_or_offers(self):
        for action in ("assign", "offer", "advance", "create", "reorder"):
            with self.assertRaises(RuleError) as error:
                apply_action(self.state, MIKE, {"action": action})
            self.assertEqual(error.exception.status, 403)

    def test_worker_payload_excludes_guest_and_recovery_records(self):
        result = public_state(self.state, MIKE)
        self.assertNotIn("guests", result)
        self.assertNotIn("offers", result)
        self.assertNotIn("events", result)
        self.assertEqual([t["id"] for t in result["issues"]], ["E-103"])
        self.assertNotIn("guest_id", result["issues"][0])

    def test_stale_recommendation_cannot_overwrite_new_queue(self):
        old_revision = self.state["revision"]
        self.act("done", "E-103", MIKE)
        with self.assertRaises(RuleError) as error:
            self.act("assign", "E-101", worker_id="mike", position=0, revision=old_revision)
        self.assertEqual(error.exception.status, 409)

    def test_duplicate_completion_rejected(self):
        version = self.issue("E-103")["version"]
        self.act("done", "E-103", MIKE)
        with self.assertRaises(RuleError):
            apply_action(self.state, MIKE, {"action": "done", "id": "E-103", "version": version})
        self.assertEqual(sum(e["action"] == "Job completed" for e in self.state["events"]), 1)

    def test_advancing_time_does_not_complete_work(self):
        statuses = [(t["id"], t["status"]) for t in self.state["issues"]]
        self.act("advance")
        self.assertEqual(statuses, [(t["id"], t["status"]) for t in self.state["issues"]])

    def test_recovery_workflow_and_repeat_suppression(self):
        r = recoveries(self.state, "g1")
        self.assertTrue(r["trigger"])
        kind = r["options"][0]["kind"]
        self.act("offer", guest_id="g1", kind=kind, revision=self.state["revision"])
        offer = self.state["offers"][-1]
        self.assertTrue(recoveries(self.state, "g1")["pending"])
        with self.assertRaises(RuleError):
            self.act("offer_status", offer_id=offer["id"], status="fulfilled")
        for status in ("offered", "accepted", "fulfilled"):
            self.act("offer_status", offer_id=offer["id"], status=status)
        self.assertFalse(recoveries(self.state, "g1")["trigger"])
        self.assertEqual(self.issue("E-101")["status"], "new")
        self.state["offset"] += 3600
        self.assertTrue(recoveries(self.state, "g1")["trigger"])

    def test_policy_limit_enforced(self):
        self.state["policy"]["max_offers_per_stay"] = 0
        self.assertTrue(recoveries(self.state, "g1")["policy_limited"])
        with self.assertRaises(RuleError):
            self.act("offer", guest_id="g1", kind="points", revision=self.state["revision"])

    def test_queue_follows_live_priority_and_only_first_job_can_start(self):
        self.assign("E-101", "sara")
        queue = sorted((t for t in self.state["issues"] if t["worker_id"] == "sara" and t["status"] == "queued"), key=lambda t:t["queue_order"])
        later = queue[1]["id"]
        with self.assertRaises(RuleError):
            self.act("head", later, SARA)
        with self.assertRaises(RuleError):
            self.act("reorder", later, direction=-1, revision=self.state["revision"])
        first=queue[0]["id"]
        self.act("head", first, SARA)
        self.assertEqual(self.issue(first)["status"], "on_way")

    def test_new_urgent_assignment_moves_first_without_interrupting_current_work(self):
        self.assign("E-101","mike")
        active=copy.deepcopy(self.issue("E-103"))
        self.act("create",guest_id="g2",category="leak",description="Active water leak")
        urgent=self.state["issues"][-1]["id"]
        self.assign(urgent,"mike")
        self.assertEqual(ordered_queue(self.state,"mike")[0]["id"],urgent)
        self.assertEqual(self.issue("E-103"),active)
        self.act("done","E-103",MIKE)
        self.assertEqual(ordered_queue(self.state,"mike")[0]["id"],urgent)
        self.act("head",urgent,MIKE)
        committed=copy.deepcopy(self.issue(urgent))
        self.act("create",guest_id="g2",category="leak",description="Another active water leak")
        self.assign(self.state["issues"][-1]["id"],"mike")
        self.assertEqual(self.issue(urgent),committed)

    def test_waiting_job_overtakes_when_its_priority_increases(self):
        now=clock(self.state)
        first=copy.deepcopy(self.issue("E-107"))
        second=copy.deepcopy(first)
        first.update(id="Q-1",reported_at=now,queue_order=0,guest_id="g6")
        second.update(id="Q-2",reported_at=now-3590,queue_order=1,guest_id="g2")
        self.state["issues"]=[first,second]
        self.state["guests"]["g2"]["sensitivity"]["light"]=.01
        categories={**CATEGORIES,"light":{**CATEGORIES["light"],"cap":.1,"tau":50}}
        with patch("model.CATEGORIES",categories),patch("model.clock",return_value=now):
            self.assertEqual([t["id"] for t in ordered_queue(self.state,"sara")],["Q-1","Q-2"])
        stale=first["version"]
        with patch("model.CATEGORIES",categories),patch("model.clock",return_value=now+20):
            self.assertTrue(rebalance_queues(self.state))
            self.assertEqual([t["id"] for t in ordered_queue(self.state,"sara")],["Q-2","Q-1"])
            self.assertGreater(first["version"],stale)
            self.assertFalse(rebalance_queues(self.state))
            with self.assertRaises(RuleError):
                apply_action(self.state,SARA,{"action":"head","id":"Q-1","version":stale})

    def test_live_refresh_persists_stack_once_and_matches_recommendations(self):
        self.assign("E-101","sara")
        self.state["guests"]["g1"]["checkout"]=clock(self.state)-1
        revision=self.state["revision"]
        with tempfile.TemporaryDirectory() as folder:
            store=Store(Path(folder)/"stack.sqlite3")
            with store.connect() as db:
                import json
                db.execute("UPDATE app_state SET data=? WHERE id=1",(json.dumps(self.state),))
            refreshed=store.read()
            self.assertEqual(refreshed["revision"],revision+1)
            self.assertEqual(next(t for t in refreshed["issues"] if t["id"]=="E-107")["queue_order"],0)
            self.assertEqual(store.read()["revision"],refreshed["revision"])
            with store.connect() as db:
                persisted=json.loads(db.execute("SELECT data FROM app_state WHERE id=1").fetchone()[0])
            self.assertEqual(persisted,refreshed)
        # A recommendation's position agrees with the priority order after approval.
        self.state=seed_state(include_extra_reports=False)
        option=next(o for o in proposal(self.state,self.issue("E-101")) if o["worker_id"]=="sara")
        self.assign("E-101","sara")
        self.assertEqual(self.issue("E-101")["queue_order"],option["position"])

    def test_departed_stay_does_not_displace_live_guest_repair(self):
        self.assign("E-101","sara")
        self.state["guests"]["g1"]["checkout"]=clock(self.state)-1
        rebalance_queues(self.state)
        self.assertEqual(ordered_queue(self.state,"sara")[0]["id"],"E-107")

    def test_outcome_requires_resolved_stay(self):
        with self.assertRaises(RuleError):
            self.act("outcome", guest_id="g2", rating=4, sentiment="Mixed", review="Resolved eventually")
        self.act("done", "E-103", MIKE)
        self.act("outcome", guest_id="g2", rating=4, sentiment="Mixed", review="Resolved eventually")
        result=self.state["outcomes"][-1]
        self.assertIn("expected_before_outcome", result)
        self.assertEqual(result["rating"], 4)


class EstimateTests(unittest.TestCase):
    def setUp(self):
        self.state = seed_state(include_extra_reports=False)

    def test_decay_is_monotonic_bounded_and_sensitive_to_history(self):
        t = self.state["issues"][0]
        now = clock(self.state)
        values = [loss(self.state,t,now+i*60) for i in range(120)]
        self.assertEqual(values, sorted(values))
        self.assertLess(values[-1], 1.9)
        sensitive = values[0]
        self.state["guests"]["g1"]["sensitivity"] = {}
        self.assertGreater(sensitive, loss(self.state,t,now))

    def test_combined_rating_is_bounded_and_all_issues_contribute(self):
        combined=stay_estimate(self.state,"g1")
        self.state["issues"] = [t for t in self.state["issues"] if t["id"] != "E-102"]
        self.assertLess(combined["rating"], stay_estimate(self.state,"g1")["rating"])
        for t in self.state["issues"]:
            t["reported_at"] -= 1000000
        self.assertGreaterEqual(stay_estimate(self.state,"g1")["rating"],1)

    def test_completion_freezes_issue_loss(self):
        t=self.state["issues"][2]
        t["closed_at"]=clock(self.state)
        t["status"]="closed"
        before=loss(self.state,t)
        self.state["offset"] += 3600
        self.assertEqual(before,loss(self.state,t))

    def test_reopening_does_not_charge_for_time_previously_closed(self):
        issue=self.state["issues"][2]
        apply_action(self.state, MIKE, {"action":"done", "id":issue["id"], "version":issue["version"]})
        before=loss(self.state,issue)
        self.state["offset"] += 3600
        apply_action(self.state, AGENT, {"action":"reopen", "id":issue["id"], "version":issue["version"], "reason":"Still not cooling"})
        self.assertAlmostEqual(before,loss(self.state,issue),places=5)

    def test_urgent_leak_takes_precedence(self):
        leak=copy.deepcopy(self.state["issues"][0])
        leak.update(category="leak",reported_at=clock(self.state))
        self.assertGreater(metrics(self.state,leak)["priority"], max(metrics(self.state,t)["priority"] for t in self.state["issues"]))

    def test_review_order_prioritizes_agent_decisions_over_committed_work(self):
        issues = {t["id"]: t for t in self.state["issues"]}
        recovery = review_priority(self.state, issues["E-101"])
        unassigned = review_priority(self.state, issues["E-106"])
        queued = review_priority(self.state, issues["E-107"])
        working = review_priority(self.state, issues["E-103"])
        self.assertLess(recovery["tier"], unassigned["tier"])
        self.assertLess(unassigned["tier"], queued["tier"])
        self.assertLess(queued["tier"], working["tier"])
        self.assertEqual(issues["E-103"]["status"], "working")

    def test_urgent_uncommitted_review_precedes_recovery(self):
        leak = copy.deepcopy(self.state["issues"][0])
        leak.update(category="leak", reported_at=clock(self.state))
        self.assertEqual(review_priority(self.state, leak)["tier"], 0)
        self.assertGreater(review_priority(self.state, self.state["issues"][0])["tier"], 0)

    def test_guest_loss_stops_at_checkout_even_with_open_maintenance(self):
        issue=self.state["issues"][0]
        departure=self.state["guests"][issue["guest_id"]]["checkout"]
        self.assertEqual(loss(self.state,issue,departure),loss(self.state,issue,departure+3600))
        self.assertEqual(issue["status"],"new")

    def test_repair_finishing_just_before_checkout_requires_recovery(self):
        issue=self.state["issues"][0]
        self.state["guests"]["g1"]["checkout"]=clock(self.state)+40*60
        value=repair_value(self.state,issue,20)
        self.assertEqual(value["usable"],10)
        self.assertFalse(value["meaningful"])
        self.assertLess(value["avoidable_rating_loss"],.1)
        recovery=recoveries(self.state,"g1")
        self.assertTrue(recovery["trigger"])
        self.assertTrue(recovery["limited_benefit"])
        self.assertNotIn("breakfast",[o["kind"] for o in recovery["options"]])

    def test_longer_stays_still_benefit_from_repair(self):
        issue=self.state["issues"][2]
        value=repair_value(self.state,issue,13)
        self.assertTrue(value["meaningful"])
        self.assertGreater(value["usable"],200)
        self.assertGreater(value["avoidable_rating_loss"],.5)

    def test_departed_guest_has_zero_benefit_from_new_repair(self):
        issue=self.state["issues"][0]
        self.state["guests"]["g1"]["checkout"]=clock(self.state)-60
        value=repair_value(self.state,issue,20)
        self.assertEqual(value["usable"],0)
        self.assertEqual(value["avoidable_rating_loss"],0)

    def test_checkout_ends_guest_dispatch_but_keeps_room_issue_open(self):
        issue=self.state["issues"][0]
        self.state["guests"][issue["guest_id"]]["checkout"]=clock(self.state)-1
        original=copy.deepcopy(issue)
        self.assertEqual(proposal(self.state,issue),[])
        self.assertEqual(issue,original)
        self.assertTrue(recoveries(self.state,issue["guest_id"])["trigger"])
        self.assertIn("checked out",recoveries(self.state,issue["guest_id"])["reason"])
        self.assertEqual(issue["status"],"new")

    def test_urgent_safety_dispatch_remains_available_after_checkout(self):
        issue=self.state["issues"][0]
        issue["category"]="leak"
        self.state["guests"][issue["guest_id"]]["checkout"]=clock(self.state)-1
        self.assertTrue(proposal(self.state,issue))

    def test_stale_pre_checkout_dispatch_cannot_be_approved_after_checkout(self):
        issue=self.state["issues"][0]
        options=proposal(self.state,issue)
        choice=options[0]
        self.state["guests"][issue["guest_id"]]["checkout"]=clock(self.state)-1
        with self.assertRaises(RuleError):
            apply_action(self.state,AGENT,{"action":"assign","id":issue["id"],"version":issue["version"],"revision":self.state["revision"],"worker_id":choice["worker_id"],"position":choice["position"]})

    def test_default_demo_includes_five_additional_unassigned_reports(self):
        expanded=seed_state()
        self.assertEqual(len(expanded["issues"]),13)
        self.assertEqual(expanded["next_id"],114)
        added=expanded["issues"][-5:]
        self.assertEqual(len({t["id"] for t in expanded["issues"]}),13)
        self.assertTrue(all(t["status"]=="new" and t["worker_id"] is None for t in added))
        self.assertIn("leak",{t["category"] for t in added})

    def test_public_stay_scores_use_100_point_scale_without_changing_state(self):
        original=copy.deepcopy(self.state)
        data=public_state(self.state,AGENT)
        self.assertEqual(data["score_metric"]["maximum"],100)
        self.assertEqual(data["score_metric"]["minimum"],0)
        for raw, task in zip(self.state["issues"],data["issues"]):
            self.assertAlmostEqual(task["metrics"]["loss"],metrics(self.state,raw)["loss"]*20)
            self.assertIn(task["task_priority"]["value"],range(1,6))
        for gid, guest in data["guests"].items():
            self.assertAlmostEqual(guest["estimate"]["rating"],stay_estimate(self.state,gid)["rating"]*20)
            self.assertGreaterEqual(guest["estimate"]["low"],0)
            self.assertLessEqual(guest["estimate"]["high"],100)
            self.assertEqual(guest["history"],self.state["guests"][gid]["history"])
        self.assertEqual(self.state,original)
        self.state["outcomes"].append({"guest_id":"g1","rating":4,"expected_before_outcome":stay_estimate(self.state,"g1")})
        outcome=public_state(self.state,AGENT)["outcomes"][0]
        self.assertEqual(outcome["rating"],4)
        self.assertGreater(outcome["expected_before_outcome"]["rating"],5)

    def test_task_priority_uses_absolute_one_to_five_bands(self):
        for issue in self.state["issues"]:
            value=task_priority(self.state,issue)["value"]
            self.assertIsInstance(value,int)
            self.assertIn(value,range(1,6))
        self.assertEqual(task_priority(self.state,self.state["issues"][0])["value"],2)
        self.assertEqual(task_priority(self.state,self.state["issues"][2])["value"],3)
        self.assertEqual(task_priority(self.state,self.state["issues"][4])["value"],4)
        issue=copy.deepcopy(self.state["issues"][0])
        issue["category"]="leak"
        self.assertEqual(task_priority(self.state,issue)["value"],1)
        issue=copy.deepcopy(self.state["issues"][-2])
        issue["category"]="light"
        issue["reported_at"]=clock(self.state)
        with patch('model.CATEGORIES', {**CATEGORIES, "light": {**CATEGORIES["light"], "cap": .1}}):
            self.assertEqual(task_priority(self.state,issue)["value"],5)

    def test_task_priority_does_not_depend_on_filter_or_list_position(self):
        issue=self.state["issues"][4]
        original=task_priority(self.state,issue)["value"]
        self.state["issues"].reverse()
        self.assertEqual(task_priority(self.state,issue)["value"],original)


class PersistenceTests(unittest.TestCase):
    def test_restart_keeps_changes_and_failed_write_rolls_back(self):
        with tempfile.TemporaryDirectory() as folder:
            path=Path(folder)/"test.sqlite3"
            store=Store(path)
            store.mutate(AGENT,{"action":"create","guest_id":"g2","category":"light","description":"Desk light out"})
            state=Store(path).read()
            self.assertEqual(len(state["issues"]),len(seed_state()["issues"])+1)
            revision=state["revision"]
            with self.assertRaises(RuleError):
                store.mutate(MIKE,{"action":"create"})
            self.assertEqual(store.read()["revision"],revision)



if __name__=="__main__":
    unittest.main()
