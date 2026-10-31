import unittest
import test_webcraft as helpers
from core import Invalid
from store import Conflict
from webcraft.preference import analyze,context

class WebPreferenceTests(unittest.TestCase):
    setUp=helpers.WebcraftTests.setUp
    act=helpers.WebcraftTests.act
    def test_feedback_changes_scores_without_adopting_and_undo_restores(self):
        before=self.v['document'];r=self.repo.preference(self.pid,{'revision':0});self.assertEqual(6561,r['eligible']);self.assertEqual(0,r['feedback_count'])
        self.act('compare',query=r['query']['key'],winner='b');after=analyze(self.v);self.assertEqual(before,self.v['document']);self.assertEqual(1,after['feedback_count']);self.assertNotEqual(r['weights_hash'],after['weights_hash'])
        self.act('undo');self.assertEqual(0,analyze(self.v)['feedback_count'])
    def test_locks_filter_both_recommendation_and_query(self):
        self.act('protect',component='nav',field='layout',enabled=True);r=analyze(self.v);self.assertEqual(2187,r['eligible'])
        for c in [r['recommendation']['choice'],r['query']['a'],r['query']['b']]:self.assertEqual('quiet',c['nav']['layout'])
    def test_stale_and_fabricated_votes_rejected(self):
        r=analyze(self.v)
        with self.assertRaises(Invalid):self.act('compare',query='forged',winner='a')
        self.act('compare',query=r['query']['key'],winner='a')
        with self.assertRaises(Conflict):self.repo.action(self.pid,{'revision':0,'kind':'compare','query':r['query']['key'],'winner':'a'})
        self.assertNotEqual(r['query']['key'],analyze(self.v)['query']['key'])
    def test_changed_copy_archives_feedback_and_recommendation_is_valid_patch(self):
        r=analyze(self.v);self.act('compare',query=r['query']['key'],winner='b');content={**self.v['document']['components']['hero']['content'],'title':'新文案'}
        self.act('patch',patches=[{'component':'hero','field':'content','value':content}]);r=analyze(self.v);self.assertEqual(0,r['feedback_count']);self.assertEqual(1,r['archived_feedback'])

    def test_cold_start_has_no_fabricated_training_curve_or_gain(self):
        r=analyze(self.v);self.assertEqual(0,r['training']['steps']);self.assertEqual(1,len(r['training']['trace']));self.assertIsNone(r['training']['trace'][0]['objective']);self.assertEqual(0,r['recommendation']['score_gain']);self.assertEqual(6561,r['recommendation']['tied_best']);self.assertIsNone(r['last_update'])

    def test_training_trace_matches_independent_logistic_objective(self):
        import math
        from webcraft.preference import fit,vector
        q=analyze(self.v)['query'];rows=[{'winner':q['a'],'loser':q['b']}]
        weights,_,report=fit(rows,True);trace=report['trace'];self.assertAlmostEqual(math.log(2),trace[0]['objective']);self.assertEqual(list(range(0,121,10)),[p['step'] for p in trace]);self.assertLess(trace[-1]['objective'],trace[0]['objective'])
        margin=sum(w*(a-b) for w,a,b in zip(weights,vector(q['a']),vector(q['b'])))
        expected=math.log1p(math.exp(-margin))+.1*sum(w*w for w in weights)
        self.assertAlmostEqual(expected,trace[-1]['objective']);self.assertEqual(1,report['fitted_directions'])
        _,_,conflict=fit(rows+[{'winner':q['b'],'loser':q['a']}],True);self.assertEqual(2,conflict['tied_directions']);self.assertAlmostEqual(math.log(2),conflict['trace'][-1]['objective'])

    def test_contributions_sum_to_score_gain_and_feedback_effect_is_audited(self):
        before=analyze(self.v);self.act('compare',query=before['query']['key'],winner='b');after=analyze(self.v)
        rec=after['recommendation'];self.assertAlmostEqual(rec['score_gain'],sum(c['score_delta'] for c in rec['contributions']));self.assertGreater(rec['score_gain'],0)
        effect=after['last_update'];self.assertEqual(before['weights_hash'],effect['before_model_hash']);self.assertEqual(after['weights_hash'],effect['after_model_hash']);self.assertEqual(0,effect['source_revision'])
        for c in effect['recommendation_changes']:
            self.assertEqual(before['recommendation']['choice'][c['component']][c['field']],c['before']);self.assertEqual(after['recommendation']['choice'][c['component']][c['field']],c['after'])
        self.assertEqual(effect['recommendation_changes'],self.v['history'][0]['evidence']['recommendation_changes']);self.act('undo');self.assertIsNone(analyze(self.v)['last_update'])

    def test_query_difference_list_exactly_covers_actual_differences(self):
        self.act('protect',component='hero',field='palette',enabled=True);r=analyze(self.v);q=r['query'];self.assertEqual(6561-2187,r['excluded'])
        actual={(cid,f) for cid in q['a'] for f in ('layout','palette') if q['a'][cid][f]!=q['b'][cid][f]}
        self.assertEqual(actual,{(c['component'],c['field']) for c in q['differences']});self.assertNotIn(('hero','palette'),actual)
