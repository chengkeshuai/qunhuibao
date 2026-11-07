"""Semantic rendering checks without opening local HTML in a browser."""
from copy import deepcopy
from html import unescape
from html.parser import HTMLParser
import json
import re
import shutil
import subprocess
import unittest

from qunhuibao.renderer import render_html, render_markdown


def fixture():
    messages = {
        "schema_version": 1, "conversation": "演示群", "coverage": "2026-11-06",
        "warnings": ["演示数据，未连接真实微信。"],
        "messages": [
            {"id": "m1", "sender": "小林", "timestamp": "2026-11-06 10:00",
             "text": "本周整理新人常见问题。\n负责人需要再确认。", "attachments": []},
            {"id": "m2", "sender": "小周", "timestamp": "", "text": "明天讨论模板。",
             "attachments": [{"name": "模板.txt", "source": "", "kind": "file", "status": "indexed_not_rendered"}]},
        ],
    }
    report = {
        "schema_version": 1, "source_digest": "test-only", "title": "演示群汇报",
        "summary": "整理群内有依据的下一步。", "conversation": "演示群", "period": "今天",
        "sections": [
            {"key": "topics", "title": "主题精华", "items": [
                {"title": "新人问题", "body": "需要整理常见问题。", "kind": "fact", "evidence_refs": ["m1"]}]},
            {"key": "decisions", "title": "已定事项", "items": []},
            {"key": "actions", "title": "行动清单", "items": [
                {"title": "整理问题", "body": "先汇总问题。", "kind": "action", "evidence_refs": ["m1", "m2"]}]},
            {"key": "assets", "title": "资产", "items": []},
            {"key": "questions", "title": "待确认", "items": [
                {"title": "谁来负责", "body": "待讨论。", "kind": "question", "evidence_refs": []},
                {"title": "增加目录", "body": "可考虑分类索引。", "kind": "suggestion", "evidence_refs": []}]},
        ],
    }
    return report, messages


class Document(HTMLParser):
    def __init__(self, text):
        super().__init__(convert_charrefs=True)
        self.tags = []
        self.feed(text)

    def handle_starttag(self, tag, attrs):
        self.tags.append((tag, dict(attrs)))


class RendererTests(unittest.TestCase):
    def test_topic_cloud_has_grounded_counts_safe_targets_and_optional_omission(self):
        report, messages = fixture()
        report['keywords'] = ['新人', '负责人']
        messages['messages'][1]['text'] = '新人可以先看看。'
        page = render_html(report, messages)
        buttons = [attrs for tag, attrs in Document(page).tags if tag == 'button' and 'data-keyword' in attrs]
        self.assertEqual({button['data-keyword']: button['data-message-count'] for button in buttons}, {'新人': '2', '负责人': '1'})
        self.assertEqual(len({button['class'] for button in buttons}), 2)
        self.assertIn('这次聊到了什么', page)
        self.assertIn('回复里的引用内容不另计', page)
        targets = json.loads(next(button for button in buttons if button['data-keyword'] == '新人')['data-keyword-matches'])
        self.assertEqual([target['field'] for target in targets], ['msg-0001-body', 'msg-0002-body'])
        report['keywords'] = []
        self.assertNotIn('id="topic-cloud"', render_html(report, messages))
        report['keywords'] = ['材料中不存在']
        self.assertNotIn('id="topic-cloud"', render_html(report, messages))

    def test_unclaimed_followups_have_metadata_and_separate_cover_counts(self):
        report, messages = fixture()
        report["sections"][2]["items"] = [
            {"title": f"候选跟进 {index}", "body": "需要另行认领。", "kind": "suggestion", "evidence_refs": []}
            for index in range(4)
        ]
        page = render_html(report, messages)
        self.assertIn("0 项已确认行动", page)
        self.assertIn("4 项建议跟进", page)
        self.assertIn("2 项其他问题与建议", page)
        self.assertEqual(len(re.findall(r'<dd class="status"><span[^>]*>未认领</span></dd>', page)), 4)
        self.assertEqual(len(re.findall(r'<dd class="owner"><span[^>]*>待确认</span></dd>', page)), 4)
        self.assertEqual(len(re.findall(r'<dd class="due"><span[^>]*>待确认</span></dd>', page)), 4)
        self.assertEqual(page.count('<span class="item-kind">AI 建议 · 未认领</span>'), 4)
        # Suggestions outside the action section retain their previous display.
        other = re.search(r'<section class="report-section" id="questions">(.*?)</section>', page, re.S).group(1)
        self.assertIn("AI 建议 · 非已确认事实", other)
        self.assertNotIn('class="action-meta"', other)
        markdown = render_markdown(report, messages)
        self.assertEqual(markdown.count("状态：未认领"), 4)
        self.assertEqual(markdown.count("**AI 建议 · 未认领**"), 4)
        self.assertIn("**AI 建议 · 非已确认事实**", markdown)

    @unittest.skipUnless(shutil.which("node"), "Node unavailable; clipboard behavior check skipped")
    def test_copy_includes_followup_label_without_copying_other_suggestions(self):
        report, messages = fixture()
        report["sections"][2]["items"].append(
            {"title": "建议核实", "body": "先核对条件。", "kind": "suggestion", "evidence_refs": []})
        page = render_html(report, messages)
        self.assertIn("1 项已确认行动", page)
        self.assertIn("1 项建议跟进", page)
        cards = []
        for block in re.findall(r'<article class="report-item[^\"]*"[^>]*>(.*?)</article>', page, re.S):
            fields = {}
            for field in ("item-title", "item-body", "item-kind", "owner", "due", "status", "empty-evidence"):
                match = re.search(r'<[^>]+class="[^\"]*\b' + field + r'\b[^\"]*"[^>]*>(.*?)</[^>]+>', block, re.S)
                if match:
                    fields["." + field] = unescape(re.sub(r'<[^>]*>', '', match.group(1)))
            cards.append({"fields": fields, "meta": 'class="action-meta"' in block,
                          "refs": [unescape(text) for text in re.findall(r'<a class="source-link"[^>]*>(.*?)</a>', block)]})
        payload = {"cards": cards, "script": re.search(r'<script>(.*?)</script>', page, re.S).group(1)}
        # Execute the real static script against text-only DOM doubles, never a browser.
        harness = r'''
const fs = require('fs'), vm = require('vm');
const input = JSON.parse(fs.readFileSync(0, 'utf8'));
const controls = new Map();
function control(selector) {
  if (!controls.has(selector)) controls.set(selector, {textContent: '', listeners: {},
    addEventListener(name, callback) { this.listeners[name] = callback; }});
  return controls.get(selector);
}
const items = input.cards.map(card => ({
  querySelector(selector) {
    if (selector === '.action-meta') return card.meta ? {} : null;
    return selector in card.fields ? {textContent: card.fields[selector]} : null;
  },
  querySelectorAll(selector) { return selector === '.source-link' ? card.refs.map(textContent => ({textContent})) : []; }
}));
let copied = '';
vm.runInNewContext(input.script, {
  document: {querySelector: control, querySelectorAll: selector => selector === '.report-item' ? items : [], addEventListener() {}},
  window: {location: {hash: ''}, addEventListener() {}, print() {}},
  navigator: {clipboard: {async writeText(text) { copied = text; }}},
  setTimeout: () => 0, clearTimeout() {}
});
Promise.resolve(control('#copy-actions').listeners.click()).then(() => process.stdout.write(JSON.stringify(copied)));
'''
        result = subprocess.run([shutil.which("node"), "-e", harness], input=json.dumps(payload),
                                capture_output=True, text=True, encoding="utf-8", check=True)
        copied = json.loads(result.stdout)
        self.assertIn("整理问题", copied)
        self.assertIn("类型：待办行动", copied)
        self.assertIn("建议核实", copied)
        self.assertIn("类型：AI 建议 · 未认领", copied)
        self.assertIn("状态：未认领", copied)
        self.assertIn("聊天依据：无直接聊天依据", copied)
        self.assertNotIn("增加目录", copied)

    def test_offline_document_has_resolvable_generated_anchors(self):
        report, messages = fixture()
        page = render_html(report, messages)
        parsed = Document(page)
        ids = [attrs["id"] for _, attrs in parsed.tags if "id" in attrs]
        self.assertEqual(len(ids), len(set(ids)))
        for tag, attrs in parsed.tags:
            if "href" in attrs:
                self.assertTrue(attrs["href"].startswith("#"), attrs)
                self.assertIn(attrs["href"][1:], ids)
            if "src" in attrs:
                self.assertEqual(tag, "img")
                self.assertTrue(attrs["src"].startswith("data:image/png;base64,"))
        self.assertEqual(sum(tag == "script" for tag, _ in parsed.tags), 1)
        self.assertEqual(sum(tag == "style" for tag, _ in parsed.tags), 1)
        self.assertEqual(sum(tag == "details" for tag, _ in parsed.tags), 2)
        self.assertIn("本地报告 · 未发布", page)
        self.assertNotIn("file://", page)
        self.assertNotIn("C:/Users/", page)
        self.assertNotIn("D:/", page)

    def test_untrusted_text_cannot_create_markup_attributes_or_script(self):
        report, messages = fixture()
        payload = '</script><img src="https://bad.invalid/x" onerror="alert(1)"><a id="evil">&\'"'
        report["title"] = payload
        report["summary"] = payload
        report["conversation"] = payload
        report["period"] = payload
        report["sections"][0]["title"] = payload
        item = report["sections"][2]["items"][0]
        for key in ("title", "body", "owner", "due", "status"):
            item[key] = payload
        followup = deepcopy(item)
        followup["kind"] = "suggestion"
        report["sections"][2]["items"].append(followup)
        messages["warnings"] = [payload]
        for message in messages["messages"]:
            message.update(sender=payload, text=payload, timestamp=payload, attachments=[
                {"name": payload, "source": payload, "kind": payload, "status": "indexed_not_rendered"}])
        # An arbitrary external-looking message ID must only become text.
        old_id = messages["messages"][0]["id"]
        messages["messages"][0]["id"] = payload
        for section in report["sections"]:
            for candidate in section["items"]:
                candidate["evidence_refs"] = [payload if ref == old_id else ref for ref in candidate["evidence_refs"]]
        page = render_html(report, messages)
        parsed = Document(page)
        self.assertNotIn(payload, page)
        self.assertIn("&lt;/script&gt;", page)
        self.assertEqual(sum(tag == "img" for tag, _ in parsed.tags), 1)
        self.assertEqual(sum(tag == "script" for tag, _ in parsed.tags), 1)
        self.assertFalse(any(key.startswith("on") for _, attrs in parsed.tags for key in attrs))
        self.assertFalse(any(payload in value for _, attrs in parsed.tags for value in attrs.values() if value))
        self.assertNotIn("bad.invalid", re.search(r"<script>(.*?)</script>", page, re.S).group(1))
        self.assertIn('href="#msg-0001"', page)

    def test_questions_and_suggestions_cannot_look_like_confirmed_decisions(self):
        report, messages = fixture()
        page = render_html(report, messages)
        self.assertIn("AI 建议 · 非已确认事实", page)
        self.assertIn("无直接聊天依据", page)
        self.assertIn("待补充聊天依据", page)
        for field in ('owner', 'due', 'status'):
            self.assertRegex(page, r'<dd class="' + field + r'"><span[^>]*>待确认</span></dd>')
        self.assertIn("消息 ID：m1", page)
        self.assertIn("负责人需要再确认。", page)

    def test_empty_sections_are_omitted_and_visible_numbers_are_consecutive(self):
        report, messages = fixture()
        before = deepcopy((report, messages))
        page = render_html(report, messages)
        for anchor in ('decisions', 'assets'):
            self.assertNotIn('id="' + anchor + '"', page)
            self.assertNotIn('href="#' + anchor + '"', page)
        numbers = re.findall(r'<span class="nav-number">(\d+)</span>', page)
        self.assertEqual(numbers, ['01', '02', '03', '04'])
        self.assertIn('<h2><span>04</span> 原消息依据</h2>', page)
        self.assertEqual((report, messages), before)
        report["sections"] = []
        expected_report = deepcopy(report)
        page = render_html(report, messages)
        for anchor in ("topics", "decisions", "actions", "assets", "questions"):
            self.assertNotIn('id="' + anchor + '"', page)
        self.assertIn('<h2><span>01</span> 原消息依据</h2>', page)
        self.assertNotIn("本次未提取此类内容。", page)
        self.assertIn('## 01 原消息依据', render_markdown(report, messages))
        self.assertEqual(report, expected_report)
        self.assertEqual(messages, before[1])

    def test_source_reading_groups_dates_and_moves_metadata_to_details(self):
        report, messages = fixture()
        messages['messages'][1]['timestamp'] = '2026-11-06T10:02:35+08:00'
        messages['messages'][0]['sources'] = [{'file': 'demo.json', 'locator': 'messages[0]'}]
        page = render_html(report, messages)
        sources = page.split('<div class="source-list">', 1)[1].split('</main>', 1)[0]
        self.assertEqual(sources.count('class="source-date"'), 1)
        self.assertIn('<span class="message-time">10:02</span>', sources)
        self.assertIn('<article class="source-message" id="msg-0001">', sources)
        first = sources.split('<article class="source-message" id="msg-0002">')[0]
        before_details, details = first.split('<details class="message-details">', 1)
        self.assertIn('本周整理新人常见问题。', before_details)
        self.assertNotIn('消息 ID：', before_details)
        self.assertIn('消息 ID：m1', details)
        self.assertIn('demo.json · messages[0]', details)
        self.assertIn('文件 · 模板.txt（仅记录，未读取内容）', sources)
        self.assertNotIn('&quot;status&quot;', sources)
        links = re.findall(r'<a class="source-link"[^>]*>(.*?)</a>', page)
        self.assertTrue(all(re.fullmatch(r'\[\d{3}\] .+', text) for text in links))
        self.assertTrue(all('2026-' not in text for text in links))

    def test_reply_rendering_preserves_raw_evidence_and_handles_missing_context(self):
        report, messages = fixture()
        messages['messages'][1]['text'] = '我来补充。\n引用消息 ID：m1\n引用发言人：小林\n引用内容：🎬 我用 Chat put 做剪辑。'
        original = deepcopy(messages)
        page = render_html(report, messages)
        source = page.split('<article class="source-message" id="msg-0002">', 1)[1]
        visible, details = source.split('<details class="message-details">', 1)
        self.assertIn('class="reply-quote"', visible)
        self.assertIn('查看原消息 [001]', visible)
        self.assertIn('回复 <span id="msg-0002-reply-sender" data-search-field>小林</span>', visible)
        self.assertNotIn('引用消息 ID', visible)
        self.assertIn('引用消息 ID：m1', details)
        reply_field = next(attrs for _, attrs in Document(visible).tags if attrs.get('id') == 'msg-0002-reply')
        records = json.loads(reply_field['data-aliases'])
        self.assertEqual(records[0]['original'], 'Chat put')
        self.assertEqual(records[0]['start'], 6)  # JavaScript UTF-16 index includes the emoji's surrogate pair.
        self.assertEqual(messages, original)
        messages['messages'][1]['text'] = messages['messages'][1]['text'].replace('ID：m1', 'ID：outside')
        self.assertIn('引用的原消息不在本次材料中', render_html(report, messages))

    def test_markdown_keeps_source_references_and_safe_source_text(self):
        report, messages = fixture()
        messages["messages"][0]["text"] = '<script>alert(1)</script>\n[click](javascript:alert(1))\n# spoof heading'
        markdown = render_markdown(report, messages)
        self.assertIn("[消息 001](#msg-0001)", markdown)
        self.assertIn('<a id="msg-0001"></a>', markdown)
        self.assertIn("消息 ID：m1", markdown)
        self.assertIn("负责人：待确认", markdown)
        self.assertIn("无直接聊天依据。", markdown)
        self.assertNotIn("<script>", markdown)
        self.assertNotIn("[click](javascript:", markdown)
        self.assertIn(r"\[click\]\(javascript:", markdown)
        self.assertIn(r"> \# spoof heading", markdown)
        self.assertIn("演示数据，未连接真实微信。", markdown)


if __name__ == "__main__":
    unittest.main()
