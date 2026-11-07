"""Small, local topic vocabulary grounded in message bodies, not a word-frequency model.

Candidates use optional report keywords; legacy reports fall back to a
deliberately limited business vocabulary and English names in report text.
Every retained word includes original-message ranges. Repeated uses in one
message count once; imported reply quotations, names and attachment metadata
are excluded. Neither source text nor its digest is changed.
"""
from __future__ import annotations

import re
import unicodedata

from .terminology import review_terms


# This is a bounded vocabulary, not general-purpose Chinese segmentation.
BUSINESS_TERMS = (
    "群汇报", "微信流", "群聊总结", "社群", "群聊", "知识库", "外脑", "复盘",
    "工作流", "自动化", "智能体", "提示词", "大模型", "多模态", "开源", "本地部署",
    "短视频", "视频剪辑", "视频切片", "直播切片", "切片", "混剪", "剪辑", "口播",
    "配音", "字幕", "素材", "分镜", "剪映", "即梦", "数字人", "直播", "小程序",
    "公众号", "小红书", "视频号", "抖音", "选题", "文案", "封面", "品牌",
    "派单", "接单", "报价", "交付", "验收", "修改", "售后", "需求", "样片",
    "获客", "投放", "私域", "公域", "成交", "转化", "复购", "客户", "销售",
    "课程", "训练营", "咨询", "运营", "商业化", "定价", "合作", "版权",
    "SOP", "MCP", "CLI", "API", "AI", "n8n", "ffmpeg",
)
ENGLISH_NOISE = frozenset("""
    a an and are as at be been but by can could do for from had has have he hello
    her here him his how i if in into is it its let me my no not of on or our out
    please put say she should so some than that the their them then there these
    they this those to us use using was we were what when where which who why
    will with would yes you your chat ok okay thanks thank http https www com
    net org json html css js id url title body text file source script img src
    onerror window alert true false null undefined javascript div span
""".split())
ENGLISH_ENTITY = re.compile(r"(?<![A-Za-z0-9_])[A-Za-z][A-Za-z0-9]*(?:[.+#-][A-Za-z0-9]+)*(?![A-Za-z0-9_])")
CHINESE_NOISE = frozenset("大家 可以 好的 收到 谢谢 没错 确实 这个 那个 就是 然后 感觉 可能 什么 怎么 一个 我们 你们 他们 今天 明天 昨天 现在 时候 需要 知道 一下 没有 不是 还是 已经 看看 是的 对的 好吧 不用 东西 问题".split())
EXPLICIT_TECHNICAL_TERMS = frozenset(('json', 'html', 'css', 'js', 'id', 'url', 'http', 'https'))


def split_reply(text: str) -> dict | None:
    """Split only the importer's terminal quote block, retaining original offsets."""
    match = re.search(r"(?:^|\n)(?:引用消息 ID[：:](?P<id>[^\n]*)\n)?"
                      r"(?:引用发言人[：:](?P<sender>[^\n]*)\n)?引用内容[：:](?P<content>[\s\S]*)$", text)
    if not match:
        return None
    return {"body": text[:match.start()].rstrip("\r\n"), "id": (match.group("id") or "").strip(),
            "sender": (match.group("sender") or "").strip(), "content": match.group("content"),
            "offset": match.start("content")}


def keyword_key(value: str) -> str:
    return re.sub(r"\s+", "", unicodedata.normalize("NFKC", value).casefold())


def canonical_keyword(value: str, reviews: list[dict]) -> str:
    """Normalize only an occurrence-approved alias; do not expand a global typo rule."""
    key = keyword_key(value)
    for alias in reviews:
        if key in (keyword_key(alias['original']), keyword_key(alias['canonical'])):
            return alias['canonical']
    return unicodedata.normalize('NFKC', value).strip()


def _noise(value: str) -> bool:
    key = keyword_key(value)
    return ((key in ENGLISH_NOISE and key not in EXPLICIT_TECHNICAL_TERMS) or key in CHINESE_NOISE
            or bool(re.fullmatch(r'[哈呵嘿嗯哦啊呀！!~～]+', key)))


def _normalized(value: str) -> tuple[str, list[int]]:
    text, offsets = [], []
    for index, character in enumerate(value):
        normalized = unicodedata.normalize("NFKC", character).casefold()
        text.extend(normalized)
        offsets.extend([index] * len(normalized))
    return "".join(text), offsets


def _pattern(term: str) -> re.Pattern:
    body = r"\s*".join(re.escape(char) for char in keyword_key(term))
    if re.search(r"[a-z0-9]", keyword_key(term)):
        body = r"(?<![a-z0-9_])" + body + r"(?![a-z0-9_])"
    return re.compile(body)


def _report_text(report: dict) -> str:
    parts = [report.get("title", ""), report.get("summary", "")]
    for section in report.get("sections", []):
        for item in section.get("items", []):
            parts.extend((item.get("title", ""), item.get("body", "")))
    return "\n".join(parts)


def _candidates(report: dict, messages: dict, reviews: list[dict]) -> list[str]:
    names = {keyword_key(message["sender"]) for message in messages["messages"]}
    if 'keywords' in report:
        selected = [canonical_keyword(term, reviews) for term in report['keywords']]
        return list(dict.fromkeys(term for term in selected if keyword_key(term) not in names
                                  and not _noise(term)))
    text, _ = _normalized(_report_text(report))
    # Candidate spelling may use a confirmed correction; evidence stays raw.
    originals = {keyword_key(item["original"]): item for item in reviews}
    for alias in originals.values():
        text = _pattern(alias["original"]).sub(alias["canonical"], text)
    candidates: dict[str, str] = {}
    for term in BUSINESS_TERMS:
        if _pattern(term).search(text.casefold()) and keyword_key(term) not in names:
            candidates[keyword_key(term)] = term
    # Preserve capitalization from the report for names such as ChatCut/Claude.
    # Lowercase-only ordinary English is intentionally not inferred as an entity.
    for match in ENGLISH_ENTITY.finditer(unicodedata.normalize("NFKC", _report_text(report))):
        term = match.group()
        key = keyword_key(term)
        if 2 <= len(term) <= 32 and any(char.isupper() for char in term) and key not in ENGLISH_NOISE and key not in names:
            candidates.setdefault(key, term)
    for alias in originals.values():
        if _pattern(alias["original"]).search(_normalized(_report_text(report))[0]) or _pattern(alias["canonical"]).search(text.casefold()):
            if keyword_key(alias["canonical"]) not in names:
                candidates[keyword_key(alias["canonical"])] = alias["canonical"]
            candidates.pop(keyword_key(alias["original"]), None)
    return list(candidates.values())


def build_topic_keywords(report: dict, messages: dict, *, term_reviews: list[dict] | None = None,
                         limit: int = 24) -> list[dict]:
    """Return topic words with unique-message counts and Python source offsets.

    ``matches`` records contain ``message_id``, ``start`` and exclusive ``end``.
    Only text before an imported quotation block is counted. A word can have
    several matching ranges but contributes at most one count per message.
    This is a report-led topic sample, never complete chat word frequencies.
    """
    if limit <= 0:
        return []
    reviews = review_terms(messages) if term_reviews is None else term_reviews
    by_message: dict[str, list] = {}
    for alias in reviews:
        by_message.setdefault(alias['message_id'], []).append(alias)
    rows = []
    for message in messages["messages"]:
        reply = split_reply(message["text"])
        body = reply["body"] if reply else message["text"]
        normalized, offsets = _normalized(body)
        approved = [alias for alias in by_message.get(message['id'], [])
                    if 0 <= alias["start"] < alias["end"] <= len(body)
                    and body[alias["start"]:alias["end"]] == alias["original"]]
        rows.append((message["id"], normalized, offsets, approved))
    result = []
    for term in _candidates(report, messages, reviews):
        pattern = _pattern(term)
        matches, message_ids = [], []
        for message_id, normalized, offsets, approved in rows:
            spans = {(offsets[match.start()], offsets[match.end() - 1] + 1) for match in pattern.finditer(normalized)}
            spans.update((alias["start"], alias["end"]) for alias in approved if keyword_key(alias["canonical"]) == keyword_key(term))
            if spans:
                message_ids.append(message_id)
                matches.extend({"message_id": message_id, "start": start, "end": end} for start, end in sorted(spans))
        if message_ids:
            result.append({"term": term, "message_count": len(message_ids), "message_ids": message_ids, "matches": matches})
    # Avoid displaying both a broad word and its containing phrase when they
    # describe exactly the same messages, e.g. 视频切片 + 切片.
    if 'keywords' not in report:
        result = [item for item in result if not any(
            keyword_key(item["term"]) != keyword_key(other["term"]) and keyword_key(item["term"]) in keyword_key(other["term"])
            and item["message_ids"] == other["message_ids"] for other in result)]
    return sorted(result, key=lambda item: (-item["message_count"], keyword_key(item["term"])))[:min(limit, 24)]
