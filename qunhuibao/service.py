"""Invitation-only publishing service. SQLite transactions isolate each publisher."""
import datetime as dt
import hashlib
import json
import secrets
import sqlite3
from contextlib import contextmanager
from html import escape
from pathlib import Path

from .publication import validate_publication, render_publication, shell


class Store:
    def __init__(self, path):
        self.path=Path(path)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        with self.db() as db:
            db.executescript('''
            CREATE TABLE IF NOT EXISTS publishers(id TEXT PRIMARY KEY, name TEXT NOT NULL, token TEXT UNIQUE NOT NULL, active INTEGER NOT NULL DEFAULT 1);
            CREATE TABLE IF NOT EXISTS groups(id TEXT PRIMARY KEY, owner TEXT NOT NULL REFERENCES publishers(id), name TEXT NOT NULL, config TEXT NOT NULL);
            CREATE TABLE IF NOT EXISTS editions(group_id TEXT NOT NULL REFERENCES groups(id), day TEXT NOT NULL, current INTEGER NOT NULL, visible INTEGER NOT NULL, PRIMARY KEY(group_id,day));
            CREATE TABLE IF NOT EXISTS versions(group_id TEXT NOT NULL, day TEXT NOT NULL, version INTEGER NOT NULL, payload TEXT NOT NULL, fingerprint TEXT NOT NULL, created TEXT NOT NULL, PRIMARY KEY(group_id,day,version));
            CREATE TABLE IF NOT EXISTS notices(id INTEGER PRIMARY KEY, owner TEXT NOT NULL, text TEXT NOT NULL, created TEXT NOT NULL);
            ''')

    @contextmanager
    def db(self):
        db=sqlite3.connect(self.path, timeout=15)
        db.row_factory=sqlite3.Row
        db.execute('PRAGMA foreign_keys=ON')
        try:
            with db: yield db
        finally: db.close()

    def invite(self,name):
        token=secrets.token_urlsafe(32)
        uid=secrets.token_hex(12)
        with self.db() as db:
            db.execute('INSERT INTO publishers(id,name,token) VALUES(?,?,?)',(uid,name,hashlib.sha256(token.encode()).hexdigest()))
        return {'publisher':uid,'token':token,'note':'令牌只显示一次；保存在本机凭据文件，不放进URL或报告。'}

    def authenticate(self,token):
        with self.db() as db:
            row=db.execute('SELECT id FROM publishers WHERE token=? AND active=1',(hashlib.sha256(token.encode()).hexdigest(),)).fetchone()
        if not row: raise PermissionError('发布凭据无效或资格已撤销')
        return row['id']

    def revoke(self,uid):
        with self.db() as db:
            if not db.execute('UPDATE publishers SET active=0 WHERE id=?',(uid,)).rowcount: raise ValueError('发布者不存在')
            db.execute('UPDATE editions SET visible=0 WHERE group_id IN (SELECT id FROM groups WHERE owner=?)',(uid,))
        return {'status':'revoked','publisher':uid}

    @staticmethod
    def owned(db,owner,gid):
        row=db.execute('SELECT * FROM groups WHERE id=? AND owner=?',(gid,owner)).fetchone()
        if not row: raise PermissionError('群不存在或不属于当前发布者')
        return row

    def groups(self,owner):
        with self.db() as db:
            return [dict(r) for r in db.execute('SELECT id,name,config FROM groups WHERE owner=? ORDER BY name',(owner,))]

    def create_group(self,owner,name,config=None):
        if not isinstance(name,str) or not name.strip() or len(name)>200: raise ValueError('群名不正确')
        config=config or {}
        if not isinstance(config,dict) or set(config)-{'focus','mode','time','timezone','empty_policy','section_order'}: raise ValueError('群策略字段不正确')
        gid=secrets.token_hex(12)
        with self.db() as db: db.execute('INSERT INTO groups VALUES(?,?,?,?)',(gid,owner,name,json.dumps(config,ensure_ascii=False)))
        return {'id':gid,'name':name,'url':f'/g/{gid}'}

    def publish(self,owner,gid,payload):
        validate_publication(payload)
        raw=json.dumps(payload,ensure_ascii=False,sort_keys=True,separators=(',',':'))
        fp=hashlib.sha256(raw.encode()).hexdigest()
        day=payload['date']
        with self.db() as db:
            db.execute('BEGIN IMMEDIATE')
            group=self.owned(db,owner,gid)
            if payload['conversation']!=group['name']: raise ValueError('日报群名与发布目标不一致，已阻止串群')
            current=db.execute('SELECT e.current,e.visible,v.fingerprint FROM editions e JOIN versions v ON v.group_id=e.group_id AND v.day=e.day AND v.version=e.current WHERE e.group_id=? AND e.day=?',(gid,day)).fetchone()
            if current and current['fingerprint']==fp and current['visible']:
                return {'status':'unchanged','version':current['current'],'url':f'/g/{gid}/{day}'}
            version=db.execute('SELECT COALESCE(MAX(version),0)+1 FROM versions WHERE group_id=? AND day=?',(gid,day)).fetchone()[0]
            now=dt.datetime.now(dt.timezone.utc).isoformat()
            db.execute('INSERT INTO versions VALUES(?,?,?,?,?,?)',(gid,day,version,raw,fp,now))
            db.execute('INSERT INTO editions VALUES(?,?,?,1) ON CONFLICT(group_id,day) DO UPDATE SET current=excluded.current,visible=1',(gid,day,version))
            db.execute('INSERT INTO notices(owner,text,created) VALUES(?,?,?)',(owner,f'{group["name"]} {day} 日报已发布，版本{version}',now))
        return {'status':'published','version':version,'url':f'/g/{gid}/{day}'}

    def withdraw(self,owner,gid,day):
        with self.db() as db:
            self.owned(db,owner,gid)
            if not db.execute('UPDATE editions SET visible=0 WHERE group_id=? AND day=?',(gid,day)).rowcount: raise ValueError('日报不存在')
        return {'status':'withdrawn'}

    def versions(self,owner,gid,day):
        with self.db() as db:
            self.owned(db,owner,gid)
            return [dict(r) for r in db.execute('SELECT version,created FROM versions WHERE group_id=? AND day=? ORDER BY version DESC',(gid,day))]

    def restore(self,owner,gid,day,version):
        with self.db() as db:
            self.owned(db,owner,gid)
            row=db.execute('SELECT payload FROM versions WHERE group_id=? AND day=? AND version=?',(gid,day,version)).fetchone()
            if not row: raise ValueError('版本不存在')
        return self.publish(owner,gid,json.loads(row['payload']))

    def notices(self,owner):
        with self.db() as db: return [dict(r) for r in db.execute('SELECT id,text,created FROM notices WHERE owner=? ORDER BY id DESC LIMIT 100',(owner,))]

    def page(self,gid,day=None):
        with self.db() as db:
            group=db.execute('SELECT g.* FROM groups g JOIN publishers p ON p.id=g.owner WHERE g.id=? AND p.active=1',(gid,)).fetchone()
            if not group: raise LookupError('群主页不存在')
            rows=db.execute('SELECT e.day,v.payload FROM editions e JOIN versions v ON v.group_id=e.group_id AND v.day=e.day AND v.version=e.current WHERE e.group_id=? AND e.visible=1 ORDER BY e.day DESC',(gid,)).fetchall()
        if day:
            row=next((r for r in rows if r['day']==day),None)
            if not row: raise LookupError('日报不存在或已撤下')
            return render_publication(json.loads(row['payload']),f'/g/{gid}')
        if not rows: return shell(group['name'],f'<section class="hero"><h1>{escape(group["name"])}</h1><p>还没有已发布日报。</p></section>')
        history='<section class="report-section"><div class="digest-section-heading"><h2>按日期查看历史日报</h2></div><div class="resources-grid">'+''.join(f'<a class="edit-card" href="/g/{gid}/{r["day"]}">{r["day"]} · {escape(json.loads(r["payload"])["title"])}</a>' for r in rows)+'</div></section>'
        return render_publication(json.loads(rows[0]['payload'])).replace('<footer class="report-footer">',history+'<footer class="report-footer">')


def serve(store,host='127.0.0.1',port=8765):
    from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
    from urllib.parse import urlsplit
    class Handler(BaseHTTPRequestHandler):
        def log_message(self,*args): pass  # Never log tokens or report contents.
        def respond(self,status,value,html=False):
            raw=(value if html else json.dumps(value,ensure_ascii=False)).encode('utf-8')
            self.send_response(status)
            self.send_header('Content-Type','text/html; charset=utf-8' if html else 'application/json; charset=utf-8')
            self.send_header('Content-Length',str(len(raw)))
            self.send_header('Cache-Control','no-store')
            self.send_header('X-Content-Type-Options','nosniff')
            self.send_header('Referrer-Policy','no-referrer')
            self.send_header('Content-Security-Policy',"default-src 'none'; img-src data: blob:; style-src 'unsafe-inline'; script-src 'unsafe-inline'; frame-src 'self' about:; base-uri 'none'; frame-ancestors 'none'; form-action 'none'")
            self.end_headers(); self.wfile.write(raw)
        def dispatch(self):
            path=urlsplit(self.path).path
            parts=path.strip('/').split('/')
            if self.command=='GET' and path=='/health': return self.respond(200,{'status':'ok'})
            if self.command=='GET' and parts[0]=='g' and len(parts) in (2,3): return self.respond(200,store.page(parts[1],parts[2] if len(parts)==3 else None),True)
            if not path.startswith('/api/'): raise LookupError('页面不存在')
            auth=self.headers.get('Authorization','')
            if not auth.startswith('Bearer '): raise PermissionError('需要发布凭据')
            owner=store.authenticate(auth[7:])
            data={}
            if self.command=='POST':
                length=int(self.headers.get('Content-Length','0'))
                if not 0<length<=2_000_000: raise ValueError('请求大小不正确')
                self.connection.settimeout(15)
                data=json.loads(self.rfile.read(length))
                if not isinstance(data,dict): raise ValueError('请求须为JSON对象')
            if parts==['api','groups']:
                result=store.groups(owner) if self.command=='GET' else store.create_group(owner,data['name'],data.get('config'))
            elif parts==['api','notices'] and self.command=='GET': result=store.notices(owner)
            elif len(parts)==4 and parts[:2]==['api','groups'] and self.command=='POST':
                gid,action=parts[2:]
                if action=='publish': result=store.publish(owner,gid,data)
                elif action=='withdraw': result=store.withdraw(owner,gid,data['date'])
                elif action=='versions': result=store.versions(owner,gid,data['date'])
                elif action=='restore': result=store.restore(owner,gid,data['date'],data['version'])
                else: raise LookupError('接口不存在')
            else: raise LookupError('接口不存在')
            self.respond(200,result)
        def handle_request(self):
            try: self.dispatch()
            except PermissionError as ex: self.respond(403,{'error':str(ex)})
            except LookupError: self.respond(404,{'error':'资源不存在'})
            except (ValueError,TypeError,KeyError,OverflowError) as ex: self.respond(400,{'error':'请求格式或字段不正确：'+str(ex)[:150]})
            except Exception: self.respond(500,{'error':'服务内部错误；请检查服务端状态'})
        do_GET=handle_request
        do_POST=handle_request
    server=ThreadingHTTPServer((host,port),Handler)
    server.daemon_threads=True
    return server
