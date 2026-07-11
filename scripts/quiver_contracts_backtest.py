"""
Stage 1 research script — Quiver Edge Expansion plan.

Purpose: find out whether government contract award disclosures show a real,
sized forward-return effect BEFORE any signal-generation code gets written.
This is intentionally NOT wired into lox/quiver/signal.py or the CLI — it is
a standalone, throwaway-if-it-fails research pass.

Why gov contracts instead of insider clusters (the original Stage 1 target):
insider trading data is not accessible on the current Quiver API tier
(/live/insiders returns 403 "Upgrade your subscription plan") and no CSV
export has been dropped into data/cache/quiver/. Gov contracts data IS
live-accessible on the current tier (/live/govcontractsall), so this pass
starts there instead, without any paid upgrade.

Design principles (per the plan's review):
  - Log EVERY ticker-week candidate, not just "notable" ones — so we can see
    real base rates and avoid selection bias.
  - No scoring formula, no convergence multiplier — just raw effect size.
  - Compute a materiality scaler (award $ / market cap) so we can check
    whether the "revenue surprise" causal story actually requires size-
    relative-to-company, as the review flagged.
  - Explicit, printed caveats about data limitations rather than silently
    assuming away known gaps.

Known limitations of this pass (read before trusting the output):
  - The /live/govcontractsall feed only returns ~5 months of history
    (2026-02-16 to present as of this run) — sample size is inherently
    limited, especially for the 45-trading-day horizon.
  - The feed has no field distinguishing NEW awards from contract
    MODIFICATIONS or IDIQ/IDV ceiling values. A large "Amount" may be a
    ceiling that will never be fully obligated. This script cannot fix
    that; it can only flag that the effect size may be diluted by it.
  - Market cap used for the materiality scaler is CURRENT market cap
    (fetched once, cached 7 days), not point-in-time as of the award date.
    For most large/mid-caps this doesn't move the bucket much; for anything
    that had a big re-rating since Feb 2026 it will be wrong.
  - No transaction costs, spreads, or liquidity are modeled here — this is
    a pure price-effect check, not a tradable expected-value estimate.
  - No survivorship handling — tickers not resolvable via FMP (delisted,
    renamed, wrong exchange) are dropped and counted, not imputed.

Usage:
    python scripts/quiver_contracts_backtest.py
    python scripts/quiver_contracts_backtest.py --refresh-raw   # refetch from Quiver API
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

import numpy as np
import pandas as pd
import requests

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from lox.config import Settings
from lox.data.market import fetch_equity_daily_closes

RAW_CACHE = Path("data/cache/quiver_research/govcontracts_raw.json")
CANDIDATES_OUT = Path("data/cache/quiver_research/contracts_backtest_candidates.csv")
HORIZONS = (5, 10, 20, 45)


def fetch_raw_contracts(*, refresh: bool = False) -> list[dict]:
    if RAW_CACHE.exists() and not refresh:
        return json.loads(RAW_CACHE.read_text())

    from dotenv import load_dotenv
    import os

    load_dotenv()
    key = os.environ.get("QUIVER_API_KEY")
    if not key:
        raise RuntimeError("QUIVER_API_KEY not set")

    resp = requests.get(
        "https://api.quiverquant.com/beta/live/govcontractsall",
        headers={"accept": "application/json", "Authorization": f"Token {key}"},
        timeout=30,
    )
    resp.raise_for_status()
    data = resp.json()

    RAW_CACHE.parent.mkdir(parents=True, exist_ok=True)
    RAW_CACHE.write_text(json.dumps(data))
    return data


def build_ticker_week_candidates(raw: list[dict]) -> pd.DataFrame:
    df = pd.DataFrame(raw)
    df = df[df["Ticker"].notna() & (df["Ticker"].astype(str).str.strip() != "")]
    df["Ticker"] = df["Ticker"].astype(str).str.strip().str.upper()
    df["Date"] = pd.to_datetime(df["Date"], errors="coerce")
    df["Amount"] = pd.to_numeric(df["Amount"], errors="coerce").fillna(0.0)
    df = df.dropna(subset=["Date"])

    df["week"] = df["Date"].dt.to_period("W")

    grp = df.groupby(["Ticker", "week"]).agg(
        total_usd=("Amount", "sum"),
        n_line_items=("Amount", "count"),
        max_single_usd=("Amount", "max"),
        signal_date=("Date", "max"),  # last disclosure date in the window = when it's fully visible
        agencies=("Agency", lambda s: sorted(set(s.dropna()))[:3]),
    ).reset_index()
    grp = grp.rename(columns={"Ticker": "ticker"})
    return grp


def fetch_market_caps(tickers: list[str], settings: Settings) -> dict[str, float | None]:
    from lox.altdata.fmp import fetch_profile

    out: dict[str, float | None] = {}
    for t in tickers:
        try:
            profile = fetch_profile(settings=settings, ticker=t)
            out[t] = profile.market_cap if profile else None
        except Exception:
            out[t] = None
    return out


def _trading_day_return(px: pd.Series, t0_idx: int, offset: int) -> float | None:
    if t0_idx + offset >= len(px):
        return None
    p0, p1 = px.iloc[t0_idx], px.iloc[t0_idx + offset]
    if p0 is None or p1 is None or p0 == 0 or pd.isna(p0) or pd.isna(p1):
        return None
    return (p1 / p0) - 1.0


def run_backtest(*, refresh_raw: bool) -> tuple[pd.DataFrame, pd.DataFrame]:
    print("Fetching raw gov contracts feed...")
    raw = fetch_raw_contracts(refresh=refresh_raw)
    print(f"  {len(raw)} raw line items")

    candidates = build_ticker_week_candidates(raw)
    print(f"  {len(candidates)} ticker-week candidates across {candidates['ticker'].nunique()} tickers")

    tickers = sorted(candidates["ticker"].unique().tolist())
    earliest = candidates["signal_date"].min() - pd.Timedelta(days=5)

    settings = Settings()

    print(f"Fetching daily prices for {len(tickers)} tickers + SPY (cached where available)...")
    px_frames = []
    resolved_tickers = []
    for t in tickers + ["SPY"]:
        try:
            px = fetch_equity_daily_closes(settings=settings, symbols=[t], start=str(earliest.date()))
            if px is not None and not px.empty and t in px.columns:
                px_frames.append(px[[t]])
                if t != "SPY":
                    resolved_tickers.append(t)
        except Exception as e:
            print(f"  skip {t}: {e}")

    if not px_frames:
        raise RuntimeError("No price data fetched — aborting.")

    price_df = pd.concat(px_frames, axis=1).sort_index()
    price_df = price_df.loc[:, ~price_df.columns.duplicated()]

    if "SPY" not in price_df.columns:
        raise RuntimeError("Could not fetch SPY prices — cannot compute excess returns.")

    dropped = set(tickers) - set(resolved_tickers)
    if dropped:
        print(f"  dropped {len(dropped)} tickers with no resolvable price data: {sorted(dropped)[:20]}{'...' if len(dropped) > 20 else ''}")

    print(f"Fetching market caps for materiality scaler ({len(resolved_tickers)} tickers)...")
    mkt_caps = fetch_market_caps(resolved_tickers, settings)

    rows = []
    for _, c in candidates.iterrows():
        ticker = c["ticker"]
        if ticker not in price_df.columns:
            continue
        px = price_df[ticker].dropna()
        spy = price_df["SPY"].dropna()
        common_idx = px.index.intersection(spy.index)
        px = px.loc[common_idx]
        spy = spy.loc[common_idx]
        if px.empty:
            continue

        signal_date = c["signal_date"]
        pos = px.index.searchsorted(signal_date)
        if pos >= len(px):
            continue  # signal date after all available price data

        mkt_cap = mkt_caps.get(ticker)
        materiality = (c["total_usd"] / mkt_cap) if mkt_cap else None

        row = {
            "ticker": ticker,
            "week": str(c["week"]),
            "signal_date": signal_date.date(),
            "total_usd": c["total_usd"],
            "n_line_items": c["n_line_items"],
            "max_single_usd": c["max_single_usd"],
            "agencies": ";".join(c["agencies"]),
            "market_cap": mkt_cap,
            "materiality_pct": (materiality * 100.0) if materiality is not None else None,
        }
        for h in HORIZONS:
            raw_ret = _trading_day_return(px, pos, h)
            spy_ret = _trading_day_return(spy, pos, h)
            excess = (raw_ret - spy_ret) if (raw_ret is not None and spy_ret is not None) else None
            row[f"ret_{h}d"] = raw_ret
            row[f"excess_{h}d"] = excess
        rows.append(row)

    result = pd.DataFrame(rows)
    CANDIDATES_OUT.parent.mkdir(parents=True, exist_ok=True)
    result.to_csv(CANDIDATES_OUT, index=False)
    print(f"\nWrote {len(result)} candidates (all, resolved + unresolved) to {CANDIDATES_OUT}")
    return result, price_df


def _bucket_stats(df: pd.DataFrame, horizon: int, group_col: str | None = None) -> None:
    col = f"excess_{horizon}d"
    resolved = df[df[col].notna()]
    print(f"\n  --- {horizon}d horizon: {len(resolved)}/{len(df)} candidates resolved ---")
    if resolved.empty:
        print("    no resolved candidates at this horizon")
        return

    def _report(sub: pd.DataFrame, label: str) -> None:
        n = len(sub)
        if n == 0:
            return
        hit_rate = (sub[col] > 0).mean()
        avg_excess = sub[col].mean()
        med_excess = sub[col].median()
        print(f"    {label:<28} n={n:<5} hit_rate={hit_rate:.1%}  avg_excess={avg_excess:+.2%}  median_excess={med_excess:+.2%}")

    _report(resolved, "ALL (unfiltered)")

    if group_col and group_col in resolved.columns:
        valid = resolved[resolved[group_col].notna()]
        if not valid.empty:
            try:
                quartiles = pd.qcut(valid[group_col], q=4, duplicates="drop")
                for q, sub in valid.groupby(quartiles):
                    _report(sub, f"{group_col} bucket {q}")
            except ValueError:
                print(f"    (not enough spread in {group_col} to bucket)")


def print_report(df: pd.DataFrame) -> None:
    print("\n" + "=" * 72)
    print("STAGE 1 RESEARCH RESULT — Gov Contracts vs Forward Returns")
    print("=" * 72)
    print(f"Total candidates logged (all, unfiltered): {len(df)}")
    print(f"Distinct tickers: {df['ticker'].nunique()}")
    print(f"Candidates with a usable market cap: {df['market_cap'].notna().sum()}")
    print(f"Signal date range: {df['signal_date'].min()} -> {df['signal_date'].max()}")

    for h in HORIZONS:
        _bucket_stats(df, h, group_col="materiality_pct")

    print("\n" + "-" * 72)
    print("REMINDERS (do not skip):")
    print("  - Sample is ~5 months of data (Quiver API history limit on this tier).")
    print("  - No new-award vs modification/IDV-ceiling distinction in this feed.")
    print("  - Market cap is CURRENT, not point-in-time as of the award date.")
    print("  - No transaction costs / liquidity / spread modeled.")
    print("  - This is exploratory research only — not a signal, not shipped.")
    print("-" * 72)


def _ticker_baseline_excess(price_df: pd.DataFrame, ticker: str, horizon: int) -> tuple[float | None, float | None, int]:
    """
    Baseline = forward excess return starting from EVERY trading day this ticker
    has data for in the same window, not just award-week dates. This controls for
    two confounds at once: (1) the overall regime during this sample period, and
    (2) the fact that this specific universe of tickers (gov contractors, often
    small/mid-cap) may behave differently from SPY regardless of award timing.

    Windows are overlapping/autocorrelated by construction — this is a descriptive
    comparison of average level, not a significance test.
    """
    if ticker not in price_df.columns:
        return None, None, 0
    px = price_df[ticker].dropna()
    spy = price_df["SPY"].dropna()
    idx = px.index.intersection(spy.index)
    px, spy = px.loc[idx], spy.loc[idx]
    if len(px) <= horizon:
        return None, None, 0

    excess_vals = []
    for i in range(len(px) - horizon):
        r = _trading_day_return(px, i, horizon)
        s = _trading_day_return(spy, i, horizon)
        if r is not None and s is not None:
            excess_vals.append(r - s)
    if not excess_vals:
        return None, None, 0
    arr = np.array(excess_vals)
    return float(arr.mean()), float((arr > 0).mean()), len(arr)


def print_control_comparison(df: pd.DataFrame, price_df: pd.DataFrame) -> None:
    print("\n" + "=" * 72)
    print("CONTROL-GROUP CHECK — award weeks vs. this same ticker's own baseline")
    print("=" * 72)
    print("For each ticker with candidates: baseline = forward excess return from")
    print("EVERY trading day in the sample window, not just award weeks.")
    print("Delta = (candidate avg excess) - (that ticker's own baseline avg excess).")
    print("Delta > 0 means award weeks beat a random week for the SAME stock in the")
    print("SAME period — i.e. the effect isn't just regime or ticker-selection.\n")

    tickers = sorted(df["ticker"].unique().tolist())

    for h in HORIZONS:
        col = f"excess_{h}d"
        deltas = []
        per_ticker_rows = []
        for t in tickers:
            cand_sub = df[(df["ticker"] == t) & df[col].notna()]
            if cand_sub.empty:
                continue
            cand_avg = cand_sub[col].mean()
            base_avg, base_hit, base_n = _ticker_baseline_excess(price_df, t, h)
            if base_avg is None:
                continue
            deltas.append(cand_avg - base_avg)
            per_ticker_rows.append((t, len(cand_sub), cand_avg, base_avg, base_n))

        if not deltas:
            print(f"  {h}d: no tickers with both candidate and baseline data")
            continue

        arr = np.array(deltas)
        print(f"  --- {h}d horizon: {len(deltas)} tickers with both candidate + baseline data ---")
        print(f"    mean delta (candidate - own baseline): {arr.mean():+.2%}")
        print(f"    median delta:                          {np.median(arr):+.2%}")
        print(f"    % of tickers where award weeks beat own baseline: {(arr > 0).mean():.1%}")

    print("-" * 72)


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--refresh-raw", action="store_true", help="Refetch raw data from Quiver API instead of using cache")
    args = parser.parse_args()

    df, price_df = run_backtest(refresh_raw=args.refresh_raw)
    print_report(df)
    print_control_comparison(df, price_df)


if __name__ == "__main__":
    main()
