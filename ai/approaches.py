"""User-editable generation directions, separate from hard constraints."""
from core import Invalid

DEFAULTS={
    'auto':[('先做可用版','先解决核心用途，减少前期准备；交代主动放弃的内容'),('降低长期负担','优先容易维护、复用和持续执行；说明初期需要的准备'),('先验证再投入','优先用可检查的小步骤验证不确定事项，再逐步扩大投入')],
    'project':[('最快跑通闭环','优先实现一条端到端流程，明确暂缓功能和后续补齐条件'),('少维护、易持续','优先少依赖、易维护和可重复执行的方案，说明初期准备'),('为后续扩展准备','先划清模块和数据边界，再实现核心闭环，说明额外工作与必要性')],
    'study':[('边做边学','从可完成的小练习切入，每次引入必要知识并立刻应用'),('先补基础','先补齐先修知识，再逐步整合练习，给出每天可判定检查'),('围绕最终成果倒推','从最终交付拆出阶段练习和依赖，明确每一步为成品解决什么问题')],
    'writing':[('简洁直接','先说明来意与必要事实，减少铺垫，结尾给出明确回复请求'),('细节充分','交代必要背景、依据和具体诉求；遵守同一总字数限制'),('温和商量','保留不确定信息，语气尊重并给对方选择空间，不新增承诺')],
    'analysis':[('必要条件优先','先逐项排除不满足硬条件的方案，再给依据与不能推断的事项'),('可执行落地优先','在所有必要条件满足的前提下突出执行步骤与所需输入，不编造成本数据'),('不确定性与复验优先','突出证据缺口、不能推断的结论和最小复验，已知事实不改')]
}


def normalize(value, category='auto', draft=False):
    if value is None:return [{'name':n,'instruction':i} for n,i in DEFAULTS.get(category,DEFAULTS['auto'])]
    if not isinstance(value,list) or len(value)!=3:raise Invalid('请为三份候选各指定一个探索方向')
    clean=[]
    for item in value:
        if not isinstance(item,dict) or not isinstance(item.get('name'),str) or not (0 if draft else 1)<=len(item['name'].strip())<=40 or not isinstance(item.get('instruction'),str) or not (0 if draft else 2)<=len(item['instruction'].strip())<=400:
            raise Invalid('方向名称1–40字，方向要求2–400字')
        clean.append({'name':item['name'].strip(),'instruction':item['instruction'].strip()})
    if not draft and len({x['name'] for x in clean})!=3:raise Invalid('三个方向名称不能相同')
    return clean
