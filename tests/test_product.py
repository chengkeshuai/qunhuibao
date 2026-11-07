import copy
import json
import tempfile
import threading
import unittest
from pathlib import Path
from urllib.error import HTTPError

from examples.build_demo import example_report
from qunhuibao.importers import import_source
from qunhuibao.publication import make_publication, render_publication, validate_publication
from qunhuibao.service import Store, serve
from qunhuibao.product_cli import request


class ProductTests(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.store=Store(Path(self.tmp.name)/'site.db')
        self.a=self.store.invite('甲')
        self.b=self.store.invite('乙')
        self.messages=import_source(Path(__file__).resolve().parents[1]/'examples/chat.json')
        self.report=example_report(self.messages)
        self.payload=make_publication(self.report,self.messages,'2026-11-06',['demo-01'])
        self.group=self.store.create_group(self.a['publisher'],self.messages['conversation'])['id']

    def test_minimal_payload_does_not_ship_archive(self):
        raw=json.dumps(self.payload,ensure_ascii=False)
        self.assertNotIn('source_digest',raw)
        self.assertNotIn('sources',raw)
        self.assertEqual(len(self.payload['quotes']),1)
        self.assertNotIn(self.messages['messages'][-1]['text'],raw)

    def test_wrong_quote_rejected(self):
        with self.assertRaises(ValueError): make_publication(self.report,self.messages,'2026-11-06',['unknown'])

    def test_isolation_revoke_and_token_hashing(self):
        with self.assertRaises(PermissionError): self.store.publish(self.b['publisher'],self.group,self.payload)
        with self.store.db() as db:
            self.assertNotEqual(db.execute('SELECT token FROM publishers WHERE id=?',(self.a['publisher'],)).fetchone()[0],self.a['token'])
        self.store.publish(self.a['publisher'],self.group,self.payload)
        self.store.revoke(self.a['publisher'])
        with self.assertRaises(PermissionError): self.store.authenticate(self.a['token'])
        with self.assertRaises(LookupError): self.store.page(self.group)

    def test_publish_idempotence_withdraw_restore(self):
        owner=self.a['publisher']
        self.assertEqual(self.store.publish(owner,self.group,self.payload)['version'],1)
        self.assertEqual(self.store.publish(owner,self.group,self.payload)['status'],'unchanged')
        modified=copy.deepcopy(self.payload);modified['title']='修改后的标题'
        self.assertEqual(self.store.publish(owner,self.group,modified)['version'],2)
        self.assertIn('修改后的标题',self.store.page(self.group))
        self.store.withdraw(owner,self.group,'2026-11-06')
        with self.assertRaises(LookupError): self.store.page(self.group,'2026-11-06')
        self.assertEqual(self.store.restore(owner,self.group,'2026-11-06',1)['version'],3)
        self.assertIn(self.payload['title'],self.store.page(self.group))
        self.assertEqual(len(self.store.versions(owner,self.group,'2026-11-06')),3)

    def test_cross_group_title_blocked_and_rollback(self):
        p=copy.deepcopy(self.payload);p['conversation']='另一个群'
        with self.assertRaises(ValueError): self.store.publish(self.a['publisher'],self.group,p)
        self.assertEqual(self.store.versions(self.a['publisher'],self.group,'2026-11-06'),[])

    def test_server_fixed_template_escape_and_reject_unknown(self):
        p=copy.deepcopy(self.payload);p['summary']='<script>alert(1)</script>'
        page=render_publication(p)
        self.assertNotIn('<script>alert(1)</script>',page)
        self.assertIn('&lt;script&gt;',page)
        p['html']='evil'
        with self.assertRaises(ValueError): validate_publication(p)

    def test_http_auth_publish_history_and_no_private_static_files(self):
        server=serve(self.store,port=0)
        thread=threading.Thread(target=server.serve_forever,daemon=True);thread.start()
        self.addCleanup(server.server_close);self.addCleanup(server.shutdown)
        url='http://127.0.0.1:'+str(server.server_port)
        result=request(url,self.a['token'],f'/api/groups/{self.group}/publish',self.payload)
        self.assertEqual(result['status'],'published')
        with self.assertRaises(HTTPError) as ex: request(url,self.b['token'],f'/api/groups/{self.group}/versions',{'date':'2026-11-06'})
        self.assertEqual(ex.exception.code,403)
        with self.assertRaises(HTTPError) as ex: request(url,self.a['token'],'/site.db')
        self.assertEqual(ex.exception.code,404)
        self.assertEqual(len(request(url,self.a['token'],'/api/notices')),1)

    def test_contacts_masked_but_resource_url_kept(self):
        report=copy.deepcopy(self.report)
        report['summary']='联系13812345678 test@example.com，资源 https://example.com/docs'
        p=make_publication(report,self.messages,'2026-11-06')
        self.assertNotIn('13812345678',p['summary'])
        self.assertNotIn('test@example.com',p['summary'])
        self.assertIn('https://example.com/docs',p['summary'])
