// LOX FUND Dashboard v1

// Track dismissed alerts (per session)
let dismissedAlertTimestamp = null;

function dismissAlert() {
    const alert = document.getElementById('regime-alert');
    if (alert) {
        alert.style.display = 'none';
        dismissedAlertTimestamp = new Date().toISOString();
    }
}

function showRegimeAlert(details) {
    const alert = document.getElementById('regime-alert');
    const alertText = document.getElementById('alert-text');
    
    if (!alert || !alertText || !details || details.length === 0) return;
    
    // Build alert message
    const change = details[0]; // Show first/most important change
    const direction = change.direction === 'worsening' ? '↗' : '↘';
    alertText.textContent = `${change.indicator} shifted: ${change.from} → ${change.to}`;
    
    alert.style.display = 'flex';
}

function formatCurrency(value, showCents = false) {
    // Show cents for smaller values or when explicitly requested
    const decimals = (showCents || Math.abs(value) < 100) ? 2 : 0;
    return new Intl.NumberFormat('en-US', {
        style: 'currency',
        currency: 'USD',
        minimumFractionDigits: decimals,
        maximumFractionDigits: decimals,
    }).format(value);
}

function formatPercent(value) {
    const sign = value >= 0 ? '+' : '';
    return `${sign}${value.toFixed(2)}%`;
}

function formatTimestamp(isoString) {
    const date = new Date(isoString);
    return date.toLocaleTimeString('en-US', {
        hour: '2-digit',
        minute: '2-digit',
        second: '2-digit',
    });
}

function formatSymbol(symbol, optInfo) {
    if (optInfo) {
        // Handle both 'C'/'P' and 'CALL'/'PUT' formats
        let type = 'P';
        if (optInfo.opt_type === 'C' || optInfo.opt_type === 'CALL' || optInfo.opt_type === 'call') {
            type = 'C';
        } else if (optInfo.opt_type === 'P' || optInfo.opt_type === 'PUT' || optInfo.opt_type === 'put') {
            type = 'P';
        }
        return `${optInfo.underlying} ${optInfo.strike}${type} ${optInfo.expiry}`;
    }
    return symbol;
}

function updateDashboard() {
    fetch('/api/positions')
        .then(response => {
            if (!response.ok) {
                throw new Error(`HTTP ${response.status}: ${response.statusText}`);
            }
            return response.json();
        })
        .then(data => {
            // Update summary - always show values even if there's an error
            const navEl = document.getElementById('nav-value');
            if (data.nav_equity && data.nav_equity > 0) {
                navEl.textContent = formatCurrency(data.nav_equity);
            } else if (data.error) {
                navEl.textContent = 'Error';
            } else {
                navEl.textContent = formatCurrency(0);
            }
            navEl.className = 'summary-value';

            const pnlEl = document.getElementById('total-pnl');
            pnlEl.textContent = formatCurrency(data.total_pnl || 0);
            pnlEl.className = 'summary-value ' + ((data.total_pnl || 0) >= 0 ? 'positive' : 'negative');

            if (data.error) {
                console.error('Error:', data.error);
                document.getElementById('positions-body').innerHTML = 
                    `<tr><td colspan="5" class="loading">Error loading positions: ${data.error}</td></tr>`;
                return;
            }

            const cashEl = document.getElementById('cash-available');
            cashEl.textContent = formatCurrency(data.cash_available || 0);
            cashEl.className = 'summary-value';

            // Update performance comparison
            const fundReturnEl = document.getElementById('fund-return');
            if (data.return_pct !== undefined) {
                const returnVal = data.return_pct;
                fundReturnEl.textContent = `${returnVal >= 0 ? '+' : ''}${returnVal.toFixed(2)}%`;
                fundReturnEl.className = 'perf-value ' + (returnVal >= 0 ? 'positive' : 'negative');
            }
            
            // S&P 500
            const sp500ReturnEl = document.getElementById('sp500-return');
            const alphaSp500El = document.getElementById('alpha-sp500');
            if (data.sp500_return !== undefined && data.sp500_return !== null) {
                const sp500Val = data.sp500_return;
                sp500ReturnEl.textContent = `${sp500Val >= 0 ? '+' : ''}${sp500Val.toFixed(2)}%`;
                sp500ReturnEl.className = 'perf-value ' + (sp500Val >= 0 ? 'positive' : 'negative');
                
                // Alpha vs S&P
                if (data.alpha_sp500 !== undefined && data.alpha_sp500 !== null) {
                    const alpha = data.alpha_sp500;
                    alphaSp500El.textContent = `α: ${alpha >= 0 ? '+' : ''}${alpha.toFixed(1)}%`;
                    alphaSp500El.className = 'perf-alpha ' + (alpha >= 0 ? 'positive' : 'negative');
                }
            } else {
                sp500ReturnEl.textContent = '—';
                alphaSp500El.textContent = '';
            }
            
            // BTC/USD
            const btcReturnEl = document.getElementById('btc-return');
            const alphaBtcEl = document.getElementById('alpha-btc');
            if (data.btc_return !== undefined && data.btc_return !== null) {
                const btcVal = data.btc_return;
                btcReturnEl.textContent = `${btcVal >= 0 ? '+' : ''}${btcVal.toFixed(2)}%`;
                btcReturnEl.className = 'perf-value ' + (btcVal >= 0 ? 'positive' : 'negative');
                
                // Alpha vs BTC
                if (data.alpha_btc !== undefined && data.alpha_btc !== null) {
                    const alpha = data.alpha_btc;
                    alphaBtcEl.textContent = `α: ${alpha >= 0 ? '+' : ''}${alpha.toFixed(1)}%`;
                    alphaBtcEl.className = 'perf-alpha ' + (alpha >= 0 ? 'positive' : 'negative');
                }
            } else {
                btcReturnEl.textContent = '—';
                alphaBtcEl.textContent = '';
            }

            // Update positions table
            const tbody = document.getElementById('positions-body');
            if (data.positions.length === 0) {
                tbody.innerHTML = '<tr><td colspan="5" class="loading">No positions</td></tr>';
                return;
            }

            tbody.innerHTML = data.positions.map(pos => {
                const pnlClass = pos.pnl >= 0 ? 'pnl-positive' : 'pnl-negative';
                let optDetails = '';
                if (pos.opt_info) {
                    // Normalize opt_type to C or P for display
                    let type = 'P';
                    if (pos.opt_info.opt_type === 'C' || pos.opt_info.opt_type === 'CALL' || pos.opt_info.opt_type === 'call') {
                        type = 'C';
                    } else if (pos.opt_info.opt_type === 'P' || pos.opt_info.opt_type === 'PUT' || pos.opt_info.opt_type === 'put') {
                        type = 'P';
                    }
                    optDetails = `<div class="opt-details">${pos.opt_info.expiry} | Strike ${pos.opt_info.strike}${type}</div>`;
                }
                
                return `
                    <tr>
                        <td>
                            <div class="symbol">${formatSymbol(pos.symbol, pos.opt_info)}</div>
                            ${optDetails}
                        </td>
                        <td>${pos.qty > 0 ? '+' : ''}${pos.qty.toFixed(0)}</td>
                        <td>${formatCurrency(Math.abs(pos.market_value))}</td>
                        <td class="${pnlClass}">${formatCurrency(pos.pnl)}</td>
                        <td class="${pnlClass}">${formatPercent(pos.pnl_pct)}</td>
                    </tr>
                `;
            }).join('');
        })
        .catch(error => {
            console.error('Fetch error:', error);
            document.getElementById('nav-value').textContent = 'Error';
            document.getElementById('total-pnl').textContent = 'Error';
            document.getElementById('positions-body').innerHTML = 
                '<tr><td colspan="5" class="loading">Error connecting to server. Please refresh.</td></tr>';
        });
}

// Fetch and display Palmer's dashboard (traffic lights, events, headlines, insight)
function fetchPalmerDashboard() {
    const trafficLights = document.getElementById('traffic-lights');
    const eventsContainer = document.getElementById('palmer-events');
    const headlinesContainer = document.getElementById('palmer-headlines');
    const insightContainer = document.getElementById('palmer-insight');
    
    fetch('/api/regime-analysis')
        .then(response => response.json())
        .then(data => {
            if (data.error && !data.traffic_lights) {
                insightContainer.innerHTML = `<div class="insight-loading">Error: ${data.error}</div>`;
                return;
            }
            
            // Update traffic lights
            if (data.traffic_lights) {
                const tl = data.traffic_lights;
                trafficLights.innerHTML = `
                    <div class="traffic-item" data-status="${tl.regime?.color || 'gray'}">
                        <span class="traffic-label">REGIME</span>
                        <span class="traffic-dot">●</span>
                        <span class="traffic-value">${tl.regime?.label || '—'}</span>
                    </div>
                    <div class="traffic-item" data-status="${tl.volatility?.color || 'gray'}">
                        <span class="traffic-label">VOLATILITY</span>
                        <span class="traffic-dot">●</span>
                        <span class="traffic-value">${tl.volatility?.label || '—'} ${tl.volatility?.value ? '(' + tl.volatility.value + ')' : ''}</span>
                    </div>
                    <div class="traffic-item" data-status="${tl.credit?.color || 'gray'}">
                        <span class="traffic-label">CREDIT</span>
                        <span class="traffic-dot">●</span>
                        <span class="traffic-value">${tl.credit?.label || '—'} ${tl.credit?.value ? '(' + tl.credit.value + ')' : ''}</span>
                    </div>
                    <div class="traffic-item" data-status="${tl.rates?.color || 'gray'}">
                        <span class="traffic-label">RATES</span>
                        <span class="traffic-dot">●</span>
                        <span class="traffic-value">${tl.rates?.label || '—'} ${tl.rates?.value ? '(' + tl.rates.value + ')' : ''}</span>
                    </div>
                `;
            }
            
            // Update today's economic releases (stunning visual design)
            if (data.events && data.events.releases && data.events.releases.length > 0) {
                const releases = data.events.releases;
                const calDate = data.events.date || 'Today';
                
                eventsContainer.innerHTML = `
                    <div class="calendar-header">
                        <span class="calendar-flag">🇺🇸</span>
                        <span class="calendar-date">${calDate}</span>
                    </div>
                    <div class="releases-grid">
                        ${releases.map(e => {
                            const actualVal = e.actual !== null && e.actual !== undefined ? e.actual : '—';
                            const prevVal = e.previous !== null && e.previous !== undefined ? e.previous : '—';
                            const estVal = e.estimate !== null && e.estimate !== undefined ? e.estimate : '—';
                            
                            // Surprise indicator
                            let indicator = '';
                            let indicatorClass = '';
                            if (e.surprise_direction === 'beat') {
                                indicator = '▲';
                                indicatorClass = 'beat';
                            } else if (e.surprise_direction === 'miss') {
                                indicator = '▼';
                                indicatorClass = 'miss';
                            }
                            
                            const eventLink = e.url 
                                ? `<a href="${e.url}" target="_blank" rel="noopener noreferrer">${e.event}</a>`
                                : e.event;
                            
                            return `
                                <div class="release-card ${indicatorClass}">
                                    <div class="release-header">
                                        <span class="release-time">${e.time || ''}</span>
                                        <span class="release-indicator">${indicator}</span>
                                    </div>
                                    <div class="release-name">${eventLink}</div>
                                    <div class="release-values">
                                        <div class="release-value actual">
                                            <span class="value-label">Actual</span>
                                            <span class="value-num ${indicatorClass}">${actualVal}</span>
                                        </div>
                                        <div class="release-value">
                                            <span class="value-label">Est</span>
                                            <span class="value-num">${estVal}</span>
                                        </div>
                                        <div class="release-value">
                                            <span class="value-label">Prev</span>
                                            <span class="value-num">${prevVal}</span>
                                        </div>
                                    </div>
                                </div>
                            `;
                        }).join('')}
                    </div>
                `;
            } else {
                eventsContainer.innerHTML = `
                    <div class="calendar-header">
                        <span class="calendar-flag">🇺🇸</span>
                        <span class="calendar-date">${new Date().toLocaleDateString('en-US', { weekday: 'long', month: 'long', day: 'numeric', year: 'numeric' })}</span>
                    </div>
                    <div class="no-releases">No US economic releases today</div>
                `;
            }
            
            // Update macro headlines with clickable links
            if (data.headlines && data.headlines.length > 0) {
                headlinesContainer.innerHTML = data.headlines.map(h => {
                    const headlineContent = h.url 
                        ? `<a href="${h.url}" target="_blank" rel="noopener noreferrer" class="headline-link">${h.headline}</a>`
                        : h.headline;
                    return `
                    <div class="headline-item">
                        <div class="headline-text">
                            ${h.ticker ? `<span class="headline-ticker">${h.ticker}</span> ` : ''}${headlineContent}
                        </div>
                        <div class="headline-meta">
                            <span class="headline-source">${h.source || 'News'}</span>
                            ${h.time ? ` • ${h.time}` : ''}
                            ${h.url ? ' • <span class="read-more">Read →</span>' : ''}
                        </div>
                    </div>
                `}).join('');
            } else {
                headlinesContainer.innerHTML = '<div class="headline-loading">No recent headlines</div>';
            }
            
            // Update Palmer's insight
            if (data.analysis) {
                insightContainer.innerHTML = `<div class="insight-text">"${data.analysis}"</div>`;
            } else {
                insightContainer.innerHTML = '<div class="insight-loading">Palmer is generating analysis...</div>';
                // Retry in 10 seconds
                setTimeout(fetchPalmerDashboard, 10000);
                return;
            }
            
            // Check for regime changes
            if (data.regime_changed && data.regime_change_details) {
                // Only show if not already dismissed this session
                if (!dismissedAlertTimestamp || new Date(data.timestamp) > new Date(dismissedAlertTimestamp)) {
                    showRegimeAlert(data.regime_change_details);
                }
            }
            
            // Update footer timestamp
            updateFooterTimestamp();
        })
        .catch(error => {
            console.error('Palmer fetch error:', error);
            insightContainer.innerHTML = '<div class="insight-loading">Unable to load Palmer. Server may be starting up.</div>';
            // Retry in 10 seconds
            setTimeout(fetchPalmerDashboard, 10000);
        });
}

// Fetch and display closed trades
function fetchClosedTrades() {
    fetch('/api/closed-trades')
        .then(response => response.json())
        .then(data => {
            // Update toggle badges (win rate + realized P&L)
            const winRateValue = document.getElementById('win-rate-value');
            const winRateBadge = document.getElementById('win-rate-badge');
            if (data.win_rate !== undefined) {
                winRateValue.textContent = `${data.win_rate.toFixed(0)}% W`;
                winRateBadge.className = 'win-rate-badge ' + (data.win_rate >= 50 ? 'positive' : 'negative');
            }
            
            const realizedPnlBadge = document.getElementById('realized-pnl-badge');
            if (realizedPnlBadge) {
                const pnl = data.total_pnl || 0;
                realizedPnlBadge.textContent = formatCurrency(pnl);
                realizedPnlBadge.className = 'realized-pnl-badge ' + (pnl >= 0 ? 'positive' : 'negative');
            }
            
            // Update stats inside the expanded section
            document.getElementById('total-wins').textContent = data.wins || 0;
            document.getElementById('total-losses').textContent = data.losses || 0;
            
            // Update closed trades table
            const tbody = document.getElementById('closed-trades-body');
            
            if (!data.trades || data.trades.length === 0) {
                tbody.innerHTML = '<tr><td colspan="4" class="loading">No closed trades yet</td></tr>';
                return;
            }
            
            tbody.innerHTML = data.trades.map(trade => {
                const pnlClass = trade.pnl >= 0 ? 'pnl-positive' : 'pnl-negative';
                const statusIcon = trade.pnl >= 0 ? '✓' : '✗';
                const statusClass = trade.pnl >= 0 ? 'win-icon' : 'loss-icon';
                const pnlPct = trade.pnl_pct !== undefined ? trade.pnl_pct : (trade.cost > 0 ? (trade.pnl / trade.cost * 100) : 0);
                const pnlPctStr = `${pnlPct >= 0 ? '+' : ''}${pnlPct.toFixed(1)}%`;
                
                return `
                    <tr>
                        <td>
                            <span class="${statusClass}">${statusIcon}</span>
                            <span class="closed-symbol">${trade.symbol}</span>
                        </td>
                        <td>${formatCurrency(trade.cost)}</td>
                        <td>${formatCurrency(trade.proceeds)}</td>
                        <td class="${pnlClass}">
                            ${formatCurrency(trade.pnl)}
                            <span class="pnl-pct">${pnlPctStr}</span>
                        </td>
                    </tr>
                `;
            }).join('');
        })
        .catch(error => {
            console.error('Closed trades fetch error:', error);
            document.getElementById('closed-trades-body').innerHTML = 
                '<tr><td colspan="4" class="loading">Error loading closed trades</td></tr>';
        });
}

// Update footer with last updated time
function updateFooterTimestamp() {
    const footerEl = document.getElementById('last-updated');
    if (footerEl) {
        const now = new Date();
        footerEl.textContent = `Updated ${now.toLocaleTimeString('en-US', { hour: 'numeric', minute: '2-digit' })}`;
    }
}

// Initial load
updateDashboard();
fetchClosedTrades();
fetchPalmerDashboard();
updateFooterTimestamp();

// Auto-refresh every 5 minutes (silent)
setInterval(() => {
    updateDashboard();
    fetchClosedTrades();
    fetchPalmerDashboard();
    updateFooterTimestamp();
}, 300000);
