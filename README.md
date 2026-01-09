## Lox Fund — ML + LLM macro trader (research system, execution-aware)

Lox is a **research-to-execution** macro trading system designed around a simple operating model:

- **Quant layer (ML)**: cross-sectional ranking of liquid, optionable instruments using a regime-aware feature panel.
- **Discretion layer (LLM risk overlay)**: a “macro trader” review that consumes **trackers + calendar events + headlines** and can explicitly recommend **HOLD / NEEDS_REVIEW** before deploying risk.
- **Execution layer (paper-first)**: budgeted, defined-risk options selection + robust order submission guards.

This repo is the codebase behind a small live trading vehicle I call the **Lox Fund**, seeded with **$550** in initial capital. The emphasis is on **repeatability, risk-aware workflows, and operator-grade CLI ergonomics**.

### Guardrails
- **Not investment advice.** This is research software.
- **Not a regulated or managed fund.** “Lox Fund” is a personal label for an experimental capital pool.
- **Grounded LLM prompts.** LLM outputs are instructed to use only provided JSON (trackers/events/headlines) and avoid hallucinated facts.

---

## Mandate + macro thesis (research hypothesis)

Lox Fund is built to express a specific macro research hypothesis:

- **Persistent inflation risk**: inflation may remain structurally sticky versus the post‑2010 baseline.
- **Rising macro volatility**: volatility may increase as the **Treasury issuance / term premium** and broader **fiscal trajectory** become more binding constraints on risk assets.
- **Deteriorating fiscal/treasury dynamics**: deficits, issuance mix, and auction absorption can propagate into **rates volatility**, **liquidity**, and cross-asset risk premia.

How the system attempts to express this (defined-risk where possible):

- **Real asset / inflation hedges**: e.g., gold/commodities exposures when regimes support it.
- **Rates / duration sensitivity**: explicit attention to the yield curve and rate momentum regimes.
- **Volatility convexity**: selective long‑vol / convex options expression when the overlay indicates an elevated asymmetry.

---

## Quickstart

### Install

```bash
pip install -e .
```

### Configure `.env`

- **Alpaca**: `ALPACA_API_KEY`, `ALPACA_API_SECRET` (optional: `ALPACA_DATA_KEY`, `ALPACA_DATA_SECRET`, `ALPACA_OPTIONS_FEED=opra`)
- **FRED**: `FRED_API_KEY`
- **FMP (news + econ calendar)**: `FMP_API_KEY`
- **OpenAI**: `OPENAI_API_KEY` (optional: `OPENAI_MODEL`)

---

## Operator workflow (the “daily run”)

### 1) Account briefing (LLM, with events + links)

```bash
lox account summary
```

Outputs: **trades/exposures**, **market risk watch** (trackers + upcoming releases), and an **articles/reading list** (URLs from FMP).

### 2) Autopilot: generate budgeted trades + LLM oversight

Paper-first, with LLM overlay and per-position outlook:

```bash
lox autopilot run-once --engine ml --basket extended --llm --llm-news
```

If you want the LLM to act as a gate (must say `DECISION: GO` before execution is allowed):

```bash
lox autopilot run-once --engine ml --basket extended --llm --llm-news --llm-gate --execute
```

---

## Moonshot scanner (high-variance, in-budget options)

This is a research scanner designed to find **in-budget longshots** while focusing on **high realized-vol underlyings**:

```bash
lox options moonshot --basket extended
```

Single name:

```bash
lox options moonshot --ticker SLV
```

It steps through candidates and prompts you per ticker; it will also generate a short, **grounded thesis** if OpenAI is configured.

---

## How it works (high level)

### Quant engine (ML)
- Builds a **macro panel dataset**: regime features + instrument features
- Fits a cross-sectional model and produces ranked candidates (expected return + directional probability)

### Risk overlay (LLM)
- Consumes:
  - **Regime feature row** and curated **tracker values**
  - **Upcoming economic calendar events** (FMP; cached)
  - **Recent headlines + URLs + sentiment** (FMP)
- Produces:
  - **Per-position outlook** (hold/reduce/hedge/exit/needs_review)
  - A decision memo and (optionally) `DECISION: GO|HOLD|NEEDS_REVIEW`

### Execution
- Budgeted recommendations (cash-aware)
- Options legs chosen under constraints (DTE, premium cap, spread, delta target)
- Paper-first and live guarded with explicit confirmation

---

## Testing

```bash
pytest -q
```

---

## Project constitution
- `docs/PROJECT_CONSTITUTION.md`
- `docs/OBJECTIVES.md`
