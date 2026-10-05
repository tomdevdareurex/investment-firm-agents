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

  if (result.synth_role) {
    const model = result.synth_model ? ` (${result.synth_model})` : '';
    const attribution = `Final recommendation issued by ${result.synth_role.toUpperCase()}${model}`;
    panel.appendChild(el('p', 'memo-attribution', attribution));
  }

  if (result.question) {
    panel.appendChild(el('p', 'memo-question', `Question: ${result.question}`));
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
