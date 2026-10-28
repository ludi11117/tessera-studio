"""Validate a real generated QA session with a real revision, without touching user sessions."""
import argparse
import hashlib
import json
import sys
import time
from pathlib import Path

ROOT=Path(__file__).resolve().parents[1];sys.path.insert(0,str(ROOT))
from ai.provider import Settings,SiliconFlow
from ai.service import AIService
from core import render_variant,variant_for
from store import Store

parser=argparse.ArgumentParser();parser.add_argument('folder',type=Path);args=parser.parse_args()
folder=args.folder.resolve()
if not str(folder).lower().startswith('d:\\codexwork\\temp\\intent-ai-live-check\\'):
    raise SystemExit('Use an isolated live-check directory on D:')
store=Store(folder/'qa.sqlite3');settings=Settings(ROOT/'data/private');provider=SiliconFlow(settings)
service=AIService(store,provider);service.settings=settings
initial=json.loads((folder/'result.json').read_text(encoding='utf-8'))
sid=initial['result']['session_id'];view=store.view(sid)
editable=[b for b in view['task']['blocks'] if not b.get('fixed')]
first,last=editable[0]['id'],editable[-1]['id']
store.action(sid,{'kind':'lock','block':first,'revision':view['revision']})
before=store.view(sid)
locked_text=render_variant(before['task'],variant_for(before['task'],first,before['state']['combo'][first]))
started=time.perf_counter()
job=service.submit('revise',{'revision':before['revision'],'instruction':'请把最后一节改成两周内的分日执行步骤，并给出三项具体的验收测试。只改这一节，保留前面的技术选择。','scope':[last]},sid)
last_progress=None
for _ in range(320):
    job=service.public_job(job['id'])
    if job['progress']!=last_progress:print(json.dumps({'progress':job['progress']},ensure_ascii=False),flush=True);last_progress=job['progress']
    if job['status'] not in ('queued','running'):break
    time.sleep(1)
if job['status']!='completed':
    print(json.dumps({'status':job['status'],'error':job['error']},ensure_ascii=False));service.close();raise SystemExit(1)
assert job['result']['can_apply'],job['result']
assert store.view(sid)['text']==before['text']
service.apply(job['id'],{'revision':before['revision']})
after=store.view(sid)
assert locked_text==render_variant(after['task'],variant_for(after['task'],first,after['state']['combo'][first]))
assert after['text']!=before['text']
artifact=service.export(sid,after['revision'],'zip')
proof={'data_origin':'development_test_real_provider','provider':'siliconflow','model':settings.public()['model'],'generation':'completed','revision':'completed','draft_preserved_original':True,'locked_text_unchanged':True,'pair_labels_from_generation_or_revision':after['pair_count'],'revision_elapsed_seconds':round(time.perf_counter()-started,2),'revision_calls':job['result']['calls'],'initial_calls':initial['result']['calls'],'export':artifact,'qa_database':str(folder/'qa.sqlite3'),'job_id':job['id']}
(folder/'live-proof.json').write_text(json.dumps(proof,ensure_ascii=False,indent=2),encoding='utf-8')
print(json.dumps(proof,ensure_ascii=False,indent=2),flush=True);service.close()
