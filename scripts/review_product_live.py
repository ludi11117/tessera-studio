"""Correct the live guide after manual review; one additional paid request."""
import json
import os
import shutil
import sys
import time
from pathlib import Path

ROOT=Path(__file__).resolve().parents[1];sys.path.insert(0,str(ROOT))
from ai.provider import Settings,SiliconFlow
from ai.service import AIService
from store import Store


def main():
    path=ROOT/'docs/validation/product-live-proof-v3.json';proof=json.loads(path.read_text(encoding='utf-8'))
    # Preserve initial output and explicitly record its failed editorial acceptance.
    for kind,extension in [('markdown','md'),('package','zip')]:
        original=Path(proof['outputs'][kind]);target=ROOT/'docs/examples'/f'工作室使用说明-模型原稿-v3.{extension}'
        if original!=target and original.exists():shutil.copyfile(original,target)
        proof['outputs'][kind]=str(target)
    proof['manual_review']={'initial_status':'needs_correction','issues':['Invented button names and task states','Invented D:/data/projects storage','Invented M1-001 citation format','Claimed automatic exports on modification'],'initial_promoted_to_user_deliverable':False}
    path.write_text(json.dumps(proof,ensure_ascii=False,indent=2),encoding='utf-8')
    source=Settings(ROOT/'data/private');prior=os.environ.get('INTENT_SILICONFLOW_API_KEY');os.environ['INTENT_SILICONFLOW_API_KEY']=source.key()
    store=Store(proof['isolated_database']);service=AIService(store,SiliconFlow(source));service.settings.save({'model':source.public()['model']})
    try:
        sid=next(s['id'] for s in store.sessions() if s['source']=='generated')
        view=store.view(sid)
        for block in view['task']['blocks']:
            if not block.get('fixed') and block['id'] in view['state']['locks']:
                store.action(sid,{'kind':'lock','block':block['id'],'revision':view['revision']});view=store.view(sid)
        library=service.materials(sid)
        service.update_materials(sid,{'revision':library['revision'],'materials':library['materials']+[{'name':'精确界面与操作契约.md','text':(ROOT/'docs/PRODUCT_WORKFLOW.md').read_text(encoding='utf-8')}]})
        view=store.view(sid)
        job=service.submit('revise',{'revision':view['revision'],'instruction':'人工复核发现原稿含虚构操作。请仅依据新增M3精确界面资料，重写全部四章，纠正按钮名称、素材编号、数据库和导出路径、恢复方式。禁止出现M1-001、待生成、保存并生成、data/projects、自动导出备份等错误。不要用英文writing指代界面选项。必须写出“理解目标并开始”“补充 / 修改素材”，引用M3对应片段。每章用150–250字的具体步骤，不要加入资料未说明的功能或状态。','scope':None},sid)
        started=time.monotonic();last=0
        while time.monotonic()-started<360:
            job=service.public_job(job['id'])
            if job['status'] not in ('running','queued'):break
            if time.monotonic()-last>15:print(job['progress'],flush=True);last=time.monotonic()
            time.sleep(.5)
        if job['status']!='completed':raise RuntimeError(job['error'] or 'Review deadline exceeded')
        text='\n'.join(d['after'] for d in job['result']['diffs'])
        if any(word in text for word in ('M1-001','待生成','保存并生成','data/projects','data\\projects')):raise RuntimeError('Known invented details remain; proposal was not adopted')
        if not all(word in text for word in ('理解目标并开始','补充 / 修改素材')):raise RuntimeError('Missing required real controls; proposal was not adopted')
        service.apply(job['id'],{'revision':view['revision']});after=store.view(sid)
        outputs={}
        for kind in ('md','zip'):
            export=service.export(sid,after['revision'],kind);dest=ROOT/'docs/examples'/f'工作室使用说明-资料校正版-v3.{kind}'
            shutil.copyfile(export['path'],dest);outputs[kind]=str(dest)
        proof['manual_review'].update({'correction_calls':job['result']['calls'],'known_invented_literals_removed':True,'required_control_names_present':True,'corrected_outputs':outputs,'final_editorial_review':'pending'})
        path.write_text(json.dumps(proof,ensure_ascii=False,indent=2),encoding='utf-8');print(json.dumps(outputs,ensure_ascii=False),flush=True)
    finally:
        service.close()
        if prior is None:os.environ.pop('INTENT_SILICONFLOW_API_KEY',None)
        else:os.environ['INTENT_SILICONFLOW_API_KEY']=prior


if __name__=='__main__':main()
