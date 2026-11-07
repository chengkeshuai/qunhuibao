"""Read-only adapter for an existing wechat-cli 0.2.4 installation.

No key extraction, sending, source database writes or automatic installation.
"""
import datetime as dt
import hashlib
import json
import sqlite3
from pathlib import Path


def export_chat(chat, start, end):
    from importlib.metadata import version
    if version('wechat-cli') != '0.2.4': raise ValueError('当前适配器仅验证wechat-cli 0.2.4；请先核验其他版本')
    from wechat_cli.core.context import AppContext
    from wechat_cli.core.contacts import get_contact_names
    from wechat_cli.core.messages import decompress_content, format_msg_type
    tz=dt.timezone(dt.timedelta(hours=8))
    def stamp(value):
        t=dt.datetime.fromisoformat(value)
        return t.replace(tzinfo=tz) if t.tzinfo is None else t.astimezone(tz)
    first,last=stamp(start),stamp(end)
    if last<=first or last-first>dt.timedelta(days=32): raise ValueError('时间窗应大于零且不超过32天')
    app=AppContext()
    names=get_contact_names(app.cache,app.decrypted_dir)
    normalize=lambda s: ''.join(s.split()).casefold()
    matches=[k for k,v in names.items() if k.endswith('@chatroom') and (k==chat or normalize(v)==normalize(chat))]
    if chat.endswith('@chatroom') and chat not in matches: matches.append(chat)
    if len(matches)!=1: raise ValueError('群名不存在或同名不唯一，请提供明确群ID；不会模糊选择其他群')
    uid=matches[0]
    table='Msg_'+hashlib.md5(uid.encode()).hexdigest()
    configured={Path(k.replace('\\','/')).name for k in app.msg_db_keys}
    actual={p.name for p in (Path(app.db_dir)/'message').glob('message_*.db')}
    if actual-configured: raise ValueError('微信新分库尚未配置，取数可能不完整；请先修复现有微信CLI')
    output={}
    for rel in app.msg_db_keys:
        cache=app.cache.get(rel)
        if not cache: raise ValueError('微信消息分库读取失败，本次不生成日报')
        con=sqlite3.connect(Path(cache).resolve().as_uri()+'?mode=ro',uri=True)
        try:
            con.execute('PRAGMA query_only=ON')
            if not con.execute('SELECT 1 FROM sqlite_master WHERE type=? AND name=?',('table',table)).fetchone(): continue
            senders=dict(con.execute('SELECT rowid,user_name FROM Name2Id'))
            rows=con.execute(f'SELECT local_id,server_id,local_type,real_sender_id,create_time,message_content,WCDB_CT_message_content FROM [{table}] WHERE create_time>=? AND create_time<? ORDER BY create_time,local_id',(int(first.timestamp()),int(last.timestamp())))
            for local,server,kind,sender,ts,content,ct in rows:
                raw=decompress_content(content,ct)
                if raw is None: raise ValueError('消息解码失败，本次不生成不完整日报')
                sender_id=senders.get(sender,'')
                if ':\n' in raw and raw.split(':\n',1)[0].startswith(('wxid_','gh_')):
                    sender_id,raw=raw.split(':\n',1)
                mid=uid+':'+(str(server) if server else hashlib.sha256(f'{ts}|{sender_id}|{kind}|{raw}'.encode()).hexdigest())
                base=int(kind)&0xffffffff
                attachments=[]
                if base not in (1,10000,10002,49):
                    attachments=[{'name':format_msg_type(kind),'source':'','kind':{3:'image',34:'audio',43:'video'}.get(base,'file'),'status':'indexed_not_rendered'}]
                message={'id':mid,'timestamp':dt.datetime.fromtimestamp(ts,tz).isoformat(),'sender':names.get(sender_id,sender_id or '发言人未识别'),'text':raw or '[空消息]','attachments':attachments}
                if mid in output and output[mid]!=message: raise ValueError('同一消息ID存在冲突，已停止')
                output[mid]=message
                if len(output)>100000: raise ValueError('消息过多，请缩小日期范围')
        finally: con.close()
    if not output: return None
    return {'schema_version':1,'conversation':names.get(uid,chat),'coverage':f'{first.isoformat()} 至 {last.isoformat()}（不含结束时间，仅本机缓存）','messages':sorted(output.values(),key=lambda m:(m['timestamp'],m['id'])),'warnings':['仅读取本机缓存，附件未识别；不代表群聊完整历史。']}


def main():
    import argparse
    p=argparse.ArgumentParser()
    p.add_argument('--chat',required=True);p.add_argument('--start',required=True);p.add_argument('--end',required=True);p.add_argument('--out',required=True)
    args=p.parse_args()
    try:
        data=export_chat(args.chat,args.start,args.end)
        with Path(args.out).open('x',encoding='utf-8') as f: json.dump(data,f,ensure_ascii=False)
    except Exception:
        # Third party exceptions may contain local configuration paths. Never emit keys.
        raise SystemExit('微信只读适配未完成：请检查版本、授权、群ID、时间范围和分库完整性。')


if __name__=='__main__': main()
