(() => {
  'use strict';
  const base = JSON.parse(document.getElementById('review-data').textContent);
  const clone = obj => JSON.parse(JSON.stringify(obj));
  const $ = id => document.getElementById(id);
  const labels = {fact:'聊天事实', decision:'已定事项', action:'待办行动', asset:'可复用资产', question:'待确认', suggestion:'AI 建议 · 未认领'};
  const strings = ['title','body','owner','due','status','question','answer','conditions','outcome'];
  const learningLabels = {question:'问题 / 场景',answer:'回答 / 方法',conditions:'适用条件与限制',outcome:'验证状态'};
  const initial = [];
  base.report.sections.forEach(section => section.items.forEach(item => initial.push({id:initial.length, section:section.key, sectionTitle:section.title, item:clone(item), selected:['topics','assets','questions'].includes(section.key), quoteRefs:[]})));
  let state = {schema_version:1, fingerprint:base.fingerprint, source_digest:base.report.source_digest, title:base.report.title, summary:base.report.summary, items:clone(initial), shareTitle:'今日群聊精华', shareSummary:'', maskNames:false, redactions:''};
  const key = 'qunhuibao-review-' + base.fingerprint;
  const messages = new Map(base.messages.messages.map(m => [m.id,m]));
  const esc = s => String(s).replace(/[&<>"']/g,c=>({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]));
  function notify(text) {$('save-status').textContent=text;}
  function persist() {
    $('share-preview').hidden=true;
    $('share-status').textContent='内容有修改，预览需刷新；下载始终使用当前内容。';
    try {localStorage.setItem(key,JSON.stringify(state));notify('已暂存到本浏览器。换电脑或清理浏览器前，请下载审稿进度。');}
    catch {notify('浏览器暂存不可用，请点击“下载审稿进度”保存。');}
  }
  function field(parent, title, value, onChange, multiline=true) {
    const label=document.createElement('label');label.className='edit-field';label.append(document.createTextNode(title));
    const input=document.createElement(multiline?'textarea':'input');input.value=value; if(multiline)input.rows=3;
    input.addEventListener('input',()=>{onChange(input.value);persist();});label.append(input);parent.append(label);return input;
  }
  function draw() {
    $('internal-title').value=state.title;$('internal-summary').value=state.summary;
    $('share-title').value=state.shareTitle;$('share-summary').value=state.shareSummary;
    $('mask-names').checked=state.maskNames;$('redactions').value=state.redactions;
    const root=$('editor-items');root.replaceChildren();
    base.report.sections.forEach(section => {
      const rows=state.items.filter(r=>r.section===section.key);if(!rows.length)return;
      const heading=document.createElement('h3');heading.textContent=section.title;root.append(heading);
      rows.forEach((row,index)=>{
        const card=document.createElement('article');card.className='edit-card'+(row.selected?'':' excluded');card.dataset.rowId=row.id;
        const select=document.createElement('input');select.type='checkbox';select.checked=row.selected;select.className='select-item';
        const label=document.createElement('label');label.append(select,document.createTextNode(' 分享此条 · '+labels[row.item.kind]));card.append(label);
        select.onchange=()=>{row.selected=select.checked;card.classList.toggle('excluded',!row.selected);persist();};
        field(card,'标题',row.item.title,v=>row.item.title=v,false);
        field(card,'内容',row.item.body,v=>row.item.body=v);
        for(const name of ['owner','due','status']) if(name in row.item) field(card,({owner:'负责人',due:'期限',status:'状态'})[name],row.item[name],v=>row.item[name]=v,false);
        for(const name of Object.keys(learningLabels)) if(name in row.item)field(card,learningLabels[name],row.item[name],v=>row.item[name]=v);
        if(row.item.steps)field(card,'方法步骤（每行一步；仅保留原文支持的步骤）',row.item.steps.join('\n'),v=>row.item.steps=v.split('\n').map(x=>x.trim()).filter(Boolean));
        const controls=document.createElement('div');controls.className='edit-actions';
        for(const [text,delta] of [['上移',-1],['下移',1]]) {
          const b=document.createElement('button');b.textContent=text;b.disabled=index+delta<0||index+delta>=rows.length;
          b.onclick=()=>{const a=state.items.indexOf(row),other=state.items.indexOf(rows[index+delta]);[state.items[a],state.items[other]]=[state.items[other],state.items[a]];persist();draw();document.querySelector(`[data-row-id="${row.id}"]`).scrollIntoView({block:'center'});};controls.append(b);
        }card.append(controls);
        row.item.evidence_refs.forEach(ref=>{
          const m=messages.get(ref),quote=document.createElement('div');quote.className='edit-source';
          const meta=document.createElement('small');meta.textContent=m.sender+' · '+(m.timestamp||'时间未提供');
          const p=document.createElement('p');p.textContent=base.display[ref]||'仅有附件索引，未读内容';
          const checkbox=document.createElement('input');checkbox.type='checkbox';checkbox.checked=row.quoteRefs.includes(ref);
          checkbox.onchange=()=>{row.quoteRefs=checkbox.checked?[...row.quoteRefs,ref]:row.quoteRefs.filter(x=>x!==ref);persist();};
          const qlabel=document.createElement('label');qlabel.append(checkbox,document.createTextNode('分享时附这条原话（包含此消息内的回复引文）'));
          quote.append(meta,p,qlabel);card.append(quote);
        });root.append(card);
      });
    });
  }
  function validate(candidate) {
    const fail=()=>{throw new Error('审稿进度格式不符或属于其他材料 / 报告，未载入。');};
    if(!candidate||candidate.schema_version!==1||candidate.fingerprint!==base.fingerprint||candidate.source_digest!==base.report.source_digest)fail();
    if(Object.keys(candidate).sort().join()!==Object.keys(state).sort().join())fail();
    for(const name of ['title','summary','shareTitle','shareSummary','redactions'])if(typeof candidate[name]!=='string'||candidate[name].length>200000)fail();
    if(typeof candidate.maskNames!=='boolean'||!Array.isArray(candidate.items)||candidate.items.length!==initial.length)fail();
    const seen=new Set();
    for(const row of candidate.items) {
      if(!row||!Number.isInteger(row.id)||!initial[row.id]||seen.has(row.id))fail();seen.add(row.id);
      const origin=initial[row.id];
      if(Object.keys(row).sort().join()!==Object.keys(origin).sort().join()||row.section!==origin.section||row.sectionTitle!==origin.sectionTitle||typeof row.selected!=='boolean'||!row.item)fail();
      if(Object.keys(row.item).sort().join()!==Object.keys(origin.item).sort().join()||row.item.kind!==origin.item.kind||JSON.stringify(row.item.evidence_refs)!==JSON.stringify(origin.item.evidence_refs))fail();
      for(const k of strings)if(k in origin.item&&(typeof row.item[k]!=='string'||row.item[k].length>200000))fail();
      if('steps' in origin.item&&(!Array.isArray(row.item.steps)||row.item.steps.length>30||row.item.steps.some(x=>typeof x!=='string'||!x.trim()||x.length>200000)))fail();
      if(!Array.isArray(row.quoteRefs)||new Set(row.quoteRefs).size!==row.quoteRefs.length||row.quoteRefs.some(x=>!origin.item.evidence_refs.includes(x)))fail();
    }
    return clone(candidate);
  }
  function restore(candidate) {const checked=validate(candidate);state=checked;draw();persist();return true;}
  function download(name,content,type) {
    const url=URL.createObjectURL(new Blob([content],{type})),a=document.createElement('a');a.href=url;a.download=name;document.body.append(a);a.click();a.remove();setTimeout(()=>URL.revokeObjectURL(url),2000);
  }
  function reportData() {
    validate(state);
    const report=clone(base.report);report.title=state.title;report.summary=state.summary;
    report.sections=report.sections.map(s=>({...s,items:state.items.filter(r=>r.section===s.key).map(r=>clone(r.item))}));
    if(!report.title.trim()||!report.summary.trim()||state.items.some(r=>!r.item.title.trim()||!r.item.body.trim()))throw new Error('标题、摘要和条目内容不能为空。');
    for(const section of report.sections) for(const item of section.items) for(const name of Object.keys(learningLabels)) if(name in item&&!item[name].trim())delete item[name];
    return report;
  }
  function sanitizer() {
    const replacements=[];
    if(state.maskNames) {
      replacements.push([base.messages.conversation,'社群']);
      [...new Set(base.messages.messages.map(m=>m.sender))].forEach((name,i)=>replacements.push([name,'成员'+String(i+1).padStart(2,'0')]));
    }
    state.redactions.split('\n').map(x=>x.trim()).filter(Boolean).forEach(x=>replacements.push([x,'[已遮盖]']));
    replacements.sort((a,b)=>b[0].length-a[0].length);
    const map=new Map(replacements),pattern=replacements.length?new RegExp([...map.keys()].map(s=>s.replace(/[.*+?^${}()|[\]\\]/g,'\\$&')).join('|'),'g'):null;
    return value=>{
      let s=String(value);if(pattern)s=s.replace(pattern,m=>map.get(m));
      return s.replace(/https?:\/\/[^\s<>"）]+/gi,'[链接已隐藏]').replace(/[A-Z0-9._%+-]+@[A-Z0-9.-]+\.[A-Z]{2,}/gi,'[邮箱已隐藏]').replace(/(?:\+?86[- ]?)?1[3-9](?:[- ]?\d){9}(?!\d)/g,'[手机已隐藏]').replace(/(?:微信号|微信|vx|v信|wechat)\s*[:：=]\s*[a-zA-Z0-9_-]{5,}/gi,'[联系方式已隐藏]');
    };
  }
  function buildShare() {
    validate(state);
    const rows=state.items.filter(r=>r.selected);
    if(!rows.length)throw new Error('请至少勾选一条分享内容。');
    if(!state.shareTitle.trim()||rows.some(r=>!r.item.title.trim()||!r.item.body.trim()))throw new Error('分享标题和所选条目不能为空。');
    const sanitize=sanitizer(), safe=s=>esc(sanitize(s));
    let index=0, sectionIndex=0;
    const entryIds=new Map(rows.map((r,i)=>[r.id,'entry-'+(i+1)]));
    // Keep IDs aligned with actual section order, including drafts with moved rows.
    base.report.sections.forEach(s=>rows.filter(r=>r.section===s.key).forEach(r=>entryIds.set(r.id,'entry-'+(++index))));
    index=0;
    const chapterNames={topics:'今日讨论重点',assets:'工具与资源',questions:'问题与回答',actions:'下一步跟进',decisions:'重要消息'};
    const chapterNotes={topics:'看懂问题与结论',assets:'留下值得再用的线索',questions:'已答到哪，还缺什么',actions:'区分认领与建议',decisions:'有依据的已定事项'};
    const readingLabels={...labels,fact:'重点讨论',asset:'工具 / 方法',question:'继续追问'};
    const nav=[];
    const blocks=base.report.sections.map(section=>{
      const selected=rows.filter(r=>r.section===section.key);if(!selected.length)return '';
      const number=String(++sectionIndex).padStart(2,'0'),chapter=chapterNames[section.key]||section.title;
      nav.push(`<a href="#chapter-${section.key}"><span class="nav-number">${number}</span><span class="nav-label">${safe(chapter)}</span><span class="nav-arrow" aria-hidden="true">→</span></a>`);
      const grid=section.key==='assets'?'resources-grid':section.key==='questions'?'questions-grid':'topics-grid';
      return `<section class="report-section" id="chapter-${section.key}"><header class="digest-section-heading"><span>${number}</span><h2>${safe(chapter)}</h2><small>${selected.length} 条 · ${chapterNotes[section.key]||''}</small></header><div class="${grid}">${selected.map((row,localIndex)=>{
        const item=row.item;
        const contributors=[...new Set(item.evidence_refs.map(ref=>messages.get(ref).sender))];
        const authors=contributors.length?`<p class="entry-authors"><b>参与讨论</b> · ${contributors.map(safe).join('、')}</p>`:'';
        let answer='';
        if(item.question||item.answer)answer='<div class="qa-answer">'+(item.question?`<p data-share-search><b>问：</b>${safe(item.question)}</p>`:'')+(item.answer?`<p data-share-search><b>答：</b>${safe(item.answer)}</p>`:'')+'</div>';
        if(item.steps?.length)answer+='<ol class="learning-steps">'+item.steps.map(x=>`<li data-share-search>${safe(x)}</li>`).join('')+'</ol>';
        let notes='';
        for(const [k,label] of [['conditions','适用条件'],['outcome','讨论进展']])if(item[k])notes+=`<div><strong>${label}</strong><p data-share-search>${safe(item[k])}</p></div>`;
        if(item.kind==='action'||item.kind==='suggestion'&&row.section==='actions')notes+=`<div><strong>跟进信息</strong><p data-share-search>负责人：${safe(item.owner||'待确认')} · 期限：${safe(item.due||'待确认')} · 状态：${safe(item.status||(item.kind==='suggestion'?'未认领':'待确认'))}</p></div>`;
        const quotes=row.quoteRefs.map(ref=>{const m=messages.get(ref),time=m.timestamp.match(/\d{2}:\d{2}/)?.[0]||'时间未提供';return `<blockquote class="edit-source"><div class="quote-person"><b>${safe(m.sender)}</b><time>${safe(time)}</time></div><p data-share-search>${safe(base.display[ref]||'附件未读取')}</p></blockquote>`;}).join('');
        const flavor=section.key==='assets'?'resource-entry':section.key==='questions'?'question-entry':'topic-entry';
        return `<article class="edit-card share-card ${flavor}" id="${entryIds.get(row.id)}"><div class="entry-kicker"><span class="entry-no">${String(localIndex+1).padStart(2,'0')}</span><span class="edit-badge">${readingLabels[item.kind]}</span></div><h3 data-share-search>${safe(item.title)}</h3>${authors}<div class="story-grid"><div><p class="share-body" data-share-search>${safe(item.body)}</p>${answer}</div>${notes?'<aside class="entry-notes">'+notes+'</aside>':''}</div>${quotes?'<div class="entry-quotes">'+quotes+'</div>':''}</article>`;
      }).join('')}</div></section>`;
    }).join('');
    // Generate from an allowlist. No raw report, draft state, sources, paths or IDs are serialized.
    const css=$('brand-style').textContent, logo=$('brand-logo').getAttribute('src');
    const shareScript=JSON.parse($('share-runtime').textContent);
    const groupTitle=safe(base.messages.conversation)+' · 群日报';
    const norm=s=>s.normalize('NFKC').toLowerCase().replace(/\s/g,'');
    const itemText=r=>[r.item.title,r.item.body,r.item.question,r.item.answer,r.item.conditions,r.item.outcome,...(r.item.steps||[])].filter(Boolean).join(' ');
    const words=(base.report.keywords||[]).map(word=>({word,count:rows.filter(r=>norm(itemText(r)).includes(norm(word))).length})).filter(x=>x.count).map(({word,count})=>`<button type="button" class="share-word" data-weight="${Math.min(3,count)}" title="本篇 ${count} 条内容提及，点击定位">${safe(word)}</button>`).join(' ');
    const highlights=(rows.filter(r=>r.section==='topics').length?rows.filter(r=>r.section==='topics'):rows).slice(0,3);
    const highlightsHtml=highlights.map((r,i)=>`<a href="#${entryIds.get(r.id)}"><span>${String(i+1).padStart(2,'0')}</span>${safe(r.item.title)}</a>`).join('');
    const counts=[['topics','条重点'],['assets','条资料'],['questions','个问题']].map(([key,label])=>({count:rows.filter(r=>r.section===key).length,label})).filter(x=>x.count);
    const stats=counts.map(x=>`<span><b>${x.count}</b>${x.label}</span>`).join('')||`<span><b>${rows.length}</b>条内容</span>`;
    return '<!doctype html><html lang="zh-CN"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1"><meta name="robots" content="noindex,nofollow"><title>'+groupTitle+' · '+safe(base.report.period||'')+'</title><style>'+css+'</style></head><body class="share-page"><div class="wrap"><header class="brand-header"><img class="brand-logo" src="'+logo+'" alt="群汇报" width="270" height="90"><div class="edition-mark"><b>群聊一键出日报</b></div></header><section class="hero"><div class="hero-copy"><p class="meta">社群精华日报 / '+safe(base.report.period||'时间范围未提供')+'</p><h1 class="group-title" data-share-search>'+groupTitle+'</h1><p class="issue-title" data-share-search>'+safe(state.shareTitle)+'</p><p class="lead" data-share-search>'+safe(state.shareSummary)+'</p></div><aside class="hero-aside"><small>本期值得带走</small>'+highlightsHtml+'</aside></section><div class="reader-actions"><button type="button" id="copy-digest">复制本期摘要</button><button type="button" id="print-digest">打印 / 保存 PDF</button><span id="reader-status" role="status" aria-live="polite"></span></div><div class="edition-summary"><div class="edition-stats">'+stats+'</div><p>依据本次提供时段整理，非全天完整历史。图片与视频实体未读取。</p></div><nav class="toc digest-nav" aria-label="章节导航">'+nav.join('')+'</nav><div class="share-search"><label for="share-search">搜索本篇</label><input id="share-search" type="search" placeholder="输入关键词，点击结果直达内容"><button id="share-clear" type="button">清空</button><ol id="share-results"></ol></div>'+(words?'<aside class="topic-map"><div class="topic-map-head"><strong>话题地图</strong><small>点词定位 · 字号表示本篇所选条目提及量</small></div><nav aria-label="话题入口">'+words+'</nav></aside>':'')+'<main>'+blocks+'</main><footer class="report-footer"><div class="footer-brand"><span>群汇报 · 群聊一键出日报</span><span>qunhuibao.com</span></div><p>本地阅读版，未自动发布。建议与已决定事项分开标注；原话若有遮盖，属于脱敏摘录。</p></footer></div><script>'+shareScript+'</script></body></html>';
  }
  function run(action) {try{action();}catch(e){notify(e.message);$('share-status').textContent=e.message;}}
  for(const [id,name] of [['internal-title','title'],['internal-summary','summary'],['share-title','shareTitle'],['share-summary','shareSummary'],['redactions','redactions']]) $(id).addEventListener('input',()=>{state[name]=$(id).value;persist();});
  $('mask-names').onchange=()=>{state.maskNames=$('mask-names').checked;persist();};
  $('save-draft').onclick=()=>run(()=>{validate(state);download('群汇报-审稿进度-私有.json',JSON.stringify(state,null,2),'application/json');notify('已发起下载。请在浏览器下载列表确认；审稿进度含私有内容，不要分享。');});
  $('save-report').onclick=()=>run(()=>download('report.reviewed.json',JSON.stringify(reportData(),null,2),'application/json'));
  $('restore-local').onclick=()=>run(()=>{const raw=localStorage.getItem(key);if(!raw)throw new Error('本浏览器没有这篇报告的草稿。');restore(JSON.parse(raw));});
  $('load-draft').onchange=async()=>{const file=$('load-draft').files[0];if(!file)return;try{if(file.size>32*1024*1024)throw new Error('审稿文件超过32MiB。');restore(JSON.parse(await file.text()));}catch(e){notify(e.message);}finally{$('load-draft').value='';}};
  for(const [id,predicate] of [['select-reading',r=>['topics','assets','questions'].includes(r.section)],['select-all',()=>true],['select-none',()=>false]])$(id).onclick=()=>{state.items.forEach(r=>r.selected=predicate(r));persist();draw();};
  $('preview-share').onclick=()=>run(()=>{const html=buildShare();$('share-preview').srcdoc=html;$('share-preview').hidden=false;$('share-status').textContent='以下是实际导出的内容，请核对再分享。';});
  $('download-share').onclick=()=>run(()=>{download('群汇报-分享版.html',buildShare(),'text/html;charset=utf-8');$('share-status').textContent='已发起分享文件下载。只转发“分享版”，不要转发审稿台或整个文件夹。';});
  $('coverage').textContent=base.messages.conversation+' · '+base.messages.coverage+' · '+base.messages.messages.length+' 条消息 · '+new Set(base.messages.messages.map(m=>m.sender)).size+' 位发言人 · '+base.messages.messages.reduce((n,m)=>n+m.attachments.length,0)+' 个附件仅索引';
  base.messages.warnings.forEach(s=>{const li=document.createElement('li');li.textContent=s;$('warnings').append(li);});
  draw();
  try{if(localStorage.getItem(key))notify('发现这篇报告的浏览器草稿，可点击“恢复浏览器草稿”；当前仍显示原始版本。');}catch{}
  window.QHBReview=Object.freeze({snapshot:()=>clone(state),restore,buildShare,reportData});
})();
