import copy
import hashlib
import importlib.util
import tempfile
import time
import unittest
from pathlib import Path
from unittest.mock import patch

from core import Invalid,initial_state,enumerate_feasible
from store import Store,Conflict


class FixtureSemantic:
    dimension=12
    fingerprint='explicit-test-only-not-pretrained-semantics'
    metadata={'version':'synthetic-encoder-for-unit-tests','frozen':True,'dimension':12,'not_a_real_semantic_model':True}
    def encode(self,texts):
        import numpy as np
        from research.content_model import raw_features
        rows=[]
        for text in texts:
            x=raw_features(text)[:12]+np.array([int(hashlib.sha256((text+str(i)).encode()).hexdigest()[:5],16)/1048576*.03 for i in range(12)])
            rows.append(x/max(1e-12,np.linalg.norm(x)))
        return np.array(rows)


def task():
    texts=['先完成发布与搜索，再用三个样例核对输入和结果。','希望实现全面先进的平台，持续提升体验和价值。','先记录错误输入、恢复办法和验收结果，再完善流程。']
    return {'title':'本地偏好训练样本','brief':'给出能实施并检查的任务方案','source':'example','category':'project','facts':{},
            'blocks':[{'id':k,'title':k,'variants':[{'id':k+str(j),'template':v+suffix} for j,v in enumerate(texts)]} for k,suffix in [('first','先确认边界。'),('second','再完成验收。')]]}


def pairs_for(t,n=18):
    combos=enumerate_feasible(t,initial_state(t));pairs=[]
    for i,a in enumerate(combos):
        for b in combos[i+1:]:
            score=lambda c:sum(v.endswith('0')*2+v.endswith('2') for v in c.values())
            if score(a)==score(b):continue
            winner,loser=(a,b) if score(a)>score(b) else (b,a)
            pairs.append({'winner':winner,'loser':loser,'reasons':['clarity']})
    return pairs[:n]


@unittest.skipUnless(importlib.util.find_spec('numpy'),'Optional NumPy environment')
class DeepTests(unittest.TestCase):
    def setUp(self):
        import numpy as np
        from research.deep_preference import DeepEncoder,PreferenceNetwork,DeepPreferenceModel
        self.np=np;self.t=task();self.semantic=FixtureSemantic();self.Encoder=DeepEncoder;self.Net=PreferenceNetwork;self.Model=DeepPreferenceModel
        folder=Path('D:/CodexWork/temp/intent-deep-tests');folder.mkdir(parents=True,exist_ok=True)
        self.temp=tempfile.TemporaryDirectory(dir=folder);self.addCleanup(self.temp.cleanup);self.folder=Path(self.temp.name)

    def test_all_layer_backprop_matches_finite_differences(self):
        from research.deep_preference import label_arrays
        enc=self.Encoder(self.t,self.semantic);raw,w,l,mask=label_arrays(self.t,enc,pairs_for(self.t,5));net=self.Net(enc)
        _,grads=net.loss_grad(raw,w,l,mask)
        for key,indices in [('w1',[(0,0),(25,4)]),('w2',[(2,3),(20,9)]),('b1',[(3,)]),('b2',[(5,)]),('head',[(0,0),(15,1)])]:
            for index in indices:
                value=net.params[key][index];eps=1e-5;net.params[key][index]=value+eps;plus=net.loss_grad(raw,w,l,mask)[0]
                net.params[key][index]=value-eps;minus=net.loss_grad(raw,w,l,mask)[0];net.params[key][index]=value
                self.assertAlmostEqual(float(grads[key][index]),(plus-minus)/(2*eps),places=6)

    def test_trainable_depth_is_gated_and_checkpoint_roundtrips(self):
        from research.deep_preference import label_arrays
        enc=self.Encoder(self.t,self.semantic)
        for n,phase in [(2,'head_only'),(4,'last_hidden_layer'),(8,'all_preference_layers')]:
            raw,w,l,mask=label_arrays(self.t,enc,pairs_for(self.t,n));net=self.Net(enc);before=copy.deepcopy(net.params);net.fit(raw,w,l,mask,steps=40)
            self.assertEqual(phase,net.phase);self.assertLess(net.trace[-1]['training_objective'],net.trace[0]['training_objective'])
            self.assertEqual(n>=8,not self.np.array_equal(before['w1'],net.params['w1']))
            self.assertEqual(n>=4,not self.np.array_equal(before['w2'],net.params['w2']))
        model=self.Model(self.t,self.semantic).fit(pairs_for(self.t,12),steps=40);folder=self.folder/'checkpoint';model.save(folder)
        restored=self.Model.load(self.t,self.semantic,folder);combos=enumerate_feasible(self.t,initial_state(self.t))
        self.np.testing.assert_array_equal(model.scores(combos),restored.scores(combos));self.assertEqual(model.metadata()['snapshot_hash'],restored.metadata()['snapshot_hash'])
        for combo in combos[:2]:self.assertAlmostEqual(float(model.scores([combo])[0]),sum(t['contribution'] for t in model.explain(combo)),places=10)
        with (folder/'weights.npz').open('ab') as f:f.write(b'corrupt')
        with self.assertRaises(Invalid):self.Model.load(self.t,self.semantic,folder)

    def test_grouped_holdout_does_not_leak_reverse_pairs(self):
        from research.deep_preference import partition,group_key
        pairs=pairs_for(self.t,20);pairs.append({'winner':pairs[0]['loser'],'loser':pairs[0]['winner']})
        split=partition(self.t,pairs);sets={k:{group_key(self.t,pairs[j]) for j in split[k]} for k in ('train','validation','test')}
        self.assertFalse(sets['train']&sets['test']);self.assertFalse(sets['train']&sets['validation']);self.assertFalse(sets['validation']&sets['test'])
        model=self.Model(self.t,self.semantic).fit(pairs,steps=40)
        self.assertIsNotNone(model.report['heldout_deep']);self.assertIsNotNone(model.report['heldout_linear'])
        sparse=self.Model(self.t,self.semantic).fit(pairs[:3],steps=40);self.assertIsNone(sparse.report['heldout_deep'])

    def test_training_registry_retraction_and_new_text_prediction_without_new_labels(self):
        from research.deep_preference import training_hash
        store=Store(self.folder/'qa.sqlite3');sid=store.create(self.t);service=store.learning();self.addCleanup(service.close)
        def action(kind,**extra):store.action(sid,{'kind':kind,'revision':store.view(sid)['revision'],**extra})
        for _ in range(4):
            view=store.view(sid);offer=store.offer(sid,view['revision']);action('compare',offer=offer['id'],choice='a',reasons=['clarity'])
        original=store.view(sid)
        with patch('ai.learning.availability',return_value={'available':True}),patch('research.semantic.encoder',return_value=self.semantic):
            run=service.submit(sid,{'revision':original['revision'],'steps':40})
            for _ in range(400):
                current=service.public(run['id'])
                if current['status'] not in ('queued','running') and current['report'] and current['report'].get('activation')!='pending':break
                time.sleep(.01)
            self.assertEqual('completed',current['status'],current['error']);trained=store.view(sid)
            self.assertEqual('activated',current['report']['activation'],current['report'].get('activation_error'))
            self.assertEqual('semantic_deep',trained['model_config']['model_id']);self.assertEqual(4,trained['pair_count']);self.assertEqual(original['text'],trained['text'])
            action('learning_priorities',priorities={'clarity':2});self.assertEqual({'clarity':2},store.view(sid)['model_config']['prediction_priorities'])
            action('learning_activate',run=run['id'],model_kind='semantic_linear')
            self.assertEqual('semantic_linear',store.view(sid)['model_config']['model_id'])
            action('learning_activate',run=run['id'],model_kind='semantic_deep')
            decision=store.decision(sid,store.view(sid)['revision'])
            self.assertEqual(3,decision['stability']['hypotheses'])
            self.assertGreaterEqual(decision['stability']['expected_regret'],0)
            forecast=store.offer(sid,store.view(sid)['revision'])
            self.assertEqual('finite-hypothesis-regret-v1',forecast['planning']['method'])
            self.assertEqual({'a','b'},{b['response'] for b in forecast['planning']['branches']})
            self.assertEqual(4,store.view(sid)['pair_count'])
            self.assertEqual(original['text'],store.view(sid)['text'])
            with self.assertRaises(Invalid):action('learning_priorities',priorities={'effort':1})
            blocks=copy.deepcopy(store.view(sid)['task']['blocks']);blocks[0]['variants'][0]['template']+='补充一条新的核对步骤。'
            # This candidate may have old labels; its archived text remains the training source.
            action('edit',blocks=blocks);updated=store.view(sid)
            self.assertEqual(4,updated['pair_count']);self.assertEqual('semantic_deep',updated['model_config']['model_id'])
            label=next(e for e in store.audit(sid)['events'] if e['kind']=='compare')
            action('feedback_retract',target=label['id']);retracted=store.view(sid)
            self.assertEqual(3,retracted['pair_count']);self.assertTrue(retracted['learning']['stale']);self.assertNotEqual('semantic_deep',retracted['model_config'].get('model_id'))
            with self.assertRaises(Invalid):action('learning_activate',run=run['id'])
            action('undo');self.assertEqual('semantic_deep',store.view(sid)['model_config']['model_id'])

    def test_reasons_are_explicit_and_retraction_exports_exclusion(self):
        from research.dataset import build_dataset
        store=Store(self.folder/'reason.sqlite3');sid=store.create(self.t)
        offer=store.offer(sid,0)
        with self.assertRaises(Invalid):store.action(sid,{'kind':'compare','revision':0,'offer':offer['id'],'choice':'a','reasons':['invented']})
        store.action(sid,{'kind':'compare','revision':0,'offer':offer['id'],'choice':'a','reasons':['clarity'],'reason_note':'希望步骤清楚'})
        labels,_=build_dataset(store.audit(sid));self.assertEqual(['clarity'],labels[0]['reasons'])
        target=next(e['id'] for e in store.audit(sid)['events'] if e['kind']=='compare')
        store.action(sid,{'kind':'feedback_retract','revision':1,'target':target});labels,_=build_dataset(store.audit(sid));self.assertEqual([],labels)

    def test_stale_auto_activation_and_cancel_keep_manuscript_and_old_model_safe(self):
        import threading
        for cancel in (False,True):
            store=Store(self.folder/('cancel.sqlite3' if cancel else 'stale.sqlite3'));sid=store.create(self.t);service=store.learning();self.addCleanup(service.close)
            for _ in range(2):
                v=store.view(sid);offer=store.offer(sid,v['revision']);store.action(sid,{'kind':'compare','revision':v['revision'],'offer':offer['id'],'choice':'a'})
            v=store.view(sid);entered=threading.Event();release=threading.Event();base=self.semantic
            class BlockedSemantic(FixtureSemantic):
                def encode(self,texts):entered.set();release.wait(5);return base.encode(texts)
            with patch('ai.learning.availability',return_value={'available':True}),patch('research.semantic.encoder',return_value=BlockedSemantic()):
                run=service.submit(sid,{'revision':v['revision'],'steps':40});self.assertTrue(entered.wait(3))
                if cancel:service.cancel(run['id'])
                else:store.action(sid,{'kind':'option_save','revision':v['revision'],'name':'训练中保存备选','combo':v['state']['combo'],'anchors':{}})
                release.set();service.pool.shutdown(wait=True);current=service.public(run['id'])
                self.assertEqual('cancelled' if cancel else 'completed',current['status'],current['error'])
                if not cancel:self.assertEqual('inputs_changed_not_activated',current['report']['activation'])
                self.assertNotIn('learning_active',store.view(sid)['state']);self.assertEqual(v['text'],store.view(sid)['text'])
