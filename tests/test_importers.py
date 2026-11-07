import json
import stat
import tempfile
import unittest
import zipfile
from html import escape
from pathlib import Path
from unittest.mock import patch

from qunhuibao.importers import import_source


class ImportSourceTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)

    def write(self, name, content):
        path = self.root / name
        if isinstance(content, bytes):
            path.write_bytes(content)
        else:
            path.write_text(content, encoding="utf-8")
        return path

    def archive(self, entries, name="messages.zip"):
        path = self.root / name
        with zipfile.ZipFile(path, "w", zipfile.ZIP_DEFLATED) as archive:
            for member, data in entries:
                archive.writestr(member, data)
        return path

    def test_evidence_jsonl_mapping_and_read_only(self):
        record = {
            "message_id": "demo@chatroom:svr:123",
            "conversation_name": "演示项目群", "sender_display_name": "小林",
            "timestamp": 1793926800, "time_beijing": "2026-11-06T10:20:00+08:00",
            "text": "我来整理需求。", "raw_content": "不应重复展示的原始XML",
            "link_title": "演示资料", "link_url": "https://example.com/demo",
            "quoted_message_id": "demo:122", "quoted_sender": "小周", "quoted_content": "还缺哪些材料？",
            "attachments": [{"file_name": "需求.pdf", "source_path": "missing/需求.pdf", "kind": "file"}],
        }
        path = self.write("evidence.jsonl", json.dumps(record, ensure_ascii=False) + "\n")
        before = path.read_bytes()
        result = import_source(path)
        self.assertEqual(result["conversation"], "演示项目群")
        message = result["messages"][0]
        self.assertEqual(message["id"], record["message_id"])
        self.assertEqual(message["timestamp"], record["time_beijing"])
        self.assertEqual(message["sender"], "小林")
        self.assertIn("引用内容：还缺哪些材料？", message["text"])
        self.assertNotIn("不应重复展示", message["text"])
        self.assertEqual(message["sources"], [{"file": "evidence.jsonl", "locator": "line:1"}])
        self.assertEqual(message["attachments"][0]["status"], "indexed_not_rendered")
        self.assertTrue(any("附件仅建立索引" in warning for warning in result["warnings"]))
        self.assertEqual(path.read_bytes(), before)

    def test_structured_json_and_timestamp_seconds(self):
        path = self.write("messages.json", json.dumps({"conversation": "演示群", "messages": [
            {"id": "m1", "timestamp": 0, "sender": "小张", "text": "准备方案"}
        ]}))
        result = import_source(path, "指定会话")
        self.assertEqual(result["conversation"], "指定会话")
        self.assertEqual(result["messages"][0]["timestamp"], "1970-01-01T08:00:00+08:00")
        self.assertEqual(result["messages"][0]["sources"][0]["locator"], "$.messages[0]")

    def test_txt_both_header_orders_and_multiline(self):
        path = self.write("chat.txt", "[2026-11-06 10:20:00] 小林：第一条\n补充说明\n\n小周 2026-11-06 10:21:00\n第二条\n")
        messages = import_source(path)["messages"]
        self.assertEqual(len(messages), 2)
        self.assertEqual(messages[0]["sender"], "小林")
        self.assertEqual(messages[0]["text"], "第一条\n补充说明")
        self.assertEqual(messages[1]["sender"], "小周")
        self.assertEqual(messages[1]["text"], "第二条")
        self.assertEqual(messages[0]["sources"][0]["locator"], "lines:1-3")
        self.assertEqual(messages[1]["sources"][0]["locator"], "lines:4-5")

    def test_unparsed_text_is_preserved_without_invented_identity(self):
        original = "大家需要讨论如何安排。\n暂时没有截止时间。\n\n另一段原文。"
        path = self.write("plain.txt", original)
        result = import_source(path)
        self.assertEqual(len(result["messages"]), 2)
        self.assertEqual(result["messages"][0]["text"], "大家需要讨论如何安排。\n暂时没有截止时间。")
        self.assertEqual(result["messages"][0]["timestamp"], "")
        self.assertEqual(result["messages"][0]["sender"], "待确认")
        self.assertTrue(any("原文本段已保留" in warning for warning in result["warnings"]))
        self.assertEqual(import_source(path), result)

    def test_time_only_keeps_missing_date(self):
        path = self.write("time.txt", "小林 10:20\n先做演示。")
        result = import_source(path)
        self.assertEqual(result["messages"][0]["timestamp"], "10:20")
        self.assertTrue(any("缺少完整日期" in warning for warning in result["warnings"]))

    def test_invalid_date_is_not_fabricated(self):
        source = "2026-02-30 10:20 小林：无效日期\n下一行"
        result = import_source(self.write("invalid.txt", source))
        self.assertEqual(result["messages"][0]["text"], source)
        self.assertEqual(result["messages"][0]["timestamp"], "")

    def test_explicit_ids_deduplicate_and_keep_all_sources(self):
        message = {"id": "stable-1", "sender": "小林", "timestamp": "2026-11-06 10:00", "text": "演示消息"}
        path = self.archive([
            ("part1.jsonl", json.dumps(message)), ("part2.jsonl", json.dumps(message))
        ])
        result = import_source(path)
        self.assertEqual(len(result["messages"]), 1)
        self.assertEqual(len(result["messages"][0]["sources"]), 2)
        self.assertTrue(any("合并 1 条" in warning for warning in result["warnings"]))

    def test_conflicting_id_is_error(self):
        records = [{"id": "same", "text": "原文"}, {"id": "same", "text": "修改过的原文"}]
        path = self.write("conflict.json", json.dumps({"messages": records}))
        with self.assertRaisesRegex(ValueError, "ID 冲突"):
            import_source(path)

    def test_identical_text_without_stable_id_is_not_wrongly_merged(self):
        path = self.write("repeat.json", json.dumps({"messages": [{"text": "收到"}, {"text": "收到"}]}))
        messages = import_source(path)["messages"]
        self.assertEqual(len(messages), 2)
        self.assertNotEqual(messages[0]["id"], messages[1]["id"])

    def test_json_formatted_strings_fail_with_explanation(self):
        path = self.write("cli.json", json.dumps({"messages": ["[10:20] 小林：你好"]}))
        with self.assertRaisesRegex(ValueError, "格式化字符串"):
            import_source(path)

    def test_duplicate_json_fields_and_nonfinite_values_rejected(self):
        cases = [
            ("duplicate.json", '{"messages":[{"text":"第一段","text":"第二段"}]}', "重复字段"),
            ("duplicate.jsonl", '{"text":"第一段","text":"第二段"}', "重复字段"),
            ("nonfinite.json", '{"messages":[{"text":"正文","timestamp":NaN}]}', "非有限数值"),
        ]
        for name, data, error in cases:
            with self.subTest(name=name):
                with self.assertRaisesRegex(ValueError, error):
                    import_source(self.write(name, data))

    def test_zip_text_json_and_attachment_index_without_extraction(self):
        path = self.archive([
            ("part/chat.txt", "小林 10:20\n演示一"),
            ("part/chat.json", json.dumps({"messages": [{"id": "m2", "text": "演示二"}]})),
            ("assets/photo.png", b"not a real image"),
        ])
        before = set(self.root.iterdir())
        result = import_source(path)
        self.assertEqual(len(result["messages"]), 2)
        self.assertEqual(set(self.root.iterdir()), before)
        self.assertTrue(any("assets/photo.png" in warning and "未关联消息" in warning for warning in result["warnings"]))
        self.assertEqual(result["messages"][0]["attachments"], [])

    def test_zip_unsafe_paths_rejected_even_for_unused_attachments(self):
        for name in ("../outside.txt", "/root/file.bin", "C:/outside.bin", "..\\outside.bin", "foo/../../x.bin", "file:stream.bin"):
            with self.subTest(name=name):
                path = self.archive([("chat.txt", "演示内容"), (name, "unused")])
                with self.assertRaisesRegex(ValueError, "不安全路径"):
                    import_source(path)

    def test_zip_symlink_and_duplicate_paths_rejected(self):
        info = zipfile.ZipInfo("link.txt")
        info.create_system = 3
        info.external_attr = (stat.S_IFLNK | 0o777) << 16
        path = self.archive([(info, "outside.txt")])
        with self.assertRaisesRegex(ValueError, "符号链接"):
            import_source(path)
        path = self.archive([("chat.txt", "一"), ("CHAT.TXT", "二")])
        with self.assertRaisesRegex(ValueError, "重复或大小写冲突"):
            import_source(path)

    def test_input_and_all_zip_resource_limits(self):
        path = self.write("large.txt", "1234567890")
        with patch("qunhuibao.importers.MAX_INPUT_BYTES", 5):
            with self.assertRaisesRegex(ValueError, "大小上限"):
                import_source(path)
        zipped = self.archive([("one.txt", "123456"), ("two.txt", "789012")])
        for constant, value, expected in (
            ("MAX_ZIP_BYTES", 1, "压缩包大小"),
            ("MAX_ZIP_MEMBERS", 1, "成员数量"),
            ("MAX_ZIP_TOTAL_BYTES", 10, "解压总量"),
            ("MAX_ZIP_MEMBER_BYTES", 5, "单文件"),
        ):
            with self.subTest(constant=constant), patch(f"qunhuibao.importers.{constant}", value):
                with self.assertRaisesRegex(ValueError, expected):
                    import_source(zipped)

    def test_empty_invalid_and_unsupported_inputs(self):
        cases = [("empty.txt", " \n\t"), ("empty.json", '{"messages":[]}'),
                 ("broken.jsonl", '{"text":"ok"}\n{broken'), ("other.csv", "a,b"),
                 ("binary.txt", b"a\x00b"), ("schema.json", '{"notes":"not messages"}')]
        for name, content in cases:
            with self.subTest(name=name):
                with self.assertRaises(ValueError):
                    import_source(self.write(name, content))
        path = self.archive([("only.png", b"image")])
        with self.assertRaisesRegex(ValueError, "没有支持"):
            import_source(path)
        with self.assertRaisesRegex(ValueError, "空输入"):
            import_source(self.archive([("blank.txt", ""), ("valid.txt", "不能掩盖空文件")]))

    def test_utf16_and_gb18030_encodings(self):
        text = "小林 10:20\n中文演示"
        for encoding in ("utf-16", "gb18030"):
            with self.subTest(encoding=encoding):
                result = import_source(self.write("encoded.txt", text.encode(encoding)))
                self.assertEqual(result["messages"][0]["text"], "中文演示")
                if encoding == "gb18030":
                    self.assertTrue(any("GB18030" in warning for warning in result["warnings"]))

    def test_unknown_attachment_entity_is_not_read(self):
        path = self.write("attachment.json", json.dumps({"messages": [{
            "id": "attachment-1", "attachments": [{"name": "private.pdf", "source": "C:/private/not-read.pdf"}]
        }]}))
        message = import_source(path)["messages"][0]
        self.assertEqual(message["text"], "")
        self.assertEqual(message["attachments"][0]["name"], "private.pdf")

    def test_multi_conversation_is_visible_and_reimport_keeps_sources(self):
        path = self.write("mixed.jsonl", "\n".join(json.dumps(item) for item in [
            {"id": "a", "conversation_name": "演示群甲", "text": "第一条"},
            {"id": "b", "conversation_name": "演示群乙", "text": "第二条"},
        ]))
        result = import_source(path)
        self.assertEqual(result["conversation"], "多会话导入（2 个）")
        self.assertTrue(any("多个会话" in warning for warning in result["warnings"]))
        copy = self.write("normalized.json", json.dumps(result))
        imported = import_source(copy)
        self.assertIn({"file": "mixed.jsonl", "locator": "line:1"}, imported["messages"][0]["sources"])

    def test_large_body_is_not_truncated(self):
        body = "完整文本" * 30000
        path = self.write("long.json", json.dumps({"messages": [{"text": body}]}))
        self.assertEqual(import_source(path)["messages"][0]["text"], body)

    def test_old_app_titles_are_not_synthetic_file_attachments(self):
        for subtype in (5, 57):
            with self.subTest(subtype=subtype):
                record = {"id": "demo-app", "base_type": 49, "sub_type": subtype,
                          "message_type": "链接/文件", "file_name": "演示标题",
                          "text": "[引用或链接：演示标题]"}
                result = import_source(self.write("old-app.jsonl", json.dumps(record)))
                self.assertEqual(result["messages"][0]["attachments"], [])
                self.assertIn("演示标题", result["messages"][0]["text"])
                self.assertTrue(any("未生成文件附件" in warning for warning in result["warnings"]))

    def test_real_file_subtype_is_kept_and_ambiguous_filename_is_only_text(self):
        metadata_cases = [{"base_type": 49, "sub_type": "6"},
                          {"local_type": str((6 << 32) | 49)}, {"message_type": "文件"}]
        for metadata in metadata_cases:
            with self.subTest(metadata=metadata):
                record = {"id": "file-demo", "file_name": "演示方案.pdf", **metadata}
                result = import_source(self.write("file.json", json.dumps({"messages": [record]})))
                self.assertEqual(result["messages"][0]["attachments"][0]["name"], "演示方案.pdf")
        result = import_source(self.write("ambiguous.jsonl", json.dumps({"text": "演示", "file_name": "尚未确认的名称"})))
        self.assertEqual(result["messages"][0]["attachments"], [])
        self.assertIn("名称字段（类型待确认）：尚未确认的名称", result["messages"][0]["text"])

    def test_quote_and_link_hints_prevent_file_inference(self):
        for metadata in ({"quoted_message_id": "demo-reference"}, {"message_type": "引用消息"},
                         {"link_url": "https://example.com/demo"}, {"quoted_content": "普通引用文字"}):
            with self.subTest(metadata=metadata):
                record = {"id": "hint-demo", "text": "演示消息", "file_name": "一个标题", **metadata}
                result = import_source(self.write("hint.jsonl", json.dumps(record)))
                self.assertEqual(result["messages"][0]["attachments"], [])

    def test_legacy_placeholder_is_removed_but_explicit_attachment_is_kept(self):
        record = {"id": "quote-demo", "base_type": 49, "sub_type": 57, "text": "演示引用",
                  "file_name": "演示引用", "attachments": [
                      {"kind": "link_or_file", "file_name": "演示引用", "source_path": "", "exists": False}
                  ]}
        result = import_source(self.write("placeholder.jsonl", json.dumps(record)))
        self.assertEqual(result["messages"][0]["attachments"], [])
        self.assertTrue(any("无实体附件占位" in warning for warning in result["warnings"]))
        record["attachments"].append({"kind": "file", "file_name": "单独附带.pdf", "source_path": "demo/单独附带.pdf"})
        result = import_source(self.write("explicit.jsonl", json.dumps(record)))
        self.assertEqual(len(result["messages"][0]["attachments"]), 1)
        self.assertEqual(result["messages"][0]["attachments"][0]["name"], "单独附带.pdf")

    def test_quoted_media_xml_never_leaks_transport_metadata(self):
        for tag, label in (("img", "图片"), ("videomsg", "视频"), ("voicemsg", "语音")):
            with self.subTest(tag=tag):
                xml = f'wxid_demo_only:\n<msg><{tag} aeskey="FAKE_MEDIA_KEY" cdnurl="https://demo.invalid/FAKE_CDN_PATH" /></msg>'
                record = {"id": "media-demo", "text": "普通正文保留", "quoted_content": xml}
                result = import_source(self.write("media.jsonl", json.dumps(record)))
                self.assertIn(f"[引用{label}，实体未读取]", result["messages"][0]["text"])
                serialized = json.dumps(result, ensure_ascii=False)
                self.assertNotIn("FAKE_MEDIA_KEY", serialized)
                self.assertNotIn("FAKE_CDN_PATH", serialized)
                self.assertNotIn("wxid_demo_only", serialized)
                self.assertTrue(any("元数据未纳入" in warning for warning in result["warnings"]))

    def test_nested_quotes_keep_titles_and_media_markers_only_in_json_and_html(self):
        def wrap(title, nested):
            return (f'<msg><appmsg><type>57</type><title>{title}</title>'
                    '<appattach><aeskey>FAKE_APP_KEY</aeskey><cdnattachurl>https://demo.invalid/FAKE_APP_CDN</cdnattachurl></appattach>'
                    f'<refermsg><type>49</type><content>{escape(nested)}</content></refermsg></appmsg></msg>')
        media = 'wxid_demo_only:\n<msg><img aeskey="FAKE_MEDIA_KEY" cdnmidimgurl="https://demo.invalid/FAKE_MEDIA_CDN" /></msg>'
        quoted = wrap("第二层可读标题", media)
        quoted = wrap("第一层可读标题", quoted)
        result = import_source(self.write("nested.jsonl", json.dumps({"id": "nested-demo", "text": "演示正文", "quoted_content": quoted})))
        text = result["messages"][0]["text"]
        self.assertIn("第一层可读标题", text)
        self.assertIn("第二层可读标题", text)
        self.assertIn("[引用图片，实体未读取]", text)
        from qunhuibao.renderer import render_html
        from qunhuibao.validation import source_digest
        report = {"schema_version": 1, "source_digest": source_digest(result), "title": "演示报告", "summary": "仅用于测试",
                  "conversation": result["conversation"], "period": "", "sections": [
                      {"key": "topics", "title": "主题", "items": [
                          {"title": "演示", "body": "引用演示材料", "kind": "fact", "evidence_refs": ["nested-demo"]}
                      ]}
                  ]}
        rendered = render_html(report, result)
        for output in (json.dumps(result), rendered):
            for secret in ("FAKE_APP_KEY", "FAKE_APP_CDN", "FAKE_MEDIA_KEY", "FAKE_MEDIA_CDN", "wxid_demo_only"):
                self.assertNotIn(secret, output)

    def test_unknown_malformed_and_entity_xml_leave_markers_and_warnings(self):
        cases = [
            '<unknown aeskey="FAKE_UNKNOWN_KEY"><url>https://demo.invalid/FAKE_UNKNOWN_CDN</url></unknown>',
            'wxid_demo_only:\n<msg><img aeskey="FAKE_BROKEN_KEY"',
            '<!DOCTYPE msg [<!ENTITY x "FAKE_ENTITY_VALUE">]><msg><appmsg><title>&x;</title></appmsg></msg>',
        ]
        for index, xml in enumerate(cases):
            with self.subTest(index=index):
                result = import_source(self.write("unknown.jsonl", json.dumps({"text": "正常正文", "quoted_content": xml})))
                serialized = json.dumps(result, ensure_ascii=False)
                self.assertNotIn("FAKE_", serialized)
                self.assertIn("引用结构化内容", result["messages"][0]["text"])
                self.assertTrue(any("未完整读取" in warning for warning in result["warnings"]))

    def test_xml_size_depth_and_encoded_reference_have_explicit_boundaries(self):
        xml = '<msg><img aeskey="FAKE_KEY" /></msg>'
        with patch("qunhuibao.importers.MAX_QUOTED_XML_CHARS", 10):
            result = import_source(self.write("size.jsonl", json.dumps({"text": "正文", "quoted_content": xml})))
            self.assertIn("引用结构化内容过大", result["messages"][0]["text"])
        nested = f'<msg><appmsg><title>标题</title><refermsg><content>{escape(xml)}</content></refermsg></appmsg></msg>'
        with patch("qunhuibao.importers.MAX_QUOTE_DEPTH", 1):
            result = import_source(self.write("depth.jsonl", json.dumps({"text": "正文", "quoted_content": nested})))
            self.assertIn("嵌套引用层级过深", result["messages"][0]["text"])
        result = import_source(self.write("encoded.jsonl", json.dumps({"text": "正文", "quoted_content": escape(xml)})))
        self.assertIn("[引用图片，实体未读取]", result["messages"][0]["text"])
        self.assertNotIn("FAKE_KEY", json.dumps(result))

    def test_normal_body_and_plain_quoted_code_are_not_globally_filtered(self):
        body = '教学代码：aeskey = "示例变量"\nprint("<msg><img /></msg>")\n普通地址 https://example.com/demo'
        quote = 'Python 示例：value = "<msg>"；aeskey 只是变量名称。'
        result = import_source(self.write("code.jsonl", json.dumps({"text": body, "quoted_content": quote})))
        self.assertEqual(result["messages"][0]["text"], body + "\n引用内容：" + quote)


if __name__ == "__main__":
    unittest.main()
