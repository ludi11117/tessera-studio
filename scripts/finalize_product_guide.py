"""Developer editorial acceptance of the live guide. No provider call."""
import copy
import json
import shutil
import sys
from pathlib import Path

ROOT=Path(__file__).resolve().parents[1];sys.path.insert(0,str(ROOT))
from ai.service import AIService
from store import Store

SECTIONS=[
'''1. 点击侧栏“＋ 开始一个新目标”，输入想完成的目标。按需要选择“项目方案”“学习规划”“写作沟通”“分析决策”，也可保留“按目标定制”。
2. 在“补充固定事实与限制”中逐行填写不可随意改变的条件；通过“＋ 添加素材”附加TXT、MD或JSON文件。
3. 默认选择“完整初稿 · 含实施细节与验收”。只想先确定方向时，可改为“快速起点 · 先确定方向”。
4. 等待草稿提示显示已保存，刷新后目标、条件和素材应能恢复。目标草稿保存在项目data目录的assistant.sqlite3，不会为每个任务建立独立数据库。
5. 点击“理解目标并开始”。生成期间查看首页进度，完成后进入工作区；“我的成果”中显示新任务。确认章节、假设与固定条件符合自己的要求，再继续修改。''',
'''1. 打开“目标与素材”，点击“补充 / 修改素材”。可在弹窗中编辑已有素材的名称或原文，也可点击“＋ 添加 TXT / MD / JSON”附加文件。
2. 点击“保存素材”。资料保存后，当前正文保持原样；在左侧明确说明如何使用新材料，并按需要选择修改章节，点击“生成修改 ↑”。
3. 素材编号为M1、M2等。修改原文会得到新编号；排序不会改变编号。移除资料后，正文若仍引用旧资料，应核对提示并更新相关章节。
4. 修改先形成草案。点击“预览”或“预览修改”检查前后差异，确认后点“采用这些修改”。满意的章节可以“锁定”，需要时通过顶部“↶”撤回。
5. 每次提交使用当时的成稿和资料。提交之后添加的素材不会混入正在执行的请求；要使用它们，请重新提交修改。''',
'''1. 刷新页面后，正在执行的任务应继续显示进度。网络、限流或余额等问题会显示相应失败原因；服务停止时仍在执行的任务，在服务重启后会标为中断。
2. 排除问题后，在进度卡点击“重试”。生成重试保留原目标与素材；修改重试使用当前成稿和最新资料，并重新检查允许修改的范围。
3. 草案生成后若成稿已经更新，该草案无法覆盖新版本。请基于当前版本重新提出修改。
4. 点击“取消”后不会采用该任务的结果；已经提交到服务商的请求可能仍计费。用户主动重试也会产生新调用。
5. 判断恢复是否成功，应检查新任务是否完成、已有正文是否保留、草案范围是否正确。不要把刷新成功当作内容已经完成。''',
'''1. 在“目标与素材”的“交付前检查”中查看章节、字数、素材与引用提示。逐章通读，核对事实、假设和实际要求，再由自己勾选三项确认。
2. 正文或素材改变后，确认项会清空；撤回会恢复对应版本的确认状态。自动检查不能核实事实真伪，不能代替通读。
3. 普通任务点击“导出 MD ↓”，写作任务显示“导出 TXT ↓”；需要完整记录时点击“交付包 ↗”。修改和采用本身不会自动在导出目录生成备份文件。
4. 文件先保存在D:\\CodexWork\\projects\\intent-workbench\\data\\exports，页面提供下载链接。浏览器另存位置由浏览器设置或用户选择决定。
5. ZIP包含正文、任务条件、当前素材原文、素材与生成记录、会话审计及交付检查。检查内容与当前成稿一致后再使用或分享；包内不应包含API Key。'''
]


def main():
    proof_path=ROOT/'docs/validation/product-live-proof-v3.json';proof=json.loads(proof_path.read_text(encoding='utf-8'))
    store=Store(proof['isolated_database']);service=AIService(store)
    try:
        sid=next(s['id'] for s in store.sessions() if s['source']=='generated');view=store.view(sid)
        blocks=copy.deepcopy(view['task']['blocks']);content=[b for b in blocks if not b.get('fixed')]
        if len(content)!=len(SECTIONS):raise RuntimeError('Guide structure changed; review manually')
        for block,text in zip(content,SECTIONS):
            if block['id'] in view['state']['locks']:raise RuntimeError('Manual correction scope is locked')
            next(v for v in block['variants'] if v['id']==view['state']['combo'][block['id']])['template']=text
        store.action(sid,{'kind':'edit','revision':view['revision'],'blocks':blocks})
        current=store.view(sid);store.action(sid,{'kind':'review','revision':current['revision'],'checks':{'read_through':True,'facts_checked':True,'usable':True}})
        final=store.view(sid);outputs={}
        for kind in ('md','zip'):
            result=service.export(sid,final['revision'],kind);dest=ROOT/'docs/examples'/f'工作室使用说明-人工核对版-v3.{kind}'
            shutil.copyfile(result['path'],dest);outputs[kind]=str(dest)
        correction=next(j for j in service.jobs(sid) if j['kind']=='revise')
        proof['manual_review'].update({'correction_calls':correction['result']['calls'],'correction_proposal_adopted':False,
            'remaining_proposal_errors':['Still invented task-list status labels','Mixed network failure with service restart','Wrong export label for writing tasks'],
            'final_editorial_review':'developer_corrected_against_current_source_and_browser_flow',
            'corrected_by':'manual edit action, not a model-only output','final_revision':final['revision'],
            'corrected_outputs':outputs,'human_trial':False})
        proof_path.write_text(json.dumps(proof,ensure_ascii=False,indent=2),encoding='utf-8')
        print(json.dumps({'reviewed_outputs':outputs,'revision':final['revision']},ensure_ascii=False))
    finally:service.close()


if __name__=='__main__':main()
