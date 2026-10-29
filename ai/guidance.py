"""Grounded novice intake. Rule-based questions, no model calls or inferred labels."""
from core import Invalid

VERSION = 'guided-intent-v1'
CATALOG = {
 'writing': {'name':'写作与沟通','base':'writing','questions':[
   {'id':'audience','title':'这份内容主要给谁看？','options':['老师或导师','同学或朋友','合作对象','公开读者']},
   {'id':'outcome','title':'希望对方看完之后做什么？','options':['了解情况','回复或确认','考虑合作','按步骤操作']},
   {'id':'direction','title':'哪种表达更接近你想要的？','examples':[
     {'name':'直接说明','text':'您好，想邀请您参与这次交流。如果方便，期待收到您的回复。','value':'先说明来意，表达简洁直接'},
     {'name':'留出商量空间','text':'您好，想先和您商量一下交流安排。参与方式可以根据您的情况再一起确定。','value':'语气温和，留出选择与协商空间'}]},
   {'id':'done','title':'拿到什么程度，你才会觉得能用了？','options':['可直接发送的完整正文','先给结构，再补内容','保留全部已知事实，标出待确认处']}]},
 'study': {'name':'学习与练习','base':'study','questions':[
   {'id':'starting','title':'现在学到哪里，最容易卡在哪里？','options':['刚开始，需要先补基础','懂一些，但不会独立做','已经会做，需要查漏补缺']},
   {'id':'time','title':'能投入多久？不知道也可以暂时跳过。','options':[]},
   {'id':'direction','title':'哪种学习过程更适合你？','examples':[
     {'name':'先动手','text':'先做一个小练习，遇到问题再补相关知识，用结果检查自己。','value':'以练习或小作品为起点，边做边补知识'},
     {'name':'先理解','text':'先把关键概念讲清楚，再做对应练习，最后用小测试检查。','value':'先补必要概念，再练习与自测'}]},
   {'id':'done','title':'你想用什么判断自己学会了？','options':['能独立做出作品','能做对对应题目','能解释并应用关键概念']}]},
 'project': {'name':'项目与产品方案','base':'project','questions':[
   {'id':'audience','title':'谁会使用它，先解决哪一个问题？','options':[]},
   {'id':'boundary','title':'有什么必须保留或现实限制？','options':['先做一个能验证的核心流程','优先便于后续维护','功能范围先帮我梳理']},
   {'id':'direction','title':'先从哪个具体角度找灵感？','examples':[
     {'name':'从使用过程开始','text':'用户进入 → 完成一个关键操作 → 看到结果。先把这条过程讲清楚。','value':'从用户操作流程倒推最小功能与验收'},
     {'name':'从已有想法开始','text':'把现有想法分成：必须保留、可以尝试、暂不做，再安排实施顺序。','value':'整理现有想法，区分保留项、探索项和暂缓项'}]},
   {'id':'done','title':'这次希望先拿到哪份具体成果？','options':['功能范围与页面/流程说明','可执行的实施计划与验收清单','供继续开发的需求说明']}]},
 'analysis': {'name':'分析与选择','base':'analysis','questions':[
   {'id':'decision','title':'你最后需要做哪个决定？','options':[]},
   {'id':'boundary','title':'什么条件绝对不能突破？','options':['只依据已有资料','先排除不符合必要条件的选项','暂时没有，先帮我发现关键条件']},
   {'id':'direction','title':'哪种对照更容易帮助你判断？','examples':[
     {'name':'按条件筛选','text':'把每个选项是否满足必要条件并排列出，再看剩下的取舍。','value':'先检查必要条件，再解释可行选项之间的取舍'},
     {'name':'按证据对照','text':'分别列出已知证据、不能确定的事项，以及补哪条信息会改变选择。','value':'区分证据与未知，说明哪些补充信息会改变结论'}]},
   {'id':'done','title':'最终结果需要包含什么？','options':['推荐与理由、适用边界','并排比较与证据缺口','下一步验证动作']}]},
 'career': {'name':'求职与自我表达','base':'writing','questions':[
   {'id':'audience','title':'这份材料主要给谁看？','options':['招聘者或筛选者','面试官','内推人或学长学姐','公开主页的访客']},
   {'id':'outcome','title':'希望对方看完之后做什么？','options':['愿意联系你','给你一次面试','记住你的一个能力','了解你的经历']},
   {'id':'direction','title':'哪种表达更接近你想要的？','examples':[
     {'name':'先给证据','text':'先用一个具体项目说明我能做什么，再补充与岗位相关的经历和合作方式。','value':'先用具体项目与结果证明能力，再说明与这次机会的关系'},
     {'name':'先讲动机','text':'先说为什么想做这件事，再用经历说明自己已经为此准备了什么。','value':'先讲清楚动机与方向，再用经历和行动提供依据'}]},
   {'id':'done','title':'拿到什么程度，你才会觉得能用了？','options':['可直接投递或发送的完整版本','先给结构和要点','保留真实经历，标出待补内容']}]},
 'life': {'name':'生活与安排','base':'project','questions':[
   {'id':'scene','title':'这次要安排什么？','options':['一次出行','一场活动或聚会','一段日常计划','一件要办成的事']},
   {'id':'boundary','title':'哪些条件不能忽略？','options':['时间和预算有限','需要照顾同行的人','先保证能执行','希望留出弹性']},
   {'id':'direction','title':'哪种安排更接近你想要的？','examples':[
     {'name':'稳妥可执行','text':'先把时间、地点和必须完成的事排清楚，再给一个遇到变化时的备选。','value':'先保证每个环节能执行，再补备选与弹性'},
     {'name':'体验优先','text':'先保留最想体验的部分，再围绕它安排时间、预算和交通。','value':'先确定最想体验的内容，再倒推时间与预算'}]},
   {'id':'done','title':'拿到什么程度，你才会觉得能用了？','options':['可直接照着做的时间表','带预算和备选的清单','先给一版再调整']}]},
 'content': {'name':'内容与创作','base':'writing','questions':[
   {'id':'channel','title':'内容准备发在哪里？','options':['社交平台','公众号或长文','视频口播','个人作品集']},
   {'id':'outcome','title':'希望读者看完做什么？','options':['记住一个观点','愿意互动或转发','了解你的作品','按步骤尝试']},
   {'id':'direction','title':'哪种内容更接近你想要的？','examples':[
     {'name':'从一个具体场景开始','text':'先写一个人人都遇到过的具体场景，再引出你的做法和结果。','value':'用具体场景或故事开头，再落到做法与结果'},
     {'name':'从一个明确观点开始','text':'先把最想说的判断放在开头，再用三个具体依据支撑。','value':'先给明确观点，再用具体依据和例子展开'}]},
   {'id':'done','title':'拿到什么程度，你才会觉得能用了？','options':['可直接发布的完整文案','标题与正文','先给选题和结构']}]}}


def base_type(category):
    return CATALOG.get(category, {}).get('base', 'project')


def normalize(value, goal=None):
    if value is None:return None
    if not isinstance(value, dict) or value.get('version') != VERSION or value.get('category') not in CATALOG:
        raise Invalid('需求卡格式无效，请重新整理')
    clean = {'version': VERSION, 'category': value['category']}
    if type(value.get('confirmed',False)) is not bool:raise Invalid('需求卡确认状态无效')
    clean['confirmed']=value.get('confirmed',False)
    for key, limit in [('goal',6000),('keep',1000),('change',1000),('criteria',1000)]:
        text = value.get(key, '')
        if not isinstance(text,str) or len(text)>limit:raise Invalid('需求卡内容过长或格式无效')
        clean[key]=text.strip()
    if goal is not None and clean['goal']!=goal.strip():raise Invalid('目标已变化，请更新需求卡或移除后再开始')
    questions = CATALOG[clean['category']]['questions'];known={q['id'] for q in questions}
    answers=value.get('answers', {})
    if not isinstance(answers,dict) or set(answers)-known:raise Invalid('需求卡问题已变化，请重新整理')
    if any(v is not None and (not isinstance(v,str) or not 1<=len(v.strip())<=500) for v in answers.values()):raise Invalid('每项回答最多500字；未确定时请选择跳过')
    clean['answers']={k:v.strip() if isinstance(v,str) else None for k,v in answers.items()}
    reference=value.get('inspiration')
    if reference is not None:
        import re
        if not isinstance(reference,dict) or not re.fullmatch(r'[a-f0-9]{32}',str(reference.get('job',''))) or not re.fullmatch(r'direction-[0-2]',str(reference.get('choice',''))) or not re.fullmatch(r'[a-f0-9]{64}',str(reference.get('context_hash',''))):raise Invalid('灵感选择记录无效，请重新选择')
        clean['inspiration']={k:reference[k] for k in ('job','choice','context_hash')}
        if reference.get('confirmed_context_hash') is not None:
            if not re.fullmatch(r'[a-f0-9]{64}',str(reference['confirmed_context_hash'])):raise Invalid('灵感需求确认记录无效')
            clean['inspiration']['confirmed_context_hash']=reference['confirmed_context_hash']
    return clean


def context(value):
    if not value:return None
    questions=CATALOG[value['category']]['questions']
    return {'version':VERSION,'original_idea':value['goal'],'category':value['category'],
            'explicit_answers':[{'question':q['title'],'answer':value['answers'][q['id']]} for q in questions if value['answers'].get(q['id'])],
            'unresolved':[q['title'] for q in questions if not value['answers'].get(q['id'])],
            'keep':value['keep'],'change':value['change'],'user_acceptance':value['criteria'],'inspiration':value.get('inspiration'),
            'boundary':'只有明确回答代表用户要求。跳过与未回答不是同意默认值；不得把示例文字当成用户事实。保留要求只在已有材料与文字支持时落实，无法确认的内容列为待确认。'}
