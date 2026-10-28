import copy
import importlib.util
import json
import tempfile
import unittest
from pathlib import Path

from core import Invalid, fit
from research.dataset import build_dataset
from store import Store

HAS_NUMPY = importlib.util.find_spec("numpy") is not None
ROOT = Path(__file__).resolve().parents[1]


class DatasetTests(unittest.TestCase):
    def setUp(self):
        folder = Path("D:/CodexWork/temp/intent-workbench-research-tests")
        folder.mkdir(parents=True, exist_ok=True)
        self.temp = tempfile.TemporaryDirectory(dir=folder)
        self.addCleanup(self.temp.cleanup)
        self.store = Store(Path(self.temp.name)/"qa.sqlite3")
        self.sid = self.store.sessions()[0]["id"]

    def action(self, kind, **extras):
        return self.store.action(self.sid, {"kind":kind,"revision":self.store.view(self.sid)["revision"],**extras})

    def test_dataset_old_edits_retractions_and_provenance(self):
        offer = self.store.offer(self.sid, 0)
        self.action("compare", offer=offer["id"], choice="a")
        original = self.store.view(self.sid)["text"]
        blocks = copy.deepcopy(self.store.view(self.sid)["task"]["blocks"])
        bid = offer["block"]
        for b in blocks:
            if b["id"] == bid:
                for v in b["variants"]:
                    if v["id"] == offer["a"][bid]:
                        v["template"] += " （编辑后的新措辞）"
        self.action("edit", blocks=blocks)
        q = self.store.offer(self.sid, self.store.view(self.sid)["revision"])
        self.action("compare", offer=q["id"], choice="b")
        before_undo,_=build_dataset(self.store.audit(self.sid))
        self.assertEqual(2,len(before_undo))
        self.assertEqual(before_undo[0]["task_hash"],before_undo[1]["task_hash"])
        self.assertNotEqual(before_undo[0]["pair_text_hash"],before_undo[1]["pair_text_hash"])
        self.action("undo")
        audit=self.store.audit(self.sid)
        rows,manifest=build_dataset(audit)
        self.assertEqual(1,len(rows))
        self.assertEqual(original,rows[0]["texts"]["a"])
        self.assertEqual(1,len(manifest["excluded"]))
        self.assertEqual(0,manifest["participant_count"])
        self.assertEqual("unclassified",rows[0]["data_origin"])
        # Genuine old events remain readable; origin is not retroactively guessed.
        legacy=copy.deepcopy(audit);legacy["schema_version"]=1
        for e in legacy["events"]:
            if e["kind"]=="comparison_exposure":e["payload"].pop("snapshot",None)
        old,_=build_dataset(legacy)
        self.assertEqual("unclassified_legacy",old[0]["data_origin"])
        forged=copy.deepcopy(audit)
        forged["events"]=[e for e in forged["events"] if e["kind"]!="comparison_exposure"]
        with self.assertRaises(Invalid):build_dataset(forged)
        forged=copy.deepcopy(audit)
        for e in forged["events"]:
            if e["kind"]=="comparison_exposure":e["payload"]["snapshot"]["texts"]["a"]="伪造的文字"
        with self.assertRaises(Invalid):build_dataset(forged)


@unittest.skipUnless(HAS_NUMPY,"Optional research environment is not installed")
class ResearchTests(unittest.TestCase):
    setUp = DatasetTests.setUp
    action = DatasetTests.action

    def test_legacy_equivalence_and_interaction_reversal_coverage(self):
        from research.experiment import counterexample, task_fixture
        from research.model import PreferenceModel
        task=task_fixture(3)
        q=self.store.offer(self.sid,0)
        task=self.store.view(self.sid)["task"]
        pairs=[{"winner":q["a"],"loser":q["b"]}]
        model=PreferenceModel(task,"legacy").fit(pairs)
        self.assertEqual(fit(task,pairs),model.weights.tolist())
        example=counterexample()
        full={r["model"]:r for r in example["rows"] if r["coverage"]=="all_contexts"}
        self.assertEqual(2,full["interaction"]["reversal_correct"])
        self.assertLess(full["additive"]["reversal_correct"],2)
        sparse=next(r for r in example["rows"] if r["coverage"]=="single_context" and r["model"]=="interaction")
        self.assertLess(sparse["reversal_correct"],2)

    def test_kg_fantasies_do_not_mutate_labels_and_seeded_replay(self):
        from research.experiment import run_one, semantic_payload
        config=json.loads((ROOT/"research/configs/benchmark-v1.json").read_text())
        config["budgets"]=[0,2,4]
        arm=next(a for a in config["arms"] if a["id"]=="interaction_kg")
        scenario=next(s for s in config["scenarios"] if s["id"]=="strong_interaction")
        a,l=run_one(config,scenario,arm,101)
        b,m=run_one(config,scenario,arm,101)
        self.assertEqual(semantic_payload(a,l),semantic_payload(b,m))
        self.assertEqual(4,len(l))
        self.assertEqual(0,sum(r["constraint_violations"] for r in a))
        self.assertTrue(all(r["planning"]["negative_kg_count"]==0 for r in l))
        self.assertTrue(all(r["gradient_max_abs"]<1e-6 for r in a))

    def test_diagnostic_evaluate_only_budget_locks_and_traceability(self):
        first=self.store.view(self.sid)["task"]["blocks"][0]["id"]
        self.action("lock",block=first)
        base={"model":"interaction","policy":"random","context_mode":"mixed","budget":4,"seed":11,"evaluate_only":True,"data_origin":"development_test","participant_id":"P_TEST"}
        q=None
        for seed in range(20):
            base["seed"]=seed
            self.action("research_config",config=base)
            view=self.store.view(self.sid)
            q=self.store.offer(self.sid,view["revision"])
            if q["alternative_context"]:break
        self.assertTrue(q["alternative_context"])
        self.assertEqual("evaluate_only",q["response_mode"])
        state=copy.deepcopy(self.store.view(self.sid)["state"])
        before_count=len([e for e in self.store.audit(self.sid)["events"] if e["kind"]=="compare"])
        self.assertEqual(0,before_count)
        for side in ("a","b"):
            self.assertEqual(state["locks"][first],q[side][first])
        self.action("compare",offer=q["id"],choice="b")
        view=self.store.view(self.sid)
        self.assertEqual(state["combo"],view["state"]["combo"])
        self.assertEqual(1,view["pair_count"])
        for r in view["ranking"]:
            self.assertAlmostEqual(r["score"],sum(r["score_terms"].values()),places=4)
        rows,manifest=build_dataset(self.store.audit(self.sid))
        self.assertEqual(1,len(rows));self.assertEqual(1,manifest["participant_count"])
        self.assertEqual("development_test",rows[0]["data_origin"])
        self.assertEqual(q["context"],rows[0]["comparison_context"])
        self.action("undo")
        self.assertEqual(0,self.store.view(self.sid)["pair_count"])
        base["budget"]=0
        self.action("research_config",config=base)
        self.assertIsNone(self.store.offer(self.sid,self.store.view(self.sid)["revision"]))
        self.assertEqual(state["combo"],self.store.view(self.sid)["state"]["combo"])


if __name__=="__main__":unittest.main(verbosity=2)
