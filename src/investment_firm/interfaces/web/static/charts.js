/**
 * Market Charts panel — candlesticks + volume + SMA overlays.
 * Plain JS, no build step. Chart library is vendored locally at
 * /static/vendor/lightweight-charts.standalone.production.js (no runtime CDN).
 * Data: GET /api/market/price-history (yfinance, SQLite-cached, decision-support only).
 * XSS note: all API data is inserted via textContent/createElement — never innerHTML.
 * Reuses global helpers from app.js: fetchJson(), el().
 */

'use strict';

(function () {
  const SMA_CONFIGS = [
    { checkboxId: 'chart-sma20', period: 20, color: '#f5a623', label: 'SMA 20' },
    { checkboxId: 'chart-sma50', period: 50, color: '#7b61ff', label: 'SMA 50' },
  ];

  // Server-computed overlays (shared stockstats engine — same values the agents
  // cite). Multiple lines may share one checkbox (e.g. the Bollinger bands).
  const SERVER_LINES = [
    { name: 'close_10_ema', checkboxId: 'chart-ema10', color: '#00bcd4', label: 'EMA 10' },
    { name: 'close_200_sma', checkboxId: 'chart-sma200', color: '#e91e63', label: 'SMA 200' },
    { name: 'boll_ub', checkboxId: 'chart-boll', color: 'rgba(123, 97, 255, 0.55)', label: 'Boll Upper' },
    { name: 'boll', checkboxId: 'chart-boll', color: 'rgba(123, 97, 255, 0.9)', label: 'Boll Mid' },
    { name: 'boll_lb', checkboxId: 'chart-boll', color: 'rgba(123, 97, 255, 0.55)', label: 'Boll Lower' },
  ];

  // Oscillator sub-panes rendered in their own vertical band (separate price
  // scale) below the price/volume, from the same shared server engine.
  const SUBPANES = [
    {
      id: 'rsi', checkboxId: 'chart-rsi', priceScaleId: 'rsi',
      lines: [{ name: 'rsi', type: 'line', color: '#26c6da', label: 'RSI 14' }],
    },
    {
      id: 'macd', checkboxId: 'chart-macd', priceScaleId: 'macd',
      lines: [
        { name: 'macdh', type: 'histogram', color: 'rgba(120, 144, 156, 0.6)' },
        { name: 'macd', type: 'line', color: '#42a5f5', label: 'MACD' },
        { name: 'macds', type: 'line', color: '#ef5350', label: 'Signal' },
      ],
    },
  ];

  let chart = null;
  let candleSeries = null;
  let volumeSeries = null;
  let smaSeries = {}; // period -> line series
  let serverSeries = {}; // indicator name -> line series
  let subpaneSeries = {}; // indicator name -> oscillator series
  let lastPayload = null;

  // ── Indicators (computed client-side from returned closes) ─────────────

  function computeSMA(ohlc, period) {
    if (!Array.isArray(ohlc) || ohlc.length < period) return [];
    const points = [];
    let sum = 0;
    for (let i = 0; i < ohlc.length; i += 1) {
      sum += ohlc[i].close;
      if (i >= period) sum -= ohlc[i - period].close;
      if (i >= period - 1) {
        points.push({ time: ohlc[i].time, value: sum / period });
      }
    }
    return points;
  }

  // ── Chart lifecycle ─────────────────────────────────────────────────────

  function destroyChart() {
    if (chart) {
      chart.remove();
      chart = null;
      candleSeries = null;
      volumeSeries = null;
      smaSeries = {};
      serverSeries = {};
      subpaneSeries = {};
    }
  }

  function createChart(container) {
    destroyChart();
    chart = LightweightCharts.createChart(container, {
      height: 420,
      layout: { background: { color: 'transparent' }, textColor: '#9aa4b2' },
      grid: {
        vertLines: { color: 'rgba(154, 164, 178, 0.12)' },
        horzLines: { color: 'rgba(154, 164, 178, 0.12)' },
      },
      rightPriceScale: { borderVisible: false },
      timeScale: { borderVisible: false },
      autoSize: true,
    });
    candleSeries = chart.addCandlestickSeries({
      upColor: '#26a69a',
      downColor: '#ef5350',
      borderVisible: false,
      wickUpColor: '#26a69a',
      wickDownColor: '#ef5350',
    });
    volumeSeries = chart.addHistogramSeries({
      priceFormat: { type: 'volume' },
      priceScaleId: 'volume',
    });
    // Vertical bands (candles / volume / oscillator sub-panes) are assigned in
    // applyLayout() so they reflow when RSI/MACD sub-panes are toggled.
  }

  function renderSeries(payload) {
    const container = document.getElementById('chart-container');
    createChart(container);
    candleSeries.setData(payload.ohlc);

    const closeByTime = {};
    payload.ohlc.forEach((bar) => { closeByTime[bar.time] = bar; });
    volumeSeries.setData((payload.volume || []).map((v) => {
      const bar = closeByTime[v.time];
      const up = !bar || bar.close >= bar.open;
      return {
        time: v.time,
        value: v.value,
        color: up ? 'rgba(38, 166, 154, 0.5)' : 'rgba(239, 83, 80, 0.5)',
      };
    }));

    renderOverlays(payload);
    renderServerOverlays(payload);
    renderSubpanes(payload);
    applyLayout();
    chart.timeScale().fitContent();
  }

  function renderOverlays(payload) {
    if (!chart) return;
    SMA_CONFIGS.forEach((cfg) => {
      const wanted = document.getElementById(cfg.checkboxId).checked;
      const existing = smaSeries[cfg.period];
      if (existing) {
        chart.removeSeries(existing);
        delete smaSeries[cfg.period];
      }
      if (!wanted) return;
      const points = computeSMA(payload.ohlc, cfg.period);
      if (!points.length) return; // fewer bars than the SMA window — skip overlay
      const line = chart.addLineSeries({
        color: cfg.color,
        lineWidth: 2,
        priceLineVisible: false,
        lastValueVisible: false,
        title: cfg.label,
      });
      line.setData(points);
      smaSeries[cfg.period] = line;
    });
  }

  // ── Server overlays (shared indicator engine) ──────────────────────────

  // Unique indicator names whose controlling checkbox is currently checked.
  function requestedServerIndicators() {
    const names = [];
    SERVER_LINES.forEach((cfg) => {
      const box = document.getElementById(cfg.checkboxId);
      if (box && box.checked && !names.includes(cfg.name)) names.push(cfg.name);
    });
    SUBPANES.forEach((sp) => {
      const box = document.getElementById(sp.checkboxId);
      if (box && box.checked) {
        sp.lines.forEach((ln) => { if (!names.includes(ln.name)) names.push(ln.name); });
      }
    });
    return names;
  }

  function renderServerOverlays(payload) {
    if (!chart) return;
    // Clear any existing server line series first.
    Object.values(serverSeries).forEach((line) => chart.removeSeries(line));
    serverSeries = {};
    const overlays = (payload && payload.indicators) || {};
    SERVER_LINES.forEach((cfg) => {
      const box = document.getElementById(cfg.checkboxId);
      if (!box || !box.checked) return;
      const points = overlays[cfg.name];
      if (!Array.isArray(points) || !points.length) return;
      const line = chart.addLineSeries({
        color: cfg.color,
        lineWidth: 2,
        priceLineVisible: false,
        lastValueVisible: false,
        title: cfg.label,
      });
      line.setData(points);
      serverSeries[cfg.name] = line;
    });
  }

  // ── Oscillator sub-panes (RSI / MACD) ───────────────────────────────

  function activeSubpanes() {
    return SUBPANES.filter((sp) => {
      const box = document.getElementById(sp.checkboxId);
      return box && box.checked;
    });
  }

  function renderSubpanes(payload) {
    if (!chart) return;
    Object.values(subpaneSeries).forEach((series) => chart.removeSeries(series));
    subpaneSeries = {};
    const overlays = (payload && payload.indicators) || {};
    activeSubpanes().forEach((sp) => {
      sp.lines.forEach((ln) => {
        const points = overlays[ln.name];
        if (!Array.isArray(points) || !points.length) return;
        const series = ln.type === 'histogram'
          ? chart.addHistogramSeries({
            priceScaleId: sp.priceScaleId,
            color: ln.color,
            priceLineVisible: false,
            lastValueVisible: false,
          })
          : chart.addLineSeries({
            priceScaleId: sp.priceScaleId,
            color: ln.color,
            lineWidth: 2,
            priceLineVisible: false,
            lastValueVisible: false,
            title: ln.label,
          });
        series.setData(points);
        subpaneSeries[ln.name] = series;
      });
    });
  }

  // Assign non-overlapping vertical bands: oscillators at the bottom, volume
  // above them, candles filling the remaining top space. Reflows on toggle.
  function applyLayout() {
    if (!chart || !candleSeries) return;
    const active = activeSubpanes();
    const subHeight = 0.18;
    const volHeight = 0.16;
    let fromBottom = 0;
    active.forEach((sp) => {
      const top = Math.max(0, 1 - (fromBottom + subHeight));
      chart.priceScale(sp.priceScaleId).applyOptions({
        scaleMargins: { top, bottom: fromBottom },
      });
      fromBottom += subHeight;
    });
    const volTop = Math.max(0, 1 - (fromBottom + volHeight));
    chart.priceScale('volume').applyOptions({
      scaleMargins: { top: volTop, bottom: fromBottom },
    });
    fromBottom += volHeight;
    candleSeries.priceScale().applyOptions({
      scaleMargins: { top: 0.05, bottom: Math.min(0.7, fromBottom) },
    });
  }

  // ── Status / cache rendering (textContent only) ─────────────────────────

  function setStatus(text, kind) {
    const node = document.getElementById('chart-status');
    node.replaceChildren();
    if (!text) return;
    const cls = kind === 'error' ? 'chart-status-msg chart-status-msg--error'
      : 'chart-status-msg';
    node.appendChild(el('span', cls, text));
  }

  function renderCacheInfo(payload) {
    const node = document.getElementById('chart-cache');
    node.replaceChildren();
    const cache = payload && payload.cache;
    const bits = [];
    if (cache && typeof cache === 'object') {
      bits.push(`cache: ${cache.hit ? 'hit' : 'miss'}`);
      bits.push(`stored: ${cache.stored ? 'yes' : 'no'}`);
      bits.push(`fetched_at: ${cache.fetched_at || 'n/a'}`);
      bits.push(`expires_at: ${cache.expires_at || 'n/a'}`);
    } else {
      bits.push('cache: n/a');
    }
    bits.push(`source: ${payload.source || payload.provider || 'n/a'}`);
    bits.push(`as_of: ${payload.as_of || 'n/a'}`);
    node.appendChild(el('span', 'chart-cache-line', bits.join(' · ')));
  }

  // ── Load flow ────────────────────────────────────────────────────────────

  async function loadChart() {
    const ticker = document.getElementById('chart-ticker').value.trim();
    const period = document.getElementById('chart-period').value;
    const interval = document.getElementById('chart-interval').value;
    const force = document.getElementById('chart-force-refresh').checked;
    if (!ticker) {
      setStatus('Enter a ticker symbol.', 'error');
      return;
    }

    const params = new URLSearchParams({ ticker, period, interval });
    if (force) params.set('force_refresh', 'true');
    const serverIndicators = requestedServerIndicators();
    if (serverIndicators.length) params.set('indicators', serverIndicators.join(','));

    const button = document.getElementById('btn-chart-load');
    button.disabled = true;
    setStatus(`Loading ${ticker.toUpperCase()} (${period}/${interval})…`);
    try {
      const payload = await fetchJson(`/api/market/price-history?${params}`);
      lastPayload = payload;
      renderSeries(payload);
      renderCacheInfo(payload);
      setStatus(`${payload.ticker} — ${payload.ohlc.length} bars (${period}/${interval})`);
    } catch (err) {
      lastPayload = null;
      destroyChart();
      document.getElementById('chart-cache').replaceChildren();
      if (err.status === 400) {
        setStatus(`Invalid request: ${err.message}`, 'error');
      } else if (err.status === 502) {
        setStatus(`Market data provider unavailable: ${err.message}`, 'error');
      } else {
        setStatus(`Failed to load chart: ${err.message}`, 'error');
      }
    } finally {
      button.disabled = false;
    }
  }

  function initCharts() {
    const form = document.getElementById('chart-form');
    if (!form) return;
    if (typeof LightweightCharts === 'undefined') {
      setStatus(
        'Chart library missing — expected /static/vendor/lightweight-charts.standalone.production.js',
        'error'
      );
      return;
    }
    form.addEventListener('submit', (event) => {
      event.preventDefault();
      loadChart();
    });
    SMA_CONFIGS.forEach((cfg) => {
      document.getElementById(cfg.checkboxId).addEventListener('change', () => {
        if (lastPayload) renderOverlays(lastPayload);
      });
    });
    // Server overlays need the extra series from the API, so a toggle re-fetches
    // (base OHLC is cached; overlays are recomputed cheaply server-side).
    const serverBoxIds = [
      ...new Set([
        ...SERVER_LINES.map((cfg) => cfg.checkboxId),
        ...SUBPANES.map((sp) => sp.checkboxId),
      ]),
    ];
    serverBoxIds.forEach((id) => {
      const box = document.getElementById(id);
      if (box) box.addEventListener('change', () => { if (lastPayload) loadChart(); });
    });
  }

  if (document.readyState === 'loading') {
    document.addEventListener('DOMContentLoaded', initCharts);
  } else {
    initCharts();
  }
})();
