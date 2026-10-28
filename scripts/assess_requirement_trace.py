"""Designed evidence-location fixtures, not semantic acceptance or a user study."""
import hashlib
import json
import random
import sys
import time
from pathlib import Path

ROOT=Path(__file__).resolve().parents[1];sys.path.insert(0,str(ROOT))
from ai.requirement_trace import evidence_for,report,semantic_evidence
from core import initial_state


def run():
    folder=ROOT/'experiments/runs'/('requirement-trace-'+str(time.time_ns()));folder.mkdir(parents=True)
    cases=[]
    # Explicit overlap, partial paraphrase, and absence/negation traps are kept
    # separately. Expected location is hand-specified, never passed to retrieval.
    pairs=[
        ('需要搜索功能','输入物品关键词，提供搜索功能以查找记录。','locator'),
        ('提供错误恢复步骤','错误恢复步骤：保留输入，提示错误，再允许重新提交。','locator'),
        ('按天安排练习','第1天练习基础概念，第2天练习应用题。','paraphrase'),
        ('邀请对方回复','若您方便参与，烦请回复可用时间。','paraphrase'),
        ('说明隐私保护','隐私保护：不公开联系方式，说明可见范围。','locator'),
        ('解释方案取舍','方案取舍：优先验证核心流程，暂缓扩展功能。','locator'),
        ('需要搜索功能','当前不支持搜索功能，仍需进一步设计。','negation'),
        ('提供错误恢复步骤','错误恢复步骤尚未完成，不应视为已经具备。','negation')]
    results=[];use_semantic='--semantic' in sys.argv;semantic_model=None
    for seed in range(3):
        for index,(query,text,track) in enumerate(pairs):
            pool=[{'block':'target','title':'相关章节','text':text},
                  {'block':'noise-a','title':'背景','text':'这份说明介绍项目背景、准备工作和分工。'},
                  {'block':'noise-b','title':'后续','text':'后续需要根据反馈继续调整内容与安排。'}]
            random.Random(seed*31+index).shuffle(pool)
            start=time.perf_counter();evidence=evidence_for(query,pool);elapsed=(time.perf_counter()-start)*1000
            task={'title':'核对实验','brief':query,'source':'example','category':'project','facts':{},
                  'intent_brief':{'explicit_answers':[{'question':'用户要求','answer':query}],'unresolved':[]},
                  'blocks':[{'id':p['block'],'title':p['title'],'variants':[{'id':'v'+str(i),'template':p['text']} for i in range(3)]} for p in pool]}
            row=report(task,initial_state(task))['rows'][0]
            assert row['status'] not in ('user_met','machine_passed')
            cases.append({'seed':seed,'track':track,'query':query,'sections':pool,'expected_location':'target'})
            semantic=semantic_evidence(query,pool) if use_semantic else None
            if semantic:semantic_model=semantic['model']
            results.append({'semantic_top1_hit':bool(semantic and semantic['evidence'] and semantic['evidence'][0]['block']=='target'),'semantic_top3_hit':bool(semantic and any(e['block']=='target' for e in semantic['evidence'])),'semantic_evidence':semantic, 'seed':seed,'track':track,'query':query,'top1_hit':bool(evidence and evidence[0]['block']=='target'),
                            'top3_hit':any(e['block']=='target' for e in evidence),'first_section_hit':pool[0]['block']=='target',
                            'status':row['status'],'evidence':evidence,'milliseconds':elapsed})
    summary=[]
    for track in ['locator','paraphrase','negation']:
        rows=[r for r in results if r['track']==track]
        summary.append({'track':track,'cases':len(rows),'top1_hits':sum(r['top1_hit'] for r in rows),'top3_hits':sum(r['top3_hit'] for r in rows),
                        'first_section_hits':sum(r['first_section_hit'] for r in rows),'automatic_semantic_passes':0,'semantic_top1_hits':sum(r['semantic_top1_hit'] for r in rows) if use_semantic else None,'semantic_top3_hits':sum(r['semantic_top3_hit'] for r in rows) if use_semantic else None})
    record={'result':'PASS','synthetic':True,'paid_calls':0,'summary':summary,'semantic_enabled':use_semantic,'frozen_model':semantic_model,
            'limits':['24 designed fixtures, not real user effectiveness or general retrieval accuracy.','Locating a negation is useful evidence, not satisfaction.','Paraphrase misses are retained; semantic retrieval is not a verifier.','First-section baseline measures only a trivial locator, not ordinary Codex/chat.']}
    for name,value in [('inputs.json',cases),('results.json',results),('report.json',record)]:
        (folder/name).write_text(json.dumps(value,ensure_ascii=False,indent=2),encoding='utf-8')
    manifest={}
    for name in ['ai/requirement_trace.py','research/semantic.py','scripts/assess_requirement_trace.py']:
        blob=(ROOT/name).read_bytes();dest=folder/'source'/name;dest.parent.mkdir(parents=True,exist_ok=True);dest.write_bytes(blob);manifest[name]=hashlib.sha256(blob).hexdigest()
    (folder/'manifest.json').write_text(json.dumps(manifest,indent=2),encoding='utf-8')
    (ROOT/'experiments/requirement-trace-latest.json').write_text(json.dumps({'folder':str(folder)},ensure_ascii=False,indent=2),encoding='utf-8')
    print(json.dumps({'folder':str(folder),**record},ensure_ascii=False,indent=2))


if __name__=='__main__':run()
