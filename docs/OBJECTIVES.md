# Objectives checklist (resume-level)

## Phase 1 — Repo hygiene and deterministic core (now)
- [ ] Package structure under `src/`
- [ ] Central config via env (`config.py`)
- [ ] OCC parsing utility + tests
- [ ] Deterministic option selection:
      liquidity filters + scoring (DTE, delta, spread, OI/vol)
- [ ] Structured logging of decisions

## Phase 2 — Risk policy and execution hardening
- [ ] Risk policy module: max risk %, max positions, stops, time stops
- [ ] Use quote mid for sizing; avoid last-trade when possible
- [ ] Order preview object (no side effects) + explicit execute step

## Phase 3 — Evaluation (choose one)
A) Paper-trading report (fast)
- [ ] Daily run across a fixed universe
- [ ] Persist decisions + PnL snapshots
- [ ] Basic performance report

B) Backtest harness (stronger)
- [ ] Historical underlying + option proxy data pipeline
- [ ] Walk-forward evaluation and metrics

## Phase 4 — Documentation & CI
- [ ] README architecture diagram
- [ ] `make test`, ruff/black, GitHub Actions CI
