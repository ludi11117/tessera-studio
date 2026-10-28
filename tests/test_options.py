import copy
import json
import tempfile
import unittest
from pathlib import Path

from ai.approaches import normalize
from ai.choice_demo import seed
from ai.options import describe
from core import Invalid
from research.dataset import build_dataset
from store import Conflict,Store


def grid_task():
    return {'title':'组合选择开发样本','source':'example','category':'analysis','brief':'明确条件下挑选已有章节','facts':{},
            'blocks':[{'id':k,'title':k,'variants':[{'id':k+str(j),'template':char*n} for j,n in enumerate([10,30,50])]}
                      for k,char in [('left','甲'),('right','乙')]]}


class OptionTests(unittest.TestCase):
    def setUp(self):
        root=Path('D:/CodexWork/temp/intent-options-tests');root.mkdir(parents=True,exist_ok=True)
        self.temp=tempfile.TemporaryDirectory(dir=root);self.addCleanup(self.temp.cleanup)
        self.store=Store(Path(self.temp.name)/'qa.sqlite3');self.sid=self.store.create(grid_task())

    def action(self,kind,**body):
        return self.store.action(self.sid,{'revision':self.store.view(self.sid)['revision'],'kind':kind,**body})

    def contract(self,lo,hi):self.action('acceptance',contract={'length':{'min':lo,'max':hi}})

    def inspect(self,combo,anchors):
        return self.store.options(self.sid,{'revision':self.store.view(self.sid)['revision'],'combo':combo,'anchors':anchors})

    def test_anchored_completion_is_read_only_and_never_relaxes_pins(self):
        self.contract(40,40);before=self.store.audit(self.sid);before.pop('exported_at')
        r=self.inspect({'left':'left0','right':'right0'},{'left':'left1'})
        self.assertEqual(1,r['eligible']);self.assertEqual('left1',r['completion']['combo']['left'])
        self.assertTrue(r['completion']['can_apply']);self.assertEqual(0,r['paid_calls'])
        impossible=self.inspect({'left':'left0','right':'right0'},{'left':'left0','right':'right0'})
        self.assertEqual(0,impossible['eligible']);self.assertIsNone(impossible['completion'])
        self.assertEqual({'left':'left0','right':'right0'},impossible['anchors'])
        self.assertEqual(1,len(impossible['closest_without_anchors']['changes_needed']))
        after=self.store.audit(self.sid);after.pop('exported_at');self.assertEqual(before,after)

    def test_customization_is_atomic_locked_and_reversible_without_labels(self):
        self.contract(40,40);before=self.store.view(self.sid)
        self.action('customize',combo={'left':'left1','right':'right0'},anchors={'left':'left1'})
        after=self.store.view(self.sid);self.assertEqual('left1',after['state']['locks']['left']);self.assertEqual(0,after['pair_count'])
        with self.assertRaises(Invalid):self.action('customize',combo={'left':'left0','right':'right1'},anchors={})
        self.action('undo');self.assertEqual(before['state'],self.store.view(self.sid)['state'])

    def test_saved_invalid_draft_and_historical_text_are_not_silently_adopted(self):
        self.contract(40,40);before=self.store.view(self.sid)
        self.action('option_save',name='待改搭配',combo=before['state']['combo'],anchors={})
        saved=self.store.view(self.sid)['choice_board']['saved'][0]
        self.assertFalse(saved['can_apply']);self.assertTrue(saved['available'])
        self.assertEqual(before['text'],self.store.view(self.sid)['text']);self.assertEqual(0,self.store.view(self.sid)['pair_count'])
        blocks=copy.deepcopy(self.store.view(self.sid)['task']['blocks']);blocks[0]['variants'][0]['template']='新文字'
        self.action('edit',blocks=blocks)
        old=self.store.view(self.sid)['choice_board']['saved'][0]
        self.assertFalse(old['available']);self.assertEqual('甲'*10,old['sections'][0]['text'])
        self.action('undo');self.assertTrue(self.store.view(self.sid)['choice_board']['saved'][0]['available'])
        self.action('option_delete',option=saved['id']);self.assertEqual([],self.store.view(self.sid)['choice_board']['saved'])
        self.action('undo');self.assertEqual(1,len(self.store.view(self.sid)['choice_board']['saved']))

    def test_tight_constraints_allow_full_plan_preference_without_auto_adoption(self):
        self.contract(40,40);v=self.store.view(self.sid)
        offer=self.store.offer(self.sid,v['revision'])
        self.assertEqual('whole_plan',offer['comparison_kind']);self.assertEqual(2,len(offer['changed_blocks']))
        self.assertEqual('evaluate_only',offer['response_mode'])
        self.action('compare',offer=offer['id'],choice='b');after=self.store.view(self.sid)
        self.assertEqual(v['text'],after['text']);self.assertEqual(1,after['pair_count']);self.assertEqual(offer['b'],after['ranking'][0]['combo'])
        labels,_=build_dataset(self.store.audit(self.sid));self.assertEqual('whole_plan',labels[0]['comparison_kind'])
        self.assertEqual({},labels[0]['comparison_context']);self.assertIn('acceptance',labels[0]['constraint'])
        self.assertIsNone(self.store.offer(self.sid,after['revision']))
        self.action('undo');self.assertEqual(0,self.store.view(self.sid)['pair_count'])

    def test_portfolio_contains_distinct_legal_combinations_and_actual_lengths(self):
        view=self.store.view(self.sid);board=view['choice_board']
        self.assertEqual(9,board['eligible']);self.assertEqual(3,len(board['portfolio']))
        keys=[json.dumps(p['combo'],sort_keys=True) for p in board['portfolio']];self.assertEqual(3,len(set(keys)))
        for p in board['portfolio']:self.assertTrue(p['can_apply'])
        self.assertEqual([20,60,100],[p['body_characters'] for p in board['initials']])
        self.action('lock',block='left')
        for p in self.store.view(self.sid)['choice_board']['portfolio']:self.assertEqual('left0',p['combo']['left'])

    def test_user_directions_validate_and_partial_drafts_are_allowed(self):
        project=normalize(None,'project');study=normalize(None,'study');self.assertNotEqual(project,study)
        project[0]['name']='';self.assertEqual('',normalize(project,'project',draft=True)[0]['name'])
        with self.assertRaises(Invalid):normalize(project,'project')
        with self.assertRaises(Invalid):normalize([{'name':'同名','instruction':'要求'}]*3)

    def test_demo_has_real_mixed_solutions_and_is_not_counted_as_user_work(self):
        sid=seed(self.store);v=self.store.view(sid);board=v['choice_board']
        self.assertEqual('example',v['task']['source']);self.assertEqual([False]*3,[p['can_apply'] for p in board['initials']])
        self.assertEqual(3,board['eligible']);self.assertEqual(0,v['pair_count']);self.assertEqual(sid,seed(self.store))

    def test_snapshot_inspection_rejects_stale_unknown_or_extra_choices(self):
        v=self.store.view(self.sid);self.action('lock',block='left')
        with self.assertRaises(Conflict):self.store.options(self.sid,{'revision':v['revision'],'combo':v['state']['combo']})
        with self.assertRaises(Invalid):self.inspect({'left':'left0','right':'right0','extra':'x'},{})
        with self.assertRaises(Invalid):self.inspect(v['state']['combo'],{'left':'unknown'})

    def test_condition_experiment_does_not_relax_saved_contract_or_adoption(self):
        self.contract(40,40);view=self.store.view(self.sid);audit=self.store.audit(self.sid);audit.pop('exported_at')
        trial=self.store.options(self.sid,{'revision':view['revision'],'combo':view['state']['combo'],'anchors':{},'trial_contract':{'length':{'min':20,'max':100}}})
        self.assertEqual(2,trial['trial']['original_eligible']);self.assertEqual(9,trial['trial']['eligible']);self.assertTrue(trial['trial']['adoption_requires_confirmation'])
        after=self.store.audit(self.sid);after.pop('exported_at');self.assertEqual(audit,after)
        with self.assertRaises(Invalid):self.action('apply',combo=view['state']['combo'])
