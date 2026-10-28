"""Explicit live smoke: two paid model requests, isolated D-drive storage.

Run manually only. Never part of unittest discovery or production startup.
"""
import json
import os
import shutil
import sys
import time
from pathlib import Path

ROOT=Path(__file__).resolve().parents[1];sys.path.insert(0,str(ROOT))
from ai.delivery import check
from ai.provider import Settings,SiliconFlow
from ai.service import AIService
from store import Store


def main():
    folder=Path('D:/CodexWork/temp/intent-product-live')/str(time.time_ns());folder.mkdir(parents=True)
    source=Settings(ROOT/'data/private');key=source.key()
    if not key:raise RuntimeError('Configure SiliconFlow locally first')
    old_key=os.environ.get('INTENT_SILICONFLOW_API_KEY');os.environ['INTENT_SILICONFLOW_API_KEY']=key
    store=Store(folder/'qa.sqlite3');provider=SiliconFlow(source);service=AIService(store,provider)
    service.settings.save({'model':source.public()['model']})
    def wait(job):
        started=time.monotonic();last=0
        while time.monotonic()-started<650:
            current=service.public_job(job['id'])
            if current['status'] not in ('queued','running'):
                if current['status']!='completed':raise RuntimeError(current['error'])
                return current
            if time.monotonic()-last>15:
                print(current['kind']+': '+current['progress'],flush=True);last=time.monotonic()
            time.sleep(.5)
        raise RuntimeError('Live job deadline exceeded')
    try:
        generated=wait(service.submit('generate',{'goal':'为第一次使用这套意图工作室的人写一份可以直接照着操作的完整中文使用说明。严格依据材料，用四章讲清创建目标、补充资料与修改、失败恢复、复核和导出。每章给出具体操作与成功标志，不宣传不存在的能力。',
            'task_type':'writing','detail_level':'complete','facts':'资料和成果的主存储位于D盘；任务修改采用前保留原文',
            'materials':[{'name':'产品实际流程.md','text':(ROOT/'docs/PRODUCT_WORKFLOW.md').read_text(encoding='utf-8')}]}))
        sid=generated['result']['session_id'];view=store.view(sid)
        blocks=[b for b in view['task']['blocks'] if not b.get('fixed')]
        store.action(sid,{'kind':'lock','revision':view['revision'],'block':blocks[0]['id']})
        library=service.materials(sid)
        service.update_materials(sid,{'revision':library['revision'],'materials':library['materials']+[{'name':'交付补充.md','text':'交付包实际包含正文、任务条件、素材原文、生成记录、会话审计及交付检查。正文或素材改变后用户确认项清空；撤回恢复对应版本。自动检查不能核实事实真伪。'}]})
        before=store.view(sid)
        revised=wait(service.submit('revise',{'revision':before['revision'],'instruction':'根据新增的交付补充资料，把最后一章写清ZIP具体包含哪些文件、确认项何时清空及自动检查的边界。引用新增素材，保留其余内容。','scope':[blocks[-1]['id']]},sid))
        assert store.view(sid)['text']==before['text'],'Proposal unexpectedly changed content'
        service.apply(revised['id'],{'revision':before['revision']})
        after=store.view(sid)
        assert after['state']['locks']==before['state']['locks']
        assert after['state']['combo'][blocks[0]['id']]==before['state']['combo'][blocks[0]['id']]
        assert after['pair_count']==0
        files={kind:service.export(sid,after['revision'],kind) for kind in ('md','zip')}
        examples=ROOT/'docs/examples';examples.mkdir(exist_ok=True)
        shutil.copyfile(files['md']['path'],examples/'工作室使用说明-模型原稿-v3.md')
        shutil.copyfile(files['zip']['path'],examples/'工作室使用说明-模型原稿-v3.zip')
        proof={'validation_type':'developer_live_api_check_not_human_trial','provider':'siliconflow','model':source.public()['model'],
            'isolated_database':str(store.path),'prompt_version':after['task']['ai']['prompt_version'],
            'generation_calls':generated['result']['calls'],'revision_calls':revised['result']['calls'],
            'checks':{'proposal_preserved_current_text':True,'locked_section_preserved':True,'pair_count':after['pair_count'],
                      'material_count':len(service.materials(sid)['materials']),'new_material_in_revision_context':any(s['id'].startswith('M2#') for s in revised['result']['sources'])},
            'delivery':check(after,service.materials(sid)['materials']),
            'outputs':{'markdown':str(examples/'工作室使用说明-模型原稿-v3.md'),'package':str(examples/'工作室使用说明-模型原稿-v3.zip')}}
        path=ROOT/'docs/validation/product-live-proof-v3.json';path.write_text(json.dumps(proof,ensure_ascii=False,indent=2),encoding='utf-8')
        print(json.dumps({'proof':str(path),'characters':proof['delivery']['characters'],'checks':proof['checks']},ensure_ascii=False),flush=True)
    finally:
        service.close()
        if old_key is None:os.environ.pop('INTENT_SILICONFLOW_API_KEY',None)
        else:os.environ['INTENT_SILICONFLOW_API_KEY']=old_key


if __name__=='__main__':main()
