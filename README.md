# Lox Capital — Discretionary Macro with Systematic Research

**A research platform for regime-aware portfolio management and tail-risk hedging**

---

## Executive Summary

Lox Capital is operated by Jeff Larson and is a **discretionary macro portfolio** with systematic research infrastructure. The platform combines real-time web analytics, AI-powered macro intelligence, and quantitative research tools to support regime-aware portfolio management and tail-risk hedging.

**Primary Interface**: Live web dashboard providing real-time portfolio analytics, regime monitoring, and position-level intelligence.

**Research Layer**: CLI tools for deep-dive analysis, scenario modeling, and trade idea generation.

**Philosophy**: Tools inform. Portfolio manager decides. Every trade decision follows rigorous regime assessment, risk analysis, and scenario stress-testing.

---

## Quick Start

```bash
# Daily workflow
lox status                    # Portfolio health
lox dashboard                 # All regimes at a glance

# Research a ticker
lox research -t NVDA          # Deep research
lox scan -t NVDA --want put   # Options chain

# Check regimes
lox regime vol                # Volatility regime
lox regime fiscal             # Fiscal regime

# Scenarios
lox scenario monte-carlo      # Monte Carlo simulation
```

---

## Technical Documentation

For reviewers and due diligence, comprehensive technical documentation is available:

| Document | Description |
|----------|-------------|
| [**EXECUTIVE_SUMMARY.md**](docs/EXECUTIVE_SUMMARY.md) | One-page technical overview for quick review |
| [**METHODOLOGY.md**](docs/METHODOLOGY.md) | Palmer, Monte Carlo, regime detection algorithms with full formulas |
| [**TECHNICAL_SPEC.md**](docs/TECHNICAL_SPEC.md) | Architecture, data lineage, error handling, deployment |
| [**V3_SUMMARY.md**](docs/V3_SUMMARY.md) | Platform overview and design decisions |

---

## Live Portfolio Dashboard

### Access

🌐 **Production:** [**https://loxfund.com**](https://loxfund.com)

**Local Development:**
```bash
cd dashboard
python app.py
# Navigate to http://localhost:5001
```

### Core Capabilities

**Portfolio Analytics**
- **Liquidation NAV**: Conservative bid/ask marking for accurate portfolio valuation
- **Unrealized P&L**: Real-time profit/loss with percentage attribution
- **Performance Attribution**: Fund return vs S&P 500 and BTC with alpha calculation
- **Position-Level P&L**: Individual position performance with theory explanations

**Palmer — Macro Intelligence Engine**
- **Traffic Light Indicators**: Real-time regime classification (RISK-ON/CAUTIOUS/RISK-OFF)
- **Volatility Monitoring**: VIX level with percentile and regime implications
- **Credit Conditions**: HY spreads with stress indicators
- **Rates Environment**: 10Y yield with historical context
- **LLM Analysis**: Concise macro insights updated every 30 minutes
- **Regime Change Alerts**: Early detection of macro shifts with detailed explanations

**Monte Carlo Forecast**
- **6-Month Outlook**: Scenario simulation based on current regime persistence
- **Expected Return**: Mean P&L projection
- **Tail Risk**: VaR 95% and win probability
- **Regime-Conditional**: Adjusts assumptions based on current macro state

**Position Intelligence**
- **LLM-Generated Theories**: Macro-aware explanations of profit conditions for each position
- **Regime-Conditional Analysis**: Considers VIX, HY spreads, 10Y yield, and regime status
- **Actionable Insights**: Specific catalysts and market dynamics required for profitability
- **Dynamic Updates**: Theories adapt to current portfolio and macro conditions

**Economic Intelligence**
- **Today's Releases**: Economic calendar with actual vs estimate analysis
- **Beat/Miss Indicators**: Visual indicators for economic surprises
- **Trading Economics Integration**: Primary data source with timezone-accurate timestamps
- **Portfolio News**: Dynamic headlines filtered by active positions

---

## Philosophy

Lox Capital combines **discretionary portfolio management** with **systematic research tools**. Every trade decision is made by a human analyst after rigorous examination of macro regimes, quantitative metrics, and market context.

The platform provides:
- **Regime classification** across inflation, growth, liquidity, and volatility
- **Real-time web dashboard** with live portfolio analytics and macro intelligence
- **Quantitative dashboards** with z-scores, percentiles, and historical context
- **PhD-level research briefs** synthesizing news, data, and scenario analysis
- **Trade idea generation** as starting points for further analysis

**The tools inform. The portfolio manager decides.**

---

## Performance

| Metric | Value |
|--------|-------|
| **Inception** | January 9, 2026 |
| **Total Capital** | $1,100 |
| **Current NAV** | $1,024 |
| **TWR (Since Inception)** | **-5.60%** |
| **Benchmark (SPY)** | -0.70% |
| **Alpha** | -4.9% |
| **Strategy** | Discretionary macro with tail-risk hedging |

*Last updated: Jan 24, 2026 • Live at [loxfund.com](https://loxfund.com)*

---

## Investment Process

### 1. Morning Dashboard Review
Every morning begins with the **live web dashboard** for real-time portfolio and macro context:

**Web Dashboard** (Primary):
- Open browser to dashboard URL
- Review Palmer's regime analysis and traffic lights
- Check Monte Carlo 6-month forecast
- Review position-level theories and P&L attribution

**CLI Research** (Deep Dive):
```bash
lox status                   # Portfolio health
lox dashboard                # All regimes at a glance
lox regime vol --llm         # Volatility with LLM analysis
```

### 2. Deep Research
Before any trade, I conduct multi-source analysis:

**Ticker-Level Research**:
```bash
lox research -t NVDA              # Deep ticker research
lox research -t AAPL --llm        # With LLM analysis
lox chat -t FXI                   # Interactive discussion
```

**Regime Research**:
```bash
lox regime vol                    # Volatility regime
lox regime fiscal                 # Fiscal (deficits, TGA)
lox regime rates                  # Rates/curve analysis
lox regime macro                  # Macro overview
```

### 3. Options Scanning
Find options for trade ideas:

```bash
lox scan -t NVDA --want put       # Options chain (30-365 DTE default)
lox scan -t CRWV --min-days 100   # Long-dated options
lox options best NVDA --budget 500  # Best under budget
```

### 4. Risk Analysis
Before execution, stress-test the portfolio:

```bash
lox scenario monte-carlo          # Monte Carlo simulation
lox scenario stress               # Stress testing
lox analyze --depth deep          # Full position analysis
```

### 5. Execution Decision
After completing research, I make the final call:
- Size based on conviction and portfolio impact
- Entry triggers based on technical/catalyst timing
- Stops and targets informed by scenario analysis

**No trade is executed without completing this workflow.**

---

## Recent Upgrades

### v1 Dashboard (January 24, 2026) — Now Live at [loxfund.com](https://loxfund.com)

**Investor Dashboard**
- **TWR Performance**: GIPS-compliant time-weighted returns as headline metric
- **Benchmark Comparison**: S&P 500 performance with alpha calculation
- **Liquidation NAV**: Conservative bid/ask marking for accurate portfolio valuation
- **Investor Ledger**: Individual investor P&L with unitized returns

**Market Intelligence**
- **Regime Trackers**: Visual range bars for VIX, HY Spread, 10Y Yield with smart thresholds
- **Regime Domain Grid**: Six macro domains (Funding, USD, Commodities, Volatility, Housing, Crypto)
- **Palmer AI Analysis**: LLM-generated macro context with portfolio impact assessment
- **Traffic Light System**: Real-time RISK-ON / CAUTIOUS / RISK-OFF classification

**News & Economic Calendar**
- **Portfolio News Feed**: Headlines filtered by active positions (SOFI, TAN, IWM, FXI, VIXM)
- **Economic Calendar**: Upcoming high-impact events (Fed speeches, PPI, CPI, NFP)
- **Source Attribution**: News sources with timestamps

**Position Intelligence**
- **LLM Position Theories**: Macro-aware explanations for each position's profit conditions
- **Monte Carlo Forecast**: 6-month outlook with VaR 95% and win probability
- **Trade Performance**: Realized P&L history with win rate tracking

**Design**
- **Collapsed Accordions**: Clean default view with key metrics visible at a glance
- **Mobile-Responsive**: Professional interface optimized for all devices
- **Subtle Animations**: Smooth expand/collapse with hover effects

### Enhanced Research Tools
- **Standardized CLI Flags**: Uniform `--llm`, `--features`, `--json` across all `lox labs` commands
- **Trading Economics Integration**: Primary calendar data source with FMP fallback
- **Live Portfolio Monte Carlo**: Real-time scenario analysis using actual positions
- **Dynamic Portfolio Analysis**: LLM adapts to current positions for contextual insights

### Deep Ticker Research (January 2026) — Primary Trade Research Driver

The `lox labs ticker deep` command has evolved into our **primary research tool** for individual securities. It provides institutional-grade analysis with asset-type awareness, distinguishing between ETFs and individual stocks.

**Asset-Type Aware Analysis**
- **Automatic Detection**: Identifies ETFs by holdings data, company name patterns (iShares, Vanguard, SPDR, etc.)
- **Tailored Metrics**: Shows relevant data for each asset type — no earnings analysis for ETFs, no fund flows for stocks
- **Context-Aware LLM**: Prompts adapt to provide fund thesis for ETFs, earnings preview for stocks

**ETF Analysis Features**
```bash
lox labs ticker deep -t FXI --llm    # China large-cap ETF
lox labs ticker deep -t TIP --llm    # TIPS bond ETF
```
- **Fund Profile**: AUM, expense ratio, holdings count, category
- **Top Holdings**: Asset breakdown with weights (uses `name` fallback for bond holdings)
- **Performance & Flows**: 1W, 1M, 3M, YTD returns + fund flow signals (volume trend proxy for inflows/outflows)
- **Institutional Holders**: Top 10 investors with share counts and position changes (who's buying/selling)
- **LLM Analysis**: Fund thesis, holdings concentration, risk factors, market environment fit

**Stock Analysis Features**
```bash
lox labs ticker deep -t AAPL --llm   # Individual stock
lox labs ticker deep -t NVDA --llm   # Growth stock
```
- **Company Profile**: Sector, industry, market cap, description
- **Price & Technicals**: Current price, day/52-week ranges, volume analysis
- **Hedge Fund Metrics**: P/E, P/S, P/B, EV/EBITDA, ROE, ROIC, margins, FCF yield
- **Earnings & Estimates**: Next earnings date, analyst EPS/revenue estimates, historical beat rate
- **SEC Filings**: Recent 8-K, 10-K, 10-Q with items/descriptions
- **Analyst Targets**: Consensus, low, high price targets with analyst count
- **LLM Analysis**: Bull/bear case, earnings preview, near-term catalysts

**Interactive Ticker Chat**
```bash
lox chat -t AAPL    # Chat with AAPL context loaded
lox chat -t FXI     # Discuss China ETF with full research context
```
Loads deep research data (profile, earnings, news, SEC filings) into chat for focused ticker discussions.

**Example Output: ETF Institutional Holders**
```
                     Top Institutional Holders                        
┏━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━┳━━━━━━━━━━━━┳━━━━━━━━━━━━┳━━━━━━━━━━━━┓
┃ Institution                    ┃     Shares ┃     Change ┃ Reported   ┃
┡━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━╇━━━━━━━━━━━━╇━━━━━━━━━━━━╇━━━━━━━━━━━━┩
│ MORGAN STANLEY                 │ 30,503,443 │ +2,949,582 │ 2025-09-30 │
│ JANE STREET GROUP, LLC         │  8,330,241 │ +8,322,966 │ 2025-09-30 │
│ BlackRock, Inc.                │  6,151,016 │ +1,852,363 │ 2025-09-30 │
└────────────────────────────────┴────────────┴────────────┴────────────┘
```

This research forms the foundation for every trade decision — understanding who's investing, what the fund/company does, and how it fits our macro thesis.

### v2 Regime System (January 25, 2026)

**Unified Regime Framework**
- **10 Regime Domains**: Macro, Volatility, Rates, Funding, Fiscal, Commodities, Housing, Monetary, USD, Crypto
- **Unified State Builder**: Single `lox labs unified` command shows all regimes with scores
- **ML Feature Extraction**: Export flat feature vectors with `--json` for model training
- **Standardized Interface**: All regimes return consistent `RegimeResult` with name, label, score, tags

**Leading Indicator Adjustments (Edge Enhancement)**
- **7 Warning Signals**: Yield curve inversion, VIX elevated/complacent, credit widening, funding stress, rates shock
- **Probability Adjustments**: Signals adjust transition probabilities (e.g., inverted curve → risk-off prob ×1.8)
- **Research-Backed**: Each indicator sourced from academic research (Estrella & Mishkin, CBOE, Gilchrist & Zakrajsek)
- **Transparent**: Active signals displayed in `lox labs transitions` output

**Regime Transition Probabilities**
- **Historical Frequencies**: Base probabilities from 2000-2024 market data
- **Horizon Scaling**: 1-month, 3-month, 6-month horizons with mean-reversion
- **Monte Carlo Integration**: Scenarios weighted by transition probability
- **Path Simulation**: `simulate_regime_path()` for multi-step forecasts

**New Commands**
```bash
lox labs unified              # View all 10 regimes with scores
lox labs unified --json       # Export ML features
lox labs transitions          # Transition matrix with signal adjustments
lox labs transitions --no-adjust  # Raw historical frequencies
```

---

## Research Capabilities

### Regime Analysis
```bash
lox regime vol                    # Volatility regime
lox regime vol --llm              # With LLM analysis
lox regime fiscal                 # Fiscal (deficits, TGA)
lox regime funding                # Funding markets (SOFR)
lox regime rates                  # Rates/yield curve
lox regime macro                  # Macro overview
```

### Ticker Research
```bash
lox research -t NVDA              # Deep ticker research
lox research -t AAPL --llm        # With LLM analysis
```

### Options Scanning
```bash
lox scan -t NVDA                  # Default: puts, 30-365 DTE
lox scan -t CRWV --want put --min-days 100 --max-days 400
lox options best NVDA --budget 500
```

### Scenario Analysis
```bash
lox scenario monte-carlo          # Monte Carlo simulation
lox scenario stress               # Stress testing
```

### Advanced Tools (Power Users)
```bash
lox labs ticker deep -t AAPL --llm    # Full ticker deep dive
lox labs mc-v01 --regime RISK_OFF     # Specific regime scenario
lox labs unified                       # All 10 regimes
```

---

## Quick Reference

### CLI Structure

```
lox                           # Help with examples
├── scan -t TICKER            # Options chain scanner
├── research -t TICKER        # Deep ticker research
├── status                    # Portfolio health
├── dashboard                 # All regimes at a glance
│
├── regime                    # Economic regime analysis
│   ├── vol                   # Volatility (VIX)
│   ├── fiscal                # Fiscal (deficits, TGA)
│   ├── funding               # Funding markets (SOFR)
│   ├── rates                 # Yield curve
│   └── macro                 # Macro overview
│
├── scenario                  # Portfolio scenarios
│   ├── monte-carlo           # Monte Carlo simulation
│   └── stress                # Stress testing
│
├── trade                     # Trade execution
├── ideas                     # Trade ideas
├── chat                      # Interactive research chat
├── options                   # Full options toolset
└── labs                      # Advanced tools (power users)
```

### Daily Workflow
```bash
# Morning: Dashboard review (5 min)
lox status                    # Portfolio health
lox dashboard                 # All regimes at a glance

# Research (as needed)
lox research -t NVDA          # Deep ticker research
lox regime vol                # Volatility regime
lox regime fiscal             # Fiscal regime

# Options scanning
lox scan -t CRWV --want put   # Options chain
lox scan -t NVDA --min-days 60 --max-days 180

# Ideas and scenarios
lox suggest                   # Trade ideas
lox scenario monte-carlo      # Monte Carlo simulation

# EOD: Record NAV
lox nav snapshot
```

### Dashboard Access
| Environment | URL | Command |
|------------|-----|---------|
| **Production** | [**loxfund.com**](https://loxfund.com) | Direct browser access |
| **Local** | http://localhost:5001 | `cd dashboard && python app.py` |

### Core Commands
| Command | Purpose |
|---------|---------|
| `lox status` | Portfolio health at a glance |
| `lox dashboard` | All regime pillars |
| `lox scan -t TICKER` | Options chain scanner |
| `lox research -t TICKER` | Deep ticker research |
| `lox regime vol` | Volatility regime |
| `lox regime fiscal` | Fiscal regime |
| `lox scenario monte-carlo` | Monte Carlo simulation |

### Research Commands
| Command | Purpose |
|---------|---------|
| `lox research -t AAPL` | Deep ticker research |
| `lox research -t NVDA --llm` | With LLM analysis |
| `lox regime vol --llm` | Volatility with LLM |
| `lox regime rates` | Rates/curve analysis |
| `lox labs ticker deep -t AAPL` | Full ticker deep dive (legacy) |

### Options Commands
| Command | Purpose |
|---------|---------|
| `lox scan -t NVDA` | Options chain (default: puts, 30-365 DTE) |
| `lox scan -t CRWV --want put --min-days 100` | Custom DTE range |
| `lox options best NVDA --budget 500` | Best options under budget |

### Interactive Chat
| Command | Purpose |
|---------|---------|
| `lox chat` | Interactive research chat |
| `lox chat -t AAPL` | Ticker-focused chat |
| `lox chat -c fiscal` | Chat with regime context |

---

## Strategy

### Mandate
Discretionary macro portfolio management with systematic research support. Primary focus on tail-risk hedging with positive carry during calm periods.

### Thesis
- Persistent inflation risk above 2010s baseline
- Rising macro volatility from fiscal/rates dynamics
- Structural shift in Treasury issuance → higher vol premium
- Regime awareness improves timing and sizing

### Implementation
- **Long convexity**: OTM puts on SPY/QQQ, VIX calls
- **Delta management**: Adjust exposures based on regime signals
- **Carry optimization**: Time spreads and premium selling in favorable regimes
- **Cross-asset**: Sector rotation based on rate/vol/growth implications

### Risk Limits
| Metric | Limit |
|--------|-------|
| Max position size | 15% NAV |
| Max portfolio delta | ±30% |
| Max theta decay | 2% NAV/month |
| VaR 95% (3M) | <10% |

---

## Data Sources

| Source | Data |
|--------|------|
| **FRED** | Macro time series (rates, employment, inflation) |
| **Alpaca** | Real-time quotes, positions, news with full content |
| **Trading Economics** | Economic calendar (primary source, timezone-accurate) |
| **FMP** | Stock news, economic calendar (fallback), company data |
| **CBOE** | VIX, term structure, options data |

The LLM analyst aggregates these sources into research briefs with proper citations. The dashboard integrates all sources for real-time portfolio and macro intelligence.

---

## Installation

### Requirements
- **Python 3.10+** (check with `python --version`)
- API keys for: Alpaca, OpenAI, FRED, FMP (see `.env.example`)

### Quick Start
```bash
# Clone and install
git clone <repo>
cd ai-options-trader-starter
pip install -e .

# Configure API keys (copy and edit)
cp .env.example .env
# Edit .env with your API keys

# Verify CLI installation
lox --help
lox status
```

### API Keys Required
| Service | Purpose | Get Key |
|---------|---------|---------|
| **Alpaca** | Brokerage, positions, market data | [alpaca.markets](https://app.alpaca.markets/) |
| **OpenAI** | LLM analysis (`--llm`, chat, analyze) | [platform.openai.com](https://platform.openai.com/api-keys) |
| **FRED** | Macro/economic time series | [fred.stlouisfed.org](https://fred.stlouisfed.org/docs/api/api_key.html) |
| **FMP** | News, calendar, quotes, company data | [financialmodelingprep.com](https://financialmodelingprep.com/developer/docs/) |
| Trading Economics | Economic calendar (optional) | [tradingeconomics.com](https://tradingeconomics.com/api/) |

### Dashboard Setup
```bash
# Install dashboard dependencies
cd dashboard
pip install -r requirements.txt

# Run locally
python app.py
# Navigate to http://localhost:5001
```

The dashboard requires:
- All API keys configured in `.env` (in project root)
- `FUND_TOTAL_CAPITAL` set for accurate P&L (defaults to $1000)
- Background refresh runs automatically (30-minute intervals)
- Force refresh: `curl "http://localhost:5001/api/regime-analysis/force-refresh?secret=YOUR_ADMIN_SECRET"`

---

## Architecture

```
lox/
├── Top-Level Commands (Daily Use)
│   ├── scan           → Options chain scanner
│   ├── research       → Deep ticker research
│   ├── status         → Portfolio health
│   ├── dashboard      → All regimes at a glance
│   ├── regime *       → Economic regime analysis
│   └── scenario *     → Portfolio scenarios
│
├── Web Dashboard (Primary Interface)
│   ├── Real-time portfolio analytics
│   ├── Palmer macro intelligence
│   ├── Monte Carlo forecast
│   ├── Position-level LLM theories
│   └── Economic calendar integration
│
├── Subgroups
│   ├── options        → Full options toolset
│   ├── trade          → Trade execution
│   ├── ideas          → Trade idea generation
│   ├── chat           → Interactive research
│   └── labs           → Advanced tools (power users)
│
├── Data Layer
│   ├── FRED           → Macro time series
│   ├── Alpaca         → Market data + positions
│   ├── FMP            → News + calendar + quotes
│   └── Polygon        → Options data (OI, greeks)
│
└── Analysis Layer
    ├── Regime pillars → Vol, fiscal, funding, rates, macro
    ├── LLM analyst    → Research synthesis
    └── Scenarios      → Monte Carlo, stress testing
```

---

**Lox Capital** | [loxfund.com](https://loxfund.com) | Discretionary Macro | Since Jan 2026

*The platform provides research and analysis tools. All investment decisions are made by the portfolio manager after independent evaluation. Not investment advice.*
