"""Review confirmed, context-bound aliases without rewriting any evidence.

``review_terms(messages)`` returns one record per alias occurrence. ``start``
and ``end`` are Python string offsets in that message's original text (end is
exclusive), never UTF-16/JavaScript offsets. Consumers can use ``original`` and
``canonical`` for presentation/search; neither this module nor callers should
replace text inside messages or recalculate its digest to hide a correction.
"""
from __future__ import annotations

import json
import re
import unicodedata
from datetime import datetime
from importlib.resources import files

from .validation import validate_messages

RULES_SOURCE = "qunhuibao/assets/terminology.json"


def _normalized(text: str) -> tuple[str, list[int]]:
    """Normalize width/case while retaining offsets into the original string."""
    characters: list[str] = []
    offsets: list[int] = []
    for index, character in enumerate(text):
        normalized = unicodedata.normalize("NFKC", character).casefold()
        characters.extend(normalized)
        offsets.extend([index] * len(normalized))
    return "".join(characters), offsets


def _pattern(value: str) -> re.Pattern:
    normalized, _ = _normalized(value)
    # Flexible spacing applies inside the configured alias, not arbitrary words.
    body = r"\s*".join(re.escape(part) for part in normalized.split())
    return re.compile(r"(?<![a-z0-9_])" + body + r"(?![a-z0-9_])")


def _has_term(text: str, terms: list[str]) -> bool:
    for term in terms:
        normalized, _ = _normalized(term)
        if normalized.isascii():
            if _pattern(term).search(text):
                return True
        elif normalized in text:
            return True
    return False


def _near_in_time(first: dict, second: dict, maximum: int) -> bool:
    """Known timestamps restrict adjacency; missing timestamps add no date."""
    try:
        left = datetime.fromisoformat(first["timestamp"].replace("Z", "+00:00"))
        right = datetime.fromisoformat(second["timestamp"].replace("Z", "+00:00"))
        return abs((left - right).total_seconds()) <= maximum
    except (ValueError, TypeError):
        return True


def _ordinary_phrase(normalized: str, start: int, end: int, context: dict) -> bool:
    """Do not interpret an ordinary imperative/verb-object phrase as a name."""
    before = normalized[max(0, start - 48):start].rstrip()
    after = normalized[end:end + 48].lstrip()
    for phrase in context["non_product_prefixes"]:
        if any(match.end() == len(before) for match in _pattern(phrase).finditer(before)):
            return True
    return any(_pattern(phrase).match(after) for phrase in context["non_product_suffixes"])


def _context_reason(rows: list[dict], index: int, normalized: str,
                    start: int, end: int, context: dict) -> str | None:
    if _ordinary_phrase(normalized, start, end, context):
        return None
    radius = context["character_radius"]
    local = normalized[max(0, start - radius):end + radius]
    if _has_term(local, context["exclude"]):
        return None
    if _has_term(local, context["any"]):
        return "已确认别名；本条消息命中视频剪辑语境。仅用于整理和检索，原文保持不变。"
    distance = context["message_radius"]
    for neighbor in range(max(0, index - distance), min(len(rows), index + distance + 1)):
        if neighbor == index or not _near_in_time(rows[index], rows[neighbor], context["max_gap_seconds"]):
            continue
        # Avoid borrowing a remote sentence inside a very long neighboring item.
        text = rows[neighbor]["text"][-radius:] if neighbor < index else rows[neighbor]["text"][:radius]
        nearby, _ = _normalized(text)
        if not _has_term(nearby, context["exclude"]) and _has_term(nearby, context["any"]):
            return "已确认别名；附近消息命中视频剪辑语境。仅用于整理和检索，原文保持不变。"
    return None


def review_terms(messages: dict) -> list[dict]:
    """Return confirmed alias occurrences in matching context; never mutate input.

    Unmatched/ambiguous words are left for the Agent's semantic review rather
    than silently extending the confirmed dictionary. No surrounding chat text
    is copied into the result; ``original`` contains only the matched alias.
    """
    validate_messages(messages)
    data = json.loads(files("qunhuibao").joinpath("assets", "terminology.json").read_text(encoding="utf-8"))
    rules = [rule for rule in data["rules"]
             if rule["status"] == "confirmed" and rule["confidence"] == "high"
             and rule["action"] == "normalize_summary_and_search"]
    patterns = [(rule, _pattern(alias)) for rule in rules for alias in rule["aliases"]]
    rows = messages["messages"]
    result: list[dict] = []
    for index, message in enumerate(rows):
        text = message["text"]
        normalized, offsets = _normalized(text)
        seen = set()
        for rule, pattern in patterns:
            for match in pattern.finditer(normalized):
                start, end = offsets[match.start()], offsets[match.end() - 1] + 1
                key = (rule["id"], start, end)
                if key in seen:
                    continue
                reason = _context_reason(rows, index, normalized, match.start(), match.end(), rule["context"])
                if reason is None:
                    continue
                seen.add(key)
                result.append({
                    "message_id": message["id"], "original": text[start:end],
                    "canonical": rule["canonical"], "rule_id": rule["id"],
                    "start": start, "end": end, "reason": reason,
                })
    order = {message["id"]: index for index, message in enumerate(rows)}
    return sorted(result, key=lambda item: (order[item["message_id"]], item["start"], item["end"]))
