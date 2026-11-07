import copy
import json
import re
import tempfile
import unittest
from pathlib import Path
from examples.build_demo import example_report
from qunhuibao.cli import prepare, read_json
from qunhuibao.importers import import_source
from qunhuibao.editor import render_editor
from qunhuibao.renderer import render_html, render_markdown
from qunhuibao.validation import validate_report


class EditorTests(unittest.TestCase):
    def setUp(self):
        self.messages = import_source(Path(__file__).resolve().parents[1] / 'examples/chat.json')
        self.report = example_report(self.messages)

    def test_learning_fields_validate_and_render_in_both_formats(self):
        item = self.report['sections'][0]['items'][0]
        item.update(question='问题场景', answer='有限回答', conditions='先有授权', outcome='尚未实测', steps=['第一步', '第二步'])
        validate_report(self.report, self.messages)
        for rendered in (render_html(self.report, self.messages), render_markdown(self.report, self.messages)):
            for text in ('有限回答', '先有授权', '尚未实测', '第二步'):
                self.assertIn(text, rendered)

    def test_ungrounded_answer_rejected_even_when_suggestion(self):
        item = self.report['sections'][0]['items'][0]
        item.update(kind='suggestion', evidence_refs=[], answer='虚构解决方案')
        with self.assertRaisesRegex(ValueError, '回答和方法步骤'):
            validate_report(self.report, self.messages)

    def test_reply_display_has_no_technical_source_id(self):
        from qunhuibao.validation import source_digest
        self.messages['messages'][0]['text'] = '同意\n引用消息 ID：private-server-id\n引用发言人：小甲\n引用内容：可以先试用'
        self.report['source_digest'] = source_digest(self.messages)
        # Also verifies raw close-script input cannot terminate the inert JSON element.
        self.report['title'] = '</script><script>evil()</script>'
        html = render_editor(self.report, self.messages)
        self.assertNotIn('</script><script>evil()', html)
        self.assertIn('review-data', html)
        data=json.loads(re.search(r'<script id="review-data" type="application/json">(.*?)</script>',html,re.S)[1])
        display=data['display'][self.messages['messages'][0]['id']]
        self.assertIn('回复 小甲',display)
        self.assertIn('可以先试用',display)
        self.assertNotIn('private-server-id',display)

    def test_focus_and_brief_strategy_written_to_prepare_prompt(self):
        with tempfile.TemporaryDirectory() as root:
            target=Path(root)/'prepared'
            prepare(Path(__file__).resolve().parents[1]/'examples/chat.json', target, focus='接单条件和未答疑', mode='brief')
            prompt=(target/'整理提示词.md').read_text(encoding='utf-8')
            self.assertIn('接单条件和未答疑', prompt)
            self.assertIn('日报模式：brief', prompt)
            self.assertIn('感谢或有人回复不能当解决', prompt)
