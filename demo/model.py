"""Configurable, illustrative estimates. These are not calibrated Hilton policies."""
import math
import time

VERSION = "demo-stayscore-v3-priority"
CATEGORIES = {
    "ac": {"label": "Heating / AC", "team": "Maintenance", "minutes": 25, "cap": 1.9, "tau": 65},
    "water": {"label": "Bathroom / water", "team": "Maintenance", "minutes": 20, "cap": 1.5, "tau": 85},
    "light": {"label": "Lights / equipment", "team": "Maintenance", "minutes": 15, "cap": .7, "tau": 140},
    "leak": {"label": "Active water leak", "team": "Maintenance", "minutes": 30, "cap": 2.5, "tau": 25, "urgent": True},
    "clean": {"label": "Room cleaning", "team": "Housekeeping", "minutes": 25, "cap": 1.7, "tau": 80},
    "linen": {"label": "Towels / linen", "team": "Housekeeping", "minutes": 10, "cap": .65, "tau": 110},
}
OFFERS = {
    "coffee": {"label": "Coffee for two", "points": 0, "cost": 12, "credit": .12},
    "breakfast": {"label": "Breakfast for two", "points": 0, "cost": 50, "credit": .3},
    "points": {"label": "2,000 loyalty points", "points": 2000, "cost": 10, "credit": .22},
}

# Illustrative minimum time to benefit after completion, not fitted policy.
SERVICE_WINDOWS = {"ac": {"settling": 10, "minimum": 30}, "clean": {"settling": 0, "minimum": 20},
                   "water": {"settling": 0, "minimum": 20}, "light": {"settling": 0, "minimum": 20},
                   "linen": {"settling": 0, "minimum": 10}, "leak": {"settling": 0, "minimum": 0}}


def clock(state):
    return time.time() + state.get("offset", 0)


def loss(state, issue, at=None):
    at = clock(state) if at is None else at
    guest = state["guests"][issue["guest_id"]]
    category = CATEGORIES[issue["category"]]
    sensitivity = guest.get("sensitivity", {}).get(issue["category"], 1)
    property_factor = state["property_factors"].get(issue["category"], 1)
    end = min(at, issue["closed_at"]) if issue.get("closed_at") else at
    end = min(end, guest["checkout"])
    minutes = max(0, (end - issue["reported_at"] - issue.get("paused_seconds", 0)) / 60)
    return category["cap"] * (1 - math.exp(-minutes * sensitivity * property_factor / category["tau"]))


def stay_estimate(state, guest_id, at=None, override=None):
    at = clock(state) if at is None else at
    guest = state["guests"][guest_id]
    raw = sum(loss(state, t, override.get(t["id"], at) if override else at)
              for t in state["issues"] if t["guest_id"] == guest_id and t["status"] != "cancelled")
    combined = 4 * (1 - math.exp(-raw / 4))
    # Only fulfilled gestures affect this illustrative scenario estimate.
    credit = min(.6, sum(OFFERS[o["kind"]]["credit"] for o in state["offers"]
                          if o["guest_id"] == guest_id and o["status"] == "fulfilled"))
    rating = max(1, min(guest["baseline"], guest["baseline"] - combined + credit))
    return {"rating": round(rating, 2), "low": round(max(1, rating - .4), 1),
            "high": round(min(5, rating + .4), 1), "loss": round(combined, 2),
            "severe": rating < 3.2, "recovery_credit": credit}


def metrics(state, issue):
    now = clock(state)
    current = loss(state, issue, now)
    future = loss(state, issue, now + 30 * 60)
    stay = stay_estimate(state, issue["guest_id"])
    safety = CATEGORIES[issue["category"]].get("urgent", False)
    priority = (1000 if safety else 0) + max(0, 3.2 - stay["rating"]) * 40 + (future - current) * 100 + current * 6
    return {"loss": round(current, 2), "delay_loss": round(future - current, 2), "priority": round(priority, 2),
            "trend": "Worsening quickly" if future - current > .3 else "Worsening" if future - current > .1 else "Slow decline",
            "urgent": safety, "stay": stay}


def travel(a, b):
    return 1 + abs(a - b) * .4


def repair_value(state, issue, finish_minutes):
    """Benefit to this stay, distinct from the continuing maintenance obligation."""
    now = clock(state)
    guest = state["guests"][issue["guest_id"]]
    remaining = max(0, (guest["checkout"] - now) / 60)
    window = SERVICE_WINDOWS[issue["category"]]
    usable = max(0, remaining - finish_minutes - window["settling"])
    horizon = max(now, guest["checkout"])
    no_fix = stay_estimate(state, guest["id"], at=horizon)["rating"]
    with_fix = stay_estimate(state, guest["id"], at=horizon,
                             override={issue["id"]: now + (finish_minutes + window["settling"]) * 60})["rating"]
    return {"remaining": round(remaining), "finish": round(finish_minutes), "settling": window["settling"],
            "usable": round(usable), "minimum": window["minimum"],
            "meaningful": usable >= window["minimum"] and remaining > 0,
            "avoidable_rating_loss": round(max(0, with_fix - no_fix), 2)}


def service_timing(state, issue):
    if issue["status"] == "new":
        options = recommendations(state, issue)
        finish = min((o["finish"] for o in options), default=999)
    elif issue["status"] == "queued":
        worker = next(w for w in state["workers"] if w["id"] == issue["worker_id"])
        finish = worker_plan(state, worker)[issue["id"]]["finish"]
    else:
        finish = max(3, (issue.get("started_at", issue.get("headed_at", clock(state)))
                         + CATEGORIES[issue["category"]]["minutes"] * 60 - clock(state)) / 60)
    return repair_value(state, issue, finish)


def review_priority(state, issue, recovery=None):
    """Agent attention order, separate from worker dispatch and protected work."""
    if issue["status"] == "closed":
        return {"tier": 7, "reason": "Completed"}
    committed = issue["status"] in ("on_way", "working")
    if CATEGORIES[issue["category"]].get("urgent") and not committed:
        return {"tier": 0, "reason": "Urgent issue · review dispatch"}
    recovery = recoveries(state, issue["guest_id"]) if recovery is None else recovery
    if recovery["trigger"]:
        return {"tier": 1, "reason": "Guest recovery first" if recovery["limited_benefit"] else "Recovery decision needed"}
    if state["guests"][issue["guest_id"]]["checkout"] <= clock(state):
        return {"tier": 2, "reason": "Stay ended · guest follow-up"}
    severe = stay_estimate(state, issue["guest_id"])["severe"]
    if issue["status"] == "new":
        return {"tier": 2 if severe else 3, "reason": "Severe stay · needs assignment" if severe else "Needs assignment"}
    if issue["status"] == "queued":
        return {"tier": 4 if severe else 5, "reason": "Severe stay · review queue" if severe else "Assignment approved"}
    return {"tier": 6, "reason": "Worker committed · monitor"}


def task_priority(state, issue, recovery=None):
    """Absolute 1–5 demo bands; 1 is highest, matching HotSOS priority direction.

    Band thresholds are provisional Eisen rules, not Amadeus defaults.
    Assignment status breaks ties in review order; it does not redefine severity.
    """
    m = metrics(state, issue)
    if m["urgent"]:
        return {"value": 1, "label": "Critical", "reason": "Active safety-related issue"}
    if m["stay"]["severe"]:
        return {"value": 2, "label": "High", "reason": "Severe stay impact"}
    if m["delay_loss"] >= .3 or m["priority"] >= 35 or clock(state) - issue["reported_at"] >= 3600:
        return {"value": 3, "label": "Medium", "reason": "Time-sensitive impact or extended wait"}
    if m["loss"] >= .15 or m["delay_loss"] >= .1:
        return {"value": 4, "label": "Low", "reason": "Lower-impact service request"}
    return {"value": 5, "label": "Routine", "reason": "Limited immediate impact"}


def ordered_queue(state, worker_id, inserted=None):
    """Only approved, unstarted jobs move; committed work is never included."""
    now = clock(state)
    queue = [t for t in state["issues"] if t["worker_id"] == worker_id and t["status"] == "queued"
             and (inserted is None or t["id"] != inserted["id"])]
    if inserted is not None:
        queue.append(inserted)
    def rank(issue):
        m = metrics(state, issue)
        departed = state["guests"][issue["guest_id"]]["checkout"] <= now and not m["urgent"]
        return (departed, task_priority(state, issue)["value"], -m["priority"], issue["reported_at"], issue["id"])
    return sorted(queue, key=rank)


def worker_plan(state, worker, inserted=None, position=0):
    now = clock(state)
    active = next((t for t in state["issues"] if t["worker_id"] == worker["id"] and t["status"] in ("on_way", "working")), None)
    minutes, floor = 0, worker["floor"]
    if active:
        expected = active.get("started_at", active.get("headed_at", now)) + CATEGORIES[active["category"]]["minutes"] * 60
        minutes = max(3, (expected - now) / 60)
        if active["status"] == "on_way":
            minutes += travel(worker["floor"], active["floor"])
        floor = active["floor"]
    queue = ordered_queue(state, worker["id"], inserted)
    result = {}
    for t in queue:
        minutes += travel(floor, t["floor"])
        start = minutes
        minutes += CATEGORIES[t["category"]]["minutes"]
        result[t["id"]] = {"start": round(start), "finish": round(minutes)}
        floor = t["floor"]
    return result


def recommendations(state, issue):
    now = clock(state)
    # A departed guest cannot benefit from a new service dispatch. Safety work remains urgent.
    if state["guests"][issue["guest_id"]]["checkout"] <= now and not CATEGORIES[issue["category"]].get("urgent"):
        return []
    options = []
    for worker in state["workers"]:
        if worker["team"] != CATEGORIES[issue["category"]]["team"]:
            continue
        base = worker_plan(state, worker)
        queue = sorted((t for t in state["issues"] if t["worker_id"] == worker["id"] and t["status"] == "queued"), key=lambda t: t["queue_order"])
        ordered = ordered_queue(state, worker["id"], issue)
        position = next(i for i, task in enumerate(ordered) if task["id"] == issue["id"])
        plan = worker_plan(state, worker, issue, position)
        target = plan[issue["id"]]
        added_harm = sum(max(0, loss(state, t, now + plan[t["id"]]["finish"] * 60) - loss(state, t, now + base[t["id"]]["finish"] * 60)) for t in queue)
        future = loss(state, issue, now + (target["finish"] + SERVICE_WINDOWS[issue["category"]]["settling"]) * 60)
        late = now + target["finish"] * 60 > state["guests"][issue["guest_id"]]["checkout"]
        objective = future + added_harm
        active = next((t for t in state["issues"] if t["worker_id"] == worker["id"] and t["status"] in ("working", "on_way")), None)
        reason = (f"{worker['name']} is committed to room {active['room']}. " if active else f"{worker['name']} is available on floor {worker['floor']}. ")
        reason += f"Start in about {target['start']} min; finish in about {target['finish']} min. "
        if position < len(queue):
            reason += f"Place before room {queue[position]['room']}; {len(queue) - position} queued job(s) move later."
        else:
            reason += "Upcoming jobs follow live priority; committed work stays protected."
        options.append({"worker_id": worker["id"], "name": worker["name"], "position": position, **target,
                        "late": late, "reason": reason, "objective": round(objective, 3), "added_harm": round(added_harm, 2),
                        "guest_value": repair_value(state, issue, target["finish"])})
    # Each worker option uses the same live priority order as the executable stack.
    options.sort(key=lambda o: (o["objective"], o["finish"], o["worker_id"]))
    distinct = []
    for option in options:
        if not any(o["worker_id"] == option["worker_id"] for o in distinct):
            distinct.append(option)
    return distinct


def recoveries(state, guest_id):
    guest = state["guests"][guest_id]
    issues = [t for t in state["issues"] if t["guest_id"] == guest_id and t["status"] not in ("closed", "cancelled")]
    estimate = stay_estimate(state, guest_id)
    now = clock(state)
    timings = [service_timing(state, issue) for issue in issues]
    unlikely = any(t["finish"] >= t["remaining"] for t in timings)
    limited_benefit = any(not t["meaningful"] for t in timings)
    previous = [o for o in state["offers"] if o["guest_id"] == guest_id]
    pending = any(o["status"] in ("approved", "offered", "accepted") for o in previous)
    handled = [o for o in previous if o["status"] in ("fulfilled", "declined")]
    materially_worse = not handled or estimate["loss"] >= handled[-1].get("loss_at_offer", 0) + .25
    trigger = (estimate["severe"] or limited_benefit) and not pending and materially_worse
    charged = [o for o in previous if o["status"] != "declined"]
    policy = state["policy"]
    # Illustrative catalog ranking: reflect historical acceptance, preferences, repeats, checkout feasibility.
    ranked = []
    for kind, offer in OFFERS.items():
        if (len(charged) >= policy["max_offers_per_stay"]
                or sum(OFFERS[o["kind"]]["cost"] for o in charged) + offer["cost"] > policy["max_cost_per_stay"]
                or sum(OFFERS[o["kind"]]["points"] for o in charged) + offer["points"] > policy["max_points_per_stay"]):
            continue
        value = offer["credit"]
        if kind == guest.get("preferred_offer"):
            value += .2
        # Do not recommend a meal the guest cannot use before departure.
        if kind == "breakfast" and guest["checkout"] - now < 60 * 60:
            continue
        if any(o["kind"] == kind for o in handled):
            value -= .15
        if kind == "points" and not guest["loyalty"]:
            continue
        if any(h.get("offer") == kind and h.get("accepted") is False for h in guest["history"]):
            value -= .3
        ranked.append({"kind": kind, **offer, "value": value})
    ranked.sort(key=lambda o: -o["value"])
    return {"trigger": trigger and bool(ranked), "policy_limited": trigger and not ranked,
            "limited_benefit": limited_benefit,
            "reason": ("The guest has checked out. Follow up about the completed stay; repairs prepare the room for its next use."
                       if guest["checkout"] <= now else "A fix is unlikely to finish before checkout. Contact the guest now; keep maintenance open."
                       if unlikely else "A fix would leave too little useful time before checkout. Contact the guest now; keep maintenance open."
                       if limited_benefit else "The combined stay experience is severely affected. Contact the guest while work continues."
                       if estimate["severe"] else "Repair can still provide useful service before checkout."),
            "options": ranked[:2], "previous": previous, "pending": pending,
            "suppressed": not materially_worse and not pending and (estimate["severe"] or limited_benefit)}


EXTRA_SAMPLE_REPORTS = [
    ("g2", "ac", "Room temperature is too hot despite AC running", 35, "new", None),
    ("g3", "leak", "Water leaking under the bathroom sink", 8, "new", None),
    ("g6", "clean", "Spilled coffee on the carpet needs cleaning", 20, "new", None),
    ("g2", "light", "Desk lamp flickers and switches off", 5, "new", None),
    ("g3", "linen", "Extra pillows and a fresh duvet requested", 12, "new", None),
]


def seed_state(include_extra_reports=True):
    now = time.time()
    guests = {
        "g1": {"id": "g1", "name": "Alex Morgan", "room": "1208", "baseline": 4.7, "checkout": now + 42 * 60, "loyalty": True,
               "sensitivity": {"ac": 1.65}, "preferred_offer": "points", "history": [
                   {"property": "Waldorf Astoria Ithaca", "issue": "Room too warm", "expected": 2.5, "actual": 3, "sentiment": "Mixed: appreciated recovery, still mentioned the heat", "offer": "points", "accepted": True},
                   {"property": "Previous sample property", "issue": "Noisy AC", "expected": 3.2, "actual": 2, "sentiment": "Negative: sleep disturbed", "offer": "coffee", "accepted": False}]},
        "g2": {"id": "g2", "name": "Taylor Reed", "room": "1204", "baseline": 4.6, "checkout": now + 240 * 60, "loyalty": True, "sensitivity": {}, "history": [], "preferred_offer": "breakfast"},
        "g3": {"id": "g3", "name": "Jordan Lee", "room": "0812", "baseline": 4.7, "checkout": now + 360 * 60, "loyalty": False, "sensitivity": {"clean": 1.3}, "history": [{"property": "Waldorf Astoria Ithaca", "issue": "Room cleanliness", "expected": 3.5, "actual": 3, "sentiment": "Negative: cleanliness mattered", "offer": "breakfast", "accepted": True}], "preferred_offer": "breakfast"},
        "g4": {"id": "g4", "name": "Casey Rivera", "room": "0816", "baseline": 4.8, "checkout": now + 150 * 60, "loyalty": True, "sensitivity": {}, "history": [], "preferred_offer": "coffee"},
        "g5": {"id": "g5", "name": "Sam Patel", "room": "1502", "baseline": 4.6, "checkout": now + 110 * 60, "loyalty": True, "sensitivity": {"water": 1.2}, "history": [], "preferred_offer": "points"},
        "g6": {"id": "g6", "name": "Drew Wilson", "room": "1510", "baseline": 4.7, "checkout": now + 300 * 60, "loyalty": False, "sensitivity": {}, "history": [], "preferred_offer": "coffee"},
    }
    workers = [{"id": "mike", "name": "Mike", "team": "Maintenance", "floor": 12},
               {"id": "sara", "name": "Sara", "team": "Maintenance", "floor": 8},
               {"id": "ana", "name": "Ana", "team": "Housekeeping", "floor": 8},
               {"id": "leo", "name": "Leo", "team": "Housekeeping", "floor": 15}]
    specs = [("g1", "ac", "AC runs, but the room is not cooling", 75, "new", None),
             ("g1", "clean", "Bathroom was not cleaned before arrival", 55, "new", None),
             ("g2", "ac", "Thermostat is not responding", 30, "working", "mike"),
             ("g3", "clean", "Stains on the bathroom floor", 25, "working", "ana"),
             ("g4", "linen", "Two fresh bath towels requested", 18, "new", None),
             ("g5", "water", "Shower has no hot water", 65, "new", None),
             ("g6", "light", "Bedside lamp does not turn on", 12, "queued", "sara"),
             ("g6", "linen", "Replacement bedding requested", 10, "queued", "leo")]
    if include_extra_reports:
        specs.extend(EXTRA_SAMPLE_REPORTS)
    issues = []
    for i, (gid, category, text, age, status, worker) in enumerate(specs, 1):
        issues.append({"id": f"E-{100+i}", "guest_id": gid, "room": guests[gid]["room"], "floor": int(guests[gid]["room"][:-2]),
                       "category": category, "description": text, "note": "", "reported_at": now - age * 60,
                       "status": status, "worker_id": worker, "queue_order": 0, "version": 1,
                       **({"started_at": now - 12 * 60} if status == "working" else {})})
    return {"property": "Waldorf Astoria Ithaca", "revision": 1, "offset": 0, "next_id": 101 + len(issues), "guests": guests,
            "workers": workers, "issues": issues, "offers": [], "events": [], "snapshots": [], "outcomes": [],
            "property_factors": {"ac": 1.12, "water": 1.05, "clean": 1.08},
            "property_history": [{"category": "ac", "count": 18, "summary": "Cooling complaints: faster decline in sample property history"},
                                 {"category": "clean", "count": 12, "summary": "Cleanliness complaints: repeat issues associated with lower ratings"}],
            "policy": {"label": "Illustrative demo policy", "max_offers_per_stay": 3, "max_cost_per_stay": 100, "max_points_per_stay": 6000}}
