import copy
import importlib.util
import json
import tempfile
import unittest
from pathlib import Path

from core import Invalid, initial_state
from store import Store


@unittest.skipUnless(importlib.util.find_spec('numpy'), 'Optional NumPy environment')
class ContentTests(unittest.TestCase):
    def setUp(self):
        import numpy as np
        from research.content_model import ContentPreferenceModel
        from research.content_experiment import fixture, labels_for
        self.np=np;self.Model=ContentPreferenceModel
        self.task,self.held,self.utility,self.p=fixture(31,'register_interaction')
        self.pairs=labels_for(self.task,self.p,31)[:12]

    def temporary(self):
        root=Path('D:/CodexWork/temp/intent-content-tests');root.mkdir(parents=True,exist_ok=True)
        temp=tempfile.TemporaryDirectory(dir=root);self.addCleanup(temp.cleanup)
        return Path(temp.name)

    def test_backprop_finite_differences(self):
        m=self.Model(self.held);np=self.np
        combos=[p[key] for p in self.pairs[:3] for key in ('winner','loser')]
        raw=np.stack([m.encoder.raw(c) for c in combos]);a=np.array([0,2,4]);b=np.array([1,3,5])
        w=m.initial_projection.copy();h=np.random.default_rng(8).normal(0,.3,len(m.weights))
        _,gw,gh=m.neural_loss_grad(raw,a,b,w,h)
        for matrix,gradient,indices in ((w,gw,[(0,0),(2,8),(7,33)]),(h,gh,[(0,),(25,),(47,)])):
            for idx in indices:
                old=matrix[idx];eps=1e-5
                matrix[idx]=old+eps;plus=m.neural_loss_grad(raw,a,b,w,h)[0]
                matrix[idx]=old-eps;minus=m.neural_loss_grad(raw,a,b,w,h)[0];matrix[idx]=old
                self.assertAlmostEqual(float(gradient[idx]),(plus-minus)/(2*eps),places=6)

    def test_deterministic_training_checkpoint_and_integrity(self):
        from core import enumerate_feasible
        m=self.Model(self.held).fit(self.pairs);replay=self.Model(self.held).fit(self.pairs)
        self.assertEqual(m.metadata()['snapshot_hash'],replay.metadata()['snapshot_hash'])
        self.assertEqual(400,m.projection_steps)
        self.assertLess(m.loss_history[-1]['training_objective'],m.loss_history[0]['training_objective'])
        folder=self.temporary()/'checkpoint';m.save(folder)
        loaded=self.Model.load(self.held,folder)
        combos=enumerate_feasible(self.held,initial_state(self.held))
        self.np.testing.assert_array_equal(m.scores(combos),loaded.scores(combos))
        self.assertEqual(m.coverage(),loaded.coverage())
        with self.assertRaises(Invalid):m.save(folder)
        incompatible=copy.deepcopy(self.held);incompatible['brief']='another task'
        with self.assertRaises(Invalid):self.Model.load(incompatible,folder)
        with (folder/'weights.npz').open('ab') as f:f.write(b'corruption')
        with self.assertRaises(Invalid):self.Model.load(self.held,folder)

    def test_ids_do_not_encode_content_and_rendered_fact_is_cache_key(self):
        from research.content_model import raw_features
        task=copy.deepcopy(self.held);combo=initial_state(task)['combo']
        before=self.Model(task,'content_linear').encoder.encode(combo)
        renamed=copy.deepcopy(task);other={}
        for i,b in enumerate(renamed['blocks']):
            old_bid=b['id'];b['id']=f'newblock{i}'
            for j,v in enumerate(b['variants']+b['archive']):
                old_vid=v['id'];v['id']=f'renamed{i}-{j}'
                if combo[old_bid]==old_vid:other[b['id']]=v['id']
        self.np.testing.assert_array_equal(before,self.Model(renamed,'content_linear').encoder.encode(other))
        m=self.Model(task);key=m.encoder.text_key('完成{{fact}}')
        task['facts']={'fact':'测试'};task['blocks'][0]['variants'][0]['template']='完成{{fact}}'
        first=m.encoder.raw(combo).copy();task['facts']['fact']='一起轻松聊聊'
        second=m.encoder.raw(combo)
        self.assertFalse(self.np.array_equal(first,second))
        self.assertNotEqual(key,m.encoder.text_key('完成测试'))
        self.assertTrue(self.np.isfinite(raw_features('')).all())

    def test_heldout_never_enters_training_and_sparse_network_freezes(self):
        from research.model import create_model, digest
        active={v['id'] for b in self.held['blocks'] for v in b['variants']}
        used={v for p in self.pairs for key in ('winner','loser') for v in p[key].values()}
        self.assertFalse(active&used)
        for arm in ('content_linear','content_frozen','content_neural'):
            m=create_model(self.held,arm).fit(self.pairs)
            self.assertEqual(digest(self.pairs),m.metadata()['training_pair_hash'])
            self.assertTrue(self.np.isfinite(m.scores([initial_state(self.held)['combo']])).all())
        sparse=self.Model(self.held).fit(self.pairs[:3]);self.assertEqual(0,sparse.projection_steps)
        empty=self.Model(self.held).fit([]);self.assertEqual(.5,empty.probability(self.pairs[0]['winner'],self.pairs[0]['loser']))

    def test_store_learning_edit_archive_constraints_undo_and_reopen(self):
        path=self.temporary()/'qa.sqlite3';store=Store(path);sid=store.create(self.task)
        def action(kind,**extra):return store.action(sid,{'kind':kind,'revision':store.view(sid)['revision'],**extra})
        config={'model':'content_neural','policy':'cost_kg','context_mode':'mixed','budget':8,'seed':11,'evaluate_only':True,'data_origin':'development_test'}
        action('research_config',config=config)
        original=store.view(sid)['text']
        offer=store.offer(sid,store.view(sid)['revision']);action('compare',offer=offer['id'],choice='a')
        self.assertEqual(original,store.view(sid)['text'])
        blocks=copy.deepcopy(store.view(sid)['task']['blocks']);blocks[0]['variants'][0]['template']+='完成验收。'
        action('edit',blocks=blocks)
        view=store.view(sid);self.assertEqual(1,view['pair_count']);self.assertTrue(view['task']['blocks'][0]['archive'])
        self.assertEqual('content_neural',view['model_config']['model_id'])
        bid=view['task']['blocks'][0]['id'];action('lock',block=bid)
        locked=store.view(sid)['state']['locks'][bid]
        self.assertTrue(all(r['combo'][bid]==locked for r in store.view(sid)['ranking']))
        self.assertEqual(1,Store(path).view(sid)['pair_count'])
        action('undo');action('undo');action('undo')
        self.assertEqual(0,store.view(sid)['pair_count'])
        self.assertEqual(original,store.view(sid)['text'])

    def test_revision_context_is_bounded_scoped_and_not_a_label(self):
        from ai.preference import revision_context
        from research.integration import view_model
        task=self.held;state=initial_state(task);state['research']={'model':'content_neural'}
        state['locks']['b0']=state['combo']['b0']
        ranks,_,_,metadata=view_model(task,state,self.pairs)
        view={'task':task,'state':state,'ranking':ranks,'pair_count':len(self.pairs),'model_config':metadata,'revision':9}
        ctx=revision_context(view,['b0','b1'])
        self.assertEqual(['b1'],[item['block'] for item in ctx['examples']])
        self.assertEqual('model_prediction_not_human_label',ctx['source'])
        self.assertEqual(9,ctx['base_revision'])
        self.assertTrue(all(len(item['text'])<=600 for item in ctx['examples']))
        self.assertIsNone(revision_context({**view,'pair_count':3},['b1']))
        self.assertIsNone(revision_context({**view,'research_warning':'dependency missing'},['b1']))
        self.assertIsNone(revision_context(view,['b0']))


if __name__=='__main__':unittest.main()
