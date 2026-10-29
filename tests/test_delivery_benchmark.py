import copy
import tempfile
import unittest
from pathlib import Path
from research.delivery_benchmark import load_tasks,build_plan,empty_records,assess,digest,evidence

class DeliveryBenchmarkTests(unittest.TestCase):
    def setUp(self):
        self.tasks=load_tasks(Path(__file__).resolve().parents[1]/'research/fixtures/delivery_tasks.json');self.plan=build_plan(self.tasks);self.log=empty_records(self.plan)
    def test_empty_study_remains_pending_not_zero_success(self):
        r=assess(self.plan,self.log);self.assertEqual('pending',r['status']);self.assertEqual(0,r['complete_pairs']);self.assertIsNone(r['paired_arm_means']);self.assertEqual(20,r['planned_pairs'])
    def test_assignment_is_balanced_and_materials_match(self):
        for pid in {a['participant_id'] for a in self.plan['assignments']}:
            rows=[a for a in self.plan['assignments'] if a['participant_id']==pid and a['arm']=='tessera'];self.assertEqual({1,2},{r['order'] for r in rows})
        changed=copy.deepcopy(self.log);changed['records'][0]['materials_hash']='other'
        with self.assertRaises(ValueError):assess(self.plan,changed)
    def test_rejects_forged_metrics_duplicate_trial_and_plan_change(self):
        for mutate in [lambda r:r['records'][0].update(success_rate=1),lambda r:r['records'].append(r['records'][0]),lambda r:r.update(plan_hash='wrong')]:
            log=copy.deepcopy(self.log);mutate(log)
            with self.assertRaises(ValueError):assess(self.plan,log)
    def test_evidence_identity_and_path_boundary(self):
        root=Path('D:/CodexWork/temp/tessera-delivery-tests') if __import__('os').name=='nt' else Path(tempfile.gettempdir());root.mkdir(parents=True,exist_ok=True)
        with tempfile.TemporaryDirectory(dir=root) as tmp:
            p=Path(tmp)/'artifact.txt';p.write_text('evidence',encoding='utf-8');sha=__import__('hashlib').sha256(p.read_bytes()).hexdigest();self.assertTrue(evidence({'path':p.name,'sha256':sha},tmp))
            for ref in [{'path':'../outside','sha256':sha},{'path':p.name,'sha256':'wrong'}]:
                with self.assertRaises(ValueError):evidence(ref,tmp)
