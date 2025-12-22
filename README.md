## Lox — regime-aware options research & execution (Alpaca)

**Lox** is a research + execution CLI designed to turn a macro thesis into **tradeable options expressions**, with an emphasis on:
- **Regime-aware context** (macro + tariff/cost-push)
- **Deterministic contract selection** (DTE / delta / spread / liquidity)
- **Explainability** (why an idea exists, what inputs drove it, what could invalidate, and what to watch next)
- **Paper execution + tracking** (log recommendations, link executed orders, track P&L)

**Important**: This is a research tool. Nothing here is financial advice. Use paper trading first.

## Quickstart

```bash
cd /path/to/repo
pip install -e .
cp .env.example .env
```

Minimum environment (by capability):
- **Alpaca**: `ALPACA_API_KEY`, `ALPACA_API_SECRET` (and optionally `ALPACA_DATA_KEY`, `ALPACA_DATA_SECRET`)
- **FRED**: `FRED_API_KEY` (for quantitative macro state/regimes)
- **FMP**: `FMP_API_KEY` (for equity news + economic calendar)
- **LLM**: `OPENAI_API_KEY` (and optional `OPENAI_MODEL`)

Entry points:
- Use `lox ...` (primary).
- `avocado ...` is a compatibility alias and may be removed later.

## Core workflow (recommended)

### 1) Inspect regimes (macro + tariff) and optional LLM readout

```bash
lox regimes
lox regimes --llm
```

List available tariff baskets:

```bash
lox tariff baskets
```

### 2) Generate thesis-driven ideas (AI bubble / inflation / tariffs)

```bash
lox ideas ai-bubble --top 15
```

Pull option chains and select a liquid **starter leg** per idea:

```bash
lox ideas ai-bubble --with-legs --top 10 --target-dte 45
```

### 3) Review ideas one-by-one and optionally execute (paper)

```bash
lox ideas ai-bubble --interactive --with-legs --execute --top 10
```

Execution safety:
- Orders are only sent when you confirm interactively
- When `ALPACA_PAPER` is false, execution is refused

## Macro & financial features (a “research note” view)

This section is intentionally detailed: it’s a conceptual map of **what Lox measures**, **why those measurements exist**, and **how they turn into tradeable option legs**.

### Macro state: what is measured (quantitative)
`src/ai_options_trader/macro/signals.py` builds a daily macro dataset from a small set of FRED series and derives interpretable features:

- **Inflation reality (CPI)**:
  - CPI YoY, Core CPI YoY
  - CPI 3-month annualized, CPI 6-month annualized (computed on monthly CPI observations then forward-filled)
- **Inflation expectations (breakevens)**:
  - 5y breakeven, 10y breakeven
- **Rates & curve**:
  - Effective Fed Funds
  - 2y and 10y Treasury yields
  - 2s10s curve slope
- **Derived real-yield proxy**:
  - \( \text{REAL\_YIELD\_PROXY\_10Y} = \text{DGS10} - \text{T10YIE} \)
- **A key “inflation surprise / repricing” feature**:
  - \( \text{INFL\_MOM\_MINUS\_BE5Y} = \text{CPI\_6M\_ANN} - \text{T5YIE} \)
- **Composite disconnect score (z-scored)**:
  - A weighted combination of z-scores of inflation momentum vs breakevens and the real-yield proxy

Outputs are packaged into `MacroState` / `MacroInputs` (`src/ai_options_trader/macro/models.py`) so the CLI can print them, and the LLM can consume them as structured data.

### Macro regime: what the label means (classification)
`src/ai_options_trader/macro/regime.py` classifies regimes using two axes:

- **Inflation surprise / momentum** (up vs down)
- **Real yield proxy** (tightening vs easing financial conditions)

This yields four named regimes (e.g., “stagflation”, “reflation”, etc.) that serve as a **coarse prior** for equity/risk behavior. The point is not to be “right” all the time; it is to ensure your downstream decisions are explicitly conditioned on a macro context.

### Tariff / cost-push regimes: where trade policy enters
The tariff subsystem (`src/ai_options_trader/tariff/*`) is designed around a cost-push thesis: import-exposed baskets can behave differently when cost pressures rise and pass-through risk increases. It provides:

- Basket definitions / universes
- Proxy series (FRED) and transforms
- Regime scoring logic per basket

### News + NLP layer: what it’s for (qualitative)
Lox includes two complementary “text → structure” tools:

- **Ticker news brief** (position/ticker monitoring):
  - Fetches **FMP `stock_news`** (recent, ticker-scoped)
  - Summarizes and classifies tone (optional explain mode with evidence indices)
- **Macro news brief**:
  - Fetches **FMP `general_news`** (broad market/macro)
  - Topic-tags items (monetary / fiscal / trade/tariffs / inflation / growth/labor)
  - Produces a 3/6/12-month macro outlook narrative

### Economic calendar: “what to watch next”
Lox can compute “What to watch next” items using:

- **FMP `economic_calendar`** for next release dates (preferred)
- **Official schedule scraping** (fallback)

The watchlist is meant to be actionable: it tells you what macro prints are most likely to move the regime inputs (inflation, rates, expectations) and, by extension, the option structures you prefer.

### Combined macro outlook: quant + qual in one report
`lox macro outlook` combines:

- `MacroState` (quant)
- `MacroRegime` (classification)
- recent macro news items (qual)
- watchlist (calendar)

Then asks the LLM to produce a single cohesive outlook across 3/6/12 months that explicitly ties “what to watch” to the regime.

### Single ticker outlook: quant + macro + news (+ optional concrete option legs)
`lox ticker-outlook` combines:

- Ticker quant snapshot: trend/momentum/volatility/relative strength vs benchmark
- macro regime + macro inputs
- ticker news items (FMP stock_news)
- optional “options plan” + Alpaca option chain selection + interactive submit

## Architecture

High-level pipeline:

```text
                ┌───────────────────────────────────────────────────────────┐
                │                         CLI (Typer)                       │
                │                   src/ai_options_trader/cli.py            │
                └───────────────┬───────────────────────────────┬──────────┘
                                │                               │
                                │                               │
                 ┌──────────────▼───────────────┐  ┌───────────▼───────────┐
                 │     Regimes / Datasets       │  │     Thesis → Ideas     │
                 │  macro/*  tariff/*  data/*   │  │  ideas/ai_bubble.py    │
                 └──────────────┬───────────────┘  └───────────┬───────────┘
                                │                               │
                                │                               │
                  ┌─────────────▼─────────────┐    ┌───────────▼───────────┐
                  │     Data Providers        │    │   Option Leg Selector  │
                  │  FRED (fred.py)           │    │ strategy/selector.py   │
                  │  Alpaca (market.py,       │    │ (filters + scoring +   │
                  │         alpaca.py)         │    │  sizing hooks)         │
                  └─────────────┬─────────────┘    └───────────┬───────────┘
                                │                               │
                                │                               │
                      ┌─────────▼─────────┐           ┌─────────▼─────────┐
                      │  Execution (opt)  │           │ Tracking (SQLite) │
                      │ execution/alpaca  │           │ tracking/store.py │
                      └─────────┬─────────┘           └─────────┬─────────┘
                                │                               │
                                └───────────────┬───────────────┘
                                                │
                                      ┌─────────▼─────────┐
                                      │ Reports / Sync     │
                                      │ `avocado track …`  │
                                      └────────────────────┘
```

Where the “brains” live:
- **Idea engine (direction + ranking + explainability)**: `src/ai_options_trader/ideas/ai_bubble.py`
- **Regimes**:
  - Macro dataset/state: `src/ai_options_trader/macro/signals.py`
  - Macro regime label: `src/ai_options_trader/macro/regime.py`
  - Tariff regime: `src/ai_options_trader/tariff/signals.py`
- **Option selector (filters + scoring)**: `src/ai_options_trader/strategy/selector.py`
- **Order submission (paper/live guardrails)**: `src/ai_options_trader/execution/alpaca.py`
- **Tracker DB**: `src/ai_options_trader/tracking/store.py`

## Tracking & reporting

Avocado logs:
- Every **recommendation** (per run id)
- Every **execution** (links Alpaca order id back to the recommendation)

Storage:
- Default SQLite DB: `data/tracker.sqlite3`
- Override: `AOT_TRACKER_DB=/path/to/tracker.sqlite3`

Commands:

```bash
avocado track recent --limit 20
avocado track sync --limit 50
avocado track report
```

## What to edit (the “brains”)

- **Idea engine (thesis → ranked tickers + direction + why)**: `src/ai_options_trader/ideas/ai_bubble.py`
- **Option selector (filters + scoring + sizing)**: `src/ai_options_trader/strategy/selector.py`
- **Risk sizing constraints**: `src/ai_options_trader/strategy/risk.py` and `src/ai_options_trader/config.py`
- **Data inputs**:
  - FRED: `src/ai_options_trader/data/fred.py`
  - Alpaca option snapshots / greeks: `src/ai_options_trader/data/alpaca.py`

## Command reference (high signal)

### Macro

```bash
lox macro snapshot
lox macro news --provider fmp --days 7
lox macro outlook --provider fmp --days 7
lox macro equity-sensitivity --tickers NVDA,AMD,MSFT,GOOGL --benchmark QQQ
lox macro beta-adjusted-sensitivity --tickers NVDA,AMD,MSFT,GOOGL --benchmark QQQ
```

### News & sentiment (positions / tickers)

Summarize recent ticker-specific news (uses Alpaca open positions by default, or pass tickers explicitly):

```bash
lox track news-brief --provider fmp --days 7 --tickers AAPL,MSFT
lox track news-brief --provider fmp --days 7
```

Explain mode (includes reasons + evidence indices and prints indexed inputs):

```bash
lox track news-brief --provider fmp --days 7 --tickers AAPL --explain
```

### Single ticker outlook (3/6/12 months)

```bash
lox ticker-outlook --ticker AAPL --benchmark SPY --news-days 14
lox ticker-outlook --ticker AAPL --interactive
lox ticker-outlook --ticker AAPL --interactive --execute
```

### Single-name leg selection

```bash
lox select --ticker AAPL --sentiment positive --target-dte 30 --debug
```

### Tariff

```bash
lox tariff snapshot --basket import_retail_apparel --benchmark XLY
lox tariff baskets
```

## Notes & limitations

- **Option snapshot completeness varies**: OI/volume/greeks may be missing; filters are best-effort when fields are absent.
- **This repo is “legs-first”**: verticals/condors/etc. are the next layer (compose legs into spreads).
- **Cache**: FRED data is cached under `data/cache/` (recommended: do not commit cache artifacts).
- **News sources**:
  - Ticker news uses **FMP** `stock_news` (provider `fmp`) and filters to your lookback window.
  - Macro news uses **FMP** `general_news` (provider `fmp`) and topic-tags items heuristically.
- **Economic “What to watch”**: uses **FMP** `economic_calendar` when available for next release dates; falls back to official schedule scraping when needed.

## Roadmap

See `docs/OBJECTIVES.md`.
