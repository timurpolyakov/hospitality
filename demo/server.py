#!/usr/bin/env python3
"""Local Eisen MVP: same-origin UI/API, SQLite persistence, direct agent and worker portals."""
import argparse
import copy
import json
import hashlib
import subprocess
import sys
import mimetypes
import secrets
import sqlite3
import threading
import time
from contextlib import contextmanager
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import parse_qs, urlsplit

from model import CATEGORIES, OFFERS, VERSION, clock, metrics, ordered_queue, recommendations, recoveries, review_priority, seed_state, stay_estimate, task_priority

ROOT = Path(__file__).resolve().parent
ACTIVE = ("on_way", "working")


class RuleError(Exception):
    def __init__(self, message, status=400):
        self.status = status
        super().__init__(message)


def require(condition, message, status=400):
    if not condition:
        raise RuleError(message, status)


def proposal(state, issue):
    clean = copy.deepcopy(state)
    target = next(t for t in clean["issues"] if t["id"] == issue["id"])
    target.update(status="new", worker_id=None)
    return recommendations(clean, target)


def event(state, actor, action, issue=None, **details):
    state["events"].append({"id": secrets.token_hex(6), "at": clock(state), "actor": actor["name"], "action": action,
                            "issue_id": issue["id"] if issue else None, **details})


def snapshot(state, issue, action):
    state["snapshots"].append({"at": clock(state), "issue_id": issue["id"], "action": action,
                               "model": VERSION, "metrics": metrics(state, issue), "property_factors": copy.deepcopy(state["property_factors"]),
                               "categories": copy.deepcopy(CATEGORIES), "sensitivity": copy.deepcopy(state["guests"][issue["guest_id"]]["sensitivity"])})


def rebalance_queues(state):
    changed = False
    for worker in state["workers"]:
        queue = ordered_queue(state, worker["id"])
        moved = False
        for index, task in enumerate(queue):
            if task["queue_order"] != index:
                task["queue_order"] = index
                task["version"] += 1
                moved = changed = True
        if moved:
            event(state, {"name": "Eisen"}, "Stack updated by priority", worker=worker["name"], order=[t["id"] for t in queue])
    return changed


def apply_action(state, actor, data):
    action = data.get("action")
    now = clock(state)
    if rebalance_queues(state):
        state["revision"] += 1
    if action in ("assign", "reorder", "unassign", "create", "edit", "reopen", "offer", "offer_status", "advance", "outcome"):
        require(actor["role"] == "agent", "Only the hotel agent can approve this action.", 403)
    else:
        require(action in ("head", "start", "done"), "Unknown action.")
        require(actor["role"] == "worker", "Use the assigned worker’s page to update progress.", 403)
    if "revision" in data:
        require(data["revision"] == state["revision"], "The board changed. Review the updated recommendation and try again.", 409)
    issue = None
    if action in ("assign", "reorder", "unassign", "edit", "reopen", "head", "start", "done"):
        issue = next((t for t in state["issues"] if t["id"] == data.get("id")), None)
        require(issue is not None, "Job not found.", 404)
        require(data.get("version") == issue["version"], "This job changed. Review its latest state and try again.", 409)
    if action == "create":
        guest = state["guests"].get(data.get("guest_id"))
        require(guest is not None, "Choose an occupied sample room.")
        require(data.get("category") in CATEGORIES, "Choose a supported issue type.")
        description = str(data.get("description", "")).strip()
        require(3 <= len(description) <= 500, "Describe the issue in 3–500 characters.")
        note = str(data.get("note", "")).strip()
        require(len(note) <= 500, "Keep the note under 500 characters.")
        issue = {"id": f"E-{state['next_id']}", "guest_id": guest["id"], "room": guest["room"], "floor": int(guest["room"][:-2]),
                 "description": description, "note": note, "category": data["category"], "status": "new", "worker_id": None,
                 "queue_order": 0, "reported_at": now, "version": 1}
        state["next_id"] += 1
        state["issues"].append(issue)
        event(state, actor, "Issue reported", issue)
    elif action == "edit":
        require(issue["status"] in ("new", "queued"), "A committed job cannot be changed.")
        description = str(data.get("description", "")).strip()
        note = str(data.get("note", "")).strip()
        require(3 <= len(description) <= 500 and len(note) <= 500, "Check the description and note lengths.")
        issue.update(description=description, note=note)
        event(state, actor, "Issue details updated", issue)
    elif action == "assign":
        require(issue["status"] in ("new", "queued"), "Work already committed; it cannot be reassigned.", 409)
        require("revision" in data, "Review a current recommendation before assigning.")
        options = proposal(state, issue)
        chosen = next((o for o in options if o["worker_id"] == data.get("worker_id") and o["position"] == data.get("position")), None)
        require(chosen is not None, "That recommendation changed; choose an updated option.", 409)
        snapshot(state, issue, "Before assignment")
        old_worker = issue["worker_id"]
        queue = sorted((t for t in state["issues"] if t["id"] != issue["id"] and t["worker_id"] == chosen["worker_id"] and t["status"] == "queued"), key=lambda t: t["queue_order"])
        queue.insert(chosen["position"], issue)
        for order, task in enumerate(queue):
            if task["queue_order"] != order and task is not issue:
                task["version"] += 1
            task["queue_order"] = order
        issue.update(status="queued", worker_id=chosen["worker_id"], assignment_reason=chosen["reason"], approved_by=actor["name"], approved_at=now)
        event(state, actor, "Assignment approved", issue, worker=chosen["name"], previous_worker=old_worker,
              position=chosen["position"] + 1, alternatives=options)
    elif action == "unassign":
        require(issue["status"] == "queued", "Only upcoming jobs can return to the pool.", 409)
        issue.update(status="new", worker_id=None)
        event(state, actor, "Returned to unassigned pool", issue)
    elif action == "reorder":
        raise RuleError("Upcoming stacks now follow live priority automatically.", 409)
    elif action in ("head", "start", "done"):
        require(issue["worker_id"] == actor["id"], "This job is assigned to another worker.", 403)
        if action == "head":
            require(issue["status"] == "queued", "This job is no longer queued.", 409)
            require(not any(t["worker_id"] == actor["id"] and t["status"] in ACTIVE for t in state["issues"]), "Finish your current job first.", 409)
            queue = sorted((t for t in state["issues"] if t["worker_id"] == actor["id"] and t["status"] == "queued"), key=lambda t: t["queue_order"])
            require(queue and queue[0]["id"] == issue["id"], "The queue changed. Head to the first approved job.", 409)
            issue.update(status="on_way", headed_at=now)
            event(state, actor, "Heading to job", issue)
        elif action == "start":
            require(issue["status"] == "on_way", "Tap Head there before starting.", 409)
            issue.update(status="working", started_at=now)
            next(w for w in state["workers"] if w["id"] == actor["id"])["floor"] = issue["floor"]
            event(state, actor, "Work started", issue)
        else:
            require(issue["status"] == "working", "Only a job in progress can be completed.", 409)
            snapshot(state, issue, "Before completion")
            issue.update(status="closed", closed_at=now)
            event(state, actor, "Job completed", issue)
    elif action == "reopen":
        require(issue["status"] == "closed", "Only a completed job can reopen.")
        reason = str(data.get("reason", "")).strip()
        require(3 <= len(reason) <= 500, "Record the guest’s feedback to reopen this job.")
        snapshot(state, issue, "Before reopening")
        issue.setdefault("closures", []).append(issue["closed_at"])
        issue["paused_seconds"] = issue.get("paused_seconds", 0) + max(0, now - issue["closed_at"])
        issue.update(status="new", worker_id=None, closed_at=None)
        event(state, actor, "Guest reported unresolved issue", issue, reason=reason)
    elif action == "advance":
        state["offset"] += 15 * 60
        event(state, actor, "Demo clock advanced 15 minutes")
    elif action == "offer":
        gid, kind = data.get("guest_id"), data.get("kind")
        require(gid in state["guests"] and kind in OFFERS, "Invalid recovery option.")
        require("revision" in data, "Review a current recovery recommendation.")
        recovery = recoveries(state, gid)
        require(recovery["trigger"] and any(o["kind"] == kind for o in recovery["options"]), "Recovery recommendation changed. Review the latest stay details.", 409)
        existing = [o for o in state["offers"] if o["guest_id"] == gid and o["status"] != "declined"]
        policy = state["policy"]
        require(len(existing) < policy["max_offers_per_stay"], "Demo policy limit reached for this stay.")
        require(sum(OFFERS[o["kind"]]["cost"] for o in existing) + OFFERS[kind]["cost"] <= policy["max_cost_per_stay"], "Demo recovery budget reached.")
        require(sum(OFFERS[o["kind"]]["points"] for o in existing) + OFFERS[kind]["points"] <= policy["max_points_per_stay"], "Demo points limit reached.")
        state["offers"].append({"id": secrets.token_hex(6), "guest_id": gid, "kind": kind, "status": "approved", "at": now,
                                "loss_at_offer": stay_estimate(state, gid)["loss"], "reason": recovery["reason"], "approved_by": actor["name"],
                                "prediction_before": stay_estimate(state, gid), "model": VERSION})
        event(state, actor, "Recovery approved", guest_id=gid, kind=kind)
    elif action == "offer_status":
        offer = next((o for o in state["offers"] if o["id"] == data.get("offer_id")), None)
        require(offer is not None, "Offer not found.")
        allowed = {"approved": ("offered",), "offered": ("accepted", "declined"), "accepted": ("fulfilled",)}
        status = data.get("status")
        require(status in allowed.get(offer["status"], ()), "This offer has already changed.", 409)
        offer["status"] = status
        offer[status + "_at"] = now
        event(state, actor, f"Recovery {status}", guest_id=offer["guest_id"], kind=offer["kind"])
    elif action == "outcome":
        gid = data.get("guest_id")
        require(gid in state["guests"], "Stay not found.")
        require(not any(t["guest_id"] == gid and t["status"] not in ("closed", "cancelled") for t in state["issues"]), "Resolve this stay’s open issues before recording an outcome.")
        rating = data.get("rating")
        require(isinstance(rating, (int, float)) and 1 <= rating <= 5, "Choose a rating from 1 to 5.")
        sentiment = data.get("sentiment")
        require(sentiment in ("Positive", "Mixed", "Negative"), "Choose the review sentiment.")
        review = str(data.get("review", "")).strip()
        require(len(review) <= 2000, "Keep the review under 2,000 characters.")
        require(not any(o["guest_id"] == gid for o in state["outcomes"]), "An outcome has already been recorded for this stay.", 409)
        state["outcomes"].append({"guest_id": gid, "at": now, "rating": rating, "sentiment": sentiment, "review": review,
                                  "expected_before_outcome": stay_estimate(state, gid), "model": VERSION})
        event(state, actor, "Stay outcome recorded", guest_id=gid)
    if issue and action != "create":
        issue["version"] += 1
    rebalance_queues(state)
    state["revision"] += 1
    return {"id": issue["id"] if issue else None}


class Store:
    def __init__(self, path):
        self.path = str(path)
        self.lock = threading.RLock()
        with self.connect() as db:
            db.execute("CREATE TABLE IF NOT EXISTS app_state (id INTEGER PRIMARY KEY CHECK(id=1), data TEXT NOT NULL)")
            db.execute("INSERT OR IGNORE INTO app_state VALUES (1, ?)", (json.dumps(seed_state()),))

    @contextmanager
    def connect(self):
        db = sqlite3.connect(self.path, timeout=10)
        try:
            db.execute("PRAGMA journal_mode=WAL")
            with db:
                yield db
        finally:
            db.close()

    def read(self):
        with self.lock, self.connect() as db:
            db.execute("BEGIN IMMEDIATE")
            state = json.loads(db.execute("SELECT data FROM app_state WHERE id=1").fetchone()[0])
            if rebalance_queues(state):
                state["revision"] += 1
                db.execute("UPDATE app_state SET data=? WHERE id=1", (json.dumps(state),))
            return state

    def mutate(self, actor, data):
        with self.lock, self.connect() as db:
            db.execute("BEGIN IMMEDIATE")
            state = json.loads(db.execute("SELECT data FROM app_state WHERE id=1").fetchone()[0])
            result = apply_action(state, actor, data)
            db.execute("UPDATE app_state SET data=? WHERE id=1", (json.dumps(state),))
            return result



def public_scores(value):
    """Expose legacy latent satisfaction units as 0–100 Stay Score points.

    Stored model inputs stay unchanged, preserving existing scenarios and decisions.
    Actual guest review ratings are handled separately and retain their 1–5 scale.
    """
    score_fields = {"rating", "low", "high", "loss", "delay_loss", "recovery_credit",
                    "credit", "loss_at_offer", "avoidable_rating_loss", "added_harm", "cap"}
    if isinstance(value, list):
        return [public_scores(item) for item in value]
    if isinstance(value, dict):
        return {key: round(item * 20, 2) if key in score_fields and isinstance(item, (int, float))
                else public_scores(item) for key, item in value.items()}
    return value


def public_state(state, actor):
    common = {"property": state["property"], "revision": state["revision"], "now": clock(state), "actor": actor, "categories": public_scores(CATEGORIES), "model": VERSION,
              "score_metric": {"name": "Stay Score", "minimum": 0, "maximum": 100, "status": "provisional_demo"}}
    if actor["role"] == "worker":
        tasks = [t for t in state["issues"] if t["worker_id"] == actor["id"] and t["status"] != "cancelled"]
        # Workers receive operational details only, not guest profiles or recovery history.
        allowed = ("id", "room", "floor", "category", "description", "note", "status", "queue_order", "version", "closed_at", "approved_at")
        return {**common, "issues": [{k: t[k] for k in allowed if k in t} for t in tasks],
                "worker": next(w for w in state["workers"] if w["id"] == actor["id"]), "workers": state["workers"]}
    guests = {gid: {**g, "baseline": round(g["baseline"] * 20, 2), "estimate": public_scores(stay_estimate(state, gid)), "recovery": public_scores(recoveries(state, gid))} for gid, g in state["guests"].items()}
    return {**common, "issues": [{**t, "metrics": public_scores(metrics(state, t)), "review": review_priority(state, t, guests[t["guest_id"]]["recovery"]),
                                 "task_priority": task_priority(state, t, guests[t["guest_id"]]["recovery"])} for t in state["issues"]], "guests": guests,
            "workers": state["workers"], "events": state["events"][-150:], "offers": public_scores(OFFERS),
            "policy": state["policy"], "outcomes": [{**o, "expected_before_outcome": public_scores(o["expected_before_outcome"])} for o in state["outcomes"]], "property_history": state["property_history"]}


class Handler(BaseHTTPRequestHandler):
    server_version = "Eisen/1.0"

    def respond(self, status, value=None):
        body = json.dumps(value).encode() if value is not None else b""
        self.send_response(status)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Cache-Control", "no-store")
        self.send_header("X-Content-Type-Options", "nosniff")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def identity(self):
        # Demo portal context is explicit per request, so tabs never share a role.
        identity = self.headers.get("X-Eisen-Actor", "")
        if identity == "agent":
            return {"id": "agent", "name": "Hotel agent", "role": "agent"}
        worker = next((w for w in self.server.store.read()["workers"] if w["id"] == identity), None)
        require(worker is not None, "Choose a valid demo portal.", 400)
        return {"id": worker["id"], "name": worker["name"], "role": "worker", "team": worker["team"]}

    def do_GET(self):
        route = urlsplit(self.path)
        try:
            if route.path == "/api/state":
                state = public_state(self.server.store.read(), self.identity())
                if getattr(self.server, "dev_mode", False):
                    state["dev_revision"] = source_revision()
                return self.respond(200, state)
            if route.path == "/api/recommendations":
                actor = self.identity()
                require(actor["role"] == "agent", "Agent access required.", 403)
                state = self.server.store.read()
                issue_id = parse_qs(route.query).get("id", [""])[0]
                issue = next((t for t in state["issues"] if t["id"] == issue_id), None)
                require(issue is not None, "Job not found.", 404)
                require(issue["status"] in ("new", "queued"), "This worker has already committed to the job.", 409)
                return self.respond(200, {"options": public_scores(proposal(state, issue)), "revision": state["revision"], "version": issue["version"]})
            if route.path.startswith("/api/"):
                raise RuleError("Not found.", 404)
            files = {"/": "index.html", "/index.html": "index.html", "/agent.html": "agent.html", "/worker.html": "worker.html", "/agent": "agent.html", "/worker": "worker.html", "/app.js": "app.js", "/styles.css": "styles.css"}
            filename = "worker.html" if route.path.startswith("/worker/") else files.get(route.path)
            require(filename is not None, "Not found.", 404)
            body = (ROOT / filename).read_bytes()
            self.send_response(200)
            self.send_header("Content-Type", mimetypes.guess_type(filename)[0] + "; charset=utf-8")
            self.send_header("Content-Length", str(len(body)))
            self.send_header("Cache-Control", "no-cache")
            self.send_header("X-Content-Type-Options", "nosniff")
            self.send_header("Content-Security-Policy", "default-src 'self'; style-src 'self'; script-src 'self'; connect-src 'self'; img-src 'self' data:; frame-ancestors 'none'")
            self.end_headers()
            self.wfile.write(body)
        except RuleError as error:
            self.respond(error.status, {"error": str(error)})

    def do_POST(self):
        try:
            origin = self.headers.get("Origin")
            require(not origin or urlsplit(origin).netloc == self.headers.get("Host"), "Cross-origin action denied.", 403)
            require(self.headers.get("Content-Type", "").startswith("application/json"), "Use JSON.", 415)
            size = int(self.headers.get("Content-Length", "0"))
            require(0 < size <= 16384, "Invalid request size.")
            data = json.loads(self.rfile.read(size))
            require(isinstance(data, dict), "Expected an object.")
            require(self.path == "/api/action", "Not found.", 404)
            return self.respond(200, self.server.store.mutate(self.identity(), data))
        except RuleError as error:
            self.respond(error.status, {"error": str(error)})
        except (ValueError, TypeError, KeyError):
            self.respond(400, {"error": "Invalid request. Refresh and try again."})


def source_revision(python_only=False):
    extensions = {".py"} if python_only else {".py", ".html", ".js", ".css"}
    sources = [(p.name, p.stat().st_mtime_ns, p.stat().st_size)
               for p in sorted(ROOT.iterdir()) if p.suffix in extensions]
    return hashlib.sha256(repr(sources).encode()).hexdigest()[:16]


def serve_with_reload():
    """Restart Python changes; the client detects source revisions for browser reloads."""
    command = [sys.executable, str(ROOT / "server.py"),
               *[arg for arg in sys.argv[1:] if arg != "--reload"], "--dev"]
    child = None
    print("Development reload enabled: Python, HTML, JavaScript and CSS.", flush=True)
    try:
        while True:
            revision = source_revision(python_only=True)
            child = subprocess.Popen(command)
            while child.poll() is None and source_revision(python_only=True) == revision:
                time.sleep(.5)
            if child.poll() is not None:
                return child.returncode
            print("Python source changed; restarting the local server.", flush=True)
            child.terminate()
            child.wait(timeout=5)
            time.sleep(.3)
    except KeyboardInterrupt:
        return 0
    finally:
        if child is not None and child.poll() is None:
            child.terminate()
            try:
                child.wait(timeout=5)
            except subprocess.TimeoutExpired:
                child.kill()
                child.wait()


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", type=int, default=8765)
    parser.add_argument("--db", default=str(ROOT / "eisen.sqlite3"))
    parser.add_argument("--reload", action="store_true", help="Reload browser assets and restart on Python changes")
    parser.add_argument("--dev", action="store_true", help=argparse.SUPPRESS)
    args = parser.parse_args()
    if args.reload:
        return serve_with_reload()
    server = ThreadingHTTPServer((args.host, args.port), Handler)
    server.daemon_threads = True
    server.dev_mode = args.dev
    server.store = Store(args.db)
    print(f"Eisen local demo: http://{args.host}:{args.port} — agent.html / worker.html", flush=True)
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        server.server_close()


if __name__ == "__main__":
    main()
