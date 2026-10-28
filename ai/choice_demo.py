"""Developer-written example, visibly marked; never a successful model output."""
from core import Invalid


TITLE='组合定制示例｜邀请邮件'


def task():
    intro=[
        '林老师您好！我们正在筹备校园数据可视化工作坊，想邀请您参加案例点评。希望借助您的专业意见，帮助同学更清楚地表达数据与呈现分析思路。',
        '林老师您好！我们正在筹备校园数据可视化工作坊，诚邀您参与案例点评。我们希望把同学已有的可视化作品作为交流起点，请您从表达是否清晰、图表是否贴合问题等角度给出建议。相较于安排完整授课，这次邀请更侧重具体作品的讨论，也方便同学根据点评继续改进。',
        '林老师您好！想请您看看我们的校园数据可视化工作坊安排，若时间方便，诚邀您参与案例点评。我们希望同学不只展示图表，也能说清问题、依据和表达取舍。点评环节拟围绕作品展开，您可以选择熟悉的案例给出建议。具体点评方式仍可与您商量，我们会根据您的意见完善后续安排，避免给您增加不必要的准备负担。'
    ]
    closing=[
        '工作坊计划于11月6日14:00–15:30在实验楼B204举行，名额尚未确认。若您方便参加，烦请回复。',
        '工作坊拟于11月6日14:00–15:30在实验楼B204举行，名额尚未确认。如您愿意参加，也欢迎告知您更方便的点评方式；我们会先与您核对安排，再作后续准备。',
        '目前计划的时间是11月6日14:00–15:30，地点为实验楼B204，名额尚未确认。请您先回复是否方便参加。如有时间冲突或希望采用其他点评方式，也可以直接提出，我们会进一步沟通，以双方确认的安排为准。'
    ]
    return {'title':TITLE,'brief':'开发者编写的组合体验，不是模型成功案例或真实用户成果。为活动邀请选择合适背景与安排说明，正文总长140–190字符，保留“名额尚未确认”。先试着保留喜欢的一章，再让系统补齐其余。',
            'source':'example','category':'writing','facts':{},'materials':[],
            'blocks':[{'id':'intro','title':'邀请与背景','variants':[{'id':'intro-'+str(j),'template':text} for j,text in enumerate(intro)]},
                      {'id':'closing','title':'安排与回复','variants':[{'id':'closing-'+str(j),'template':text} for j,text in enumerate(closing)]}],
            'ai':{'candidate_labels':['直接说明来意','展开点评内容','保留协商空间'],'blueprint':{'assumptions':['所有文字由开发者为演示编写，不代表模型交付质量。']}}}


def seed(store):
    sid=next((s['id'] for s in store.sessions() if s['title']==TITLE and s['source']=='example'),None)
    if sid:return sid
    sid=store.create(task())
    store.action(sid,{'kind':'acceptance','revision':0,'contract':{'length':{'min':140,'max':190},'required':['名额尚未确认'],'manual':['语气是否适合收件人、安排是否准确，需人工确认。']}})
    return sid
