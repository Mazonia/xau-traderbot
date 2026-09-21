/**
 * XAUUSD AI Trading Bot — Dashboard JavaScript
 *
 * Handles:
 * - WebSocket connection for real-time updates
 * - TradingView Lightweight Charts
 * - DOM updates for stats, positions, trades, news
 * - Auto-refresh polling fallback
 */

// ── State ──────────────────────────────────────────────────────────────
let ws = null;
let chart = null;
let candleSeries = null;
let reconnectAttempts = 0;
const MAX_RECONNECT = 10;
const POLL_INTERVAL = 5000; // 5 seconds fallback

// ── Initialize ─────────────────────────────────────────────────────────
document.addEventListener('DOMContentLoaded', () => {
    initChart();
    connectWebSocket();
    refreshAll();

    // Auto-refresh every 5s as fallback
    setInterval(refreshAll, POLL_INTERVAL);

    // Timeframe tab handlers
    document.querySelectorAll('.tf-btn').forEach(btn => {
        btn.addEventListener('click', (e) => {
            document.querySelectorAll('.tf-btn').forEach(b => b.classList.remove('active'));
            e.target.classList.add('active');
            // TODO: Reload chart with new timeframe
        });
    });
});

// ── Chart ──────────────────────────────────────────────────────────────
function initChart() {
    const container = document.getElementById('chart-container');
    if (!container || typeof LightweightCharts === 'undefined') return;

    chart = LightweightCharts.createChart(container, {
        width: container.clientWidth,
        height: container.clientHeight || 400,
        layout: {
            background: { type: 'solid', color: 'transparent' },
            textColor: '#9ca3af',
            fontFamily: "'Inter', sans-serif",
            fontSize: 11,
        },
        grid: {
            vertLines: { color: 'rgba(255, 255, 255, 0.03)' },
            horzLines: { color: 'rgba(255, 255, 255, 0.03)' },
        },
        crosshair: {
            mode: LightweightCharts.CrosshairMode.Normal,
            vertLine: { color: 'rgba(245, 158, 11, 0.3)', style: 2, width: 1 },
            horzLine: { color: 'rgba(245, 158, 11, 0.3)', style: 2, width: 1 },
        },
        timeScale: {
            borderColor: 'rgba(255, 255, 255, 0.06)',
            timeVisible: true,
            secondsVisible: false,
        },
        rightPriceScale: {
            borderColor: 'rgba(255, 255, 255, 0.06)',
        },
    });

    candleSeries = chart.addCandlestickSeries({
        upColor: '#10b981',
        downColor: '#ef4444',
        borderUpColor: '#10b981',
        borderDownColor: '#ef4444',
        wickUpColor: '#10b981',
        wickDownColor: '#ef4444',
    });

    // Resize handler
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

// ── WebSocket ──────────────────────────────────────────────────────────
function connectWebSocket() {
    const protocol = window.location.protocol === 'https:' ? 'wss' : 'ws';
    const wsUrl = `${protocol}://${window.location.host}/ws`;

    try {
        ws = new WebSocket(wsUrl);

        ws.onopen = () => {
            reconnectAttempts = 0;
            updateConnectionStatus('connected');
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
            updateConnectionStatus('disconnected');
            scheduleReconnect();
        };

        ws.onerror = () => {
            updateConnectionStatus('disconnected');
        };

    } catch (e) {
        console.error('WebSocket connection failed:', e);
        updateConnectionStatus('disconnected');
    }
}

function scheduleReconnect() {
    if (reconnectAttempts >= MAX_RECONNECT) return;
    reconnectAttempts++;
    const delay = Math.min(1000 * Math.pow(2, reconnectAttempts), 30000);
    setTimeout(connectWebSocket, delay);
}

function handleWSMessage(data) {
    switch (data.type) {
        case 'price_update':
            updatePrice(data);
            break;
        case 'trade_opened':
        case 'trade_closed':
            refreshTrades();
            refreshPositions();
            break;
        case 'pong':
            break;
    }
}

function updateConnectionStatus(status) {
    const badge = document.getElementById('connection-status');
    const dot = badge?.querySelector('.status-dot');
    const text = badge?.querySelector('span:last-child');

    if (dot) {
        dot.className = 'status-dot ' + status;
    }
    if (text) {
        text.textContent = status === 'connected' ? 'Live' : 'Offline';
    }
}

// ── Data Fetching ──────────────────────────────────────────────────────
async function refreshAll() {
    await Promise.allSettled([
        refreshAccount(),
        refreshPositions(),
        refreshTrades(),
        refreshStats(),
        refreshNews(),
    ]);
}

async function fetchJSON(url) {
    try {
        const response = await fetch(url);
        if (!response.ok) throw new Error(`HTTP ${response.status}`);
        return await response.json();
    } catch (e) {
        console.error(`Fetch error (${url}):`, e);
        return null;
    }
}

async function refreshAccount() {
    const data = await fetchJSON('/api/account');
    if (!data || data.error) return;

    setText('balance', formatCurrency(data.balance));
    setText('equity', formatCurrency(data.equity));

    const pnl = data.profit || 0;
    const pnlEl = document.getElementById('daily-pnl');
    if (pnlEl) {
        pnlEl.textContent = formatCurrency(pnl, true);
        pnlEl.className = 'stat-value ' + (pnl >= 0 ? 'profit' : 'loss');
    }
}

async function refreshPositions() {
    const data = await fetchJSON('/api/positions');
    if (!data) return;

    const container = document.getElementById('positions-list');
    const countBadge = document.getElementById('open-count');

    if (countBadge) countBadge.textContent = data.length;

    if (!container) return;

    if (data.length === 0) {
        container.innerHTML = '<div class="empty-state">No open positions</div>';
        return;
    }

    container.innerHTML = data.map(pos => {
        const profitClass = pos.profit >= 0 ? 'profit' : 'loss';
        const typeClass = pos.type.toLowerCase();

        return `
            <div class="position-item">
                <div class="position-row">
                    <span class="position-type ${typeClass}">${pos.type}</span>
                    <span class="position-profit ${profitClass}">${formatCurrency(pos.profit, true)}</span>
                </div>
                <div class="position-row">
                    <span class="position-detail">${pos.volume} lots @ ${pos.price_open?.toFixed(2)}</span>
                    <span class="position-detail">SL: ${pos.sl?.toFixed(2)} | TP: ${pos.tp?.toFixed(2)}</span>
                </div>
            </div>
        `;
    }).join('');
}

async function refreshTrades() {
    const data = await fetchJSON('/api/trades');
    if (!data) return;

    const tbody = document.getElementById('trades-body');
    if (!tbody) return;

    if (data.length === 0) {
        tbody.innerHTML = '<tr><td colspan="8" class="empty-state">No trades yet</td></tr>';
        return;
    }

    tbody.innerHTML = data.slice(0, 20).map(trade => {
        const typeClass = trade.type?.toLowerCase() || '';
        const profitClass = (trade.profit || 0) >= 0 ? 'profit' : 'loss';
        const time = trade.opened_at ? new Date(trade.opened_at).toLocaleTimeString([], {hour: '2-digit', minute:'2-digit'}) : '—';

        return `
            <tr>
                <td>${time}</td>
                <td><span class="type-badge ${typeClass}">${trade.type}</span></td>
                <td>${trade.strategy || '—'}</td>
                <td>${trade.entry?.toFixed(2) || '—'}</td>
                <td>${trade.exit?.toFixed(2) || '—'}</td>
                <td>${trade.volume}</td>
                <td class="${profitClass}">${formatCurrency(trade.profit || 0, true)}</td>
                <td>${trade.confluence?.toFixed(0) || '—'}</td>
            </tr>
        `;
    }).join('');
}

async function refreshStats() {
    const data = await fetchJSON('/api/stats');
    if (!data) return;

    setText('win-rate', `${(data.win_rate || 0).toFixed(1)}%`);
    setText('total-trades', data.total_trades || 0);
    setText('profit-factor', (data.profit_factor || 0).toFixed(2));
}

async function refreshNews() {
    const data = await fetchJSON('/api/news');
    if (!data) return;

    const container = document.getElementById('news-feed');
    if (!container) return;

    if (data.length === 0) {
        container.innerHTML = '<div class="empty-state">No news loaded</div>';
        return;
    }

    container.innerHTML = data.map(item => {
        const sentClass = (item.sentiment || '').toLowerCase();
        const scoreClass = item.score >= 0 ? 'positive' : 'negative';
        const time = item.time ? new Date(item.time).toLocaleTimeString([], {hour: '2-digit', minute:'2-digit'}) : '';

        return `
            <div class="news-item">
                <div class="news-sentiment ${sentClass}"></div>
                <div class="news-content">
                    <div class="news-headline">${item.headline}</div>
                    <div class="news-meta">
                        <span>${item.source}</span>
                        <span>${time}</span>
                        <span class="news-score ${scoreClass}">${item.score >= 0 ? '+' : ''}${item.score?.toFixed(2)}</span>
                        <span>${item.impact}</span>
                    </div>
                </div>
            </div>
        `;
    }).join('');
}

// ── Helpers ────────────────────────────────────────────────────────────
function formatCurrency(value, showSign = false) {
    if (typeof value !== 'number') return '$0.00';
    const sign = showSign && value >= 0 ? '+' : '';
    return `${sign}$${value.toLocaleString('en-US', { minimumFractionDigits: 2, maximumFractionDigits: 2 })}`;
}

function setText(id, text) {
    const el = document.getElementById(id);
    if (el) el.textContent = text;
}

function updatePrice(data) {
    const priceEl = document.getElementById('current-price');
    const changeEl = document.getElementById('price-change');

    if (priceEl && data.price) {
        priceEl.textContent = `$${data.price.toFixed(2)}`;
    }

    if (changeEl && data.change !== undefined) {
        const isPositive = data.change >= 0;
        changeEl.textContent = `${isPositive ? '+' : ''}${data.change.toFixed(2)}`;
        changeEl.className = `price-change ${isPositive ? 'positive' : 'negative'}`;
    }
}
