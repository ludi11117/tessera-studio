'use strict';
const $ = (selector, root = document) => root.querySelector(selector);
const esc = value => String(value ?? '').replace(/[&<>"']/g, c => ({'&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;'}[c]));
const short = value => value ? String(value).slice(0, 12) : '—';
const codePoints = value => Array.from(value);
const cpSlice = (value, start, end) => codePoints(value).slice(start, end).join('');
const cpInsert = (value, index, text) => {
  const chars = codePoints(value);
  return chars.slice(0, index).join('') + text + chars.slice(index).join('');
};
const fmtTime = value => {
  if (!value) return '—';
  const date = new Date(value);
  return isNaN(date) ? String(value) : date.toLocaleString('zh-CN', {hour12: false});
};
const S = {chain: null, ledger: [], solver: null, preview: null, receipt: null, solverToken: 0};

async function api(path, body) {
  const init = body === undefined ? {} : {method: 'POST', headers: {'Content-Type': 'application/json'}, body: JSON.stringify(body)};
  const response = await fetch(path, init);
  const data = await response.json().catch(() => ({error: '响应不是有效 JSON'}));
  if (!response.ok) {
    const error = new Error(data.error || ('HTTP ' + response.status));
    error.status = response.status;
    error.requestId = data.request_id;
    throw error;
  }
  return data;
}

function setBusy(button, busy) {
  if (button) button.disabled = Boolean(busy);
}

function showConflict(host, error, title) {
  if (!host) return;
  host.hidden = false;
  host.innerHTML = '<strong>' + esc(title) + '</strong>HTTP ' + esc(error.status) + ' · ' + esc(error.message) +
    (error.requestId ? '<br><span class="mono">request_id ' + esc(error.requestId) + '</span>' : '');
}

function protocolStatus(text, bad = false) {
  const host = $('#protocol-status');
  host.textContent = text;
  host.classList.toggle('bad', bad);
}

function lockState(chain) {
  const block = chain.task.blocks[0];
  const locked = Boolean(block && chain.state.locks && chain.state.locks[block.id]);
  return {block, locked, title: block ? block.title : '—'};
}

function renderChain() {
  const chain = S.chain;
  if (!chain) return;
  const lock = lockState(chain);
  $('#revision-badge').textContent = '稿件 v' + chain.session.revision;
  $('#proof-session').textContent = chain.session.title + ' · ' + short(chain.session.id);
  $('#proof-revision').textContent = 'v' + chain.session.revision;
  $('#proof-lock').textContent = lock.locked ? lock.title : '未锁定';
  const toggle = $('#toggle-lock');
  toggle.textContent = lock.locked ? '解锁章节' : '锁定章节';
  toggle.dataset.kind = lock.locked ? 'unlock' : 'lock';
  $('#event-count').textContent = '按时间顺序 · ' + chain.events_total + ' 个事件 · ' + chain.active_events + ' 个有效 · ' + chain.labels + ' 个训练标签';
  $('#chain-checks').innerHTML = chain.checks.map(check =>
    '<li class="' + (check.passed ? 'ok' : 'bad') + '"><span class="check-mark" aria-hidden="true">' + (check.passed ? '✓' : '×') +
    '</span><span>' + esc(check.label) + '<br><span class="proof-label">' + esc(check.id) + '</span></span></li>').join('');
  const events = chain.events.slice(-9);
  $('#event-rows').innerHTML = events.map(event =>
    '<tr><td>' + esc(event.seq) + '</td><td><span class="tag">' + esc(event.kind) + '</span></td><td>' + esc(event.revision) +
    '</td><td>' + esc(event.summary.text) + (event.summary.training_label ? ' <span class="tag">label</span>' : '') +
    '</td><td><code class="hash">' + esc(short(event.before_hash)) + '</code></td><td><code class="hash">' + esc(short(event.after_hash)) + '</code></td></tr>'
  ).join('') || '<tr><td colspan="6">暂无事件</td></tr>';
}

function renderLedger() {
  const rows = S.ledger || [];
  $('#ledger-rows').innerHTML = rows.map(job =>
    '<tr><td><span class="tag">' + esc(job.kind) + '</span><br><code class="hash">' + esc(job.id) + '</code></td><td>' +
    esc(job.status) + (job.retry ? ' <span class="tag">retry</span>' : '') + '</td><td>' + esc(job.attempts) + ' / ' + esc(job.call_limit ?? '—') +
    '</td><td>' + esc(job.model || '—') + '<br><span class="proof-label">' + esc(job.provider || '—') + '</span></td><td><code class="hash">' +
    esc(job.input_hash) + '</code></td><td>' + esc(fmtTime(job.created)) + '</td></tr>'
  ).join('') || '<tr><td colspan="6">本次运行还没有模型作业。页面自身不会发起付费调用。</td></tr>';
}

async function loadState() {
  const state = await api('/api/proof/state');
  S.chain = state.chain;
  S.ledger = state.ledger;
  renderChain();
  renderLedger();
}

async function refreshChain() {
  const state = await api('/api/proof/state');
  S.chain = state.chain;
  S.ledger = state.ledger;
  renderChain();
  renderLedger();
}

async function submitLock(kind) {
  if (!S.chain) return;
  const revision = S.chain.session.revision;
  const button = $('#toggle-lock');
  setBusy(button, true);
  try {
    const chain = await api('/api/proof/action', {kind, revision});
    S.chain = chain;
    $('#protocol-conflict').hidden = true;
    renderChain();
    protocolStatus('提交成功：v' + revision + ' → v' + chain.session.revision + '，快照链校验仍通过。');
  } catch (error) {
    if (error.status === 409) {
      showConflict($('#protocol-conflict'), error, '旧 revision 被拒绝（真实 409）');
      protocolStatus('服务端拒绝了这次提交，正文没有变化。已重新读取当前版本。', true);
      await refreshChain().catch(() => {});
    } else {
      protocolStatus(error.message, true);
    }
  } finally {
    setBusy(button, false);
  }
}

async function staleSubmit() {
  if (!S.chain) return;
  const revision = S.chain.session.revision;
  const first = lockState(S.chain).locked ? 'unlock' : 'lock';
  const second = first === 'lock' ? 'unlock' : 'lock';
  const button = $('#stale-submit');
  setBusy(button, true);
  try {
    const chain = await api('/api/proof/action', {kind: first, revision});
    S.chain = chain;
    renderChain();
    protocolStatus('第一个窗口已用 v' + revision + ' 提交，当前是 v' + chain.session.revision + '。现在用旧版本再提交一次。');
    try {
      await api('/api/proof/action', {kind: second, revision});
      protocolStatus('异常：旧版本被接受了，请检查事务实现。', true);
    } catch (error) {
      if (error.status === 409) {
        showConflict($('#protocol-conflict'), error, '旧 revision 被拒绝（真实 409）');
        protocolStatus('并发冲突已复现：第二个请求未改动任何文字，当前仍是 v' + chain.session.revision + '。');
        await refreshChain().catch(() => {});
      } else {
        throw error;
      }
    }
  } catch (error) {
    protocolStatus(error.message, true);
  } finally {
    setBusy(button, false);
  }
}

async function resetSandbox() {
  const button = $('#reset-proof');
  setBusy(button, true);
  try {
    S.chain = await api('/api/proof/reset', {});
    $('#protocol-conflict').hidden = true;
    renderChain();
    protocolStatus('已新建一条 proof 会话；历史会话保留，正式数据库未改动。');
  } catch (error) {
    protocolStatus(error.message, true);
  } finally {
    setBusy(button, false);
  }
}

function renderSolver() {
  const report = S.solver;
  if (!report) return;
  $('#solver-metrics').innerHTML =
    '<div><span>搜索空间</span><strong>' + esc(report.universe) + '</strong></div>' +
    '<div><span>可行搭配</span><strong>' + esc(report.eligible) + '</strong></div>' +
    '<div><span>本地耗时</span><strong>' + esc(report.elapsed_ms) + ' ms</strong></div>' +
    '<div><span>条件数</span><strong>' + esc(report.constraints.length) + '</strong></div>';
  const hero = $('#hero-metrics').children;
  hero[0].querySelector('strong').textContent = report.universe;
  hero[1].querySelector('strong').textContent = report.eligible;
  hero[2].querySelector('strong').textContent = report.elapsed_ms + ' ms';
  const core = report.conflict_core || [];
  $('#solver-core').innerHTML = core.length
    ? core.map(item => '<li>' + esc(item.label) + ' <span class="proof-label">' + esc(item.kind) + '</span></li>').join('')
    : '<li class="empty">当前条件下存在 ' + esc(report.eligible) + ' 个可行搭配，无需冲突核。</li>';
  const coreIds = new Set(core.map(item => item.id));
  const outside = report.constraints.filter(item => !coreIds.has(item.id)).map(item => item.label);
  $('#solver-note').textContent = core.length
    ? '拿掉冲突核中任意一项，这组条件本身就有解。' + (outside.length ? '核外条件：' + outside.join('、') + '；它们可能单独受限，也可能被冲突核遮蔽。' : '')
    : '有解时不再寻找冲突核。';
  const corrections = report.corrections || [];
  $('#correction-count').textContent = report.correction_count + ' 组';
  $('#solver-corrections').innerHTML = corrections.length
    ? corrections.map(item => '<article class="correction"><b>放宽 ' + item.relax.length + ' 项条件</b><span>' + item.relax.map(esc).join('；') +
      '</span><span class="witness">候选 ' + esc(item.witness) + ' · 改动 ' + esc(item.witness_changes) + ' 章</span><small>' +
      (item.adoptable_under_current_conditions ? '当前条件下可采用' : '仅作为修正证据，当前仍不可采用') + '</small></article>').join('')
    : '<p class="proof-note">没有找到包含关系最小的修正集合。</p>';
  $('#solver-sensitivity').innerHTML = report.sensitivity.map(item =>
    '<li><span>' + esc(item.label) + '</span><b>+' + esc(item.newly_eligible) + ' 个</b></li>').join('');
  $('#solver-limits').textContent = (report.limits || []).join('；');
  $('#solver-fingerprint').textContent = '空间指纹 ' + report.space_hash + ' · ' + report.method + ' · 付费调用 ' + report.paid_calls + ' 次';
}

async function solve() {
  const token = ++S.solverToken;
  const max = $('#solver-max').value;
  try {
    const report = await api('/api/proof/solve', {
      lock: $('#solver-lock').checked,
      require_phrase: $('#solver-require').checked,
      max_chars: max ? Number(max) : null
    });
    if (token !== S.solverToken) return;
    S.solver = report;
    renderSolver();
  } catch (error) {
    if (token === S.solverToken) {
      $('#solver-core').innerHTML = '<li>' + esc(error.message) + '</li>';
    }
  }
}

function renderPreview(preview) {
  const range = preview.range;
  $('#splice-receipt').innerHTML =
    '<div><dt>码点区间</dt><dd>' + esc(range.start) + ' – ' + esc(range.end) + '（' + esc(range.end - range.start) + ' 字符）</dd></div>' +
    '<div><dt>UTF-16 区间</dt><dd>' + esc(range.utf16_start) + ' – ' + esc(range.utf16_end) + '（偏移差 ' + esc(range.utf16_start - range.start) + '）</dd></div>' +
    '<div><dt>选中原文</dt><dd>' + esc(cpSlice($('#splice-text').value, range.start, range.end)) + '</dd></div>' +
    '<div><dt>前缀哈希</dt><dd><code>' + esc(short(preview.prefix_hash)) + '</code></dd></div>' +
    '<div><dt>后缀哈希</dt><dd><code>' + esc(short(preview.suffix_hash)) + '</code></dd></div>' +
    '<div><dt>选区哈希</dt><dd><code>' + esc(short(preview.selection_hash)) + '</code></dd></div>';
  $('#splice-result').hidden = true;
}

async function previewSplice(quiet = false) {
  const text = $('#splice-text').value;
  const occurrence = Number($('#splice-occurrence').value);
  try {
    const preview = await api('/api/proof/splice', {mode: 'preview', text, query: '这是要替换的句子。', occurrence});
    S.preview = preview;
    S.receipt = null;
    renderPreview(preview);
    $('#splice-status').textContent = quiet
      ? '已定位第 ' + occurrence + ' 次出现：码点 ' + preview.range.start + '–' + preview.range.end + '，UTF-16 ' + preview.range.utf16_start + '–' + preview.range.utf16_end + '。'
      : '已定位第 ' + occurrence + ' 次出现：码点 ' + preview.range.start + '–' + preview.range.end +
        '，UTF-16 ' + preview.range.utf16_start + '–' + preview.range.utf16_end + '。' +
        (preview.range.utf16_start !== preview.range.start ? 'emoji 使两种下标不同。' : '');
    if (!quiet) $('#splice-conflict').hidden = true;
    return preview;
  } catch (error) {
    $('#splice-status').textContent = error.message;
    return null;
  }
}

async function applySplice(stale) {
  if (!S.preview) {
    const preview = await previewSplice();
    if (!preview) return;
  }
  const preview = S.preview;
  let text = $('#splice-text').value;
  if (stale) {
    text = cpInsert(text, preview.range.start, '（另一窗口已改动）');
  }
  const button = stale ? $('#splice-stale') : $('#splice-apply');
  setBusy(button, true);
  try {
    const receipt = await api('/api/proof/splice', {
      mode: 'apply', text,
      start: preview.range.start, end: preview.range.end,
      replacement: $('#splice-replacement').value,
      prefix_hash: preview.prefix_hash, suffix_hash: preview.suffix_hash, selection_hash: preview.selection_hash
    });
    S.receipt = receipt;
    $('#splice-conflict').hidden = true;
    $('#splice-receipt').innerHTML =
      '<div><dt>拼接状态</dt><dd>成功 · 选区外未改变 ✓</dd></div>' +
      '<div><dt>原文 / 结果</dt><dd>' + esc(receipt.before_chars) + ' → ' + esc(receipt.after_chars) + ' 字符</dd></div>' +
      '<div><dt>before 哈希</dt><dd><code>' + esc(short(receipt.before_hash)) + '</code></dd></div>' +
      '<div><dt>after 哈希</dt><dd><code>' + esc(short(receipt.after_hash)) + '</code></dd></div>' +
      '<div><dt>回执哈希</dt><dd><code>' + esc(short(receipt.receipt_hash)) + '</code></dd></div>' +
      '<div><dt>选区外一致</dt><dd>' + (receipt.outside_unchanged ? '是' : '否') + '</dd></div>';
    $('#splice-result').hidden = false;
    $('#splice-output').textContent = receipt.after;
    $('#splice-status').textContent = '服务端按码点完成拼接；前缀、后缀与选中文字哈希都匹配，替换范围之外没有变化。';
  } catch (error) {
    if (error.status === 409) {
      showConflict($('#splice-conflict'), error, stale ? '过期回执被拒绝（真实 409）' : '原文已变化，替换被拒绝');
      $('#splice-status').textContent = stale
        ? '这份回执对应旧原文；另一窗口的改动使选区哈希不再匹配，服务端拒绝覆盖。'
        : '文本框内容在上次定位后发生了变化。重新定位选区即可生成新回执。';
    } else {
      $('#splice-status').textContent = error.message;
    }
  } finally {
    setBusy(button, false);
  }
}

$('#toggle-lock').addEventListener('click', () => submitLock($('#toggle-lock').dataset.kind || 'lock'));
$('#stale-submit').addEventListener('click', staleSubmit);
$('#reset-proof').addEventListener('click', resetSandbox);
for (const id of ['solver-lock', 'solver-require', 'solver-max']) {
  $('#' + id).addEventListener('change', solve);
}
$('#splice-preview').addEventListener('click', () => previewSplice());
$('#splice-occurrence').addEventListener('change', () => previewSplice());
$('#splice-apply').addEventListener('click', () => applySplice(false));
$('#splice-stale').addEventListener('click', () => applySplice(true));

(async function boot() {
  const results = await Promise.allSettled([loadState(), solve(), previewSplice(true)]);
  const failed = results.find(result => result.status === 'rejected');
  if (failed) {
    protocolStatus('本地服务读取失败：' + failed.reason.message, true);
  } else {
    protocolStatus('沙盒已读取；所有操作都是真实的本地提交。');
  }
})();
