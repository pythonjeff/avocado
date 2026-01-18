# Lox — Quantitative Options Trading System

**A systematic tail-risk hedging strategy combining machine learning, regime analysis, and options selection**

---

## Overview

Lox is a quantitative trading system designed for **institutional-grade options portfolio construction and risk management**. The system integrates:

- **ML-driven options discovery** across liquid baskets
- **Monte Carlo risk analysis** with position-level attribution
- **Macro regime classification** and calendar-aware positioning
- **LLM integration** for market synthesis and trade oversight
- **Single-name analysis** for deep fundamental + technical views

### Performance

- **Strategy**: Tail-risk hedging with systematic rebalancing
- **Benchmark**: S&P 500 Total Return
- **Objective**: Positive Sharpe with convex payoffs during market stress
- **Live since**: January 2026 | **Initial capital**: $550

*Detailed performance metrics available via `lox weekly report`*

---

## Core Capabilities

### 1. ML Options Discovery
**Find high-probability options trades across any basket**

```bash
# Discover trades across extended basket (top liquid options)
lox autopilot run-once --engine ml --basket extended

# Multi-strategy approach (macro + vol + housing sleeves)
lox autopilot run-once --sleeves macro vol housing --llm

# Predictions only (no execution)
lox autopilot run-once --predictions --top-predictions 25
```

**What it does:**
- Builds regime-aware feature matrix (inflation, rates, vol, liquidity)
- ML model ranks instruments by expected excess return vs SPY
- Budgets positions with defined-risk options structures
- Optional LLM gate for trade approval

### 2. Monte Carlo Risk Analysis
**Position-level P&L simulation with 8 regime scenarios**

```bash
# Test tail hedges in crash scenario
lox labs mc-v01 --regime RISK_OFF --real

# Test theta bleed in calm markets
lox labs mc-v01 --regime VOL_CRUSH --real

# Baseline 6-month outlook
lox labs mc-v01 --regime ALL --real

# Available regimes: RISK_OFF, CREDIT_STRESS, SLOW_BLEED, RATES_SHOCK,
#                    STAGFLATION, GOLDILOCKS, VOL_CRUSH, ALL
```

**What it provides:**
- **Real underlying prices** from FMP (no more strike-as-proxy)
- Position-level P&L using Taylor approximation (Δ·ΔS + ½Γ(ΔS)² + Vega·Δσ + Θ·Δt)
- Separate equity and IV dynamics (correlated with vol-of-vol)
- 8 regime-conditional scenarios (crash, credit stress, slow bleed, rates shock, etc.)
- VaR, CVaR, skewness, and tail risk probabilities
- Scenario attribution (top 3 winners/losers with market moves)
- Sanity checks (greeks must sum correctly or MC halts)

### 3. Macro Analysis & LLM Integration
**Fed policy, liquidity, and regime-aware market synthesis**

```bash
# Comprehensive macro dashboard
lox labs fedfunds-outlook

# Regime snapshots
lox labs commodities snapshot
lox labs housing snapshot
lox labs fiscal snapshot
```

**What it tracks:**
- **Fed policy**: Corridor dynamics, TGA, reserves, RRP, net liquidity
- **Inflation**: CPI, median CPI, breakevens, disconnect analysis
- **Growth**: Payrolls, claims, unemployment
- **Credit & Vol**: HY spreads, VIX, term structure
- **LLM synthesis**: PhD-level macro outlook with portfolio implications

### 4. Regime Classification
**Multi-dimensional regime framework across macro, funding, commodities, housing**

```bash
# Current macro regime
lox labs macro snapshot

# Funding/liquidity regime
lox labs funding snapshot

# Commodities regime (gold/oil)
lox labs commodities snapshot

# Housing/MBS regime
lox labs housing snapshot
```

**Regimes detected:**
- **Macro**: Stagflation, disinflationary, goldilocks, inflationary
- **Funding**: Orderly, fragile, stressed (based on SOFR-IORB, reserves, RRP)
- **Commodities**: Breakout, neutral, risk-off
- **Housing**: Stressed, cooling, stable, heating

### 5. Single-Ticker Options Selector
**Deep dive into individual names with liquidity filtering**

```bash
# Interactive options scanner (high-variance, in-budget)
lox options moonshot --ticker NVDA

# Basket scan with ML thesis
lox options moonshot --basket extended

# Direct options recommendation
lox options recommend --ticker SPY --direction bearish
```

**Features:**
- Filters for liquidity (open interest, bid/ask spread)
- Shows required underlying move for +5% option profit
- Generates LLM thesis (grounded in recent news)
- Interactive prompts for trade execution

### 6. Deep Ticker/ETF Analysis
**Fundamental + technical + regime context**

```bash
# Account summary with macro context
lox account summary

# Detailed position analysis
lox account positions

# Trade history and P&L attribution
lox account trades --since 30

# Buy shares with cash allocation
lox account buy-shares --ticker SQQQ --pct-cash 0.5
```

---

## Installation

### Prerequisites
- Python 3.10+
- API keys: Alpaca (execution), FRED (macro data), FMP (news/calendar), OpenAI (LLM)

### Setup

```bash
# Clone and install
git clone <repo>
cd ai-options-trader-starter
pip install -e .

# Configure API keys in .env
cat > .env << EOF
ALPACA_API_KEY=your_key
ALPACA_API_SECRET=your_secret
ALPACA_PAPER=true

FRED_API_KEY=your_fred_key
FMP_API_KEY=your_fmp_key
OPENAI_API_KEY=your_openai_key

AOT_PRICE_SOURCE=fmp
EOF
```

### Verify Installation

```bash
# Test macro data pipeline
lox labs macro snapshot

# Test Monte Carlo
lox labs mc-v01

# Test ML engine
lox autopilot run-once --predictions --top-predictions 5
```

---

## Daily Workflow

### Morning: Market Context
```bash
# 1. Macro/regime snapshot
lox labs fedfunds-outlook

# 2. Account briefing
lox account summary
```

### Midday: Trade Generation
```bash
# 3. ML-driven trade ideas (with LLM oversight)
lox autopilot run-once --engine ml --basket extended --llm --llm-news

# 4. Execute approved trades (paper-first)
lox autopilot run-once --engine ml --basket extended --llm --llm-gate --execute
```

### EOD: Risk Review
```bash
# 5. Portfolio risk analysis (multiple regimes)
lox labs mc-v01 --regime RISK_OFF --real      # Crash scenario
lox labs mc-v01 --regime VOL_CRUSH --real     # Worst case for hedges
lox labs mc-v01 --regime SLOW_BLEED --real    # Theta vs direction

# 6. Weekly performance report (Fridays)
lox weekly report
```

---

## Strategy Overview

### Mandate
**Systematic tail-risk hedging with positive carry during calm periods**

### Thesis
- Persistent inflation risk above 2010s baseline
- Rising macro volatility from fiscal/rates dynamics
- Structural shift in Treasury issuance → higher vol premium

### Implementation
- **Long convexity**: OTM puts on SPY/QQQ, VIX calls
- **Delta hedge**: Short equity/credit to neutralize directional exposure
- **Carry optimization**: Time spreads and selling near-the-money premium
- **Regime-aware**: Adjust Greeks based on macro/funding/vol regimes

### Risk Management
- **Max position size**: 15% of NAV per underlying
- **Max portfolio delta**: ±30%
- **Max theta decay**: 2% NAV per month
- **VaR 95% target**: <10% over 3M horizon

---

## Key Features

### Multi-Sleeve Architecture
Run multiple strategies in parallel with unified risk aggregation:
```bash
lox autopilot run-once --sleeves macro vol housing --engine ml
```

### LLM Risk Overlay
Optional AI gate that must approve all trades:
```bash
lox autopilot run-once --llm-gate --execute
```

### Calendar-Aware Positioning
Automatically loads economic calendar (FOMC, CPI, payrolls) and adjusts Greeks:
```bash
lox labs calendar --days 14
```

### Liquidity Filters
All options filtered for:
- Minimum open interest (customizable)
- Maximum bid/ask spread (% of mid)
- Minimum daily volume

---

## Testing

```bash
# Run full test suite
pytest -q

# Test specific modules
pytest tests/test_macro_playbook.py
pytest tests/test_monte_carlo.py -v
```

---

## Documentation

- **Architecture**: `docs/ARCHITECTURE_SLEEVES.md`
- **Objectives**: `docs/OBJECTIVES.md`
- **Constitution**: `docs/PROJECT_CONSTITUTION.md`
- **Monte Carlo v0.1**: `docs/MONTE_CARLO_V01_SUMMARY.md`
- **Interpretability**: `docs/MONTE_CARLO_INTERPRETABILITY.md`

---

## Performance Tracking

### NAV Accounting
```bash
# Record NAV snapshot
lox nav snapshot

# Record investor contribution
lox nav investor contribute --name "Investor A" --amount 10000

# Generate investor statements
lox nav investor statement --name "Investor A"
```

### Reporting
```bash
# Weekly report (NAV, trades, macro, performance)
lox weekly report

# Account summary (positions, P&L, risk metrics)
lox account summary

# Historical P&L
lox account trades --since 90
```

---

## Advanced Usage

### Monte Carlo Regime Testing
**8 comprehensive scenarios for stress testing your portfolio:**

```bash
# DOWNSIDE SCENARIOS:
lox labs mc-v01 --regime RISK_OFF --real        # -25% drift, 35% vol, 25% jump prob (max tail risk)
lox labs mc-v01 --regime CREDIT_STRESS --real   # -15% drift, credit spreads widen
lox labs mc-v01 --regime SLOW_BLEED --real      # -8% drift, low vol (death by 1000 cuts)
lox labs mc-v01 --regime RATES_SHOCK --real     # -10% drift, Fed tightening pressure
lox labs mc-v01 --regime STAGFLATION --real     # -2% drift, persistent inflation

# UPSIDE SCENARIOS:
lox labs mc-v01 --regime GOLDILOCKS --real      # +8% drift, low vol (strong growth)
lox labs mc-v01 --regime VOL_CRUSH --real       # +10% drift, VIX→10 (worst case for hedges)

# NEUTRAL:
lox labs mc-v01 --regime ALL --real             # +5% drift, balanced baseline
```

### Scenario Analysis
```bash
# Custom macro scenarios
lox labs scenarios-custom --10y 4.7 --cpi 3.5 --vix 25 --diagnose

# Historical event scenarios
lox labs scenarios-historical --events "covid_crash_2020,gfc_2008"

# Forward-looking regime scenarios
lox labs scenarios-forward --show-catalysts
```

### Regime Deep Dives
```bash
# Fiscal regime (auctions, deficits, Treasury dynamics)
lox labs fiscal snapshot

# Monetary regime (Fed balance sheet, RRP, TGA)
lox labs monetary snapshot

# USD regime (DXY, trade-weighted)
lox labs usd snapshot

# Volatility regime (VIX term structure, MOVE)
lox labs volatility snapshot
```

---

## Support & Contributing

This is research software for educational and experimental purposes.

**Not investment advice. Not a regulated fund. Use at your own risk.**

For questions or contributions, see `docs/PROJECT_CONSTITUTION.md` for design principles.

---

## License

Proprietary - Lox Fund Research © 2026

---

## Appendix: Command Reference

### Core Commands
| Command | Purpose |
|---------|---------|
| `lox account summary` | Portfolio snapshot with macro context |
| `lox autopilot run-once` | ML trade generation + execution |
| `lox labs mc-v01 --real` | Position-level Monte Carlo with real prices |
| `lox labs fedfunds-outlook` | Macro/policy/liquidity dashboard |
| `lox weekly report` | Weekly performance summary |
| `lox options moonshot` | High-variance options scanner |

### Regime Commands
| Command | Purpose |
|---------|---------|
| `lox labs macro snapshot` | Macro regime (inflation/growth) |
| `lox labs funding snapshot` | Liquidity/funding regime |
| `lox labs commodities snapshot` | Gold/oil regime |
| `lox labs housing snapshot` | Housing/MBS regime |
| `lox labs fiscal snapshot` | Treasury/deficit regime |

### Analysis Commands
| Command | Purpose |
|---------|---------|
| `lox labs scenarios-forward` | Regime-aware forward scenarios |
| `lox labs scenarios-historical` | Historical event scenarios |
| `lox labs scenarios-custom` | User-defined scenarios |
| `lox options recommend` | Single-ticker options |
| `lox account positions` | Position-level detail |

---

**Lox Fund** | Systematic Options | Tail-Risk Hedging | Since Jan 2026
