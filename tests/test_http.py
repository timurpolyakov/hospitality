"""Exercise the real HTTP boundary with direct agent and worker portals."""
import json
import sys
import tempfile
import threading
import unittest
import urllib.error
import urllib.request
from http.server import ThreadingHTTPServer
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "demo"))
from server import Handler, Store


class QuietHandler(Handler):
    def log_message(self, *args):
        pass


class HTTPTests(unittest.TestCase):
    def setUp(self):
        self.folder = tempfile.TemporaryDirectory()
        self.http = ThreadingHTTPServer(("127.0.0.1", 0), QuietHandler)
        self.http.store = Store(Path(self.folder.name) / "http.sqlite3")
        self.thread = threading.Thread(target=self.http.serve_forever, daemon=True)
        self.thread.start()
        self.base = f"http://127.0.0.1:{self.http.server_port}"
        self.agent = self.client()
        self.worker = self.client()
        self.agent.addheaders = [("X-Eisen-Actor", "agent")]
        self.worker.addheaders = [("X-Eisen-Actor", "sara")]

    def tearDown(self):
        self.http.shutdown()
        self.http.server_close()
        self.thread.join()
        self.folder.cleanup()

    def client(self):
        return urllib.request.build_opener()

    def request(self, client, path, body=None, origin=None, actor=None):
        headers = {"Content-Type": "application/json"}
        if actor:
            headers["X-Eisen-Actor"] = actor
        if origin:
            headers["Origin"] = origin
        request = urllib.request.Request(self.base + path, data=json.dumps(body).encode() if body is not None else None, headers=headers)
        try:
            with client.open(request) as response:
                return response.status, json.loads(response.read())
        except urllib.error.HTTPError as error:
            with error:
                return error.code, json.loads(error.read())

    def test_direct_portals_dispatch_progress_refresh_and_protection(self):
        self.assertEqual(self.request(self.client(), "/api/state")[0], 400)
        for path in ("/", "/agent.html", "/worker.html", "/worker.html?worker=sara"):
            with self.client().open(self.base + path) as response:
                self.assertEqual(response.status, 200)
                self.assertIn(b"app.js", response.read())
        # One browser profile can use both portals without a shared role cookie.
        self.assertEqual(self.request(self.agent, "/api/state", actor="sara")[1]["actor"]["role"], "worker")
        self.assertEqual(self.request(self.agent, "/api/state")[1]["actor"]["role"], "agent")
        state = self.request(self.agent, "/api/state")[1]
        self.assertEqual(state["score_metric"]["name"], "Stay Score")
        self.assertEqual(state["score_metric"]["maximum"], 100)
        self.assertTrue(all(t["task_priority"]["value"] in range(1, 6) for t in state["issues"]))
        rec = self.request(self.agent, "/api/recommendations?id=E-101")[1]
        option = next(o for o in rec["options"] if o["worker_id"] == "sara")
        body = {"action":"assign", "id":"E-101", "version":rec["version"], "revision":rec["revision"],
                "worker_id":"sara", "position":option["position"]}
        self.assertEqual(self.request(self.agent,"/api/action",body)[0],200)
        self.assertEqual(self.request(self.agent,"/api/action",body)[0],409)
        worker_state=self.request(self.worker,"/api/state")[1]
        self.assertNotIn("guests",worker_state)
        queue=sorted((t for t in worker_state["issues"] if t["status"]=="queued"),key=lambda t:t["queue_order"])
        first=queue[0]
        for action in ("head","start","done"):
            self.assertEqual(self.request(self.worker,"/api/action",{"action":action,"id":first["id"],"version":first["version"]})[0],200)
            first=next(t for t in self.request(self.worker,"/api/state")[1]["issues"] if t["id"]==first["id"])
        agent_state=self.request(self.agent,"/api/state")[1]
        self.assertEqual(next(t for t in agent_state["issues"] if t["id"]==first["id"])["status"],"closed")
        self.assertEqual(self.request(self.worker,"/api/action",{"action":"advance"})[0],403)
        self.assertEqual(self.request(self.agent,"/api/action",{"action":"advance"},origin="https://untrusted.example")[0],403)
        self.assertEqual(self.request(self.agent,"/api/login",{})[0],404)
        self.assertEqual(self.request(self.agent,"/api/state")[0],200)
        self.assertEqual(self.request(self.worker,"/api/state")[0],200)



if __name__ == "__main__":
    unittest.main()
