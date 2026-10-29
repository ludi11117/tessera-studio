'use strict';
/* Direct chat: one input, no setup. First message generates, later messages revise. */
(function () {
  const $ = (selector, root = document) => root.querySelector(selector);
  const esc = (value) => String(value ?? '').replace(/[&<>"']/g, (c) => ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;' }[c]));
  const pad = (value) => String(value).padStart(2, '0');
  const KEY = 'tessera-chat-v1';
  const STUDIO_KEY = 'intent-studio-session';
  const reduced = () => window.matchMedia('(prefers-reduced-motion: reduce)').matches;

  const S = { sid: null, view: null, messages: [], pending: null, busy: false, activeJob: null };

  async function api(url, body) {
    const options = body === undefined
      ? { cache: 'no-store' }
      : { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify(body) };
    const response = await fetch(url, options);
    const value = await response.json().catch(() => ({}));
    if (!response.ok) {
      const error = new Error(value.error || '请求没有完成');
      error.status = response.status;
      throw error;
    }
    return value;
  }

  function fill(template, facts) {
    return String(template).replace(/\{\{(.*?)\}\}/g, (_, key) => facts[key] ?? '{{' + key + '}}');
  }

  function load() {
    try {
      const value = JSON.parse(localStorage.getItem(KEY) || 'null');
      return value && typeof value === 'object' ? value : null;
    } catch { return null; }
  }

  function persist() {
    try {
      const messages = S.messages.slice(-40);
      localStorage.setItem(KEY, JSON.stringify({ sid: S.sid, messages, pending: S.pending, ts: Date.now() }));
      if (S.sid) localStorage.setItem(STUDIO_KEY, S.sid);
    } catch {}
  }

  function toast(message) {
    const node = $('#toast');
    node.textContent = message;
    node.classList.add('show');
    clearTimeout(toast.timer);
    toast.timer = setTimeout(() => node.classList.remove('show'), 2600);
  }

  function scrollBottom(force = true) {
    const thread = $('#thread');
    if (!force) return;
    thread.scrollTo({ top: thread.scrollHeight, behavior: reduced() ? 'auto' : 'smooth' });
  }

  /* ---------- message model ---------- */

  function uid() {
    return Math.random().toString(36).slice(2, 10) + Date.now().toString(36);
  }

  function sectionsOf(view) {
    const task = view.task;
    return task.blocks.filter((block) => !block.fixed).map((block) => {
      const variant = block.variants.find((item) => item.id === view.state.combo[block.id]) || block.variants[0];
      return { title: block.title, text: fill(variant.template, task.facts || {}) };
    });
  }

  function documentMessage(view, options = {}) {
    return {
      uid: uid(), role: 'doc', sid: S.sid, title: view.task.title,
      version: (Number(view.revision) || 0) + 1, sections: sectionsOf(view),
      collapsed: Boolean(options.collapsed), changed: options.changed || [], note: options.note || ''
    };
  }

  function sectionsHTML(message) {
    return message.sections.map((section, index) =>
      `<section class="doc-section"><h3><span>${pad(index + 1)}</span>${esc(section.title)}</h3><p class="doc-text">${esc(section.text)}</p></section>`
    ).join('');
  }

  function docHTML(message) {
    const body = `<div class="doc-body">${sectionsHTML(message)}</div>`;
    const changed = message.changed.length
      ? `<p class="doc-changes"><b>这次改了</b> ${message.changed.map(esc).join(' · ')}</p>`
      : '';
    return `<article class="doc-card">
      <div class="doc-head">
        <div><p class="doc-kicker">${message.collapsed ? '已更新 · 当前成稿' : '新成稿 · 完整初版'}</p><h2 class="doc-title">${esc(message.title)}</h2></div>
        <span class="doc-version">v${message.version}</span>
      </div>
      ${changed}
      ${message.collapsed
        ? `<details class="doc-details"><summary>查看完整成稿 · ${message.sections.length} 段</summary>${body}</details>`
        : body}
      <div class="doc-foot">
        <button class="doc-btn" type="button" data-copy="${message.uid}">复制全文</button>
        <a class="doc-btn primary" href="/studio?sid=${encodeURIComponent(message.sid)}">进工作室继续改 ↗</a>
        <p class="doc-note">已保存在本地任务${message.note ? ' · ' + esc(message.note) : ''}。事实、用途与验收仍需你核对。</p>
      </div>
    </article>`;
  }

  function messageHTML(message) {
    if (message.role === 'user') {
      return `<div class="msg user"><div class="bubble">${esc(message.text)}</div></div>`;
    }
    if (message.role === 'doc') {
      return `<div class="msg assistant">${docHTML(message)}</div>`;
    }
    const setup = message.setup ? '<a class="inline-link" href="/studio">去工作室连接模型 ↗</a>' : '';
    return `<div class="msg ${message.role === 'error' ? 'error' : 'assistant'}"><div class="bubble">${esc(message.text)}${setup}</div></div>`;
  }

  function removeProgress(node) {
    if (node && node.isConnected) node.remove();
  }

  function push(message) {
    S.messages.push(message);
    if (S.messages.length > 40) {
      S.messages = S.messages.slice(-40);
      renderAll();
    } else {
      $('#messages').insertAdjacentHTML('beforeend', messageHTML(message));
    }
    $('#empty').hidden = true;
    persist();
    scrollBottom();
  }

  function renderAll() {
    $('#messages').innerHTML = S.messages.map(messageHTML).join('');
    $('#empty').hidden = S.messages.length > 0;
  }

  function progressNode(text) {
    const node = document.createElement('div');
    node.className = 'msg assistant';
    node.innerHTML = `<div class="progress"><span class="pulse" aria-hidden="true"><i></i><i></i><i></i></span><span class="progress-text">${esc(text)}</span><button type="button" class="cancel" data-cancel>取消</button></div>`;
    node.querySelector('[data-cancel]').addEventListener('click', cancelActive);
    $('#messages').append(node);
    $('#empty').hidden = true;
    scrollBottom();
    return node;
  }

  function setProgress(node, text) {
    const label = node?.querySelector('.progress-text');
    if (label && text) label.textContent = text;
  }

  /* ---------- jobs ---------- */

  const sleep = (ms) => new Promise((resolve) => setTimeout(resolve, ms));

  async function waitJob(jid, node) {
    for (;;) {
      const job = await api('/api/ai/jobs/' + jid);
      if (job.progress) setProgress(node, job.progress);
      if (['completed', 'error', 'cancelled', 'interrupted'].includes(job.status)) return job;
      await sleep(850);
    }
  }

  async function cancelActive() {
    if (!S.activeJob) { toast('任务还在提交，请稍候。'); return; }
    try {
      await api(`/api/ai/jobs/${S.activeJob}/cancel`, {});
      toast('已取消；成稿没有改动。');
    } catch (error) {
      toast(error.message);
    }
  }

  function jobError(job) {
    if (job.status === 'cancelled') return new Error('已取消；成稿没有改动。');
    if (job.status === 'interrupted') return new Error(job.error || '任务被本机服务中断；成稿没有改动。');
    return new Error(job.error || 'AI 任务没有完成，现有内容未改动。请重试。');
  }

  function fail(error) {
    const text = String(error?.message || '没有完成');
    const setup = /AI设置|API Key|API密钥|选择模型|模型接口|连接/.test(text);
    push({ uid: uid(), role: 'error', text, setup });
  }

  function setBusy(busy, label) {
    S.busy = busy;
    $('#send').disabled = busy;
    $('#new-chat').disabled = busy;
    $('#status').textContent = busy ? (label || '处理中…') : 'Enter 发送 · Shift+Enter 换行';
  }

  async function submitJob(path, body) {
    const job = await api(path, { ...body, request_id: crypto.randomUUID() });
    S.pending = { id: job.id, kind: path.includes('generate') ? 'generate' : 'revise' };
    S.activeJob = job.id;
    persist();
    return job;
  }

  /* ---------- generation ---------- */

  async function generate(goal) {
    setBusy(true, '正在生成…');
    const node = progressNode('正在理解你的目标…');
    try {
      const job = await submitJob('/api/ai/generate', { goal });
      const done = await waitJob(job.id, node);
      S.pending = null;
      persist();
      if (done.status !== 'completed') throw jobError(done);
      await finishGenerate(done);
    } catch (error) {
      fail(error);
    } finally {
      S.activeJob = null;
      S.pending = null;
      removeProgress(node);
      setBusy(false);
      persist();
    }
  }

  async function finishGenerate(job) {
    const sid = job.result?.session_id;
    if (!sid) throw new Error('生成结束但没有拿到成稿，请重新发送一次。');
    S.sid = sid;
    const view = await api('/api/sessions/' + sid);
    S.view = view;
    try { localStorage.setItem(STUDIO_KEY, sid); } catch {}
    if (!S.messages.some((message) => message.role === 'doc' && message.sid === sid)) {
      push({ uid: uid(), role: 'assistant', text: '这是第一版。哪一段不顺手，直接说，我改那一部分。' });
      push(documentMessage(view));
    }
  }

  /* ---------- revision ---------- */

  async function revise(instruction) {
    setBusy(true, '正在修改…');
    const node = progressNode('正在按你的要求修改…');
    try {
      const job = await submitJob(`/api/sessions/${S.sid}/ai/revise`, { revision: S.view.revision, instruction, scope: null });
      const done = await waitJob(job.id, node);
      S.pending = null;
      persist();
      if (done.status !== 'completed') throw jobError(done);
      await finishRevise(done);
    } catch (error) {
      if (error.status === 409) {
        try { S.view = await api('/api/sessions/' + S.sid); } catch {}
        fail(new Error('成稿在另一个窗口更新了，已刷新到最新版本。请再说一次要改哪里。'));
      } else {
        fail(error);
      }
    } finally {
      S.activeJob = null;
      S.pending = null;
      removeProgress(node);
      setBusy(false);
      persist();
    }
  }

  async function finishRevise(job) {
    const result = job.result || {};
    if (result.applied) {
      S.view = await api('/api/sessions/' + S.sid);
      push({ uid: uid(), role: 'assistant', text: result.summary || '这次修改已采用。' });
      push(documentMessage(S.view, { collapsed: true, changed: (result.diffs || []).map((diff) => diff.title), note: '修改已采用' }));
      return;
    }
    if (!result.can_apply) {
      const text = [result.summary, result.validation_message || '这次草案没有通过约束检查，成稿没有改动。'].filter(Boolean).join('\n\n');
      push({ uid: uid(), role: 'assistant', text });
      return;
    }
    const base = Number.isInteger(result.base_revision) ? result.base_revision : S.view.revision;
    await api(`/api/ai/jobs/${job.id}/apply`, { revision: base });
    S.view = await api('/api/sessions/' + S.sid);
    push({ uid: uid(), role: 'assistant', text: result.summary || '改好了。' });
    push(documentMessage(S.view, { collapsed: true, changed: (result.diffs || []).map((diff) => diff.title), note: '未提到的部分保持原样' }));
  }

  /* ---------- boot ---------- */

  async function resume(pending, node) {
    setBusy(true, '正在继续上次的任务…');
    try {
      const done = await waitJob(pending.id, node);
      S.pending = null;
      persist();
      if (done.status !== 'completed') throw jobError(done);
      if (pending.kind === 'generate') await finishGenerate(done);
      else {
        if (done.result?.session_id && !S.sid) S.sid = done.result.session_id;
        if (!S.sid) throw new Error('上次的成稿找不到了，请重新发送任务。');
        await finishRevise(done);
      }
    } catch (error) {
      fail(error);
    } finally {
      S.activeJob = null;
      S.pending = null;
      removeProgress(node);
      setBusy(false);
      persist();
    }
  }

  async function boot() {
    wire();
    const saved = load();
    if (saved) {
      S.sid = saved.sid || null;
      S.messages = Array.isArray(saved.messages) ? saved.messages : [];
      S.pending = saved.pending && saved.pending.id ? saved.pending : null;
    }
    renderAll();
    if (S.sid) {
      try {
        S.view = await api('/api/sessions/' + S.sid);
        if (!S.messages.some((message) => message.role === 'doc' && message.sid === S.sid)) {
          push({ uid: uid(), role: 'assistant', text: '继续上次的会话。接着说要改哪里，改动会直接落在这份成稿上。' });
          push(documentMessage(S.view, { collapsed: true }));
        }
      } catch {
        S.sid = null;
        S.view = null;
        if (S.messages.length) push({ uid: uid(), role: 'assistant', text: '上次的会话在本机找不到了；接着说一句新的需求，会重新开始一份成稿。' });
      }
    }
    if (S.pending) {
      const node = progressNode('正在继续上次的任务…');
      resume(S.pending, node);
    }
  }

  /* ---------- wiring ---------- */

  function resize() {
    const input = $('#input');
    input.style.height = 'auto';
    input.style.height = Math.min(input.scrollHeight, 150) + 'px';
  }

  async function copyText(text) {
    try {
      await navigator.clipboard.writeText(text);
      return true;
    } catch {
      const area = document.createElement('textarea');
      area.value = text;
      area.style.cssText = 'position:fixed;left:-9999px;top:0';
      document.body.appendChild(area);
      area.select();
      let ok = false;
      try { ok = document.execCommand('copy'); } catch {}
      area.remove();
      return ok;
    }
  }

  function wire() {
    $('#composer').addEventListener('submit', (event) => {
      event.preventDefault();
      const input = $('#input');
      const text = input.value.trim();
      if (!text || S.busy) return;
      if (!S.sid && text.length < 5) { toast('再多说一句：你想要什么成果？'); return; }
      if (S.sid && text.length < 2) { toast('说一下要改哪里。'); return; }
      if (S.sid && text.length > 3000) { toast('修改要求最多 3000 字。'); return; }
      input.value = '';
      resize();
      push({ uid: uid(), role: 'user', text });
      if (!S.sid) generate(text);
      else revise(text);
    });

    $('#chips').addEventListener('click', (event) => {
      const chip = event.target.closest('[data-prompt]');
      if (!chip) return;
      const input = $('#input');
      input.value = chip.dataset.prompt;
      resize();
      input.focus();
      toast('按 Enter 发送，或再加一点自己的情况。');
    });

    document.addEventListener('click', (event) => {
      const button = event.target.closest('[data-copy]');
      if (!button) return;
      const message = S.messages.find((item) => item.uid === button.dataset.copy);
      if (!message) return;
      copyText(message.sections.map((section) => section.text).join('\n\n')).then((ok) => {
        toast(ok ? '正文已复制到剪贴板。' : '复制没有成功，可以进工作室导出。');
        if (!ok) return;
        const label = button.textContent;
        button.textContent = '已复制 ✓';
        setTimeout(() => { button.textContent = label; }, 1600);
      });
    });

    $('#input').addEventListener('input', resize);
    let composing = false;
    $('#input').addEventListener('compositionstart', () => { composing = true; });
    $('#input').addEventListener('compositionend', () => { composing = false; });
    $('#input').addEventListener('keydown', (event) => {
      if (event.key === 'Enter' && !event.shiftKey && !composing) {
        event.preventDefault();
        $('#composer').requestSubmit();
      }
    });

    $('#new-chat').addEventListener('click', () => {
      if (S.busy) { toast('等当前任务结束，或先点取消。'); return; }
      S.sid = null;
      S.view = null;
      S.pending = null;
      S.messages = [];
      try {
        localStorage.removeItem(KEY);
        localStorage.removeItem(STUDIO_KEY);
      } catch {}
      $('#messages').replaceChildren();
      $('#empty').hidden = false;
      $('#thread').scrollTop = 0;
      $('#input').focus();
      toast('已开新对话；上一份稿子还在工作室里。');
    });
  }

  boot();
})();
