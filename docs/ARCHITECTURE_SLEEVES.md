# Lox “Sleeves” Architecture (MVP)

Goal: support a multi-sleeve (pod-style) architecture while keeping **one shared pipeline** for:
- data + caching
- feature/regime matrix
- scoring (analog/playbook/ML)
- evaluation
- LLM overlay
- execution

This is an MVP: it’s intentionally minimal, but the interfaces are designed to support later sophistication.

## Sleeve concepts

Each sleeve is a configuration object that defines:
- **Universe**: how to get a list of tickers for this sleeve
- **Regime weighting**: how to emphasize subsets of the shared regime feature matrix for similarity/scoring
- **Allowed trade families**: what kinds of expressions are allowed (shares vs options; later: probes/spreads/moonshots)
- **Sleeve risk budget**: fraction of total deployable budget reserved for the sleeve

The sleeve output is standardized as `CandidateTrade` records so sleeves can be compared and aggregated.

## Shared pipeline stages

1) **Resolve sleeves**
   - Parse `--sleeves` and load `SleeveConfig` objects from a registry.
   - If `--sleeves` is omitted, default to `["macro"]` for backward compatibility.

2) **Build shared inputs once**
   - Build the shared regime matrix: `build_regime_feature_matrix(...)`
   - Build the shared price panel for the union of sleeve universes: `fetch_equity_daily_closes(...)`
   - Select `asof` as the min of available feature and price endpoints.

3) **Per-sleeve scoring**
   - Apply sleeve’s feature weighting rules to the shared feature matrix (no new data sources; just weighting).
   - Score tickers via:
     - **analog/playbook**: `rank_macro_playbook(features=..., prices=..., tickers=...)`
     - **ml**: train/predict once on the union tickers, then slice per sleeve (MVP)
   - Convert ideas → standardized `CandidateTrade` list, attaching option legs when enabled and feasible.

4) **Portfolio aggregation**
   - Merge all `CandidateTrade` across sleeves.
   - Net redundant exposures and apply caps:
     - no more than one levered inverse equity ETF
     - disallow PSQ and SQQQ together
     - if multiple trades share the same `risk_factors` signature, keep only the highest score
     - enforce factor caps: max 1 position per factor unless `probe=True`
   - Enforce sleeve budgets + total budget with simple cost accounting (`est_cost_usd`).

5) **LLM overlay (optional)**
   - Keep one overlay call. MVP chooses **post-aggregation** for maintainability.
   - Feed the LLM:
     - per-sleeve candidate summaries (top N each)
     - post-aggregation budgeted list (the only set eligible for “actions”)
     - optional: risk_watch + news payloads (when `--llm-news`)

6) **Execution (optional, confirmation-gated)**
   - Execution is unchanged: paper by default; live requires `--live` and extra confirmations.
   - Only trades in the post-aggregation budgeted list are eligible for execution prompts.

## Aggregator logic (MVP)

The MVP aggregator is a greedy selector:
- Sort candidates by `score` desc.
- Skip candidates that violate:
  - levered inverse equity exclusivity
  - PSQ/SQQQ exclusivity
  - factor caps (unless probe)
  - sleeve budget or total budget
  - duplicate `risk_factors` signature (keep best)

This is intentionally simple. Later improvements:
- convex optimization or knapsack sizing
- netting by delta exposures (options) rather than ticker heuristic buckets
- portfolio-level stress tests

## How to add a new sleeve

1) Add a `SleeveConfig` entry in `src/ai_options_trader/strategies/sleeves.py`:
   - `name` and optional `aliases`
   - `risk_budget_pct`
   - `universe_fn(basket_name) -> list[str]`
   - `feature_weights_by_prefix` (optional)
   - `allowed_trade_families` (optional)

2) Add/update `risk_factors` inference rules in `src/ai_options_trader/strategies/base.py` if needed.

3) (Optional) Add targeted unit tests in `tests/test_strategies_aggregator.py`.

## CLI UX

- Autopilot multi-sleeve:
  - `lox autopilot run-once --sleeves vol macro ai-bubble --engine ml --basket extended --llm --llm-news`
- Moonshot sleeve universe:
  - `lox options moonshot --sleeves vol`
  - `lox options moonshot --sleeves ai-bubble`

