(() => {
  'use strict';
  const input=document.getElementById('share-search'), results=document.getElementById('share-results');
  const fields=[...document.querySelectorAll('[data-share-search]')];
  const originals=fields.map(el=>el.innerHTML);
  const norm=s=>s.normalize('NFKC').toLowerCase().replace(/\s/g,'');
  function search(){
    results.replaceChildren();
    fields.forEach((el,i)=>{el.innerHTML=originals[i];el.classList.remove('share-hit');});
    const q=norm(input.value);if(!q)return;
    fields.forEach(el=>{
      if(!norm(el.textContent).includes(q))return;
      const walker=document.createTreeWalker(el,NodeFilter.SHOW_TEXT),nodes=[];let node;
      while((node=walker.nextNode()))nodes.push(node);
      for(const node of nodes){
        const text=node.textContent;let normalized='',map=[],offset=0;
        for(const ch of text){const n=norm(ch);for(let i=0;i<n.length;i++)map.push([offset,offset+ch.length]);normalized+=n;offset+=ch.length;}
        let cursor=0,from=0,pos;const frag=document.createDocumentFragment();
        while((pos=normalized.indexOf(q,from))>=0){const start=map[pos][0],end=map[pos+q.length-1][1];frag.append(text.slice(cursor,start));const mark=document.createElement('mark');mark.textContent=text.slice(start,end);frag.append(mark);cursor=end;from=pos+q.length;}
        if(cursor){frag.append(text.slice(cursor));node.replaceWith(frag);}
      }
      const li=document.createElement('li'),b=document.createElement('button');b.textContent=el.textContent.slice(0,100);b.onclick=()=>{fields.forEach(f=>f.classList.remove('share-hit'));el.classList.add('share-hit');el.scrollIntoView({behavior:'smooth',block:'center'});};li.append(b);results.append(li);
    });
    if(!results.children.length)results.textContent='本期没有匹配内容';
  }
  input.addEventListener('input',search);
  document.getElementById('share-clear').onclick=()=>{input.value='';search();input.focus();};
  input.addEventListener('keydown',e=>{if(e.key==='Enter')results.querySelector('button')?.click();if(e.key==='Escape')document.getElementById('share-clear').click();});
  document.querySelectorAll('.share-word').forEach(b=>b.onclick=()=>{input.value=b.textContent;search();results.querySelector('button')?.click();});
  document.getElementById('print-digest').onclick=()=>window.print();
  const status=document.getElementById('reader-status');
  document.getElementById('copy-digest').onclick=async()=>{
    const text=['.group-title','.hero .meta','.issue-title','.hero .lead'].map(s=>document.querySelector(s)?.textContent).filter(Boolean).join('\n\n');
    try{await navigator.clipboard.writeText(text);status.textContent='摘要已复制';}
    catch{let area=document.querySelector('.copy-fallback');if(!area){area=document.createElement('textarea');area.className='copy-fallback';status.parentNode.append(area);}area.value=text;area.focus();area.select();status.textContent='摘要已选中，按Ctrl+C复制';}
  };
  document.getElementById('export-image').onclick=async function(){
    this.disabled=true;status.textContent='正在生成长图…';
    try{
      const target=document.querySelector('main');
      const height=target.scrollHeight;
      if(height>28000)throw new Error('本期过长，请使用打印/PDF或缩短内容后再导出长图');
      const canvas=await html2canvas(target,{backgroundColor:'#fffaf5',scale:Math.min(2,28000/height),logging:false,windowWidth:860,ignoreElements:el=>el.matches('.reader-actions,.share-search,#share-results')});
      const blob=await new Promise(resolve=>canvas.toBlob(resolve,'image/png'));
      if(!blob)throw new Error('浏览器未能导出PNG，请使用打印/PDF');
      const url=URL.createObjectURL(blob),a=document.createElement('a');a.href=url;a.download='群汇报-'+document.querySelector('.group-title').textContent.replace(/[<>:"/\\|?*]/g,'_')+'.png';a.click();setTimeout(()=>URL.revokeObjectURL(url),60000);status.textContent='PNG长图已生成';
    }catch(e){status.textContent=e.message||'长图导出失败，请使用打印/PDF';}finally{this.disabled=false;}
  };
})();
