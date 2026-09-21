/**
 * XAUUSD AI Trading Station — Frontend Application Script
 * 
 * High-performance state synchronization:
 * - Real MT5 Candlestick Chart via Lightweight Charts
 * - WebSocket streaming + 3s smart polling
 * - Direct MT5 1-Click order execution & position closure
 * - Neural Market Regime & Macro AI Sentiment gauges
 */

// ── Global State ─────────────────────────────────────────────────────────
let ws = null;
let chart = null;
let candleSeries = null;
let currentTimeframe = 'H1';
let currentPrice = 0;
let previousPrice = 0;
let reconnectAttempts = 0;
const MAX_RECONNECT = 10;
const POLL_INTERVAL = 3000; // 3 seconds real-time fallback
let showPositionsOnChart = true;
let chartPriceLines = [];
let lastCachedPositions = [];
let lastCachedPending = [];

// ── Initialization ──────────────────────────────────────────────────────
document.addEventListener('DOMContentLoaded', () => {
    initChart();
    loadChartData(currentTimeframe);
    connectWebSocket();
    refreshAll();
    pollBarometer();

    // Regular data polling fallback
    setInterval(refreshAll, POLL_INTERVAL);

    // Auto-update live candle every 3 seconds (No manual page refresh needed!)
    setInterval(pollLiveCandle, 3000);

    // Auto-poll barometer (24H range, spread, ATR, RSI) every 4 seconds
    setInterval(pollBarometer, 4000);

    // Start live candle close countdown timer
    startCountdownTimer();

    // Timeframe selector listeners
    document.querySelectorAll('.tf-btn').forEach(btn => {
        btn.addEventListener('click', (e) => {
            const tf = e.target.getAttribute('data-tf');
            if (tf && tf !== currentTimeframe) {
                document.querySelectorAll('.tf-btn').forEach(b => b.classList.remove('active'));
                e.target.classList.add('active');
                currentTimeframe = tf;
                loadChartData(currentTimeframe);
            }
        });
    });
});

// ── TradingView Lightweight Chart ───────────────────────────────────────
function initChart() {
    const container = document.getElementById('chart-viewport');
    if (!container || typeof LightweightCharts === 'undefined') return;

    chart = LightweightCharts.createChart(container, {
        width: container.clientWidth,
        height: container.clientHeight || 440,
        layout: {
            background: { type: 'solid', color: 'transparent' },
            textColor: '#94A3B8',
            fontFamily: "'JetBrains Mono', monospace",
            fontSize: 11,
        },
        grid: {
            vertLines: { color: 'rgba(255, 255, 255, 0.03)' },
            horzLines: { color: 'rgba(255, 255, 255, 0.03)' },
        },
        crosshair: {
            mode: LightweightCharts.CrosshairMode.Normal,
            vertLine: { color: 'rgba(245, 158, 11, 0.4)', style: 2, width: 1 },
            horzLine: { color: 'rgba(245, 158, 11, 0.4)', style: 2, width: 1 },
        },
        timeScale: {
            borderColor: 'rgba(255, 255, 255, 0.08)',
            timeVisible: true,
            secondsVisible: false,
        },
        rightPriceScale: {
            borderColor: 'rgba(255, 255, 255, 0.08)',
            autoScale: true,
            scaleMargins: {
                top: 0.1,
                bottom: 0.1,
            },
        },
    });

    candleSeries = chart.addCandlestickSeries({
        upColor: '#10B981',
        downColor: '#EF4444',
        borderUpColor: '#10B981',
        borderDownColor: '#EF4444',
        wickUpColor: '#10B981',
        wickDownColor: '#EF4444',
    });

    // Crosshair legend update
    chart.subscribeCrosshairMove(param => {
        if (!param || !param.time || !param.seriesData) return;
        const data = param.seriesData.get(candleSeries);
        if (data) {
            setText('legend-o', `$${data.open.toFixed(2)}`);
            setText('legend-h', `$${data.high.toFixed(2)}`);
            setText('legend-l', `$${data.low.toFixed(2)}`);
            setText('legend-c', `$${data.close.toFixed(2)}`);
        }
    });

    // Responsive auto-resize
    const resizeObserver = new ResizeObserver(entries => {
        for (let entry of entries) {
            chart.applyOptions({
                width: entry.contentRect.width,
                height: entry.contentRect.height,
            });
        }
    });
    resizeObserver.observe(container);
}

async function loadChartData(tf) {
    const data = await fetchJSON(`/api/chart?timeframe=${tf}&count=150`);
    if (data && Array.isArray(data) && data.length > 0 && candleSeries) {
        candleSeries.setData(data);
        const last = data[data.length - 1];
        if (last) {
            setText('legend-o', `$${last.open.toFixed(2)}`);
            setText('legend-h', `$${last.high.toFixed(2)}`);
            setText('legend-l', `$${last.low.toFixed(2)}`);
            setText('legend-c', `$${last.close.toFixed(2)}`);
            updatePriceDisplay(last.close);
        }
        // Re-apply open position lines on the newly loaded timeframe
        updateChartPositionOverlays();
    }
}

// ── Chart Position & Order Visual Overlay Engine ────────────────────────
function togglePositionsOverlay() {
    showPositionsOnChart = !showPositionsOnChart;
    const btn = document.getElementById('btn-toggle-pos-overlay');
    const label = document.getElementById('overlay-status-text');

    if (btn && label) {
        if (showPositionsOnChart) {
            btn.className = 'position-overlay-toggle active';
            label.textContent = 'Positions: ON';
        } else {
            btn.className = 'position-overlay-toggle off';
            label.textContent = 'Positions: OFF';
        }
    }

    updateChartPositionOverlays(lastCachedPositions, lastCachedPending);
}

function updateChartPositionOverlays(positions, pendingOrders) {
    if (Array.isArray(positions)) lastCachedPositions = positions;
    if (Array.isArray(pendingOrders)) lastCachedPending = pendingOrders;

    if (!candleSeries || typeof LightweightCharts === 'undefined') return;

    // Clear existing price lines
    chartPriceLines.forEach(line => {
        try {
            candleSeries.removePriceLine(line);
        } catch (e) {
            console.debug('Error removing price line:', e);
        }
    });
    chartPriceLines = [];

    if (!showPositionsOnChart) return;

    // 1. Render Active Open Positions (Entry, SL, TP)
    if (Array.isArray(lastCachedPositions)) {
        lastCachedPositions.forEach(pos => {
            if (!pos.price_open) return;
            const isBuy = (pos.type || '').toUpperCase().includes('BUY');
            const entryColor = isBuy ? '#3B82F6' : '#F97316';

            // Entry Price Line
            const entryLine = candleSeries.createPriceLine({
                price: pos.price_open,
                color: entryColor,
                lineWidth: 2,
                lineStyle: LightweightCharts.LineStyle.Solid,
                axisLabelVisible: true,
                title: `OPEN ${pos.type} ${pos.volume?.toFixed(2)} (#${pos.ticket})`,
            });
            chartPriceLines.push(entryLine);

            // Stop Loss Line
            if (pos.sl && pos.sl > 0) {
                const slLine = candleSeries.createPriceLine({
                    price: pos.sl,
                    color: '#EF4444',
                    lineWidth: 1,
                    lineStyle: LightweightCharts.LineStyle.Dashed,
                    axisLabelVisible: true,
                    title: `SL #${pos.ticket} ($${pos.sl.toFixed(2)})`,
                });
                chartPriceLines.push(slLine);
            }

            // Take Profit Line
            if (pos.tp && pos.tp > 0) {
                const tpLine = candleSeries.createPriceLine({
                    price: pos.tp,
                    color: '#10B981',
                    lineWidth: 1,
                    lineStyle: LightweightCharts.LineStyle.Dashed,
                    axisLabelVisible: true,
                    title: `TP #${pos.ticket} ($${pos.tp.toFixed(2)})`,
                });
                chartPriceLines.push(tpLine);
            }
        });
    }

    // 2. Render Scheduled Pending Orders (Limit, SL, TP)
    if (Array.isArray(lastCachedPending)) {
        lastCachedPending.forEach(ord => {
            if (!ord.price || ord.price <= 0) return;
            const ordLine = candleSeries.createPriceLine({
                price: ord.price,
                color: '#F59E0B',
                lineWidth: 1,
                lineStyle: LightweightCharts.LineStyle.Dotted,
                axisLabelVisible: true,
                title: `LIMIT ${ord.type} ${ord.volume?.toFixed(2)} (#${ord.ticket})`,
            });
            chartPriceLines.push(ordLine);

            if (ord.sl && ord.sl > 0) {
                const ordSl = candleSeries.createPriceLine({
                    price: ord.sl,
                    color: 'rgba(239, 68, 68, 0.75)',
                    lineWidth: 1,
                    lineStyle: LightweightCharts.LineStyle.Dotted,
                    axisLabelVisible: true,
                    title: `LIMIT SL #${ord.ticket}`,
                });
                chartPriceLines.push(ordSl);
            }

            if (ord.tp && ord.tp > 0) {
                const ordTp = candleSeries.createPriceLine({
                    price: ord.tp,
                    color: 'rgba(16, 185, 129, 0.75)',
                    lineWidth: 1,
                    lineStyle: LightweightCharts.LineStyle.Dotted,
                    axisLabelVisible: true,
                    title: `LIMIT TP #${ord.ticket}`,
                });
                chartPriceLines.push(ordTp);
            }
        });
    }
}

// ── Live Candlestick Real-Time Auto-Updating Engine ─────────────────────
async function pollLiveCandle() {
    if (!candleSeries) return;
    try {
        const data = await fetchJSON(`/api/chart?timeframe=${currentTimeframe}&count=3`);
        if (data && Array.isArray(data) && data.length > 0) {
            const latest = data[data.length - 1];
            if (latest) {
                candleSeries.update(latest);
                setText('legend-o', `$${latest.open.toFixed(2)}`);
                setText('legend-h', `$${latest.high.toFixed(2)}`);
                setText('legend-l', `$${latest.low.toFixed(2)}`);
                setText('legend-c', `$${latest.close.toFixed(2)}`);
                updatePriceDisplay(latest.close);
            }
        }
    } catch (e) {
        console.debug('Live candle poll error:', e);
    }
}

// ── Technical Barometer Real-Time Engine ────────────────────────────────
async function pollBarometer() {
    try {
        const b = await fetchJSON('/api/barometer');
        if (b && b.success) {
            setText('dock-low', `$${b.low_24h.toFixed(2)}`);
            setText('dock-high', `$${b.high_24h.toFixed(2)}`);
            setText('dock-spread', `${(b.spread / 10).toFixed(1)} pips`);
            setText('dock-atr', `$${b.atr.toFixed(2)}`);

            const rsiEl = document.getElementById('dock-rsi');
            if (rsiEl) {
                const rsiZone = b.rsi >= 70 ? 'OVERBOUGHT' : b.rsi <= 30 ? 'OVERSOLD' : 'NEUTRAL';
                const zoneClass = b.rsi >= 70 ? 'loss' : b.rsi <= 30 ? 'profit' : '';
                rsiEl.innerHTML = `${b.rsi.toFixed(1)} <span class="badge-tag ${zoneClass}">${rsiZone}</span>`;
            }

            const pin = document.getElementById('dock-range-pin');
            const fill = document.getElementById('dock-range-fill');
            if (pin) pin.style.left = `${b.pct_in_range}%`;
            if (fill) fill.style.width = `${b.pct_in_range}%`;
        }
    } catch (e) {
        console.debug('Barometer poll error:', e);
    }
}

// ── Live Candle Close Countdown Timer ───────────────────────────────────
function startCountdownTimer() {
    setInterval(() => {
        const nowSec = Math.floor(Date.now() / 1000);
        const tfSeconds = {
            'M5': 300,
            'M15': 900,
            'H1': 3600,
            'H4': 14400,
            'D1': 86400
        };
        const totalSec = tfSeconds[currentTimeframe] || 3600;
        const remaining = totalSec - (nowSec % totalSec);

        const mins = Math.floor(remaining / 60);
        const secs = remaining % 60;
        const formatted = `${String(mins).padStart(2, '0')}:${String(secs).padStart(2, '0')}`;

        setText('dock-countdown', formatted);

        // When countdown expires, trigger a full live candle sync
        if (remaining === totalSec - 1) {
            pollLiveCandle();
        }
    }, 1000);
}

// ── WebSocket Real-time Engine ──────────────────────────────────────────
function connectWebSocket() {
    const protocol = window.location.protocol === 'https:' ? 'wss' : 'ws';
    const wsUrl = `${protocol}://${window.location.host}/ws`;

    try {
        ws = new WebSocket(wsUrl);

        ws.onopen = () => {
            reconnectAttempts = 0;
            updateConnectionPill(true);
        };

        ws.onmessage = (event) => {
            try {
                const data = JSON.parse(event.data);
                handleWSMessage(data);
            } catch (e) {
                console.error('WS parse error:', e);
            }
        };

        ws.onclose = () => {
            updateConnectionPill(false);
            scheduleReconnect();
        };

        ws.onerror = () => {
            updateConnectionPill(false);
        };

    } catch (e) {
        updateConnectionPill(false);
    }
}

function scheduleReconnect() {
    if (reconnectAttempts >= MAX_RECONNECT) return;
    reconnectAttempts++;
    const delay = Math.min(1000 * Math.pow(2, reconnectAttempts), 15000);
    setTimeout(connectWebSocket, delay);
}

function handleWSMessage(data) {
    if (data.type === 'price_update' && data.price) {
        updatePriceDisplay(data.price);
        if (candleSeries && chart) {
            // Update latest candle on chart
            const nowSeconds = Math.floor(Date.now() / 1000);
            candleSeries.update({
                time: nowSeconds,
                open: data.price,
                high: data.price,
                low: data.price,
                close: data.price,
            });
        }
    } else if (data.type === 'trade_opened' || data.type === 'trade_closed') {
        refreshPositions();
        refreshTrades();
        refreshAccount();
    }
}

function updateConnectionPill(connected) {
    const pill = document.getElementById('mt5-status-pill');
    const text = document.getElementById('mt5-status-text');
    if (pill && text) {
        if (connected) {
            pill.className = 'status-pill connected';
            text.textContent = 'MT5 Connected';
        } else {
            pill.className = 'status-pill disconnected';
            text.textContent = 'MT5 Reconnecting';
        }
    }
}

// ── Data Fetching Orchestrator ──────────────────────────────────────────
async function refreshAll() {
    await Promise.allSettled([
        refreshAccount(),
        refreshPositions(),
        refreshTrades(),
        refreshStats(),
        refreshRegime(),
        refreshSentiment(),
        refreshNews(),
        refreshLearning(),
    ]);
}

async function fetchJSON(url) {
    try {
        const res = await fetch(url);
        if (!res.ok) throw new Error(`HTTP ${res.status}`);
        return await res.json();
    } catch (e) {
        return null;
    }
}

// ── Account & Metrics ───────────────────────────────────────────────────
async function refreshAccount() {
    const data = await fetchJSON('/api/account');
    if (!data || data.error) return;

    setText('balance', formatCurrency(data.balance));
    setText('equity', formatCurrency(data.equity));
    setText('account-login', `Account: #${data.login || '—'}`);
    setText('margin-free', `Free Margin: ${formatCurrency(data.free_margin || 0)}`);
    setText('leverage-val', `1:${data.leverage || 100}`);
    setText('server-val', data.server || 'MetaQuotes-Demo');

    // Realized & Net P&L metrics
    const netPnl = data.net_pnl_today !== undefined ? data.net_pnl_today : (data.profit || 0);
    const realized = data.realized_today !== undefined ? data.realized_today : 0;
    const floating = data.floating_profit !== undefined ? data.floating_profit : (data.profit || 0);

    const pnlEl = document.getElementById('daily-pnl');
    if (pnlEl) {
        pnlEl.textContent = formatCurrency(netPnl, true);
        pnlEl.className = `kpi-num ${netPnl >= 0 ? 'profit' : 'loss'}`;
    }

    const statusSub = document.getElementById('floating-status');
    if (statusSub) {
        statusSub.textContent = `Closed: ${formatCurrency(realized, true)} | Float: ${formatCurrency(floating, true)}`;
    }
}

// ── Positions Station ───────────────────────────────────────────────────
let currentOrderMode = 'market';

function setOrderMode(mode) {
    currentOrderMode = mode;
    const marketBtn = document.getElementById('mode-market-btn');
    const pendingBtn = document.getElementById('mode-pending-btn');
    const targetGroup = document.getElementById('target-price-group');
    const buyLabel = document.getElementById('buy-label');
    const sellLabel = document.getElementById('sell-label');

    if (mode === 'market') {
        if (marketBtn) marketBtn.classList.add('active');
        if (pendingBtn) pendingBtn.classList.remove('active');
        if (targetGroup) targetGroup.style.display = 'none';
        if (buyLabel) buyLabel.textContent = 'BUY';
        if (sellLabel) sellLabel.textContent = 'SELL';
    } else {
        if (marketBtn) marketBtn.classList.remove('active');
        if (pendingBtn) pendingBtn.classList.add('active');
        if (targetGroup) targetGroup.style.display = 'block';
        if (buyLabel) buyLabel.textContent = 'BUY LIMIT';
        if (sellLabel) sellLabel.textContent = 'SELL LIMIT';

        // Suggest target price if empty
        const targetInput = document.getElementById('order-target-price');
        if (targetInput && !targetInput.value) {
            const curP = parseFloat(document.getElementById('current-price')?.textContent?.replace(/[^0-9.]/g, '') || '0');
            if (curP > 0) targetInput.value = (curP - 15.0).toFixed(2);
        }
    }
}

async function handleOrderSubmit(direction) {
    if (currentOrderMode === 'pending') {
        const action = direction === 'BUY' ? 'BUY_LIMIT' : 'SELL_LIMIT';
        await executePendingOrder(action);
    } else {
        await executeTrade(direction);
    }
}

async function executePendingOrder(action) {
    const volumeInput = document.getElementById('order-volume');
    const targetInput = document.getElementById('order-target-price');
    const slInput = document.getElementById('order-sl');
    const tpInput = document.getElementById('order-tp');

    const volume = parseFloat(volumeInput?.value || '0.01');
    const target_price = parseFloat(targetInput?.value || '0');
    const sl_pips = slInput?.value ? parseFloat(slInput.value) : null;
    const tp_pips = tpInput?.value ? parseFloat(tpInput.value) : null;

    if (isNaN(volume) || volume <= 0) {
        showToast('Invalid volume lot size', 'error');
        return;
    }
    if (isNaN(target_price) || target_price <= 0) {
        showToast('Please specify a valid Target Trigger Price ($)', 'error');
        return;
    }

    showToast(`Scheduling ${action} order (${volume} lots @ $${target_price.toFixed(2)})...`);
    try {
        const res = await fetch('/api/order', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ action, volume, target_price, sl_pips, tp_pips })
        });
        const data = await res.json();
        if (data.success) {
            showToast(`Scheduled Order #${data.ticket} successfully placed at $${data.price.toFixed(2)}!`, 'success');
            refreshPositions();
        } else {
            showToast(`Order failed: ${data.error}`, 'error');
        }
    } catch (e) {
        showToast(`Scheduling error: ${e}`, 'error');
    }
}

async function cancelOrder(ticket) {
    showToast(`Canceling pending order #${ticket}...`);
    try {
        const res = await fetch(`/api/cancel-order/${ticket}`, { method: 'POST' });
        const data = await res.json();
        if (data.success) {
            showToast(`Order #${ticket} canceled successfully!`, 'success');
            refreshPositions();
        } else {
            showToast(`Failed to cancel: ${data.error}`, 'error');
        }
    } catch (e) {
        showToast(`Cancel error: ${e}`, 'error');
    }
}

async function refreshPositions() {
    const [positionsData, pendingData] = await Promise.all([
        fetchJSON('/api/positions'),
        fetchJSON('/api/pending')
    ]);

    const posListRaw = Array.isArray(positionsData) ? positionsData : (positionsData?.positions || []);
    const pendListRaw = Array.isArray(pendingData) ? pendingData : [];
    updateChartPositionOverlays(posListRaw, pendListRaw);

    const countBadge = document.getElementById('open-positions-count');
    const pendingBadge = document.getElementById('pending-orders-count');
    const statusSub = document.getElementById('floating-status');
    const posTbody = document.getElementById('positions-body');
    const pendingTbody = document.getElementById('pending-body');

    // 1. Render Active Positions
    const posList = Array.isArray(positionsData) ? positionsData : (positionsData?.positions || []);
    const posCount = posList.length;
    if (countBadge) countBadge.textContent = posCount;
    if (statusSub) statusSub.textContent = `${posCount} Open Position${posCount === 1 ? '' : 's'}`;

    if (posTbody) {
        if (posCount === 0) {
            posTbody.innerHTML = '<tr><td colspan="9" class="empty-state">No open positions. Scanning market regimes...</td></tr>';
        } else {
            posTbody.innerHTML = posList.map(pos => {
                const typeClass = (pos.type || '').toLowerCase();
                const profit = pos.profit || 0;
                const profitClass = profit >= 0 ? 'profit' : 'loss';
                const priceOpen = pos.price_open ? pos.price_open.toFixed(2) : '—';
                const priceCurrent = pos.price_current ? pos.price_current.toFixed(2) : '—';
                const sl = pos.sl ? pos.sl.toFixed(2) : '—';
                const tp = pos.tp ? pos.tp.toFixed(2) : '—';

                return `
                    <tr>
                        <td><strong>#${pos.ticket}</strong></td>
                        <td><span class="type-pill ${typeClass}">${pos.type}</span></td>
                        <td>${pos.volume?.toFixed(2)}</td>
                        <td>$${priceOpen}</td>
                        <td>$${priceCurrent}</td>
                        <td>${sl}</td>
                        <td>${tp}</td>
                        <td class="pnl-cell ${profitClass}"><strong>${formatCurrency(profit, true)}</strong></td>
                        <td>
                            <button class="btn-close-sm" onclick="closePosition(${pos.ticket})" title="Market Close Position">Close</button>
                        </td>
                    </tr>
                `;
            }).join('');
        }
    }

    // 2. Render Scheduled Pending Orders
    const pendList = Array.isArray(pendingData) ? pendingData : [];
    const pendCount = pendList.length;
    if (pendingBadge) {
        pendingBadge.textContent = `${pendCount} Scheduled`;
        pendingBadge.style.display = pendCount > 0 ? 'inline-block' : 'none';
    }

    if (pendingTbody) {
        if (pendCount === 0) {
            pendingTbody.innerHTML = '<tr><td colspan="8" class="empty-state">No scheduled pending orders in book.</td></tr>';
        } else {
            pendingTbody.innerHTML = pendList.map(o => {
                const typeClass = (o.type || '').toLowerCase();
                const targetP = o.price ? o.price.toFixed(2) : '—';
                const sl = o.sl ? o.sl.toFixed(2) : '—';
                const tp = o.tp ? o.tp.toFixed(2) : '—';
                const cmt = o.comment || 'Scheduled';

                return `
                    <tr>
                        <td><strong>#${o.ticket}</strong></td>
                        <td><span class="type-pill ${typeClass}">${o.type}</span></td>
                        <td>${o.volume?.toFixed(2)}</td>
                        <td><strong>$${targetP}</strong></td>
                        <td>${sl}</td>
                        <td>${tp}</td>
                        <td><span class="comment-text">${cmt}</span></td>
                        <td>
                            <button class="btn-cancel-sm" onclick="cancelOrder(${o.ticket})" title="Cancel Scheduled Order">Cancel</button>
                        </td>
                    </tr>
                `;
            }).join('');
        }
    }
}

async function refreshTrades() {
    const data = await fetchJSON('/api/trades');
    if (!data) return;

    const tbody = document.getElementById('trades-body');
    if (!tbody) return;

    if (data.length === 0) {
        tbody.innerHTML = '<tr><td colspan="8" class="empty-state">No recorded trades yet.</td></tr>';
        return;
    }

    tbody.innerHTML = data.slice(0, 25).map(trade => {
        const typeClass = (trade.type || '').toLowerCase();
        const profit = trade.profit || 0;
        const profitClass = profit >= 0 ? 'profit' : 'loss';
        const displayTime = trade.closed_at
            ? new Date(trade.closed_at).toLocaleTimeString([], { hour: '2-digit', minute: '2-digit' })
            : (trade.opened_at ? new Date(trade.opened_at).toLocaleTimeString([], { hour: '2-digit', minute: '2-digit' }) : '—');
        const entryPrice = trade.entry ? `$${trade.entry.toFixed(2)}` : '—';
        const exitPrice = trade.exit ? `$${trade.exit.toFixed(2)}` : '—';
        const strategyTag = trade.comment ? trade.comment : (trade.strategy || 'QUANT_AUTO');

        return `
            <tr>
                <td>${displayTime}</td>
                <td><span class="type-pill ${typeClass}">${trade.type}</span></td>
                <td>${strategyTag}</td>
                <td>${entryPrice}</td>
                <td>${exitPrice}</td>
                <td>${trade.volume?.toFixed(2) || '—'}</td>
                <td class="pnl-cell ${profitClass}"><strong>${formatCurrency(profit, true)}</strong></td>
                <td><span class="status-pill-sm ${trade.status?.toLowerCase() || 'closed'}">${trade.status || 'CLOSED'}</span></td>
            </tr>
        `;
    }).join('');
}

// ── Stats ───────────────────────────────────────────────────────────────
async function refreshStats() {
    const data = await fetchJSON('/api/stats');
    if (!data) return;

    setText('win-rate', `${(data.win_rate || 0).toFixed(1)}%`);
    const count = data.total_trades || 0;
    const tradeText = count === 1 ? '1 Closed Trade' : `${count} Closed Trades`;
    setText('total-trades-sub', tradeText);
    setText('profit-factor', (data.profit_factor || 0).toFixed(2));
}

// ── Market Regime ───────────────────────────────────────────────────────
async function refreshRegime() {
    const data = await fetchJSON('/api/regime');
    if (!data || data.error) return;

    setText('nav-regime-val', data.regime);
    setText('regime-tag', data.regime);
    setText('regime-adx', `${data.adx || 0}`);
    setText('regime-vol', `${data.volatility_label || 'NORMAL'} (${(data.volatility_percentile || 0).toFixed(1)}%)`);
    setText('regime-sizer', `${(data.position_size_modifier || 1.0).toFixed(2)}x`);

    const adxBar = document.getElementById('adx-bar');
    if (adxBar) {
        const pct = Math.min(100, Math.max(5, ((data.adx || 0) / 40) * 100));
        adxBar.style.width = `${pct}%`;
    }

    const volBar = document.getElementById('vol-bar');
    if (volBar) {
        volBar.style.width = `${Math.min(100, Math.max(5, data.volatility_percentile || 15))}%`;
    }

    const chipBox = document.getElementById('strategy-chips');
    if (chipBox && Array.isArray(data.recommended_strategies)) {
        chipBox.innerHTML = data.recommended_strategies.map(s => `<span class="chip">${s.toUpperCase()}</span>`).join('');
    }
}

// ── Sentiment & News ────────────────────────────────────────────────────
async function refreshSentiment() {
    const data = await fetchJSON('/api/sentiment');
    if (!data) return;

    const pill = document.getElementById('nav-sentiment-val');
    if (pill) {
        const sign = data.score >= 0 ? '+' : '';
        pill.textContent = `${sign}${data.score.toFixed(2)} ${data.label}`;
        pill.className = `pill-val ${data.label.toLowerCase()}`;
    }
}

async function refreshNews() {
    const data = await fetchJSON('/api/news');
    if (!data) return;

    const container = document.getElementById('news-container');
    if (!container) return;

    if (data.length === 0) {
        container.innerHTML = '<div class="empty-state">No news cached. Tap "Fetch Live News" above.</div>';
        return;
    }

    container.innerHTML = data.slice(0, 6).map(item => {
        const sent = (item.sentiment || 'NEUTRAL').toUpperCase();
        const sentClass = sent.toLowerCase();
        const time = item.time ? new Date(item.time).toLocaleTimeString([], { hour: '2-digit', minute: '2-digit' }) : '';
        const scoreStr = typeof item.score === 'number' ? (item.score >= 0 ? '+' : '') + item.score.toFixed(2) : '';

        return `
            <div class="news-card-item">
                <div class="news-meta-top">
                    <span class="news-source-tag">${item.source || 'MACRO'}</span>
                    <span class="news-time">${time}</span>
                </div>
                <div class="news-headline">${item.headline}</div>
                <div class="news-footer">
                    <span class="sentiment-badge ${sentClass}">${sent} ${scoreStr}</span>
                    ${item.analysis ? `<span class="news-note" title="${item.analysis}">Note: ${item.analysis}</span>` : ''}
                </div>
            </div>
        `;
    }).join('');
}


// ── Self-Learning & Adaptation ──────────────────────────────────────────
async function refreshLearning() {
    const data = await fetchJSON('/api/learning');
    if (!data || data.error) return;

    // 1. Update Strategy Multipliers
    const mults = data.strategy_multipliers || {};
    const scalp = mults.scalping || 1.0;
    const day = mults.day_trading || 1.0;
    const swing = mults.swing_trading || 1.0;

    updateMultChip('mult-scalp', 'SCALP', scalp);
    updateMultChip('mult-day', 'DAY', day);
    updateMultChip('mult-swing', 'SWING', swing);

    // 2. Update Confluence Weights
    const weights = data.adaptive_weights || {};
    const tech = weights.technical || 40.0;
    const ai = weights.ai_prediction || 25.0;
    const sent = weights.sentiment || 20.0;
    const reg = weights.regime || 15.0;

    setText('weights-val', `${tech.toFixed(0)}% / ${ai.toFixed(0)}% / ${sent.toFixed(0)}% / ${reg.toFixed(0)}%`);

    setBarWidth('w-tech', tech);
    setBarWidth('w-ai', ai);
    setBarWidth('w-sent', sent);
    setBarWidth('w-reg', reg);

    // 3. Update Mistake Memory Guard
    setText('guard-count', `${data.active_mistakes_memorized || 0} Active Trap(s) Guarded`);
    if (data.recent_lessons && data.recent_lessons.length > 0) {
        const latest = data.recent_lessons[0];
        setText('guard-latest-rule', `Latest: ${latest.rule || latest.summary}`);
    }
}

function updateMultChip(id, label, val) {
    const el = document.getElementById(id);
    if (!el) return;
    el.textContent = `${label}: ${val.toFixed(2)}x`;
    if (val > 1.0) {
        el.className = 'mult-chip profit';
    } else if (val < 1.0) {
        el.className = 'mult-chip loss';
    } else {
        el.className = 'mult-chip';
    }
}

function setBarWidth(id, pct) {
    const el = document.getElementById(id);
    if (el) el.style.width = `${Math.max(5, pct)}%`;
}

// ── Trade & Control Actions ─────────────────────────────────────────────
async function closePosition(ticket) {
    showToast(`Sending close order for #${ticket}...`);
    try {
        const res = await fetch(`/api/close-position/${ticket}`, { method: 'POST' });
        const data = await res.json();
        if (data.success) {
            showToast(`Position #${ticket} closed successfully!`, 'success');
            refreshPositions();
            refreshAccount();
        } else {
            showToast(`Failed to close #${ticket}: ${data.error}`, 'error');
        }
    } catch (e) {
        showToast(`Network error closing position: ${e}`, 'error');
    }
}

function openCloseAllModal() {
    const modal = document.getElementById('close-all-modal');
    if (modal) modal.classList.add('active');
}

function closeCloseAllModal() {
    const modal = document.getElementById('close-all-modal');
    if (modal) modal.classList.remove('active');
}

async function executeCloseAll() {
    closeCloseAllModal();
    showToast('Executing emergency close for ALL positions...');
    try {
        const res = await fetch('/api/close-all', { method: 'POST' });
        const data = await res.json();
        if (data.success) {
            showToast(`Closed ${data.closed_count} position(s)!`, 'success');
            refreshPositions();
            refreshAccount();
        } else {
            showToast(`Close all failed: ${data.error}`, 'error');
        }
    } catch (e) {
        showToast(`Network error: ${e}`, 'error');
    }
}

function setLot(val) {
    const input = document.getElementById('order-volume');
    if (input) input.value = val.toFixed(2);
}

async function executeTrade(action) {
    const volumeInput = document.getElementById('order-volume');
    const slInput = document.getElementById('order-sl');
    const tpInput = document.getElementById('order-tp');

    const volume = parseFloat(volumeInput?.value || '0.01');
    const sl_pips = slInput?.value ? parseFloat(slInput.value) : null;
    const tp_pips = tpInput?.value ? parseFloat(tpInput.value) : null;

    if (isNaN(volume) || volume <= 0) {
        showToast('Invalid volume lot size', 'error');
        return;
    }

    showToast(`Submitting manual ${action} order (${volume} lots)...`);
    try {
        const res = await fetch('/api/order', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ action, volume, sl_pips, tp_pips })
        });
        const data = await res.json();
        if (data.success) {
            showToast(`Order executed! Ticket #${data.ticket} at $${data.price.toFixed(2)}`, 'success');
            refreshPositions();
            refreshAccount();
        } else {
            showToast(`Order failed: ${data.error}`, 'error');
        }
    } catch (e) {
        showToast(`Execution error: ${e}`, 'error');
    }
}

async function triggerNewsRefresh() {
    const btn = document.getElementById('btn-fetch-news');
    if (btn) btn.disabled = true;
    showToast('Fetching latest macro news from Finnhub & Alpha Vantage...');

    try {
        const res = await fetch('/api/news/refresh', { method: 'POST' });
        const data = await res.json();
        if (data.success) {
            showToast(`Processed ${data.articles_processed} articles with AI sentiment!`, 'success');
            refreshNews();
            refreshSentiment();
        } else {
            showToast(`News fetch error: ${data.error}`, 'error');
        }
    } catch (e) {
        showToast(`Network error: ${e}`, 'error');
    } finally {
        if (btn) btn.disabled = false;
    }
}

// ── UI Helpers ──────────────────────────────────────────────────────────
function formatCurrency(val, showSign = false) {
    if (typeof val !== 'number' || isNaN(val)) return '$0.00';
    const sign = showSign && val >= 0 ? '+' : '';
    return `${sign}$${val.toLocaleString('en-US', { minimumFractionDigits: 2, maximumFractionDigits: 2 })}`;
}

function setText(id, text) {
    const el = document.getElementById(id);
    if (el) el.textContent = text;
}

function updatePriceDisplay(price) {
    if (!price) return;
    const priceEl = document.getElementById('current-price');
    const changeEl = document.getElementById('price-change');
    const askHint = document.getElementById('buy-ask-hint');
    const sellHint = document.getElementById('sell-bid-hint');

    if (previousPrice > 0 && priceEl) {
        if (price > previousPrice) {
            priceEl.classList.remove('flash-down');
            priceEl.classList.add('flash-up');
        } else if (price < previousPrice) {
            priceEl.classList.remove('flash-up');
            priceEl.classList.add('flash-down');
        }
        setTimeout(() => {
            priceEl.classList.remove('flash-up', 'flash-down');
        }, 500);
    }

    previousPrice = currentPrice;
    currentPrice = price;

    if (priceEl) priceEl.textContent = `$${price.toFixed(2)}`;
    if (askHint) askHint.textContent = `ASK: $${(price + 0.15).toFixed(2)}`;
    if (sellHint) sellHint.textContent = `BID: $${price.toFixed(2)}`;
}

function showToast(msg, type = 'info') {
    const container = document.getElementById('toast-container');
    if (!container) return;

    const toast = document.createElement('div');
    toast.className = `toast ${type}`;
    const icon = type === 'success' ? '✅' : (type === 'error' ? '⚠️' : 'ℹ️');
    toast.innerHTML = `<span>${icon}</span><span>${msg}</span>`;
    container.appendChild(toast);

    setTimeout(() => {
        toast.style.opacity = '0';
        toast.style.transform = 'translateY(10px)';
        toast.style.transition = 'all 0.3s ease';
        setTimeout(() => toast.remove(), 300);
    }, 3800);
}
