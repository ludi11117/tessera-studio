"""Offline, text-disjoint controlled evaluation; not a real user study."""
import copy
import itertools
import json
import random
import sys
import time
from pathlib import Path

ROOT=Path(__file__).resolve().parents[1];sys.path.insert(0,str(ROOT))
import numpy as np
from core import enumerate_feasible,initial_state,fit,features,score
from research.deep_preference import DeepPreferenceModel
from research.semantic import encoder

TRAIN=[
 ['先完成一个登记和搜索闭环，用三个样例检查输入与结果。','先写全面规划与长期愿景，后续持续完善整体能力。','一起从轻松的讨论开始，先记录想法再商量下一步。'],
 ['分两步执行，记录每步输出和错误恢复办法。','构建先进高效的整体体系，全面提升项目价值。','可以先聊聊感受，再找一个容易开始的小任务。'],
 ['验收时核对实际结果，列出失败条件与复验步骤。','总结整体意义与后续展望，保持持续优化方向。','邀请伙伴一起试试，按各自习惯给些建议。']
]
HELD=[
 ['把发布与查找做成可运行的小流程，用示例逐项核验。','优先阐述宏观定位及未来蓝图，逐步丰富平台内涵。','先和同伴随意交流，收集大家愿意尝试的点子。'],
 ['按顺序落实动作，为每个动作注明产物与异常处理。','打造综合协同机制，以长期演进促进整体发展。','从一个没有压力的起点试起来，再一起调整节奏。'],
 ['对照预期输出做自测，发现问题后重复验证修复。','回顾战略价值并规划发展方向，以迭代增进品质。','请朋友参与体验，轻松说说哪里更合心意。']
]


def scenario(kind):
    blocks=[]
    for i in range(3):
        blocks.append({'id':'p'+str(i),'title':['目标','实施','验收'][i],
                       'variants':[{'id':f'new{i}-{j}','template':t} for j,t in enumerate(HELD[i])],
                       'archive':[{'id':f'old{i}-{j}','template':t} for j,t in enumerate(TRAIN[i])]})
    return {'title':'离线偏好评价 '+kind,'source':'example','category':'project','facts':{},'brief':'为学生设计可实施的小项目方案，保留用户选择的表达与实施取舍。','blocks':blocks}


def utility(combo,kind):
    ids=[int(combo['p'+str(i)].split('-')[-1]) for i in range(3)]
    if kind=='action_preference':return sum([2.,0.,.3][j] for j in ids)
    if kind=='warm_preference':return sum([.5,0.,2.][j] for j in ids)
    if kind=='coherent_pairs':return sum(a==b for a,b in zip(ids,ids[1:]))*2+.1*sum(j==0 for j in ids)
    return sum([0.,.2,.1][j] for j in ids)


def main():
    run=str(time.time_ns());out=ROOT/'experiments/runs'/('deep-semantic-'+run);out.mkdir(parents=True)
    import shutil,hashlib,importlib.metadata
    for name in ['research/deep_preference.py','research/semantic.py','scripts/assess_deep_learning.py']:
        destination=out/'source'/name;destination.parent.mkdir(parents=True,exist_ok=True);shutil.copyfile(ROOT/name,destination)
    sem=encoder();report={'type':'synthetic_controlled_evaluation_not_user_study','semantic_encoder':sem.metadata,'run':run,'paid_calls':0,'results':[]}
    for kind in ['action_preference','warm_preference','coherent_pairs']:
        for seed in [101,211,307]:
            task=scenario(kind);held=enumerate_feasible(task,initial_state(task));old=[{k:v.replace('new','old') for k,v in c.items()} for c in held]
            candidates=[]
            for a,b in itertools.combinations(old,2):
                delta=utility(a,kind)-utility(b,kind)
                if not delta:continue
                winner,loser=(a,b) if delta>0 else (b,a)
                reasons=['coherence'] if kind=='coherent_pairs' else ['clarity'] if kind=='action_preference' else []
                candidates.append({'winner':winner,'loser':loser,'reasons':reasons})
            rng=random.Random(seed);rng.shuffle(candidates);pairs=candidates[:24]
            started=time.perf_counter();model=DeepPreferenceModel(task,sem).fit(pairs,steps=120)
            model.save(out/(kind+'-'+str(seed)))
            heads=model.encoder.pool(model.encoder.matrix(held))@model.linear_head;deep=model.scores(held)
            weights=fit(task,pairs);legacy=np.array([score(weights,features(task,c)) for c in held])
            trials=[(i,j) for i,j in itertools.combinations(range(len(held)),2) if utility(held[i],kind)!=utility(held[j],kind)]
            rng.shuffle(trials);trials=trials[:80]
            def accuracy(scores):
                return float(np.mean([.5 if abs(float(scores[i]-scores[j]))<1e-10 else int((scores[i]>scores[j])==(utility(held[i],kind)>utility(held[j],kind))) for i,j in trials]))
            (out/(kind+'-'+str(seed)+'-inputs.json')).write_text(json.dumps({'task':task,'training_pairs':pairs,'test_combos':held,'test_pair_indices':trials,
                'predictions':{'id_baseline':legacy.tolist(),'semantic_linear':heads.tolist(),'semantic_deep':deep.tolist()}},ensure_ascii=False,indent=2),'utf-8')
            row={'scenario':kind,'seed':seed,'training_labels':24,'new_wording_test_pairs':len(trials),'id_baseline':accuracy(legacy),
                 'semantic_linear':accuracy(heads),'semantic_deep':accuracy(deep),'elapsed_seconds':round(time.perf_counter()-started,3),
                 'internal_holdout':model.report['heldout_deep'],'phase':model.report['phase']}
            report['results'].append(row);(out/'report.json').write_text(json.dumps(report,ensure_ascii=False,indent=2),'utf-8');print(json.dumps(row),flush=True)
    report['averages']={key:float(np.mean([r[key] for r in report['results']])) for key in ('id_baseline','semantic_linear','semantic_deep')}
    report['note']='配方真值仅用于生成模拟反馈和离线评分，不输入编码器；旧措辞训练与新措辞测试分离。这些结果不能证明真实用户收益或优于直接对话。'
    (out/'report.json').write_text(json.dumps(report,ensure_ascii=False,indent=2),'utf-8')
    print(json.dumps({'report':str(out/'report.json'),'averages':report['averages']}),flush=True)


if __name__=='__main__':main()
