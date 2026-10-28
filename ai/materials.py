"""Immutable material IDs survive add/remove/reorder and keep citations stable."""
import hashlib
import re

from core import Invalid
from ai.retrieval import prepare


def reconcile(incoming,previous=(),counter=0):
    prepare(incoming)
    old={m['id']:m for m in previous}
    counter=max([counter]+[int(k[1:]) for k in old if re.fullmatch(r'M[1-9][0-9]*',k)])
    result=[];seen=set()
    for item in incoming:
        name=item['name'].strip();text=item['text'].strip()
        if not name or not text:raise Invalid('素材名称与正文不能为空')
        mid=item.get('id')
        if mid is not None and (mid not in old or mid in seen):raise Invalid('素材版本不存在或重复，请重新载入')
        if mid is not None:seen.add(mid)
        if mid is None or (name,text)!=(old[mid]['name'],old[mid]['text']):
            counter+=1;mid=f'M{counter}'
        seen.add(mid)
        result.append({'id':mid,'name':name,'text':text,'sha256':hashlib.sha256(text.encode()).hexdigest()})
    return result,counter


def initial(materials):
    prepare(materials)
    if len({m.get('id') for m in materials if m.get('id')})!=sum(bool(m.get('id')) for m in materials):raise Invalid('素材版本重复')
    # Accept IDs only when reconstructing an already validated library.
    if materials and all(re.fullmatch(r'M[1-9][0-9]*',str(m.get('id',''))) for m in materials):
        return reconcile(materials,materials)[0]
    return reconcile([{k:m[k] for k in ('name','text')} for m in materials])[0]
