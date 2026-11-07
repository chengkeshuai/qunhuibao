"""Offline review workstation. Private source data never enters the share template."""
import base64
import hashlib
import json

from .renderer import ASSET_DIR
from .keywords import split_reply
from .validation import validate_report
from .styles import report_styles


def render_editor(report, messages):
    validate_report(report, messages)
    fingerprint = hashlib.sha256(json.dumps(report, ensure_ascii=False, sort_keys=True).encode()).hexdigest()
    display = {}
    for message in messages["messages"]:
        reply = split_reply(message["text"])
        display[message["id"]] = (f"回复 {reply['sender'] or '原发言人未提供'}：{reply['content']}\n\n{reply['body']}" if reply else message["text"])
    data = json.dumps({"report": report, "messages": messages, "display": display, "fingerprint": fingerprint}, ensure_ascii=False).replace("<", "\\u003c").replace("&", "\\u0026")
    css = report_styles(editor=True)
    js = (ASSET_DIR / "editor.js").read_text(encoding="utf-8").replace("</script", "<\\/script")
    share_js = json.dumps((ASSET_DIR / "share.js").read_text(encoding="utf-8"), ensure_ascii=False).replace("<", "\\u003c")
    logo = base64.b64encode((ASSET_DIR / "qunhuibao-logo.png").read_bytes()).decode()
    return f'''<!doctype html><html lang="zh-CN"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1"><meta name="robots" content="noindex,nofollow">
<title>群汇报 · 日报审稿台</title><style id="brand-style">{css}</style></head><body class="workbench-page">
<div class="wrap"><header class="brand-header"><img id="brand-logo" class="brand-logo" src="data:image/png;base64,{logo}" alt="群汇报" width="270" height="90"><span>群聊一键出日报</span></header>
<section class="hero"><div class="hero-copy"><p class="meta">第一版 · 本地审稿台</p><h1>把今天值得留下的，整理好。</h1><p class="lead">核对原话，修改内容，再选择给群友看的部分。</p><p>本页含完整材料，仅供自己审稿。分享请使用下方导出的分享文件。</p></div></section>
<section class="report-section"><h2>01 材料与编辑</h2><p id="coverage"></p><ul id="warnings"></ul><a href="report.html" target="_blank" rel="noopener">打开原始报告，搜索全部原文</a>
<label class="edit-field">内部标题<input id="internal-title" maxlength="300"></label><label class="edit-field">内部摘要<textarea id="internal-summary" rows="3"></textarea></label>
<div class="edit-actions"><button id="save-draft" type="button">下载审稿进度</button><label class="file-button">载入审稿进度<input type="file" id="load-draft" accept=".json,application/json"></label><button id="restore-local" type="button">恢复浏览器草稿</button><button id="save-report" type="button">下载修改后的报告 JSON</button></div>
<p id="save-status" role="status" aria-live="polite">审稿进度可下载保存；浏览器存储可用时自动保存。</p></section>
<section class="report-section"><h2>02 核对条目 · 勾选分享</h2><p>原话直接列在条目下面。取消勾选即可从分享版移除；上下移动调整同一栏目内的顺序。正文修改不会改动原始消息。</p><div class="edit-actions"><button id="select-reading" type="button">阅读版：重点、资料与问答</button><button id="select-all" type="button">完整：全部条目</button><button id="select-none" type="button">全部取消</button></div><div id="editor-items"></div></section>
<section class="report-section" id="share-settings"><h2>03 分享版</h2><p>分享标题和导语独立填写，避免内部摘要带出未勾选内容。默认不附原话；勾选的引用才会进入文件。</p>
<label class="edit-field">分享标题<input id="share-title" maxlength="300" value="今日群聊精华"></label><label class="edit-field">分享导语（可留空）<textarea id="share-summary" rows="2"></textarea></label>
<label><input id="mask-names" type="checkbox"> 对外分享时，将发言昵称和群名替换为代称</label><p>群内回顾默认保留真实昵称。手机号、邮箱、网址和常见微信号写法仍按现有规则处理；需要对外分享时再选择姓名遮盖。</p>
<label class="edit-field">额外遮盖的文字（每行一项，如客户名、地址）<textarea id="redactions" rows="2"></textarea></label>
<div class="edit-actions"><button id="preview-share" type="button">刷新分享预览</button><button id="download-share" type="button">下载分享 HTML</button></div><p id="share-status" role="status" aria-live="polite"></p>
<iframe id="share-preview" title="实际分享文件预览" sandbox="allow-scripts" hidden></iframe></section>
<footer class="report-footer"><p>本地生成，不会上传。域名上线、访问权限、撤回仍待腾讯云部署；已下载或转发的文件无法远程撤回。</p></footer></div>
<script id="review-data" type="application/json">{data}</script><script id="share-runtime" type="application/json">{share_js}</script><script>{js}</script></body></html>'''
