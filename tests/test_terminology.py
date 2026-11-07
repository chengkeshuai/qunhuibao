import copy
import json
import tempfile
import unittest
from pathlib import Path

from qunhuibao.cli import prepare, read_json
from qunhuibao.importers import import_source
from qunhuibao.terminology import review_terms
from qunhuibao.validation import source_digest


def evidence(*texts, timestamps=None, conversation="合成测试群"):
    return {
        "schema_version": 1, "conversation": conversation, "coverage": "合成材料",
        "warnings": [],
        "messages": [
            {"id": f"m{index}", "sender": "测试成员", "timestamp": timestamps[index] if timestamps else "",
             "text": text, "attachments": []}
            for index, text in enumerate(texts)
        ],
    }


class TerminologyTests(unittest.TestCase):
    def test_confirmed_video_alias_has_exact_original_offsets(self):
        text = "ﬃ😀我用ＣＨＡＴ　　ｐｕｔ做视频剪辑。"
        result = review_terms(evidence(text))
        self.assertEqual(len(result), 1)
        item = result[0]
        self.assertEqual(set(item), {"message_id", "original", "canonical", "rule_id", "start", "end", "reason"})
        self.assertEqual(item["original"], "ＣＨＡＴ　　ｐｕｔ")
        self.assertEqual(text[item["start"]:item["end"]], item["original"])
        self.assertEqual(item["start"], text.index("Ｃ"))
        self.assertEqual(item["canonical"], "ChatCut")
        self.assertNotIn(text, item["reason"])

    def test_case_width_and_whitespace_variants(self):
        for alias in ("chat put", "CHAT PUT", "Chat   put", "Ｃｈａｔ　Ｐｕｔ", "Chat\t\nput", "Chatput"):
            with self.subTest(alias=alias):
                result = review_terms(evidence(f"视频剪辑可用{alias}。"))
                self.assertEqual(len(result), 1)
                self.assertEqual(result[0]["original"], alias)

    def test_nearby_editing_context_supports_short_reply(self):
        result = review_terms(evidence("哪个视频剪辑工具好用？", "Chat put可以。", "可以试试"))
        self.assertEqual([item["message_id"] for item in result], ["m1"])
        self.assertIn("附近消息", result[0]["reason"])

    def test_english_editing_context_preserves_word_boundaries(self):
        result = review_terms(evidence("For video editing I use Chat put on clips."))
        self.assertEqual(len(result), 1)

    def test_non_editing_context_and_group_name_are_not_enough(self):
        self.assertEqual(review_terms(evidence("今天讨论Chat put。", conversation="视频剪辑群")), [])
        self.assertEqual(review_terms(evidence("Chat put是聊天服务。")), [])

    def test_explicit_other_context_overrides_neighbor(self):
        self.assertEqual(review_terms(evidence("我们刚才讲视频剪辑。", "这条英语练习讲普通英语Chat put。")), [])
        self.assertEqual(review_terms(evidence("视频剪辑刚才说过，这里Chat put是聊天接口。")), [])
        self.assertEqual(review_terms(evidence("这里的Chat put与剪辑无关，是另一个产品。")), [])

    def test_ordinary_english_phrase_never_borrows_editing_context(self):
        for sentence in ("Please chat put this in the folder.", "Can you chat put it here?", "I saw chat put this into the draft."):
            with self.subTest(sentence=sentence):
                self.assertEqual(review_terms(evidence("我们讨论视频剪辑。", sentence, "这个剪辑功能不错。")), [])
                self.assertEqual(review_terms(evidence(sentence + " This is about video editing.")), [])
        self.assertEqual(len(review_terms(evidence("Please use Chat put for video editing."))), 1)

    def test_no_generic_put_or_unconfirmed_alias_expansion(self):
        self.assertEqual(review_terms(evidence("视频剪辑用FF和ffmpeg，HTTP PUT只是请求；先put文件。")), [])
        self.assertEqual(review_terms(evidence("视频剪辑使用ChatCut和Chat Cut。")), [])

    def test_alias_cannot_match_inside_other_ascii_word(self):
        self.assertEqual(review_terms(evidence("视频剪辑例子：myChat put以及Chat putty都不是别名。")), [])

    def test_multiple_occurrences_keep_message_and_text_order(self):
        result = review_terms(evidence("视频剪辑用Chat put，另一次写CHAT PUT。", "混剪也用Chat put。"))
        self.assertEqual([item["message_id"] for item in result], ["m0", "m0", "m1"])
        self.assertLess(result[0]["start"], result[1]["start"])

    def test_remote_context_cannot_authorize_mapping(self):
        self.assertEqual(review_terms(evidence("视频剪辑", "午饭", "天气", "Chat put")), [])
        self.assertEqual(review_terms(evidence("视频剪辑", "Chat put", timestamps=["2026-11-06T09:00:00+08:00", "2026-11-06T12:00:00+08:00"])), [])
        self.assertEqual(review_terms(evidence("视频剪辑。" + "无关内容" * 100 + "Chat put。")), [])

    def test_review_does_not_mutate_any_evidence_or_digest(self):
        messages = evidence("视频剪辑推荐Chat put。")
        before = copy.deepcopy(messages)
        digest = source_digest(messages)
        first, second = review_terms(messages), review_terms(messages)
        self.assertEqual(first, second)
        self.assertEqual(messages, before)
        self.assertEqual(source_digest(messages), digest)
        self.assertIn("Chat put", messages["messages"][0]["text"])

    def test_prepare_adds_review_and_required_guidance_without_rewriting(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            source = root / "chat.json"
            source.write_text(json.dumps(evidence("视频剪辑推荐Chat put。"), ensure_ascii=False), encoding="utf-8")
            before = source.read_bytes()
            expected = import_source(source)
            output = root / "prepared"
            result = prepare(source, output)
            saved = read_json(output / "messages.json")
            review = read_json(output / "术语核对.json")
            draft = read_json(output / "report.draft.json")
            prompt = (output / "整理提示词.md").read_text(encoding="utf-8")
            self.assertEqual(source.read_bytes(), before)
            self.assertEqual(saved, expected)
            self.assertEqual(review["source_digest"], source_digest(saved))
            self.assertEqual(review["source_digest"], draft["source_digest"])
            self.assertEqual(review["matches"], review_terms(saved))
            self.assertEqual(result["term_matches"], 1)
            self.assertIn("已识别 1 处", prompt)
            self.assertIn("易错题库.md", prompt)
            self.assertIn("术语候选.md", prompt)
            self.assertIn("不改messages.json或source_digest", prompt)
            self.assertEqual(review["rules_source"], "qunhuibao/assets/terminology.json")

    def test_prepare_reports_zero_matches_without_declaring_no_typos(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            source = root / "chat.json"
            source.write_text(json.dumps(evidence("普通聊天内容。"), ensure_ascii=False), encoding="utf-8")
            result = prepare(source, root / "prepared")
            self.assertEqual(result["term_matches"], 0)
            self.assertEqual(read_json(root / "prepared" / "术语核对.json")["matches"], [])
            self.assertIn("不等于材料没有错词", (root / "prepared" / "整理提示词.md").read_text(encoding="utf-8"))


if __name__ == "__main__":
    unittest.main()
