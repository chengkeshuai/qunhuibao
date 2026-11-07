"""Explicit SMTP notification delivery; no email is sent on import or publish."""
import os
import smtplib
import ssl
from email.message import EmailMessage


def deliver(store,owner,recipient):
    host=os.environ.get('QHB_SMTP_HOST')
    username=os.environ.get('QHB_SMTP_USER')
    password=os.environ.get('QHB_SMTP_PASSWORD')
    sender=os.environ.get('QHB_SMTP_FROM',username)
    if not all((host,username,password,sender)): raise ValueError('SMTP配置不完整；通知仍保留在站内')
    if not recipient or '\n' in recipient or '\r' in recipient: raise ValueError('收件地址不正确')
    with store.db() as db:
        db.execute('CREATE TABLE IF NOT EXISTS delivered_mail(notice_id INTEGER PRIMARY KEY, recipient TEXT NOT NULL)')
        notices=db.execute('SELECT id,text,created FROM notices WHERE owner=? AND id NOT IN (SELECT notice_id FROM delivered_mail) ORDER BY id',(owner,)).fetchall()
    if not notices:return {'status':'empty','sent':0}
    sent=0
    with smtplib.SMTP_SSL(host,int(os.environ.get('QHB_SMTP_PORT','465')),context=ssl.create_default_context(),timeout=30) as smtp:
        smtp.login(username,password)
        for notice in notices:
            message=EmailMessage();message['From']=sender;message['To']=recipient;message['Subject']='群汇报 · 日报通知'
            message['Message-ID']=f'<qunhuibao-{notice["id"]}-{owner}@qunhuibao.com>'
            message.set_content(notice['text']+'\n'+notice['created'])
            smtp.send_message(message)
            with store.db() as db: db.execute('INSERT OR IGNORE INTO delivered_mail VALUES(?,?)',(notice['id'],recipient))
            sent+=1
    return {'status':'delivered','sent':sent}
