"""Task-local pairwise logistic preference and diagonal Fisher query heuristic.

Exact enumeration of the finite design space; no semantic or calibrated
uncertainty claim. Content snapshots isolate feedback after copy changes.
"""
import itertools
import math
from webcraft.model import IDS,LAYOUTS,PALETTES,digest
from core import Invalid

def context(doc):return digest({cid:doc['components'][cid]['content'] for cid in IDS})
def vector(choice):
    return [float(choice[cid][field]==v) for cid in IDS for field,values in [('layout',LAYOUTS),('palette',PALETTES)] for v in values]
def dot(a,b):return sum(x*y for x,y in zip(a,b))
def probability(z):return 1/(1+math.exp(-max(-30,min(30,z))))
def fit(rows):
    weights=[0.]*24;diffs=[[x-y for x,y in zip(vector(r['winner']),vector(r['loser']))] for r in rows]
    for _ in range(120):
        grad=[.2*w for w in weights]
        for d in diffs:
            error=probability(dot(weights,d))-1
            for k in range(24):grad[k]+=error*d[k]/max(1,len(diffs))
        weights=[w-.3*g for w,g in zip(weights,grad)]
    fisher=[.2]*24
    for d in diffs:
        p=probability(dot(weights,d))
        fisher=[f+p*(1-p)*v*v for f,v in zip(fisher,d)]
    return weights,fisher
def patches(doc,choice):
    return [{'component':cid,'field':field,'value':choice[cid][field]} for cid in IDS for field in ('layout','palette') if doc['components'][cid][field]!=choice[cid][field]]
def analyze(state):
    doc=state['document'];ctx=context(doc);rows=[r for r in state.get('preferences',[]) if r['context']==ctx];weights,fisher=fit(rows)
    choices=[]
    for cid in IDS:
        c=doc['components'][cid];choices.append([{'layout':l,'palette':p} for l in LAYOUTS for p in PALETTES if (cid+'.layout' not in state['locks'] or l==c['layout']) and (cid+'.palette' not in state['locks'] or p==c['palette'])])
    candidates=[]
    for values in itertools.product(*choices):
        choice=dict(zip(IDS,values));v=vector(choice);delta=patches(doc,choice)
        candidates.append({'choice':choice,'features':v,'score':dot(weights,v),'changes':len(delta),'id':digest(choice)})
    ranked=sorted(candidates,key=lambda c:(-c['score'],c['changes'],c['id']))
    # Cover high scorers plus a deterministic spread across the full legal bank.
    spread=candidates[::max(1,len(candidates)//12)]
    pool=list({c['id']:c for c in ranked[:12]+spread[:12]}.values());seen={r['pair'] for r in rows};best=None
    for a,b in itertools.combinations(pool,2):
        key=digest(sorted([a['id'],b['id']]))
        if key in seen:continue
        d=[x-y for x,y in zip(a['features'],b['features'])];p=probability(a['score']-b['score']);value=p*(1-p)*sum(x*x/f for x,f in zip(d,fisher))
        if best is None or value>best[0]:best=(value,key,a,b,p)
    top=ranked[0]
    result={'context':ctx,'feedback_count':len(rows),'archived_feedback':len(state.get('preferences',[]))-len(rows),'eligible':len(candidates),'method':'pairwise-logistic-diagonal-fisher-v1','recommendation':{'choice':top['choice'],'patches':patches(doc,top['choice']),'score':top['score']},'query':None,'weights_hash':digest(weights),'note':'有限设计空间精确筛选；选题采用小样本线性模型与对角Fisher启发式，不是校准置信度或最优询问保证。'}
    if best:
        value,key,a,b,p=best;result['query']={'key':key,'a':a['choice'],'b':b['choice'],'heuristic_value':value,'probability_a':p,'pool_size':len(pool)}
    return result
def feedback(state,body):
    r=analyze(state);q=r['query']
    if not q or body.get('query')!=q['key'] or body.get('winner') not in ('a','b'):raise Invalid('比较已变化，请刷新后选择当前两个版本')
    win=body['winner'];lose='b' if win=='a' else 'a'
    rows=state.setdefault('preferences',[])
    if len(rows)>=100:raise Invalid('本项目已达100条比较上限，请撤回或新建项目')
    rows.append({'context':r['context'],'pair':q['key'],'winner':q[win],'loser':q[lose]})
    return {'query':q,'context':r['context'],'before_model_hash':r['weights_hash'],'after_model_hash':analyze(state)['weights_hash'],'explicit_feedback':True}
