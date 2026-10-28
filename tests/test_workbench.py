import copy
import http.client
import json
import os
import tempfile
import threading
import unittest
from http.server import ThreadingHTTPServer
from pathlib import Path

from core import Invalid, enumerate_feasible, features, fit, initial_state, recommendations, render, score, validate_task
from samples import SAMPLES
from server import make_handler
from store import Conflict, Store


class WorkbenchTests(unittest.TestCase):
    def setUp(self):
        root = Path(os.environ.get("INTENT_TEST_TEMP", "D:/CodexWork/temp/intent-workbench-tests"))
        root.mkdir(parents=True, exist_ok=True)
        self.temp = tempfile.TemporaryDirectory(dir=root)
        self.addCleanup(self.temp.cleanup)
        self.path = Path(self.temp.name) / "test.sqlite3"
        self.store = Store(self.path)
        self.sid = next(s["id"] for s in self.store.sessions() if s["title"] == SAMPLES[0]["title"])

    def act(self, kind, **extras):
        rev = self.store.view(self.sid)["revision"]
        return self.store.action(self.sid, {"kind": kind, "revision": rev, **extras})

    def test_examples_facts_and_combinations(self):
        for task in SAMPLES:
            validate_task(task)
            combos = enumerate_feasible(task, initial_state(task))
            self.assertEqual(81, len(combos))
            for combo in combos:
                text = render(task, combo)
                self.assertNotIn("{{", text)
                for value in task["facts"].values():
                    self.assertIn(value, text)

    def test_selection_is_not_a_pair_label(self):
        self.act("exposure")
        self.act("select", block="opening", variant="opening-1")
        self.act("apply", combo={b["id"]: b["variants"][2]["id"] for b in SAMPLES[0]["blocks"]})
        self.act("adopt")
        view = self.store.view(self.sid)
        self.assertEqual(0, view["pair_count"])
        self.assertTrue(all(w["weight"] == 0 for w in view["weights"]))

    def test_locks_hold_for_search_compare_and_invalid_apply(self):
        self.act("select", block="opening", variant="opening-1")
        self.act("lock", block="opening")
        view = self.store.view(self.sid)
        task, state = view["task"], view["state"]
        self.assertEqual(27, view["feasible_count"])
        for c in enumerate_feasible(task, state):
            self.assertEqual("opening-1", c["opening"])
        offer = self.store.offer(self.sid, view["revision"])
        self.assertNotEqual("opening", offer["block"])
        self.assertEqual("opening-1", offer["a"]["opening"])
        with self.assertRaises(Invalid):
            self.act("apply", combo={**state["combo"], "opening": "opening-2"})
        with self.assertRaises(Invalid):
            self.act("select", block="opening", variant="opening-2")
        self.assertEqual(view["revision"], self.store.view(self.sid)["revision"])
        self.act("lock", block="opening")
        self.act("select", block="opening", variant="opening-2")
        self.assertEqual("opening-2", self.store.view(self.sid)["state"]["combo"]["opening"])

    def test_real_pair_moves_ranking_and_undo_removes_it(self):
        view = self.store.view(self.sid)
        offer = self.store.offer(self.sid, view["revision"])
        self.assertEqual(offer, self.store.offer(self.sid, view["revision"]))
        self.assertEqual(1, sum(e["kind"] == "comparison_exposure" for e in self.store.audit(self.sid)["events"]))
        self.act("compare", offer=offer["id"], choice="b")
        trained = self.store.view(self.sid)
        self.assertEqual(1, trained["pair_count"])
        self.assertEqual(offer["b"], trained["state"]["combo"])
        pair = next(e["payload"] for e in self.store.audit(self.sid)["events"] if e["kind"] == "compare")
        diff = [k for k in pair["winner"] if pair["winner"][k] != pair["loser"][k]]
        self.assertEqual([offer["block"]], diff)
        weights = fit(view["task"], [pair])
        self.assertGreater(score(weights, features(view["task"], offer["b"])), score(weights, features(view["task"], offer["a"])))
        self.assertEqual(offer["b"][offer["block"]], trained["ranking"][0]["combo"][offer["block"]])
        self.act("undo")
        reverted = self.store.view(self.sid)
        self.assertEqual(0, reverted["pair_count"])
        self.assertEqual(view["state"], reverted["state"])
        self.assertTrue(all(w["weight"] == 0 for w in reverted["weights"]))

    def test_stale_duplicate_and_invalid_feedback_rejected(self):
        view = self.store.view(self.sid)
        offer = self.store.offer(self.sid, view["revision"])
        with self.assertRaises(Invalid):
            self.act("compare", offer=offer["id"], choice="invented")
        self.act("select", block="project", variant="project-1")
        with self.assertRaises(Conflict):
            self.act("compare", offer=offer["id"], choice="a")
        with self.assertRaises(Conflict):
            self.store.action(self.sid, {"kind": "lock", "block": "project", "revision": 0})
        new_offer = self.store.offer(self.sid, self.store.view(self.sid)["revision"])
        self.act("compare", offer=new_offer["id"], choice="a")
        with self.assertRaises(Conflict):
            self.act("compare", offer=new_offer["id"], choice="b")
        self.assertEqual(1, self.store.view(self.sid)["pair_count"])

    def test_infeasible_constraints_do_not_break_locks(self):
        self.act("lock", block="opening")
        original = self.store.view(self.sid)["state"]
        self.act("constraint", max_chars=1)
        view = self.store.view(self.sid)
        self.assertEqual(0, view["feasible_count"])
        self.assertEqual(original["combo"], view["state"]["combo"])
        self.assertEqual(original["locks"], view["state"]["locks"])
        self.assertIsNone(self.store.offer(self.sid, view["revision"]))
        for kind in ("adopt", "export"):
            with self.assertRaises(Invalid):
                self.act(kind)
        self.act("undo")
        self.assertEqual(27, self.store.view(self.sid)["feasible_count"])

    def test_restart_undo_stack_and_export_roundtrip(self):
        self.act("select", block="opening", variant="opening-1")
        self.act("lock", block="opening")
        offer = self.store.offer(self.sid, self.store.view(self.sid)["revision"])
        self.act("compare", offer=offer["id"], choice="b")
        self.act("adopt")
        expected = self.store.view(self.sid)
        self.store = Store(self.path)
        self.assertEqual(expected, self.store.view(self.sid))
        exported = self.act("export")
        self.assertEqual(expected["text"], Path(exported["path"]).read_text(encoding="utf-8"))
        audit = self.act("audit_export")
        data = json.loads(Path(audit["path"]).read_text(encoding="utf-8"))
        self.assertEqual(expected["state"]["final"]["text"], data["state"]["final"]["text"])
        self.act("undo")  # adoption, not export
        self.assertEqual(1, self.store.view(self.sid)["pair_count"])
        self.act("undo")  # comparison
        self.assertEqual(0, self.store.view(self.sid)["pair_count"])
        self.act("undo")  # lock
        self.assertEqual({}, self.store.view(self.sid)["state"]["locks"])
        self.act("undo")  # select
        self.assertEqual(initial_state(SAMPLES[0]), self.store.view(self.sid)["state"])

    def test_skip_and_fact_validation(self):
        offer = self.store.offer(self.sid, 0)
        self.act("skip", offer=offer["id"])
        self.assertEqual(0, self.store.view(self.sid)["pair_count"])
        self.assertNotEqual(offer["key"], self.store.offer(self.sid, 1)["key"])
        broken = copy.deepcopy(SAMPLES[0])
        broken["blocks"][0]["variants"][0]["template"] = "{{nonexistent}}"
        with self.assertRaises(Invalid):
            self.store.create(broken)
        broken["blocks"][0]["variants"][0]["template"] = "不再引用原来的事实"
        with self.assertRaises(Invalid):
            self.store.create(broken)

    def test_edit_versions_preserve_real_pair_identity_and_undo(self):
        offer = self.store.offer(self.sid, 0)
        self.act("compare", offer=offer["id"], choice="b")
        before = self.store.view(self.sid)
        blocks = copy.deepcopy(before["task"]["blocks"])
        current_id = before["state"]["combo"]["opening"]
        for v in blocks[0]["variants"]:
            if v["id"] == current_id:
                v["template"] += " 也希望听听您的看法。"
        self.act("edit", blocks=blocks)
        after = self.store.view(self.sid)
        new_id = after["state"]["combo"]["opening"]
        self.assertNotEqual(current_id, new_id)
        self.assertEqual(1, after["pair_count"])
        self.assertIn("也希望听听您的看法", after["text"])
        current_index = next(i for i, v in enumerate(after["task"]["blocks"][0]["variants"]) if v["id"] == new_id)
        self.assertEqual(0, after["weights"][current_index]["weight"])
        event = next(e for e in self.store.audit(self.sid)["events"] if e["kind"] == "compare")
        self.assertEqual(current_id, event["payload"]["winner"]["opening"])
        self.assertEqual(before["text"], render(after["task"], event["payload"]["winner"]))
        with self.assertRaises(Invalid):
            self.act("select", block="opening", variant=current_id)
        self.store = Store(self.path)
        self.assertEqual(new_id, self.store.view(self.sid)["state"]["combo"]["opening"])
        self.act("undo")
        restored = self.store.view(self.sid)
        self.assertEqual(before["text"], restored["text"])
        self.assertEqual(before["state"], restored["state"])
        self.assertEqual(1, restored["pair_count"])
        self.assertEqual(before["weights"], restored["weights"])
        self.act("undo")
        self.assertEqual(0, self.store.view(self.sid)["pair_count"])

    def test_candidate_edit_lock_guard_and_atomic_validation(self):
        self.act("lock", block="opening")
        before = self.store.view(self.sid)
        blocks = copy.deepcopy(before["task"]["blocks"])
        blocks[0]["variants"][1]["template"] += " 希望得到您的建议。"
        self.act("edit", blocks=blocks)
        after = self.store.view(self.sid)
        self.assertEqual(before["state"]["locks"], after["state"]["locks"])
        self.assertEqual(before["text"], after["text"])
        broken = copy.deepcopy(after["task"]["blocks"])
        broken[1]["variants"][0]["template"] += " 修改其他段落。"
        broken[0]["variants"][0]["template"] += " 修改锁定段落。"
        with self.assertRaises(Invalid):
            self.act("edit", blocks=broken)
        self.assertEqual(after, self.store.view(self.sid))
        broken = copy.deepcopy(after["task"]["blocks"])
        broken[1]["variants"][0]["template"] = "删除了固定事实"
        with self.assertRaises(Invalid):
            self.act("edit", blocks=broken)
        self.assertEqual(after, self.store.view(self.sid))

    def test_http_routes_security_and_conflicts(self):
        httpd = ThreadingHTTPServer(("127.0.0.1", 0), make_handler(self.store))
        thread = threading.Thread(target=httpd.serve_forever, daemon=True)
        thread.start()
        self.addCleanup(httpd.server_close)
        self.addCleanup(httpd.shutdown)
        connection = http.client.HTTPConnection("127.0.0.1", httpd.server_port)
        self.addCleanup(connection.close)

        def request(method, path, data=None, headers=None):
            connection.request(method, path, json.dumps(data) if data is not None else None, headers or {"Content-Type": "application/json"})
            response = connection.getresponse()
            return response.status, response.read()

        status, content = request("GET", "/")
        self.assertEqual(200, status)
        self.assertIn(b"<title>Tessera", content)
        status, _ = request("POST", "/api/sessions", {"clone": self.sid})
        self.assertEqual(201, status)
        self.assertTrue(all(s["source"] == "example" for s in self.store.sessions()))
        status, _ = request("POST", f"/api/sessions/{self.sid}/action", {"kind": "lock", "block": "opening", "revision": 0})
        self.assertEqual(200, status)
        status, _ = request("POST", f"/api/sessions/{self.sid}/action", {"kind": "lock", "block": "opening", "revision": 0})
        self.assertEqual(409, status)
        status, _ = request("POST", "/api/sessions", {"sample": "email"}, {"Content-Type": "application/json", "Origin": "https://other.example"})
        self.assertEqual(403, status)
        status, _ = request("GET", "/api/sessions", headers={"Host": "evil.example"})
        self.assertEqual(403, status)
        status, _ = request("GET", "/../store.py")
        self.assertEqual(404, status)


if __name__ == "__main__":
    unittest.main(verbosity=2)
