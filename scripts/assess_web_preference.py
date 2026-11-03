"""Matched-budget test of the CURRENT website algorithm. Synthetic, zero API."""
import copy
import json
import hashlib
import random
import sys
import time
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1];sys.path.insert(0,str(ROOT))
from webcraft.model import create,IDS,LAYOUTS,PALETTES,digest
from webcraft.preference import analyze,fit,context
from research.web_study import TRACKS,POLICIES,SEEDS,bank,truth,oracle,score,paired_interval

def write(p,v):p.write_text(json.dumps(v,ensure_ascii=False,indent=2),encoding='utf-8')
def run():
    out=ROOT/'experiments/runs'/('web-preference-'+str(time.time_ns()));out.mkdir(parents=True)
    protocol={'seeds':SEEDS,'tracks':TRACKS,'policies':POLICIES,'budgets':[0,2,4,6],'warm_start':0,'fit_steps':120,'l2':.2,'query_pool':'same production builder for all policies; pool contents adapt to own feedback','space':'6561; odd seeds protect navigation layout/palette, leaving 729','heldout':'64 fixed pairs reserved from queries by prerecording pair IDs as exclusions, without exposing labels','noise':'20% fixed per unordered pair in interaction_noisy','paid_calls':0,'limitations':['Designed preferences, not real users.','Only 12 seeds per fixed track; bootstrap intervals are conditional on that track.','No model or policy tuning against this report.','Three policies and several metrics; no multiplicity correction.']}
    write(out/'protocol.json',protocol)
    sources=['webcraft/preference.py','webcraft/model.py','research/web_study.py','scripts/assess_web_preference.py'];manifest={}
    for name in sources:
        p=out/'source'/name;p.parent.mkdir(parents=True,exist_ok=True);p.write_bytes((ROOT/name).read_bytes());manifest[name]=hashlib.sha256(p.read_bytes()).hexdigest()
    write(out/'source-manifest.json',manifest);records=[];inputs=[];started=time.perf_counter()
    for track in TRACKS:
      for seed in SEEDS:
        rng=random.Random(4000+seed);doc=create({'name':'设计性实验','title':'固定展示内容','brief':'所有策略共享同一资料，不代表真实用户。','projects':'项目｜固定说明'})
        locks={k:digest(doc['components']['nav'][k.split('.')[1]]) for k in ('nav.layout','nav.palette')} if seed%2 else {}
        state={'document':doc,'locks':locks,'preferences':[]};choices=bank(doc,locks)
        coeff={cid:{f:{v:rng.gauss(0,1) for v in vals} for f,vals in [('layout',LAYOUTS),('palette',PALETTES)]} for cid in IDS}
        terms=[] if track=='additive_clean' else [{'when':[['hero','layout','quiet'],['projects','layout','compact']],'bonus':6.},{'when':[['hero','palette','ink'],['contact','palette','sage']],'bonus':5.}]
        utilities={digest(c):truth(c,coeff,terms) for c in choices};heldout=[];excluded=set()
        while len(heldout)<64:
            a,b=rng.sample(choices,2);key=digest(sorted([digest(a),digest(b)]))
            if key not in excluded:heldout.append((a,b));excluded.add(key)
        inputs.append({'track':track,'seed':seed,'document':doc,'locks':locks,'coefficients':coeff,'interactions':terms,'heldout_pairs':heldout})
        for policy in POLICIES:
            current=copy.deepcopy(state)
            for step in range(7):
                r=analyze(current,policy,seed*100+step,excluded);rows=[v for v in current['preferences'] if v['context']==context(doc)];weights,_=fit(rows)
                row={'track':track,'seed':seed,'policy':policy,'comparisons':step,'metrics':score(r['recommendation']['choice'],utilities,heldout,weights),'recommendation':r['recommendation']['choice'],'model_hash':r['weights_hash'],'feedback':copy.deepcopy(rows),'query':r['query']};records.append(row)
                if step==6:break
                q=r['query'];assert q and q['key'] not in excluded
                a,b=q['a'],q['b'];answer=oracle(seed,track,a,b,utilities[digest(a)],utilities[digest(b)])
                current['preferences'].append({'context':context(doc),'pair':q['key'],'winner':a if answer else b,'loser':b if answer else a});row['answer_a']=answer
        print(json.dumps({'track':track,'seed':seed,'completed_policies':3}),flush=True)
    summary=[];deltas=[]
    for track in TRACKS:
      for budget in (0,2,4,6):
        for policy in POLICIES:
            rows=[r for r in records if r['track']==track and r['policy']==policy and r['comparisons']==budget]
            summary.append({'track':track,'budget':budget,'policy':policy,**{k:sum(r['metrics'][k] for r in rows)/len(rows) for k in ('normalized_regret','heldout_pair_agreement','optimal_hit')}})
        for baseline in ('random','entropy'):
            lookup={(r['seed'],r['policy']):r['metrics']['normalized_regret'] for r in records if r['track']==track and r['comparisons']==budget}
            deltas.append({'track':track,'budget':budget,'contrast':'fisher minus '+baseline,**paired_interval([lookup[s,'fisher']-lookup[s,baseline] for s in SEEDS])})
    report={'type':'designed_website_preferences_not_user_study','protocol':protocol,'summary':summary,'paired_differences':deltas,'seconds':time.perf_counter()-started,'source_manifest':manifest}
    for name,v in [('inputs.json',inputs),('trajectory.json',records),('report.json',report)]:write(out/name,v)
    write(ROOT/'experiments/web-preference-latest.json',{'folder':str(out)});write(ROOT/'research/results/web-preference-v1.json',report)
    print(json.dumps({'folder':str(out),'final':[r for r in summary if r['budget']==6]},ensure_ascii=False),flush=True)
if __name__=='__main__':run()
