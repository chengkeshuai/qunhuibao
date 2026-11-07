const {test}=require('node:test');
const assert=require('node:assert/strict');
const {spawnSync}=require('node:child_process');
const {JSDOM,VirtualConsole}=require('jsdom');
function open(){
 const py=spawnSync('python',['-c',`from pathlib import Path
from qunhuibao.importers import import_source
from examples.build_demo import example_report
from qunhuibao.publication import make_publication,render_publication
m=import_source(Path('examples/chat.json'));r=example_report(m)
r['sections'][0]['items'][0]['body']='工具 https://example.com/docs 可用 <script>bad()</script>'
print(render_publication(make_publication(r,m,'2026-11-06',['demo-01'])))`],{cwd:require('node:path').resolve(__dirname,'..'),encoding:'utf8',env:{...process.env,PYTHONUTF8:'1'},maxBuffer:8*1024*1024});
 assert.equal(py.status,0,py.stderr);
 const errors=[],scroll=[];const vc=new VirtualConsole();vc.on('jsdomError',e=>errors.push(e));
 const dom=new JSDOM(py.stdout,{runScripts:'dangerously',url:'https://test.invalid',virtualConsole:vc,beforeParse(w){w.HTMLElement.prototype.scrollIntoView=function(){scroll.push(this);};}});
 assert.equal(errors.length,0,String(errors[0]));return {dom,d:dom.window.document,w:dom.window,scroll};
}
test('新版阅读页保留资源链接、搜索定位与中文清空',()=>{
 const x=open(),input=x.d.getElementById('share-search');
 const link=()=>x.d.querySelector('a[href="https://example.com/docs"]');assert.ok(link());
 input.value='ＥＸＡＭＰＬＥ';input.dispatchEvent(new x.w.Event('input'));
 assert.ok(x.d.querySelector('mark'));x.d.querySelector('#share-results button').click();assert.equal(x.scroll.length,1);
 x.d.getElementById('share-clear').click();assert.equal(input.value,'');assert.ok(link());assert.equal(x.d.querySelectorAll('mark').length,0);
 assert.equal(x.w.bad,undefined);x.w.close();
});
test('长图按钮成功下载与失败提示，不伪报成功',async()=>{
 const x=open();let clicked=false;
 x.w.html2canvas=async()=>({toBlob:fn=>fn(new x.w.Blob(['png']))});x.w.URL.createObjectURL=()=> 'blob:png';x.w.URL.revokeObjectURL=()=>{};
 x.w.HTMLAnchorElement.prototype.click=function(){clicked=true;};
 await x.d.getElementById('export-image').onclick();assert.ok(clicked);assert.match(x.d.getElementById('reader-status').textContent,/已生成/);
 x.w.html2canvas=async()=>{throw Error('导出失败');};await x.d.getElementById('export-image').onclick();assert.match(x.d.getElementById('reader-status').textContent,/失败/);assert.equal(x.d.getElementById('export-image').disabled,false);x.w.close();
});
