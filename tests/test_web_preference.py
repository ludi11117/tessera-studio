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
