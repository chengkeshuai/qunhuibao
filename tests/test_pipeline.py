import copy
import json
import tempfile
import unittest
from pathlib import Path

from examples.build_demo import example_report
from qunhuibao.cli import prepare, render, read_json, json_text, write_new_directory, main
from qunhuibao.importers import import_source
from qunhuibao.validation import validate_messages, validate_report, source_digest

ROOT = Path(__file__).resolve().parents[1]


class PipelineTests(unittest.TestCase):
    def setUp(self):
        self.messages = validate_messages(import_source(ROOT / "examples" / "chat.json"))
        self.report = example_report(self.messages)

    def test_digest_ignores_json_formatting_but_not_evidence_changes(self):
        roundtrip = json.loads(json.dumps(self.messages, ensure_ascii=True, sort_keys=True))
        self.assertEqual(source_digest(roundtrip), source_digest(self.messages))
        roundtrip["messages"][0]["text"] += "变更"
        with self.assertRaisesRegex(ValueError, "source_digest"):
            validate_report(self.report, roundtrip)

    def test_missing_reference_rejected(self):
        self.report["sections"][0]["items"][0]["evidence_refs"] = ["not-found"]
        with self.assertRaisesRegex(ValueError, "不存在"):
            validate_report(self.report, self.messages)

    def test_facts_need_evidence_but_suggestions_do_not(self):
        validate_report(self.report, self.messages)
        self.report["sections"][0]["items"][0]["evidence_refs"] = []
        with self.assertRaisesRegex(ValueError, "必须引用"):
            validate_report(self.report, self.messages)

    def test_unknown_html_field_rejected(self):
        self.report["html"] = "<script>alert(1)</script>"
        with self.assertRaisesRegex(ValueError, "未知"):
            validate_report(self.report, self.messages)

    def test_optional_keywords_keep_legacy_reports_valid_and_bind_to_body_text(self):
        validate_report(self.report, self.messages)
        self.report['keywords'] = []
        validate_report(self.report, self.messages)
        self.report['keywords'] = ['固定模板', '公开分享']
        validate_report(self.report, self.messages)
        self.report['keywords'] = ['没有出现的话题']
        with self.assertRaisesRegex(ValueError, '须命中消息自身正文'):
            validate_report(self.report, self.messages)

    def test_empty_evidence_rejected(self):
        self.messages["messages"][0]["text"] = ""
        with self.assertRaisesRegex(ValueError, "不能同时为空"):
            validate_messages(self.messages)

    def test_duplicate_message_ids_rejected(self):
        self.messages["messages"].append(copy.deepcopy(self.messages["messages"][0]))
        with self.assertRaisesRegex(ValueError, "重复消息"):
            validate_messages(self.messages)

    def test_end_to_end_and_output_protection(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            prepare(ROOT / "examples" / "chat.json", root / "prepared")
            evidence = read_json(root / "prepared" / "messages.json")
            report_path = root / "prepared" / "report.json"
            report_path.write_text(json_text(example_report(evidence)), encoding="utf-8")
            render(root / "prepared" / "messages.json", report_path, root / "report")
            html = (root / "report" / "report.html").read_text(encoding="utf-8")
            self.assertIn("合成演示", html)
            self.assertIn("demo-04", (root / "report" / "messages.json").read_text(encoding="utf-8"))
            self.assertEqual(read_json(root / "report" / "manifest.json")["publication"], "local_only")
            with self.assertRaisesRegex(ValueError, "已存在"):
                render(root / "prepared" / "messages.json", report_path, root / "report")
            self.assertEqual(html, (root / "report" / "report.html").read_text(encoding="utf-8"))

    def test_empty_template_cannot_be_published_as_finished(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            prepare(ROOT / "examples" / "chat.json", root / "prepared")
            with self.assertRaises(ValueError):
                render(root / "prepared" / "messages.json", root / "prepared" / "report.draft.json", root / "report")
            self.assertFalse((root / "report").exists())

    def test_even_empty_output_directory_is_protected(self):
        with tempfile.TemporaryDirectory() as tmp:
            with self.assertRaisesRegex(ValueError, "已存在"):
                write_new_directory(Path(tmp), {"keep.txt": "x"})

    def test_duplicate_json_fields_rejected(self):
        with tempfile.TemporaryDirectory() as tmp:
            file = Path(tmp) / "report.json"
            file.write_text('{"title":"first","title":"second"}', encoding="utf-8")
            with self.assertRaisesRegex(ValueError, "重复字段"):
                read_json(file)


if __name__ == "__main__":
    unittest.main()
