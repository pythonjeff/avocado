# Avocado 🥑 — options “spreads-first” research CLI (Alpaca)

**Avocado** is a research-grade, execution-aware CLI that helps you go from **market view → spread idea → execution-ready legs** on Alpaca.

The core idea: **spreads are how you express an opinion with defined risk** (credit/debit, capped downside, volatility-aware). Avocado’s job is to:

- **Decide direction / bias** (sentiment + macro regime context)
- **Pick liquid, reasonably-priced option legs** that fit constraints (DTE, delta, spread width, risk budget)
- **Log and explain** why it chose what it chose, so you can trust (or override) it

> Current state: the `select` command picks a **single best leg** (call/put) and prints sizing + diagnostics. It’s intentionally built as the *leg-selection engine* you need to construct verticals, calendars, iron condors, etc. (spreads wiring is the next natural step).

## Quickstart

1. Create a virtualenv and install:
```bash
pip install -e .
```

2. Copy env template and set keys:
```bash
cp .env.example .env
```

3. Run a dry-run selection:
```bash
avocado select --ticker NVDA --sentiment positive
# (alias also supported)
ai-options-trader select --ticker NVDA --sentiment positive
```

> By default this is **dry-run only** (no orders are submitted).
>
> Note: Alpaca's `get_option_chain()` snapshots may not include open interest / volume. In that case, those thresholds are treated as best-effort (only enforced when the fields are present). Use `--debug` to see filter diagnostics.

## What Avocado can do today

### Options leg selection (spread building block)

- **Input**: ticker + sentiment (`positive` → calls, `negative` → puts)
- **Filters**: DTE window, delta target, bid/ask spread sanity, (best-effort) liquidity
- **Output**: an option contract symbol + pricing + position sizing budget

```bash
avocado select --ticker AAPL --sentiment positive --target-dte 30 --debug
```

### Macro regime + datasets (context for spreads)

Avocado also computes a lightweight macro state and a simple “regime” label you can use to choose spread structures (e.g., defined-risk premium selling vs directional debit spreads).

```bash
avocado macro snapshot
```

### Regime dashboard (macro + tariff baskets) + LLM summary

Print **macro regime + tariff/cost-push regimes** across all baskets:

```bash
avocado regimes
```

See available tariff baskets:

```bash
avocado tariff baskets
```

Have an LLM read the regimes and produce a short **summary + risks + follow-up checklist**:

```bash
avocado regimes --llm
```

Notes:
- **Data requirements**: tariff regimes require Alpaca **data** keys (or trading keys) + `FRED_API_KEY`.
- **LLM requirements**: `OPENAI_API_KEY` (and optionally `OPENAI_MODEL` in `.env`).
- **Optional overrides**:

```bash
avocado regimes --llm --llm-model gpt-4o-mini --llm-temperature 0.2
avocado regimes --baskets import_retail_apparel,big_box_retail --benchmark XLY
```

### Equity sensitivity (optional: “what drives this stock?”)

Useful for deciding whether to structure spreads around rates / breakevens sensitivity.

```bash
avocado macro equity-sensitivity --tickers NVDA,AMD,MSFT,GOOGL --benchmark QQQ
avocado macro beta-adjusted-sensitivity --tickers NVDA,AMD,MSFT,GOOGL --benchmark QQQ
```

## Why “spreads-first”

If you’re trading options in the real world, “pick a contract” isn’t the end goal. You usually want:

- **Defined risk**: cap worst-case loss
- **Cleaner thesis expression**: directional view + volatility view
- **Better fills**: choose liquid legs and sane bid/ask conditions

Avocado is designed to make that workflow systematic: **select legs first, then compose them into spreads**.

## Roadmap
See `docs/OBJECTIVES.md`.
