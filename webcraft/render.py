"""Compile an allowlisted document into standalone, script-free HTML."""
from html import escape
from pathlib import Path
from webcraft.model import IDS,validate,digest,VERSION

CSS=Path(__file__).resolve().parents[1]/'static/web-render.css'

def render(doc,preview=False):
    validate(doc);chunks=[]
    for cid in IDS:
        c=doc['components'][cid];v={k:escape(x,quote=True) for k,x in c['content'].items()}
        attrs=f'id="{cid}" data-component="{cid}" class="component {cid} layout-{c["layout"]} palette-{c["palette"]}"'
        if cid=='nav':body=f'<a class="brand" href="#hero">{v["title"]}<span>®</span></a><div class="nav-links"><a href="#projects">项目</a><a href="#contact">联系 ↗</a></div>'
        elif cid=='hero':body=f'<div class="eyebrow">独立想法 · 实际作品</div><h1>{v["title"]}</h1><p class="intro">{v["body"]}</p><a class="cta" href="#projects">探索我的项目 <span>↘</span></a><div class="hero-mark" aria-hidden="true">↗</div>'
        elif cid=='projects':
            cards=[]
            for i,line in enumerate(c['content']['body'].splitlines()):
                if not line.strip():continue
                title,sep,body=line.partition('｜')
                cards.append(f'<article class="project"><span class="project-index">{len(cards)+1:02d}</span><div><h3>{escape(title.strip())}</h3><p>{escape(body.strip()) if sep else ""}</p></div><span class="project-arrow" aria-hidden="true">↗</span></article>')
            body=f'<div class="section-label">SELECTED WORK</div><h2>{v["title"]}</h2><div class="projects-grid">{"".join(cards)}</div>'
        else:
            link=f'<a class="cta" href="{v["url"]}">联系我 ↗</a>' if v['url'] else '<a class="cta" href="#hero">回到顶部 ↑</a>'
            body=f'<div class="section-label">NEXT CHAPTER</div><h2>{v["title"]}</h2><p>{v["body"]}</p>{link}'
        tag='nav' if cid=='nav' else 'section';chunks.append(f'<{tag} {attrs}>{body}</{tag}>')
    styles='<link rel="stylesheet" href="/web-render.css">' if preview else '<style>'+CSS.read_text(encoding='utf-8')+'</style>'
    policy="default-src 'none'; style-src 'self' 'unsafe-inline'; base-uri 'none'; form-action 'none'"
    return f'<!doctype html><html lang="zh-CN"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width, initial-scale=1"><meta http-equiv="Content-Security-Policy" content="{policy}"><meta name="generator" content="{VERSION}"><title>{escape(doc["components"]["nav"]["content"]["title"])} · 作品集</title>{styles}</head><body><main>{"".join(chunks)}</main><footer>用作品表达自己。<span>Tessera · 拾构</span></footer></body></html>'

def evidence(doc):
    return {'compiler':VERSION,'document_hash':digest(doc),'html_sha256':__import__('hashlib').sha256(render(doc).encode()).hexdigest(),'script_free':True,'external_assets':0,'component_ids':list(IDS),'checks':['closed_schema','escaped_text','allowed_contact_url','four_components','one_to_six_projects'],'limits':['Checks do not establish factual truth or user satisfaction.','Property preservation does not promise pixel-identical geometry when content length changes.']}
