"""Validate report structure and its binding to the supplied evidence."""
import hashlib
import json
import re

SECTION_KEYS = {"topics", "decisions", "actions", "assets", "questions", "tutorials", "notices", "highlights"}
KINDS = {"fact", "decision", "action", "asset", "question", "suggestion"}


def _object(value, required, optional=(), label="对象"):
    if not isinstance(value, dict):
        raise ValueError(f"{label}须为对象")
    missing, extra = set(required) - value.keys(), value.keys() - set(required) - set(optional)
    if missing or extra:
        raise ValueError(f"{label}字段错误：缺少 {sorted(missing)}；未知 {sorted(extra)}")


def _str(value, label, empty=False, limit=200_000):
    if not isinstance(value, str) or (not empty and not value.strip()):
        raise ValueError(f"{label}须为{'可空' if empty else '非空'}字符串")
    if len(value) > limit:
        raise ValueError(f"{label}超过 {limit} 字符，请拆分输入")


def _list(value, label, maximum=100_000):
    if not isinstance(value, list) or len(value) > maximum:
        raise ValueError(f"{label}须为数组，最多 {maximum} 项")


def source_digest(messages):
    """Stable across JSON whitespace/key order; includes all evidence and warnings."""
    raw = json.dumps(messages, ensure_ascii=False, sort_keys=True, separators=(",", ":"), allow_nan=False)
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()


def validate_messages(data):
    _object(data, ("schema_version", "conversation", "coverage", "messages", "warnings"), label="messages")
    if type(data["schema_version"]) is not int or data["schema_version"] != 1:
        raise ValueError("不支持的 messages schema_version")
    _str(data["conversation"], "conversation", limit=1000)
    _str(data["coverage"], "coverage", limit=4000)
    _list(data["warnings"], "warnings")
    for warning in data["warnings"]:
        _str(warning, "warning")
    _list(data["messages"], "messages")
    if not data["messages"]:
        raise ValueError("输入中没有消息")
    ids = set()
    for msg in data["messages"]:
        _object(msg, ("id", "timestamp", "sender", "text", "attachments"), ("sources",), "message")
        for field in ("id", "sender", "timestamp", "text"):
            _str(msg[field], f"message.{field}", empty=field in ("timestamp", "text"))
        if msg["id"] in ids:
            raise ValueError(f"重复消息 ID：{msg['id']}")
        ids.add(msg["id"])
        _list(msg["attachments"], "attachments", maximum=1000)
        if not msg["text"].strip() and not msg["attachments"]:
            raise ValueError("消息正文和附件不能同时为空")
        for att in msg["attachments"]:
            _object(att, ("name", "source", "kind", "status"), label="attachment")
            for field in att:
                _str(att[field], f"attachment.{field}", empty=field == "source")
            if att["status"] != "indexed_not_rendered":
                raise ValueError("附件仅允许 indexed_not_rendered 状态")
        _list(msg.get("sources", []), "sources", maximum=10_000)
        for origin in msg.get("sources", []):
            _object(origin, ("file", "locator"), label="source")
            _str(origin["file"], "source.file")
            _str(origin["locator"], "source.locator")
    return data


def validate_report(report, messages):
    validate_messages(messages)
    _object(report, ("schema_version", "source_digest", "title", "summary", "conversation", "period", "sections"), ("keywords",), label="report")
    if type(report["schema_version"]) is not int or report["schema_version"] != 1:
        raise ValueError("不支持的 report schema_version")
    for field in ("title", "summary", "conversation", "period", "source_digest"):
        _str(report[field], f"report.{field}", empty=field == "period")
    if not re.fullmatch(r"[a-f0-9]{64}", report["source_digest"]) or report["source_digest"] != source_digest(messages):
        raise ValueError("source_digest 与本次材料不符；请基于当前 messages.json 重新整理报告")
    if report["conversation"] != messages["conversation"]:
        raise ValueError("报告会话与材料不一致")
    ids = {m["id"] for m in messages["messages"]}
    seen_sections = set()
    _list(report["sections"], "sections", maximum=8)
    if not report["sections"]:
        raise ValueError("报告至少需要一个 section")
    count = 0
    for section in report["sections"]:
        _object(section, ("key", "title", "items"), label="section")
        _str(section["key"], "section.key")
        if section["key"] not in SECTION_KEYS or section["key"] in seen_sections:
            raise ValueError("section.key 未知或重复")
        seen_sections.add(section["key"])
        _str(section["title"], "section.title")
        _list(section["items"], "items", maximum=1000)
        for item in section["items"]:
            count += 1
            _object(item, ("title", "body", "evidence_refs", "kind"), ("owner", "due", "status", "question", "answer", "conditions", "outcome", "steps"), "item")
            for field in ("title", "body", "kind"):
                _str(item[field], f"item.{field}")
            if item["kind"] not in KINDS:
                raise ValueError("未知的 item.kind")
            for field in ("owner", "due", "status"):
                if field in item:
                    _str(item[field], f"item.{field}", empty=True)
            for field in ("question", "answer", "conditions", "outcome"):
                if field in item:
                    _str(item[field], f"item.{field}")
            if "steps" in item:
                _list(item["steps"], "item.steps", maximum=30)
                for step in item["steps"]:
                    _str(step, "item.steps 步骤")
            if (item.get("answer") or item.get("steps")) and not item["evidence_refs"]:
                raise ValueError("回答和方法步骤必须引用原消息，不能填补未经证实的解决方案")
            _list(item["evidence_refs"], "evidence_refs")
            for ref in item["evidence_refs"]:
                _str(ref, "evidence_ref")
                if ref not in ids:
                    raise ValueError(f"引用不存在的消息：{ref}")
            if len(set(item["evidence_refs"])) != len(item["evidence_refs"]):
                raise ValueError("同一条目含重复引用")
            if item["kind"] in {"fact", "decision", "action", "asset"} and not item["evidence_refs"]:
                raise ValueError(f"{item['kind']} 条目必须引用原消息")
    if not count:
        raise ValueError("报告尚无内容，请先由 Agent 整理材料")
    if 'keywords' in report:
        _list(report['keywords'], 'keywords', maximum=24)
        for term in report['keywords']:
            _str(term, 'keywords 词条', limit=2000)
            if not 2 <= len(term.strip()) <= 40:
                raise ValueError('keywords 每个词条去首尾空格后须为 2–40 字')
        # Import here to avoid the terminology -> message-validation import cycle.
        from .keywords import build_topic_keywords, canonical_keyword, keyword_key
        from .terminology import review_terms
        reviews = review_terms(messages)
        keys = [keyword_key(canonical_keyword(term, reviews)) for term in report['keywords']]
        if len(set(keys)) != len(keys):
            raise ValueError('keywords 含重复词条（已忽略全半角、空格、大小写及已确认别名差异）')
        grounded = {keyword_key(item['term']) for item in build_topic_keywords(report, messages, term_reviews=reviews)}
        missing = [term for term, key in zip(report['keywords'], keys) if key not in grounded]
        if missing:
            raise ValueError('keywords 须命中消息自身正文，且不能是昵称或口水词；回复引用和附件不计：' + '、'.join(missing))
    return report
