# AI Options Trader (Alpaca) — Starter Repo

A research-grade, execution-aware **AI-assisted options selector** built on Alpaca.
This repo is designed to be extended into a resume-level project: deterministic selection logic, risk policy, logging, and tests.

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
ai-options-trader --ticker NVDA --sentiment positive
# (also supported)
ai-options-trader select --ticker NVDA --sentiment positive
```

> By default this is **dry-run only** (no orders are submitted).
>
> Note: Alpaca's `get_option_chain()` snapshots may not include open interest / volume. In that case, those thresholds are treated as best-effort (only enforced when the fields are present). Use `--debug` to see filter diagnostics.

## Roadmap
See `docs/OBJECTIVES.md`.
