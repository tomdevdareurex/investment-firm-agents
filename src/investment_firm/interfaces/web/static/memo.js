/**
 * Memo tab — plain-language committee result.
 * Reuses global helpers from app.js: el(), textBlock(), recBadge().
 * XSS note: model text goes in via textContent/createElement only — never innerHTML.
 */

'use strict';

function confidenceDots(n) {
  const k = Math.max(0, Math.min(5, Number(n) || 0));
  const span = el('span', 'confidence-dots', '\u25cf'.repeat(k) + '\u25cb'.repeat(5 - k));
  span.title = `Confidence ${k} / 5`;
  return span;
}

function memoList(title, items) {
  const clean = (items || []).filter((t) => String(t || '').trim());
  if (clean.length === 0) return null;
  const wrap = el('div', 'memo-section');
  wrap.appendChild(el('h3', 'section-title', title));
  const ul = el('ul', 'memo-list');
  clean.forEach((t) => ul.appendChild(el('li', '', String(t))));
  wrap.appendChild(ul);
  return wrap;
}

function fmtNum(v) {
  const f = Number(v);
  if (!Number.isFinite(f)) return String(v == null ? '' : v);
  return Number.isInteger(f) ? String(f) : f.toFixed(2);
}

function memoVote(vote) {
  if (!vote || typeof vote !== 'object' || !vote.winner) return null;
  const wrap = el('div', 'memo-section memo-vote');
  wrap.appendChild(el('h3', 'section-title', 'Committee vote (advisory)'));
  const vetoBy = Array.isArray(vote.veto_by) ? vote.veto_by.join(', ') : '';
  const vetoTxt = vote.veto ? `VETO raised by ${vetoBy || 'a veto role'}` : 'no veto';
  const excluded = Array.isArray(vote.excluded) ? vote.excluded.length : 0;
  wrap.appendChild(el('p', 'memo-vote-outcome',
    `Outcome: ${vote.winner} (margin ${fmtNum(vote.margin)}) \u2014 ${vetoTxt}. ` +
    `${fmtNum(vote.participants)} voting, ${excluded} excluded.`));
  const totals = vote.totals && typeof vote.totals === 'object' ? vote.totals : {};
  const totalsTxt = Object.keys(totals).map((k) => `${k} ${fmtNum(totals[k])}`).join(' | ');
  if (totalsTxt) wrap.appendChild(el('p', 'memo-note', `Totals: ${totalsTxt}`));
  const rows = Array.isArray(vote.rows) ? vote.rows : [];
  if (rows.length > 0) {
    const details = el('details', 'memo-vote-rows');
    details.appendChild(el('summary', '', `Ballots (${rows.length})`));
    const ul = el('ul', 'memo-list');
    rows.forEach((r) => {
      const note = r.note ? ` \u2014 ${r.note}` : '';
      ul.appendChild(el('li', r.counted ? '' : 'memo-vote-skipped',
        `${r.role}: ${r.stance} (conviction ${fmtNum(r.conviction)}, weight ${fmtNum(r.weight)}, ` +
        `${r.counted ? 'counted' : 'not counted'})${note}`));
    });
    details.appendChild(ul);
    wrap.appendChild(details);
  }
  wrap.appendChild(el('p', 'memo-note',
    'Advisory only \u2014 the CIO ruling above remains the recommendation.'));
  return wrap;
}

// Second opinion: an independent model family re-reads the views and the ruling.
// Never changes the recommendation; rendered only when status is ok|error.
function memoCrossCheck(cc) {
  if (!cc || typeof cc !== 'object' || !cc.status || cc.status === 'skipped') return null;
  const wrap = el('div', 'memo-section memo-cross-check');
  wrap.appendChild(el('h3', 'section-title', 'Second opinion (CIO cross-check)'));
  const model = cc.model ? ` (reviewer: ${cc.model})` : '';
  if (cc.status === 'ok') {
    const verdict = cc.agrees ? 'Agrees' : 'Disagrees';
    const line = el('p', cc.agrees ? 'memo-cc-agree' : 'memo-cc-disagree');
    line.appendChild(el('strong', '', verdict));
    line.appendChild(document.createTextNode(` with the CIO ruling${model}.`));
    wrap.appendChild(line);
    if (cc.note) wrap.appendChild(el('p', '', String(cc.note)));
    const concerns = Array.isArray(cc.concerns) ? cc.concerns.filter((c) => String(c).trim()) : [];
    if (concerns.length > 0) {
      const ul = el('ul', 'memo-list');
      concerns.forEach((c) => ul.appendChild(el('li', '', String(c))));
      wrap.appendChild(ul);
    }
  } else {
    wrap.appendChild(el('p', 'memo-cc-error',
      `Second opinion unavailable${model} \u2014 ${cc.reason || 'unknown error'}`));
  }
  wrap.appendChild(el('p', 'memo-note',
    'Advisory only \u2014 a different model family reviewed the ruling; it never changes the recommendation.'));
  return wrap;
}

function renderMemoTab(result) {
  const panel = document.getElementById('tab-memo');
  panel.textContent = '';

  const header = el('div', 'memo-header');
  header.appendChild(el('span', 'memo-label', 'Recommendation: '));
  header.appendChild(recBadge(result.recommendation));
  if (result.horizon_label) {
    header.appendChild(el('span', 'badge badge--horizon', result.horizon_label));
  }
  if (Number(result.confidence) > 0) {
    header.appendChild(el('span', 'memo-label', 'Confidence: '));
    header.appendChild(confidenceDots(result.confidence));
  }
  panel.appendChild(header);

  if (result.recommendation_plain) {
    panel.appendChild(el('p', 'memo-rec-plain', result.recommendation_plain));
  }
  if (result.recommendation === 'ERROR') {
    const box = el('div', 'error-box');
    box.appendChild(el('strong', '', 'Why there is no ruling: '));
    box.appendChild(document.createTextNode(result.failure_reason || 'see the summary below'));
    if (Number(result.token_budget) > 0) {
      box.appendChild(el('div', 'memo-note-detail',
        `Tokens used: ${result.total_tokens} of ${result.token_budget} budget.`));
    }
    panel.appendChild(box);
  }
  if (result.synth_note) {
    panel.appendChild(el('p', 'memo-note', result.synth_note));
  }
  if (result.headline) {
    panel.appendChild(el('h3', 'memo-headline', result.headline));
  }

  panel.appendChild(el('h3', 'section-title', 'In plain words'));
  panel.appendChild(textBlock(result.summary || '', 'memo-summary'));

  [
    ['Why the committee thinks so', result.key_reasons],
    ['What could go wrong', result.main_risks],
    ['What to watch', result.what_to_watch],
  ].forEach(([title, items]) => {
    const node = memoList(title, items);
    if (node) panel.appendChild(node);
  });

  const voteNode = memoVote(result.vote);
  if (voteNode) panel.appendChild(voteNode);
  const ccNode = memoCrossCheck(result.cross_check);
  if (ccNode) panel.appendChild(ccNode);

  if (result.synth_role) {
    const model = result.synth_model ? ` (${result.synth_model})` : '';
    const attribution = `Final recommendation issued by ${result.synth_role.toUpperCase()}${model}`;
    panel.appendChild(el('p', 'memo-attribution', attribution));
  }

  if (result.question) {
    panel.appendChild(el('p', 'memo-question', `Question: ${result.question}`));
  }
  if (result.portfolio_id) {
    panel.appendChild(el('p', 'memo-question',
      `Based on your analysed portfolio (analysis ${result.portfolio_id}) - see the Briefing tab.`));
  }

  const glossary = Array.isArray(result.glossary) ? result.glossary : [];
  if (glossary.length > 0) {
    const details = el('details', 'memo-glossary');
    details.appendChild(el('summary', '', `Words used in this memo (${glossary.length})`));
    const dl = el('dl', 'glossary-list');
    glossary.forEach((g) => {
      dl.appendChild(el('dt', '', g.term || ''));
      dl.appendChild(el('dd', '', g.plain || ''));
    });
    details.appendChild(dl);
    panel.appendChild(details);
  }
}
