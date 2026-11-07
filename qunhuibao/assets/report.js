/* Trusted static behavior. Report and chat text only enter DOM text nodes. */
(() => {
  'use strict';
  const find = (selector) => document.querySelector(selector);
  const items = Array.from(document.querySelectorAll('.report-item'));
  const search = find('#report-search');
  const scope = find('#search-scope');
  const resultList = find('#search-results');
  const position = find('#search-position');
  const previous = find('#search-prev');
  const next = find('#search-next');
  const more = find('#search-more');
  const returnButton = find('#return-to-search');
  const floating = find('#search-floating');
  const floatingPrevious = find('#search-floating-prev');
  const floatingNext = find('#search-floating-next');
  const floatingPosition = find('#search-floating-position');
  const toast = find('#report-toast');
  let toastTimer;
  const notify = (message) => {
    toast.textContent = message;
    toast.hidden = false;
    clearTimeout(toastTimer);
    toastTimer = setTimeout(() => { toast.hidden = true; }, 3000);
  };

  const segmenter = typeof Intl.Segmenter === 'function' ? new Intl.Segmenter(undefined, {granularity: 'grapheme'}) : null;
  const normalize = (value) => value.normalize('NFKC').toLowerCase().replace(/\s/gu, '');
  function indexedText(value) {
    const segments = segmenter ? Array.from(segmenter.segment(value)) : (() => {
      let offset = 0;
      return Array.from(value, (segment) => {
        const result = {segment, index: offset};
        offset += segment.length;
        return result;
      });
    })();
    let text = '';
    const starts = [], ends = [];
    segments.forEach(({segment, index}) => {
      const normalized = normalize(segment);
      text += normalized;
      for (let unit = 0; unit < normalized.length; unit += 1) {
        starts.push(index);
        ends.push(index + segment.length);
      }
    });
    return {text, starts, ends};
  }

  const fields = Array.from(document.querySelectorAll('[data-search-field]')).map((node) => {
    const original = node.textContent;
    const source = node.closest('.source-message');
    const block = source || node.closest('.report-item') || find('#report-overview');
    let aliases = [];
    try { aliases = JSON.parse(node.getAttribute('data-aliases') || '[]'); } catch (error) { /* Invalid metadata has no aliases. */ }
    aliases = Array.isArray(aliases) ? aliases.filter((alias) =>
      Number.isInteger(alias.start) && Number.isInteger(alias.end) && alias.start >= 0 && alias.end <= original.length &&
      alias.end > alias.start && typeof alias.canonical === 'string' && original.slice(alias.start, alias.end) === alias.original
    ) : [];
    return {node, original, indexed: indexedText(original), aliases, block, scope: source ? 'sources' : 'report'};
  });
  const fieldsById = new Map(fields.map((field) => [field.node.id, field]));
  // Reverse lookup uses only pairs approved for occurrences in this document.
  // Canonical queries match an alias only at its reviewed original-text range.
  const approvedPairs = new Map();
  fields.forEach((field) => field.aliases.forEach((alias) => {
    const original = normalize(alias.original), canonical = normalize(alias.canonical);
    if (!approvedPairs.has(original)) approvedPairs.set(original, new Set());
    approvedPairs.get(original).add(canonical);
  }));
  let matches = [];
  let current = -1;
  let visibleCount = 8;
  let keywordSearch = null;

  function textMatches(field, query) {
    const candidates = [];
    const terms = new Set([query, ...(approvedPairs.get(query) || [])]);
    terms.forEach((term) => {
      if (!term) return;
      let offset = 0;
      while ((offset = field.indexed.text.indexOf(term, offset)) !== -1) {
        candidates.push({start: field.indexed.starts[offset], end: field.indexed.ends[offset + term.length - 1],
          alias: term === query ? '' : '按已确认术语匹配'});
        offset += term.length;
      }
    });
    field.aliases.forEach((alias) => {
      if (terms.has(normalize(alias.canonical))) candidates.push({start: alias.start, end: alias.end,
        alias: '原文 ' + alias.original + ' · 已确认指 ' + alias.canonical});
    });
    candidates.sort((a, b) => a.start - b.start || b.end - a.end);
    const ranges = [];
    let end = -1;
    candidates.forEach((candidate) => {
      if (candidate.start >= end) { ranges.push(candidate); end = candidate.end; }
    });
    return ranges;
  }

  function labelFor(field) {
    if (field.scope === 'sources') {
      const number = field.block.querySelector('.source-number').textContent;
      const sender = field.block.querySelector('.source-sender').textContent;
      const time = field.block.querySelector('.message-time').textContent;
      return '原消息 ' + number + ' ' + sender + ' · ' + time;
    }
    const title = field.block.querySelector('.item-title') || field.block.querySelector('h1');
    return '报告 · ' + (title ? title.textContent : '阅读概览');
  }

  function updatePosition() {
    const query = normalize(search.value);
    position.textContent = !query ? '输入关键词后显示结果' : matches.length ?
      (current < 0 ? '找到 ' + matches.length + ' 处匹配' : '第 ' + (current + 1) + ' / ' + matches.length + ' 处') : '没有匹配内容';
    if (keywordSearch) position.textContent = keywordSearch.messageCount + ' 条消息 · ' + position.textContent;
    const keywordNote = find('#search-keyword-note');
    if (keywordNote) keywordNote.hidden = !keywordSearch;
    previous.disabled = next.disabled = matches.length === 0;
    floating.hidden = current < 0;
    floatingPrevious.disabled = floatingNext.disabled = matches.length === 0;
    floatingPosition.textContent = current < 0 ? '' : (current + 1) + ' / ' + matches.length;
    resultList.querySelectorAll('.search-result-link').forEach((link) => {
      if (Number(link.dataset.matchIndex) === current) link.setAttribute('aria-current', 'true');
      else link.removeAttribute('aria-current');
    });
  }

  function renderResults() {
    resultList.replaceChildren();
    matches.slice(0, visibleCount).forEach((match, index) => {
      const li = document.createElement('li');
      const link = document.createElement('a');
      link.className = 'search-result-link';
      link.href = '#' + match.mark.id;
      link.dataset.matchIndex = String(index);
      const label = document.createElement('span');
      label.className = 'search-result-label';
      label.textContent = (index + 1) + '. ' + labelFor(match.field);
      const snippet = document.createElement('span');
      snippet.className = 'search-snippet';
      const from = Math.max(0, match.start - 28), to = Math.min(match.field.original.length, match.end + 42);
      snippet.append(document.createTextNode((from ? '…' : '') + match.field.original.slice(from, match.start)));
      const hit = document.createElement('strong');
      hit.textContent = match.field.original.slice(match.start, match.end);
      snippet.append(hit, document.createTextNode(match.field.original.slice(match.end, to) + (to < match.field.original.length ? '…' : '')));
      link.append(label, snippet);
      if (match.alias) {
        const note = document.createElement('small');
        note.textContent = match.alias;
        link.append(note);
      }
      link.addEventListener('click', (event) => { event.preventDefault(); selectMatch(index); });
      li.append(link);
      resultList.append(li);
    });
    if (normalize(search.value) && !matches.length) {
      const li = document.createElement('li');
      li.className = 'search-empty';
      li.textContent = '没有找到匹配内容。可以换个关键词或搜索范围；完整正文仍在下方。';
      resultList.append(li);
    }
    more.hidden = visibleCount >= matches.length;
    more.textContent = '再显示 ' + Math.min(8, Math.max(0, matches.length - visibleCount)) + ' 处结果';
    updatePosition();
  }

  function selectMatch(index) {
    if (!matches.length) return;
    if (current >= 0) matches[current].mark.classList.remove('is-current');
    current = (index + matches.length) % matches.length;
    const match = matches[current];
    match.mark.classList.add('is-current');
    if (current >= visibleCount) {
      visibleCount = Math.ceil((current + 1) / 8) * 8;
      renderResults();
    } else updatePosition();
    match.mark.focus({preventScroll: true});
    match.mark.scrollIntoView({block: 'center', behavior: 'auto'});
  }

  function searchPage() {
    const query = normalize(search.value);
    matches = [];
    current = -1;
    visibleCount = 8;
    fields.forEach((field) => {
      field.node.replaceChildren(document.createTextNode(field.original));
      if (!query || (scope.value !== 'all' && scope.value !== field.scope)) return;
      const ranges = keywordSearch ? (keywordSearch.ranges.get(field.node.id) || []) : textMatches(field, query);
      if (!ranges.length) return;
      const fragment = document.createDocumentFragment();
      let offset = 0;
      ranges.forEach((range) => {
        fragment.append(document.createTextNode(field.original.slice(offset, range.start)));
        const mark = document.createElement('mark');
        mark.className = 'search-hit';
        mark.id = 'search-hit-' + (matches.length + 1);
        mark.tabIndex = -1;
        mark.textContent = field.original.slice(range.start, range.end);
        fragment.append(mark);
        matches.push({...range, field, mark});
        offset = range.end;
      });
      fragment.append(document.createTextNode(field.original.slice(offset)));
      field.node.replaceChildren(fragment);
    });
    renderResults();
    // No focus, scroll, hash change, or content filtering while typing.
  }

  function clearSearch() {
    search.value = '';
    keywordSearch = null;
    searchPage();
  }
  search.addEventListener('input', () => { keywordSearch = null; searchPage(); });
  scope.addEventListener('change', () => { keywordSearch = null; searchPage(); });
  document.querySelectorAll('.keyword-word').forEach((button) => {
    button.addEventListener('click', () => {
      const ranges = new Map();
      let targets;
      try { targets = JSON.parse(button.dataset.keywordMatches); } catch (error) { return; }
      if (!Array.isArray(targets)) return;
      targets.forEach((target) => {
        const field = fieldsById.get(target.field);
        if (!field || field.scope !== 'sources' || !field.node.closest('.message-text') || !Number.isInteger(target.start) || !Number.isInteger(target.end) ||
            target.start < 0 || target.end > field.original.length || target.end <= target.start) return;
        const approved = field.aliases.find((alias) => alias.start === target.start && alias.end === target.end &&
          normalize(alias.canonical) === normalize(button.dataset.keyword));
        if (!ranges.has(target.field)) ranges.set(target.field, []);
        ranges.get(target.field).push({start: target.start, end: target.end,
          alias: approved ? '原文 ' + approved.original + ' · 已确认指 ' + approved.canonical : ''});
      });
      if (!ranges.size) return;
      keywordSearch = {ranges, messageCount: Number(button.dataset.messageCount)};
      search.value = button.dataset.keyword;
      scope.value = 'sources';
      searchPage();
      selectMatch(0);
    });
  });
  find('#search-clear').addEventListener('click', () => { clearSearch(); search.focus({preventScroll: true}); });
  previous.addEventListener('click', () => { selectMatch(current < 0 ? matches.length - 1 : current - 1); });
  next.addEventListener('click', () => { selectMatch(current + 1); });
  floatingPrevious.addEventListener('click', () => { selectMatch(current - 1); });
  floatingNext.addEventListener('click', () => { selectMatch(current + 1); });
  search.addEventListener('keydown', (event) => {
    if (event.key === 'Enter' && !event.isComposing) {
      event.preventDefault();
      selectMatch(event.shiftKey ? (current < 0 ? matches.length - 1 : current - 1) : current + 1);
    }
  });
  document.addEventListener('keydown', (event) => {
    if (event.key === 'Escape' && search.value) { event.preventDefault(); clearSearch(); }
    if (event.key === 'Enter' && !event.isComposing && event.target.closest('.search-hit')) {
      event.preventDefault();
      selectMatch(current + (event.shiftKey ? -1 : 1));
    }
  });
  more.addEventListener('click', () => { visibleCount += 8; renderResults(); });
  returnButton.addEventListener('click', () => {
    const link = resultList.querySelector('[data-match-index="' + current + '"]');
    resultList.scrollIntoView({block: 'start', behavior: 'auto'});
    (link || resultList).focus({preventScroll: true});
  });

  const revealSource = () => {
    if (!/^#msg-\d{4,}$/.test(window.location.hash)) return;
    const target = document.getElementById(window.location.hash.slice(1));
    if (target) target.scrollIntoView({block: 'start'});
  };
  window.addEventListener('hashchange', revealSource);
  revealSource();

  const actionText = () => {
    const actions = items.filter((item) => item.querySelector('.action-meta'));
    return actions.map((item, index) => {
      const read = (selector) => item.querySelector(selector).textContent.trim();
      const refs = Array.from(item.querySelectorAll('.source-link')).map((link) => link.textContent.trim());
      const evidence = refs.length ? refs.join('；') : read('.empty-evidence');
      return (index + 1) + '. ' + read('.item-title') + '\n类型：' + read('.item-kind') + '\n' + read('.item-body') +
        '\n负责人：' + read('.owner') + '\n截止时间：' + read('.due') +
        '\n状态：' + read('.status') + '\n聊天依据：' + evidence;
    }).join('\n\n');
  };
  find('#copy-actions')?.addEventListener('click', async () => {
    const text = actionText();
    if (!text) { notify('本次没有可复制的行动或建议'); return; }
    try {
      if (navigator.clipboard && navigator.clipboard.writeText) {
        await navigator.clipboard.writeText(text);
        notify('行动与建议清单已复制');
        return;
      }
    } catch (error) { /* File pages may not allow the Clipboard API. */ }
    const area = find('#copy-content');
    area.value = text;
    const dialog = find('#copy-dialog');
    if (typeof dialog.showModal === 'function') dialog.showModal();
    else dialog.setAttribute('open', '');
    area.focus();
    area.select();
  });
  find('#close-copy-dialog').addEventListener('click', () => {
    const dialog = find('#copy-dialog');
    if (typeof dialog.close === 'function') dialog.close();
    else dialog.removeAttribute('open');
  });
  find('#print-report').addEventListener('click', () => { window.print(); });
})();
