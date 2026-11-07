"""Bounded, read-only chat imports. Chat content is always treated as data."""

from __future__ import annotations

import hashlib
import json
import re
import stat
import xml.etree.ElementTree as ET
import zipfile
from datetime import datetime, timedelta, timezone
from html import unescape
from pathlib import Path, PurePosixPath, PureWindowsPath

MAX_INPUT_BYTES = 32 * 1024 * 1024
MAX_ZIP_BYTES = 64 * 1024 * 1024
MAX_ZIP_MEMBERS = 512
MAX_ZIP_TOTAL_BYTES = 64 * 1024 * 1024
MAX_ZIP_MEMBER_BYTES = 16 * 1024 * 1024
MAX_QUOTED_XML_CHARS = 256 * 1024
MAX_QUOTE_DEPTH = 8
SUPPORTED_SUFFIXES = {".txt", ".json", ".jsonl"}
_BEIJING = timezone(timedelta(hours=8))
_CLOCK = r"\d{1,2}:\d{2}(?::\d{2}(?:\.\d+)?)?"
_DATE = r"\d{4}[-/]\d{1,2}[-/]\d{1,2}"
_STAMP = rf"(?:{_DATE}[ T])?{_CLOCK}(?:Z|[+-]\d{{2}}:\d{{2}})?"
_TIME_FIRST = re.compile(
    rf"^\[?(?P<time>{_STAMP})\]?\s+(?P<rest>\S.*?)\s*$"
)
_SENDER_FIRST = re.compile(
    rf"^(?P<sender>\S.*?)\s+\[?(?P<time>{_STAMP})\]?(?:\s*[:：]\s*(?P<body>.*))?$"
)


def _warning(warnings: list[str], text: str) -> None:
    if text not in warnings:
        warnings.append(text)


def _string(value: object, label: str, *, allow_number: bool = False) -> str:
    if value is None:
        return ""
    if isinstance(value, str):
        return value
    if allow_number and isinstance(value, (int, float)) and not isinstance(value, bool):
        return str(value)
    raise ValueError(f"{label} 必须是字符串")


def _first(record: dict, keys: tuple[str, ...]) -> object:
    for key in keys:
        if key in record and record[key] not in (None, ""):
            return record[key]
    return ""


def _unique_object(pairs: list[tuple[str, object]]) -> dict:
    result = {}
    for key, value in pairs:
        if key in result:
            raise ValueError(f"JSON 含重复字段：{key}，不能静默选择其中一个值")
        result[key] = value
    return result


def _reject_nonfinite(value: str) -> None:
    raise ValueError(f"JSON 不接受非有限数值：{value}")


def _load_json(text: str) -> object:
    return json.loads(text, object_pairs_hook=_unique_object, parse_constant=_reject_nonfinite)


def _decode(data: bytes, source: str, warnings: list[str]) -> str:
    if data.startswith((b"\xff\xfe", b"\xfe\xff")):
        encoding = "utf-16"
    else:
        encoding = "utf-8-sig"
    try:
        text = data.decode(encoding)
    except UnicodeDecodeError:
        try:
            text = data.decode("gb18030")
        except UnicodeDecodeError as exc:
            raise ValueError(f"{source} 编码无法识别；请提供 UTF-8 文本") from exc
        _warning(warnings, f"{source} 按 GB18030 解码，请核对中文是否正确。")
    if "\x00" in text:
        raise ValueError(f"{source} 含有 NUL 字节，不能作为聊天文本导入")
    return text


def _timestamp(record: dict, label: str, warnings: list[str]) -> str:
    value = _first(record, ("time_beijing", "timestamp", "time", "datetime", "create_time"))
    if isinstance(value, (int, float)) and not isinstance(value, bool):
        try:
            # The evidence exporter records Unix seconds, not milliseconds.
            value = datetime.fromtimestamp(value, _BEIJING).isoformat(timespec="seconds")
        except (ValueError, OverflowError, OSError) as exc:
            raise ValueError(f"{label} 的 Unix 时间戳超出有效范围") from exc
    value = _string(value, f"{label} 时间")
    if not value:
        _warning(warnings, "部分消息没有时间，已保留为空，未推测日期。")
    elif not re.search(r"\d{4}[-/]\d{1,2}[-/]\d{1,2}", value):
        _warning(warnings, "部分消息时间缺少完整日期，已保留原值，未补全日期。")
    return value


def _attachments(value: object, label: str) -> list[dict]:
    if value is None:
        return []
    if not isinstance(value, list):
        raise ValueError(f"{label} attachments 必须是数组")
    result = []
    for index, item in enumerate(value):
        if isinstance(item, str):
            name, source, kind = PurePosixPath(item.replace("\\", "/")).name, item, "file"
        elif isinstance(item, dict):
            source = _string(_first(item, ("source", "archive_path", "source_path", "path", "url")), f"{label} 附件来源")
            name = _string(_first(item, ("name", "file_name", "filename")), f"{label} 附件名称")
            name = name or PurePosixPath(source.replace("\\", "/")).name or f"附件{index + 1}"
            kind = _string(_first(item, ("kind", "type")), f"{label} 附件类型") or "file"
        else:
            raise ValueError(f"{label} 附件必须是字符串或对象")
        result.append({"name": name, "source": source, "kind": kind, "status": "indexed_not_rendered"})
    return result


def _int_metadata(value: object) -> int | None:
    if isinstance(value, bool):
        return None
    try:
        return int(value) if isinstance(value, (str, int)) else None
    except ValueError:
        return None


def _file_name_role(record: dict) -> str:
    """Old exports use file_name for every appmsg title, including links/quotes."""
    base, subtype = _int_metadata(record.get("base_type")), _int_metadata(record.get("sub_type"))
    packed = _int_metadata(record.get("local_type"))
    if packed is not None:
        base = base if base is not None else packed & 0xFFFFFFFF
        subtype = subtype if subtype not in (None, 0) else packed >> 32
    if subtype == 6 and base in (None, 49):
        return "file"
    if base not in (None, 49) or (subtype not in (None, 0, 6) and base in (None, 49)):
        return "non_file"
    message_type = str(record.get("message_type") or "").strip().lower()
    if message_type in {"文件", "file"}:
        return "file"
    if (record.get("quoted_message_id") or record.get("quoted_content") or record.get("link_url")
            or message_type in {"引用消息", "引用", "链接", "小程序", "合并聊天记录", "图片", "视频", "语音", "表情", "文本", "link", "quote", "reference", "image", "video", "voice", "text"}):
        return "non_file"
    return "unknown"


def _without_legacy_placeholders(value: object, role: str, label: str, warnings: list[str]) -> object:
    if role != "non_file" or not isinstance(value, list):
        return value
    kept = []
    for item in value:
        if (isinstance(item, dict) and item.get("kind") in {"file", "link_or_file"}
                and not _first(item, ("source", "archive_path", "source_path", "path", "url"))
                and (item.get("kind") == "link_or_file" or item.get("exists") is False)):
            _warning(warnings, f"{label} 已忽略旧导出器为非文件消息生成的无实体附件占位，未把消息标题认作文件。")
        else:
            kept.append(item)
    return kept


def _tag(element: ET.Element) -> str:
    return element.tag.rsplit("}", 1)[-1].lower() if isinstance(element.tag, str) else ""


def _child(element: ET.Element, name: str) -> ET.Element | None:
    return next((child for child in element if _tag(child) == name), None)


def _quoted_xml_candidate(value: str) -> str | None:
    candidate = value.lstrip("\ufeff \t\r\n")
    # Only strip a sender prefix when it immediately precedes XML, never prose.
    candidate = re.sub(r"^[^\s<>:]{1,160}:\s*(?=<|&(?:lt;|#0*60;|#x0*3c;))", "", candidate, count=1, flags=re.I)
    for _ in range(2):
        if candidate.startswith("&"):
            decoded = unescape(candidate)
            if decoded == candidate:
                break
            candidate = decoded.lstrip()
    return candidate if re.match(r"<(?:[A-Za-z_:]|\?xml\b|!)", candidate, re.I) else None


def _readable_quote(value: str, label: str, warnings: list[str], depth: int = 0, media_type: int | None = None) -> str:
    """Keep a readable title, never serialize WeChat media XML into a report.

    This applies solely to quoted_content and its nested refermsg/content fields.
    Ordinary message text and non-XML quoted prose/code are not filtered.
    """
    media_labels = {3: "图片", 34: "语音", 43: "视频", 47: "表情"}
    if media_type in media_labels:
        _warning(warnings, f"{label} 引用媒体仅保留存在性标记，实体未读取；媒体地址、密钥等元数据未纳入。")
        return f"[引用{media_labels[media_type]}，实体未读取]"
    candidate = _quoted_xml_candidate(value)
    if candidate is None:
        return value
    if depth >= MAX_QUOTE_DEPTH:
        _warning(warnings, f"{label} 嵌套引用超过解析层级上限，剩余结构化内容未纳入。")
        return "[嵌套引用层级过深，后续内容未纳入]"
    if len(candidate) > MAX_QUOTED_XML_CHARS:
        _warning(warnings, f"{label} 引用 XML 超过解析大小上限，仅保留存在性标记，内容未完整读取。")
        return "[引用结构化内容过大，未纳入]"
    if re.search(r"<!\s*(?:DOCTYPE|ENTITY)\b", candidate, re.I):
        _warning(warnings, f"{label} 引用 XML 含 DTD/实体声明，未解析，内容未完整读取。")
        return "[引用结构化内容未解析，原文未纳入]"
    try:
        root = ET.fromstring(candidate)
    except ET.ParseError:
        _warning(warnings, f"{label} 引用 XML 损坏或不完整，仅保留存在性标记，内容未完整读取。")
        return "[引用结构化内容解析失败，原文未纳入]"
    _warning(warnings, f"{label} 引用 XML 仅提取可读标题或媒体存在性标记，未读取实体；媒体地址、密钥等元数据未纳入，不能视为原引用已完整读取。")
    media_tags = {"img": "图片", "image": "图片", "videomsg": "视频", "video": "视频",
                  "voicemsg": "语音", "voice": "语音", "emoji": "表情", "location": "位置"}
    for node in (root, *list(root)):
        if _tag(node) in media_tags:
            return f"[引用{media_tags[_tag(node)]}，实体未读取]"
    app = root if _tag(root) == "appmsg" else _child(root, "appmsg")
    if app is None:
        _warning(warnings, f"{label} 引用 XML 类型尚不支持，仅保留存在性标记，内容未完整读取。")
        return "[引用结构化内容未解析，原文未纳入]"
    title_element = _child(app, "title")
    title = ""
    if title_element is not None:
        if len(title_element):
            title = "[引用标题含结构化内容，未完整读取]"
            _warning(warnings, f"{label} 引用标题包含嵌套结构，未作为普通标题展开。")
        elif title_element.text:
            title = _readable_quote(title_element.text.strip(), label, warnings, depth + 1)
    parts = [title] if title else []
    reference = _child(app, "refermsg")
    if reference is not None:
        nested = _child(reference, "content")
        nested_type_element = _child(reference, "type")
        nested_type = _int_metadata(nested_type_element.text) if nested_type_element is not None else None
        if nested is not None:
            if len(nested):
                nested_value = "".join(ET.tostring(child, encoding="unicode") for child in nested)
            else:
                nested_value = nested.text or ""
            if nested_value or nested_type in media_labels:
                parts.append("嵌套引用：" + _readable_quote(nested_value, label, warnings, depth + 1, nested_type))
        else:
            parts.append("[嵌套引用正文缺失，未纳入]")
            _warning(warnings, f"{label} 嵌套引用缺少 content，无法完整读取。")
    if not parts:
        _warning(warnings, f"{label} 引用 appmsg 缺少可读标题，内容未完整读取。")
        return "[引用消息无可读标题，原文未纳入]"
    return "\n".join(parts)


def _normalize_record(record: object, source: str, locator: str, warnings: list[str]) -> dict:
    label = f"{source} {locator}"
    if not isinstance(record, dict):
        raise ValueError(f"{label} 消息必须是对象，不能把格式化字符串当结构化消息")
    sender = _string(_first(record, ("sender_display_name", "sender", "sender_name", "from", "sender_id")), f"{label} 发言人")
    if not sender or sender in {"[发言人未识别]", "[未知]"}:
        sender = "待确认"
        _warning(warnings, "部分消息没有可识别的发言人，已标记为待确认。")
    timestamp = _timestamp(record, label, warnings)
    text_value = _first(record, ("text", "content", "message"))
    text = _string(text_value, f"{label} 正文")
    extras = []
    for field, heading in (
        ("link_title", "链接标题"), ("link_url", "链接"), ("card_summary", "卡片摘要"),
        ("mini_program_name", "小程序"), ("quoted_message_id", "引用消息 ID"),
        ("quoted_sender", "引用发言人"), ("quoted_content", "引用内容"),
    ):
        value = _string(record.get(field), f"{label} {field}", allow_number=field == "quoted_message_id")
        if value:
            if field == "quoted_content":
                value = _readable_quote(value, label, warnings)
            extras.append(f"{heading}：{value}")
    if extras:
        text = "\n".join(([text] if text else []) + extras)
    file_role = _file_name_role(record)
    attachment_records = _without_legacy_placeholders(record.get("attachments", []), file_role, label, warnings)
    attachments = _attachments(attachment_records, label)
    file_name = _string(record.get("file_name"), f"{label} file_name")
    if file_name and not attachments:
        if file_role == "file":
            attachments = [{"name": file_name, "source": "", "kind": "file", "status": "indexed_not_rendered"}]
        else:
            heading = "消息标题" if file_role == "non_file" else "名称字段（类型待确认）"
            if file_name not in text:
                text = "\n".join(part for part in (text, f"{heading}：{file_name}") if part)
            _warning(warnings, f"{label} file_name 没有明确文件类型依据，已按标题/名称保留，未生成文件附件。")
    if not text and not attachments:
        raw = _string(record.get("raw_content"), f"{label} raw_content")
        if raw:
            text = raw
            _warning(warnings, f"{label} 未提供可读正文，已保留原始内容为文本。")
        else:
            raise ValueError(f"{label} 消息没有正文或附件，无法作为证据导入")
    if attachments:
        _warning(warnings, "附件仅建立索引，本版未读取或渲染附件实体；图片、语音、视频内容未纳入提炼。")
    parse_status = _string(record.get("parse_status"), f"{label} parse_status")
    if parse_status and parse_status not in {"ok", "parsed", "success"}:
        _warning(warnings, f"{label} 原导出解析状态：{parse_status}")
    message_id = _string(_first(record, ("id", "message_id")), f"{label} 消息 ID", allow_number=True)
    if not message_id.strip():
        material = json.dumps([source, locator, timestamp, sender, text, attachments], ensure_ascii=False, sort_keys=True)
        message_id = "local:" + hashlib.sha256(material.encode("utf-8")).hexdigest()[:24]
    sources = [{"file": source, "locator": locator}]
    # Retain earlier source locators when an already normalized export is reimported.
    previous_sources = record.get("sources", [])
    if not isinstance(previous_sources, list):
        raise ValueError(f"{label} sources 必须是数组")
    for item in previous_sources:
        if not isinstance(item, dict) or set(item) != {"file", "locator"}:
            raise ValueError(f"{label} sources 项必须包含 file 和 locator")
        if not all(isinstance(item[key], str) and item[key] for key in ("file", "locator")):
            raise ValueError(f"{label} sources 项必须是非空字符串")
        if item not in sources:
            sources.append(dict(item))
    return {"id": message_id, "timestamp": timestamp, "sender": sender, "text": text,
            "attachments": attachments, "sources": sources}


def _valid_time(value: str) -> bool:
    try:
        if re.match(_DATE, value):
            normalized = value.replace("/", "-").replace("Z", "+00:00")
            # strptime accepts non-zero-padded month/day from common TXT exports.
            date_part, clock_part = re.split(r"[ T]", normalized, maxsplit=1)
            year, month, day = (int(part) for part in date_part.split("-"))
            datetime(year, month, day)
        else:
            clock_part = value
        clock = re.match(r"(\d{1,2}):(\d{2})(?::(\d{2}))?", clock_part)
        return bool(clock and 0 <= int(clock[1]) <= 23 and 0 <= int(clock[2]) <= 59
                    and (clock[3] is None or 0 <= int(clock[3]) <= 59))
    except (ValueError, TypeError):
        return False


def _header(line: str) -> tuple[str, str, str] | None:
    first = _TIME_FIRST.fullmatch(line)
    if first and _valid_time(first["time"]):
        rest = first["rest"]
        if ":" in rest or "：" in rest:
            sender, body = re.split(r"[:：]", rest, maxsplit=1)
        else:
            sender, body = rest, ""
        if sender.strip():
            return first["time"], sender.strip(), body.lstrip()
    second = _SENDER_FIRST.fullmatch(line)
    if second and _valid_time(second["time"]):
        return second["time"], second["sender"].strip(), second["body"] or ""
    return None


def _parse_txt(text: str, source: str, warnings: list[str]) -> list[dict]:
    result = []
    current = None
    lines: list[str] = []
    start_line = 1
    last_line = 0

    def flush() -> None:
        nonlocal lines, current
        body = "\n".join(lines).strip("\n")
        if body or current:
            if not body:
                raise ValueError(f"{source} line:{start_line} 只有消息头，没有正文")
            record = {"text": body, "sender": current[1] if current else "", "timestamp": current[0] if current else ""}
            locator = f"line:{start_line}" if start_line == last_line else f"lines:{start_line}-{last_line}"
            result.append(_normalize_record(record, source, locator, warnings))
            if not current:
                _warning(warnings, f"{source} {locator} 未识别出可靠的消息头，原文本段已保留，时间和发言人未推测。")
        lines, current = [], None

    for line_number, line in enumerate(text.splitlines(), 1):
        header = _header(line)
        if header:
            flush()
            current, start_line = header, line_number
            lines = [header[2]] if header[2] else []
        elif not current and not line.strip():
            flush()
            start_line = line_number + 1
        else:
            if not lines and not current:
                start_line = line_number
            lines.append(line)
        last_line = line_number
    flush()
    return result


def _parse_document(data: bytes, source: str, warnings: list[str]) -> tuple[list[dict], list[str]]:
    text = _decode(data, source, warnings)
    if not text.strip():
        raise ValueError(f"{source} 是空输入")
    suffix = PurePosixPath(source).suffix.lower()
    if suffix == ".txt":
        return _parse_txt(text, source, warnings), []
    records: list[tuple[object, str]] = []
    conversations = []
    try:
        if suffix == ".jsonl":
            for line_number, line in enumerate(text.splitlines(), 1):
                if line.strip():
                    try:
                        records.append((_load_json(line), f"line:{line_number}"))
                    except json.JSONDecodeError as exc:
                        raise ValueError(f"{source} line:{line_number} JSON 无效：{exc.msg}") from exc
        else:
            payload = _load_json(text)
            if isinstance(payload, dict):
                raw_records = payload.get("messages")
                title = _first(payload, ("conversation", "conversation_name", "chat"))
                if title:
                    conversations.append(_string(title, f"{source} conversation"))
                imported_warnings = payload.get("warnings", [])
                if not isinstance(imported_warnings, list) or not all(isinstance(item, str) for item in imported_warnings):
                    raise ValueError(f"{source} warnings 必须是字符串数组")
                for item in imported_warnings:
                    _warning(warnings, item)
                locator_prefix = "$.messages"
            elif isinstance(payload, list):
                raw_records, locator_prefix = payload, "$"
            else:
                raise ValueError(f"{source} JSON 顶层必须是 messages 对象或消息数组")
            if not isinstance(raw_records, list):
                raise ValueError(f"{source} 缺少 messages 数组")
            records = [(record, f"{locator_prefix}[{index}]") for index, record in enumerate(raw_records)]
    except json.JSONDecodeError as exc:
        raise ValueError(f"{source} JSON 无效（第 {exc.lineno} 行）：{exc.msg}") from exc
    if not records:
        raise ValueError(f"{source} 没有消息")
    messages = []
    for record, locator in records:
        messages.append(_normalize_record(record, source, locator, warnings))
        title = _first(record, ("conversation_name", "conversation", "chat"))
        if title:
            conversations.append(_string(title, f"{source} {locator} conversation"))
    return messages, conversations


def _safe_member(info: zipfile.ZipInfo) -> str:
    name = info.filename.replace("\\", "/")
    path = PurePosixPath(name)
    if (not name or name.startswith("/") or PureWindowsPath(name).drive
            or ".." in path.parts or ":" in name or "\x00" in info.orig_filename):
        raise ValueError(f"ZIP 包含不安全路径：{info.filename!r}")
    mode = info.external_attr >> 16
    if stat.S_ISLNK(mode) or (stat.S_IFMT(mode) not in (0, stat.S_IFREG, stat.S_IFDIR)):
        raise ValueError(f"ZIP 不允许符号链接或特殊文件：{info.filename}")
    if info.flag_bits & 1:
        raise ValueError(f"ZIP 不支持加密成员：{info.filename}")
    if info.file_size > MAX_ZIP_MEMBER_BYTES:
        raise ValueError(f"ZIP 单文件超过大小上限：{info.filename}")
    return str(path)


def _read_zip(path: Path, warnings: list[str]) -> tuple[list[dict], list[str]]:
    if path.stat().st_size > MAX_ZIP_BYTES:
        raise ValueError("ZIP 文件超过压缩包大小上限")
    messages, conversations = [], []
    try:
        with zipfile.ZipFile(path) as archive:
            infos = archive.infolist()
            if len(infos) > MAX_ZIP_MEMBERS:
                raise ValueError("ZIP 成员数量超过上限")
            total, names, checked = 0, set(), []
            for info in infos:
                name = _safe_member(info)
                if name.casefold() in names:
                    raise ValueError(f"ZIP 包含重复或大小写冲突路径：{name}")
                names.add(name.casefold())
                total += info.file_size
                if total > MAX_ZIP_TOTAL_BYTES:
                    raise ValueError("ZIP 解压总量超过上限")
                checked.append((info, name))
            supported = [(info, name) for info, name in checked
                         if not info.is_dir() and PurePosixPath(name).suffix.lower() in SUPPORTED_SUFFIXES]
            if not supported:
                raise ValueError("ZIP 中没有支持的 TXT、JSONL 或 JSON 消息文件")
            for info, name in checked:
                if info.is_dir():
                    continue
                if PurePosixPath(name).suffix.lower() not in SUPPORTED_SUFFIXES:
                    _warning(warnings, f"附件索引（未关联消息、未渲染实体）：{name}（{info.file_size} 字节）。")
            for info, name in supported:
                with archive.open(info, "r") as stream:
                    data = stream.read(MAX_ZIP_MEMBER_BYTES + 1)
                if len(data) > MAX_ZIP_MEMBER_BYTES or len(data) != info.file_size:
                    raise ValueError(f"ZIP 成员实际大小与声明不符或超限：{name}")
                part, titles = _parse_document(data, f"{path.name}!/{name}", warnings)
                messages.extend(part)
                conversations.extend(titles)
    except (zipfile.BadZipFile, NotImplementedError, RuntimeError, EOFError) as exc:
        raise ValueError(f"无法读取 ZIP：{exc}") from exc
    return messages, conversations


def _deduplicate(messages: list[dict], warnings: list[str]) -> list[dict]:
    unique = {}
    duplicates = 0
    for message in messages:
        previous = unique.get(message["id"])
        if previous is None:
            unique[message["id"]] = message
            continue
        # Do not silently choose one body when the same stable ID conflicts.
        fields = ("timestamp", "sender", "text", "attachments")
        if any(previous[field] != message[field] for field in fields):
            raise ValueError(f"消息 ID 冲突：{message['id']}，同一 ID 对应不同正文或元数据")
        duplicates += 1
        for source in message["sources"]:
            if source not in previous["sources"]:
                previous["sources"].append(source)
    if duplicates:
        _warning(warnings, f"已按稳定消息 ID 合并 {duplicates} 条重复记录，保留全部来源位置。")
    return list(unique.values())


def import_source(path: Path, conversation: str | None = None) -> dict:
    """Import TXT/JSON/JSONL/ZIP without changing inputs or extracting files.

    Raises ValueError for malformed, empty, oversized, conflicting or unsafe data.
    Generic JSON messages must be objects; wechat-cli's formatted-string JSON
    output is intentionally rejected in favour of the evidence exporter JSONL.
    """
    path = Path(path)
    if not path.is_file():
        raise ValueError(f"输入不是可读文件：{path}")
    if conversation is not None and (not isinstance(conversation, str) or not conversation.strip()):
        raise ValueError("conversation 必须是非空字符串")
    warnings: list[str] = []
    suffix = path.suffix.lower()
    if suffix == ".zip":
        messages, conversations = _read_zip(path, warnings)
    elif suffix in SUPPORTED_SUFFIXES:
        if path.stat().st_size > MAX_INPUT_BYTES:
            raise ValueError("输入文件超过大小上限")
        with path.open("rb") as stream:
            data = stream.read(MAX_INPUT_BYTES + 1)
        if len(data) > MAX_INPUT_BYTES:
            raise ValueError("输入文件读取期间超过大小上限")
        messages, conversations = _parse_document(data, path.name, warnings)
    else:
        raise ValueError("仅支持 .txt、.jsonl、.json 和 .zip 输入")
    if not messages:
        raise ValueError("输入没有可导入的消息")
    messages = _deduplicate(messages, warnings)
    titles = list(dict.fromkeys(title for title in conversations if title.strip()))
    if len(titles) > 1:
        _warning(warnings, "输入包含多个会话：" + "、".join(titles) + "。请核对是否应合并为同一份报告。")
    resolved_title = conversation or (titles[0] if len(titles) == 1 else None)
    if not resolved_title:
        resolved_title = f"多会话导入（{len(titles)} 个）" if titles else path.stem
    timed = sum(bool(message["timestamp"]) for message in messages)
    coverage = f"已导入提供材料中的 {len(messages)} 条消息；其中 {timed} 条带时间。仅代表输入材料，不保证群聊时间段完整。"
    return {"schema_version": 1, "conversation": resolved_title, "coverage": coverage,
            "messages": messages, "warnings": warnings}
