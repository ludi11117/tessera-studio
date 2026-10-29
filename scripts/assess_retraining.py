"""Run the actual preference retraining loop with synthetic, paired feedback.

No paid API, no production session, no invented user outcome. See the protocol
written before fitting to each immutable experiment directory.
"""
import argparse
import copy
import csv
import hashlib
import itertools
import json
import os
from pathlib import Path
import platform
import shutil
import sys
import time

os.environ.setdefault('OPENBLAS_NUM_THREADS','1')
ROOT=Path(__file__).resolve().parents[1];sys.path.insert(0,str(ROOT))
import numpy as np
from core import enumerate_feasible,initial_state
from research.deep_preference import DeepPreferenceModel,SemanticLinearModel
from research.semantic import encoder
from research.retraining_study import POLICIES,BUDGETS,choose_query,evaluate,summarize
from scripts.assess_deep_learning import scenario,utility

PROFILES=('action_preference','warm_preference','coherent_pairs')
SEEDS=(101,211,307,401,503,601,701,809)


def write(path,value):
    path.write_text(json.dumps(value,ensure_ascii=False,indent=2),encoding='utf-8')


def run(seeds=SEEDS,steps=80):
    out=ROOT/'experiments'/'runs'/('retraining-'+str(time.time_ns()));out.mkdir(parents=True)
    protocol={'type':'synthetic_feedback_actual_retraining_not_real_user_study','profiles':list(PROFILES),'seeds':list(seeds),
        'policies':list(POLICIES),'initial_shared_comparisons':4,'additional_budgets':list(BUDGETS),'total_feedback_budgets':[4+b for b in BUDGETS],
        'candidate_bank':24,'model_training_steps_per_member':steps,'deep_members':3,'linear_control_same_feedback':True,
        'query_model':'semantic_deep for all policies; linear is a matched-feedback scoring ablation, not a separate acquisition loop',
        'oracle':'logistic utility differences, temperature 1, fixed uniform draw for each unordered candidate pair',
        'candidate_sampling':'seeded random permutation of 27 combinations, first 24, independent of synthetic truth',
        'restart':'each round trains from the same original initializations with all feedback so far, matching production fit()',
        'initialization_seeds':[19,37,73],'reasons':[],'checkpoint_budgets':list(BUDGETS),'paid_calls':0,
        'interval':'seed-cluster paired bootstrap 4000 draws, conditional on 3 fixed designed preference profiles',
        'limits':['Synthetic preferences reuse three earlier designed profiles; not new independent real-world tasks.',
                  'Four shared warm-start comparisons precede every reported additional budget.',
                  'All policies receive the same optimizer budget; deep has three members and linear one, so their FLOPs differ.',
                  'Current online candidate pool can include more options; this controlled bank has 24.',
                  'No reasons supervise training here; only overall pairwise labels.',
                  'New wording preserves designed utility labels; this is a controlled wording-transfer test, not a new-user test.']}
    write(out/'protocol.json',protocol)
    sources=['scripts/assess_retraining.py','scripts/assess_deep_learning.py','research/retraining_study.py','research/deep_preference.py','research/decision_value.py','research/semantic.py','research/content_model.py','research/model.py','core.py']
    manifest={}
    for source in sources:
        target=out/'source'/source;target.parent.mkdir(parents=True,exist_ok=True);shutil.copyfile(ROOT/source,target)
        manifest[source]=hashlib.sha256(target.read_bytes()).hexdigest()
    write(out/'source-manifest.json',manifest)
    sem=encoder();write(out/'environment.json',{'python':platform.python_version(),'numpy':np.__version__,'semantic_encoder':sem.metadata,'platform':platform.platform(),'threads':os.environ.get('OPENBLAS_NUM_THREADS')})
    records=[];started=time.perf_counter();fits=0
    for profile in PROFILES:
        for seed in seeds:
            task=scenario(profile)
            held=enumerate_feasible(task,initial_state(task));order=np.random.default_rng(seed).permutation(len(held))[:24]
            held=[held[int(i)] for i in order];bank=[{k:v.replace('new','old') for k,v in c.items()} for c in held]
            truth=np.array([utility(c,profile) for c in bank]);pairs=list(itertools.combinations(range(len(bank)),2))
            initial_indices=np.random.default_rng(seed+5000).choice(len(pairs),size=4,replace=False)
            initial_queries=[pairs[int(i)] for i in initial_indices]
            uniform=np.random.default_rng(seed+9000).random(len(pairs));draws=dict(zip(pairs,map(float,uniform)))
            def answer(pair):
                i,j=pair;canonical=tuple(sorted(pair));u=draws[canonical];p=float(1/(1+np.exp(-np.clip(truth[i]-truth[j],-40,40))))
                # Canonical common-random draw gives identical feedback when sides are reversed.
                choose_a=(u if i<j else 1-u)<p
                label={'winner':copy.deepcopy(bank[i if choose_a else j]),'loser':copy.deepcopy(bank[j if choose_a else i]),'reasons':[]}
                return label,{'pair':list(pair),'winner':i if choose_a else j,'probability_a':p,'canonical_uniform':u}
            labels=[answer(p)[0] for p in initial_queries]
            folder=out/(profile+'-'+str(seed));folder.mkdir()
            write(folder/'inputs.json',{'task':task,'candidate_bank':bank,'wording_transfer_bank':held,'truth_utility':truth.tolist(),
                'oracle_draws':[{'pair':list(p),'uniform':draws[p]} for p in pairs],'initial_queries':initial_queries,'initial_labels':labels})
            fit_start=time.perf_counter();initial=DeepPreferenceModel(task,sem).fit(labels,steps=steps);fits+=1
            initial_time=time.perf_counter()-fit_start;initial.save(folder/'initial-model')
            for policy in POLICIES:
                model=initial;history=copy.deepcopy(labels);seen={tuple(sorted(p)) for p in initial_queries};rng=np.random.default_rng(seed+13000)
                run_folder=folder/policy;run_folder.mkdir();pending=None;fit_time=initial_time;chain=[]
                for additional in range(7):
                    score_heads=model.score_heads(bank)@model.head_weights();linear=SemanticLinearModel(model)
                    predictions={'semantic_deep':{'same_wording':model.scores(bank),'new_wording':model.scores(held)},
                                 'semantic_linear':{'same_wording':linear.scores(bank),'new_wording':linear.scores(held)}}
                    row={'profile':profile,'seed':seed,'policy':policy,'additional_comparisons':additional,'total_feedback':len(history),
                         'phase':model.report['phase'],'model_snapshot':model.metadata()['snapshot_hash'],'label_hash':model.report['label_hash'],
                         'trainable_parameters_per_member':model.report['trainable_parameters_per_member'],'training_seconds':fit_time,
                         'feedback':copy.deepcopy(history),'member_scores':score_heads.tolist(),
                         'predictions':{m:{d:s.tolist() for d,s in values.items()} for m,values in predictions.items()},
                         'metrics':{m:{d:evaluate(s,truth) for d,s in values.items()} for m,values in predictions.items()},
                         'received_response':pending}
                    chain.append(row);records.append(row)
                    if additional in BUDGETS and additional:model.save(run_folder/('model-'+str(additional)))
                    if additional==6:break
                    query,forecast=choose_query(score_heads,seen,policy,rng)
                    seen.add(tuple(sorted(query)));label,pending=answer(query);history.append(label)
                    row['next_query']=list(query);row['forecast']=forecast
                    fit_start=time.perf_counter();model=DeepPreferenceModel(task,sem).fit(history,steps=steps);fits+=1;fit_time=time.perf_counter()-fit_start
                write(run_folder/'trajectory.json',chain)
            write(out/'progress.json',{'completed_profile':profile,'completed_seed':seed,'fits':fits,'elapsed_seconds':time.perf_counter()-started})
            print(json.dumps({'profile':profile,'seed':seed,'fits':fits,'elapsed_seconds':round(time.perf_counter()-started,2)}),flush=True)
    summary,differences=summarize(records)
    report={'status':'completed',**protocol,'training_fits':fits,'elapsed_seconds':time.perf_counter()-started,
            'summary':summary,'paired_policy_differences':differences,'semantic_encoder':sem.metadata}
    write(out/'report.json',report)
    write(out/'trajectory.json',records)
    with (out/'summary.csv').open('w',encoding='utf-8-sig',newline='') as f:
        fields=['policy','model','domain','additional_comparisons','total_feedback','mean','interval_low','interval_high','optimal_hit_rate','pair_agreement'];writer=csv.DictWriter(f,fieldnames=fields);writer.writeheader()
        for r in summary:writer.writerow({**{k:r[k] for k in fields if k in r},'interval_low':r['seed_cluster_bootstrap_95_percentile'][0],'interval_high':r['seed_cluster_bootstrap_95_percentile'][1]})
    write(ROOT/'experiments'/'retraining-latest.json',{'directory':str(out),'report':str(out/'report.json'),'status':'completed'})
    print(json.dumps({'report':str(out/'report.json'),'fits':fits,'final': [r for r in summary if r['additional_comparisons']==6]},ensure_ascii=False),flush=True)
    return out


if __name__=='__main__':
    p=argparse.ArgumentParser();p.add_argument('--seeds',type=int,default=8,choices=range(1,9));p.add_argument('--steps',type=int,default=80,choices=range(40,501));a=p.parse_args()
    run(SEEDS[:a.seeds],a.steps)
