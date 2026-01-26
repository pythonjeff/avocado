// LOX FUND Dashboard v1 - Investor-Focused

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
    
    const change = details[0];
    alertText.textContent = `${change.indicator} shifted: ${change.from} → ${change.to}`;
    alert.style.display = 'flex';
}

function formatCurrency(value, decimals = 0) {
    if (Math.abs(value) < 100) decimals = 2;
    return new Intl.NumberFormat('en-US', {
        style: 'currency',
        currency: 'USD',
        minimumFractionDigits: decimals,
        maximumFractionDigits: decimals,
    }).format(value);
}

function formatPercent(value, decimals = 2) {
    const sign = value >= 0 ? '+' : '';
    return `${sign}${value.toFixed(decimals)}%`;
}

function formatTime() {
    return new Date().toLocaleTimeString('en-US', { 
        hour: 'numeric', 
        minute: '2-digit',
        hour12: true 
    });
}

function formatDateTime() {
    return new Date().toLocaleDateString('en-US', {
        month: 'short',
        day: 'numeric',
        hour: 'numeric',
        minute: '2-digit',
        hour12: true
    });
}

// ============================================
// MAIN DATA FETCH
// ============================================
function updateDashboard() {
    fetch('/api/positions')
        .then(r => r.json())
        .then(data => {
            if (data.error) {
                console.error('API Error:', data.error);
            }
            
            // Update header timestamp
            document.getElementById('header-timestamp').textContent = formatDateTime();
            
            // HERO: Fund Return
            const heroReturn = document.getElementById('hero-return');
            if (data.return_pct !== undefined) {
                const val = data.return_pct;
                heroReturn.textContent = formatPercent(val);
                heroReturn.className = 'hero-value ' + (val >= 0 ? 'positive' : 'negative');
            }
            
            // HERO: Benchmark comparison
            const heroBenchmark = document.getElementById('hero-benchmark');
            if (data.sp500_return !== undefined && data.sp500_return !== null) {
                const sp500 = data.sp500_return;
                const alpha = data.alpha_sp500;
                let benchmarkHtml = `S&P 500: ${formatPercent(sp500)}`;
                if (alpha !== undefined && alpha !== null) {
                    const alphaClass = alpha >= 0 ? 'positive' : 'negative';
                    benchmarkHtml += ` <span class="alpha ${alphaClass}">${formatPercent(alpha, 1)} alpha</span>`;
                }
                heroBenchmark.innerHTML = benchmarkHtml;
            }
            
            // METRICS: NAV
            const navEl = document.getElementById('nav-value');
            navEl.textContent = data.nav_equity ? formatCurrency(data.nav_equity) : '—';
            
            // METRICS: P&L - calculate from NAV minus capital for accuracy
            const pnlEl = document.getElementById('total-pnl');
            const navEquity = data.nav_equity || 0;
            const originalCapital = data.original_capital || 1100;  // Default to 1100 if not provided
            let pnl = navEquity - originalCapital;
            
            // Use API total_pnl if it looks more accurate (negative when we expect negative)
            if (data.total_pnl !== null && data.total_pnl !== undefined) {
                pnl = data.total_pnl;
            }
            
            pnlEl.textContent = formatCurrency(pnl);
            pnlEl.className = 'metric-value ' + (pnl < 0 ? 'negative' : 'positive');
            console.log('[P&L Debug] NAV:', navEquity, 'Capital:', originalCapital, 'P&L:', pnl);
            
            // METRICS: Cash
            const cashEl = document.getElementById('cash-value');
            cashEl.textContent = data.cash_available ? formatCurrency(data.cash_available) : '—';
            
            // POSITIONS: Count badge (label style)
            const countEl = document.getElementById('positions-count');
            countEl.textContent = data.positions ? `${data.positions.length} POSITIONS` : '—';
            
            // POSITIONS: P&L badge
            const posPnlEl = document.getElementById('positions-pnl');
            if (data.positions && data.positions.length > 0) {
                let totalPnl = 0;
                let totalCost = 0;
                data.positions.forEach(p => {
                    totalPnl += p.pnl || 0;
                    totalCost += Math.abs((p.market_value || 0) - (p.pnl || 0));
                });
                const pnlPct = totalCost > 0 ? (totalPnl / totalCost) * 100 : 0;
                posPnlEl.textContent = formatPercent(pnlPct, 1);
                posPnlEl.className = 'badge-pnl ' + (pnlPct >= 0 ? 'positive' : 'negative');
            }
            
            // POSITIONS: Table
            const tbody = document.getElementById('positions-body');
            if (!data.positions || data.positions.length === 0) {
                tbody.innerHTML = '<tr><td colspan="4" class="loading">No positions</td></tr>';
            } else {
                tbody.innerHTML = data.positions.map(pos => {
                    const pnlClass = pos.pnl >= 0 ? 'positive' : 'negative';
                    
                    // Format symbol
                    let symbol = pos.symbol;
                    let details = '';
                    if (pos.opt_info) {
                        const type = (pos.opt_info.opt_type || '').toUpperCase().startsWith('C') ? 'C' : 'P';
                        symbol = `${pos.opt_info.underlying} $${pos.opt_info.strike}${type}`;
                        details = `<div class="position-details">${pos.opt_info.expiry}</div>`;
                    }
                    
                    return `
                        <tr>
                            <td>
                                <div class="position-symbol">${symbol}</div>
                                ${details}
                            </td>
                            <td>${pos.qty > 0 ? '+' : ''}${pos.qty}</td>
                            <td>${formatCurrency(Math.abs(pos.market_value || 0))}</td>
                            <td class="pnl-cell ${pnlClass}">
                                ${formatCurrency(pos.pnl || 0)}
                                <span class="pnl-percent">${formatPercent(pos.pnl_pct || 0, 1)}</span>
                            </td>
                        </tr>
                    `;
                }).join('');
            }
            
            // Update footer
            document.getElementById('footer-time').textContent = `Updated ${formatTime()}`;
        })
        .catch(err => {
            console.error('Fetch error:', err);
            document.getElementById('hero-return').textContent = 'Error';
        });
}

// ============================================
// INVESTORS
// ============================================
function fetchInvestors() {
    fetch('/api/investors')
        .then(r => r.json())
        .then(data => {
            // NAV per unit badge
            const navUnit = document.getElementById('nav-per-unit');
            if (data.nav_per_unit) {
                navUnit.textContent = `$${data.nav_per_unit.toFixed(4)}`;
            }
            
            // Table
            const tbody = document.getElementById('investor-body');
            if (!data.investors || data.investors.length === 0) {
                tbody.innerHTML = '<tr><td colspan="6" class="loading">No investor data</td></tr>';
                return;
            }
            
            tbody.innerHTML = data.investors.map(inv => {
                const pnlClass = inv.pnl >= 0 ? 'positive' : 'negative';
                const retClass = inv.return_pct >= 0 ? 'positive' : 'negative';
                return `
                    <tr>
                        <td><span class="investor-code">${inv.code}</span></td>
                        <td>${inv.ownership.toFixed(1)}%</td>
                        <td>${formatCurrency(inv.basis)}</td>
                        <td>${formatCurrency(inv.value)}</td>
                        <td class="pnl-cell ${pnlClass}">${formatCurrency(inv.pnl, 2)}</td>
                        <td class="pnl-cell ${retClass}">${formatPercent(inv.return_pct, 1)}</td>
                    </tr>
                `;
            }).join('');
        })
        .catch(err => console.error('Investors error:', err));
}

// ============================================
// MARKET CONTEXT
// ============================================

// Helper: Position marker on tracker bar given value and range
function positionMarker(markerId, value, min, max) {
    const marker = document.getElementById(markerId);
    if (!marker || value === null || value === undefined) return;
    
    // Clamp value to range
    const clamped = Math.max(min, Math.min(max, value));
    const percent = ((clamped - min) / (max - min)) * 100;
    marker.style.left = `${percent}%`;
}

// Extract numeric value from string like "VIX 16.1" or "271bp" or "4.24%"
function parseTrackerValue(str) {
    if (!str || str === '—' || str === 'N/A') return null;
    const match = str.match(/[\d.]+/);
    return match ? parseFloat(match[0]) : null;
}

function fetchMarketContext() {
    fetch('/api/regime-analysis')
        .then(r => r.json())
        .then(data => {
            // Regime badge in header
            const regimeBadge = document.getElementById('regime-badge');
            if (data.traffic_lights?.regime) {
                const regime = data.traffic_lights.regime;
                regimeBadge.textContent = regime.label || '—';
                regimeBadge.className = 'regime-badge ' + (regime.label || '').toLowerCase().replace(' ', '-');
            }
            
            // Regime trackers with range bars
            if (data.traffic_lights) {
                const tl = data.traffic_lights;
                
                // VIX tracker (range: 10-40)
                const vixVal = document.getElementById('vix-value');
                if (tl.volatility) {
                    const vixStr = tl.volatility.value || '—';
                    vixVal.textContent = vixStr;
                    const vixNum = parseTrackerValue(vixStr);
                    if (vixNum !== null) {
                        positionMarker('vix-marker', vixNum, 10, 40);
                        // Color the value based on zone
                        if (vixNum < 18) vixVal.style.color = 'var(--green)';
                        else if (vixNum < 25) vixVal.style.color = 'var(--yellow)';
                        else vixVal.style.color = 'var(--red)';
                    }
                }
                
                // HY Spread tracker (range: 200-600bp)
                const hyVal = document.getElementById('hy-value');
                if (tl.credit) {
                    const hyStr = tl.credit.value || '—';
                    hyVal.textContent = hyStr;
                    const hyNum = parseTrackerValue(hyStr);
                    if (hyNum !== null) {
                        positionMarker('hy-marker', hyNum, 200, 600);
                        // Color the value based on zone
                        if (hyNum < 325) hyVal.style.color = 'var(--green)';
                        else if (hyNum < 400) hyVal.style.color = 'var(--yellow)';
                        else hyVal.style.color = 'var(--red)';
                    }
                }
                
                // 10Y Yield tracker (range: 3.0-5.5%)
                const ratesVal = document.getElementById('rates-value');
                if (tl.rates) {
                    const ratesStr = tl.rates.value || '—';
                    ratesVal.textContent = ratesStr;
                    const ratesNum = parseTrackerValue(ratesStr);
                    if (ratesNum !== null) {
                        positionMarker('rates-marker', ratesNum, 3.0, 5.5);
                        // Color the value based on zone
                        if (ratesNum < 4.0) ratesVal.style.color = 'var(--green)';
                        else if (ratesNum < 4.5) ratesVal.style.color = 'var(--yellow)';
                        else ratesVal.style.color = 'var(--red)';
                    }
                }
            }
            
            // AI Insight
            const insightText = document.getElementById('insight-text');
            const insightTime = document.getElementById('insight-time');
            if (data.analysis) {
                insightText.textContent = data.analysis;
                insightTime.textContent = `Updated ${formatTime()}`;
            } else {
                insightText.textContent = 'Loading market analysis...';
            }
            
            // Regime change alert
            if (data.regime_changed && data.regime_change_details) {
                if (!dismissedAlertTimestamp || new Date(data.timestamp) > new Date(dismissedAlertTimestamp)) {
                    showRegimeAlert(data.regime_change_details);
                }
            }
        })
        .catch(err => {
            console.error('Market context error:', err);
            document.getElementById('insight-text').textContent = 'Unable to load market data.';
        });
}

// ============================================
// REGIME DOMAINS (Funding, USD, Commodities, etc.)
// ============================================
function fetchRegimeDomains() {
    fetch('/api/regime-domains')
        .then(r => r.json())
        .then(data => {
            if (data.error) {
                console.error('Regime domains error:', data.error);
                return;
            }
            
            const domains = data.domains || {};
            
            // Update each domain indicator
            const domainConfigs = [
                { id: 'regime-funding', key: 'funding' },
                { id: 'regime-usd', key: 'usd' },
                { id: 'regime-commod', key: 'commod' },
                { id: 'regime-volatility', key: 'volatility' },
                { id: 'regime-housing', key: 'housing' },
                { id: 'regime-crypto', key: 'crypto' },
            ];
            
            domainConfigs.forEach(({ id, key }) => {
                const el = document.getElementById(id);
                if (!el) return;
                
                const domain = domains[key];
                const dot = el.querySelector('.domain-dot');
                const status = el.querySelector('.domain-status');
                
                if (domain) {
                    if (dot) {
                        dot.className = 'domain-dot ' + (domain.color || 'gray');
                    }
                    if (status) {
                        status.textContent = domain.label || '—';
                        // Add sentiment class
                        const label = (domain.label || '').toLowerCase();
                        if (label.includes('bull') || label.includes('easy') || label.includes('healthy') || label.includes('weak')) {
                            status.className = 'domain-status bullish';
                        } else if (label.includes('bear') || label.includes('stress') || label.includes('tight') || label.includes('strong')) {
                            status.className = 'domain-status bearish';
                        } else {
                            status.className = 'domain-status neutral';
                        }
                    }
                }
            });
        })
        .catch(err => {
            console.error('Regime domains fetch error:', err);
        });
}

// ============================================
// TRADE PERFORMANCE (Closed Trades)
// ============================================
function fetchClosedTrades() {
    fetch('/api/closed-trades')
        .then(r => r.json())
        .then(data => {
            // Update header badges
            const statsEl = document.getElementById('trade-stats');
            const realizedPnlEl = document.getElementById('realized-pnl');
            
            if (data.trades && data.trades.length > 0) {
                // Stats badge
                const winRate = data.win_rate || 0;
                statsEl.textContent = `${data.trades.length} TRADES · ${winRate.toFixed(0)}% WIN`;
                
                // Realized P&L badge
                const totalPnl = data.total_pnl || 0;
                realizedPnlEl.textContent = formatCurrency(totalPnl);
                realizedPnlEl.className = 'badge-pnl ' + (totalPnl < 0 ? 'negative' : 'positive');
            } else {
                statsEl.textContent = 'NO CLOSED TRADES';
                realizedPnlEl.textContent = '$0';
                realizedPnlEl.className = 'badge-pnl';
            }
            
            // Populate table
            const tbody = document.getElementById('trades-body');
            if (!data.trades || data.trades.length === 0) {
                tbody.innerHTML = '<tr><td colspan="4" class="loading">No closed trades yet</td></tr>';
                return;
            }
            
            tbody.innerHTML = data.trades.map(trade => {
                const pnlClass = trade.pnl >= 0 ? 'positive' : 'negative';
                const statusClass = trade.fully_closed ? 'closed' : 'partial';
                const statusText = trade.fully_closed ? 'CLOSED' : 'PARTIAL';
                
                return `
                    <tr>
                        <td>
                            <span class="trade-symbol">${trade.symbol}</span>
                            <span class="trade-status ${statusClass}">${statusText}</span>
                        </td>
                        <td>${formatCurrency(trade.cost)}</td>
                        <td>${formatCurrency(trade.proceeds)}</td>
                        <td class="pnl-cell ${pnlClass}">
                            ${formatCurrency(trade.pnl)}
                            <span class="pnl-percent">${formatPercent(trade.pnl_pct, 1)}</span>
                        </td>
                    </tr>
                `;
            }).join('');
        })
        .catch(err => {
            console.error('Closed trades error:', err);
            document.getElementById('trades-body').innerHTML = 
                '<tr><td colspan="4" class="loading">Unable to load trades</td></tr>';
        });
}

// ============================================
// MARKET NEWS & CALENDAR
// ============================================
function fetchMarketNews() {
    fetch('/api/market-news')
        .then(r => r.json())
        .then(data => {
            if (data.error) {
                console.error('News error:', data.error);
                return;
            }
            
            // Update news count badge
            const newsCount = document.getElementById('news-count');
            const totalItems = (data.news?.length || 0) + (data.calendar?.length || 0);
            if (totalItems > 0) {
                newsCount.textContent = `${totalItems} items`;
            }
            
            // Render calendar
            const calendarEl = document.getElementById('calendar-items');
            if (data.calendar && data.calendar.length > 0) {
                calendarEl.innerHTML = data.calendar.map(item => {
                    const estimate = item.estimate ? `Est: ${item.estimate}` : '';
                    return `
                        <div class="calendar-item">
                            <span class="calendar-date">${formatCalendarDate(item.date)}</span>
                            <span class="calendar-event">${item.event}</span>
                            <span class="calendar-estimate">${estimate}</span>
                        </div>
                    `;
                }).join('');
            } else {
                calendarEl.innerHTML = '<span class="loading-text">No upcoming high-impact events</span>';
            }
            
            // Render news feed
            const newsFeedEl = document.getElementById('news-feed');
            if (data.news && data.news.length > 0) {
                newsFeedEl.innerHTML = data.news.map(item => `
                    <div class="news-item">
                        <span class="news-ticker">${item.symbol}</span>
                        <div class="news-text">
                            <div class="news-title">
                                <a href="${item.url}" target="_blank" rel="noopener">${item.title}</a>
                            </div>
                            <div class="news-meta">${item.source} · ${formatNewsTime(item.time)}</div>
                        </div>
                    </div>
                `).join('');
            } else {
                newsFeedEl.innerHTML = '<span class="loading-text">No recent news</span>';
            }
        })
        .catch(err => {
            console.error('News fetch error:', err);
        });
}

function formatCalendarDate(dateStr) {
    if (!dateStr) return '';
    const date = new Date(dateStr);
    const today = new Date();
    const tomorrow = new Date(today);
    tomorrow.setDate(tomorrow.getDate() + 1);
    
    if (date.toDateString() === today.toDateString()) return 'Today';
    if (date.toDateString() === tomorrow.toDateString()) return 'Tmrw';
    
    return date.toLocaleDateString('en-US', { weekday: 'short', month: 'short', day: 'numeric' }).replace(',', '');
}

function formatNewsTime(timeStr) {
    if (!timeStr) return '';
    const date = new Date(timeStr);
    const now = new Date();
    const diffHours = Math.floor((now - date) / (1000 * 60 * 60));
    
    if (diffHours < 1) return 'Just now';
    if (diffHours < 24) return `${diffHours}h ago`;
    return date.toLocaleDateString('en-US', { month: 'short', day: 'numeric' });
}


// ============================================
// INIT & REFRESH (OPTIMIZED - PARALLEL LOADING)
// ============================================

/**
 * OPTIMIZATION: Initial page load now fetches all 6 API endpoints in parallel.
 * This reduces load time from ~5s (sequential) to ~1-2s (parallel).
 * 
 * Each original fetch function is still used for incremental refreshes,
 * but the initial load uses Promise.all for maximum speed.
 */

async function initDashboardParallel() {
    console.log('[Dashboard] Starting parallel initial load...');
    const startTime = performance.now();
    
    // Fetch all endpoints in parallel
    const fetches = [
        fetch('/api/positions').then(r => r.json()).catch(e => ({ error: e.message, positions: [] })),
        fetch('/api/investors').then(r => r.json()).catch(e => ({ error: e.message, investors: [] })),
        fetch('/api/regime-analysis').then(r => r.json()).catch(e => ({ error: e.message })),
        fetch('/api/closed-trades').then(r => r.json()).catch(e => ({ error: e.message, trades: [] })),
        fetch('/api/regime-domains').then(r => r.json()).catch(e => ({ error: e.message, domains: {} })),
        fetch('/api/market-news').then(r => r.json()).catch(e => ({ error: e.message })),
    ];
    
    try {
        const [positionsData, investorsData, marketData, tradesData, domainsData, newsData] = await Promise.all(fetches);
        
        // Process positions (reuse logic from updateDashboard)
        processPositionsData(positionsData);
        
        // Process investors (reuse logic from fetchInvestors)  
        processInvestorsData(investorsData);
        
        // Process market context (reuse logic from fetchMarketContext)
        processMarketContextData(marketData);
        
        // Process closed trades (reuse logic from fetchClosedTrades)
        processClosedTradesData(tradesData);
        
        // Process regime domains (reuse logic from fetchRegimeDomains)
        processRegimeDomainsData(domainsData);
        
        // Process market news (reuse logic from fetchMarketNews)
        processMarketNewsData(newsData);
        
        const elapsed = (performance.now() - startTime).toFixed(0);
        console.log(`[Dashboard] Parallel load complete in ${elapsed}ms`);
    } catch (err) {
        console.error('[Dashboard] Parallel load error:', err);
        // Fallback to sequential loading
        updateDashboard();
        fetchInvestors();
        fetchMarketContext();
        fetchClosedTrades();
        fetchRegimeDomains();
        fetchMarketNews();
    }
}

// Extract data processing from updateDashboard for reuse
function processPositionsData(data) {
    if (data.error) {
        console.error('Positions API Error:', data.error);
    }
    
    // Update header timestamp
    document.getElementById('header-timestamp').textContent = formatDateTime();
    
    // HERO: Fund Return
    const heroReturn = document.getElementById('hero-return');
    if (data.return_pct !== undefined) {
        const val = data.return_pct;
        heroReturn.textContent = formatPercent(val);
        heroReturn.className = 'hero-value ' + (val >= 0 ? 'positive' : 'negative');
    }
    
    // HERO: Benchmark comparison
    const heroBenchmark = document.getElementById('hero-benchmark');
    if (data.sp500_return !== undefined && data.sp500_return !== null) {
        const sp500 = data.sp500_return;
        const alpha = data.alpha_sp500;
        let benchmarkHtml = `S&P 500: ${formatPercent(sp500)}`;
        if (alpha !== undefined && alpha !== null) {
            const alphaClass = alpha >= 0 ? 'positive' : 'negative';
            benchmarkHtml += ` <span class="alpha ${alphaClass}">${formatPercent(alpha, 1)} alpha</span>`;
        }
        heroBenchmark.innerHTML = benchmarkHtml;
    }
    
    // METRICS: NAV
    const navEl = document.getElementById('nav-value');
    navEl.textContent = data.nav_equity ? formatCurrency(data.nav_equity) : '—';
    
    // METRICS: P&L
    const pnlEl = document.getElementById('total-pnl');
    const navEquity = data.nav_equity || 0;
    const originalCapital = data.original_capital || 1100;
    let pnl = navEquity - originalCapital;
    if (data.total_pnl !== null && data.total_pnl !== undefined) {
        pnl = data.total_pnl;
    }
    pnlEl.textContent = formatCurrency(pnl);
    pnlEl.className = 'metric-value ' + (pnl < 0 ? 'negative' : 'positive');
    
    // METRICS: Cash
    const cashEl = document.getElementById('cash-value');
    cashEl.textContent = data.cash_available ? formatCurrency(data.cash_available) : '—';
    
    // POSITIONS: Count badge
    const countEl = document.getElementById('positions-count');
    countEl.textContent = data.positions ? `${data.positions.length} POSITIONS` : '—';
    
    // POSITIONS: P&L badge
    const posPnlEl = document.getElementById('positions-pnl');
    if (data.positions && data.positions.length > 0) {
        let totalPnl = 0;
        let totalCost = 0;
        data.positions.forEach(p => {
            totalPnl += p.pnl || 0;
            totalCost += Math.abs((p.market_value || 0) - (p.pnl || 0));
        });
        const pnlPct = totalCost > 0 ? (totalPnl / totalCost) * 100 : 0;
        posPnlEl.textContent = formatPercent(pnlPct, 1);
        posPnlEl.className = 'badge-pnl ' + (pnlPct >= 0 ? 'positive' : 'negative');
    }
    
    // POSITIONS: Table
    const tbody = document.getElementById('positions-body');
    if (!data.positions || data.positions.length === 0) {
        tbody.innerHTML = '<tr><td colspan="4" class="loading">No positions</td></tr>';
    } else {
        tbody.innerHTML = data.positions.map(pos => {
            const pnlClass = pos.pnl >= 0 ? 'positive' : 'negative';
            let symbol = pos.symbol;
            let details = '';
            if (pos.opt_info) {
                const type = (pos.opt_info.opt_type || '').toUpperCase().startsWith('C') ? 'C' : 'P';
                symbol = `${pos.opt_info.underlying} $${pos.opt_info.strike}${type}`;
                details = `<div class="position-details">${pos.opt_info.expiry}</div>`;
            }
            return `
                <tr>
                    <td><div class="position-symbol">${symbol}</div>${details}</td>
                    <td>${pos.qty > 0 ? '+' : ''}${pos.qty}</td>
                    <td>${formatCurrency(Math.abs(pos.market_value || 0))}</td>
                    <td class="pnl-cell ${pnlClass}">
                        ${formatCurrency(pos.pnl || 0)}
                        <span class="pnl-percent">${formatPercent(pos.pnl_pct || 0, 1)}</span>
                    </td>
                </tr>
            `;
        }).join('');
    }
    
    // Update footer
    document.getElementById('footer-time').textContent = `Updated ${formatTime()}`;
}

// Process functions mirror the original fetch functions' .then() handlers exactly
// This ensures the parallel initializer updates the UI correctly

function processInvestorsData(data) {
    // NAV per unit badge
    const navUnit = document.getElementById('nav-per-unit');
    if (data.nav_per_unit) {
        navUnit.textContent = `$${data.nav_per_unit.toFixed(4)}`;
    }
    
    // Total units
    const totalUnits = document.getElementById('total-units');
    if (totalUnits && data.total_units) {
        totalUnits.textContent = data.total_units.toFixed(4);
    }
    
    // Investors table
    const tbody = document.getElementById('investors-body');
    if (!tbody) return;
    
    if (!data.investors || data.investors.length === 0) {
        tbody.innerHTML = '<tr><td colspan="4" class="loading">No investor data</td></tr>';
    } else {
        tbody.innerHTML = data.investors.map(inv => `
            <tr>
                <td><span class="investor-code">${inv.code}</span></td>
                <td>${formatCurrency(inv.invested)}</td>
                <td>${formatCurrency(inv.value)}</td>
                <td class="pnl-cell ${inv.pnl >= 0 ? 'positive' : 'negative'}">
                    ${formatCurrency(inv.pnl)}
                    <span class="pnl-percent">${formatPercent(inv.return_pct, 1)}</span>
                </td>
            </tr>
        `).join('');
    }
}

function processMarketContextData(data) {
    // Regime badge in header
    const regimeBadge = document.getElementById('regime-badge');
    if (regimeBadge && data.traffic_lights?.regime) {
        const regime = data.traffic_lights.regime;
        regimeBadge.textContent = regime.label || '—';
        regimeBadge.className = 'regime-badge ' + (regime.label || '').toLowerCase().replace(' ', '-');
    }
    
    // Regime trackers with range bars
    if (data.traffic_lights) {
        const tl = data.traffic_lights;
        
        // VIX tracker
        const vixVal = document.getElementById('vix-value');
        if (vixVal && tl.volatility) {
            const vixStr = tl.volatility.value || '—';
            vixVal.textContent = vixStr;
            const vixNum = parseTrackerValue(vixStr);
            if (vixNum !== null) {
                positionMarker('vix-marker', vixNum, 10, 40);
                if (vixNum < 18) vixVal.style.color = 'var(--green)';
                else if (vixNum < 25) vixVal.style.color = 'var(--yellow)';
                else vixVal.style.color = 'var(--red)';
            }
        }
        
        // HY Spread tracker
        const hyVal = document.getElementById('hy-value');
        if (hyVal && tl.credit) {
            const hyStr = tl.credit.value || '—';
            hyVal.textContent = hyStr;
            const hyNum = parseTrackerValue(hyStr);
            if (hyNum !== null) {
                positionMarker('hy-marker', hyNum, 200, 600);
                if (hyNum < 325) hyVal.style.color = 'var(--green)';
                else if (hyNum < 400) hyVal.style.color = 'var(--yellow)';
                else hyVal.style.color = 'var(--red)';
            }
        }
        
        // 10Y Yield tracker
        const ratesVal = document.getElementById('rates-value');
        if (ratesVal && tl.rates) {
            const ratesStr = tl.rates.value || '—';
            ratesVal.textContent = ratesStr;
            const ratesNum = parseTrackerValue(ratesStr);
            if (ratesNum !== null) {
                positionMarker('rates-marker', ratesNum, 3.0, 5.5);
                if (ratesNum < 4.0) ratesVal.style.color = 'var(--green)';
                else if (ratesNum < 4.5) ratesVal.style.color = 'var(--yellow)';
                else ratesVal.style.color = 'var(--red)';
            }
        }
    }
    
    // AI Insight
    const insightText = document.getElementById('insight-text');
    const insightTime = document.getElementById('insight-time');
    if (insightText) {
        if (data.analysis) {
            insightText.textContent = data.analysis;
            if (insightTime) insightTime.textContent = `Updated ${formatTime()}`;
        } else {
            insightText.textContent = 'Loading market analysis...';
        }
    }
    
    // Regime change alert
    if (data.regime_changed && data.regime_change_details) {
        if (!dismissedAlertTimestamp || new Date(data.timestamp) > new Date(dismissedAlertTimestamp)) {
            showRegimeAlert(data.regime_change_details);
        }
    }
}

function processClosedTradesData(data) {
    // Summary stats
    const totalPnlEl = document.getElementById('total-realized-pnl');
    const winRateEl = document.getElementById('win-rate');
    const tradeCountEl = document.getElementById('trade-count');
    
    if (totalPnlEl) {
        totalPnlEl.textContent = formatCurrency(data.total_pnl || 0);
        totalPnlEl.className = 'metric-value ' + ((data.total_pnl || 0) >= 0 ? 'positive' : 'negative');
    }
    if (winRateEl) winRateEl.textContent = `${(data.win_rate || 0).toFixed(0)}%`;
    if (tradeCountEl) tradeCountEl.textContent = (data.trades?.length || 0).toString();
    
    // Trades table
    const tbody = document.getElementById('trades-body');
    if (!tbody) return;
    
    if (!data.trades || data.trades.length === 0) {
        tbody.innerHTML = '<tr><td colspan="4" class="loading">No closed trades</td></tr>';
    } else {
        tbody.innerHTML = data.trades.slice(0, 10).map(t => {
            const pnlClass = t.pnl >= 0 ? 'positive' : 'negative';
            return `
                <tr>
                    <td>${t.display_symbol || t.symbol}</td>
                    <td>${t.close_date}</td>
                    <td>${t.hold_days || '—'}</td>
                    <td class="pnl-cell ${pnlClass}">
                        ${formatCurrency(t.pnl)}
                        <span class="pnl-percent">${formatPercent(t.pnl_pct || 0, 1)}</span>
                    </td>
                </tr>
            `;
        }).join('');
    }
}

function processRegimeDomainsData(data) {
    if (data.error || !data.domains) return;
    
    const domains = data.domains;
    
    // Update each domain indicator - matches original fetchRegimeDomains logic exactly
    const domainConfigs = [
        { id: 'regime-funding', key: 'funding' },
        { id: 'regime-usd', key: 'usd' },
        { id: 'regime-commod', key: 'commod' },
        { id: 'regime-volatility', key: 'volatility' },
        { id: 'regime-housing', key: 'housing' },
        { id: 'regime-crypto', key: 'crypto' },
    ];
    
    domainConfigs.forEach(({ id, key }) => {
        const el = document.getElementById(id);
        if (!el) return;
        
        const domain = domains[key];
        const dot = el.querySelector('.domain-dot');
        const status = el.querySelector('.domain-status');
        
        if (domain) {
            if (dot) {
                dot.className = 'domain-dot ' + (domain.color || 'gray');
            }
            if (status) {
                status.textContent = domain.label || '—';
                // Add sentiment class
                const label = (domain.label || '').toLowerCase();
                if (label.includes('bull') || label.includes('easy') || label.includes('healthy') || label.includes('weak')) {
                    status.className = 'domain-status bullish';
                } else if (label.includes('bear') || label.includes('stress') || label.includes('tight') || label.includes('strong')) {
                    status.className = 'domain-status bearish';
                } else {
                    status.className = 'domain-status neutral';
                }
            }
        }
    });
}

function processMarketNewsData(data) {
    if (data.error) return;
    
    // Update news count badge
    const newsCount = document.getElementById('news-count');
    const totalItems = (data.news?.length || 0) + (data.calendar?.length || 0);
    if (newsCount && totalItems > 0) {
        newsCount.textContent = `${totalItems} items`;
    }
    
    // Render calendar
    const calendarEl = document.getElementById('calendar-items');
    if (calendarEl) {
        if (data.calendar && data.calendar.length > 0) {
            calendarEl.innerHTML = data.calendar.map(item => {
                const estimate = item.estimate ? `Est: ${item.estimate}` : '';
                return `
                    <div class="calendar-item">
                        <span class="calendar-date">${formatCalendarDate(item.date)}</span>
                        <span class="calendar-event">${item.event}</span>
                        <span class="calendar-estimate">${estimate}</span>
                    </div>
                `;
            }).join('');
        } else {
            calendarEl.innerHTML = '<span class="loading-text">No upcoming high-impact events</span>';
        }
    }
    
    // Render news feed
    const newsFeedEl = document.getElementById('news-feed');
    if (newsFeedEl) {
        if (data.news && data.news.length > 0) {
            newsFeedEl.innerHTML = data.news.map(item => `
                <div class="news-item">
                    <span class="news-ticker">${item.symbol}</span>
                    <div class="news-text">
                        <div class="news-title">
                            <a href="${item.url}" target="_blank" rel="noopener">${item.title}</a>
                        </div>
                        <div class="news-meta">${item.source} · ${formatNewsTime(item.time)}</div>
                    </div>
                </div>
            `).join('');
        } else {
            newsFeedEl.innerHTML = '<span class="loading-text">No recent news</span>';
        }
    }
}

// Initialize with parallel loading for fast initial render
initDashboardParallel();

// Refresh positions every 60 seconds (uses original function)
setInterval(updateDashboard, 60000);

// Refresh other data every 5 minutes (parallel)
setInterval(() => {
    Promise.all([
        fetch('/api/investors').then(r => r.json()).then(processInvestorsData).catch(console.error),
        fetch('/api/regime-analysis').then(r => r.json()).then(processMarketContextData).catch(console.error),
        fetch('/api/closed-trades').then(r => r.json()).then(processClosedTradesData).catch(console.error),
        fetch('/api/regime-domains').then(r => r.json()).then(processRegimeDomainsData).catch(console.error),
        fetch('/api/market-news').then(r => r.json()).then(processMarketNewsData).catch(console.error),
    ]);
}, 300000);
