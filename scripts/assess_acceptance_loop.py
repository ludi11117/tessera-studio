"""Explicit, capped paid checks on historical failures, in an isolated D: DB.

Does not overwrite old evidence or run as part of startup/tests.
"""
import argparse
import json
import sys
import time
from pathlib import Path

ROOT=Path(__file__).resolve().parents[1];sys.path.insert(0,str(ROOT))
from ai.acceptance import digest,suggest
from ai.provider import Settings
from ai.service import AIService
from store import Store
from assess_readiness_live import BoundedProvider,CASES

HISTORICAL={
    'short_email':'1793087380498905200',
    'internal_choice':'1793086910277270900',
    'offline_study':'1793086910277270900'
}


def main():
    parser=argparse.ArgumentParser();parser.add_argument('--run-live',action='store_true');parser.add_argument('--max-calls',type=int,default=6)
    parser.add_argument('--case',choices=list(HISTORICAL),action='append')
    args=parser.parse_args();cases=args.case or ['short_email','internal_choice']
    if not args.run_live:
        print(json.dumps({'paid_execution':False,'cases':cases,'max_calls':args.max_calls,'per_case_limit':3},ensure_ascii=False));return
    if not 1<=args.max_calls<=6:raise ValueError('每轮最多6次真实请求')
    run=str(time.time_ns());out=ROOT/'docs/validation/acceptance-live'/run;out.mkdir(parents=True)
    folder=Path('D:/CodexWork/temp/intent-acceptance-live')/run;folder.mkdir(parents=True)
    settings=Settings(ROOT/'data/private');provider=BoundedProvider(settings,args.max_calls,out)
    store=Store(folder/'qa.sqlite3');service=AIService(store,provider);service.settings=settings
    report={'type':'developer_regression_not_user_study','run':run,'model':settings.public()['model'],'max_calls':args.max_calls,
            'database':str(store.path),'cases':[],'editorial_status':'pending_manual_review','comparison_to_direct_chat':'not_established'}
    def persist():
        report['upstream_requests']=provider.calls;(out/'report.json').write_text(json.dumps(report,ensure_ascii=False,indent=2),'utf-8')
    print(json.dumps({'output':str(out),'limit':args.max_calls,'cases':cases},ensure_ascii=False),flush=True)
    try:
        for case_id in cases:
            if args.max_calls-provider.calls<3:break
            file=ROOT/'docs/validation/readiness-live'/HISTORICAL[case_id]/(case_id+'-model-output.json')
            original=json.loads(file.read_text('utf-8'))['task'];sid=store.create(original);view=store.view(sid)
            contract=suggest(original);contract['manual']=next(c['acceptance'] for c in CASES if c['id']==case_id)
            store.action(sid,{'kind':'acceptance','revision':view['revision'],'contract':contract});before=store.view(sid)
            entry={'case':case_id,'starting_artifact':str(file),'starting_task_hash':digest(original),'initial_delivery':service.delivery(sid),'session_id':sid}
            report['cases'].append(entry);persist()
            job=service.submit('repair',{'revision':before['revision']},sid);started=time.monotonic();last=0
            while time.monotonic()-started<420:
                current=service.public_job(job['id'])
                if current['status'] not in ('queued','running'):break
                if time.monotonic()-last>15:print(case_id+': '+current['progress'],flush=True);last=time.monotonic()
                time.sleep(.5)
            else:
                service.cancel(job['id']);current=service.public_job(job['id'])
            entry.update(status=current['status'],error=current['error'],job_id=job['id'],elapsed_seconds=round(time.monotonic()-started,2),
                         original_unchanged=store.view(sid)['text']==before['text'],result=current['result'])
            (out/(case_id+'-job.json')).write_text(json.dumps(current,ensure_ascii=False,indent=2),'utf-8')
            if current['status']=='completed' and current['result'].get('can_apply'):
                service.apply(job['id'],{'revision':before['revision']});after=store.view(sid)
                entry['final_delivery']=service.delivery(sid);entry['final_pair_count']=after['pair_count']
                entry['final_body']='\n\n'.join(d['after'] for d in current['result']['diffs'])
                for kind in ('md','zip'):
                    exported=service.export(sid,after['revision'],kind)
                    (out/(case_id+'-repaired-model-output.'+kind)).write_bytes(Path(exported['path']).read_bytes())
            persist();print(json.dumps({'case':case_id,'status':current['status'],'can_apply':(current['result'] or {}).get('can_apply'),'calls':provider.calls},ensure_ascii=False),flush=True)
        print(str(out/'report.json'),flush=True)
    finally:persist();service.close()


if __name__=='__main__':main()
