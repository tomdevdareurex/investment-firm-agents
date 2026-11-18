/**
 * Forecast cone overlays for the Market Charts panel.
 *
 * Two independent layers, each fetched from GET /api/market/forecast:
 *  - "Forecast cone" (#chart-forecast): TimesFM when the `forecast` extra is
 *    installed, otherwise the random-walk baseline (blue).
 *  - "ARIMA(1,1,1)" (#chart-arima): ARIMA(1,1,1) on the log price with constant
 *    error variance (orange). Ticking "+ GARCH(1,1)" (#chart-garch) refits it
 *    with GARCH(1,1) errors (method=arima_garch) and turns ARIMA on.
 * Each draws q10 / q25 / q50 / q75 / q90 as dashed lines anchored at the last
 * close, N bars of the chart interval ahead, then zooms to the last bars + cone.
 * A cone is a statistical range — never a trade signal.
 *
 * Depends on charts.js (`window.ifaCharts`, `ifa:chart-rendered`,
 * `ifa:chart-destroyed`) and app.js globals (`fetchJson`, `el`, `selectedHorizon`).
 * XSS note: everything is rendered via textContent/createElement — never innerHTML.
 */

'use strict';

(function () {
  // Bars ahead per investment horizon, in units of the chart interval (API caps at 60).
  const HORIZON_DAYS = { short: 20, medium: 60, long: 60 };
  const SUPPORTED_INTERVALS = new Set(['1d', '1wk', '1mo']);
  const UNIT = { '1d': 'business days', '1wk': 'weeks', '1mo': 'months' };
  const VISIBLE_BARS = 50;
  const QUANTILES = ['q10', 'q90', 'q25', 'q75', 'q50'];

  function palette(outer, inner, median) {
    return {
      q10: { color: outer, width: 1, label: '10%' },
      q90: { color: outer, width: 1, label: '90%' },
      q25: { color: inner, width: 1, label: '25%' },
      q75: { color: inner, width: 1, label: '75%' },
      q50: { color: median, width: 2, label: 'median' },
    };
  }

  function checked(id) {
    const box = document.getElementById(id);
    return !!(box && box.checked);
  }

  function currentHorizonDays() {
    const h = typeof selectedHorizon === 'function' ? selectedHorizon() : 'short';
    return HORIZON_DAYS[h] || HORIZON_DAYS.short;
  }

  function setBadge(text) {
    const badge = document.getElementById('chart-forecast-badge');
    if (badge) badge.textContent = text || '';
  }

  function toLine(dates, values) {
    const out = [];
    for (let i = 0; i < dates.length && i < values.length; i++) {
      const v = Number(values[i]);
      if (Number.isFinite(v)) out.push({ time: dates[i], value: v });
    }
    return out;
  }

  // Anchor each quantile at the last actual close so the cone opens from the
  // candle it continues, instead of floating one bar to the right.
  function withAnchor(payload, values) {
    const asOf = payload.as_of;
    const last = Number(payload.last_close);
    const line = toLine(payload.dates || [], values || []);
    if (asOf && Number.isFinite(last) && (!line.length || line[0].time !== asOf)) {
      line.unshift({ time: asOf, value: last });
    }
    return line;
  }

  const pct = (v) => `${Number(v) >= 0 ? '+' : ''}${Number(v).toFixed(1)}%`;
  const num = (v, d) => Number(v).toFixed(d);

  function rangeParts(payload) {
    const s = payload.summary || payload.baseline_summary || {};
    const has = (k) => Number.isFinite(Number(s[k]));
    const parts = [`${payload.horizon_days} ${UNIT[payload.interval] || 'steps'} from ${payload.as_of}`];
    if (has('end_q50_pct')) parts.push(`median ${pct(s.end_q50_pct)}`);
    if (has('end_q25_pct') && has('end_q75_pct')) {
      parts.push(`25–75% range ${pct(s.end_q25_pct)} … ${pct(s.end_q75_pct)}`);
    }
    if (has('end_q10_pct') && has('end_q90_pct')) {
      parts.push(`10–90% range ${pct(s.end_q10_pct)} … ${pct(s.end_q90_pct)}`);
    }
    return parts;
  }

  function describeTimesfm(payload) {
    const parts = [payload.is_model ? `TimesFM (${payload.model_repo || 'model'})` : 'Random-walk baseline'];
    parts.push(...rangeParts(payload));
    if (payload.model_error) parts.push(`model unavailable: ${payload.model_error}`);
    if (payload.caveat) parts.push(payload.caveat);
    return parts.join(' · ');
  }

  function describeArima(payload) {
    const p = payload.model_params || {};
    const fit = payload.fit || {};
    const parts = [payload.source || 'ARIMA(1,1,1)'];
    parts.push(`μ=${num(p.mu_pct, 3)}% φ=${num(p.phi, 3)} θ=${num(p.theta, 3)}`);
    if (payload.method === 'arima_garch') {
      parts.push(`ω=${num(p.omega, 4)} α=${num(p.alpha, 3)} β=${num(p.beta, 3)} (α+β=${num(p.persistence, 3)})`);
      const vol = payload.step_vol_pct || [];
      if (vol.length) {
        parts.push(`1-bar vol ${num(vol[0], 2)}% → ${num(vol[vol.length - 1], 2)}%`);
      }
    } else if (Number.isFinite(Number(p.sigma_pct))) {
      parts.push(`σ=${num(p.sigma_pct, 2)}% per bar`);
    }
    parts.push(...rangeParts(payload));
    if (Number.isFinite(Number(fit.aic))) parts.push(`AIC ${num(fit.aic, 1)} (n=${fit.n_obs})`);
    (fit.warnings || []).forEach((w) => parts.push(`⚠ ${w}`));
    if (!checked('chart-forecast') && payload.caveat) parts.push(payload.caveat);
    return parts.join(' · ');
  }

  function makeLayer(cfg) {
    let series = {};
    let inflight = 0;
    let lastKey = '';

    function setInfo(text, kind) {
      const node = document.getElementById(cfg.infoId);
      if (!node) return;
      node.textContent = '';
      if (!text) return;
      node.appendChild(el('span', kind === 'error' ? 'forecast-info--error' : 'forecast-info', text));
    }

    function clear() {
      const chart = window.ifaCharts && window.ifaCharts.chart;
      Object.values(series).forEach((s) => {
        if (chart && s) {
          try { chart.removeSeries(s); } catch (_) { /* chart already gone */ }
        }
      });
      series = {};
    }

    function draw(payload, barCount) {
      const chart = window.ifaCharts && window.ifaCharts.chart;
      if (!chart) return;
      clear();
      const style = cfg.style();
      const prefix = cfg.title(payload);
      QUANTILES.forEach((key) => {
        if (!Array.isArray(payload[key])) return;
        const s = style[key];
        const line = chart.addLineSeries({
          color: s.color,
          lineWidth: s.width,
          lineStyle: 2, // dashed
          priceLineVisible: false,
          lastValueVisible: key === 'q50',
          crosshairMarkerVisible: false,
          title: `${prefix} ${s.label}`,
        });
        line.setData(withAnchor(payload, payload[key]));
        series[key] = line;
      });
      const ahead = (payload.dates || []).length;
      chart.timeScale().setVisibleLogicalRange({
        from: Math.max(0, barCount - VISIBLE_BARS),
        to: barCount + ahead + 2,
      });
    }

    async function refresh() {
      const chartPayload = window.ifaCharts && window.ifaCharts.lastPayload;
      if (!checked(cfg.boxId)) {
        inflight++;
        clear();
        lastKey = '';
        setInfo('');
        return;
      }
      if (!chartPayload || !window.ifaCharts.chart) return;

      const interval = document.getElementById('chart-interval').value;
      if (!SUPPORTED_INTERVALS.has(interval)) {
        clear();
        setInfo(`${cfg.name} is not available for the ${interval} interval.`, 'error');
        return;
      }

      const ticker = (chartPayload.ticker || document.getElementById('chart-ticker').value || '').trim();
      const horizonDays = currentHorizonDays();
      const method = cfg.method();
      const key = `${ticker}|${horizonDays}|${interval}|${method}|${chartPayload.as_of}`;
      if (key === lastKey && series.q50) return; // already drawn for this view
      const myCall = ++inflight;
      setInfo(`Computing ${cfg.name}…`);
      try {
        const url = `/api/market/forecast?ticker=${encodeURIComponent(ticker)}`
          + `&horizon_days=${horizonDays}&interval=${encodeURIComponent(interval)}`
          + `&method=${encodeURIComponent(method)}`;
        const payload = await fetchJson(url);
        if (myCall !== inflight || !checked(cfg.boxId)) return; // superseded or switched off
        draw(payload, (chartPayload.ohlc || []).length);
        lastKey = key;
        if (cfg.onDrawn) cfg.onDrawn(payload);
        setInfo(cfg.describe(payload));
      } catch (err) {
        if (myCall !== inflight) return;
        clear();
        lastKey = '';
        setInfo(`${cfg.name} unavailable: ${err.message || err}`, 'error');
      }
    }

    return {
      refresh,
      invalidate() { lastKey = ''; },
      forget() { series = {}; lastKey = ''; },
    };
  }

  const timesfmLayer = makeLayer({
    name: 'Forecast cone',
    boxId: 'chart-forecast',
    infoId: 'chart-forecast-info',
    method: () => 'timesfm',
    style: () => palette('#93c5fd', '#60a5fa', '#2563eb'),
    title: () => 'Forecast',
    describe: describeTimesfm,
    onDrawn: (payload) => setBadge(payload.is_model ? 'TimesFM' : 'baseline'),
  });

  const arimaLayer = makeLayer({
    name: 'ARIMA cone',
    boxId: 'chart-arima',
    infoId: 'chart-arima-info',
    method: () => (checked('chart-garch') ? 'arima_garch' : 'arima'),
    style: () => palette('#fdba74', '#fb923c', '#ea580c'),
    title: (payload) => (payload.method === 'arima_garch' ? 'ARIMA-GARCH' : 'ARIMA'),
    describe: describeArima,
  });

  const layers = [timesfmLayer, arimaLayer];

  async function initBadge() {
    try {
      const health = await fetchJson('/api/health');
      setBadge(health.forecast_available ? 'TimesFM' : 'baseline');
    } catch (_) {
      setBadge('');
    }
  }

  function init() {
    const box = document.getElementById('chart-forecast');
    const arima = document.getElementById('chart-arima');
    const garch = document.getElementById('chart-garch');
    if (box) {
      box.addEventListener('change', () => {
        timesfmLayer.invalidate();
        timesfmLayer.refresh();
        // The ARIMA info line carries the caveat only when the cone is off.
        if (arima && arima.checked) { arimaLayer.invalidate(); arimaLayer.refresh(); }
      });
    }
    if (arima) {
      arima.addEventListener('change', () => {
        if (!arima.checked && garch) garch.checked = false;
        arimaLayer.invalidate();
        arimaLayer.refresh();
      });
    }
    if (garch) {
      garch.addEventListener('change', () => {
        if (garch.checked && arima) arima.checked = true;
        arimaLayer.invalidate();
        arimaLayer.refresh();
      });
    }
    document.addEventListener('ifa:chart-rendered', () => {
      layers.forEach((layer) => { layer.invalidate(); layer.refresh(); });
    });
    document.addEventListener('ifa:chart-destroyed', () => {
      layers.forEach((layer) => layer.forget());
    });
    // Horizon changes trigger a chart reload via charts.js, which re-emits
    // ifa:chart-rendered; the new horizon_days is read at that point.
    initBadge();
  }

  if (document.readyState === 'loading') {
    document.addEventListener('DOMContentLoaded', init);
  } else {
    init();
  }
})();
