/* Fib V2 Mar-Apr-May 2026 dashboard.
 * Data globals: window.TRADES, window.WALKS, window.MONTHLY, window.DAILY, window.HEADLINE
 */

// ============================================================================
// Utils
// ============================================================================
const fmt = {
    r: (v) => (v == null || isNaN(v)) ? '—' : (v >= 0 ? '+' : '') + v.toFixed(2) + 'R',
    pct: (v) => (v == null || isNaN(v)) ? '—' : v.toFixed(1) + '%',
    pf: (v) => (v == null || !isFinite(v)) ? '∞' : v.toFixed(2),
    px: (v, d=4) => (v == null) ? '—' : Number(v).toFixed(d),
    ts: (s) => {
        if (!s) return '—';
        const d = new Date(s.replace(' ', 'T').replace('+00:00', 'Z'));
        return d.toISOString().slice(0,16).replace('T', ' ') + ' UTC';
    },
    secsToUtc: (t) => {
        const d = new Date(t * 1000);
        return d.toISOString().slice(0,16).replace('T', ' ') + ' UTC';
    },
};

const VARIANT_COLORS = {
    'Baseline (no partial-TP)': '#8aa0c0',
    'PTP+1R (lock 0.5R at +1R MFE)': '#4ec0ff',
    'PTP+2R (lock 1.0R at +2R MFE)': '#ff9456',
};

const OUTCOME_COLORS = {
    'TP_FULL': '#4eb98c',
    'PARTIAL_THEN_TP': '#6dffa0',
    'PARTIAL_THEN_BE': '#f0c050',
    'FULL_SL': '#e0584e',
    'TIMEOUT_NO_PARTIAL': '#8aa0c0',
    'PARTIAL_THEN_TIMEOUT': '#a0a0c0',
};
const OUTCOME_ORDER = ['TP_FULL', 'PARTIAL_THEN_TP', 'PARTIAL_THEN_BE', 'FULL_SL', 'TIMEOUT_NO_PARTIAL', 'PARTIAL_THEN_TIMEOUT'];

// ============================================================================
// 1. KPI cards
// ============================================================================
function renderKpiCards() {
    const grid = document.getElementById('kpiGrid');
    const variants = HEADLINE.slice().sort((a, b) => {
        const order = ['Baseline (no partial-TP)', 'PTP+1R (lock 0.5R at +1R MFE)', 'PTP+2R (lock 1.0R at +2R MFE)'];
        return order.indexOf(a.strategy) - order.indexOf(b.strategy);
    });

    grid.innerHTML = variants.map(v => {
        const total = v.full_TP + v.partial_then_TP + v.partial_then_BE + v.full_SL + v.timeout;
        const seg = (k, c) => v[k] > 0 ? `<span style="background:${c};width:${(v[k]/total*100).toFixed(2)}%;" title="${k}: ${v[k]}"></span>` : '';
        const netClass = v.net_R_3mo >= 0 ? 'positive' : 'negative';
        return `
        <div class="kpi-card">
            <h3>${v.strategy}</h3>
            <div class="kpi-row">
                <div class="kpi-cell"><div class="label">Trades</div><div class="value">${v.total_trades}</div></div>
                <div class="kpi-cell"><div class="label">Win rate</div><div class="value">${fmt.pct(v.win_rate_pct)}</div></div>
                <div class="kpi-cell"><div class="label">PF</div><div class="value">${fmt.pf(v.PF)}</div></div>
                <div class="kpi-cell"><div class="label">R:R</div><div class="value">${fmt.pf(v['R:R'])}</div></div>
                <div class="kpi-cell"><div class="label">Net R (3mo)</div><div class="value ${netClass}">${fmt.r(v.net_R_3mo)}</div></div>
                <div class="kpi-cell"><div class="label">Locked R</div><div class="value positive">+${v.partial_locked_R.toFixed(1)}R</div></div>
            </div>
            <div class="label" style="font-size:9px;color:var(--text-dim);text-transform:uppercase;letter-spacing:0.5px;">Outcome mix</div>
            <div class="kpi-stack">
                ${seg('full_TP', OUTCOME_COLORS.TP_FULL)}
                ${seg('partial_then_TP', OUTCOME_COLORS.PARTIAL_THEN_TP)}
                ${seg('partial_then_BE', OUTCOME_COLORS.PARTIAL_THEN_BE)}
                ${seg('full_SL', OUTCOME_COLORS.FULL_SL)}
                ${seg('timeout', OUTCOME_COLORS.TIMEOUT_NO_PARTIAL)}
            </div>
            <div class="kpi-stack-legend">
                <span><i style="background:${OUTCOME_COLORS.TP_FULL};"></i>full TP: ${v.full_TP}</span>
                <span><i style="background:${OUTCOME_COLORS.PARTIAL_THEN_TP};"></i>part→TP: ${v.partial_then_TP}</span>
                <span><i style="background:${OUTCOME_COLORS.PARTIAL_THEN_BE};"></i>part→BE: ${v.partial_then_BE}</span>
                <span><i style="background:${OUTCOME_COLORS.FULL_SL};"></i>full SL: ${v.full_SL}</span>
                <span><i style="background:${OUTCOME_COLORS.TIMEOUT_NO_PARTIAL};"></i>timeout: ${v.timeout}</span>
            </div>
        </div>`;
    }).join('');
}

// ============================================================================
// 2. Monthly chart (Chart.js bar)
// ============================================================================
let monthlyChartObj = null;
function renderMonthlyChart(metric = 'net_R') {
    const ctx = document.getElementById('monthlyChart').getContext('2d');
    const months = [...new Set(MONTHLY.map(r => r.month))].sort();
    const seriesKeys = [...new Set(MONTHLY.map(r => `${r.strategy} (${r.symbol})`))];
    const datasets = seriesKeys.map((key, i) => {
        const [strat, sym] = key.match(/^(.*) \((.*)\)$/).slice(1, 3);
        return {
            label: key,
            data: months.map(m => {
                const r = MONTHLY.find(x => x.month === m && x.strategy === strat && x.symbol === sym);
                return r ? r[metric] : 0;
            }),
            backgroundColor: (VARIANT_COLORS[strat] || '#888') + (sym.startsWith('XAU') ? 'cc' : '70'),
            borderColor: VARIANT_COLORS[strat] || '#888',
            borderWidth: 1,
        };
    });
    if (monthlyChartObj) monthlyChartObj.destroy();
    monthlyChartObj = new Chart(ctx, {
        type: 'bar',
        data: { labels: months, datasets },
        options: {
            responsive: true, maintainAspectRatio: false,
            scales: {
                x: { ticks: { color: '#8a91a0' }, grid: { color: '#2d323d' } },
                y: { ticks: { color: '#8a91a0' }, grid: { color: '#2d323d' },
                     title: { display: true, text: metric, color: '#8a91a0' } },
            },
            plugins: {
                legend: { labels: { color: '#d8dadc', font: { size: 10 } } },
                tooltip: { callbacks: {
                    label: (c) => `${c.dataset.label}: ${metric === 'net_R' ? fmt.r(c.parsed.y) : c.parsed.y}`,
                }},
            },
        },
    });
}
function wireMonthlyControls() {
    document.querySelectorAll('#monthly .controls button').forEach(btn => {
        btn.addEventListener('click', (e) => {
            document.querySelectorAll('#monthly .controls button').forEach(b => b.classList.remove('active'));
            e.target.classList.add('active');
            renderMonthlyChart(e.target.dataset.metric);
        });
    });
}

// ============================================================================
// 3. Outcome distribution (3 doughnuts)
// ============================================================================
function renderOutcomeCharts() {
    const container = document.getElementById('outcomeCharts');
    const order = ['Baseline (no partial-TP)', 'PTP+1R (lock 0.5R at +1R MFE)', 'PTP+2R (lock 1.0R at +2R MFE)'];
    container.innerHTML = order.map((strat, i) => `
        <div class="chart-card">
            <h3 style="font-size:12px;margin:0 0 8px;color:${VARIANT_COLORS[strat]};">${strat}</h3>
            <div class="chart-wrap short"><canvas id="outcome${i}"></canvas></div>
        </div>`).join('');

    order.forEach((strat, i) => {
        const trades = TRADES.filter(t => t.strategy === strat);
        const counts = {};
        OUTCOME_ORDER.forEach(o => counts[o] = 0);
        trades.forEach(t => { counts[t.outcome] = (counts[t.outcome] || 0) + 1; });
        const labels = OUTCOME_ORDER.filter(o => counts[o] > 0);
        const data = labels.map(o => counts[o]);
        const colors = labels.map(o => OUTCOME_COLORS[o] || '#888');
        const ctx = document.getElementById(`outcome${i}`).getContext('2d');
        new Chart(ctx, {
            type: 'doughnut',
            data: { labels, datasets: [{ data, backgroundColor: colors, borderColor: '#1a1d23', borderWidth: 2 }] },
            options: {
                responsive: true, maintainAspectRatio: false,
                plugins: {
                    legend: { position: 'bottom', labels: { color: '#d8dadc', font: { size: 10 }, boxWidth: 10 } },
                    tooltip: { callbacks: { label: (c) => `${c.label}: ${c.parsed} (${(c.parsed/trades.length*100).toFixed(1)}%)` } },
                },
            },
        });
    });
}

// ============================================================================
// 5. Equity curve (Chart.js line)
// ============================================================================
function renderEquityCurve() {
    const ctx = document.getElementById('equityChart').getContext('2d');
    const variants = [...new Set(TRADES.map(t => t.strategy))];
    const sortedAll = TRADES.slice().sort((a, b) => a.entry_ts.localeCompare(b.entry_ts));
    const labels = sortedAll.map(t => t.entry_ts.slice(0, 10));

    const datasets = variants.map(strat => {
        let cum = 0;
        const data = sortedAll.map(t => {
            if (t.strategy === strat) cum += t.net_r;
            return cum;
        });
        return {
            label: strat,
            data,
            borderColor: VARIANT_COLORS[strat] || '#888',
            backgroundColor: 'transparent',
            tension: 0.1, pointRadius: 0, borderWidth: 2,
        };
    });

    new Chart(ctx, {
        type: 'line',
        data: { labels, datasets },
        options: {
            responsive: true, maintainAspectRatio: false,
            scales: {
                x: { ticks: { color: '#8a91a0', maxTicksLimit: 12 }, grid: { color: '#2d323d' } },
                y: { ticks: { color: '#8a91a0' }, grid: { color: '#2d323d' },
                     title: { display: true, text: 'Cumulative net R', color: '#8a91a0' } },
            },
            plugins: {
                legend: { labels: { color: '#d8dadc', font: { size: 10 } } },
                tooltip: { callbacks: { label: (c) => `${c.dataset.label}: ${fmt.r(c.parsed.y)}` } },
            },
        },
    });
}

// ============================================================================
// 7. R histogram
// ============================================================================
function renderHistogram() {
    const ctx = document.getElementById('histogramChart').getContext('2d');
    const binSize = 0.5;
    // Bucket -2.0 → +6.0 by 0.5
    const min = -2.0, max = 6.0;
    const bins = [];
    for (let b = min; b <= max; b += binSize) bins.push(parseFloat(b.toFixed(1)));
    const labels = bins.map(b => `${b.toFixed(1)}`);

    const variants = [...new Set(TRADES.map(t => t.strategy))];
    const datasets = variants.map(strat => {
        const data = bins.map(b => 0);
        TRADES.filter(t => t.strategy === strat).forEach(t => {
            const r = t.net_r;
            if (r < min || r > max) return;
            const idx = Math.floor((r - min) / binSize);
            if (idx >= 0 && idx < data.length) data[idx]++;
        });
        return {
            label: strat, data,
            backgroundColor: (VARIANT_COLORS[strat] || '#888') + 'aa',
            borderColor: VARIANT_COLORS[strat] || '#888',
            borderWidth: 1,
        };
    });

    new Chart(ctx, {
        type: 'bar',
        data: { labels, datasets },
        options: {
            responsive: true, maintainAspectRatio: false,
            scales: {
                x: { ticks: { color: '#8a91a0' }, grid: { color: '#2d323d' },
                     title: { display: true, text: 'Net R bucket', color: '#8a91a0' } },
                y: { ticks: { color: '#8a91a0' }, grid: { color: '#2d323d' },
                     title: { display: true, text: 'Trade count', color: '#8a91a0' } },
            },
            plugins: {
                legend: { labels: { color: '#d8dadc', font: { size: 10 } } },
            },
        },
    });
}

// ============================================================================
// 4. Daily heatmap (Chart.js matrix)
// ============================================================================
function renderHeatmap() {
    const ctx = document.getElementById('heatmapChart').getContext('2d');
    const rows = [...new Set(DAILY.map(d => `${d.strategy.split(' ')[0]}|${d.symbol}`))].sort();
    const days = [...new Set(DAILY.map(d => d.day))].sort();

    const data = [];
    const allNet = DAILY.map(d => d.net_R);
    const absMax = Math.max(Math.abs(Math.min(...allNet)), Math.abs(Math.max(...allNet)), 0.001);
    DAILY.forEach(d => {
        const rowKey = `${d.strategy.split(' ')[0]}|${d.symbol}`;
        data.push({
            x: d.day, y: rowKey,
            v: d.net_R, n: d.total_trades, wr: d.win_rate_pct,
        });
    });

    new Chart(ctx, {
        type: 'matrix',
        data: { datasets: [{
            label: 'Daily net R',
            data,
            backgroundColor: (c) => {
                const v = c.raw && c.raw.v;
                if (v == null) return '#21252d';
                const t = Math.min(Math.abs(v) / absMax, 1);
                if (v > 0) return `rgba(78, 185, 140, ${0.2 + t * 0.8})`;
                return `rgba(224, 88, 78, ${0.2 + t * 0.8})`;
            },
            borderColor: '#1a1d23', borderWidth: 1,
            width: ({chart}) => (chart.chartArea || {}).width / days.length - 2,
            height: ({chart}) => (chart.chartArea || {}).height / rows.length - 2,
        }] },
        options: {
            responsive: true, maintainAspectRatio: false,
            scales: {
                x: { type: 'category', labels: days,
                     ticks: { color: '#8a91a0', maxRotation: 90, font: { size: 9 } },
                     grid: { display: false } },
                y: { type: 'category', labels: rows, offset: true,
                     ticks: { color: '#8a91a0', font: { size: 10 } },
                     grid: { display: false } },
            },
            plugins: {
                legend: { display: false },
                tooltip: { callbacks: {
                    title: (items) => items[0].raw.y + ' on ' + items[0].raw.x,
                    label: (c) => [`Net R: ${fmt.r(c.raw.v)}`, `Trades: ${c.raw.n}`, `WR: ${fmt.pct(c.raw.wr)}`],
                } },
            },
        },
    });
}

// ============================================================================
// 6. Trade table
// ============================================================================
let tableState = {
    sort: 'entry_ts', dir: 'asc',
    filters: { strategy: null, symbol: null, outcome: null },
    search: '',
};

function renderFilterChips() {
    const chips = document.getElementById('filterChips');
    const opts = [
        ['strategy', 'All', null, 'All strategies'],
        ['strategy', 'Baseline', 'Baseline (no partial-TP)', 'Baseline only'],
        ['strategy', 'PTP+1R', 'PTP+1R (lock 0.5R at +1R MFE)', 'PTP+1R only'],
        ['strategy', 'PTP+2R', 'PTP+2R (lock 1.0R at +2R MFE)', 'PTP+2R only'],
        ['symbol', 'XAU', 'XAUUSD.ecn', 'XAU only'],
        ['symbol', 'EUR', 'EURUSD.ecn', 'EUR only'],
    ];
    chips.innerHTML = opts.map(([dim, label, val, title]) => {
        const active = tableState.filters[dim] === val ? 'active' : '';
        return `<button class="chip ${active}" data-dim="${dim}" data-val="${val == null ? '' : val}" title="${title}">${label}</button>`;
    }).join('');
    chips.querySelectorAll('.chip').forEach(c => c.addEventListener('click', (e) => {
        const dim = e.target.dataset.dim;
        const val = e.target.dataset.val || null;
        tableState.filters[dim] = tableState.filters[dim] === val ? null : val;
        renderFilterChips();
        renderTradeTable();
    }));
}

function filteredTrades() {
    return TRADES.filter(t => {
        for (const dim of ['strategy', 'symbol', 'outcome']) {
            const f = tableState.filters[dim];
            if (f && t[dim] !== f) return false;
        }
        if (tableState.search) {
            const s = tableState.search.toLowerCase();
            if (!(t.trade_ref + ' ' + t.trade_id).toLowerCase().includes(s)) return false;
        }
        return true;
    });
}

function renderTradeTable() {
    const tbody = document.getElementById('tradeTbody');
    let rows = filteredTrades();
    rows = rows.slice().sort((a, b) => {
        const k = tableState.sort;
        let va = a[k], vb = b[k];
        if (typeof va === 'string') va = va || '';
        if (typeof vb === 'string') vb = vb || '';
        if (va === vb) return 0;
        return (va > vb ? 1 : -1) * (tableState.dir === 'asc' ? 1 : -1);
    });

    document.getElementById('tradeCount').textContent = `${rows.length} trades`;

    tbody.innerHTML = rows.map(t => {
        const netCls = t.net_r >= 0 ? 'positive' : 'negative';
        const partCls = t.partial_r_locked > 0 ? 'positive' : '';
        const outcomeKey = t.outcome.toLowerCase();
        return `<tr>
            <td title="${t.trade_id}">${t.trade_ref.slice(0, 20)}…</td>
            <td>${t.strategy.split(' ')[0]}</td>
            <td>${t.symbol}</td>
            <td><span class="pill ${t.side === 1 ? 'long' : 'short'}">${t.side_label}</span></td>
            <td>${fmt.ts(t.entry_ts)}</td>
            <td>${fmt.ts(t.exit_ts)}</td>
            <td class="num">${t.bars_held ?? '—'}</td>
            <td><span class="pill ${outcomeKey}">${t.outcome.replace(/_/g, ' ')}</span></td>
            <td class="num ${partCls}">${t.partial_r_locked > 0 ? '+' + t.partial_r_locked.toFixed(2) + 'R' : '—'}</td>
            <td class="num ${netCls}">${fmt.r(t.net_r)}</td>
            <td>${t.regime_at_entry || '—'}</td>
            <td><button class="btn-sim" data-tid="${t.trade_id}">Simulate ▶</button></td>
        </tr>`;
    }).join('');

    tbody.querySelectorAll('.btn-sim').forEach(b => b.addEventListener('click', (e) => {
        openSimulator(e.target.dataset.tid);
    }));
}

function wireTableSort() {
    document.querySelectorAll('#tradeTable th[data-sort]').forEach(th => {
        th.addEventListener('click', () => {
            const k = th.dataset.sort;
            if (tableState.sort === k) tableState.dir = tableState.dir === 'asc' ? 'desc' : 'asc';
            else { tableState.sort = k; tableState.dir = 'asc'; }
            document.querySelectorAll('#tradeTable th .sort-ind').forEach(s => s.remove());
            const ind = document.createElement('span');
            ind.className = 'sort-ind';
            ind.textContent = tableState.dir === 'asc' ? '▲' : '▼';
            th.appendChild(ind);
            renderTradeTable();
        });
    });
    document.getElementById('tradeSearch').addEventListener('input', (e) => {
        tableState.search = e.target.value;
        renderTradeTable();
    });
}

// ============================================================================
// Simulator
// ============================================================================
let simChart = null;
let simCandleSeries = null;
let simState = {
    trade: null, bars: [], idx: 0, playing: false, timer: null, speed: 10,
    priceLines: [], markers: [],
};

function openSimulator(tradeId) {
    const trade = TRADES.find(t => t.trade_id === tradeId);
    const bars = WALKS[tradeId] || [];
    if (!trade || bars.length === 0) {
        alert('No data for trade ' + tradeId);
        return;
    }
    simState.trade = trade;
    simState.bars = bars;
    simState.idx = 0;
    simState.playing = false;
    if (simState.timer) { clearInterval(simState.timer); simState.timer = null; }

    // Header
    document.getElementById('simRef').textContent = trade.trade_ref;
    document.getElementById('simStrategy').textContent = trade.strategy;
    document.getElementById('simSymbol').textContent = trade.symbol;
    document.getElementById('simSidePill').textContent = trade.side_label;
    document.getElementById('simSidePill').className = 'pill ' + (trade.side === 1 ? 'long' : 'short');
    document.getElementById('simRegime').textContent = trade.regime_at_entry || '—';
    document.getElementById('simOutcomePill').textContent = trade.outcome.replace(/_/g, ' ');
    document.getElementById('simOutcomePill').className = 'pill ' + trade.outcome.toLowerCase();

    // Meta strip
    document.getElementById('metaEntry').textContent = fmt.ts(trade.entry_ts);
    document.getElementById('metaExit').textContent = fmt.ts(trade.exit_ts);
    document.getElementById('metaBars').textContent = trade.bars_held;
    const decimals = trade.symbol.startsWith('XAU') ? 2 : 5;
    document.getElementById('metaEntryPx').textContent = fmt.px(trade.entry_price, decimals);
    document.getElementById('metaSlTp').textContent = `${fmt.px(trade.stop_price, decimals)} / ${fmt.px(trade.tp_price, decimals)}`;
    const netCell = document.getElementById('metaNetR');
    netCell.textContent = fmt.r(trade.net_r);
    netCell.className = 'value ' + (trade.net_r >= 0 ? 'positive' : 'negative');

    // Counter
    document.getElementById('barIdx').textContent = 0;
    document.getElementById('barTotal').textContent = bars.length;
    document.getElementById('barTs').textContent = '—';

    // Init chart
    setupSimChart();
    drawFibLines();

    // Show modal
    document.getElementById('simModal').classList.add('open');
}

function setupSimChart() {
    const container = document.getElementById('simChart');
    container.innerHTML = '';
    if (simChart) { try { simChart.remove(); } catch (e) {} simChart = null; }

    simChart = LightweightCharts.createChart(container, {
        layout: { background: { color: '#21252d' }, textColor: '#d8dadc' },
        grid: { vertLines: { color: '#2d323d' }, horzLines: { color: '#2d323d' } },
        timeScale: { timeVisible: true, secondsVisible: false, rightOffset: 5, barSpacing: 8 },
        rightPriceScale: { borderColor: '#2d323d' },
        crosshair: { mode: 1 },
    });
    simCandleSeries = simChart.addCandlestickSeries({
        upColor: '#4eb98c', downColor: '#e0584e',
        borderUpColor: '#4eb98c', borderDownColor: '#e0584e',
        wickUpColor: '#4eb98c', wickDownColor: '#e0584e',
    });
}

function drawFibLines() {
    const t = simState.trade;
    simState.priceLines = [];
    simState.markers = [];

    const addLine = (price, color, style, title) => {
        if (price == null || isNaN(price)) return;
        simState.priceLines.push(simCandleSeries.createPriceLine({
            price, color, lineWidth: 1,
            lineStyle: style, axisLabelVisible: true, title,
        }));
    };
    const SOLID = 0, DASHED = 2;
    addLine(t.fib_H,             '#888888', SOLID,  'fib_H');
    addLine(t.fib_L,             '#888888', SOLID,  'fib_L');
    addLine(t.fib_382,           '#38d4cf', DASHED, '0.382');
    addLine(t.fib_786,           '#38d4cf', DASHED, '0.786');
    addLine(t.fib_100,           '#888888', DASHED, 'fib_100');
    addLine(t.entry_price,       '#f0c050', SOLID,  'Entry');
    addLine(t.stop_price,        '#e0584e', SOLID,  'SL');
    addLine(t.tp_price,          '#4eb98c', SOLID,  'TP 1.618');
    if (t.ptp_trigger_price != null) {
        addLine(t.ptp_trigger_price, '#ff9456', DASHED, 'PTP trigger');
    }
}

function simStep() {
    if (simState.idx >= simState.bars.length) {
        simPause();
        addExitMarker();
        return;
    }
    const bar = simState.bars[simState.idx];
    simCandleSeries.update({
        time: bar.t, open: bar.o, high: bar.h, low: bar.l, close: bar.c,
    });
    simState.idx++;

    document.getElementById('barIdx').textContent = simState.idx;
    document.getElementById('barTs').textContent = fmt.secsToUtc(bar.t);
    const d = simState.trade.symbol.startsWith('XAU') ? 2 : 5;
    document.getElementById('rOHLC').textContent = `${bar.o.toFixed(d)} / ${bar.h.toFixed(d)} / ${bar.l.toFixed(d)} / ${bar.c.toFixed(d)}`;
    document.getElementById('rMfe').textContent = fmt.r(bar.mfe);
    document.getElementById('rMae').textContent = fmt.r(bar.mae);
    document.getElementById('rUnr').textContent = fmt.r(bar.unr);
    document.getElementById('rDS').textContent = fmt.r(bar.ds);
    document.getElementById('rDT').textContent = bar.dt == null ? '—' : fmt.r(bar.dt);

    // Entry marker on first bar
    if (simState.idx === 1) {
        simState.markers.push({
            time: bar.t, position: simState.trade.side === 1 ? 'belowBar' : 'aboveBar',
            color: '#f0c050', shape: simState.trade.side === 1 ? 'arrowUp' : 'arrowDown',
            text: 'Entry',
        });
        simCandleSeries.setMarkers(simState.markers);
    }
    // Partial-armed marker
    if (bar.pa === 1) {
        simState.markers.push({
            time: bar.t, position: 'inBar',
            color: '#ff9456', shape: 'circle', text: 'Partial ✦',
        });
        simCandleSeries.setMarkers(simState.markers);
    }

    // Auto-scroll: keep latest visible
    if (simState.idx % 5 === 0) {
        simChart.timeScale().scrollToRealTime();
    }

    if (simState.idx >= simState.bars.length) {
        simPause();
        addExitMarker();
    }
}

function addExitMarker() {
    const t = simState.trade;
    const lastBar = simState.bars[simState.bars.length - 1];
    let shape = 'square', color = '#8aa0c0', text = 'Exit';
    if (t.outcome === 'TP_FULL' || t.outcome === 'PARTIAL_THEN_TP') {
        shape = 'circle'; color = '#4eb98c'; text = '✓ TP';
    } else if (t.outcome === 'FULL_SL') {
        shape = 'square'; color = '#e0584e'; text = '✗ SL';
    } else if (t.outcome === 'PARTIAL_THEN_BE') {
        shape = 'square'; color = '#f0c050'; text = 'BE';
    } else {
        shape = 'square'; color = '#8aa0c0'; text = 'Timeout';
    }
    simState.markers.push({
        time: lastBar.t, position: t.side === 1 ? 'aboveBar' : 'belowBar',
        color, shape, text,
    });
    simCandleSeries.setMarkers(simState.markers);
}

function simPlay() {
    if (simState.playing) return;
    simState.playing = true;
    document.getElementById('btnPlay').textContent = '⏸ Pause';
    document.getElementById('btnPlay').classList.remove('play');
    document.getElementById('btnPlay').classList.add('pause');
    const interval = Math.max(16, 1000 / simState.speed);
    simState.timer = setInterval(simStep, interval);
}
function simPause() {
    simState.playing = false;
    if (simState.timer) { clearInterval(simState.timer); simState.timer = null; }
    document.getElementById('btnPlay').textContent = '▶ Play';
    document.getElementById('btnPlay').classList.add('play');
    document.getElementById('btnPlay').classList.remove('pause');
}
function simReset() {
    simPause();
    simState.idx = 0;
    simState.markers = [];
    if (simCandleSeries) simCandleSeries.setData([]);
    if (simCandleSeries) simCandleSeries.setMarkers([]);
    document.getElementById('barIdx').textContent = 0;
    document.getElementById('barTs').textContent = '—';
    ['rOHLC','rMfe','rMae','rUnr','rDS','rDT'].forEach(id => document.getElementById(id).textContent = '—');
}

function wireSimulator() {
    document.getElementById('simClose').addEventListener('click', () => {
        simPause();
        document.getElementById('simModal').classList.remove('open');
    });
    document.getElementById('btnPlay').addEventListener('click', () => {
        if (simState.playing) simPause(); else simPlay();
    });
    document.getElementById('btnStep').addEventListener('click', simStep);
    document.getElementById('btnReset').addEventListener('click', simReset);
    document.getElementById('speedSlider').addEventListener('input', (e) => {
        simState.speed = parseInt(e.target.value);
        document.getElementById('speedLabel').textContent = simState.speed + '×';
        if (simState.playing) {
            simPause();
            simPlay();
        }
    });
    // Click on overlay (outside modal) to close
    document.getElementById('simModal').addEventListener('click', (e) => {
        if (e.target.id === 'simModal') {
            simPause();
            document.getElementById('simModal').classList.remove('open');
        }
    });
    // Esc to close
    document.addEventListener('keydown', (e) => {
        if (e.key === 'Escape' && document.getElementById('simModal').classList.contains('open')) {
            simPause();
            document.getElementById('simModal').classList.remove('open');
        }
    });
}

// ============================================================================
// Nav active state
// ============================================================================
function wireNav() {
    const links = document.querySelectorAll('.nav a');
    const sections = [...links].map(a => document.querySelector(a.getAttribute('href')));
    window.addEventListener('scroll', () => {
        let active = sections[0];
        for (const s of sections) {
            if (s && s.getBoundingClientRect().top < 100) active = s;
        }
        links.forEach(a => a.classList.toggle('active', a.getAttribute('href') === '#' + active.id));
    });
}

// ============================================================================
// Boot
// ============================================================================
document.addEventListener('DOMContentLoaded', () => {
    renderKpiCards();
    renderMonthlyChart();
    wireMonthlyControls();
    renderOutcomeCharts();
    renderHeatmap();
    renderEquityCurve();
    renderFilterChips();
    renderTradeTable();
    wireTableSort();
    renderHistogram();
    wireSimulator();
    wireNav();
    console.log(`Loaded ${TRADES.length} trades, ${Object.keys(WALKS).length} walks groups`);
});
