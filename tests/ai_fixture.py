"""Deliberately synthetic provider fixture. Never used by production startup."""
import json
import time


def fixture_transport(path,payload=None):
    if path.startswith('/models'):
        return {"data":[{"id":"test/fixture-model"}]}
    request=json.loads(payload['messages'][-1]['content'])
    operation=request['operation']
    if operation=='仅改写选中的文字':
        count=2 if '恰好2个' in request['requirements'] else 1
        value={'options':[{'label':'开发版本'+str(i+1),'replacement':request['selected_text']+('（表达更清楚）' if i==0 else '（换一种表达）')} for i in range(count)]}
    elif operation=='围绕当前需求探索具体灵感':
        idea=request['intent_brief']['original_idea']
        value={'directions':[{'name':name,'instruction':instruction,'preview':idea+'：'+example,'tradeoff':tradeoff,'basis_quotes':[{'id':'goal','quote':idea[:160]}]} for name,instruction,example,tradeoff in [('先跑通核心','先实现本次目标的核心流程，再检查结果','先确认输入、完成核心操作、检查输出。','优先可验证，暂缓扩展。'),('先核对边界','先核对当前资料与限制，再确定实施顺序','把已知条件、未知事项、下一步核对动作列清楚。','优先减少不确定性，细节需进一步补齐。')]]}
    elif operation=='分析交付需求':
        value={"title":"校园失物招领 · 四周实施方案","objective":"交付一个可演示、可验收的本地原型","audience":"有Python基础的学生","sections":["目标与边界","核心实现","实施与验收"],"assumptions":["先服务一个校区的小范围试用"],"questions":["准备先邀请哪些同学试用？"]}
    elif operation=='生成可交付的三种候选':
        facts=' '.join('{{'+k+'}}' for k in request['facts'])
        cite=' [M1#1]' if request.get('sources') else ''
        value={"title":"校园失物招领 · 四周实施方案","candidate_labels":["先验证需求","先做最小闭环","先建立数据流程"],"blocks":[
            {"title":"目标与边界","variants":[facts+' 从一个校区开始，访谈三位实际丢过物品的同学，明确发布、匹配与认领的必要信息。'+cite,facts+' 先做发布、搜索、认领三个流程，每一步给出明确的完成状态。'+cite,facts+' 先收集匿名案例，整理地点、时间与物品特征，检查字段是否支持匹配。'+cite]},
            {"title":"核心实现","variants":["使用Python与SQLite保存物品，先做发布和搜索页面。人工确认匹配结果，不公开联系方式。","使用Python与SQLite实现发布、搜索、认领状态，并记录每次状态变更。","使用Python整理字段和数据校验，建立去重规则，再接一个最小网页入口。"]},
            {"title":"实施与验收","variants":["- 第1周：确认需求与字段。\n- 第2周：完成发布搜索。\n- 第3周：邀请试用。\n- 第4周：修复问题。\n验收：新用户可以独立走通发布到认领。","- 先完成一条端到端流程，再补错误提示。\n- 用10条虚构案例验收，不把测试记录称为真实用户。","- 先检查缺失、重复与错误字段。\n- 验收数据校验后，再测试页面与状态恢复。"]}]}
    elif operation=='独立验收当前文稿':
        value={'findings':[],'uncertain':['开发模拟检查，不代表真实内容质量。']}
    elif operation=='按验收失败项修正文稿':
        required=request['contract'].get('required',[])
        forbidden=request['contract'].get('forbidden',[])
        changes=[]
        for bid in request['allowed_blocks']:
            text=next(b['template'] for b in request['current_document'] if b['id']==bid)
            for phrase in forbidden:text=text.replace(phrase,'')
            for phrase in required:
                if phrase not in text:text+='\n'+phrase
            changes.append({'block':bid,'text':text})
        value={'summary':'模拟修正明确短语条件','changes':changes}
    else:
        if request.get('instruction')=='测试重试：首次断线' and not getattr(fixture_transport,'failed_once',False):
            fixture_transport.failed_once=True
            from ai.provider import ProviderError
            raise ProviderError('测试用连接中断，请重试')
        bid=request['allowed_blocks'][0]
        current=next(b for b in request['current_document'] if b['id']==bid)
        value={"summary":"补充了可执行的步骤与验收方式，保留其他内容。","changes":[{"block":bid,"text":current['template']+'\n- 新增验收：用三条测试案例检查输入、输出和错误恢复。'}],"questions":[]}
    return {"choices":[{"message":{"content":json.dumps(value,ensure_ascii=False)},"finish_reason":"stop"}],"usage":{"prompt_tokens":100,"completion_tokens":300,"total_tokens":400},"_latency_ms":10}
