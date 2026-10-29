'use strict';
/* Take One: pick complete written takes and watch the document assemble. */
(function () {
  const $ = (selector, root = document) => root.querySelector(selector);
  const $$ = (selector, root = document) => [...root.querySelectorAll(selector)];
  const esc = (value) => String(value ?? '').replace(/[&<>"']/g, (c) => ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;' }[c]));
  const pad = (value) => String(value).padStart(2, '0');
  const TONES = ['#c9b8ff', '#f0a36b', '#7fd6b2', '#8fb8ff', '#f2c46b', '#e7a0c8'];
  const SWIPE_KEY = 'tessera-swipe';
  const STUDIO_KEY = 'intent-studio-session';
  const reduced = () => window.matchMedia('(prefers-reduced-motion: reduce)').matches;

  const S = {
    sid: null, view: null, task: null, blocks: [], samples: [],
    started: false, busy: false, navLock: false,
    section: 0, cursor: [], picks: {}, keeps: [],
    finished: false, preview: null, shiftHeld: false, endedHint: false
  };

  async function api(url, body) {
    const options = body === undefined
      ? { cache: 'no-store' }
      : { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify(body) };
    const response = await fetch(url, options);
    const value = await response.json().catch(() => ({}));
    if (!response.ok) throw new Error(value.error || '请求没有完成');
    return value;
  }

  function fill(template, facts) {
    return String(template).replace(/\{\{(.*?)\}\}/g, (_, key) => facts[key] ?? '{{' + key + '}}');
  }

  function stored() {
    try {
      const value = JSON.parse(localStorage.getItem(SWIPE_KEY) || 'null');
      return value && typeof value === 'object' ? value : null;
    } catch { return null; }
  }

  function remember(patch) {
    try { localStorage.setItem(SWIPE_KEY, JSON.stringify(patch)); } catch {}
  }

  function snapshot() {
    return {
      sid: S.sid, title: S.task?.title || '', blocks: S.blocks.length,
      section: S.section, cursor: S.cursor, picks: S.picks, keeps: S.keeps,
      finished: S.finished, ts: Date.now()
    };
  }

  function saveProgress() {
    if (!S.sid) return;
    remember(snapshot());
  }

  function toast(message) {
    const node = $('#toast');
    node.textContent = message;
    node.classList.add('show');
    clearTimeout(toast.timer);
    toast.timer = setTimeout(() => node.classList.remove('show'), 3200);
  }

  function markSeen() {
    $('#hint')?.classList.add('seen');
  }

  function toneFor(index) {
    return TONES[Math.abs(index) % TONES.length];
  }

  function setTone() {
    $('#app').style.setProperty('--tone', toneFor(S.section));
  }

  /* ---------- start ---------- */

  function renderStart() {
    const previous = stored();
    const picked = previous?.picks ? Object.keys(previous.picks).length : 0;
    const total = Number(previous?.blocks) || 4;
    const resume = previous?.sid
      ? `<button class="resume" type="button" data-resume>
          <span><b>继续《${esc(previous.title || '上一份稿件')}》</b><small>${previous.finished ? '上次已看完成稿' : `停在第 ${Number(previous.section || 0) + 1} 段 · 已留下 ${picked} 段`}</small></span>
          <span class="resume-progress" aria-hidden="true">${Array.from({ length: Math.min(total, 8) }, (_, i) => `<i class="${i < picked ? 'on' : ''}"></i>`).join('')}</span>
        </button>`
      : '';
    $('#start-actions').innerHTML = resume + '<a class="self-link" href="/studio">没有合适的？回工作室，从自己的想法开始 <span aria-hidden="true">↗</span></a><a class="self-link" href="/chat">不想挑？直接对话，一句话就做 <span aria-hidden="true">↗</span></a>';

    const shelf = $('#shelf');
    if (!S.samples.length) {
      shelf.innerHTML = '<p class="shelf-empty">示例没有读到。可以先回工作室，从自己的想法开始。</p>';
      $('#shelf-count').textContent = '—';
      return;
    }
    shelf.innerHTML = S.samples.map((sample, index) => {
      const blocks = Number(sample.blocks) || 4;
      const variants = Number(sample.variants) || 3;
      return `<button class="shelf-card" type="button" data-sample="${esc(sample.id)}">
        <span class="shelf-top"><span class="shelf-cat"><i></i>${esc(sample.category || '示例')}</span><span class="shelf-takes">${blocks} 段 · ${blocks * variants} 条</span></span>
        <span class="shelf-title">${esc(sample.title)}</span>
        <span class="shelf-brief">${esc(sample.brief || '每段都有完整的写法，挑完自动拼成一篇。')}</span>
        <span class="shelf-cta">开始挑 <span aria-hidden="true">↗</span></span>
      </button>`;
    }).join('');
    const first = S.samples[0];
    $('#shelf-count').textContent = `${S.samples.length} 组 · 每组 ${Number(first.blocks) || 4} 段 × ${Number(first.variants) || 3} 条`;
    $('#app').dataset.screen = 'start';
    $('#undo').hidden = true;
  }

  function setStartBusy(busy) {
    $('#app').classList.toggle('starting', busy);
    $$('#start-actions button, #shelf button').forEach((button) => { button.disabled = busy; });
  }

  async function startSample(sample) {
    setStartBusy(true);
    try {
      const created = await api('/api/sessions', { sample });
      const view = await api('/api/sessions/' + created.id);
      begin(created.id, view, null);
    } catch (error) {
      toast(error.message);
      setStartBusy(false);
    }
  }

  async function resume() {
    const previous = stored();
    if (!previous?.sid) return;
    setStartBusy(true);
    try {
      const view = await api('/api/sessions/' + previous.sid);
      begin(previous.sid, view, previous);
    } catch {
      try { localStorage.removeItem(SWIPE_KEY); } catch {}
      setStartBusy(false);
      renderStart();
      toast('上次的进度读不到了，重新挑一组开始。');
    }
  }

  function begin(sid, view, saved) {
    const task = view?.task;
    if (!task || !Array.isArray(task.blocks) || !task.blocks.length) {
      toast('这份任务没有可挑选的段落。');
      setStartBusy(false);
      return false;
    }
    const selectable = task.blocks.filter((block) => !block.fixed);
    if (!selectable.length) {
      toast('这份任务只有固定条件，没有可挑选的段落；可以直接在工作室查看。');
      setStartBusy(false);
      return false;
    }
    const clean = saved && saved.sid === sid ? saved : null;
    S.sid = sid;
    S.view = view;
    S.task = task;
    S.blocks = selectable;
    S.started = true;
    S.busy = false;
    S.navLock = false;
    S.finished = false;
    S.picks = clean?.picks && typeof clean.picks === 'object' ? { ...clean.picks } : {};
    S.keeps = Array.isArray(clean?.keeps) ? clean.keeps.filter((keep) => keep && keep.block && keep.variant) : [];
    S.cursor = S.blocks.map((block, index) => {
      const value = Number(clean?.cursor?.[index]);
      return Number.isFinite(value) ? Math.min(Math.max(0, value), block.variants.length - 1) : 0;
    });
    const section = Number(clean?.section);
    S.section = Number.isFinite(section) ? Math.min(Math.max(0, section), S.blocks.length - 1) : 0;
    S.endedHint = false;
    syncPicks();
    $('#task-name').textContent = task.title;
    $('#doc-rail-title').textContent = task.title;
    $('#start').hidden = true;
    $('#final').hidden = true;
    $('#compose').hidden = false;
    $('#app').dataset.screen = 'compose';
    $('#undo').hidden = false;
    $('#app').classList.remove('starting');
    try { localStorage.setItem(STUDIO_KEY, sid); } catch {}
    paintAll();
    if (clean?.finished && complete()) {
      showFinal();
    } else {
      $('#paper').classList.add('entering');
      void $('#paper').offsetWidth;
      $('#paper').classList.remove('entering');
      focusStage();
    }
    return true;
  }

  /* ---------- data ---------- */

  function syncPicks() {
    const combo = S.view?.state?.combo || {};
    Object.keys(S.picks).forEach((block) => {
      if (!S.blocks.some((item) => item.id === block) || combo[block] !== S.picks[block]) delete S.picks[block];
    });
    S.keeps = S.keeps.filter((keep) => S.picks[keep.block] === keep.variant);
  }

  function currentTake() {
    const block = S.blocks[S.section];
    const index = Math.min(Math.max(0, S.cursor[S.section] ?? 0), block.variants.length - 1);
    const variant = block.variants[index];
    return { block, variant, index, text: fill(variant.template, S.task.facts || {}) };
  }

  function variantText(block, variantId) {
    const variant = block.variants.find((item) => item.id === variantId) || block.variants[0];
    return fill(variant.template, S.task.facts || {});
  }

  function sections(combo) {
    const map = combo || S.view?.state?.combo || {};
    return S.blocks.map((block) => {
      const variant = block.variants.find((item) => item.id === map[block.id]) || block.variants[0];
      return { block, variant, text: fill(variant.template, S.task.facts || {}), picked: S.picks[block.id] === variant.id };
    });
  }

  function complete() {
    return S.blocks.length > 0 && S.blocks.every((block) => Boolean(S.picks[block.id]));
  }

  function cursorFor(section) {
    const block = S.blocks[section];
    const variantId = S.picks[block.id] || S.view.state.combo[block.id];
    const index = block.variants.findIndex((item) => item.id === variantId);
    return index >= 0 ? index : 0;
  }

  function nextUnpicked(from) {
    for (let step = 1; step <= S.blocks.length; step += 1) {
      const index = (from + step) % S.blocks.length;
      if (!S.picks[S.blocks[index].id]) return index;
    }
    return from;
  }

  /* ---------- painting ---------- */

  function paintAll() {
    if (!S.view) return;
    paintStage();
    paintRail();
    paintButtons();
    saveProgress();
  }

  function paintStage() {
    const { block, variant, index, text } = currentTake();
    const total = block.variants.length;
    setTone();
    $('#task-name').textContent = S.task.title;
    $('#doc-rail-title').textContent = S.task.title;
    $('#section-index').textContent = pad(S.section + 1);
    $('#section-kicker').textContent = `第 ${S.section + 1} 段 · 共 ${S.blocks.length} 段`;
    $('#section-title').textContent = block.title;
    $('#take-count').textContent = index + 1;
    const counterTotal = $('.take-count-total');
    if (counterTotal) counterTotal.textContent = ' / ' + total;
    $('#take-style').textContent = variant.style || `版本 ${index + 1}`;
    $('#paper-index').textContent = `${pad(index + 1)} / ${pad(total)}`;
    const body = $('#take-text');
    body.textContent = text;
    body.scrollTop = 0;
    const paper = $('#paper');
    paper.classList.toggle('long', text.length > 80 && text.length <= 150);
    paper.classList.toggle('xlong', text.length > 150);
    const chars = [...text.replace(/\s+/g, '')].length;
    $('#paper-source').textContent = `第 ${S.section + 1} / ${S.blocks.length} 段 · 约 ${chars} 字`;

    const dots = $('#take-dots');
    dots.innerHTML = block.variants.map((_, i) => `<i class="${i === index ? 'on' : ''}"></i>`).join('');
  }

  function paintRail() {
    const rows = sections();
    $('#doc-count').textContent = `${Object.keys(S.picks).length} / ${S.blocks.length}`;
    $('#doc-slots').innerHTML = rows.map((row, index) => {
      const picked = Boolean(S.picks[row.block.id]);
      return `<button class="doc-slot${picked ? ' filled' : ''}${index === S.section ? ' current' : ''}" type="button" data-slot="${esc(row.block.id)}" data-slot-index="${index}" title="跳到第 ${index + 1} 段">
        <span class="slot-index">${pad(index + 1)}</span>
        <span class="slot-body"><span class="slot-title">${esc(row.block.title)}</span><span class="slot-text">${esc(row.text)}</span></span>
        <span class="slot-state">${picked ? '已留下' : '未挑'}</span>
      </button>`;
    }).join('');
  }

  function paintButtons() {
    const off = S.busy;
    ['#keep', '#prev', '#next', '#try', '#doc-expand', '#finish-early', '#finish-mobile'].forEach((id) => {
      const el = $(id);
      if (el) el.disabled = off;
    });
    $('#undo').disabled = off || !S.keeps.length;
    $('#keep').setAttribute('aria-label', `留下第 ${S.section + 1} 段的这一条`);
  }

  /* ---------- navigation ---------- */

  function focusStage() {
    $('#deck')?.focus({ preventScroll: true });
  }

  function navigate(delta) {
    if (!S.started || S.busy || S.navLock || S.finished || S.preview) return;
    focusStage();
    let section = S.section;
    let take = S.cursor[section] + delta;
    if (take < 0) {
      if (section === 0) { bounce(); return; }
      section -= 1;
      take = S.cursor[section];
    } else if (take >= S.blocks[section].variants.length) {
      if (section === S.blocks.length - 1) { endHint(); bounce(); return; }
      section += 1;
      take = S.cursor[section];
    }
    markSeen();
    const paper = $('#paper');
    const direction = delta > 0 ? 'up' : 'down';
    S.navLock = true;
    paper.classList.add('leaving-' + direction);
    const apply = () => {
      S.section = section;
      S.cursor[section] = take;
      paintAll();
      paper.classList.remove('leaving-up', 'leaving-down');
      paper.classList.add('entering');
      void paper.offsetWidth;
      paper.classList.remove('entering');
      setTimeout(() => { S.navLock = false; }, reduced() ? 0 : 150);
    };
    if (reduced()) { apply(); return; }
    setTimeout(apply, 170);
  }

  function jumpTo(section) {
    if (!S.started || S.busy || S.navLock || S.finished) return;
    if (S.preview) closePreview();
    focusStage();
    S.section = Math.min(Math.max(0, section), S.blocks.length - 1);
    S.cursor[S.section] = cursorFor(S.section);
    paintAll();
  }

  function bounce() {
    if (reduced()) return;
    $('#paper').animate([
      { transform: 'translateY(0)' },
      { transform: 'translateY(-7px)' },
      { transform: 'translateY(0)' }
    ], { duration: 300, easing: 'cubic-bezier(.22,1,.36,1)' });
  }

  function endHint() {
    if (S.endedHint) return;
    S.endedHint = true;
    toast('已经到最后一条了。空格留下，或点右侧「就这样，看完成稿」。');
  }

  function shake() {
    if (reduced()) return;
    $('#paper').animate([
      { transform: 'translateX(0)' },
      { transform: 'translateX(-6px)' },
      { transform: 'translateX(5px)' },
      { transform: 'translateX(0)' }
    ], { duration: 320, easing: 'ease-in-out' });
  }

  /* ---------- actions ---------- */

  async function act(body) {
    await api(`/api/sessions/${S.sid}/action`, body);
    return api(`/api/sessions/${S.sid}`);
  }

  async function keep() {
    if (!S.started || S.busy || S.finished || S.preview) return;
    focusStage();
    const { block, variant, index } = currentTake();
    if (S.picks[block.id] === variant.id) {
      toast('这一段已经留下这条了。');
      if (complete()) showFinal();
      return;
    }
    S.busy = true;
    paintButtons();
    try {
      const view = await act({ revision: S.view.revision, kind: 'select', block: block.id, variant: variant.id });
      const fromRect = $('#paper').getBoundingClientRect();
      const flying = $('#paper').cloneNode(true);
      const flightTone = toneFor(S.section);
      S.view = view;
      S.picks[block.id] = variant.id;
      S.keeps.push({ block: block.id, variant: variant.id, section: S.section, take: index });
      syncPicks();
      const done = complete();
      if (!done) {
        const target = nextUnpicked(S.section);
        S.section = target;
        S.cursor[target] = cursorFor(target);
      }
      paintAll();
      const kept = block.title;
      toast(`已留下「${kept}」这一段。`);
      requestAnimationFrame(() => flyToRail(flying, fromRect, block.id, flightTone));
      markSeen();
      if (done) setTimeout(showFinal, 820);
    } catch (error) {
      await recover(error);
    } finally {
      S.busy = false;
      paintButtons();
      focusStage();
    }
  }

  async function undo() {
    if (!S.started || S.busy) return;
    if (S.preview) closePreview();
    const last = S.keeps[S.keeps.length - 1];
    if (!last) {
      toast('还没有留下可以撤回的段落。');
      return;
    }
    S.busy = true;
    paintButtons();
    try {
      const view = await act({ revision: S.view.revision, kind: 'undo' });
      S.view = view;
      S.keeps.pop();
      delete S.picks[last.block];
      syncPicks();
      S.finished = false;
      $('#final').hidden = true;
      $('#compose').hidden = false;
      $('#app').dataset.screen = 'compose';
      S.section = Math.min(Math.max(0, last.section ?? 0), S.blocks.length - 1);
      S.cursor[S.section] = Math.min(Math.max(0, last.take ?? 0), S.blocks[S.section].variants.length - 1);
      paintAll();
      toast('已撤回上一次留下。');
      focusStage();
    } catch (error) {
      await recover(error);
    } finally {
      S.busy = false;
      paintButtons();
    }
  }

  async function recover(error) {
    toast(error.message || '操作没有完成');
    shake();
    if (!S.sid) return;
    if (/更新|重新载入|过期/.test(error.message || '')) {
      try {
        S.view = await api('/api/sessions/' + S.sid);
        syncPicks();
        paintAll();
      } catch {}
    }
  }

  function flyToRail(source, fromRect, blockId, flightTone) {
    const slot = $$('.doc-slot').find((node) => node.dataset.slot === blockId);
    if (!slot || reduced() || !source) {
      pulseSlot(slot);
      return;
    }
    slot.scrollIntoView({ block: 'nearest' });
    const toRect = slot.getBoundingClientRect();
    const clone = source;
    clone.removeAttribute('id');
    $$('[id]', clone).forEach((node) => node.removeAttribute('id'));
    clone.querySelectorAll('.paper-tone, .take-text, .paper-meta, .paper-foot').forEach((node) => { node.style.transition = 'none'; });
    clone.classList.add('paper-fly');
    const width = fromRect.width;
    const height = fromRect.height;
    clone.style.cssText = `position:fixed;left:${fromRect.left}px;top:${fromRect.top}px;width:${width}px;height:${height}px;margin:0;z-index:60;pointer-events:none;transform-origin:top left;transition:none;`;
    clone.style.setProperty('--tone', flightTone);
    document.body.appendChild(clone);
    const scaleX = Math.max(0.16, (toRect.width - 10) / width);
    const scaleY = Math.max(0.12, (toRect.height - 8) / height);
    const dx = toRect.left + 5 - fromRect.left;
    const dy = toRect.top + 4 - fromRect.top;
    const animation = clone.animate([
      { transform: 'translate(0,0) scale(1,1)', opacity: 1, filter: 'blur(0)', borderRadius: '20px' },
      { transform: `translate(${dx}px,${dy}px) scale(${scaleX},${scaleY})`, opacity: 0.05, filter: 'blur(1.4px)', borderRadius: '12px' }
    ], { duration: 620, easing: 'cubic-bezier(.22,1,.36,1)' });
    const cleanup = () => clone.remove();
    animation.onfinish = cleanup;
    setTimeout(cleanup, 1000);
    pulseSlot(slot);
  }

  function pulseSlot(slot) {
    if (!slot) return;
    slot.classList.add('receiving');
    setTimeout(() => slot.classList.remove('receiving'), 820);
  }

  /* ---------- preview ---------- */

  function openPreview(kind = 'candidate', mode = 'pin') {
    if (!S.started || S.busy || S.finished) return;
    if (S.preview) {
      if (mode === 'pin') {
        S.preview.mode = 'pin';
        paintTry();
        renderPreview();
      }
      return;
    }
    S.preview = { kind, mode };
    $('#preview').hidden = false;
    paintTry();
    renderPreview();
    if (mode === 'pin' && !reduced()) {
      requestAnimationFrame(() => $('.preview-close')?.focus({ preventScroll: true }));
    }
  }

  function closePreview() {
    if (!S.preview) return;
    S.preview = null;
    $('#preview').hidden = true;
    paintTry();
    focusStage();
  }

  function paintTry() {
    const pinned = S.preview?.mode === 'pin';
    $('#try').classList.toggle('pressed', pinned);
    $('#try').setAttribute('aria-pressed', String(pinned));
  }

  function renderPreview() {
    if (!S.preview) return;
    const { block, variant } = currentTake();
    const candidateMode = S.preview.kind === 'candidate';
    const combo = candidateMode
      ? { ...S.view.state.combo, [block.id]: variant.id }
      : { ...S.view.state.combo };
    const rows = sections(combo);
    $('#preview').style.setProperty('--tone', toneFor(S.section));
    const kicker = $('#preview-kicker');
    const lead = $('#preview-lead');
    if (kicker && lead) {
      if (candidateMode) {
        kicker.textContent = S.preview.mode === 'pin' ? '试穿 · 整篇预览' : '试穿 · 还没留下';
        lead.textContent = '这一条拼进去，整篇会变成这样。';
      } else {
        kicker.textContent = '整篇 · 当前组合';
        lead.textContent = '这是目前拼出来的样子；没在这里挑的段落沿用当前组合。';
      }
    }
    $('#preview-doc').innerHTML = rows.map((row, index) => {
      const isCandidate = candidateMode && row.block.id === block.id;
      const pending = !row.picked && !isCandidate;
      return `<section class="preview-section${isCandidate ? ' candidate' : ''}${pending ? ' pending' : ''}">
        <div class="preview-section-head"><span class="preview-number">${pad(index + 1)}</span><b>${esc(row.block.title)}</b>${isCandidate ? '<span class="candidate-badge">正在看</span>' : ''}</div>
        <p class="preview-text">${esc(row.text)}</p>
      </section>`;
    }).join('');
    const candidate = $('#preview-doc .preview-section.candidate');
    if (candidate) requestAnimationFrame(() => { candidate.scrollIntoView({ block: 'center' }); });
    else $('#preview-doc').scrollTop = 0;
  }

  /* ---------- final ---------- */

  function showFinal() {
    if (!S.started || !S.view) return;
    if (S.preview) closePreview();
    S.finished = true;
    renderFinal();
    $('#compose').hidden = true;
    $('#final').hidden = false;
    $('#app').dataset.screen = 'final';
    $('#final').scrollTop = 0;
    $('#doc-rail').scrollTop = 0;
    try { localStorage.setItem(STUDIO_KEY, S.sid); } catch {}
    saveProgress();
    paintButtons();
  }

  function renderFinal() {
    const rows = sections();
    const picked = Object.keys(S.picks).length;
    const total = S.blocks.length;
    const feasible = Number(S.view.feasible_count) || null;
    const meta = [`${total} 段`, `${picked} 段来自这里的明确选择`];
    if (picked < total) meta.push(`${total - picked} 段沿用当前组合`);
    if (feasible) meta.push(`共 ${feasible} 种可行组合`);
    if (S.task.blocks.some((block) => block.fixed)) meta.push(`${Object.keys(S.task.facts || {}).length} 项固定条件已保留`);
    $('#final-meta').textContent = meta.join(' · ');
    const trace = [
      `<span><b>组合</b> ${total} 段 · ${feasible ? feasible + ' 种可行' : '任务内可行组合'}</span>`,
      `<span><b>留下</b> ${picked} 段</span>`,
      `<span><b>其余</b> ${total - picked} 段沿用当前组合</span>`,
      '<span><b>记录</b> 只写入本地任务，不是偏好训练标签</span>'
    ].join('');
    $('#final-paper').innerHTML =
      `<h2 class="final-title">${esc(S.task.title)}</h2>
       <p class="final-sub">${esc(S.task.brief || '逐段挑出的文本成稿。')}</p>
       <div class="final-sections">${rows.map((row, index) => {
         const chosen = Boolean(S.picks[row.block.id]) && S.picks[row.block.id] === row.variant.id;
         return `<section class="final-section${chosen ? '' : ' default'}">
           <div class="final-section-head"><span class="final-number">${pad(index + 1)}</span><h2>${esc(row.block.title)}</h2><span class="final-tag${chosen ? '' : ' default'}">${chosen ? '明确留下' : '当前组合'}</span></div>
           <p class="final-text">${esc(row.text)}</p>
         </section>`;
       }).join('')}</div>
       <div class="final-trace">${trace}</div>`;
  }

  function finalText() {
    return sections().map((row) => row.text).join('\n\n');
  }

  async function copyFinal() {
    const text = finalText();
    let ok = false;
    try {
      await navigator.clipboard.writeText(text);
      ok = true;
    } catch {
      const area = document.createElement('textarea');
      area.value = text;
      area.style.cssText = 'position:fixed;left:-9999px;top:0';
      document.body.appendChild(area);
      area.select();
      try { ok = document.execCommand('copy'); } catch {}
      area.remove();
    }
    const button = $('#final-copy');
    if (ok) {
      toast('正文已复制到剪贴板。');
      button.textContent = '已复制 ✓';
      setTimeout(() => { button.textContent = '复制全文'; }, 1800);
    } else {
      toast('复制没有成功；可以进工作室导出。');
    }
  }

  function backToCompose() {
    if (!S.started) return;
    S.finished = false;
    $('#final').hidden = true;
    $('#compose').hidden = false;
    $('#app').dataset.screen = 'compose';
    const target = complete() ? S.section : nextUnpicked(S.section);
    S.section = target;
    S.cursor[target] = cursorFor(target);
    paintAll();
    focusStage();
  }

  /* ---------- why ---------- */

  function openWhy() {
    if (!S.view) return;
    const takes = S.blocks.reduce((sum, block) => sum + block.variants.length, 0);
    const picked = Object.keys(S.picks).length;
    $('#why-body').innerHTML =
      `<p>这里每一条都来自同一个任务：<b>${esc(S.task.title)}</b>。它被拆成 ${S.blocks.length} 段，每段都是完整的写法，不是截断预览。</p>
       <div class="why-grid">
         <div><b>${S.blocks.length}</b><span>个段落</span></div>
         <div><b>${takes}</b><span>条完整写法</span></div>
         <div><b>${S.view.feasible_count}</b><span>种可行组合</span></div>
         <div><b>${picked}</b><span>已留下</span></div>
       </div>
       <p><b>滚轮 / ↑↓</b> 只是翻看；<b>空格</b> 才会留下，写入本地任务记录，产生一次可撤回的选择实验记录。</p>
       <p><b>Shift</b> 是试穿：把当前这条临时拼进整篇，松开就恢复；不写入任何内容，也不会变成偏好标签。</p>
       <p>组合与可行性由程序按你的选择计算，这里不调用模型。示例内容为演示数据，事实、用途与验收仍需你自己核对。</p>
       <p>任务里的固定条件不参与挑选，也不会重复出现在正文里；它们保留在任务记录中。任何能拆成“段落 × 多种完整写法”的任务都能这样挑；想要一句话直接出稿，可以走直接对话；网站作品请到网页工作室。</p>`;
    if (!$('#why-dialog').open) $('#why-dialog').showModal();
  }

  /* ---------- wiring ---------- */

  function wire() {
    $('#shelf').addEventListener('click', (event) => {
      const sample = event.target.closest('[data-sample]');
      if (sample && !sample.disabled) startSample(sample.dataset.sample);
    });

    $('#start-actions').addEventListener('click', (event) => {
      if (event.target.closest('[data-resume]')) resume();
    });

    $('#undo').addEventListener('click', undo);
    $('#prev').addEventListener('click', () => navigate(-1));
    $('#next').addEventListener('click', () => navigate(1));
    $('#keep').addEventListener('click', keep);
    $('#try').addEventListener('click', () => {
      if (S.preview) closePreview();
      else openPreview('candidate', 'pin');
    });
    $('#why').addEventListener('click', openWhy);
    $('#doc-slots').addEventListener('click', (event) => {
      const slot = event.target.closest('[data-slot]');
      if (slot) jumpTo(Number(slot.dataset.slotIndex));
    });
    $('#doc-expand').addEventListener('click', () => openPreview('document', 'pin'));
    $('#finish-early').addEventListener('click', showFinal);
    $('#finish-mobile').addEventListener('click', showFinal);
    $('#final-copy').addEventListener('click', copyFinal);
    $('#final-back').addEventListener('click', backToCompose);

    $('#preview').addEventListener('click', (event) => {
      if (event.target.closest('[data-preview-close]')) closePreview();
    });
    $('#why-dialog').addEventListener('click', (event) => {
      if (event.target.closest('[data-close]') || event.target === $('#why-dialog')) $('#why-dialog').close();
    });
    $('#why-dialog').addEventListener('close', () => {
      if (S.started) focusStage();
    });

    let wheelTotal = 0;
    let wheelAt = 0;
    let wheelSeen = 0;
    $('#deck').addEventListener('wheel', (event) => {
      if (!S.started || S.busy || S.navLock || S.finished || S.preview) return;
      const raw = Math.abs(event.deltaY) >= Math.abs(event.deltaX) ? event.deltaY : event.deltaX;
      const delta = event.deltaMode === 1 ? raw * 16 : raw;
      if (!delta) return;
      const body = $('#take-text');
      const scrollable = body.scrollHeight > body.clientHeight + 2;
      const atTop = body.scrollTop <= 0;
      const atBottom = body.scrollTop + body.clientHeight >= body.scrollHeight - 2;
      if (scrollable && ((delta > 0 && !atBottom) || (delta < 0 && !atTop))) return;
      event.preventDefault();
      const now = performance.now();
      if (now - wheelSeen > 240) wheelTotal = 0;
      wheelSeen = now;
      if (now - wheelAt < 300) return;
      wheelTotal += delta;
      if (Math.abs(wheelTotal) < 28) return;
      wheelAt = now;
      wheelTotal = 0;
      navigate(delta > 0 ? 1 : -1);
    }, { passive: false });

    document.addEventListener('keydown', (event) => {
      if (!S.started) return;
      if ($('#why-dialog').open) return;
      if (event.key === 'Shift') {
        if (!S.shiftHeld) {
          S.shiftHeld = true;
          if (!S.busy && !S.finished && !S.preview) openPreview('candidate', 'hold');
        }
        return;
      }
      if (event.key === 'Escape') {
        if (S.preview) { closePreview(); event.preventDefault(); }
        return;
      }
      if (S.preview) return;
      const tag = event.target?.tagName;
      if (tag === 'INPUT' || tag === 'TEXTAREA' || event.target?.isContentEditable) return;
      const onControl = event.target?.closest?.('button,a,summary');
      if ((event.code === 'Space' || event.key === 'Enter') && onControl) return;
      if (event.key === 'z' || event.key === 'Z') { event.preventDefault(); undo(); return; }
      if (S.finished) return;
      if (event.key === 'ArrowDown' || event.key === 'ArrowRight' || event.key === 'PageDown') { event.preventDefault(); navigate(1); }
      else if (event.key === 'ArrowUp' || event.key === 'ArrowLeft' || event.key === 'PageUp') { event.preventDefault(); navigate(-1); }
      else if (event.code === 'Space' || event.key === 'Enter') { event.preventDefault(); keep(); }
    });

    document.addEventListener('keyup', (event) => {
      if (event.key === 'Shift') {
        S.shiftHeld = false;
        if (S.preview?.mode === 'hold') closePreview();
      }
    });

    window.addEventListener('blur', () => {
      S.shiftHeld = false;
      if (S.preview?.mode === 'hold') closePreview();
    });
  }

  async function loadSamples() {
    try {
      const data = await api('/api/sessions');
      S.samples = Array.isArray(data.samples) ? data.samples : [];
    } catch (error) {
      toast('示例读取失败：' + error.message);
    }
  }

  async function boot() {
    wire();
    let linked = null;
    try { linked = new URLSearchParams(location.search).get('sid'); } catch {}
    if (linked) {
      try {
        const view = await api('/api/sessions/' + linked);
        const saved = stored();
        if (begin(linked, view, saved && saved.sid === linked ? saved : null)) {
          loadSamples();
          return;
        }
      } catch (error) {
        toast('这份任务读不到，先挑一组示例：' + error.message);
      }
    }
    await loadSamples();
    renderStart();
  }

  boot();
})();
