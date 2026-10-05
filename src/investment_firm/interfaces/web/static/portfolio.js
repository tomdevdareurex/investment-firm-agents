/**
 * Portfolio analytics panel — upload, analyse (free), report, advisor (spends tokens).
 * Plain JS, no build step. Reuses globals from app.js: fetchJson(), el(), textBlock(),
 * selectedHorizon(), _currentRunId. Loads after app.js and the chart library.
 * XSS note: all API/model text goes in via textContent/createElement — never innerHTML.
 */

'use strict';

(function () {
  const MAX_BYTES = 100 * 1024;
  const AUTO_PERIOD = { short: '1y', medium: '5y', long: 'max' };
  const HORIZON_NAME = { short: 'short term', medium: 'medium term', long: 'long term' };
  let currentId = null;
  let charts = [];

  // ── Formatting ────────────────────────────────────────────────────────

  function pct(v) {
    return v === null || v === undefined ? 'n/a' : `${Number(v).toFixed(2)}%`;
  }

  function frac(v) {
    return v === null || v === undefined ? 'n/a' : `${(Number(v) * 100).toFixed(2)}%`;
  }

  function num(v) {
    return v === null || v === undefined ? 'n/a' : Number(v).toFixed(2);
  }

  function table(headers, rows, numCols) {
    const t = el('table', 'roles-table cost-table');
    const hrow = t.createTHead().insertRow();
    headers.forEach((h, i) => {
      const th = el('th', numCols.includes(i) ? 'num' : '', h);
      hrow.appendChild(th);
    });
    const body = t.createTBody();
    rows.forEach((cells) => {
      const tr = body.insertRow();
      cells.forEach((c, i) => {
        const td = tr.insertCell();
        if (numCols.includes(i)) td.className = 'num';
        if (c instanceof Node) td.appendChild(c);
        else td.textContent = String(c);
      });
    });
    return t;
  }

  function setStatus(text, cls) {
    const bar = document.getElementById('portfolio-status');
    bar.replaceChildren(el('span', cls || 'status-info', text));
  }

  function showTab(name) {
    document.querySelectorAll('#portfolio-panel .tab-btn').forEach((b) => {
      const on = b.dataset.ptab === name;
      b.classList.toggle('tab-btn--active', on);
      b.setAttribute('aria-selected', on ? 'true' : 'false');
    });
    document.querySelectorAll('#portfolio-panel .tab-panel').forEach((p) => {
      const on = p.id === `ptab-${name}`;
      p.classList.toggle('tab-panel--active', on);
      p.hidden = !on;
    });
    if (name === 'charts') charts.forEach((c) => c.timeScale().fitContent());
  }

  function warningsBox(items) {
    if (!items || items.length === 0) return null;
    const box = el('div', 'warn-box');
    box.appendChild(el('strong', '', 'Warnings'));
    const ul = el('ul');
    items.forEach((w) => ul.appendChild(el('li', '', w)));
    box.appendChild(ul);
    return box;
  }

  // ── Tabs ──────────────────────────────────────────────────────────────

  function plainSentences(a, d) {
    const s = a.stats || {};
    const out = [
      `Over the period the portfolio grew by ${pct(d.total_return_pct)} ` +
        `(${pct(d.cagr_pct)} per year on average).`,
    ];
    if (s.peak_date) {
      const rec = s.recovery_date ? `recovered on ${s.recovery_date}` : 'not yet recovered';
      out.push(`The worst fall from a peak was ${pct(d.max_drawdown_pct)} ` +
        `(from ${s.peak_date} to ${s.trough_date}; ${rec}).`);
    }
    out.push(`On a typical bad day (1 in 100 at ${pct(d.level_pct)} confidence) you could ` +
      `lose about ${pct(d.hist_var_1d_pct)} or more (VaR); on the worst days the average ` +
      `loss was ${pct(d.es_1d_pct)} (Expected Shortfall).`);
    out.push(`Return per unit of risk (Sharpe) was ${num(d.sharpe)}.`);
    if (d.benchmark_cagr_pct !== null && d.benchmark_cagr_pct !== undefined) {
      out.push(`The benchmark grew ${pct(d.benchmark_cagr_pct)} per year; the portfolio's ` +
        `difference was ${pct(d.excess_cagr_pct)} per year (beta ${num(d.beta)}).`);
    }
    return out;
  }

  function renderOverview(data) {
    const panel = document.getElementById('ptab-overview');
    const d = data.display || {};
    const a = data.analysis || {};
    const w = a.window || {};
    panel.replaceChildren();
    panel.appendChild(el('p', 'memo-question',
      `${w.start || '?'} → ${w.end || '?'} · ${w.n_obs || 0} daily observations · ` +
      `benchmark ${(a.params || {}).benchmark || 'n/a'} · rebalancing ${(a.params || {}).rebalance}`));
    const cards = el('div', 'stat-cards');
    [
      ['Total return', pct(d.total_return_pct)],
      ['Yearly growth (CAGR)', pct(d.cagr_pct)],
      ['Volatility / yr', pct(d.ann_vol_pct)],
      ['Max drawdown', pct(d.max_drawdown_pct)],
      ['1-day VaR', pct(d.hist_var_1d_pct)],
      ['Expected Shortfall', pct(d.es_1d_pct)],
      ['Sharpe', num(d.sharpe)],
      ['Sortino', num(d.sortino)],
      ['Calmar', num(d.calmar)],
      ['Beta', num(d.beta)],
    ].forEach(([label, value]) => {
      const card = el('div', 'stat-card');
      card.appendChild(el('span', 'stat-label', label));
      card.appendChild(el('span', 'stat-value', value));
      cards.appendChild(card);
    });
    panel.appendChild(cards);
    panel.appendChild(el('h3', 'section-title', 'In plain words'));
    plainSentences(a, d).forEach((s) => panel.appendChild(textBlock(s, 'memo-summary')));
    const warn = warningsBox(a.warnings);
    if (warn) panel.appendChild(warn);
  }

  function renderPositions(data) {
    const panel = document.getElementById('ptab-positions');
    const a = data.analysis || {};
    panel.replaceChildren();
    panel.appendChild(el('h3', 'section-title', 'Positions'));
    panel.appendChild(table(
      ['Ticker', 'Weight', 'Total return', 'Yearly growth', 'Volatility', 'Max DD', 'Contribution'],
      (a.position_stats || []).map((p) => [
        p.ticker, frac(p.weight), frac(p.total_return), frac(p.cagr), frac(p.ann_vol),
        frac(p.max_drawdown), frac(p.contribution_to_return),
      ]),
      [1, 2, 3, 4, 5, 6],
    ));
    const div = a.diversification || {};
    panel.appendChild(el('h3', 'section-title', 'Diversification'));
    panel.appendChild(table(
      ['Measure', 'Value'],
      [
        ['Concentration (HHI)', num(div.hhi)],
        ['Effective number of holdings', num(div.effective_n)],
        ['Largest weight', frac(div.largest_weight)],
        ['Average pairwise correlation', num(div.avg_pairwise_corr)],
      ],
      [1],
    ));
    const m = div.correlation_matrix || {};
    if ((m.tickers || []).length > 1) {
      panel.appendChild(el('h3', 'section-title', 'Correlation of daily returns'));
      panel.appendChild(table(
        [''].concat(m.tickers),
        m.tickers.map((t, i) => [t].concat((m.values[i] || []).map(num))),
        m.tickers.map((_, i) => i + 1),
      ));
    }
  }

  function renderBacktests(data) {
    const panel = document.getElementById('ptab-backtests');
    const a = data.analysis || {};
    const comp = a.rebalance_comparison || {};
    panel.replaceChildren();
    panel.appendChild(el('h3', 'section-title', 'Rebalancing comparison'));
    const labels = { none: 'Buy-and-hold', monthly: 'Monthly rebalance', daily: 'Daily rebalance', benchmark: 'Benchmark' };
    panel.appendChild(table(
      ['Approach', 'Total return', 'Yearly growth', 'Volatility', 'Sharpe', 'Max DD'],
      Object.keys(labels).map((k) => {
        const s = comp[k];
        return s
          ? [labels[k], frac(s.total_return), frac(s.cagr), frac(s.ann_vol), num(s.sharpe), frac(s.max_drawdown)]
          : [labels[k], 'n/a', 'n/a', 'n/a', 'n/a', 'n/a'];
      }),
      [1, 2, 3, 4, 5],
    ));
    panel.appendChild(el('h3', 'section-title', 'Strategy backtests'));
    const overlays = a.strategy_overlays || [];
    if (overlays.length === 0) {
      panel.appendChild(el('p', 'loading', 'No strategy backtests were run.'));
    } else {
      panel.appendChild(table(
        ['Strategy', 'Rule', 'Yearly growth', 'Volatility', 'Max DD', 'Sharpe'],
        overlays.map((o) => {
          const s = o.stats || {};
          return [o.strategy, o.rule, frac(s.cagr), frac(s.ann_vol), frac(s.max_drawdown), num(s.sharpe)];
        }),
        [2, 3, 4, 5],
      ));
    }
    panel.appendChild(el('p', 'cost-note',
      'Historical simulation only — rules are applied with a one-day delay to avoid ' +
      'look-ahead; past results do not predict future returns.'));
  }

  function lineData(points) {
    return (points || []).map(([time, value]) => ({ time, value }));
  }

  function renderCharts(data) {
    const panel = document.getElementById('ptab-charts');
    charts.forEach((c) => c.remove());
    charts = [];
    panel.replaceChildren();
    const series = (data.analysis || {}).series || {};
    if (typeof LightweightCharts === 'undefined') {
      panel.appendChild(el('p', 'loading', 'Chart library missing — download the HTML report for charts.'));
      return;
    }
    [
      ['Growth of 1 unit (blue) vs benchmark (grey)', [
        [series.equity, '#2f5bd3'], [series.benchmark_equity, '#9aa4b2']]],
      ['Drawdown (fall from previous high)', [[series.drawdown, '#ef5350']]],
    ].forEach(([title, lines]) => {
      panel.appendChild(el('h3', 'section-title', title));
      const box = el('div', 'portfolio-chart');
      panel.appendChild(box);
      const chart = LightweightCharts.createChart(box, {
        height: 260,
        autoSize: true,
        layout: { background: { color: 'transparent' }, textColor: '#9aa4b2' },
        grid: {
          vertLines: { color: 'rgba(154, 164, 178, 0.12)' },
          horzLines: { color: 'rgba(154, 164, 178, 0.12)' },
        },
      });
      lines.forEach(([points, color]) => {
        if (points && points.length) {
          chart.addLineSeries({ color, lineWidth: 2 }).setData(lineData(points));
        }
      });
      chart.timeScale().fitContent();
      charts.push(chart);
    });
  }

  function renderSuggestion(sug, cost) {
    const panel = document.getElementById('ptab-suggestion');
    panel.replaceChildren();
    if (!sug) {
      panel.appendChild(el('p', 'loading',
        'No suggestions yet. "Ask for suggestions" makes one LLM call (spends tokens); ' +
        'it uses the latest finished committee run as market context when available.'));
      return;
    }
    if (sug.status !== 'ok') {
      panel.appendChild(el('div', 'error-box', `The advisor did not return a usable answer: ${sug.error || 'unknown error'}`));
    } else {
      panel.appendChild(textBlock(sug.assessment || '', 'memo-summary'));
      [['Strengths', sug.strengths], ['Weaknesses', sug.weaknesses], ['Caveats', sug.caveats]]
        .forEach(([title, items]) => {
          if (!items || !items.length) return;
          panel.appendChild(el('h3', 'section-title', title));
          const ul = el('ul', 'memo-list');
          items.forEach((t) => ul.appendChild(el('li', '', t)));
          panel.appendChild(ul);
        });
      if ((sug.ideas || []).length) {
        panel.appendChild(el('h3', 'section-title', 'Options to consider'));
        sug.ideas.forEach((i) => {
          const card = el('div', 'analyst-card');
          const head = el('div', 'analyst-header');
          head.appendChild(el('span', 'analyst-role', i.idea));
          head.appendChild(el('span', 'badge badge--horizon', i.type || 'watch'));
          card.appendChild(head);
          if (i.why) card.appendChild(textBlock(i.why, 'analyst-rationale'));
          panel.appendChild(card);
        });
      }
    }
    if (cost) {
      panel.appendChild(el('p', 'cost-note',
        `Model ${sug.model || 'n/a'} · about $${Number(cost.cost_usd || 0).toFixed(4)} ` +
        `(${Number(cost.total_tokens || 0).toLocaleString()} tokens).`));
    }
  }

  function renderAll(data) {
    renderOverview(data);
    renderPositions(data);
    renderBacktests(data);
    renderCharts(data);
    renderSuggestion(data.suggestion, data.suggestion_cost);
    const report = document.getElementById('btn-portfolio-report');
    report.href = data.report_url;
    report.hidden = false;
    document.getElementById('btn-portfolio-suggest').hidden = false;
    document.getElementById('portfolio-disclaimer').textContent = data.disclaimer || '';
  }

  // ── Actions ───────────────────────────────────────────────────────────

  function readFile(file) {
    return new Promise((resolve, reject) => {
      const reader = new FileReader();
      reader.onload = () => resolve(String(reader.result || ''));
      reader.onerror = () => reject(new Error('could not read the file'));
      reader.readAsText(file);
    });
  }

  async function analyse() {
    const input = document.getElementById('portfolio-file');
    const file = input.files && input.files[0];
    const panel = document.getElementById('portfolio-panel');
    panel.hidden = false;
    if (!file) {
      setStatus('Choose a CSV or JSON portfolio file first.', 'status-error');
      return;
    }
    if (file.size > MAX_BYTES) {
      setStatus('The portfolio file is larger than 100 KB.', 'status-error');
      return;
    }
    const button = document.getElementById('btn-portfolio');
    button.disabled = true;
    setStatus('Analysing portfolio…', 'status-running');
    try {
      const text = await readFile(file);
      const period = document.getElementById('portfolio-period').value;
      const strategies = Array.from(
        document.querySelectorAll('input[name="portfolio-strategy"]:checked')
      ).map((c) => c.value);
      const data = await fetchJson('/api/portfolio/analyze', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
          portfolio_text: text,
          horizon: selectedHorizon(),
          period: period === 'auto' ? null : period,
          benchmark: document.getElementById('portfolio-benchmark').value.trim() || 'SPY',
          rebalance: document.getElementById('portfolio-rebalance').value,
          rf_annual: (Number(document.getElementById('portfolio-rf').value) || 0) / 100,
          strategies,
        }),
      });
      currentId = data.analysis_id;
      renderAll(data);
      showTab('overview');
      setStatus(`Done — ${((data.analysis || {}).positions || []).length} holdings analysed.`, 'status-done');
      panel.scrollIntoView({ behavior: 'smooth', block: 'start' });
    } catch (err) {
      setStatus(`Error: ${err.message}`, 'status-error');
    } finally {
      button.disabled = false;
    }
  }

  async function askSuggestions() {
    if (!currentId) return;
    if (!window.confirm('This asks an LLM advisor and spends tokens. Proceed?')) return;
    const button = document.getElementById('btn-portfolio-suggest');
    button.disabled = true;
    setStatus('Asking the advisor…', 'status-running');
    let runId = typeof _currentRunId !== 'undefined' ? _currentRunId : null;
    if (runId) {
      try {
        const run = await fetchJson(`/api/runs/${runId}`);
        if (run.status !== 'done') runId = null;
      } catch (_) {
        runId = null;
      }
    }
    try {
      const data = await fetchJson(`/api/portfolio/${currentId}/suggest`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ run_id: runId }),
      });
      renderSuggestion(data.suggestion, data.suggestion_cost);
      showTab('suggestion');
      setStatus(runId ? 'Suggestions ready (with committee context).' : 'Suggestions ready.', 'status-done');
    } catch (err) {
      setStatus(`Error: ${err.message}`, 'status-error');
    } finally {
      button.disabled = false;
    }
  }

  function updatePeriodHint(horizon) {
    const hint = document.getElementById('portfolio-period-hint');
    if (hint) hint.textContent = `auto = ${AUTO_PERIOD[horizon] || '1y'} for ${HORIZON_NAME[horizon] || 'short term'}.`;
  }

  function init() {
    const btn = document.getElementById('btn-portfolio');
    if (!btn) return;
    btn.addEventListener('click', analyse);
    document.getElementById('btn-portfolio-suggest').addEventListener('click', askSuggestions);
    document.querySelectorAll('#portfolio-panel .tab-btn').forEach((b) => {
      b.addEventListener('click', () => showTab(b.dataset.ptab));
    });
    document.addEventListener('ifa:horizon', (e) => updatePeriodHint(e.detail && e.detail.horizon));
  }

  if (document.readyState === 'loading') {
    document.addEventListener('DOMContentLoaded', init);
  } else {
    init();
  }
})();
