"""Controlled rewrite transfer benchmark. Synthetic recipes are not human preference data.

All arms receive identical labels, budgets, immutable archives and query order.
The recipe oracle never sees model features; models never see recipe metadata.
"""
import argparse
import copy
import hashlib
import json
import platform
import shutil
import sys
import time
from pathlib import Path

import numpy as np

from core import enumerate_feasible, initial_state, validate_task
from research.model import create_model, digest, sigmoid
from research.policies import all_queries

ROOT=Path(__file__).resolve().parents[1]
ARMS=('additive','interaction','content_linear','content_frozen','content_neural')
SCENARIOS=('additive_style','register_interaction','noisy_interaction','opaque_codes_failure')
BUDGETS=(0,4,12,24,48)
# Fixed before evaluation. Dev seeds never enter headline evaluation aggregates.
DEV_SEEDS=(31,47)
EVAL_SEEDS=(101,211,307,401,503,601)
TRAIN_PHRASES=(('您好，请您遵守正式规范。','特此说明，请您按规范安排。'),
               ('一起试试，聊聊你的想法，谢谢。','欢迎一起轻松尝试，聊聊吧。'),
               ('执行步骤，编写记录，检查结果并提交。','创建记录，执行测试，核对结果。'))
TEST_PHRASES=(('谨向您说明，请您遵照制度。','恳请依照正式制度办理。'),
              ('咱们轻松试试，欢迎分享，一起开心完成。','谢谢，咱们一起试试，欢迎来玩。'),
              ('完成验证，添加记录，实现功能并确认。','建立清单，实现功能，完成自测与验收。'))
TOPICS=(('整理露营物资','安排读书活动','规划家庭收纳'),('核对库存记录','准备校园活动','建立维修档案'))


def fixture(seed,scenario):
    rng=np.random.default_rng(seed)
    task={'title':'Controlled rewrite transfer','brief':'Synthetic style preferences; not a semantic truth test',
          'facts':{},'source':'simulation','blocks':[]}
    recipes={}
    for i in range(3):
        versions=[]
        for family in range(2):
            order=rng.permutation(3)
            for j,style in enumerate(order):
                vid=f'b{i}-{family}-{j}'
                phrase=(TRAIN_PHRASES if family==0 else TEST_PHRASES)[style][(seed+i)%2]
                if scenario=='opaque_codes_failure':
                    # Hidden categories are reassigned to unseen, equally sized codes.
                    # There is deliberately no linguistic bridge to recover this rule.
                    codes=('槐序','云岫','星河') if family==0 else ('霁月','青岚','望舒')
                    phrase='按代号'+codes[j]+'处理。'
                body=TOPICS[family][i]+'。'+phrase
                versions.append({'id':vid,'template':body})
                recipes[vid]=int(style)
        task['blocks'].append({'id':f'b{i}','title':f'阶段{i+1}','variants':versions[:3],'archive':versions[3:]})
    # Oracle weights depend on synthetic style recipes, not raw_features/projection.
    gains=rng.normal(0,.35,(3,3))
    preferred=rng.integers(0,3,size=3)
    for i,style in enumerate(preferred):gains[i,style]+=2.
    def utility(combo):
        styles=[recipes[combo[f'b{i}']] for i in range(3)]
        value=sum(gains[i,s] for i,s in enumerate(styles))
        if scenario!='additive_style':
            # Explicit nonadditive coordination, independently defined in recipe space.
            value=.2*value+sum(2.2 if styles[i]==styles[j] else -1.1 for i,j in ((0,1),(1,2),(0,2)))
        return float(value)
    noise=.2 if scenario=='noisy_interaction' else 0.
    def probability(a,b):return float(noise+(1-2*noise)*sigmoid(utility(a)-utility(b)))
    validate_task(task)
    held=copy.deepcopy(task)
    for b in held['blocks']:b['variants'],b['archive']=b['archive'],b['variants']
    validate_task(held)
    return task,held,utility,probability


def labels_for(task,probability,seed):
    queries=all_queries(task,initial_state(task))
    rng=np.random.default_rng(seed+9001)
    rng.shuffle(queries)
    labels=[]
    for q in queries:
        a,b=(q['a'],q['b']) if rng.random()<probability(q['a'],q['b']) else (q['b'],q['a'])
        labels.append({'winner':a,'loser':b})
    return labels


def evaluate(model,task,utility,probability):
    queries=all_queries(task,initial_state(task))
    predictions=np.array([model.probability(q['a'],q['b']) for q in queries])
    truth=np.array([probability(q['a'],q['b']) for q in queries])
    # Expected metrics integrate label noise instead of sampling extra evaluation labels.
    p=np.clip(predictions,1e-10,1-1e-10)
    accuracy=np.where(abs(predictions-.5)<1e-10,.5,((predictions>.5)==(truth>.5)).astype(float)).mean()
    combos=enumerate_feasible(task,initial_state(task));scores=model.scores(combos)
    true_util=np.array([utility(c) for c in combos]);best=np.flatnonzero(np.isclose(scores,scores.max(),atol=1e-10,rtol=0))
    return {'direction_accuracy':float(accuracy),'expected_nll':float(-(truth*np.log(p)+(1-truth)*np.log1p(-p)).mean()),
            'probability_mse':float(np.square(predictions-truth).mean()),
            'expected_brier':float((truth*(1-p)**2+(1-truth)*p**2).mean()),
            'simple_regret_tie_average':float(true_util.max()-true_util[best].mean()),
            'query_count':len(queries),'prediction_hash':digest(predictions.round(10).tolist())}


def run(output,seeds=EVAL_SEEDS):
    output=Path(output)
    if output.exists():raise ValueError('Run directory already exists; choose a new output')
    output.mkdir(parents=True)
    config={'schema':1,'data_origin':'simulation','oracle':'hidden recipe categories, never model features',
            'arms':ARMS,'scenarios':SCENARIOS,'budgets':BUDGETS,'seeds':list(seeds),'dev_seeds':DEV_SEEDS,'evaluation_seeds':EVAL_SEEDS,
            'l2_sum':.5,'projection_seed':19,'projection_steps':400,'label_policy':'same shuffled legal local queries for all arms',
            'heldout':'all candidate IDs and surface templates new; old candidates archived; shared synthetic recipe categories',
            'tie_rule':'mean true utility over all predicted maxima; direction ties count 0.5',
            'uncertainty':'conditional head only; not calibrated','claims':'controlled transfer, not semantic understanding or human benefit'}
    (output/'config.json').write_text(json.dumps(config,ensure_ascii=False,indent=2),encoding='utf-8')
    snapshot=output/'source';snapshot.mkdir()
    sources={}
    for name in ('core.py','research/model.py','research/content_model.py','research/content_experiment.py','research/policies.py'):
        dest=snapshot/name;dest.parent.mkdir(parents=True,exist_ok=True);shutil.copyfile(ROOT/name,dest)
        sources[name]=hashlib.sha256(dest.read_bytes()).hexdigest()
    (output/'environment.json').write_text(json.dumps({'python':sys.version,'numpy':np.__version__,'platform':platform.platform(),'sources':sources},indent=2),encoding='utf-8')
    rows=[]
    with (output/'metrics.jsonl').open('w',encoding='utf-8') as metrics,(output/'traces.jsonl').open('w',encoding='utf-8') as traces:
        for scenario in SCENARIOS:
            for seed in seeds:
                task,held,utility,probability=fixture(seed,scenario);labels=labels_for(task,probability,seed)
                traces.write(json.dumps({'scenario':scenario,'seed':seed,'train_task':task,'heldout_task':held,'labels':labels},ensure_ascii=False)+'\n')
                # Fit on archived training texts while future active candidates are visible ONLY for scoring.
                # This matches an in-product edit; held-out strings/labels never enter fit().
                for arm in ARMS:
                    for budget in BUDGETS:
                        train=labels[:budget];started=time.perf_counter()
                        model=create_model(held,arm).fit(train)
                        fit_ms=(time.perf_counter()-started)*1000
                        row={'scenario':scenario,'seed':seed,'arm':arm,'budget':budget,'train_pair_hash':digest(train),
                             'seen':evaluate(model,task,utility,probability),'rewrite':evaluate(model,held,utility,probability),
                             'fit_ms':fit_ms,'model':model.metadata()}
                        rows.append(row);metrics.write(json.dumps(row,ensure_ascii=False)+'\n');metrics.flush()
                        if seed==seeds[0] and budget==max(BUDGETS) and arm.startswith('content_'):
                            model.save(output/'checkpoints'/f'{scenario}-{arm}')
                print(f'{scenario} seed={seed} complete',flush=True)
    semantic=[{k:v for k,v in row.items() if k!='fit_ms'} for row in rows]
    semantic_hash=digest(semantic)
    (output/'result.json').write_text(json.dumps({'semantic_hash':semantic_hash,'row_count':len(rows)},indent=2),encoding='utf-8')
    return rows,semantic_hash


def main():
    p=argparse.ArgumentParser(description=__doc__);p.add_argument('--output',type=Path,required=True);p.add_argument('--split',choices=('dev','evaluation'),default='evaluation')
    args=p.parse_args();rows,h=run(args.output,DEV_SEEDS if args.split=='dev' else EVAL_SEEDS)
    print(json.dumps({'rows':len(rows),'semantic_hash':h}))


if __name__=='__main__':main()
