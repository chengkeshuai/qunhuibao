'use strict';
// Real DOM behavior with generated HTML, no browser or network access.
const {test} = require('node:test');
const assert = require('node:assert/strict');
const {spawnSync} = require('node:child_process');
const path = require('node:path');
const {JSDOM, VirtualConsole} = require('jsdom');

function fixture() {
  const messages = {
    schema_version: 1, conversation: '合成演示群', coverage: '2026-11-06', warnings: [],
    messages: [
      {id: 'm1', sender: '小林', timestamp: '2026-11-06T11:07:00+08:00', text: '🎬我用 Chat put 剪口播，剪辑后再调整。', attachments: []},
      {id: 'm2', sender: '小周', timestamp: '2026-11-06T11:08:00+08:00', text: '剪辑工具 ChatCut 可以测试。', attachments: []},
      {id: 'm3', sender: '小林', timestamp: '2026-11-06T11:09:00+08:00', text: '今天讨论 100 条切片，首次 50 条。', attachments: []},
      {id: 'm4', sender: '小满', timestamp: '', text: '代码示例 <img src=x onerror="window.injected=true"> 保留为文字。', attachments: []},
    ],
  };
  const report = {
    schema_version: 1, source_digest: 'synthetic', title: '合成演示报告', summary: '检验阅读与搜索体验。',
    conversation: messages.conversation, period: '2026-11-06', sections: [
      {key: 'topics', title: '主题', items: [{title: '剪辑方法', body: '剪辑可以先生成草稿。ChatCut 用于口播。', kind: 'fact', evidence_refs: ['m1','m2']}]},
      {key: 'decisions', title: '口径', items: []},
      {key: 'actions', title: '建议跟进', items: [{title: '核对切片条件', body: '先确认100条的交付要求。', kind: 'suggestion', evidence_refs: ['m3']}]},
      {key: 'assets', title: '工具', items: []},
      {key: 'questions', title: '待确认', items: []},
    ],
  };
  return {report, messages};
}

function openFixture(data = fixture()) {
  const result = spawnSync('python', ['-c',
    'import json,sys; from qunhuibao.renderer import render_html; d=json.load(sys.stdin); sys.stdout.write(render_html(d["report"],d["messages"]))'], {
    cwd: path.resolve(__dirname, '..'), input: JSON.stringify(data), encoding: 'utf8',
    env: {...process.env, PYTHONUTF8: '1'}, maxBuffer: 4 * 1024 * 1024,
  });
  assert.equal(result.status, 0, result.stderr);
  const errors = [], scrolls = [], copied = [];
  const virtualConsole = new VirtualConsole();
  virtualConsole.on('jsdomError', error => errors.push(error));
  const dom = new JSDOM(result.stdout, {
    runScripts: 'dangerously', virtualConsole,
    // Deliberately no resource loader: external resources cannot be fetched.
    beforeParse(window) {
      window.HTMLElement.prototype.scrollIntoView = function () { scrolls.push(this); };
      window.scrollTo = () => {};
      Object.defineProperty(window.navigator, 'clipboard', {value: {writeText: async text => copied.push(text)}});
    },
  });
  const {window} = dom;
  const document = window.document;
  function search(query, scope = 'all') {
    const select = document.querySelector('#search-scope');
    assert.ok(select, 'A report/original/all search scope control exists');
    select.value = scope;
    select.dispatchEvent(new window.Event('change', {bubbles: true}));
    const input = document.querySelector('#report-search');
    input.value = query;
    input.dispatchEvent(new window.Event('input', {bubbles: true}));
  }
  function click(selector) {
    const target = document.querySelector(selector);
    assert.ok(target, selector);
    target.click();
  }
  return {dom, window, document, errors, scrolls, copied, search, click};
}

test('source text is directly readable and technical details are secondary', () => {
  const ui = openFixture();
  try {
    const message = ui.document.querySelector('#msg-0001');
    assert.ok(message);
    const paragraph = message.querySelector('.message-text');
    assert.ok(paragraph.textContent.includes('Chat put'));
    for (let el = paragraph; el; el = el.parentElement) {
      assert.equal(el.hidden, false);
      if (el.tagName === 'DETAILS') assert.equal(el.open, true, 'message body cannot start inside closed details');
    }
    assert.ok(message.textContent.includes('11:07'));
    assert.deepEqual(ui.errors, []);
  } finally { ui.dom.window.close(); }
});

test('search includes original text, does not move while typing, and clicks locate exact matches', () => {
  const ui = openFixture();
  try {
    ui.search('剪辑', 'sources');
    assert.equal(ui.scrolls.length, 0, 'typing must not move the reading position');
    const results = ui.document.querySelectorAll('#search-results .search-result-link');
    assert.ok(results.length >= 2);
    results[0].click();
    const selected = ui.document.querySelector('mark.search-hit.is-current');
    assert.ok(selected, 'click selects a visible highlighted match');
    assert.equal(selected.textContent, '剪辑');
    assert.equal(selected.closest('.source-message').id, 'msg-0001');
    assert.ok(ui.scrolls.length > 0);
    assert.ok(ui.document.querySelector('#search-position').textContent.includes('1'));
    assert.equal(ui.document.querySelector('#search-floating').hidden, false);
    assert.equal(ui.document.querySelector('#search-floating-position').textContent, '1 / ' + results.length);
    ui.click('#search-next');
    assert.notEqual(ui.document.querySelector('mark.search-hit.is-current'), selected);
    assert.equal(ui.document.querySelector('#search-floating-position').textContent, '2 / ' + results.length);
    ui.click('#search-prev');
    assert.equal(ui.document.querySelector('mark.search-hit.is-current'), selected);
    ui.click('#search-floating-next');
    assert.notEqual(ui.document.querySelector('mark.search-hit.is-current'), selected);
    ui.click('#search-floating-prev');
    assert.equal(ui.document.querySelector('mark.search-hit.is-current'), selected);
    ui.click('#return-to-search');
    assert.ok(ui.scrolls.length >= 4);
    assert.deepEqual(ui.errors, []);
  } finally { ui.dom.window.close(); }
});

test('fullwidth, case, and spaces normalize; approved aliases locate original wording', () => {
  const ui = openFixture();
  try {
    ui.search('  cＨＡＴ   cUT  ', 'sources');
    assert.ok([...ui.document.querySelectorAll('#msg-0001 mark.search-hit')].some(m => m.textContent === 'Chat put'));
    assert.ok([...ui.document.querySelectorAll('#msg-0002 mark.search-hit')].some(m => m.textContent === 'ChatCut'));
    ui.search('Chat put', 'sources');
    assert.ok(ui.document.querySelector('#msg-0002 mark.search-hit'), 'a known typo also locates the canonical spelling');
    ui.search('100条', 'sources');
    assert.ok([...ui.document.querySelectorAll('#msg-0003 mark.search-hit')].some(m => m.textContent === '100 条'));
    assert.deepEqual(ui.errors, []);
  } finally { ui.dom.window.close(); }
});

test('alias rules do not merge an unrelated English phrase into a product', () => {
  const data = fixture();
  data.messages.messages = [{id: 'm1', sender: '小林', timestamp: '', text: 'English exercise: please chat put this in the box.', attachments: []}];
  data.report.sections = [{key: 'topics', title: '英文练习', items: [{title: '课堂笔记', body: '普通英文句子。', kind: 'fact', evidence_refs: ['m1']}]}];
  const ui = openFixture(data);
  try {
    ui.search('ChatCut', 'sources');
    assert.equal(ui.document.querySelectorAll('mark.search-hit').length, 0);
    assert.equal(ui.document.querySelector('#search-floating').hidden, true);
    assert.equal(ui.document.querySelectorAll('#search-results .search-result-link').length, 0);
    assert.deepEqual(ui.errors, []);
  } finally { ui.dom.window.close(); }
});

test('quoted messages stay readable and searchable after metadata is organized', () => {
  const data = fixture();
  data.messages.messages.push({id: 'm5', sender: '小周', timestamp: '2026-11-06T11:10:00+08:00',
    text: '我也试一下。\n引用消息 ID：m1\n引用发言人：小林\n引用内容：🎬我用 Chat put 做视频剪辑。', attachments: []});
  const ui = openFixture(data);
  try {
    const reply = ui.document.querySelector('#msg-0005');
    assert.ok(reply.textContent.includes('我也试一下。'));
    assert.ok(reply.textContent.includes('我用 Chat put 做视频剪辑。'));
    ui.search('ChatCut', 'sources');
    assert.ok([...reply.querySelectorAll('mark.search-hit')].some(m => m.textContent === 'Chat put'));
    for (const mark of reply.querySelectorAll('mark.search-hit')) {
      for (let el = mark; el; el = el.parentElement) {
        if (el.tagName === 'DETAILS') assert.equal(el.open, true);
      }
    }
    assert.deepEqual(ui.errors, []);
  } finally { ui.dom.window.close(); }
});

test('keyboard navigation, scope, and clear restore the complete readable page', () => {
  const ui = openFixture();
  try {
    ui.search('剪辑', 'report');
    assert.equal(ui.document.querySelectorAll('.source-message mark.search-hit').length, 0);
    const input = ui.document.querySelector('#report-search');
    input.dispatchEvent(new ui.window.KeyboardEvent('keydown', {key: 'Enter', bubbles: true}));
    const first = ui.document.querySelector('mark.search-hit.is-current');
    assert.ok(first);
    input.dispatchEvent(new ui.window.KeyboardEvent('keydown', {key: 'Enter', bubbles: true}));
    assert.notEqual(ui.document.querySelector('mark.search-hit.is-current'), first);
    input.dispatchEvent(new ui.window.KeyboardEvent('keydown', {key: 'Enter', shiftKey: true, bubbles: true}));
    assert.equal(ui.document.querySelector('mark.search-hit.is-current'), first);
    input.dispatchEvent(new ui.window.KeyboardEvent('keydown', {key: 'Escape', bubbles: true}));
    assert.equal(input.value, '');
    assert.equal(ui.document.querySelectorAll('mark.search-hit').length, 0);
    assert.equal(ui.document.querySelectorAll('.source-message').length, 4);
    assert.equal(ui.document.querySelectorAll('.source-message[hidden], .report-item[hidden]').length, 0);
    ui.search('100条');
    ui.click('#search-clear');
    assert.equal(input.value, '');
    assert.equal(ui.document.querySelectorAll('mark.search-hit').length, 0);
    assert.deepEqual(ui.errors, []);
  } finally { ui.dom.window.close(); }
});

test('highlighting literal HTML cannot create elements or execute chat text', () => {
  const ui = openFixture();
  try {
    ui.search('<img src=x onerror="window.injected=true">', 'sources');
    assert.ok(ui.document.querySelector('#msg-0004 mark.search-hit'));
    assert.equal(ui.document.querySelectorAll('img').length, 1, 'only the trusted embedded logo exists');
    assert.equal(ui.window.injected, undefined);
    ui.click('#search-clear');
    assert.ok(ui.document.querySelector('#msg-0004').textContent.includes('<img src=x'));
    assert.deepEqual(ui.errors, []);
  } finally { ui.dom.window.close(); }
});

test('results paginate without hiding source context, and copy keeps suggestions unassigned', async () => {
  const data = fixture();
  for (let i = 5; i < 22; i++) data.messages.messages.push({id: 'm'+i, sender: '演示成员', timestamp: '', text: '剪辑测试消息 '+i, attachments: []});
  const ui = openFixture(data);
  try {
    ui.search('剪辑', 'sources');
    const initial = ui.document.querySelectorAll('#search-results .search-result-link').length;
    const total = ui.document.querySelectorAll('mark.search-hit').length;
    assert.ok(initial > 0 && initial < total);
    ui.click('#search-more');
    assert.ok(ui.document.querySelectorAll('#search-results .search-result-link').length > initial);
    assert.equal(ui.document.querySelectorAll('.source-message[hidden]').length, 0);
    ui.click('#copy-actions');
    await Promise.resolve();
    assert.ok(ui.copied[0].includes('未认领'));
    assert.ok(ui.copied[0].includes('AI 建议'));
    assert.deepEqual(ui.errors, []);
  } finally { ui.dom.window.close(); }
});

test('topic cloud counts unique bodies and uses exact grounded search positions', () => {
  const data = fixture();
  data.report.keywords = ['ChatCut', '剪辑'];
  data.messages.messages.push({id: 'm5', sender: '小赵', timestamp: '',
    text: '收到。\n引用消息 ID：m1\n引用发言人：小林\n引用内容：ChatCut 可以剪辑。', attachments: []});
  const ui = openFixture(data);
  try {
    const word = ui.document.querySelector('.keyword-word[data-keyword="ChatCut"]');
    assert.ok(word);
    assert.equal(word.dataset.messageCount, '2');
    word.click();
    assert.equal(ui.document.querySelector('#report-search').value, 'ChatCut');
    assert.equal(ui.document.querySelector('#search-scope').value, 'sources');
    const first = ui.document.querySelector('mark.search-hit.is-current');
    assert.equal(first.textContent, 'Chat put');
    assert.equal(first.closest('.source-message').id, 'msg-0001');
    assert.equal(ui.document.querySelectorAll('#msg-0005 mark.search-hit').length, 0, 'reply quotation is not part of the topic count');
    assert.ok(ui.document.querySelector('#search-position').textContent.includes('2 条消息'));
    ui.click('#search-floating-next');
    assert.equal(ui.document.querySelector('mark.is-current').closest('.source-message').id, 'msg-0002');
    ui.click('#return-to-search');
    assert.equal(ui.document.querySelector('#search-keyword-note').hidden, false);
    assert.ok(ui.document.querySelector('#search-keyword-note a[href="#topic-cloud"]'));
    ui.search('ChatCut', 'sources');
    assert.ok(ui.document.querySelector('#msg-0005 mark.search-hit'), 'typing starts an unrestricted original-text search again');
    assert.equal(ui.document.querySelector('#search-keyword-note').hidden, true);
    assert.deepEqual(ui.errors, []);
  } finally { ui.dom.window.close(); }
});

test('keyword labels and ranges are text data even for literal markup', () => {
  const data = fixture();
  data.report.keywords = ['<img>'];
  data.messages.messages[0].text = '示例 <img> 作为文字。';
  const ui = openFixture(data);
  try {
    const word = ui.document.querySelector('.keyword-word');
    assert.equal(word.dataset.keyword, '<img>');
    word.click();
    assert.equal(ui.document.querySelector('mark.is-current').textContent, '<img>');
    assert.equal(ui.document.querySelectorAll('img').length, 1);
    assert.deepEqual(ui.errors, []);
  } finally { ui.dom.window.close(); }
});
