"""Bounded paid developer acceptance. Requires --run-live; never runs at startup.

All outputs go to a new D: directory. Original production data and historical
validation records are not modified. Literal checks are not editorial acceptance.
"""
import argparse
import json
import re
import sys
import time
from pathlib import Path

ROOT=Path(__file__).resolve().parents[1];sys.path.insert(0,str(ROOT))
from ai.provider import Settings,SiliconFlow,ProviderError
from ai.service import AIService
from core import render_variant,variant_for
from store import Store

CASES=[
    {'id':'short_email','task_type':'writing','goal':'请根据素材写一封可以直接发送给林老师的工作坊邀请邮件。正文总计160–220个中文字符，最多分成两个部分；不写主题行，不补报名链接、费用、确认名额或新的截止日期。末尾请老师回复是否方便参加。',
     'materials':[{'name':'已确认安排.md','text':'收件人为林老师。活动名称：校园数据可视化工作坊。举办日期为2026年11月6日，时间14:00–15:30，地点实验楼B204。计划面向12名同学，最终名额尚未确认。邀请林老师做一次案例点评。暂时没有报名链接，未约定费用，也没有要求老师承诺出席。'}],
     'acceptance':['三份候选均为可发送邮件，正文总字数160–220','活动、日期、时间、地点不变','不把12人计划写成已确认名额','不虚构报名、费用或截止日期']},
    {'id':'internal_choice','task_type':'analysis','goal':'只根据两份内部验收记录，为经常断网的笔记本使用者选择一套文本导入方案。写出结论、数字依据、不能推断的事项和最小复验步骤。不要联网或虚构长期测试，整份约500字，方案名称保持甲/乙。',
     'facts':'运行内存上限为300MB；中断后可以继续导入是必要条件',
     'materials':[{'name':'方案甲.md','text':'同一台机器首次导入100份测试文本耗时80秒，峰值内存420MB。发生中断后需要重新导入。只有本次测量，没有长期稳定性或识别准确率数据。'},
                  {'name':'方案乙.md','text':'同一台机器首次导入100份测试文本耗时110秒，峰值内存260MB。已验证中断后继续导入。只有本次测量，没有长期稳定性或识别准确率数据。'}],
     'acceptance':['三份候选都选择乙并说明必要条件','80秒/420MB与110秒/260MB归属正确','不声称乙更快或准确率更高','提供可执行复验而不把计划说成已完成测试']},
    {'id':'offline_study','task_type':'study','goal':'根据我的基础安排七天Python学习和练习，让我最后能独立写一个本地TXT词频统计脚本。逐天给出30分钟内的学习、练习和检查标准，标明需要先学的新知识。全程离线，不安装第三方包，不能声称我已经完成练习。',
     'facts':'学习周期为7天，每天最多30分钟；使用Windows，不能联网安装软件',
     'materials':[{'name':'当前基础.md','text':'已学变量、列表和for循环。尚未学字典、函数、类、文件读写，也没有第三方库经验。电脑已有可运行的Python。目标是读取本机UTF-8 TXT文件，按空白分词，统计每个词的出现次数，按次数降序显示前十项；不要求中文分词，不涉及联网。'}],
     'acceptance':['三份候选均覆盖七天，每天可在30分钟内执行','字典/文件读写在使用前安排学习，不要求类或第三方库','目标为按空白分词，不擅加中文分词或联网安装','有可运行练习和可判定的自测标准']}
]


class BoundedProvider(SiliconFlow):
    def __init__(self,settings,max_calls,outputs):
        super().__init__(settings);self.limit=max_calls;self.calls=0;self.outputs=outputs
    def request(self,path,payload=None,on_progress=None):
        if payload is not None:
            if self.calls>=self.limit:raise ProviderError('本轮真实请求数已达上限，未继续调用')
            self.calls+=1
        result=super().request(path,payload,on_progress)
        if payload is not None:
            # Only model content and usage, never authorization headers or credentials.
            (self.outputs/f'upstream-response-{self.calls}.json').write_text(json.dumps({k:result[k] for k in ('choices','usage') if k in result},ensure_ascii=False,indent=2),'utf-8')
        return result


def main():
    parser=argparse.ArgumentParser();parser.add_argument('--run-live',action='store_true');parser.add_argument('--max-calls',type=int,default=5)
    parser.add_argument('--case',choices=[c['id'] for c in CASES])
    args=parser.parse_args()
    if not args.run_live:
        print(json.dumps({'paid_execution':False,'cases':[{k:v for k,v in c.items() if k!='materials'} for c in CASES]},ensure_ascii=False,indent=2));return
    if not 1<=args.max_calls<=6:raise ValueError('A run is bounded to 1–6 upstream requests')
    source=Settings(ROOT/'data/private');config=source.public()
    if not config['key_configured'] or not config['model']:raise RuntimeError('No configured model')
    run=str(time.time_ns());folder=Path('D:/CodexWork/temp/intent-readiness-live')/run;folder.mkdir(parents=True)
    out=ROOT/'docs/validation/readiness-live'/run;out.mkdir(parents=True)
    provider=BoundedProvider(source,args.max_calls,out);store=Store(folder/'qa.sqlite3');service=AIService(store,provider);service.settings=source
    report={'type':'developer_live_acceptance_not_user_study','model':config['model'],'run':run,'database':str(store.path),'max_calls':args.max_calls,'cases':[],
            'editorial_status':'pending_manual_review','note':'API completion and literal matching do not establish content acceptance.'}
    def persist():
        report['upstream_requests']=provider.calls;(out/'report.json').write_text(json.dumps(report,ensure_ascii=False,indent=2),'utf-8')
    def wait(job):
        started=time.monotonic();last=0
        while time.monotonic()-started<420:
            current=service.public_job(job['id'])
            if current['status'] not in ('running','queued'):return current,round(time.monotonic()-started,2)
            if time.monotonic()-last>12:print(current['kind']+': '+current['progress'],flush=True);last=time.monotonic()
            time.sleep(.5)
        service.cancel(job['id']);raise RuntimeError('Live check deadline exceeded; cancellation requested')
    print(json.dumps({'run':run,'outputs':str(out),'request_limit':args.max_calls,'model':config['model']},ensure_ascii=False),flush=True)
    try:
        for case in [c for c in CASES if not args.case or c['id']==args.case]:
            started=time.monotonic();payload={k:v for k,v in case.items() if k in ('goal','facts','materials','task_type')};payload['detail_level']='complete'
            job,elapsed=wait(service.submit('generate',payload))
            result={'id':case['id'],'goal':case['goal'],'acceptance':case['acceptance'],'job_id':job['id'],'status':job['status'],'elapsed_seconds':elapsed,'error':job['error'],'editorial_status':'pending_manual_review'}
            report['cases'].append(result)
            if job['status']=='completed':
                sid=job['result']['session_id'];view=store.view(sid);task=view['task'];candidates=[]
                for j in range(3):
                    text='\n\n'.join(render_variant(task,b['variants'][j]) for b in task['blocks'] if not b.get('fixed'))
                    candidates.append({'candidate':'ABC'[j],'body':text,'characters_without_citations_or_whitespace':len(re.sub(r'\s+|\[M\d+#\d+\]','',text))})
                result.update(session_id=sid,calls=job['result']['calls'],candidates=candidates,pair_count=view['pair_count'],delivery=service.delivery(sid))
                (out/(case['id']+'-model-output.json')).write_text(json.dumps({'task':task,'candidates':candidates},ensure_ascii=False,indent=2),'utf-8')
                for kind in ('md','zip'):
                    export=service.export(sid,view['revision'],kind);(out/(case['id']+'-model-output.'+kind)).write_bytes(Path(export['path']).read_bytes())
            persist();print(json.dumps({k:result.get(k) for k in ('id','status','elapsed_seconds','error')},ensure_ascii=False),flush=True)
            if job['status']!='completed' and provider.calls>=args.max_calls:break
        # One targeted revision checks the real proposal/lock/apply path, when budget permits.
        ready=next((c for c in report['cases'] if c['id']=='internal_choice' and c['status']=='completed'),None)
        if ready and provider.calls<args.max_calls:
            sid=ready['session_id'];view=store.view(sid);blocks=[b for b in view['task']['blocks'] if not b.get('fixed')]
            store.action(sid,{'kind':'lock','revision':view['revision'],'block':blocks[0]['id']});before=store.view(sid)
            job,elapsed=wait(service.submit('revise',{'revision':before['revision'],'scope':[blocks[-1]['id']],'instruction':'只完善本章的最小复验步骤。写清在同一台笔记本上使用同一批100份测试TXT，分别检查计时、峰值内存，以及中断后能否继续；这是一份待执行的检查清单，不是已取得的测试结果。不要更改结论或资料中的原始数字。'},sid))
            revision={'status':job['status'],'error':job['error'],'job_id':job['id'],'elapsed_seconds':elapsed,'proposal_preserved_current':store.view(sid)['text']==before['text']}
            if job['status']=='completed':
                revision.update(diffs=job['result']['diffs'],calls=job['result']['calls'])
                if job['result'].get('can_apply'):
                    service.apply(job['id'],{'revision':before['revision']});after=store.view(sid)
                    revision.update(locked_section_preserved=variant_for(after['task'],blocks[0]['id'],after['state']['combo'][blocks[0]['id']])==variant_for(before['task'],blocks[0]['id'],before['state']['combo'][blocks[0]['id']]),pair_count=after['pair_count'])
            report['revision']=revision;persist()
        print(json.dumps({'report':str(out/'report.json'),'upstream_requests':provider.calls,'editorial_status':report['editorial_status']},ensure_ascii=False),flush=True)
    finally:
        persist();service.close()


if __name__=='__main__':main()
