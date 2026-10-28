"""Task-local two-hidden-layer preference learning with reason supervision.

The Transformer is frozen. Only explicit comparisons supervise the small network.
"""
import copy
import hashlib
import json
from pathlib import Path

import numpy as np
from core import Invalid,render_variant,variant_for
from research.content_model import raw_features
from research.model import digest,sigmoid

REASONS={'clarity':'表达更清楚','effort':'实施负担更合适','detail':'细节程度更合适','coherence':'整体搭配更协调'}
HEADS=['overall',*REASONS]
VERSION='semantic-reason-mlp-v1'


def context_hash(task):return digest({'brief':task.get('brief'),'facts':task['facts'],'blocks':[(b['id'],b['title']) for b in task['blocks'] if not b.get('fixed')]})


def pair_text(task,pair,key):
    return [{'block':b['id'],'text':render_variant(task,variant_for(task,b['id'],pair[key][b['id']]))} for b in task['blocks'] if not b.get('fixed')]


def training_hash(task,pairs):
    return digest({'context':context_hash(task),'labels':[{'winner':pair_text(task,p,'winner'),'loser':pair_text(task,p,'loser'),'reasons':p.get('reasons',[])} for p in pairs]})


def group_key(task,pair):return digest(sorted([digest(pair_text(task,pair,'winner')),digest(pair_text(task,pair,'loser'))]))


def partition(task,pairs,seed=101):
    groups={}
    for j,p in enumerate(pairs):groups.setdefault(group_key(task,p),[]).append(j)
    keys=sorted(groups);np.random.default_rng(seed).shuffle(keys)
    if len(keys)<15:return {'train':list(range(len(pairs))),'validation':[],'test':[],'groups':len(keys),'method':'all_feedback_no_heldout_claim'}
    n=max(2,len(keys)//5);test=set(keys[:n]);validation=set(keys[n:2*n])
    return {'train':[j for k in keys if k not in test|validation for j in groups[k]],
            'validation':[j for k in keys if k in validation for j in groups[k]],'test':[j for k in keys if k in test for j in groups[k]],
            'groups':len(keys),'method':'unordered_text_pair_grouped_train_validation_test'}


class DeepEncoder:
    def __init__(self,task,semantic):
        self.task=task;self.semantic=semantic;self.parts=[b for b in task['blocks'] if not b.get('fixed')]
        if not self.parts:raise Invalid('需要至少一个可定制章节才能训练')
        self.n=len(self.parts);self.edges=sorted(set([(i,i+1) for i in range(self.n-1)]+([(0,self.n-1)] if self.n>2 else [])))
        self.input_dim=semantic.dimension*2+34+6;self.context=context_hash(task)
        self.keys=[('unary','latent',str(j)) for j in range(12)]+[('interaction','latent',str(j)) for j in range(12)]
        self.goal=semantic.encode([task.get('brief','')+'\n'+'\n'.join(task['facts'].values())])[0]
        self.cache={};self.fingerprint=digest({'version':VERSION,'semantic':semantic.fingerprint,'parts':self.n,'input_dim':self.input_dim})

    def raw(self,combo):
        rows=[]
        for j,b in enumerate(self.parts):
            text=render_variant(self.task,variant_for(self.task,b['id'],combo[b['id']]));key=(j,text)
            if key not in self.cache:
                sem=self.semantic.encode([text])[0];role=np.zeros(6);role[j]=1
                self.cache[key]=np.r_[sem*3,sem*self.goal*12,raw_features(text),role]
            rows.append(self.cache[key])
        return np.stack(rows)

    def matrix(self,combos):return np.stack([self.raw(c) for c in combos]) if combos else np.empty((0,self.n,self.input_dim))

    def pool(self,z):
        unary=z.mean(1);interaction=np.mean([z[:,i]*z[:,j] for i,j in self.edges],axis=0) if self.edges else np.zeros_like(unary)
        return np.c_[unary,interaction]

    def pool_back(self,z,gradient):
        dim=z.shape[-1];result=np.broadcast_to(gradient[:,:dim,None].transpose(0,2,1)/self.n,z.shape).copy()
        for i,j in self.edges:
            g=gradient[:,dim:]/len(self.edges);result[:,i]+=g*z[:,j];result[:,j]+=g*z[:,i]
        return result


class PreferenceNetwork:
    hidden=(32,12)

    def __init__(self,encoder,seed=19):
        self.encoder=encoder;self.seed=seed;rng=np.random.default_rng(seed);a,b=self.hidden
        self.params={'w1':rng.normal(0,1/np.sqrt(encoder.input_dim),(encoder.input_dim,a)),'b1':np.zeros(a),
                     'w2':rng.normal(0,1/np.sqrt(a),(a,b)),'b2':np.zeros(b),'head':rng.normal(0,.01,(2*b,len(HEADS)))}
        self.initial=copy.deepcopy(self.params)

    def forward(self,raw):
        p=self.params;h1=np.tanh(raw@p['w1']+p['b1']);h2=np.tanh(h1@p['w2']+p['b2']);phi=self.encoder.pool(h2)
        return phi@p['head'],(h1,h2,phi)

    def loss_grad(self,raw,winner,loser,mask):
        scores,(h1,h2,phi)=self.forward(raw);margins=scores[winner]-scores[loser];n=max(1,len(winner))
        error=(sigmoid(margins)-1)*mask/n
        loss=float((np.logaddexp(0,-margins)*mask).sum()/n);gscore=np.zeros_like(scores)
        np.add.at(gscore,winner,error);np.add.at(gscore,loser,-error)
        grads={'head':phi.T@gscore};gphi=gscore@self.params['head'].T
        gz=self.encoder.pool_back(h2,gphi)*(1-h2*h2)
        grads['w2']=np.einsum('bni,bnj->ij',h1,gz);grads['b2']=gz.sum((0,1))
        gz=(gz@self.params['w2'].T)*(1-h1*h1)
        grads['w1']=np.einsum('bni,bnj->ij',raw,gz);grads['b1']=gz.sum((0,1))
        for key,value in self.params.items():
            precision=.02 if key=='head' else .005;prior=np.zeros_like(value) if key=='head' else self.initial[key]
            loss+=precision/2*float(np.square(value-prior).sum());grads[key]+=precision*(value-prior)
        return loss,grads

    def fit(self,raw,winners,losers,mask,steps=180,validation=None,progress=None):
        n=len(winners);self.phase='head_only' if n<4 else 'last_hidden_layer' if n<8 else 'all_preference_layers'
        allowed={'head'} if n<4 else {'head','w2','b2'} if n<8 else set(self.params)
        self.trainable=sum(self.params[k].size for k in allowed);mom={k:np.zeros_like(v) for k,v in self.params.items()};variance=copy.deepcopy(mom)
        self.trace=[];best=np.inf;best_params=None;best_step=0
        for step in range(1,steps+1):
            loss,grads=self.loss_grad(raw,winners,losers,mask)
            if not np.isfinite(loss) or any(not np.isfinite(g).all() for g in grads.values()):raise Invalid('训练数值异常，保留原模型')
            for k in allowed:
                g=np.clip(grads[k],-5,5);mom[k]=.9*mom[k]+.1*g;variance[k]=.999*variance[k]+.001*g*g
                self.params[k]-=.015*(mom[k]/(1-.9**step))/(np.sqrt(variance[k]/(1-.999**step))+1e-8)
            if step==1 or step%10==0 or step==steps:
                item={'step':step,'training_objective':loss}
                if validation is not None:
                    vr,vw,vl=validation;vs=self.forward(vr)[0][:,0];vloss=float(np.logaddexp(0,-(vs[vw]-vs[vl])).mean());item['validation_pair_loss']=vloss
                    if vloss<best-1e-5:best=vloss;best_params=copy.deepcopy(self.params);best_step=step
                self.trace.append(item)
                if progress:progress(step,loss)
                if validation is not None and step-best_step>=50:break
        self.steps=step;self.selected_step=best_step or step
        if best_params is not None:self.params=best_params
        return self


def label_arrays(task,encoder,pairs):
    combos=[];keys={};win=[];lose=[];mask=np.zeros((len(pairs),len(HEADS)));mask[:,0]=1
    for j,p in enumerate(pairs):
        for name,target in [('winner',win),('loser',lose)]:
            key=tuple(sorted(p[name].items()))
            if key not in keys:keys[key]=len(combos);combos.append(p[name])
            target.append(keys[key])
        for reason in p.get('reasons',[]):
            if reason in REASONS:mask[j,HEADS.index(reason)]=.35
    return encoder.matrix(combos),np.array(win,dtype=int),np.array(lose,dtype=int),mask


def pair_metrics(scores,winners,losers):
    if not len(winners):return None
    margins=scores[winners]-scores[losers]
    return {'pairs':len(winners),'accuracy':float(np.mean(np.where(np.abs(margins)<1e-10,.5,margins>0))),
            'pair_log_loss':float(np.logaddexp(0,-margins).mean()),'note':'留出比较可能复用训练候选文字，不是新措辞泛化或概率校准证明。'}


class DeepPreferenceModel:
    def __init__(self,task,semantic,members=None,priorities=None):
        self.task=task;self.encoder=DeepEncoder(task,semantic);self.members=members or [];self.priorities=priorities or {};self.report={}

    def head_weights(self):
        result=np.array([1.]+[float(self.priorities.get(k,0)) if self.report.get('reason_counts',{}).get(k,0) else 0 for k in REASONS]);return result/result.sum()

    def score_heads(self,combos):
        raw=self.encoder.matrix(combos)
        return np.stack([m.forward(raw)[0] for m in self.members]) if self.members else np.zeros((1,len(combos),len(HEADS)))

    def scores(self,combos):return self.score_heads(combos).mean(0)@self.head_weights()

    def probabilities(self,a,b):
        values=self.score_heads([a,b])@self.head_weights();return sigmoid(values[:,0]-values[:,1])

    def probability(self,a,b):return float(self.probabilities(a,b).mean())

    @property
    def weights(self):return np.mean([m.params['head'] for m in self.members],axis=0)@self.head_weights()

    def explain(self,combo):
        raw=self.encoder.matrix([combo]);terms=[]
        for j,key in enumerate(self.encoder.keys):
            value=float(np.mean([m.forward(raw)[1][2][0,j]*(m.params['head']@self.head_weights())[j] for m in self.members]))
            terms.append({'type':key[0],'key':list(key[1:]),'contribution':value})
        return terms

    def unary_contribution(self,bid,vid):
        pos=next((j for j,b in enumerate(self.encoder.parts) if b['id']==bid),None)
        if pos is None:return 0.
        combo={b['id']:b['variants'][0]['id'] for b in self.task['blocks']};combo[bid]=vid;raw=self.encoder.matrix([combo])
        return float(np.mean([m.forward(raw)[1][1][0,pos]@(m.params['head']@self.head_weights())[:12]/self.encoder.n for m in self.members]))

    def coverage(self):return {'parameter_count':self.report.get('total_parameters_per_member'),'note':'多层参数容量不等于已学会语义或已证明用户收益。'}

    def fit(self,pairs,steps=180,progress=None):
        split=partition(self.task,pairs);self.pair_hash=training_hash(self.task,pairs);self.n=len(pairs)
        train=[pairs[j] for j in split['train']];arrays=label_arrays(self.task,self.encoder,train)
        sets={k:label_arrays(self.task,self.encoder,[pairs[j] for j in split[k]]) for k in ('validation','test') if split[k]}
        validation=(sets['validation'][0],sets['validation'][1],sets['validation'][2]) if 'validation' in sets else None
        self.members=[]
        for index,seed in enumerate([19,37,73]):
            member=PreferenceNetwork(self.encoder,seed).fit(*arrays,steps=steps,validation=validation,
                        progress=(lambda step,loss:progress(index,step,loss)) if progress else None);self.members.append(member)
        # Identical semantic inputs and split for a linear Bradley-Terry control.
        raw,w,l,_=arrays;phi=self.encoder.pool(raw);head=np.zeros(phi.shape[1]);mom=np.zeros_like(head);variance=np.zeros_like(head)
        linear_trace=[];best_params=None;best=np.inf;best_step=0
        for step in range(1,steps+1):
            diff=phi[w]-phi[l];margin=diff@head;grad=diff.T@(sigmoid(margin)-1)/max(1,len(w))+.02*head
            mom=.9*mom+.1*grad;variance=.999*variance+.001*grad*grad;head-=.015*(mom/(1-.9**step))/(np.sqrt(variance/(1-.999**step))+1e-8)
            if step==1 or step%10==0 or step==steps:
                item={'step':step,'training_objective':float(np.logaddexp(0,-margin).mean()+.01*(head@head))}
                if validation:
                    vr,vw,vl=validation;vphi=self.encoder.pool(vr);vscore=vphi@head;loss=float(np.logaddexp(0,-(vscore[vw]-vscore[vl])).mean());item['validation_pair_loss']=loss
                    if loss<best-1e-5:best=loss;best_params=head.copy();best_step=step
                linear_trace.append(item)
                if validation and step-best_step>=50:break
        if best_params is not None:head=best_params
        self.linear_head=head;test=sets.get('test');test_deep=None;test_linear=None
        if test:
            tr,tw,tl,_=test;test_deep=pair_metrics(np.mean([m.forward(tr)[0][:,0] for m in self.members],axis=0),tw,tl)
            test_linear=pair_metrics(self.encoder.pool(tr)@head,tw,tl)
        self.report={'version':VERSION,'architecture':{'input':self.encoder.input_dim,'hidden':[32,12],'heads':HEADS,'document_features':'mean hidden content + adjacent/endpoint interactions'},
                     'semantic_encoder':self.encoder.semantic.metadata,'frozen_transformer':True,'pair_count':len(pairs),'partition':split,
                     'trainable_parameters_per_member':self.members[0].trainable,'total_parameters_per_member':sum(p.size for p in self.members[0].params.values()),
                     'phase':self.members[0].phase,'members':len(self.members),'epochs':[m.steps for m in self.members],'selected_epochs':[m.selected_step for m in self.members],
                     'reason_counts':{k:sum(k in p.get('reasons',[]) for p in train) for k in REASONS},
                     'curves':[m.trace for m in self.members],'linear_curve':linear_trace,'heldout_deep':test_deep,'heldout_linear':test_linear,
                     'label_hash':self.pair_hash,'evaluation_status':'heldout_comparisons' if test else 'insufficient_groups_for_heldout',
                     'note':'深层参数仅按数据量开放；训练损失下降不证明用户收益。留出测试不参与梯度或早停；语义模型和上游生成模型均未微调。'}
        return self

    def metadata(self):
        weight_hash=digest({str(j):{k:v.tolist() for k,v in m.params.items()} for j,m in enumerate(self.members)})
        return {'model_id':'semantic_deep','model_version':VERSION,'pair_count':self.n,'content_conditioned':True,'semantic_encoder':True,
                'cross_user_training':False,'training_pair_hash':self.pair_hash,'weights_hash':weight_hash,'snapshot_hash':digest({'weights':weight_hash,'priorities':self.priorities}),
                'prediction_priorities':self.priorities,
                'phase':self.report.get('phase'),'parameter_count':self.report.get('total_parameters_per_member'),'ensemble_size':len(self.members),
                'uncertainty':'ensemble initialization disagreement; uncalibrated'}

    def save(self,folder):
        folder=Path(folder)
        if folder.exists():raise Invalid('不能覆盖已有训练版本')
        folder.mkdir(parents=True);weights={f'm{j}_{k}':v for j,m in enumerate(self.members) for k,v in m.params.items()};weights['linear_head']=self.linear_head
        np.savez_compressed(folder/'weights.npz',**weights)
        info={'metadata':self.metadata(),'context_hash':self.encoder.context,'encoder_hash':self.encoder.semantic.fingerprint,'report':self.report,
              'weights_sha256':hashlib.sha256((folder/'weights.npz').read_bytes()).hexdigest()}
        (folder/'model.json').write_text(json.dumps(info,ensure_ascii=False,indent=2),'utf-8')

    @classmethod
    def load(cls,task,semantic,folder,priorities=None):
        folder=Path(folder);info=json.loads((folder/'model.json').read_text('utf-8'));model=cls(task,semantic,priorities=priorities)
        if info['context_hash']!=model.encoder.context or info['encoder_hash']!=semantic.fingerprint:raise Invalid('训练版本的任务或语义编码器不匹配')
        if hashlib.sha256((folder/'weights.npz').read_bytes()).hexdigest()!=info['weights_sha256']:raise Invalid('训练权重校验失败')
        with np.load(folder/'weights.npz',allow_pickle=False) as data:
            for j,seed in enumerate([19,37,73]):
                member=PreferenceNetwork(model.encoder,seed)
                for k,v in member.params.items():
                    value=data[f'm{j}_{k}']
                    if value.shape!=v.shape or not np.isfinite(value).all():raise Invalid('训练权重形状或数值无效')
                    member.params[k]=value.copy()
                model.members.append(member)
            model.linear_head=data['linear_head'].copy()
            if model.linear_head.shape!=(2*model.encoder.input_dim,) or not np.isfinite(model.linear_head).all():raise Invalid('语义线性对照权重形状或数值无效')
        model.report=info['report'];model.n=info['metadata']['pair_count'];model.pair_hash=info['metadata']['training_pair_hash']
        if model.metadata()['weights_hash']!=info['metadata']['weights_hash']:raise Invalid('训练版本摘要不匹配')
        return model


class SemanticLinearModel:
    """Deploy the exact semantic linear control stored by the same training run."""
    def __init__(self,base):
        self.task=base.task;self.encoder=copy.copy(base.encoder);self.report=base.report;self.weights=base.linear_head;self.n=base.n;self.pair_hash=base.pair_hash
        d=self.encoder.input_dim;self.encoder.keys=[('unary','raw',str(j)) for j in range(d)]+[('interaction','raw',str(j)) for j in range(d)]
    def scores(self,combos):return self.encoder.pool(self.encoder.matrix(combos))@self.weights
    def score_heads(self,combos):
        result=np.zeros((1,len(combos),len(HEADS)));result[0,:,0]=self.scores(combos);return result
    def head_weights(self):return np.array([1.,0,0,0,0])
    def probabilities(self,a,b):return np.array([self.probability(a,b)])
    def probability(self,a,b):return float(sigmoid(self.scores([a,b])@[1.,-1.]))
    def explain(self,combo):
        phi=self.encoder.pool(self.encoder.matrix([combo]))[0];d=self.encoder.input_dim
        return [{'type':'unary','key':['semantic_linear'],'contribution':float(phi[:d]@self.weights[:d])},
                {'type':'interaction','key':['semantic_linear'],'contribution':float(phi[d:]@self.weights[d:])}]
    def unary_contribution(self,bid,vid):
        j=next((j for j,b in enumerate(self.encoder.parts) if b['id']==bid),None)
        if j is None:return 0.
        combo={b['id']:b['variants'][0]['id'] for b in self.task['blocks']};combo[bid]=vid
        return float(self.encoder.raw(combo)[j]@self.weights[:self.encoder.input_dim]/self.encoder.n)
    def coverage(self):return {'parameter_count':len(self.weights),'note':'相同语义输入和数据划分的线性对照。'}
    def metadata(self):
        return {'model_id':'semantic_linear','model_version':VERSION,'pair_count':self.n,'content_conditioned':True,'semantic_encoder':True,'cross_user_training':False,
                'training_pair_hash':self.pair_hash,'snapshot_hash':digest({'kind':'semantic_linear','weights':self.weights.tolist()}),
                'phase':'semantic_linear','parameter_count':len(self.weights),'prediction_priorities':{},'uncertainty':'single linear model; uncalibrated'}
