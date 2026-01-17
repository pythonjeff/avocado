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

### 6) Model diagnostics (research)
- **`lox model macro-model-eval --basket starter --book longonly`**: walk-forward eval (Spearman, hit rate, top–bottom spread, portfolio returns).
- **`lox model macro-model-eval-ab --basket starter --book longonly`**: A/B sweep across regime families (`whitelist-extra`).
- **`lox model macro-model-dataset --basket starter --limit 20`**: inspect/export the ML dataset.

### 7) Idea generation from a link (LLM)
- **`lox ideas event --url <URL> --thesis "..."`**: turn an article into structured hedge/trade ideas (optional execution).

### 8) Power-user / Labs
- **`lox labs <module> ...`**: regime builders, datasets, diagnostics, legacy tools.
  - Examples:
    - `lox labs fiscal snapshot`
    - `lox labs rates snapshot`
    - `lox labs regimes show`

### Notes
- Run **`lox <command> --help`** for flags.
- Paper vs live is controlled by **`ALPACA_PAPER`** and **`--live`**.
