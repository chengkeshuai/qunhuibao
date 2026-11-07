"""Render validated group reports with a fixed, offline brand template.

Chat content is escaped text or inert data attributes. IDs are generated;
input is never inserted into executable script or CSS.
"""
from __future__ import annotations

import base64
from html import escape
import json
from pathlib import Path
import re

from .terminology import review_terms
from .keywords import build_topic_keywords, split_reply
from .styles import report_styles


ASSET_DIR = Path(__file__).resolve().parent / "assets"
SECTIONS = (
    ("topics", "主题精华", "归纳讨论的主题与关键观点"),
    ("tutorials", "经验与方法", "有原文依据的做法与适用条件"),
    ("notices", "通知与活动", "时间、参与方式和限制以原文为准"),
    ("highlights", "精彩对话", "保留真实表达，不编造金句"),
    ("decisions", "已定事项", "记录有聊天依据的决定"),
    ("actions", "行动清单", "把下一步拆成具体动作"),
    ("assets", "可复用资产", "保留资料、方法与经验"),
    ("questions", "待确认", "看清尚未解决的问题"),
)
KIND_LABELS = {
    "fact": "聊天事实",
    "decision": "已定事项",
    "action": "待办行动",
    "asset": "可复用资产",
    "question": "待确认",
    "suggestion": "AI 建议 · 非已确认事实",
}


def _text(value: object) -> str:
    return escape(str(value), quote=True)


def _attachment_text(value: object) -> str:
    if isinstance(value, str):
        return value
    kinds = {"file": "文件", "image": "图片", "video": "视频", "audio": "音频", "voice": "语音"}
    return f"{kinds.get(value.get('kind'), '附件')} · {value.get('name') or '未命名附件'}（仅记录，未读取内容）"


def _display_text(value: str) -> str:
    # HTML parsers normalize newlines; alias offsets must follow displayed text.
    return value.replace("\r\n", "\n").replace("\r", "\n")


def _utf16_length(value: str) -> int:
    return len(value.encode("utf-16-le")) // 2


def _field(text: str, field_id: str, aliases: list | None = None, offset: int = 0) -> str:
    """Text-only field plus approved, occurrence-bound aliases; never script data."""
    records = []
    for alias in aliases or []:
        start, end = alias["start"] - offset, alias["end"] - offset
        if 0 <= start < end <= len(text) and text[start:end] == alias["original"]:
            records.append({"start": _utf16_length(_display_text(text[:start])),
                            "end": _utf16_length(_display_text(text[:end])),
                            "original": _display_text(alias["original"]), "canonical": alias["canonical"]})
    data = f' data-aliases="{_text(json.dumps(records, ensure_ascii=False))}"' if records else ""
    return f'<span id="{field_id}" data-search-field{data}>{_text(_display_text(text))}</span>'


def _date_time(timestamp: str) -> tuple[str, str]:
    day = re.search(r"(?<!\d)(\d{4})[-/](\d{1,2})[-/](\d{1,2})(?!\d)", timestamp)
    clock = re.search(r"(?:T|\s|^)(\d{1,2}):(\d{2})(?::\d{2})?", timestamp)
    date = f"{day[1]}-{int(day[2]):02d}-{int(day[3]):02d}" if day else "日期待确认"
    time = f"{int(clock[1]):02d}:{clock[2]}" if clock else "时间待确认"
    return date, time


def _value(item: dict, key: str, default: str = "待确认") -> str:
    value = item.get(key, "")
    return (str(value).strip() or default) if value else default


def _is_followup(item: dict, section_key: str) -> bool:
    return section_key == "actions" and item["kind"] == "suggestion"


def _kind_label(item: dict, section_key: str) -> str:
    return "AI 建议 · 未认领" if _is_followup(item, section_key) else KIND_LABELS[item["kind"]]


def _section_map(report: dict) -> dict:
    return {section["key"]: section for section in report["sections"]}


def _message_map(messages: dict) -> dict:
    return {message["id"]: (index, message)
            for index, message in enumerate(messages["messages"], 1)}


def _evidence_html(item: dict, source_map: dict, index: int, aliases: dict) -> str:
    refs = item.get("evidence_refs", [])
    if not refs:
        label = "无直接聊天依据" if item["kind"] == "suggestion" else "待补充聊天依据"
        return '<p class="evidence empty-evidence">' + label + "</p>"
    links = []
    for ref in refs:
        source_index, message = source_map[ref]
        label = f"[{source_index:03d}] {message['sender']}"
        links.append(f'<a class="source-link" href="#msg-{source_index:04d}">{_text(label)}</a>')
    first = source_map[refs[0]][1]
    reply = split_reply(first["text"])
    body = reply["body"] if reply else first["text"]
    excerpt = body[:88]
    quotation = ('<blockquote class="evidence-quote">' +
                 _field(excerpt, f"quote-{index:04d}", aliases.get(first["id"])) +
                 ('<span aria-label="节选">…</span>' if len(body) > 88 else "") + '</blockquote>') if excerpt else ""
    return quotation + '<div class="evidence"><span>原话依据</span>' + "".join(links) + "</div>"


def _card_html(item: dict, source_map: dict, index: int, section_key: str, aliases: dict) -> str:
    kind = item["kind"]
    followup = _is_followup(item, section_key)
    suggestion_class = " suggestion" if kind == "suggestion" else ""
    details = ""
    if kind == "action" or followup:
        details = '<dl class="action-meta">' + "".join(
            f'<div><dt>{label}</dt><dd class="{field}">{_field(_value(item, field, "未认领" if followup and field == "status" else "待确认"), f"item-{index:04d}-{field}")}</dd></div>'
            for field, label in (("owner", "负责人"), ("due", "截止时间"), ("status", "状态"))
        ) + "</dl>"
    learning = []
    for key, label in (("question", "问题 / 场景"), ("answer", "回答 / 方法"), ("conditions", "适用条件"), ("outcome", "验证状态")):
        if item.get(key):
            learning.append(f'<p><strong>{label}：</strong>{_field(item[key], f"item-{index:04d}-{key}")}</p>')
    if item.get("steps"):
        learning.append('<ol>' + ''.join(f'<li>{_field(step, f"item-{index:04d}-step-{n}")}</li>' for n, step in enumerate(item['steps'])) + '</ol>')
    learning_html = '<div class="learning-details">' + ''.join(learning) + '</div>' if learning else ''
    return (f'<article class="report-item{suggestion_class}" id="item-{index:04d}">'
            f'<span class="item-kind">{_kind_label(item, section_key)}</span>'
            f'<h3 class="item-title">{_field(item["title"], f"item-{index:04d}-title")}</h3>'
            f'<p class="item-body">{_field(item["body"], f"item-{index:04d}-body")}</p>'
            f'{learning_html}{details}{_evidence_html(item, source_map, index, aliases)}</article>')


def _source_html(message: dict, index: int, source_map: dict, aliases: list) -> str:
    _, time = _date_time(message.get("timestamp") or "")
    reply = split_reply(message["text"])
    body = reply["body"] if reply else message["text"]
    content = f'<p class="message-text">{_field(body, f"msg-{index:04d}-body", aliases)}</p>'
    if reply:
        target = source_map.get(reply["id"])
        label = reply["sender"] or (target[1]["sender"] if target else "原发言人未提供")
        reference = (f'<a class="source-link" href="#msg-{target[0]:04d}">查看原消息 [{target[0]:03d}]</a>' if target else
                     '<span class="reply-unavailable">引用的原消息不在本次材料中</span>')
        content += ('<blockquote class="reply-quote"><div class="reply-heading">回复 ' + _field(label, f"msg-{index:04d}-reply-sender") + '</div>' +
                    '<p>' + _field(reply["content"], f"msg-{index:04d}-reply", aliases, reply["offset"]) + '</p>' + reference + '</blockquote>')
    attachments = message.get("attachments", [])
    if attachments:
        content += '<div class="attachments" aria-label="附件记录">' + ''.join(
            '<span class="attachment-chip">' + _field(_attachment_text(value), f"msg-{index:04d}-attachment-{i}") + '</span>'
            for i, value in enumerate(attachments, 1)) + '</div>'
    provenance = ''.join('<li>' + _text(origin['file']) + ' · ' + _text(origin['locator']) + '</li>'
                         for origin in message.get('sources', []))
    details = '<p>消息 ID：' + _text(message['id']) + '</p><p>完整时间：' + _text(message.get('timestamp') or '未提供') + '</p>'
    if provenance:
        details += '<p>导入来源：</p><ul>' + provenance + '</ul>'
    attachment_sources = [value.get('source') for value in attachments if isinstance(value, dict) and value.get('source')]
    if attachment_sources:
        details += '<p>附件索引位置（未读取）：</p><ul>' + ''.join('<li>' + _text(value) + '</li>' for value in attachment_sources) + '</ul>'
    if reply:
        details += '<p>导入原文（保留引用字段）：</p><pre class="raw-message">' + _text(message['text']) + '</pre>'
    return (f'<article class="source-message" id="msg-{index:04d}"><header class="message-heading">'
            f'<span class="source-number">[{index:03d}]</span><b class="source-sender">{_field(message["sender"], f"msg-{index:04d}-sender")}</b>'
            f'<span class="message-time">{_text(time)}</span></header><div class="source-content">{content}'
            f'<details class="message-details"><summary>消息详情</summary><div>{details}</div></details></div></article>')


def _topic_cloud_html(report: dict, messages: dict, source_map: dict, reviews: list) -> str:
    keywords = build_topic_keywords(report, messages, term_reviews=reviews)
    if not keywords:
        return ''
    maximum, minimum = keywords[0]['message_count'], keywords[-1]['message_count']
    buttons = []
    for keyword in keywords:
        targets = []
        for match in keyword['matches']:
            index, message = source_map[match['message_id']]
            targets.append({'field': f'msg-{index:04d}-body',
                            'start': _utf16_length(_display_text(message['text'][:match['start']])),
                            'end': _utf16_length(_display_text(message['text'][:match['end']]))})
        count = keyword['message_count']
        level = round(4 * (count - minimum) / (maximum - minimum)) if maximum != minimum else 2
        buttons.append(f'<button type="button" class="keyword-word keyword-size-{level}" data-keyword="{_text(keyword["term"])}" '
                       f'data-message-count="{count}" data-keyword-matches="{_text(json.dumps(targets, ensure_ascii=False))}" '
                       f'aria-label="{_text(keyword["term"])}，{count} 条消息，点击查看原文">'
                       f'<span>{_text(keyword["term"])}</span><small>{count}<span class="word-count-unit"> 条</span></small></button>')
    origin = ('整理时选定的主题词' if 'keywords' in report else '从报告里的有限业务词与英文名称筛选')
    return ('<aside class="topic-cloud" id="topic-cloud" aria-labelledby="topic-cloud-title">'
            '<div class="topic-cloud-heading"><h2 id="topic-cloud-title">这次聊到了什么</h2><span>主题词云 · 点词看原话</span></div>'
            '<div class="keyword-words">' + ''.join(buttons) + '</div>'
            '<p class="keyword-method">' + origin + '，再回到原消息核对。字号和数字表示涉及的消息条数：同条重复只算一次，回复里的引用内容不另计。'
            '这是本报告的话题导航，并非完整词频或重要性排名。</p></aside>')


def render_html(report: dict, messages: dict) -> str:
    """Return a self-contained HTML document; callers validate and write it."""
    sections = _section_map(report)
    source_map = _message_map(messages)
    aliases = {}
    term_reviews = review_terms(messages)
    for alias in term_reviews:
        aliases.setdefault(alias['message_id'], []).append(alias)
    cloud_html = _topic_cloud_html(report, messages, source_map, term_reviews)
    cloud_return_html = ('<p id="search-keyword-note" class="search-keyword-note" hidden>主题词云按消息条数计数；下面逐处定位这些消息的正文。'
                         '<a href="#topic-cloud">返回主题词云 ↑</a></p>') if cloud_html else ''
    css = report_styles()
    js = (ASSET_DIR / "report.js").read_text(encoding="utf-8")
    logo = base64.b64encode((ASSET_DIR / "qunhuibao-logo.png").read_bytes()).decode("ascii")
    all_items = [item for section in report["sections"] for item in section["items"]]
    action_count = sum(item["kind"] == "action" for item in all_items)
    followup_count = sum(_is_followup(item, "actions") for item in sections.get("actions", {}).get("items", []))
    question_count = sum(item["kind"] in ("question", "suggestion") for item in all_items) - followup_count
    period = report.get("period") or messages.get("coverage") or "时间范围待确认"
    highlights = sections.get('topics', {}).get('items', [])[:3] or all_items[:3]
    highlight_html = ''.join(f'<div><span class="phase-number">{index:02d}</span><small>讨论线索</small>'
                             f'<b>{_text(item["title"])}</b></div>' for index, item in enumerate(highlights, 1))
    speaker_count = len({message['sender'] for message in messages['messages']})

    nav = []
    blocks = []
    item_index = 0
    section_index = 0
    for key, default_title, description in SECTIONS:
        section = sections.get(key, {})
        title = section.get("title") or default_title
        items = section.get("items", [])
        if not items:
            continue
        section_index += 1
        nav.append(f'<a href="#{key}"><span class="nav-number">{section_index:02d}</span>'
                   f'<span class="nav-label">{_text(title)}<small>{len(items)} 条</small></span>'
                   '<span class="nav-arrow" aria-hidden="true">↗</span></a>')
        cards = []
        for item in items:
            item_index += 1
            cards.append(_card_html(item, source_map, item_index, key, aliases))
        extra = ('<button type="button" id="copy-actions" class="button button-primary">复制行动与建议清单</button>'
                 if key == "actions" else "")
        blocks.append(f'<section class="report-section" id="{key}">'
                      f'<div class="section-heading"><div><h2><span>{section_index:02d}</span> {_text(title)}</h2>'
                      f'<p>{description}</p></div>{extra}</div>'
                      f'<div class="report-grid">{"".join(cards)}</div></section>')

    sources = []
    previous_date = None
    for message in messages["messages"]:
        index = source_map[message["id"]][0]
        date, _ = _date_time(message.get('timestamp') or '')
        if date != previous_date:
            if previous_date is not None:
                sources.append('</div>')
            sources.append(f'<div class="source-day"><h3 class="source-date">{_text(date)}</h3>')
            previous_date = date
        sources.append(_source_html(message, index, source_map, aliases.get(message['id'], [])))
    if sources:
        sources.append('</div>')
    sources_number = section_index + 1
    warnings = messages.get("warnings", [])
    warning_html = ('<aside class="import-notes"><strong>导入说明</strong><ul>' +
                    "".join("<li>" + _text(warning) + "</li>" for warning in warnings) +
                    "</ul></aside>") if warnings else ""
    return f'''<!doctype html>
<html lang="zh-CN"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<meta name="robots" content="noindex,nofollow"><title>{_text(report['title'])} · 群汇报</title>
<style>{css}</style></head><body>
<div class="report-toolbar"><span>群汇报 <b>本地报告 · 未发布</b></span><div><a href="#contents">目录</a><button type="button" id="print-report">打印 / 保存 PDF</button></div></div>
<div class="wrap"><header class="brand-header"><img class="brand-logo" src="data:image/png;base64,{logo}" alt="群汇报 Logo" width="2172" height="724"><span>群聊一键出日报</span></header>
<section class="hero" id="report-overview"><div class="hero-copy"><p class="meta">群汇报 · {_text(period)}</p><h1>{_field(report['title'], 'report-title')}</h1><p class="subtitle">{_field(report['conversation'], 'report-conversation')}</p><p class="lead">{_field(report['summary'], 'report-summary')}</p><p class="local-note">由 Agent 提炼 · 引用可追溯 · 内容待人工核对</p></div>
<div class="phase-strip">{highlight_html}</div></section>
{warning_html}<div class="contents-heading" id="contents"><div><span class="eyebrow">GROUP REPORT</span><h2>一页读懂这次讨论</h2></div><p>点击卡片，直达重点</p></div>
<nav class="toc" aria-label="报告导航">{''.join(nav)}<a href="#sources"><span class="nav-number">{sources_number:02d}</span><span class="nav-label">原消息依据<small>{len(messages['messages'])} 条</small></span><span class="nav-arrow" aria-hidden="true">↗</span></a></nav>
<main>{cloud_html}<div class="search-area" id="search-panel"><div class="search-input-row"><label for="report-search">搜索报告与原文</label><input id="report-search" type="search" placeholder="输入关键词，点击结果定位" autocomplete="off"><select id="search-scope" aria-label="搜索范围"><option value="all">全部内容</option><option value="report">仅报告</option><option value="sources">仅原消息</option></select><button type="button" class="button" id="search-clear">清空</button></div>
<div class="search-controls"><span id="search-position" role="status" aria-live="polite">输入关键词后显示结果</span><button type="button" class="button" id="search-prev" disabled>上一处</button><button type="button" class="button" id="search-next" disabled>下一处</button><span class="search-tip">Enter 下一处 · Shift+Enter 上一处 · Esc 清除</span></div>{cloud_return_html}<ol id="search-results" aria-label="搜索结果" tabindex="-1"></ol><button type="button" class="button" id="search-more" hidden>显示更多结果</button></div><noscript>搜索与复制功能需要 JavaScript；报告正文、引用及原消息仍可直接阅读。</noscript>
{''.join(blocks)}
<section class="report-section" id="sources"><div class="section-heading"><div><h2><span>{sources_number:02d}</span> 原消息依据</h2><p>原文直接阅读；点击引用或搜索结果可定位。保留原文不代表内容已被验证。</p></div></div><div class="source-list">{''.join(sources)}</div></section>
<aside class="report-stats" aria-label="本次材料"><span>{len(messages['messages'])} 条消息</span><span>{speaker_count} 位发言人</span><span>{action_count} 项已确认行动</span><span>{followup_count} 项建议跟进</span><span>{question_count} 项其他问题与建议</span></aside>
</main><footer class="report-footer"><span>群汇报 · 群聊一键出日报</span><p>本地报告 · 未发布。原消息可能包含个人信息，分享前请核对范围。<br>负责人、期限未明确时显示“待确认”；建议跟进默认未认领，AI 建议不等同于群内决定。</p></footer></div>
<div id="report-toast" class="report-toast" role="status" aria-live="polite" hidden></div>
<div id="search-floating" class="search-floating" aria-label="继续浏览搜索命中" hidden><button type="button" id="search-floating-prev" class="button" aria-label="上一处匹配">上一处</button><span id="search-floating-position"></span><button type="button" id="search-floating-next" class="button" aria-label="下一处匹配">下一处</button><button type="button" id="return-to-search" class="button">返回结果</button></div>
<dialog id="copy-dialog"><h2>复制行动与建议清单</h2><p>自动复制不可用，请选中以下文本后复制。</p><textarea id="copy-content" readonly aria-label="全部行动与建议清单"></textarea><button type="button" id="close-copy-dialog" class="button">关闭</button></dialog>
<script>{js}</script></body></html>'''


def _markdown(value: object) -> str:
    # Disable raw HTML, links, inline code and block syntax in untrusted text.
    value = str(value).replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")
    return re.sub(r"([\\`*_{}\[\]()#+.!|~])", r"\\\1", value)


def render_markdown(report: dict, messages: dict) -> str:
    """Return a readable text report with generated, stable source anchors."""
    source_map = _message_map(messages)
    sections = _section_map(report)
    lines = ["# " + _markdown(report["title"]), "", "**本地报告 · 未发布**", "",
             "群聊：" + _markdown(report["conversation"]),
             "时间范围：" + _markdown(report.get("period") or messages.get("coverage") or "待确认"),
             "", _markdown(report["summary"]), "",
             "由 Agent 提炼，内容待人工核对。AI 建议不等同于群内决定。", ""]
    if messages.get("warnings"):
        lines += ["导入说明：", ""]
        lines += ["- " + _markdown(warning).replace("\n", "\n  ") for warning in messages["warnings"]]
        lines += [""]
    index = 0
    for key, default_title, _ in SECTIONS:
        section = sections.get(key, {})
        items = section.get("items", [])
        if not items:
            continue
        index += 1
        lines += [f"## {index:02d} " + _markdown(section.get("title") or default_title), ""]
        for item in items:
            followup = _is_followup(item, key)
            lines += ["### " + _markdown(item["title"]), "", "**" + _kind_label(item, key) + "**", "",
                      _markdown(item["body"]), ""]
            for field, label in (("question", "问题 / 场景"), ("answer", "回答 / 方法"), ("conditions", "适用条件"), ("outcome", "验证状态")):
                if item.get(field):
                    lines += [label + "：" + _markdown(item[field]), ""]
            if item.get("steps"):
                lines += [f"{n}. " + _markdown(step) for n, step in enumerate(item["steps"], 1)] + [""]
            if item["kind"] == "action" or followup:
                for key_name, label in (("owner", "负责人"), ("due", "截止时间"), ("status", "状态")):
                    default = "未认领" if followup and key_name == "status" else "待确认"
                    lines += [label + "：" + _markdown(_value(item, key_name, default)) + "  "]
                lines += [""]
            refs = item.get("evidence_refs", [])
            if refs:
                lines += ["聊天依据：" + "、".join(
                    f"[消息 {source_map[ref][0]:03d}](#msg-{source_map[ref][0]:04d})" for ref in refs), ""]
            else:
                lines += ["无直接聊天依据。" if item["kind"] == "suggestion" else "待补充聊天依据。", ""]
    lines += [f"## {index + 1:02d} 原消息依据", ""]
    for message in messages["messages"]:
        index = source_map[message["id"]][0]
        # The only raw HTML emitted by Markdown is this generated numeric anchor.
        lines += [f'<a id="msg-{index:04d}"></a>', "", f"### 消息 {index:03d}", "",
                  "消息 ID：" + _markdown(message["id"]),
                  "发言人：" + _markdown(message["sender"]),
                  "时间：" + _markdown(message.get("timestamp") or "待确认"), ""]
        lines += ["> " + _markdown(line) for line in message["text"].split("\n")]
        if message.get("attachments"):
            lines += ["", "附件记录（仅文本）：", ""]
            lines += ["- " + _markdown(_attachment_text(attachment)).replace("\n", "\n  ")
                      for attachment in message["attachments"]]
        lines += [""]
    return "\n".join(lines) + "\n"
