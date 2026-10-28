"""Explicit developer action: add labeled examples and train on simulated choices.

Never imported by production startup. Existing examples and user tasks are kept.
"""
import argparse
import json
import sys
import time
from pathlib import Path

ROOT=Path(__file__).resolve().parents[1];sys.path.insert(0,str(ROOT))
from ai.choice_demo import seed as choice_demo
from store import Store

TITLE='本地训练示例｜模拟取舍'


def seed(store):
    existing=next((s['id'] for s in store.sessions() if s['title']==TITLE and s['source']=='example'),None)
    if existing:return existing,None
    texts=[['先做一条发布到认领的最小流程，逐项核对输入与输出。','先梳理物品类型、字段和状态，再确定最小操作范围。','先画出浏览与搜索的页面草图，讨论哪些信息最容易找到。'],
           ['依次实现登记、关键词搜索和手动更新状态，记录每一步结果。','先完善数据校验和异常输入，再接登记与状态更新。','先整理导入导出与备份步骤，再用固定样例运行全流程。'],
           ['先检查登记后能否搜索到，再检查领取后的状态是否保留。','先列出错误输入、空结果和重复登记的检查清单，再逐项复验。','按真实操作顺序列出输入、预期输出与失败后的复验步骤。']]
    task={'title':TITLE,'source':'example','category':'project','brief':'本地训练机制演示。文字由开发者编写，八次选择由模拟规则产生，不是真实用户偏好，也不是API成功案例。可查看实际训练曲线、切换线性对照、撤回模拟反馈并观察旧模型停止使用。',
          'facts':{},'materials':[],'blocks':[{'id':'demo'+str(i),'title':title,'variants':[{'id':f'demo{i}-{j}','template':t} for j,t in enumerate(texts[i])]} for i,title in enumerate(['切入方式','实施顺序','验收重点'])]}
    sid=store.create(task)
    config={'model':'content_linear','policy':'uncertainty','context_mode':'current','budget':16,'seed':11,'evaluate_only':True,'data_origin':'simulation'}
    store.action(sid,{'kind':'research_config','revision':0,'config':config})
    preferences=[[1,3,0],[3,1,0],[0,1,3]]
    for _ in range(8):
        view=store.view(sid);offer=store.offer(sid,view['revision'])
        def utility(combo):return sum(preferences[i][int(combo['demo'+str(i)].split('-')[-1])] for i in range(3))
        choice='a' if utility(offer['a'])>=utility(offer['b']) else 'b'
        store.action(sid,{'kind':'compare','revision':view['revision'],'offer':offer['id'],'choice':choice,'reasons':['clarity'],
                          'reason_note':'开发模拟选择，仅用于演示；不代表真实用户偏好。'})
    current=store.view(sid);run=store.learning().submit(sid,{'revision':current['revision'],'steps':180,'activate':True})
    return sid,run['id']


def main():
    parser=argparse.ArgumentParser();parser.add_argument('--db',type=Path,required=True);args=parser.parse_args()
    target=args.db.resolve()
    if target.drive.upper()!='D:':raise ValueError('Examples and checkpoints must be on D:')
    target.parent.mkdir(parents=True,exist_ok=True);store=Store(target)
    choice=choice_demo(store);sid,rid=seed(store)
    if rid:
        start=time.monotonic()
        while time.monotonic()-start<120:
            value=store.learning().public(rid)
            if value['status'] not in ('queued','running') and (value.get('report') or {}).get('activation')!='pending':break
            time.sleep(.2)
        print(json.dumps({'choice_demo':choice,'learning_demo':sid,'run':rid,'status':value['status'],'error':value['error'],'paid_calls':0,'data_origin':'simulation'},ensure_ascii=False))
    else:print(json.dumps({'choice_demo':choice,'learning_demo':sid,'existing_preserved':True,'paid_calls':0}))
    if store._learning_service:store._learning_service.close()


if __name__=='__main__':main()
