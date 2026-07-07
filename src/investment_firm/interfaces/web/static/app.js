/**
 * Investment Committee — Web UI
 * Plain JS, no build, no CDN deps.
 * XSS note: all model-generated text is inserted via textContent or createElement.
 *            Never pass API data to innerHTML.
 */

'use strict';

// ── Constants ────────────────────────────────────────────────────────────

const POLL_INTERVAL_MS = 3000;

// ── Helpers ──────────────────────────────────────────────────────────────

async function fetchJson(url, opts) {
  const resp = await fetch(url, opts);
  if (!resp.ok) {
    const data = await resp.json().catch(() => ({ detail: resp.statusText }));
    const err = new Error(data.detail || `HTTP ${resp.status}`);
    err.status = resp.status;
    throw err;
  }
  return resp.json();
}

function tierBadge(tier) {
  const cls = {
    WORKER: 'badge--worker',
    SENIOR: 'badge--senior',
    AUTHORITY: 'badge--authority',
    HEAD: 'badge--head',
  }[tier] || 'badge--worker';
  const span = document.createElement('span');
  span.className = `badge ${cls}`;
  span.textContent = tier;
  return span;
}

function stanceBadge(stance) {
  const cls = {
    BULLISH: 'badge--bullish',
    BEARISH: 'badge--bearish',
    NEUTRAL: 'badge--neutral-stance',
    ERROR: 'badge--error',
  }[stance] || 'badge--neutral-stance';
  const span = document.createElement('span');
  span.className = `badge ${cls}`;
  span.textContent = stance;
  return span;
}

function recBadge(rec) {
  const cls = {
    BUY:   'badge--buy',
    SELL:  'badge--sell',
    HOLD:  'badge--hold',
    AVOID: 'badge--avoid',
    ERROR: 'badge--error',
  }[rec] || 'badge--hold';
  const span = document.createElement('span');
  span.className = `badge badge--rec ${cls}`;
  span.textContent = rec;
  return span;
}

function el(tag, cls, text) {
  const node = document.createElement(tag);
  if (cls) node.className = cls;
  if (text !== undefined) node.textContent = text;
  return node;
}

// Safe multi-line text block (preserves newlines via pre-wrap CSS)
function textBlock(text, cls) {
  const p = document.createElement('p');
  if (cls) p.className = cls;
  p.textContent = text;
  return p;
}

// Safe link: anchor only for http(s) URLs, plain span otherwise. Never innerHTML.
function linkNode(url, label) {
  const text = label || url;
  if (typeof url === 'string' && /^https?:\/\//i.test(url)) {
    const a = document.createElement('a');
    a.href = url;
    a.textContent = text;
    a.target = '_blank';
    a.rel = 'noopener noreferrer';
    return a;
  }
  return el('span', '', text);
}

// Render a source string, linkifying any embedded http(s) URL.
function sourceItemNode(text) {
  const li = document.createElement('li');
  const match = /https?:\/\/[^\s"'<>)\]]+/.exec(String(text));
  if (!match) {
    li.textContent = text;
    return li;
  }
  const url = match[0];
  const before = String(text).slice(0, match.index);
  const after = String(text).slice(match.index + url.length);
  if (before) li.appendChild(document.createTextNode(before));
  li.appendChild(linkNode(url, url));
  if (after) li.appendChild(document.createTextNode(after));
  return li;
}

function escHtml(str) {
  return String(str)
    .replace(/&/g, '&amp;')
    .replace(/</g, '&lt;')
    .replace(/>/g, '&gt;')
    .replace(/"/g, '&quot;');
}

function formatElapsed(startMs) {
  const s = Math.floor((Date.now() - startMs) / 1000);
  const m = Math.floor(s / 60);
  const sec = s % 60;
  return m > 0 ? `${m}m ${sec}s` : `${sec}s`;
}

// ── Boot ─────────────────────────────────────────────────────────────────

async function loadHealth() {
  try {
    const data = await fetchJson('/api/health');
    const el = document.getElementById('disclaimer');
    if (el && data.disclaimer) el.textContent = data.disclaimer;
  } catch (_) { /* non-fatal */ }
}

async function loadProfiles() {
  const select = document.getElementById('profile');
  try {
    const data = await fetchJson('/api/profiles');
    const profiles = data.profiles || {};
    const names = Object.keys(profiles).sort();
    select.innerHTML = '';
    names.forEach((name) => {
      const opt = document.createElement('option');
      opt.value = name;
      opt.textContent = name;
      if (name === 'balanced') opt.selected = true;
      select.appendChild(opt);
    });
  } catch (_err) {
    select.innerHTML = '<option value="">error loading profiles</option>';
  }
}

// ── LLM backend switch ───────────────────────────────────────────────────

function updateBackendNote(data) {
  const note = document.getElementById('backend-note');
  if (!note) return;
  // All content via textContent — never innerHTML.
  note.textContent = (data && data.note) ? data.note : '';
}

async function loadBackend() {
  const select = document.getElementById('backend');
  if (!select) return;
  try {
    const data = await fetchJson('/api/backend');
    select.innerHTML = '';
    (data.available || []).forEach((name) => {
      const opt = document.createElement('option');
      opt.value = name;
      opt.textContent = name;
      if (name === data.backend) opt.selected = true;
      select.appendChild(opt);
    });
    updateBackendNote(data);
  } catch (_err) {
    select.innerHTML = '<option value="">error loading backends</option>';
  }
}

async function switchBackend(ev) {
  const select = ev.target;
  const note = document.getElementById('backend-note');
  try {
    const data = await fetchJson('/api/backend', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ backend: select.value }),
    });
    updateBackendNote(data);
  } catch (err) {
    if (note) note.textContent = `Backend switch failed: ${err.message}`;
  }
}

// ── Preview ───────────────────────────────────────────────────────────────

function renderRolesTable(roles) {
  if (!roles || roles.length === 0) {
    return el('p', 'loading', 'No roles returned.');
  }
  const table = document.createElement('table');
  table.className = 'roles-table';
  table.setAttribute('aria-label', 'Resolved roles');

  const thead = table.createTHead();
  const hrow = thead.insertRow();
  ['Role', 'Tier', 'Model', 'Mandate'].forEach((h) => {
    const th = document.createElement('th');
    th.textContent = h;
    hrow.appendChild(th);
  });

  const tbody = table.createTBody();
  roles.forEach((r) => {
    const row = tbody.insertRow();

    const nameCell = row.insertCell();
    nameCell.textContent = r.name;

    const tierCell = row.insertCell();
    tierCell.appendChild(tierBadge(r.tier));

    const modelCell = row.insertCell();
    const modelSpan = el('span', 'model-name', r.model);
    modelCell.appendChild(modelSpan);

    const mandateCell = row.insertCell();
    const mandateSpan = el('span', 'mandate-text', r.mandate);
    mandateCell.appendChild(mandateSpan);
  });

  return table;
}

function renderPreviewResult(data) {
  const wrap = document.createElement('div');

  const meta = el('div', 'result-meta');
  const budget = (data.run_token_budget || 0).toLocaleString();
  const modeLabel = data.simple ? 'simple (3 fixed analysts)' : 'full agentic';

  [[`Profile`, data.profile], [`Mode`, modeLabel],
   [`Token budget`, budget], [`Roles`, String(data.roles.length)]].forEach(([k, v]) => {
    const span = document.createElement('span');
    span.textContent = `${k}: `;
    const strong = document.createElement('strong');
    strong.textContent = v;
    span.appendChild(strong);
    meta.appendChild(span);
  });
  wrap.appendChild(meta);
  wrap.appendChild(renderRolesTable(data.roles));
  return wrap;
}

async function runPreview(e) {
  e.preventDefault();
  const result = document.getElementById('preview-result');
  result.textContent = '';
  result.appendChild(el('p', 'loading', 'Loading preview…'));

  const question = document.getElementById('question').value.trim();
  const profile  = document.getElementById('profile').value;
  const simple   = document.getElementById('simple').checked;

  const url = `/api/preview?question=${encodeURIComponent(question)}&profile=${encodeURIComponent(profile)}&simple=${simple}`;

  try {
    const data = await fetchJson(url);
    result.textContent = '';
    result.appendChild(renderPreviewResult(data));
  } catch (err) {
    result.textContent = '';
    const box = el('div', 'error-box', `Error: ${err.message}`);
    result.appendChild(box);
  }
}

// ── Run (token-spending) ──────────────────────────────────────────────────

let _pollTimer = null;
let _runStart  = null;
let _eventSource = null;
let _currentRunId = null;

function setRunBtnState(running) {
  const btn = document.getElementById('btn-run');
  btn.disabled = running;
  btn.textContent = running ? 'Running…' : 'Run (spends tokens)';
}

function showStatusBar(text, cls) {
  const bar = document.getElementById('run-status-bar');
  bar.textContent = '';
  const span = el('span', cls || 'status-info', text);
  bar.appendChild(span);
}

// ── Results rendering ─────────────────────────────────────────────────────

function renderMemoTab(result) {
  const panel = document.getElementById('tab-memo');
  panel.textContent = '';

  const header = el('div', 'memo-header');
  header.appendChild(el('span', 'memo-label', 'Recommendation: '));
  header.appendChild(recBadge(result.recommendation));
  panel.appendChild(header);

  if (result.synth_role) {
    const model = result.synth_model ? ` (${result.synth_model})` : '';
    const attribution = `Final recommendation issued by ${result.synth_role.toUpperCase()}${model}`;
    panel.appendChild(el('p', 'memo-attribution', attribution));
  }

  panel.appendChild(el('h3', 'section-title', 'Summary'));
  panel.appendChild(textBlock(result.summary, 'memo-summary'));

  if (result.question) {
    panel.appendChild(el('p', 'memo-question', `Question: ${result.question}`));
  }
}

function renderReasoningTab(result) {
  const panel = document.getElementById('tab-reasoning');
  panel.textContent = '';

  if (!result.views || result.views.length === 0) {
    panel.appendChild(el('p', 'loading', 'No analyst views available.'));
    return;
  }

  result.views.forEach((view) => {
    const card = el('div', 'analyst-card');

    // Header row
    const header = el('div', 'analyst-header');
    header.appendChild(el('span', 'analyst-role', view.role));
    header.appendChild(stanceBadge(view.stance));
    const convSpan = el('span', 'conviction-badge', `Conviction ${view.conviction}/5`);
    header.appendChild(convSpan);
    if (view.grounded === false) {
      const badge = el('span', 'badge badge--avoid', 'UNGROUNDED');
      badge.title = 'No successful tool call or web citation backed this view';
      header.appendChild(badge);
    }
    card.appendChild(header);

    // Model
    const modelLine = el('p', 'analyst-model');
    modelLine.appendChild(el('span', 'model-name', view.model));
    card.appendChild(modelLine);

    // Explicit ERROR outcome
    if (view.stance === 'ERROR') {
      card.appendChild(el('div', 'error-box', `ERROR — ${view.error || view.rationale || 'analysis step failed'}`));
    }

    // Rationale
    card.appendChild(el('h4', 'analyst-section-title', 'Rationale'));
    card.appendChild(textBlock(view.rationale || '(none)', 'analyst-rationale'));

    // Key risks
    if (view.key_risks && view.key_risks.length > 0) {
      card.appendChild(el('h4', 'analyst-section-title', 'Key Risks'));
      const ul = document.createElement('ul');
      ul.className = 'analyst-list';
      view.key_risks.forEach((r) => {
        const li = document.createElement('li');
        li.textContent = r;
        ul.appendChild(li);
      });
      card.appendChild(ul);
    }

    // Evidence
    if (view.evidence && view.evidence.length > 0) {
      card.appendChild(el('h4', 'analyst-section-title', 'Evidence'));
      const ul = document.createElement('ul');
      ul.className = 'analyst-list analyst-list--evidence';
      view.evidence.forEach((e) => {
        ul.appendChild(sourceItemNode(e));
      });
      card.appendChild(ul);
    }

    // Web sources (real search citations captured this run)
    if (view.citations && view.citations.length > 0) {
      card.appendChild(el('h4', 'analyst-section-title', 'Web Sources'));
      const ul = document.createElement('ul');
      ul.className = 'analyst-list analyst-list--evidence';
      view.citations.forEach((c) => {
        const li = document.createElement('li');
        li.appendChild(linkNode(c.url, c.title || c.url));
        if (c.origin) li.appendChild(document.createTextNode(` (${c.origin})`));
        ul.appendChild(li);
      });
      card.appendChild(ul);
    }

    panel.appendChild(card);
  });
}

function renderDebateTab(result) {
  const panel = document.getElementById('tab-debate');
  panel.textContent = '';

  const debate = result.debate || [];
  if (debate.length === 0) {
    panel.appendChild(
      el('p', 'loading', 'No debate (simple mode or max_debate_rounds is 0).')
    );
    return;
  }

  panel.appendChild(el('h3', 'section-title', 'Bull / Bear Debate'));
  debate.forEach((turn, i) => {
    const speaker = (turn.speaker || '').toLowerCase();
    const side = speaker.includes('bull')
      ? 'bull'
      : speaker.includes('bear')
      ? 'bear'
      : 'other';
    const card = el('div', `debate-turn debate-turn--${side}`);
    const speakerRow = el('div', 'debate-speaker-row');
    speakerRow.appendChild(el('span', 'debate-order', String(i + 1)));
    speakerRow.appendChild(el('span', 'debate-speaker', turn.speaker || '?'));
    card.appendChild(speakerRow);
    if (turn.model) {
      card.appendChild(el('span', 'debate-model', turn.model));
    }
    card.appendChild(textBlock(turn.text || '', 'debate-text'));
    panel.appendChild(card);
  });

  if (result.debate_summary) {
    const judge = result.debate_judge_role
      ? `Debate Verdict — ${result.debate_judge_role.toUpperCase()} as referee` +
        (result.debate_judge_model ? ` (${result.debate_judge_model})` : '')
      : 'Debate Verdict';
    panel.appendChild(el('h3', 'section-title', judge));
    panel.appendChild(textBlock(result.debate_summary, 'debate-verdict'));
  }
}

function renderBriefingTab(result) {
  const panel = document.getElementById('tab-briefing');
  panel.textContent = '';
  if (!result.briefing) {
    panel.appendChild(el('p', 'loading', 'No briefing (simple mode skips the librarian).'));
    return;
  }
  panel.appendChild(el('h3', 'section-title', 'Research Librarian Briefing Packet'));
  if (result.briefing_role) {
    const model = result.briefing_model ? ` (${result.briefing_model})` : '';
    panel.appendChild(
      el('p', 'briefing-attribution', `${result.briefing_role.toUpperCase()}${model}`)
    );
  }
  panel.appendChild(textBlock(result.briefing, 'briefing-text'));
}

function renderSourcesTab(result) {
  const panel = document.getElementById('tab-sources');
  panel.textContent = '';
  const sources = result.sources || [];
  const webSources = result.web_sources || [];
  if (sources.length === 0 && webSources.length === 0) {
    panel.appendChild(el('p', 'loading', 'No sources recorded.'));
    return;
  }
  if (webSources.length > 0) {
    panel.appendChild(el('h3', 'section-title', `Web Sources (${webSources.length})`));
    const wul = document.createElement('ul');
    wul.className = 'sources-list';
    webSources.forEach((s) => {
      const li = document.createElement('li');
      li.appendChild(linkNode(s.url, s.title || s.url));
      if (s.origin) li.appendChild(document.createTextNode(` (${s.origin})`));
      wul.appendChild(li);
    });
    panel.appendChild(wul);
  }
  if (sources.length > 0) {
    panel.appendChild(el('h3', 'section-title', `Sources (${sources.length})`));
    const ul = document.createElement('ul');
    ul.className = 'sources-list';
    sources.forEach((s) => {
      ul.appendChild(sourceItemNode(s));
    });
    panel.appendChild(ul);
  }
}

function renderCostsTab(result) {
  const panel = document.getElementById('tab-costs');
  panel.textContent = '';

  // Warnings
  if (result.warnings && result.warnings.length > 0) {
    const warnBox = el('div', 'warn-box');
    warnBox.appendChild(el('strong', '', 'Warnings'));
    const ul = document.createElement('ul');
    result.warnings.forEach((w) => {
      const li = document.createElement('li');
      li.textContent = w;
      ul.appendChild(li);
    });
    warnBox.appendChild(ul);
    panel.appendChild(warnBox);
  }

  panel.appendChild(el('h3', 'section-title', 'Cost Summary'));
  const pre = document.createElement('pre');
  pre.className = 'cost-pre';
  pre.textContent = result.cost_summary || '(none)';
  panel.appendChild(pre);
}

function renderResults(result) {
  renderMemoTab(result);
  renderReasoningTab(result);
  renderDebateTab(result);
  renderBriefingTab(result);
  renderSourcesTab(result);
  renderCostsTab(result);
  renderConsultantTab(result);
}

function renderConsultantTab(result) {
  const panel = document.getElementById('tab-consultant');
  panel.textContent = '';
  panel.appendChild(el('h3', 'section-title', 'Read-only Quant Consultant'));
  panel.appendChild(
    el(
      'p',
      'memo-question',
      'Ask about this completed run — reasoning, indicators, or a read-only backtest. ' +
        'Analysis only; the consultant cannot trade or change anything.'
    )
  );

  const controls = el('div', 'consultant-controls');
  const modelInput = document.createElement('input');
  modelInput.type = 'text';
  modelInput.id = 'consultant-model';
  modelInput.className = 'consultant-model';
  modelInput.placeholder = 'model (default claude-4.8-opus)';
  controls.appendChild(modelInput);
  panel.appendChild(controls);

  const log = el('div', 'consultant-log');
  log.id = 'consultant-log';
  panel.appendChild(log);

  const form = el('div', 'consultant-form');
  const input = document.createElement('input');
  input.type = 'text';
  input.id = 'consultant-input';
  input.className = 'consultant-input';
  input.placeholder = 'Ask the consultant…';
  const send = el('button', 'btn consultant-send', 'Send');
  send.type = 'button';

  function appendBubble(role, text) {
    const bubble = el('div', `consultant-bubble consultant-bubble--${role}`);
    bubble.appendChild(el('span', 'consultant-role', role === 'user' ? 'You' : 'Consultant'));
    bubble.appendChild(textBlock(text, 'consultant-text'));
    log.appendChild(bubble);
    log.scrollTop = log.scrollHeight;
  }

  async function sendMessage() {
    const message = input.value.trim();
    if (!message || !_currentRunId) return;
    appendBubble('user', message);
    input.value = '';
    send.disabled = true;
    try {
      const data = await fetchJson(`/api/runs/${_currentRunId}/chat`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ message, model: modelInput.value.trim() || null }),
      });
      appendBubble('assistant', data.answer || '(no answer)');
    } catch (err) {
      appendBubble('assistant', `Error: ${err.message}`);
    } finally {
      send.disabled = false;
      input.focus();
    }
  }

  send.addEventListener('click', sendMessage);
  input.addEventListener('keydown', (e) => {
    if (e.key === 'Enter') sendMessage();
  });
  form.appendChild(input);
  form.appendChild(send);
  panel.appendChild(form);
}

// ── Tab switching ─────────────────────────────────────────────────────────

function initTabs() {
  const buttons = document.querySelectorAll('.tab-btn');
  buttons.forEach((btn) => {
    btn.addEventListener('click', () => {
      const target = btn.dataset.tab;
      buttons.forEach((b) => {
        b.classList.toggle('tab-btn--active', b.dataset.tab === target);
        b.setAttribute('aria-selected', b.dataset.tab === target ? 'true' : 'false');
      });
      document.querySelectorAll('.tab-panel').forEach((panel) => {
        const isTarget = panel.id === `tab-${target}`;
        panel.classList.toggle('tab-panel--active', isTarget);
        panel.hidden = !isTarget;
      });
    });
  });
}

// ── Polling ───────────────────────────────────────────────────────────────

function stopPolling() {
  if (_pollTimer) {
    clearInterval(_pollTimer);
    _pollTimer = null;
  }
}

// ── Live step-event stream (SSE) ────────────────────────────────────

function stopEventStream() {
  if (_eventSource) {
    _eventSource.close();
    _eventSource = null;
  }
}

function _ensureFeed() {
  const panel = document.getElementById('tab-reasoning');
  let feed = document.getElementById('live-feed');
  if (!feed) {
    panel.textContent = '';
    panel.appendChild(el('h3', 'section-title', 'Live Activity'));
    feed = document.createElement('ul');
    feed.id = 'live-feed';
    feed.className = 'live-feed';
    panel.appendChild(feed);
  }
  return feed;
}

function _appendFeedLine(ev) {
  const feed = _ensureFeed();
  const li = document.createElement('li');
  li.className = 'live-feed-item';
  const who = ev.agent ? ` ${ev.agent}` : '';
  const model = ev.model ? ` (${ev.model})` : '';
  const detail = ev.detail ? ` — ${ev.detail}` : '';
  // textContent only — never innerHTML (XSS-safe).
  li.textContent = `${ev.kind}${who}${model}${detail}`.slice(0, 240);
  feed.appendChild(li);
}

function _appendLiveDebateTurn(ev) {
  const panel = document.getElementById('tab-debate');
  let wrap = document.getElementById('live-debate');
  if (!wrap) {
    panel.textContent = '';
    panel.appendChild(el('h3', 'section-title', 'Bull / Bear Debate (live)'));
    wrap = document.createElement('div');
    wrap.id = 'live-debate';
    panel.appendChild(wrap);
  }
  const speaker = (ev.agent || '').toLowerCase();
  const side = speaker.includes('bull')
    ? 'bull'
    : speaker.includes('bear')
    ? 'bear'
    : 'other';
  const card = el('div', `debate-turn debate-turn--${side}`);
  const speakerRow = el('div', 'debate-speaker-row');
  speakerRow.appendChild(el('span', 'debate-order', String(wrap.children.length + 1)));
  speakerRow.appendChild(el('span', 'debate-speaker', ev.agent || '?'));
  card.appendChild(speakerRow);
  if (ev.model) {
    card.appendChild(el('span', 'debate-model', ev.model));
  }
  card.appendChild(textBlock(ev.detail || '', 'debate-text'));
  wrap.appendChild(card);
}

function startEventStream(runId) {
  stopEventStream();
  if (typeof EventSource === 'undefined') return;
  let es;
  try {
    es = new EventSource(`/api/runs/${runId}/events`);
  } catch (err) {
    return; // polling remains the source of truth
  }
  _eventSource = es;
  es.onmessage = (msg) => {
    let ev;
    try {
      ev = JSON.parse(msg.data);
    } catch (err) {
      return;
    }
    if (!ev || !ev.kind) return;
    _appendFeedLine(ev);
    if (ev.kind === 'debate_turn') _appendLiveDebateTurn(ev);
  };
  es.addEventListener('end', () => stopEventStream());
  es.onerror = () => stopEventStream(); // fall back to the 3s poll
}

async function pollRun(runId) {
  try {
    const data = await fetchJson(`/api/runs/${runId}`);
    const elapsed = _runStart ? ` (${formatElapsed(_runStart)})` : '';

    if (data.status === 'done') {
      stopPolling();
      stopEventStream();
      setRunBtnState(false);
      showStatusBar(`Done${elapsed}`, 'status-done');
      if (data.result) {
        renderResults(data.result);
        // Switch to Memo tab
        document.querySelector('[data-tab="memo"]').click();
      }
      return;
    }

    if (data.status === 'error') {
      stopPolling();
      stopEventStream();
      setRunBtnState(false);
      showStatusBar(`Error: ${data.error || 'unknown'}`, 'status-error');
      return;
    }

    // Still running / queued
    showStatusBar(`${data.status}… ${elapsed}`, 'status-running');
  } catch (err) {
    stopPolling();
    setRunBtnState(false);
    showStatusBar(`Poll error: ${err.message}`, 'status-error');
  }
}

async function startRun() {
  const question = document.getElementById('question').value.trim();
  if (!question) {
    alert('Please enter an investment question first.');
    return;
  }

  const confirmed = window.confirm(
    'This will run the full Investment Committee pipeline, making many LLM calls ' +
    'and spending real tokens on the Deutsche Börse AI Playground.\n\n' +
    'Proceed?'
  );
  if (!confirmed) return;

  const profile = document.getElementById('profile').value;
  const simple  = document.getElementById('simple').checked;

  setRunBtnState(true);

  // Show and reset results panel
  const panel = document.getElementById('results-panel');
  panel.hidden = false;
  panel.scrollIntoView({ behavior: 'smooth', block: 'start' });

  // Reset tabs to Memo
  document.querySelectorAll('.tab-btn').forEach((b) => {
    const isMemo = b.dataset.tab === 'memo';
    b.classList.toggle('tab-btn--active', isMemo);
    b.setAttribute('aria-selected', isMemo ? 'true' : 'false');
  });
  document.querySelectorAll('.tab-panel').forEach((p) => {
    const isMemo = p.id === 'tab-memo';
    p.classList.toggle('tab-panel--active', isMemo);
    p.hidden = !isMemo;
  });
  document.getElementById('tab-memo').textContent = '';

  _runStart = Date.now();
  showStatusBar('Queuing…', 'status-running');

  try {
    const data = await fetchJson('/api/runs', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ question, profile: profile || null, simple }),
    });

    const runId = data.run_id;
    _currentRunId = runId;
    showStatusBar('queued… 0s', 'status-running');

    stopPolling();
    startEventStream(runId);
    _pollTimer = setInterval(() => pollRun(runId), POLL_INTERVAL_MS);
    // First poll immediately
    pollRun(runId);
  } catch (err) {
    setRunBtnState(false);
    showStatusBar(`Error: ${err.message}`, 'status-error');
  }
}

// ── Init ─────────────────────────────────────────────────────────────────

document.addEventListener('DOMContentLoaded', () => {
  loadHealth();
  loadBackend();
  loadProfiles();
  initTabs();

  const backendSelect = document.getElementById('backend');
  if (backendSelect) backendSelect.addEventListener('change', switchBackend);

  const form = document.getElementById('preview-form');
  if (form) form.addEventListener('submit', runPreview);

  const btnRun = document.getElementById('btn-run');
  if (btnRun) btnRun.addEventListener('click', startRun);
});
