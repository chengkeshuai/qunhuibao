import hashlib
import os
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch,MagicMock
from qunhuibao.media import enrich
from qunhuibao.validation import source_digest
from qunhuibao.mail import deliver
from qunhuibao.service import Store

class MediaMailTests(unittest.TestCase):
    def test_media_hash_binding_preserves_original_and_rejects_substitution(self):
        with tempfile.TemporaryDirectory() as tmp:
            path=Path(tmp)/'image.png';path.write_bytes(b'fixture')
            m={'schema_version':1,'conversation':'演示','coverage':'示例','warnings':[],'messages':[{'id':'1','sender':'甲','timestamp':'2026-11-06T09:00:00+08:00','text':'图片','attachments':[{'name':'image.png','source':str(path),'kind':'image','status':'indexed_not_rendered'}]}]}
            a={'source_digest':source_digest(m),'items':[{'message_id':'1','attachment_index':0,'file':str(path),'sha256':hashlib.sha256(b'fixture').hexdigest(),'method':'ocr','text':'识别到的文字'}]}
            result=enrich(m,a)
            self.assertIn('识别到的文字',result['messages'][0]['text'])
            self.assertEqual(m['messages'][0]['text'],'图片')
            path.write_bytes(b'changed')
            with self.assertRaises(ValueError):enrich(m,a)

    def test_mail_not_marked_delivered_until_smtp_success(self):
        with tempfile.TemporaryDirectory() as tmp:
            store=Store(Path(tmp)/'db.sqlite');owner=store.invite('甲')['publisher']
            with store.db() as db:db.execute('INSERT INTO notices(owner,text,created) VALUES(?,?,?)',(owner,'发布成功','示例时间'))
            env={'QHB_SMTP_HOST':'example.invalid','QHB_SMTP_USER':'test','QHB_SMTP_PASSWORD':'fixture','QHB_SMTP_FROM':'test@example.invalid'}
            with patch.dict(os.environ,env),patch('qunhuibao.mail.smtplib.SMTP_SSL') as smtp:
                smtp.return_value.__enter__.return_value.send_message.side_effect=OSError('offline')
                with self.assertRaises(OSError):deliver(store,owner,'reader@example.invalid')
                with store.db() as db:self.assertEqual(db.execute('SELECT COUNT(*) FROM delivered_mail').fetchone()[0],0)
                smtp.return_value.__enter__.return_value.send_message.side_effect=None
                self.assertEqual(deliver(store,owner,'reader@example.invalid')['sent'],1)
                self.assertEqual(deliver(store,owner,'reader@example.invalid')['sent'],0)
