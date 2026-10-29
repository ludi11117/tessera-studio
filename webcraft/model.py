"""A closed component schema: model output is data, never executable source."""
import copy
import hashlib
import json
from urllib.parse import urlsplit
from core import Invalid

VERSION='tessera-page-v1'
IDS=('nav','hero','projects','contact')
LAYOUTS=('quiet','editorial','compact')
PALETTES=('paper','ink','sage')
FIELDS={'nav':('title',),'hero':('title','body'),'projects':('title','body'),'contact':('title','body','url')}

def digest(value):
    return hashlib.sha256(json.dumps(value,ensure_ascii=False,sort_keys=True,separators=(',',':')).encode()).hexdigest()

def string(value,limit=1600,empty=False):
    if not isinstance(value,str) or len(value)>limit or (not empty and not value.strip()):raise Invalid('文字为空或超出长度限制')
    return value.strip()

def validate(doc):
    if not isinstance(doc,dict) or set(doc)!={'version','brief','components'} or doc['version']!=VERSION:raise Invalid('网页结构版本无效')
    string(doc['brief'])
    if not isinstance(doc['components'],dict) or set(doc['components'])!=set(IDS):raise Invalid('网页需要导航、介绍、项目和联系四个组件')
    for cid,c in doc['components'].items():
        if not isinstance(c,dict) or set(c)!={'layout','palette','content'}:raise Invalid('组件结构无效')
        if c['layout'] not in LAYOUTS or c['palette'] not in PALETTES:raise Invalid('未知布局或色调')
        if not isinstance(c['content'],dict) or set(c['content'])!=set(FIELDS[cid]):raise Invalid('组件文案字段无效')
        for k,v in c['content'].items():string(v,120 if k=='title' else 1600,empty=k=='url')
        url=c['content'].get('url','')
        if url:
            parsed=urlsplit(url)
            if any(ch.isspace() for ch in url) or parsed.scheme not in ('https','mailto') or (parsed.scheme=='https' and (not parsed.netloc or parsed.username or parsed.password)) or (parsed.scheme=='mailto' and ('@' not in parsed.path or parsed.netloc or parsed.query or parsed.fragment)):
                raise Invalid('联系地址使用完整HTTPS链接或mailto邮箱地址')
        if cid=='projects' and not 1<=len([s for s in c['content']['body'].splitlines() if s.strip()])<=6:raise Invalid('项目内容需为1–6行，每行一个项目')
    return doc

def create(body):
    name=string(body.get('name',''),60);title=string(body.get('title',''),120);brief=string(body.get('brief',''))
    projects=string(body.get('projects',''));contact=string(body.get('contact','欢迎交流我的项目与想法。'))
    contents={'nav':{'title':name},'hero':{'title':title,'body':brief},'projects':{'title':'精选项目','body':projects},'contact':{'title':'让想法继续发生。','body':contact,'url':body.get('url','')}}
    return validate({'version':VERSION,'brief':brief,'components':{cid:{'layout':'quiet','palette':'paper','content':contents[cid]} for cid in IDS}})

def patch(doc,patches,locks):
    if not isinstance(patches,list) or not 1<=len(patches)<=12:raise Invalid('每次需要1–12项明确改动')
    after=copy.deepcopy(doc);seen=set();changes=[]
    for p in patches:
        if not isinstance(p,dict) or set(p)!={'component','field','value'}:raise Invalid('修改格式无效')
        cid,field=p['component'],p['field'];key=f'{cid}.{field}'
        if cid not in IDS or field not in ('layout','palette','content') or key in seen:raise Invalid('修改对象无效或重复')
        seen.add(key);before=doc['components'][cid][field]
        if p['value']!=before:
            if key in locks:raise Invalid('已保留这部分，请先明确允许修改：'+key)
            after['components'][cid][field]=copy.deepcopy(p['value']);changes.append({'component':cid,'field':field,'before':before,'after':p['value']})
    validate(after)
    if not changes:raise Invalid('内容没有变化')
    for key,expected in locks.items():
        cid,field=key.split('.')
        if digest(after['components'][cid][field])!=expected:raise Invalid('保留条件不满足：'+key)
    return after,changes

def receipt(before,after,changes):
    touched={c['component']+'.'+c['field'] for c in changes}
    checks=[{'path':cid+'.'+field,'before_hash':digest(before['components'][cid][field]),'after_hash':digest(after['components'][cid][field]),'unchanged':before['components'][cid][field]==after['components'][cid][field]} for cid in IDS for field in ('layout','palette','content') if cid+'.'+field not in touched]
    return {'compiler':VERSION,'before_hash':digest(before),'after_hash':digest(after),'changed_paths':sorted(touched),'outside_patch':checks,'outside_unchanged':all(c['unchanged'] for c in checks)}
