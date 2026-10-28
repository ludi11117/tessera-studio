"""Content-conditioned preference heads; NumPy training, immutable-label semantics.

The encoder is deterministic text statistics + signed lexical hashing, NOT a
pretrained semantic model. Neural projection training is experimental and local.
"""
import hashlib
import json
import math
import re
from pathlib import Path

import numpy as np

from core import Invalid, render_variant, variant_for
from research.model import digest, sigmoid

ENCODER_VERSION = "text-statistics-hash-v1"
STAT_NAMES = ("length", "sentence_length", "line_count", "bullet_ratio", "number_density",
              "action_density", "vague_density", "hedge_density", "formal_density", "warm_density",
              "check_density", "time_density", "question_density", "exclamation_density", "code_density",
              "link_density", "paragraph_count", "negation_density")
HASH_DIM = 16
INPUT_DIM = len(STAT_NAMES) + HASH_DIM
EMBED_DIM = 8


def raw_features(text):
    text = re.sub(r"\[M\d+#\d+\]", "", text)
    size = max(1, len(text))
    lines = [line for line in text.splitlines() if line.strip()]
    sentences = [s for s in re.split(r"[。！？.!?\n]+", text) if s.strip()]
    count = lambda pattern: len(re.findall(pattern, text, re.I))
    density = lambda pattern, scale: min(1., count(pattern) * scale / size)
    values = [math.log1p(size)/math.log(3001), min(1., size/max(1,len(sentences))/100), min(1.,len(lines)/12),
              sum(bool(re.match(r"^\s*(?:[-*+] |\d+[.)、])",line)) for line in lines)/max(1,len(lines)),
              density(r"\d+",20), density(r"实现|完成|编写|检查|测试|执行|记录|建立|创建|验证|提交|确认|添加|检查|核对|build|test|check",18),
              density(r"赋能|全面|先进|优秀|提升|优化|持续|生态|高度|一流|前沿",20),
              density(r"可能|或许|建议|大概|预计|可以考虑|maybe|perhaps",24),
              density(r"您好|请您|谨|特此|恳请|敬|正式|规范|制度",24),
              density(r"一起|咱们|聊聊|谢谢|欢迎|试试|轻松|开心|你看",24),
              density(r"验收|自测|预期输出|完成标准|测试|核对|错误恢复|checklist",20),
              density(r"第[\d一二三四五六七八九十]+[天周]|阶段|小时|分钟|每天|每周",20),
              min(1.,count(r"[？?]")/4), min(1.,count(r"[！!]")/4), min(1.,count(r"`|\bdef\b|\breturn\b|\bclass\b")*8/size),
              min(1.,count(r"https?://")/2),min(1.,len(re.split(r"\n\s*\n",text))/6),
              density(r"不|无|未|别|not\b|never\b",15)]
    hashed=np.zeros(HASH_DIM)
    lexical=re.findall(r"[a-z0-9_]{2,}",text.lower())
    for run in re.findall(r"[\u4e00-\u9fff]+",text):
        lexical.extend(run[i:i+2] for i in range(max(1,len(run)-1)))
    for token in lexical:
        h=int.from_bytes(hashlib.blake2b(token.encode(),digest_size=8,person=b"intent-v1").digest(),"little")
        hashed[h%HASH_DIM]+=1 if (h//HASH_DIM)%2 else -1
    norm=np.linalg.norm(hashed)
    if norm:hashed=hashed/norm*.35
    return np.r_[np.clip(values,0,1),hashed]


class ContentEncoder:
    version=ENCODER_VERSION

    def __init__(self,task,kind,projection=None):
        self.task,self.kind=task,kind
        self.parts=[b for b in task["blocks"] if not b.get("fixed")]
        self.n=len(self.parts)
        self.edges=sorted(set([(i,i+1) for i in range(self.n-1)]+([(0,self.n-1)] if self.n>2 else []))) if kind!="content_linear" else []
        self.projection=projection
        self.cache={}
        d=INPUT_DIM if kind=="content_linear" else EMBED_DIM
        self.keys=[("unary",str(i),f"feature{j}") for i in range(self.n) for j in range(d)]
        self.keys += [("interaction",str(i),str(j),f"factor{k}") for i,j in self.edges for k in range(d)]
        self.fingerprint=digest({"version":self.version,"kind":kind,"positions":self.n,"edges":self.edges,"input_dim":INPUT_DIM,"embed_dim":d})
        self.task_context=digest({"brief":task.get("brief"),"facts":task.get("facts"),"roles":[b["title"] for b in self.parts]})

    def text_key(self,text):
        return digest({"rendered_text":text,"encoder":self.version,"hash_dimensions":HASH_DIM})

    def raw(self,combo):
        rows=[]
        for b in self.parts:
            text=render_variant(self.task,variant_for(self.task,b["id"],combo[b["id"]]))
            key=self.text_key(text)
            if key not in self.cache:self.cache[key]=raw_features(text)
            rows.append(self.cache[key])
        return np.stack(rows) if rows else np.zeros((0,INPUT_DIM))

    def latent(self,combo):
        raw=self.raw(combo)
        return raw if self.kind=="content_linear" else np.tanh(raw@self.projection.T)

    def encode(self,combo):
        z=self.latent(combo)
        return np.concatenate([z.ravel()]+[z[i]*z[j] for i,j in self.edges])

    def matrix(self,combos):
        return np.stack([self.encode(c) for c in combos]) if combos else np.zeros((0,len(self.keys)))


def fit_head(d,l2,initial=None):
    weights=np.zeros(d.shape[1]) if initial is None else initial.copy()
    if not len(weights):return weights,np.zeros((0,0)),0.
    for iteration in range(32 if len(d) else 0):
        p=sigmoid(d@weights)
        grad=d.T@(p-1)+l2*weights
        h=(d.T*(p*(1-p)))@d+np.eye(len(weights))*l2
        delta=np.linalg.solve(h,grad)
        old=np.logaddexp(0,-d@weights).sum()+l2/2*(weights@weights)
        rate=1.
        while rate>1e-6:
            proposed=weights-rate*delta
            loss=np.logaddexp(0,-d@proposed).sum()+l2/2*(proposed@proposed)
            if loss<=old+1e-12:weights=proposed;break
            rate/=2
        if np.max(np.abs(grad))<1e-8:break
    p=sigmoid(d@weights)
    h=(d.T*(p*(1-p)))@d+np.eye(len(weights))*l2
    norm=float(np.max(np.abs(d.T@(p-1)+l2*weights))) if len(d) else 0.
    return weights,h,norm


class ContentPreferenceModel:
    def __init__(self,task,kind="content_neural",l2=.5,seed=19,steps=400):
        if kind not in ("content_linear","content_frozen","content_neural"):raise Invalid("Unknown content model")
        self.task,self.kind,self.l2,self.seed,self.steps=task,kind,l2,seed,steps
        if not math.isfinite(l2) or l2<=0:raise Invalid("Prior precision must be positive")
        self.initial_projection=np.random.default_rng(seed).normal(0,.45,(EMBED_DIM,INPUT_DIM))
        self.encoder=ContentEncoder(task,kind,self.initial_projection.copy())
        self.weights=np.zeros(len(self.encoder.keys));self.n=0;self.hessian=np.eye(len(self.weights))*l2
        self.differences=np.zeros((0,len(self.weights)));self.loss_history=[];self.projection_steps=0;self.gradient_norm=0.
        self.training_hash=digest([])

    def neural_loss_grad(self,raw,winner_indices,loser_indices,projection,head):
        z=np.tanh(raw@projection.T)
        phi=np.concatenate([z.reshape(len(raw),-1)]+[z[:,i]*z[:,j] for i,j in self.encoder.edges],axis=1)
        diff=phi[winner_indices]-phi[loser_indices]
        margins=diff@head
        error=sigmoid(margins)-1
        loss=float(np.logaddexp(0,-margins).sum()+self.l2/2*(head@head)+.05/2*np.square(projection-self.initial_projection).sum())
        gh=diff.T@error+self.l2*head
        gp=np.zeros_like(phi)
        np.add.at(gp,winner_indices,error[:,None]*head)
        np.add.at(gp,loser_indices,-error[:,None]*head)
        gz=gp[:,:self.encoder.n*EMBED_DIM].reshape(z.shape).copy()
        for edge,(i,j) in enumerate(self.encoder.edges):
            offset=self.encoder.n*EMBED_DIM+edge*EMBED_DIM
            interaction_grad=gp[:,offset:offset+EMBED_DIM]
            gz[:,i]+=interaction_grad*z[:,j]
            gz[:,j]+=interaction_grad*z[:,i]
        gw=np.einsum('bnk,bnd->kd',gz*(1-z*z),raw)+.05*(projection-self.initial_projection)
        return loss,gw,gh

    def fit(self,pairs):
        self.n=len(pairs);self.training_hash=digest(pairs)
        self.encoder.projection=self.initial_projection.copy();self.weights=np.zeros(len(self.weights))
        self.loss_history=[];self.projection_steps=0
        if self.kind=="content_neural" and len(pairs)>=4:
            combos=[];index={}
            for p in pairs:
                for key in ("winner","loser"):
                    signature=tuple(sorted(p[key].items()))
                    if signature not in index:index[signature]=len(combos);combos.append(p[key])
            raw=np.stack([self.encoder.raw(c) for c in combos])
            winners=np.array([index[tuple(sorted(p['winner'].items()))] for p in pairs])
            losers=np.array([index[tuple(sorted(p['loser'].items()))] for p in pairs])
            projection=self.initial_projection.copy();head=np.random.default_rng(self.seed+1).normal(0,.02,len(self.weights))
            mw=np.zeros_like(projection);vw=mw.copy();mh=np.zeros_like(head);vh=mh.copy()
            for step in range(1,self.steps+1):
                loss,gw,gh=self.neural_loss_grad(raw,winners,losers,projection,head)
                # Fixed full-batch Adam schedule; no held-out labels or early-stop tuning.
                mw=.9*mw+.1*gw;vw=.999*vw+.001*gw*gw
                mh=.9*mh+.1*gh;vh=.999*vh+.001*gh*gh
                projection-=.018*(mw/(1-.9**step))/(np.sqrt(vw/(1-.999**step))+1e-8)
                head-=.018*(mh/(1-.9**step))/(np.sqrt(vh/(1-.999**step))+1e-8)
                if step==1 or step%40==0:self.loss_history.append({"step":step,"training_objective":loss})
            self.encoder.projection=projection;self.projection_steps=self.steps
        self.differences=np.stack([self.encoder.encode(p["winner"])-self.encoder.encode(p["loser"]) for p in pairs]) if pairs else np.zeros((0,len(self.weights)))
        self.weights,self.hessian,self.gradient_norm=fit_head(self.differences,self.l2)
        return self

    def scores(self,combos):return self.encoder.matrix(combos)@self.weights

    def probability(self,a,b):return float(sigmoid((self.encoder.encode(a)-self.encoder.encode(b))@self.weights))

    def explain(self,combo):
        phi=self.encoder.encode(combo)
        return [{"type":k[0],"key":list(k[1:]),"contribution":float(phi[i]*self.weights[i])} for i,k in enumerate(self.encoder.keys) if abs(phi[i])>1e-12]

    def unary_contribution(self,bid,vid):
        position=next((i for i,b in enumerate(self.encoder.parts) if b["id"]==bid),None)
        if position is None:return 0.
        combo={b["id"]:b["variants"][0]["id"] for b in self.task["blocks"]};combo[bid]=vid
        z=self.encoder.latent(combo)[position]
        offset=position*len(z)
        return float(z@self.weights[offset:offset+len(z)])

    def coverage(self):
        return {"observed_difference_rank":int(np.linalg.matrix_rank(self.differences)) if self.differences.size else 0,"parameter_count":len(self.weights),"note":"Content feature coverage; it does not establish semantic or cross-user generalization."}

    def metadata(self):
        return {"model_id":self.kind,"model_version":"content-pair-network-v1","feature_version":ENCODER_VERSION,"feature_hash":self.encoder.fingerprint,
                "parameter_count":len(self.weights)+(self.initial_projection.size if self.kind=="content_neural" else 0),"head_parameter_count":len(self.weights),
                "pair_count":self.n,"edges":self.encoder.edges,"reduction":"sum","l2":self.l2,"projection_prior_precision":.05,
                "optimizer":"full-batch Adam projection + Newton head" if self.kind=="content_neural" else "Newton head",
                "projection_steps":self.projection_steps,"seed":self.seed,"gradient_max_abs":self.gradient_norm,"content_conditioned":True,
                "semantic_encoder":False,"cross_user_training":False,"training_pair_hash":self.training_hash,
                "snapshot_hash":digest({"encoder":self.encoder.fingerprint,"projection":self.encoder.projection.tolist(),"head":self.weights.tolist()}),
                "uncertainty":"Laplace head conditional on fitted projection; ignores representation uncertainty; uncalibrated"}

    def save(self,folder):
        folder=Path(folder)
        if folder.exists():raise Invalid("Checkpoint directory already exists")
        folder.mkdir(parents=True)
        np.savez_compressed(folder/'weights.npz',projection=self.encoder.projection,head=self.weights,hessian=self.hessian,differences=self.differences)
        metadata={**self.metadata(),"task_context":self.encoder.task_context,"weights_sha256":hashlib.sha256((folder/'weights.npz').read_bytes()).hexdigest(),"loss_history":self.loss_history}
        (folder/'model.json').write_text(json.dumps(metadata,ensure_ascii=False,indent=2),encoding='utf-8')

    @classmethod
    def load(cls,task,folder):
        folder=Path(folder);metadata=json.loads((folder/'model.json').read_text(encoding='utf-8'))
        model=cls(task,metadata['model_id'],metadata['l2'],metadata['seed'])
        if metadata.get('feature_hash')!=model.encoder.fingerprint or metadata.get('task_context')!=model.encoder.task_context:
            raise Invalid("Checkpoint feature or task context mismatch")
        if hashlib.sha256((folder/'weights.npz').read_bytes()).hexdigest()!=metadata['weights_sha256']:raise Invalid("Checkpoint integrity failure")
        with np.load(folder/'weights.npz',allow_pickle=False) as data:
            shapes={'projection':model.encoder.projection.shape,'head':model.weights.shape,'hessian':model.hessian.shape,'differences':(metadata['pair_count'],len(model.weights))}
            if any(data[k].shape!=shape or not np.isfinite(data[k]).all() for k,shape in shapes.items()):raise Invalid("Checkpoint shape or numeric validation failed")
            model.encoder.projection=data['projection'];model.weights=data['head'];model.hessian=data['hessian'];model.differences=data['differences']
        model.n=metadata['pair_count'];model.projection_steps=metadata['projection_steps'];model.training_hash=metadata['training_pair_hash'];model.loss_history=metadata['loss_history']
        if model.metadata()['snapshot_hash']!=metadata['snapshot_hash']:raise Invalid("Checkpoint snapshot mismatch")
        return model
