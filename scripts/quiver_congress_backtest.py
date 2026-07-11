"""
Stage 1 research script — Quiver Edge Expansion plan.

Purpose: test the existing congress-trading data itself (which the plan already
identifies as the weakest-edge family due to disclosure lag + crowding) rather
than assuming that verdict. Two questions:

  1. As an unconditional signal, do stocks that members of Congress disclosed
     BUYING actually outperform SPY afterward, measured from the disclosure
     date (the point a follower could actually act), not the trade date?
  2. Is there a meaningful, sample-size-aware difference between individual
     members — i.e. is "follow Rep. X" better than "follow the average
     discloser"?

Design principles (same as scripts/quiver_contracts_backtest.py):
  - Log EVERY disclosed trade as a candidate, not just "notable" ones.
  - No scoring formula — just raw effect size, by horizon.
  - Entry point is the DISCLOSURE date (ReportDate), not the trade date —
    that's the earliest point a real follower could have acted, and lag is
    exactly the thing this whole plan is skeptical of.
  - Rank members against the cohort average, not in isolation, so we're not
    mistaking "got lucky on one big trade" for skill.

Known limitations of this pass:
  - The /live/congresstrading endpoint on the current Quiver tier caps at
    1,000 rows regardless of page/offset/limit params — this is ~1 year of
    history (2025-07 to 2026-07), not the full multi-year record. Per-member
    sample sizes are small; treat the ranking as suggestive, not conclusive.
  - Amount is a disclosed RANGE (bucketed), not an exact dollar figure —
    the midpoint is an estimate.
  - No control-group check per member (e.g. against that member's own
    baseline or sector-matched baseline) — this is a simpler, first-pass cut.
    A member showing a positive delta vs the cohort average could still be
    riding a sector tailwind rather than genuine skill.
  - No transaction costs / liquidity modeled.

Usage:
    python scripts/quiver_congress_backtest.py
    python scripts/quiver_congress_backtest.py --refresh-raw
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

import numpy as np
import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from lox.config import Settings
from lox.data.market import fetch_equity_daily_closes
from lox.quiver.loader import fetch_congress_live, get_api_key

RAW_CACHE = Path("data/cache/quiver_research/congress_raw.json")
CANDIDATES_OUT = Path("data/cache/quiver_research/congress_backtest_candidates.csv")
HORIZONS = (5, 10, 20, 45)
MIN_TRADES_FOR_RANKING = 5


def fetch_raw(*, refresh: bool = False) -> pd.DataFrame:
    if RAW_CACHE.exists() and not refresh:
        raw = json.loads(RAW_CACHE.read_text())
        return pd.DataFrame(raw)

    key = get_api_key()
    if not key:
        raise RuntimeError("QUIVER_API_KEY not set")

    df = fetch_congress_live(key)
    if df is None:
        raise RuntimeError("No data returned from /live/congresstrading")

    RAW_CACHE.parent.mkdir(parents=True, exist_ok=True)
    RAW_CACHE.write_text(df.to_json(orient="records"))
    return df


def _classify_side(raw) -> str:
    s = str(raw or "").strip().lower()
    if "purchase" in s:
        return "Buy"
    if "sale" in s or "exchange" in s:
        return "Sell"
    return ""


def _parse_amount_mid(range_str) -> float:
    s = str(range_str or "").strip()
    if not s or s.lower() == "nan":
        return 0.0
    parts = [p.strip().lstrip("$").replace(",", "") for p in s.split("-")]
    try:
        lo = float(parts[0]) if parts[0] else 0.0
        hi = float(parts[1]) if len(parts) > 1 and parts[1] else lo
        return (lo + hi) / 2.0
    except (ValueError, IndexError):
        return 0.0


def build_candidates(raw: pd.DataFrame) -> pd.DataFrame:
    df = raw.copy()
    df.columns = [str(c).strip().lower() for c in df.columns]

    df["ticker"] = df["ticker"].astype(str).str.strip().str.upper()
    df = df[df["ticker"].notna() & (df["ticker"] != "") & (df["ticker"] != "NAN")]

    ticker_type = df.get("tickertype")
    if ticker_type is not None:
        df = df[ticker_type.astype(str).str.strip().str.lower().isin(["st", "stock", ""])]

    df["side"] = df["transaction"].apply(_classify_side)
    df = df[df["side"] != ""]

    df["transactiondate"] = pd.to_datetime(df["transactiondate"], errors="coerce")
    df["reportdate"] = pd.to_datetime(df["reportdate"], errors="coerce")
    df = df.dropna(subset=["transactiondate", "reportdate"])
    df["lag_days"] = (df["reportdate"] - df["transactiondate"]).dt.days
    df = df[df["lag_days"] >= 0]

    df["amount_mid_usd"] = df["range"].apply(_parse_amount_mid) if "range" in df.columns else 0.0

    return df[[
        "representative", "ticker", "side", "transactiondate", "reportdate",
        "lag_days", "amount_mid_usd", "party",
    ]].reset_index(drop=True)


def _trading_day_return(px: pd.Series, t0_idx: int, offset: int) -> float | None:
    if t0_idx + offset >= len(px):
        return None
    p0, p1 = px.iloc[t0_idx], px.iloc[t0_idx + offset]
    if p0 is None or p1 is None or p0 == 0 or pd.isna(p0) or pd.isna(p1):
        return None
    return (p1 / p0) - 1.0


def run_backtest(*, refresh_raw: bool) -> pd.DataFrame:
    print("Fetching congress trading feed...")
    raw = fetch_raw(refresh=refresh_raw)
    print(f"  {len(raw)} raw rows")

    candidates = build_candidates(raw)
    print(f"  {len(candidates)} usable trade candidates ({candidates['side'].eq('Buy').sum()} buys, "
          f"{candidates['side'].eq('Sell').sum()} sells) across {candidates['representative'].nunique()} representatives")
    print(f"  disclosure lag: median {candidates['lag_days'].median():.0f}d, "
          f"mean {candidates['lag_days'].mean():.0f}d, max {candidates['lag_days'].max():.0f}d")

    tickers = sorted(candidates["ticker"].unique().tolist())
    earliest = candidates["reportdate"].min() - pd.Timedelta(days=5)

    settings = Settings()

    print(f"Fetching daily prices for {len(tickers)} tickers + SPY (cached where available)...")
    px_frames = []
    resolved = []
    for t in tickers + ["SPY"]:
        try:
            px = fetch_equity_daily_closes(settings=settings, symbols=[t], start=str(earliest.date()))
            if px is not None and not px.empty and t in px.columns:
                px_frames.append(px[[t]])
                if t != "SPY":
                    resolved.append(t)
        except Exception as e:
            print(f"  skip {t}: {e}")

    price_df = pd.concat(px_frames, axis=1).sort_index()
    price_df = price_df.loc[:, ~price_df.columns.duplicated()]
    dropped = set(tickers) - set(resolved)
    if dropped:
        print(f"  dropped {len(dropped)} tickers with no resolvable price data: {sorted(dropped)}")

    rows = []
    for _, c in candidates.iterrows():
        ticker = c["ticker"]
        if ticker not in price_df.columns or "SPY" not in price_df.columns:
            continue
        px = price_df[ticker].dropna()
        spy = price_df["SPY"].dropna()
        idx = px.index.intersection(spy.index)
        px, spy = px.loc[idx], spy.loc[idx]
        if px.empty:
            continue

        signal_date = c["reportdate"]
        pos = px.index.searchsorted(signal_date)
        if pos >= len(px):
            continue

        row = {
            "representative": c["representative"],
            "party": c["party"],
            "ticker": ticker,
            "side": c["side"],
            "transaction_date": c["transactiondate"].date(),
            "report_date": signal_date.date(),
            "lag_days": c["lag_days"],
            "amount_mid_usd": c["amount_mid_usd"],
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
    print(f"\nWrote {len(result)} candidates to {CANDIDATES_OUT}")
    return result


def print_overall_report(df: pd.DataFrame) -> None:
    print("\n" + "=" * 72)
    print("OVERALL — Congress disclosures vs forward returns (from disclosure date)")
    print("=" * 72)

    for side in ("Buy", "Sell"):
        sub_side = df[df["side"] == side]
        if sub_side.empty:
            continue
        print(f"\n  === {side} disclosures (n={len(sub_side)}) ===")
        for h in HORIZONS:
            col = f"excess_{h}d"
            resolved = sub_side[sub_side[col].notna()]
            if resolved.empty:
                print(f"    {h}d: no resolved candidates")
                continue
            hit_rate = (resolved[col] > 0).mean()
            avg_excess = resolved[col].mean()
            med_excess = resolved[col].median()
            print(f"    {h}d: n={len(resolved):<5} hit_rate={hit_rate:.1%}  avg_excess={avg_excess:+.2%}  median_excess={med_excess:+.2%}")


def print_ranking(df: pd.DataFrame, horizon: int = 20) -> None:
    col = f"excess_{horizon}d"
    buys = df[(df["side"] == "Buy") & df[col].notna()]

    if buys.empty:
        print(f"\nNo resolved buy candidates at {horizon}d horizon — cannot rank.")
        return

    cohort_avg = buys[col].mean()

    print("\n" + "=" * 72)
    print(f"REPRESENTATIVE RANKING — buy disclosures, {horizon}d forward excess vs SPY")
    print("=" * 72)
    print(f"Cohort average (all reps, all buys, this horizon): {cohort_avg:+.2%}")
    print(f"Only showing representatives with >= {MIN_TRADES_FOR_RANKING} resolved buy trades ")
    print("(smaller samples are too noisy to call 'skill' — shown separately below).\n")

    grp = buys.groupby("representative").agg(
        n_trades=(col, "count"),
        avg_excess=(col, "mean"),
        hit_rate=(col, lambda s: (s > 0).mean()),
        party=("party", "first"),
    ).reset_index()
    grp["delta_vs_cohort"] = grp["avg_excess"] - cohort_avg

    ranked = grp[grp["n_trades"] >= MIN_TRADES_FOR_RANKING].sort_values("avg_excess", ascending=False)
    small_n = grp[grp["n_trades"] < MIN_TRADES_FOR_RANKING]

    if ranked.empty:
        print(f"  No representative has >= {MIN_TRADES_FOR_RANKING} resolved buy trades at this horizon.")
    else:
        print(f"  {'representative':<32} {'party':<6}{'n':>4}  {'avg_excess':>11}  {'hit_rate':>9}  {'vs_cohort':>10}")
        for _, r in ranked.iterrows():
            print(f"  {r['representative']:<32} {str(r['party']):<6}{r['n_trades']:>4}  "
                  f"{r['avg_excess']:>+10.2%}  {r['hit_rate']:>8.1%}  {r['delta_vs_cohort']:>+9.2%}")

    print(f"\n  ({len(small_n)} representatives excluded from ranking for having < {MIN_TRADES_FOR_RANKING} resolved buy trades)")

    print("\n" + "-" * 72)
    print("REMINDERS (do not skip):")
    print("  - ~1 year of history only (Quiver API caps this endpoint at 1,000 rows).")
    print("  - Amount is a bucketed disclosure range, not exact dollars.")
    print("  - No per-member control (sector tilt / own-baseline) applied — a positive")
    print("    delta here could be a sector tailwind, not demonstrated individual skill.")
    print("  - Entry point is the DISCLOSURE date, matching what a real follower could act on.")
    print("  - This is exploratory research only — not a signal, not shipped.")
    print("-" * 72)


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--refresh-raw", action="store_true", help="Refetch raw data from Quiver API instead of using cache")
    parser.add_argument("--rank-horizon", type=int, default=20, choices=HORIZONS, help="Horizon (days) to use for the representative ranking")
    args = parser.parse_args()

    df = run_backtest(refresh_raw=args.refresh_raw)
    print_overall_report(df)
    print_ranking(df, horizon=args.rank_horizon)


if __name__ == "__main__":
    main()
