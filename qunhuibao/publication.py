"""Minimized publication contract. Raw chat archives never enter this payload."""
import base64
import copy
import re
from collections import Counter
from html import escape

from .validation import validate_report
from .keywords import build_topic_keywords
from .styles import ASSET_DIR, report_styles


def redact(text):
    text = re.sub(r'(?<!\d)1[3-9]\d{9}(?!\d)', '[手机号已遮盖]', text)
    text = re.sub(r'[\w.+-]+@[\w.-]+\.[A-Za-z]{2,}', '[邮箱已遮盖]', text)
    return re.sub(r'((?:微信号|微信|vx|wechat)\s*[:：]\s*)[A-Za-z][\w-]{5,19}', r'\1[已遮盖]', text, flags=re.I)


def make_publication(report, messages, date, quote_ids=(), mask_contacts=True):
    validate_report(report, messages)
    import datetime
    datetime.date.fromisoformat(date)
    selected = set(quote_ids)
    indexed = {m['id']: m for m in messages['messages']}
    refs = {ref for s in report['sections'] for i in s['items'] for ref in i['evidence_refs']}
    if selected - refs:
        raise ValueError('原话必须来自本期条目引用的消息')
    transform = redact if mask_contacts else lambda s: s
    sections = copy.deepcopy(report['sections'])
    for section in sections:
        for item in section['items']:
            item['authors'] = list(dict.fromkeys(transform(indexed[r]['sender']) for r in item.pop('evidence_refs')))
            for key, value in item.items():
                if isinstance(value, str):
                    item[key] = transform(value)
                elif isinstance(value, list):
                    item[key] = [transform(v) for v in value]
    counts = Counter(transform(m['sender']) for m in messages['messages'])
    night = Counter(transform(m['sender']) for m in messages['messages'] if re.search(r'(?:T|\s)(?:0[0-5]):', m['timestamp']))
    return validate_publication({
        'schema_version': 1, 'date': date, 'conversation': transform(report['conversation']),
        'title': transform(report['title']), 'summary': transform(report['summary']),
        'period': transform(report['period']), 'sections': sections,
        'quotes': [{'sender': transform(indexed[r]['sender']), 'timestamp': indexed[r]['timestamp'], 'text': transform(indexed[r]['text'])} for r in dict.fromkeys(quote_ids)],
        'keywords': [{'term': transform(k['term']), 'count': k['message_count']} for k in build_topic_keywords(report, messages)],
        'stats': {'messages': len(indexed), 'participants': len(counts), 'speakers': counts.most_common(10), 'night': night.most_common(10)},
        'limitations': ['仅统计本机提供的记录，不保证覆盖群聊全部消息。'] + (['存在未读取附件；未据附件名称推断内容。'] if any(m['attachments'] for m in indexed.values()) else []),
    })


def validate_publication(p):
    import datetime
    import json
    fields = {'schema_version','date','conversation','title','summary','period','sections','quotes','keywords','stats','limitations'}
    if not isinstance(p, dict) or set(p) != fields or p['schema_version'] != 1:
        raise ValueError('发布格式不正确；仅接受结构化日报，不接受HTML或原始聊天')
    datetime.date.fromisoformat(p['date'])
    if len(json.dumps(p, ensure_ascii=False)) > 1_000_000:
        raise ValueError('单篇日报过大')
    for k in ('conversation','title','summary','period'):
        if not isinstance(p[k], str) or len(p[k]) > 20000 or (k != 'period' and not p[k].strip()):
            raise ValueError('日报文字字段不正确')
    if not isinstance(p['sections'], list) or not 1 <= len(p['sections']) <= 8:
        raise ValueError('栏目数量不正确')
    keys = set()
    allowed = {'title','body','kind','owner','due','status','question','answer','conditions','outcome','steps','authors'}
    for s in p['sections']:
        if not isinstance(s, dict) or set(s) != {'key','title','items'} or s['key'] in keys or s['key'] not in {'topics','decisions','actions','assets','questions','notices','highlights','tutorials'}:
            raise ValueError('栏目不正确')
        keys.add(s['key'])
        if not isinstance(s['title'], str) or not isinstance(s['items'], list) or len(s['items']) > 100:
            raise ValueError('栏目内容不正确')
        for i in s['items']:
            if not isinstance(i, dict) or not {'title','body','kind','authors'} <= set(i) or set(i) - allowed:
                raise ValueError('条目格式不正确')
            for k,v in i.items():
                if k in ('steps','authors'):
                    if not isinstance(v,list) or len(v)>100 or any(not isinstance(x,str) for x in v):
                        raise ValueError('条目列表不正确')
                elif not isinstance(v,str):
                    raise ValueError('条目文字不正确')
    for field, required in [('quotes', {'sender','timestamp','text'}), ('keywords', {'term','count'})]:
        if not isinstance(p[field], list) or len(p[field]) > 100:
            raise ValueError('原话/词云数量不正确')
        for v in p[field]:
            if not isinstance(v,dict) or set(v)!=required:
                raise ValueError('原话/词云格式不正确')
            for k,x in v.items():
                if (k=='count' and (type(x)!=int or x<0)) or (k!='count' and not isinstance(x,str)):
                    raise ValueError('原话/词云值不正确')
    st = p['stats']
    if not isinstance(st,dict) or set(st)!= {'messages','participants','speakers','night'}:
        raise ValueError('统计不正确')
    for k in ('messages','participants'):
        if type(st[k])!=int or st[k]<0:
            raise ValueError('统计数量不正确')
    for k in ('speakers','night'):
        if not isinstance(st[k],list) or len(st[k])>10 or any(not isinstance(v,(list,tuple)) or len(v)!=2 or not isinstance(v[0],str) or type(v[1])!=int or v[1]<0 for v in st[k]):
            raise ValueError('榜单不正确')
    if not isinstance(p['limitations'],list) or any(not isinstance(x,str) for x in p['limitations']):
        raise ValueError('覆盖说明不正确')
    return p


def shell(title, body):
    logo = base64.b64encode((ASSET_DIR/'qunhuibao-logo.png').read_bytes()).decode()
    css = report_styles(editor=True)
    return f'<!doctype html><html lang="zh-CN"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1"><meta name="robots" content="noindex"><title>{escape(title)}</title><style>{css}</style></head><body class="share-page"><main class="wrap"><header class="brand-header"><img class="brand-logo" width="270" height="90" src="data:image/png;base64,{logo}" alt="群汇报"><div class="edition-mark"><b>群聊一键出日报</b></div></header>{body}<footer class="report-footer">群汇报 · qunhuibao.com</footer></main></body></html>'


def rich(text):
    """Only explicitly http(s) links become links; all other input is escaped."""
    return re.sub(r'https?://[^\s<>"\u3000，。；）]+', lambda m: '<a rel="noopener noreferrer" target="_blank" href="'+escape(m[0],quote=True)+'">'+escape(m[0])+'</a>', escape(text))


def render_publication(p, home=''):
    validate_publication(p)
    e=escape
    nav=''.join(f'<a href="#section-{n}"><span>{n+1:02}</span>{e(s["title"])}</a>' for n,s in enumerate(p['sections']) if s['items'])
    body=f'<section class="hero"><div><p class="meta">{e(p["date"])} · {e(p["period"])}</p><h1 class="group-title">{e(p["conversation"])}</h1><h2 class="issue-title">{e(p["title"])}</h2><p class="lead">{e(p["summary"])}</p></div><aside class="hero-aside">{nav}</aside></section>'
    body+='<div class="reader-actions"><button id="copy-digest">复制摘要</button><button id="export-image">下载长图</button><button id="print-digest">打印 / PDF</button><span id="reader-status" role="status"></span></div>'
    if home: body+=f'<p><a href="{e(home,quote=True)}">返回群主页 · 查看历史日报</a></p>'
    body+='<div class="share-search"><label for="share-search">搜索本期</label><input id="share-search" type="search" placeholder="输入关键词，点击结果定位"><button id="share-clear">清空</button></div><ul id="share-results"></ul>'
    st=p['stats']
    body+=f'<div class="edition-summary"><div class="edition-stats"><span><b>{st["messages"]}</b>条消息</span><span><b>{st["participants"]}</b>位参与者</span></div></div>'
    if p['keywords']:
        words=''.join(f'<button class="share-word" data-weight="{min(3,1+k["count"]//3)}" title="覆盖{k["count"]}条消息">{e(k["term"])}</button>' for k in p['keywords'])
        body+=f'<section class="topic-map"><strong>今日话题</strong><small> · 字号表示覆盖消息数</small><nav aria-label="话题入口">{words}</nav></section>'
    for n,s in enumerate(p['sections']):
        if not s['items']: continue
        grid='resources-grid' if s['key']=='assets' else 'topics-grid'
        body+=f'<section class="report-section" id="section-{n}"><div class="digest-section-heading"><span>{n+1:02}</span><h2>{e(s["title"])}</h2></div><div class="{grid}">'
        for i in s['items']:
            klass='resource-entry' if s['key']=='assets' else ('question-entry' if s['key']=='questions' else 'topic-entry')
            body+=f'<article class="edit-card {klass}"><h3 data-share-search>{e(i["title"])}</h3><p class="entry-authors">来源：{e("、".join(i["authors"]) or "AI建议，非群内事实")}</p><p class="share-body" data-share-search>{rich(i["body"])}</p>'
            for key,label in [('question','问题'),('answer','回答'),('conditions','适用条件'),('outcome','验证情况'),('owner','负责人'),('due','期限'),('status','状态')]:
                if i.get(key): body+=f'<div class="qa-answer"><b>{label}</b><p data-share-search>{rich(i[key])}</p></div>'
            if i.get('steps'): body+='<ol class="learning-steps">'+''.join(f'<li data-share-search>{rich(x)}</li>' for x in i['steps'])+'</ol>'
            body+='</article>'
        body+='</div></section>'
    if p['quotes']:
        body+='<section class="report-section"><div class="digest-section-heading"><h2>关键原话</h2></div>'
        for q in p['quotes']: body+=f'<blockquote class="edit-source"><div class="quote-person">{e(q["sender"])} <time>{e(q["timestamp"])}</time></div><p data-share-search>{rich(q["text"])}</p></blockquote>'
        body+='</section>'
    contributions=Counter(a for s in p['sections'] for i in s['items'] if i['kind']!='suggestion' for a in i['authors'])
    body+='<section class="report-section"><div class="digest-section-heading"><h2>贡献与群内趣味</h2></div><div class="resources-grid">'
    for title,rows,note in [('精华来源',contributions.most_common(10),'被本期精华引用的条目数，不代表贡献评分。'),('发言数量',st['speakers'],'仅表示发言条数，不代表内容价值。'),('夜间活跃',st['night'],'按消息本地时间00:00—05:59统计，不推断作息。')]:
        body+=f'<article class="edit-card"><h3>{title}</h3><p>{note}</p>'+''.join(f'<p>{e(name)} · {count}</p>' for name,count in rows)+'</article>'
    body+='</div></section><p>'+e(' '.join(p['limitations']))+'</p>'
    js=(ASSET_DIR/'publication.js').read_text(encoding='utf-8')
    image_js=(ASSET_DIR/'html2canvas.min.js').read_text(encoding='utf-8')
    return shell(p['conversation'],body+f'<script>{image_js}</script><script>{js}</script>')
