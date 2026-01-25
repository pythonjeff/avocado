## Lox Fund CLI — Command guide (easy → advanced)

### 0) Quick mental model
- **Account briefing** → **Autopilot trades** → **NAV tracking**

### 1) Easiest daily commands (no flags)
- **`lox account`**: show mode/cash/equity/buying power.
- **`lox account summary`**: LLM briefing of positions + risk watch (trackers + US/USD events + curated links).
- **`lox autopilot run-once`**: generates a budgeted trade plan (default engine = regime analogs + factor momentum).
- **`lox nav snapshot`**: write a NAV snapshot from Alpaca and compute returns.
- **`lox nav investor report`**: investor ownership/basis/value/P&L via unitized NAV.
- **`lox weekly report`**: weekly summary (NAV snapshot, trades, thesis, macro performance).

### 2) Execution (paper-first)
- **`lox autopilot run-once --execute`**: prompts and submits **paper** orders.
- **`lox autopilot run-once --execute --live`**: allows **live** orders (only if `ALPACA_PAPER=false`), with extra confirmations.

### 3) Thesis + explainability (recommended)
- **`lox autopilot run-once --thesis inflation_fiscal --explain`**: biases selection toward inflation + fiscal-wall exposures and prints **WHY THESE TRADES** (drivers + US/USD events + Treasury auctions).
- **`lox autopilot run-once --no-explain`**: quiet mode (trade table only).

### 4) Options scanners
- **`lox options moonshot`**: in-budget longshot options ideas, with review/execute prompts.
- **`lox options moonshot --ticker SLV`**: single-name moonshot.

### 5) Fund accounting (investors + cashflows)
- **`lox nav investor import "Investor list.xlsx"`**: import investor code/amount/join date into the investor ledger.
- **`lox nav investor contribute JL 50 --note "Feb add"`**: logs a contribution to **both** ledgers (fund cashflows + investor flows).
- **`lox nav show`**: show the NAV sheet history.

**Ledger note:** `nav_flows.csv` (fund cashflows) and `nav_investor_flows.csv` (investor ledger) are separate by design.  
Use `lox nav investor contribute` for real investor cash moves so both ledgers stay in sync.

### 6) Model diagnostics (research)
- **`lox model macro-model-eval --basket starter --book longonly`**: walk-forward eval (Spearman, hit rate, top–bottom spread, portfolio returns).
- **`lox model macro-model-eval-ab --basket starter --book longonly`**: A/B sweep across regime families (`whitelist-extra`).
- **`lox model macro-model-dataset --basket starter --limit 20`**: inspect/export the ML dataset.

### 7) Idea generation from a link (LLM)
- **`lox ideas event --url <URL> --thesis "..."`**: turn an article into structured hedge/trade ideas (optional execution).

### 8) Interactive Research Chat (LLM)
- **`lox chat`**: start interactive chat with portfolio context loaded.
- **`lox chat -c fiscal`**: chat with US fiscal regime data (deficits, issuance, TGA).
- **`lox chat -c funding`**: chat with funding/liquidity context (SOFR, repo, reserves).
- **`lox chat -c macro`**: chat with macro regime context (inflation, growth).
- **`lox chat -c regimes`**: chat with all regime classifications loaded.
- **Ticker deep-dive**: ask about specific tickers (e.g., "tell me about FXI") for automatic snapshot, news, and analysis.

### 9) Unified Regime Analysis (NEW)
- **`lox labs unified`**: view all 10 regime domains with scores and Monte Carlo adjustments.
- **`lox labs unified --json`**: export flat ML feature vector for model training.
- **`lox labs transitions`**: regime transition probabilities adjusted for leading indicators.
- **`lox labs transitions --no-adjust`**: raw historical transition frequencies.
- **`lox labs transitions --horizon 126`**: 6-month forecast horizon.
- **`lox labs transitions --current risk_on`**: forecast from specific starting state.

**Leading Indicator Signals** (auto-detected):
- Yield curve inversion (2s10s < 0)
- VIX elevated (> 25) or complacent (< 13)
- VIX term structure inversion
- Credit spreads widening (HY OAS z > 1)
- Funding stress (SOFR spike)
- Rates shock (10Y z > 1.5)

### 10) Power-user / Labs
- **`lox labs <module> ...`**: regime builders, datasets, diagnostics, legacy tools.
  - Examples:
    - `lox labs fiscal snapshot`
    - `lox labs rates snapshot`
    - `lox labs funding snapshot`
    - `lox labs vol --llm`
    - `lox labs ticker outlook -t AAPL`
    - `lox labs ticker news -t NVDA`
    - `lox labs mc-v01 --regime RISK_OFF --real`
    - `lox labs hedge` (defensive trade ideas)
    - `lox labs grow` (offensive trade ideas)

### 11) Portfolio Analysis
- **`lox status`**: quick portfolio health (NAV, P&L, cash).
- **`lox status -v`**: with position details.
- **`lox analyze --depth deep`**: full LLM portfolio analysis.
- **`lox suggest --style defensive`**: trade ideas aligned to risk posture.
- **`lox closed-trades`**: realized P&L from closed positions.

### Notes
- Run **`lox <command> --help`** for flags.
- Paper vs live is controlled by **`ALPACA_PAPER`** and **`--live`**.
- All `--llm` flags require `OPENAI_API_KEY` in `.env`.
