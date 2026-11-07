const {test} = require('node:test');
const assert = require('node:assert/strict');
const {spawnSync} = require('node:child_process');
const {JSDOM, VirtualConsole} = require('jsdom');
const path = require('node:path');
function fixture() {
  const messages={schema_version:1,conversation:'保密客户群',coverage:'2026-11-06 截至13:36',warnings:['附件未读取'],messages:[
    {id:'SECRET_ID_1',sender:'张老板',timestamp:'2026-11-06T13:30',text:'原文秘密A 联系13812345678 邮箱user@example.com 微信:abcdef123',attachments:[],sources:[{file:'D:/secret/path.txt',locator:'line 7'}]},
    {id:'SECRET_ID_2',sender:'王教练',timestamp:'',text:'绝不分享的秘密B',attachments:[]},
  ]};
  const report={schema_version:1,source_digest:'',conversation:messages.conversation,title:'内部机密标题',summary:'内部摘要不可泄漏',period:'2026-11-06 截至13:36',keywords:[],sections:[
    {key:'topics',title:'今日重点',items:[{title:'方案A',body:'张老板讲剪辑方法 13812345678 user@example.com https://example.com/token',kind:'fact',evidence_refs:['SECRET_ID_1'],question:'如何处理？',answer:'有条件的回答',conditions:'只适用于本场景',outcome:'仅本人反馈，待复验',steps:['先检查素材','再试剪一段']},
    {title:'未选条目秘密C',body:'独有机密D',kind:'fact',evidence_refs:['SECRET_ID_2']}]},
    {key:'actions',title:'运营跟进',items:[{title:'私人待办秘密E',body:'建议验证',kind:'suggestion',evidence_refs:[],owner:'待确认',due:'待确认',status:'未认领'}]}
  ]};return {report,messages};
}
function open() {
  const result=spawnSync('python',['-c','import json,sys; from qunhuibao.editor import render_editor; from qunhuibao.validation import source_digest; d=json.load(sys.stdin); d["report"]["source_digest"]=source_digest(d["messages"]); print(render_editor(d["report"],d["messages"]))'],{cwd:path.resolve(__dirname,'..'),input:JSON.stringify(fixture()),encoding:'utf8',env:{...process.env,PYTHONUTF8:'1'},maxBuffer:8*1024*1024});
  assert.equal(result.status,0,result.stderr);
  const errors=[],scrolls=[],downloads=[];const vc=new VirtualConsole();vc.on('jsdomError',e=>errors.push(e));
  const dom=new JSDOM(result.stdout,{url:'https://offline.test/review',runScripts:'dangerously',virtualConsole:vc,beforeParse(w){w.HTMLElement.prototype.scrollIntoView=function(){scrolls.push(this);};w.URL.createObjectURL=blob=>{downloads.push(blob);return 'blob:test';};w.URL.revokeObjectURL=()=>{};w.HTMLAnchorElement.prototype.click=function(){};}});
  assert.equal(errors.length,0,String(errors[0]));return {dom,w:dom.window,d:dom.window.document,api:dom.window.QHBReview,errors,scrolls,downloads};
}
test('分享导出物理裁剪：不携带原文、未选条目、内部标题摘要、路径或私有状态',()=>{
  const x=open(),s=x.api.snapshot();s.maskNames=true;s.items[1].selected=false;x.api.restore(s);
  const html=x.api.buildShare();
  for(const secret of ['原文秘密A','绝不分享的秘密B','未选条目秘密C','独有机密D','私人待办秘密E','内部机密标题','内部摘要不可泄漏','SECRET_ID','D:/secret','source_digest','review-data','fingerprint','张老板','保密客户群','13812345678','user@example.com','https://example.com/token'])assert.ok(!html.includes(secret),secret);
  assert.ok(html.includes('方案A'));assert.ok(html.includes('适用条件'));assert.ok(html.includes('先检查素材'));
  x.dom.window.close();
});
test('仅勾选的引用输出；遮盖昵称联系方式与自定义词；关闭昵称替换仍遮盖联系方式',()=>{
  const x=open(),s=x.api.snapshot();s.maskNames=true;s.items[1].selected=false;s.items[0].quoteRefs=['SECRET_ID_1'];s.redactions='原文秘密A';x.api.restore(s);
  let html=x.api.buildShare();assert.ok(!html.includes('原文秘密A'));assert.ok(html.includes('[已遮盖]'));assert.ok(!html.includes('abcdef123'));assert.ok(!html.includes('张老板'));
  s.maskNames=false;x.api.restore(s);html=x.api.buildShare();assert.ok(html.includes('张老板'));assert.ok(!html.includes('13812345678'));x.w.close();
});
test('审稿进度往返保留编辑排序选择；错误草稿不覆盖现有状态',()=>{
  const x=open();const s=x.api.snapshot();s.title='已修改';s.items[0].item.body='修改后的正文';s.items.reverse();s.items[0].selected=true;
  x.api.restore(s);assert.equal(JSON.stringify(x.api.snapshot()),JSON.stringify(s));assert.equal(x.api.reportData().title,'已修改');
  const bad=JSON.parse(JSON.stringify(s));bad.fingerprint='other';assert.throws(()=>x.api.restore(bad));assert.equal(x.api.snapshot().title,'已修改');
  bad.fingerprint=s.fingerprint;bad.items[0].item.kind='decision';assert.throws(()=>x.api.restore(bad));
  const tampered=JSON.parse(JSON.stringify(s));tampered.items[1].item.evidence_refs=['SECRET_ID_1'];assert.throws(()=>x.api.restore(tampered));x.w.close();
});
test('真实表单编辑、上移、下载、浏览器恢复',()=>{
  const x=open();let input=x.d.querySelector('[data-row-id="0"] textarea');input.value='在表单中修改';input.dispatchEvent(new x.w.Event('input'));
  assert.equal(x.api.snapshot().items[0].item.body,'在表单中修改');assert.ok(x.w.localStorage.length>0);
  x.d.querySelector('[data-row-id="1"] .edit-actions button').click();assert.equal(x.api.snapshot().items[0].id,1);
  x.d.getElementById('save-draft').click();x.d.getElementById('download-share').click();assert.equal(x.downloads.length,2);
  x.d.getElementById('restore-local').click();assert.equal(x.api.snapshot().items[0].id,1);assert.equal(x.errors.length,0);x.w.close();
});
test('分享正文和审稿输入中的HTML保持文字，不执行脚本',()=>{
  const x=open(),s=x.api.snapshot();s.items[0].item.body='</script><img src=x onerror="window.injected=1"><script>window.injected=2</script>';s.shareTitle='<svg onload="window.injected=3">';x.api.restore(s);
  assert.equal(x.w.injected,undefined);const shared=new JSDOM(x.api.buildShare(),{runScripts:'dangerously'});assert.equal(shared.window.injected,undefined);assert.equal(shared.window.document.querySelectorAll('img').length,1);assert.ok(shared.window.document.body.textContent.includes('<img src=x'));shared.window.close();x.w.close();
});
test('导出页面搜索点击定位、高亮、空格全半角容错，清空恢复',()=>{
  const x=open(),scrolls=[];const shared=new JSDOM(x.api.buildShare(),{runScripts:'dangerously',beforeParse(w){w.HTMLElement.prototype.scrollIntoView=function(){scrolls.push(this);};}});
  const d=shared.window.document,q=d.getElementById('share-search');q.value='剪 辑';q.dispatchEvent(new shared.window.Event('input'));const b=d.querySelector('#share-results button');assert.ok(b);b.click();assert.equal(scrolls.length,1);assert.ok(d.querySelector('mark'));assert.ok(d.querySelector('.share-hit'));
  q.value='';q.dispatchEvent(new shared.window.Event('input'));assert.equal(d.querySelectorAll('mark').length,0);shared.window.close();x.w.close();
});
test('全部取消与空标题不能导出，修改后旧预览隐藏',()=>{
  const x=open();x.d.getElementById('preview-share').click();assert.equal(x.d.getElementById('share-preview').hidden,false);
  x.d.getElementById('select-none').click();assert.equal(x.d.getElementById('share-preview').hidden,true);assert.throws(()=>x.api.buildShare(),/至少/);
  x.d.getElementById('select-all').click();const s=x.api.snapshot();s.shareTitle=' ';x.api.restore(s);assert.throws(()=>x.api.buildShare(),/不能为空/);x.w.close();
});

test('审稿台和实际导出页加载完整品牌样式：基础字体、Logo尺寸、容器与封面布局生效',()=>{
  const x=open();
  const shared=new JSDOM(x.api.buildShare());
  for(const w of [x.w,shared.window]) {
    const style=el=>w.getComputedStyle(w.document.querySelector(el));
    assert.equal(style('body').margin,'0px','基础reset必须加载，不能只加载补充CSS');
    assert.ok(style('body').fontFamily.includes('Microsoft YaHei'),'基础中文字体必须实际生效');
    assert.equal(style('.brand-header').display,'flex');
    const isShare=w.document.body.classList.contains('share-page');
    assert.equal(style('.brand-logo').width,'270px','沿用品牌Logo尺寸，不能按原图自然宽度撑屏');
    assert.equal(style('.brand-logo').maxWidth,'65%');
    assert.equal(style('.brand-logo').height,'auto');
    assert.equal(w.document.querySelector('.brand-logo').getAttribute('width'),'270','HTML本身也限定基础尺寸');
    assert.equal(style('.wrap').maxWidth,'1120px');
    assert.equal(style('.hero').display,isShare?'grid':'block','分享封面双栏有导读，审稿封面为单栏');
    assert.equal(style('.hero h1').fontSize,'38px');
    assert.ok(style('.hero').backgroundImage.includes('linear-gradient(115deg'),'封面沿用同城圈暖橙浅底');
    assert.equal(style('body').backgroundColor,'rgb(255, 250, 247)');
    if(isShare){
      assert.equal(style('.digest-nav').display,'grid');
      assert.equal(style('.digest-nav').gridTemplateColumns,'repeat(3,minmax(0,1fr))');
      assert.ok(w.document.querySelector('.digest-nav .nav-number'));
    }
    const media=[...w.document.styleSheets].flatMap(s=>[...s.cssRules]).filter(r=>r.conditionText?.includes('max-width:620px'));
    assert.ok(media.some(r=>r.cssText.includes('padding: 20px 16px 40px')),'窄屏缩小页边距');
    assert.ok(media.some(r=>r.cssText.includes('font-size: 28px')),'窄屏标题适配');
  }
  shared.window.close();x.w.close();
});

test('群内阅读默认真实昵称；中文清空按钮可点击，清除高亮并返回输入框',()=>{
  const x=open();assert.equal(x.api.snapshot().maskNames,false);assert.equal(x.d.getElementById('mask-names').checked,false);
  const s=x.api.snapshot();s.items[0].quoteRefs=['SECRET_ID_1'];x.api.restore(s);
  const shared=new JSDOM(x.api.buildShare(),{runScripts:'dangerously',beforeParse(w){w.HTMLElement.prototype.scrollIntoView=()=>{};}}),w=shared.window,d=w.document;
  assert.ok(d.querySelector('.entry-authors').textContent.includes('张老板'));assert.ok(d.querySelector('.quote-person').textContent.includes('张老板'));assert.ok(!d.body.textContent.includes('成员01'));
  const q=d.getElementById('share-search'),clear=d.getElementById('share-clear');assert.equal(clear.textContent,'清空');assert.equal(w.getComputedStyle(clear).height,'44px');assert.equal(w.getComputedStyle(clear).minWidth,'72px');
  q.value='剪辑';q.dispatchEvent(new w.Event('input'));assert.ok(d.querySelector('mark'));d.querySelector('#share-results button').click();assert.ok(d.querySelector('.share-hit'));
  clear.click();assert.equal(q.value,'');assert.equal(d.querySelectorAll('mark,.share-hit').length,0);assert.equal(d.getElementById('share-results').children.length,0);assert.equal(d.activeElement,q);
  for(const a of d.querySelectorAll('.hero-aside a,.digest-nav a'))assert.ok(d.querySelector(a.getAttribute('href')),'导读与章节链接应有实际目标');
  w.close();x.w.close();
});

test('群名作为主标题与标签页身份；复制摘要只使用分享内容，剪贴板失败可手动复制',async()=>{
  const x=open(),s=x.api.snapshot();s.maskNames=true;s.items[1].selected=false;s.shareTitle='本期方法';s.shareSummary='本期公开导语';x.api.restore(s);
  let printed=0,copied='';
  const shared=new JSDOM(x.api.buildShare(),{runScripts:'dangerously',beforeParse(w){w.print=()=>printed++;}}),w=shared.window,d=w.document;
  assert.equal(d.querySelector('h1').textContent,'社群 · 群日报');
  assert.ok(d.title.startsWith('社群 · 群日报'));
  assert.equal(d.querySelector('.issue-title').textContent,'本期方法');
  d.getElementById('copy-digest').click();await new Promise(resolve=>setTimeout(resolve,0));
  const fallback=d.querySelector('.copy-fallback');assert.ok(fallback);assert.ok(fallback.value.includes('方案A'));
  for(const secret of ['保密客户群','内部机密标题','未选条目秘密C','原文秘密A'])assert.ok(!fallback.value.includes(secret));
  Object.defineProperty(w.navigator,'clipboard',{value:{writeText:async text=>{copied=text;}}});
  d.getElementById('copy-digest').click();await new Promise(resolve=>setTimeout(resolve,0));
  assert.ok(copied.includes('本期公开导语'));assert.equal(d.querySelector('.copy-fallback'),null);
  d.getElementById('print-digest').click();assert.equal(printed,1);
  w.close();x.w.close();
});
