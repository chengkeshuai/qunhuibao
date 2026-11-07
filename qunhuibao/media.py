"""Bind Agent OCR/transcription results to explicit local attachment files."""
import copy
import hashlib
from pathlib import Path
from .validation import validate_messages,source_digest


def enrich(messages, annotations):
    validate_messages(messages)
    if not isinstance(annotations,dict) or set(annotations)!={'source_digest','items'} or annotations['source_digest']!=source_digest(messages):
        raise ValueError('附件识别结果未绑定当前聊天材料')
    result=copy.deepcopy(messages)
    indexed={m['id']:m for m in result['messages']}
    seen=set()
    for entry in annotations['items']:
        if set(entry)!={'message_id','attachment_index','file','sha256','method','text'}: raise ValueError('附件识别字段不正确')
        key=(entry['message_id'],entry['attachment_index'])
        if key in seen: raise ValueError('附件识别重复')
        seen.add(key)
        msg=indexed.get(entry['message_id'])
        index=entry['attachment_index']
        if not msg or type(index)!=int or not 0<=index<len(msg['attachments']): raise ValueError('附件引用不存在')
        att=msg['attachments'][index]
        if entry['method'] not in ('ocr','transcription'): raise ValueError('只接受图片OCR或语音转写')
        if att['kind'] not in ({'image'} if entry['method']=='ocr' else {'audio','voice'}): raise ValueError('附件类型与识别方式不匹配')
        path=Path(entry['file']).resolve()
        # The source itself must bind the attachment; arbitrary files cannot be substituted.
        if not att['source'] or Path(att['source']).resolve()!=path: raise ValueError('识别文件未与原消息附件精确关联')
        if not path.is_file() or path.stat().st_size>100*1024*1024: raise ValueError('附件缺失或过大')
        with path.open('rb') as stream:
            digest=hashlib.sha256()
            for block in iter(lambda:stream.read(1024*1024),b''):digest.update(block)
        if digest.hexdigest()!=entry['sha256']:raise ValueError('识别文件内容已变化')
        text=entry['text']
        if not isinstance(text,str) or not text.strip() or len(text)>100000:raise ValueError('识别文字不正确')
        msg['text']+='\n\n['+('图片OCR' if entry['method']=='ocr' else '语音转写')+' · Agent识别，可能有误]\n'+text
    result['warnings'].append('已纳入明确关联文件的Agent识别文字；识别准确性仍需核对，未识别附件不推断。')
    return validate_messages(result)
