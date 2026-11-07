"""Agent-facing product commands, using explicit paths and structured output."""
import json
import os
import subprocess
import sys
from pathlib import Path
from urllib.request import Request, build_opener, HTTPRedirectHandler
from urllib.parse import urlsplit

from .publication import make_publication, render_publication
from .service import Store, serve


def configure(parser):
    c=parser.add_parser('enrich',help='绑定Agent已完成的OCR/转写；不自动调用收费识别服务')
    c.add_argument('--messages',type=Path,required=True);c.add_argument('--annotations',type=Path,required=True);c.add_argument('--out',type=Path,required=True)
    c=parser.add_parser('mail-drain',help='按明确收件配置发送待处理邮件通知')
    c.add_argument('--db',type=Path,required=True);c.add_argument('--publisher',required=True);c.add_argument('--recipient',required=True)
    c=parser.add_parser('schedule-tick',help='执行到期任务；需预先配置本机Agent命令，关机不取数')
    c.add_argument('--config',type=Path,required=True)
    c=parser.add_parser('site',help='本地发布服务与邀请管理（非公开部署）')
    c.add_argument('action',choices=['serve','invite','revoke'])
    c.add_argument('--db',type=Path,required=True)
    c.add_argument('--name');c.add_argument('--publisher')
    c.add_argument('--host',default='127.0.0.1');c.add_argument('--port',type=int,default=8765)
    c=parser.add_parser('daily',help='校验日报，生成最小发布包及阅读页')
    c.add_argument('--messages',type=Path,required=True);c.add_argument('--report',type=Path,required=True)
    c.add_argument('--date',required=True);c.add_argument('--out',type=Path,required=True)
    c.add_argument('--quote',action='append',default=[],help='Agent选定的关键原话消息ID，可重复')
    c.add_argument('--show-contacts',action='store_true')
    c=parser.add_parser('remote',help='管理已获资格的发布账号及群主页')
    c.add_argument('action',choices=['groups','create-group','publish','withdraw','versions','restore','notices'])
    c.add_argument('--server',required=True);c.add_argument('--credential',type=Path,required=True)
    c.add_argument('--group');c.add_argument('--name');c.add_argument('--date');c.add_argument('--version',type=int)
    c.add_argument('--payload',type=Path)
    c=parser.add_parser('fetch',help='通过已安装微信CLI的Python读取明确群和时间窗')
    c.add_argument('--chat',required=True);c.add_argument('--start',required=True);c.add_argument('--end',required=True)
    c.add_argument('--python',required=True,help='已安装wechat-cli的Python路径')
    c.add_argument('--out',type=Path,required=True)
    c=parser.add_parser('split-days',help='将明确提供的多天记录按北京时间拆分')
    c.add_argument('--messages',type=Path,required=True);c.add_argument('--out',type=Path,required=True)


def request(server,token,path,data=None):
    parsed=urlsplit(server)
    if parsed.username or parsed.password or parsed.query or parsed.fragment or parsed.path not in ('','/'):
        raise ValueError('服务地址只能包含协议、主机和端口')
    if parsed.scheme!='https' and not (parsed.scheme=='http' and parsed.hostname in ('127.0.0.1','localhost','::1')):
        raise ValueError('远程发布必须使用HTTPS，本机环回可使用HTTP')
    class NoRedirect(HTTPRedirectHandler):
        def redirect_request(self,*args,**kwargs): return None
    raw=None if data is None else json.dumps(data,ensure_ascii=False).encode()
    req=Request(server.rstrip('/')+path,data=raw,headers={'Authorization':'Bearer '+token,'Content-Type':'application/json'})
    with build_opener(NoRedirect).open(req,timeout=30) as response:
        return json.load(response)


def run(args):
    from .cli import read_json,json_text,write_new_directory
    if args.command=='mail-drain':
        from .mail import deliver
        return deliver(Store(args.db),args.publisher,args.recipient)
    if args.command=='enrich':
        from .media import enrich
        result=enrich(read_json(args.messages),read_json(args.annotations))
        out=write_new_directory(args.out,{'messages.json':json_text(result)})
        return {'status':'enriched','messages':str(out/'messages.json'),'next':'重新prepare并提炼；原始记录保持不变'}
    if args.command=='schedule-tick':
        from .jobs import tick
        return tick(args.config)
    if args.command=='site':
        store=Store(args.db)
        if args.action=='invite':
            if not args.name: raise ValueError('请指定邀请用户名称')
            return store.invite(args.name)
        if args.action=='revoke':
            if not args.publisher: raise ValueError('请指定要撤销资格的发布者')
            return store.revoke(args.publisher)
        server=serve(store,args.host,args.port)
        print(json_text({'status':'serving','address':f'http://{args.host}:{server.server_port}','deployment':'本机开发服务；生产需HTTPS反向代理及备案配置'}),flush=True)
        try: server.serve_forever()
        except KeyboardInterrupt: pass
        finally: server.server_close()
        return {'status':'stopped'}
    if args.command=='daily':
        p=make_publication(read_json(args.report),read_json(args.messages),args.date,args.quote,not args.show_contacts)
        out=write_new_directory(args.out,{'publication.json':json_text(p),'日报.html':render_publication(p),'摘要.txt':p['conversation']+'\n'+p['date']+'\n'+p['summary']})
        return {'status':'ready','page':str(out/'日报.html'),'payload':str(out/'publication.json'),'next':'已获资格且任务要求发布时，执行remote publish；不会上传完整原始聊天'}
    if args.command=='remote':
        credential=read_json(args.credential)
        token=credential['token']
        path='/api/'+('notices' if args.action=='notices' else 'groups')
        data=None
        if args.action=='create-group':
            if not args.name: raise ValueError('缺少群名')
            data={'name':args.name}
        elif args.action not in ('groups','notices'):
            import re
            if not args.group or not re.fullmatch('[a-f0-9]{24}',args.group): raise ValueError('缺少或无效的群ID')
            path+='/'+args.group+'/'+args.action
            if args.action=='publish':
                if not args.payload: raise ValueError('缺少发布包')
                data=read_json(args.payload)
            else:
                if not args.date: raise ValueError('缺少日报日期')
                data={'date':args.date}
                if args.action=='restore': data['version']=args.version
        return request(args.server,token,path,data)
    if args.command=='fetch':
        if args.out.exists(): raise ValueError('输出目录已存在')
        args.out.mkdir(parents=True)
        target=args.out/'messages.json'
        env=os.environ.copy()
        env['PYTHONPATH']=str(Path(__file__).resolve().parent.parent)
        result=subprocess.run([args.python,'-m','qunhuibao.wechat','--chat',args.chat,'--start',args.start,'--end',args.end,'--out',str(target)],env=env,capture_output=True,timeout=180)
        if result.returncode: raise ValueError('微信取数失败；未生成日报。请核查既有CLI授权、版本和分库。')
        if read_json(target) is None: return {'status':'empty','message':'该时间窗没有缓存消息，不生成空日报'}
        from .cli import prepare
        return prepare(target,args.out/'prepared')
    if args.command=='split-days':
        import datetime as dt
        from .validation import validate_messages
        data=validate_messages(read_json(args.messages))
        days={}
        tz=dt.timezone(dt.timedelta(hours=8))
        for msg in data['messages']:
            stamp=dt.datetime.fromisoformat(msg['timestamp'])
            stamp=stamp.replace(tzinfo=tz) if stamp.tzinfo is None else stamp.astimezone(tz)
            days.setdefault(stamp.date().isoformat(),[]).append(msg)
        files={day+'.json':json_text({**data,'coverage':day+'（按北京时间拆分；仅提供的记录）','messages':rows}) for day,rows in days.items()}
        out=write_new_directory(args.out,files)
        return {'status':'split','out':str(out),'days':sorted(days)}
