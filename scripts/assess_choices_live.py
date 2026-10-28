"""One explicit, capped live generation. Separate D: database, no fake labels."""
import argparse
import json
import sys
import time
from pathlib import Path

ROOT=Path(__file__).resolve().parents[1];sys.path.insert(0,str(ROOT))
from ai.provider import Settings
from ai.service import AIService
from core import render_variant
from store import Store
from assess_readiness_live import BoundedProvider

CASE={'goal':'为有一点Python基础的学生设计校园失物招领单机原型。目标为离线登记、搜索和手动更新认领状态，不开发多用户权限，不公开个人联系方式。请给出每条路径的首个闭环、具体实现步骤、主动暂缓的功能与可检查的验收方式。不要把方案写成已实现成果，不编造成本或性能数字。',
      'task_type':'project','detail_level':'quick','facts':'电脑已安装Python且标准库可用；不能联网或安装第三方包；只做单机演示',
      'materials':[{'name':'范围.md','text':'登记字段仅包括编号、物品类型、地点、简短描述和状态；状态只有待认领与已认领。演示不采集姓名或电话。所有开发步骤尚未执行，不需要联网服务。'}],
      'approaches':[{'name':'JSON文件先行','instruction':'以JSON文件和命令行完成登记与搜索，交代读写文件和状态更新的处理，不安装外部包。'},
                    {'name':'SQLite命令行','instruction':'使用Python自带SQLite管理登记、搜索与手动领取状态，以命令行作为入口，说明与JSON文件方案的具体区别。'},
                    {'name':'本地网页入口','instruction':'使用本地网页、Python自带http.server与SQLite，实现本机登记和搜索，说明网页入口相对命令行额外需要做什么，不用第三方框架。'}]}


def main():
    p=argparse.ArgumentParser();p.add_argument('--run-live',action='store_true');p.add_argument('--max-calls',type=int,default=2);args=p.parse_args()
    if not args.run_live:print(json.dumps({'paid_execution':False,'max_calls':args.max_calls,'case':CASE},ensure_ascii=False));return
    if not 1<=args.max_calls<=2:raise ValueError('This acceptance is capped at two paid requests')
    run=str(time.time_ns());out=ROOT/'docs/validation/choices-live'/run;out.mkdir(parents=True)
    folder=Path('D:/CodexWork/temp/intent-choices-live')/run;folder.mkdir(parents=True)
    settings=Settings(ROOT/'data/private');provider=BoundedProvider(settings,args.max_calls,out);store=Store(folder/'qa.sqlite3');service=AIService(store,provider);service.settings=settings
    report={'type':'developer_live_generation_not_user_study','max_calls':args.max_calls,'case':CASE,'database':str(store.path),'editorial_status':'pending_manual_review'}
    print(json.dumps({'output':str(out),'max_calls':args.max_calls},ensure_ascii=False),flush=True)
    try:
        job=service.submit('generate',CASE);started=time.monotonic();last=0
        while time.monotonic()-started<420:
            current=service.public_job(job['id'])
            if current['status'] not in ('queued','running'):break
            if time.monotonic()-last>15:print(current['progress'],flush=True);last=time.monotonic()
            time.sleep(.5)
        else:service.cancel(job['id']);current=service.public_job(job['id'])
        report.update(job=current,upstream_requests=provider.calls)
        if current['status']=='completed':
            view=store.view(current['result']['session_id']);report['task']=view['task'];report['choice_board']=view['choice_board'];report['pair_count']=view['pair_count']
            report['candidates']=['\n\n'.join(render_variant(view['task'],b['variants'][j]) for b in view['task']['blocks'] if not b.get('fixed')) for j in range(3)]
        print(json.dumps({'status':current['status'],'error':current['error'],'requests':provider.calls},ensure_ascii=False),flush=True)
    finally:
        (out/'report.json').write_text(json.dumps(report,ensure_ascii=False,indent=2),'utf-8');service.close()


if __name__=='__main__':main()
