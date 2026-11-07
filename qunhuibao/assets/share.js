(() => {
  'use strict';
  const input = document.getElementById('share-search');
  const results = document.getElementById('share-results');
  const fields = [...document.querySelectorAll('[data-share-search]')];
  const original = fields.map(el => el.textContent);
  const normalize = s => s.normalize('NFKC').toLowerCase().replace(/\s/g, '');
  function search() {
    results.replaceChildren();
    fields.forEach((el, i) => { el.textContent = original[i]; });
    document.querySelectorAll('.share-hit').forEach(el => el.classList.remove('share-hit'));
    const q = normalize(input.value);
    if (!q) return;
    fields.forEach((el, i) => {
      let normalized = '', map = [], offset = 0;
      for (const char of original[i]) {
        const n = normalize(char); for (let j = 0; j < n.length; j++) map.push([offset, offset + char.length]);
        normalized += n; offset += char.length;
      }
      let from = 0, cursor = 0, found = false, pos;
      while ((pos = normalized.indexOf(q, from)) >= 0) {
        const start = map[pos][0], end = map[pos + q.length - 1][1];
        if (!found) el.replaceChildren();
        found = true;
        el.append(document.createTextNode(original[i].slice(cursor, start)));
        const mark = document.createElement('mark'); mark.textContent = original[i].slice(start, end); el.append(mark);
        cursor = end; from = pos + q.length;
      }
      if (found) {
        el.append(document.createTextNode(original[i].slice(cursor)));
        const li = document.createElement('li'), button = document.createElement('button');
        button.textContent = original[i].slice(0, 95);
        button.onclick = () => {document.querySelectorAll('.share-hit').forEach(x=>x.classList.remove('share-hit'));el.classList.add('share-hit');el.scrollIntoView({behavior:'smooth',block:'center'});};
        li.append(button); results.append(li);
      }
    });
    if (!results.children.length) results.textContent = '本分享版没有匹配内容';
  }
  input.addEventListener('input', search);
  function clearSearch() {input.value='';search();input.focus();}
  document.getElementById('share-clear').addEventListener('click', clearSearch);
  input.addEventListener('keydown', e => {if(e.key==='Enter') results.querySelector('button')?.click();if(e.key==='Escape')clearSearch();});
  document.querySelectorAll('.share-word').forEach(b => b.addEventListener('click', () => {input.value=b.textContent;search();results.querySelector('button')?.click();}));
  document.getElementById('print-digest')?.addEventListener('click', () => window.print());
  document.getElementById('copy-digest')?.addEventListener('click', async () => {
    const text = [document.querySelector('.group-title')?.textContent,
      document.querySelector('.hero .meta')?.textContent,
      document.querySelector('.issue-title')?.textContent,
      document.querySelector('.hero .lead')?.textContent,
      ...[...document.querySelectorAll('.hero-aside a')].map(el=>el.textContent),
      '— 群汇报 · qunhuibao.com'].filter(Boolean).join('\n\n');
    const status = document.getElementById('reader-status');
    try {
      if(!navigator.clipboard?.writeText) throw new Error('Clipboard unavailable');
      await navigator.clipboard.writeText(text);
      document.querySelector('.copy-fallback')?.remove();
      status.textContent='本期摘要已复制，可粘贴到群里。';
    } catch {
      let box=document.querySelector('.copy-fallback');
      if(!box){box=document.createElement('textarea');box.className='copy-fallback';box.readOnly=true;box.setAttribute('aria-label','本期摘要，选中后复制');status.parentNode.append(box);}
      box.value=text;box.focus();box.select();
      status.textContent='浏览器未开放剪贴板，摘要已选中，按 Ctrl+C 复制。';
    }
  });
})();
