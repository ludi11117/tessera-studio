import copy
import math
import unittest
from webcraft.model import create,digest
from webcraft.preference import analyze
from research.web_study import oracle,truth,paired_interval

class WebStudyTests(unittest.TestCase):
    def setUp(self):
        self.state={'document':create({'name':'实验','title':'固定内容','brief':'设计性测试','projects':'项目｜说明'}),'locks':{}}
    def test_default_policy_unchanged_and_alternatives_reproducible(self):
        a=analyze(self.state);self.assertEqual(a,analyze(self.state,'fisher',99))
        for p in ('entropy','random'):
            r=analyze(self.state,p,19);self.assertEqual(r,analyze(self.state,p,19));self.assertEqual(a['recommendation'],r['recommendation']);self.assertEqual(a['weights_hash'],r['weights_hash'])
    def test_heldout_pair_exclusion_never_adds_training_labels(self):
        original=copy.deepcopy(self.state);q=analyze(self.state)['query'];r=analyze(self.state,excluded_pairs=[q['key']]);self.assertNotEqual(q['key'],r['query']['key']);self.assertEqual(0,r['feedback_count']);self.assertEqual(original,self.state)
    def test_response_noise_is_pair_bound_and_reverses_with_order(self):
        q=analyze(self.state)['query'];a,b=q['a'],q['b']
        for seed in range(20):
            answer=oracle(seed,'interaction_noisy',a,b,2,1);self.assertEqual(answer,oracle(seed,'interaction_noisy',a,b,2,1));self.assertNotEqual(answer,oracle(seed,'interaction_noisy',b,a,1,2))
    def test_paired_bootstrap_known_constant_difference(self):
        r=paired_interval([.2]*12);self.assertAlmostEqual(.2,r['mean']);self.assertTrue(all(abs(x-.2)<1e-12 for x in r['bootstrap_95_percentile']))
    def test_additive_representation_cannot_express_cross_component_bonus(self):
        from webcraft.preference import vector
        from webcraft.model import IDS,LAYOUTS,PALETTES
        q=analyze(self.state)['recommendation']['choice'];choices=[]
        for h,p in [(False,False),(True,False),(False,True),(True,True)]:
            c=copy.deepcopy(q);c['hero']['layout']='quiet' if h else 'editorial';c['projects']['layout']='compact' if p else 'quiet';choices.append(c)
        coeff={cid:{f:{v:0 for v in vals} for f,vals in [('layout',LAYOUTS),('palette',PALETTES)]} for cid in IDS}
        terms=[{'when':[['hero','layout','quiet'],['projects','layout','compact']],'bonus':6}]
        y=[truth(c,coeff,terms) for c in choices];self.assertEqual(6,y[3]-y[1]-y[2]+y[0])
        for values in zip(*(vector(c) for c in choices)):self.assertEqual(0,values[3]-values[1]-values[2]+values[0])
