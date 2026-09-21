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

// ── Initialization ──────────────────────────────────────────────────────
document.addEventListener('DOMContentLoaded', () => {
    initChart();
    loadChartData(currentTimeframe);
    connectWebSocket();
    refreshAll();

    // Regular data polling fallback
    setInterval(refreshAll, POLL_INTERVAL);

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
    }
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

    const pnl = data.profit || 0;
    const pnlEl = document.getElementById('daily-pnl');
    if (pnlEl) {
        pnlEl.textContent = formatCurrency(pnl, true);
        pnlEl.className = 'kpi-num ' + (pnl >= 0 ? 'profit' : 'loss');
    }
}

// ── Positions Station ───────────────────────────────────────────────────
async function refreshPositions() {
    const data = await fetchJSON('/api/positions');
    if (!data) return;

    const countBadge = document.getElementById('open-positions-count');
    const statusSub = document.getElementById('floating-status');
    const tbody = document.getElementById('positions-body');

    const count = data.length || 0;
    if (countBadge) countBadge.textContent = count;
    if (statusSub) statusSub.textContent = `${count} Open Position${count === 1 ? '' : 's'}`;

    if (!tbody) return;

    if (count === 0) {
        tbody.innerHTML = '<tr><td colspan="9" class="empty-state">No open positions. Ready for signals.</td></tr>';
        return;
    }

    tbody.innerHTML = data.map(pos => {
        const typeClass = (pos.type || '').toLowerCase();
        const profit = pos.profit || 0;
        const profitClass = profit >= 0 ? 'profit' : 'loss';
        const priceOpen = pos.price_open ? pos.price_open.toFixed(2) : '—';
        const priceCurrent = pos.price_current ? pos.price_current.toFixed(2) : '—';
        const sl = pos.sl ? pos.sl.toFixed(2) : '—';
        const tp = pos.tp ? pos.tp.toFixed(2) : '—';

        return `
            <tr>
                <td>#${pos.ticket}</td>
                <td><span class="type-pill ${typeClass}">${pos.type}</span></td>
                <td>${pos.volume?.toFixed(2)}</td>
                <td>$${priceOpen}</td>
                <td>$${priceCurrent}</td>
                <td>${sl}</td>
                <td>${tp}</td>
                <td class="pnl-cell ${profitClass}">${formatCurrency(profit, true)}</td>
                <td>
                    <button class="btn-close-single" onclick="closePosition(${pos.ticket})">✕ Close</button>
                </td>
            </tr>
        `;
    }).join('');
}

// ── Trade History ───────────────────────────────────────────────────────
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
        const profitClass = (trade.profit || 0) >= 0 ? 'profit' : 'loss';
        const time = trade.opened_at ? new Date(trade.opened_at).toLocaleTimeString([], { hour: '2-digit', minute: '2-digit' }) : '—';

        return `
            <tr>
                <td>${time}</td>
                <td><span class="type-pill ${typeClass}">${trade.type}</span></td>
                <td>${trade.strategy || 'Auto-AI'}</td>
                <td>$${trade.entry?.toFixed(2) || '—'}</td>
                <td>$${trade.exit?.toFixed(2) || '—'}</td>
                <td>${trade.volume?.toFixed(2) || '—'}</td>
                <td class="pnl-cell ${profitClass}">${formatCurrency(trade.profit || 0, true)}</td>
                <td>${trade.confluence ? trade.confluence.toFixed(0) + '/100' : '—'}</td>
            </tr>
        `;
    }).join('');
}

// ── Stats ───────────────────────────────────────────────────────────────
async function refreshStats() {
    const data = await fetchJSON('/api/stats');
    if (!data) return;

    setText('win-rate', `${(data.win_rate || 0).toFixed(1)}%`);
    setText('total-trades-sub', `${data.total_trades || 0} Closed Trades`);
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
