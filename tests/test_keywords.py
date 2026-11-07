"""Grounded topic counts; no network, model, or source-file mutation."""
from copy import deepcopy
import unittest

from qunhuibao.keywords import build_topic_keywords
from qunhuibao.validation import source_digest, validate_report


def fixture(texts, *, summary='剪辑与交付', keywords=None):
    messages = {'schema_version': 1, 'conversation': '合成词云测试', 'coverage': '2026-11-06', 'warnings': [],
                'messages': [{'id': f'm{i}', 'sender': f'成员{i}', 'timestamp': '', 'text': text, 'attachments': []}
                             for i, text in enumerate(texts, 1)]}
    report = {'schema_version': 1, 'conversation': messages['conversation'], 'title': '合成演示报告',
              'period': '', 'summary': summary, 'source_digest': source_digest(messages),
              'sections': [{'key': 'topics', 'title': '主题', 'items': [
                  {'title': '本次讨论', 'body': summary, 'kind': 'fact', 'evidence_refs': ['m1']}]}]}
    if keywords is not None:
        report['keywords'] = keywords
    return report, messages


class KeywordTests(unittest.TestCase):
    def test_fallback_uses_report_candidates_and_unique_messages(self):
        report, messages = fixture(['剪辑、剪辑，再确认交付。', '本周交付素材。'], summary='剪辑、交付和知识库')
        rows = {item['term']: item for item in build_topic_keywords(report, messages)}
        self.assertEqual(rows['剪辑']['message_count'], 1)
        self.assertEqual(rows['交付']['message_count'], 2)
        self.assertEqual(rows['交付']['message_ids'], ['m1', 'm2'])
        self.assertEqual(len(rows['剪辑']['matches']), 2)
        self.assertNotIn('知识库', rows)  # Mentioned only by the report.
        self.assertNotIn('素材', rows)  # Not selected by this report.

    def test_reply_quotes_do_not_inflate_counts_and_sources_are_unchanged(self):
        report, messages = fixture(['视频剪辑需要验收。',
            '收到。\n引用消息 ID：m1\n引用发言人：成员1\n引用内容：视频剪辑需要验收。',
            '验收条件再核对。\n引用消息 ID：m1\n引用发言人：成员1\n引用内容：视频剪辑需要验收。'],
            keywords=['视频剪辑', '验收'])
        before, digest = deepcopy(messages), source_digest(messages)
        rows = {item['term']: item for item in build_topic_keywords(report, messages)}
        self.assertEqual(rows['视频剪辑']['message_ids'], ['m1'])
        self.assertEqual(rows['验收']['message_ids'], ['m1', 'm3'])
        self.assertEqual(messages, before)
        self.assertEqual(source_digest(messages), digest)

    def test_approved_aliases_merge_without_treating_ordinary_english_as_a_product(self):
        report, messages = fixture(['🎬 我用 Chat put 做剪辑，ChatCut 也这样写。', 'ChatCut 可以处理字幕。',
            'English exercise: please chat put this in the box.'], keywords=['Chat put'])
        rows = build_topic_keywords(report, messages)
        self.assertEqual(rows[0]['term'], 'ChatCut')
        self.assertEqual(rows[0]['message_count'], 2)
        self.assertEqual(rows[0]['message_ids'], ['m1', 'm2'])
        slices = [next(msg for msg in messages['messages'] if msg['id'] == match['message_id'])['text'][match['start']:match['end']]
                  for match in rows[0]['matches']]
        self.assertEqual(slices, ['Chat put', 'ChatCut', 'ChatCut'])
        self.assertIs(validate_report(report, messages), report)

    def test_explicit_chinese_topics_are_not_tied_to_the_fallback_vocabulary(self):
        report, messages = fixture(['预售退款的办理周期是几天？'], summary='售后流程', keywords=['预售退款', '办理周期'])
        self.assertEqual({row['term'] for row in build_topic_keywords(report, messages)}, {'预售退款', '办理周期'})
        self.assertIs(validate_report(report, messages), report)
        report['keywords'] = []
        self.assertEqual(build_topic_keywords(report, messages), [])

    def test_explicit_technical_topics_are_allowed_but_fillers_and_nicknames_are_not(self):
        report, messages = fixture(['JSON 生成草稿，再导出 HTML。谢谢，收到，成员1。'], keywords=['JSON', 'HTML'])
        self.assertEqual({row['term'] for row in build_topic_keywords(report, messages)}, {'JSON', 'HTML'})
        self.assertIs(validate_report(report, messages), report)
        for word in ('谢谢', '收到', '成员1'):
            report['keywords'] = [word]
            self.assertEqual(build_topic_keywords(report, messages), [])
            with self.assertRaisesRegex(ValueError, '昵称或口水词'):
                validate_report(report, messages)

    def test_width_case_spacing_and_english_word_boundaries(self):
        report, messages = fixture(['ＡＩ is useful. AI 配音。', 'This item was paid.'], keywords=['AI'])
        result = build_topic_keywords(report, messages)
        self.assertEqual(result[0]['message_ids'], ['m1'])
        self.assertEqual(len(result[0]['matches']), 2)
        self.assertEqual(build_topic_keywords(report, messages, limit=0), [])

    def test_keyword_contract_rejects_duplicates_bad_types_and_ungrounded_terms(self):
        report, messages = fixture(['ChatCut 剪辑，Chat put 做视频剪辑。'], keywords=['ChatCut'])
        for words in (['ChatCut', 'ＣＨＡＴ　ＣＵＴ'], ['ChatCut', 'Chat put']):
            report['keywords'] = words
            with self.assertRaisesRegex(ValueError, '重复词条'):
                validate_report(report, messages)
        for words in ([1], ['a'], ['x' * 41], ['w' + str(i) for i in range(25)]):
            report['keywords'] = words
            with self.assertRaises(ValueError):
                validate_report(report, messages)
        report['keywords'] = ['不存在的议题']
        with self.assertRaisesRegex(ValueError, '须命中消息自身正文'):
            validate_report(report, messages)
        messages['messages'][0]['text'] = '收到。\n引用发言人：外部成员\n引用内容：外部议题'
        report['source_digest'] = source_digest(messages)
        report['keywords'] = ['外部议题']
        with self.assertRaisesRegex(ValueError, '回复引用和附件不计'):
            validate_report(report, messages)


if __name__ == '__main__':
    unittest.main()
