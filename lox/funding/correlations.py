"""
Funding-stack cross-correlations.

Surfaces which lever is currently driving funding pressure by computing rolling
correlations between rates (SOFR-IORB corridor, SOFR-EFFR basis) and plumbing
(reserves, RRP, TGA, WALCL, T-bills, net liquidity). The edge is:

  1. Pair correlations vs a 3-year baseline tell you which mechanism is
     currently *active* — e.g., SOFR-IORB ↔ Reserves at -0.65 (vs -0.40
     baseline) means reserves are now the dominant driver of corridor stress.

  2. Divergences flag regime breaks: when ON RRP normally buffers funding
     (strong negative corr with SOFR-IORB) but the correlation weakens toward
     zero, the cushion is broken — that's a regime shift before it shows up in
     levels.

  3. Lead-lag tells you what's a leading indicator: ΔTGA typically leads
     SOFR-IORB by 5-10 days. If today's TGA flow is large and the lagged
     correlation is strong negative, funding stress is queued.

Data alignment: weekly H.4.1 series (WRESBAL, WALCL, WSHOBL) are forward-filled
to a business-day grid so daily rolling correlations have observations on every
date. Change-based pairs use 5-day diffs so Wed-to-Wed weekly prints align
naturally without ffill artifacts.

Public API:
    build_correlation_dataset(refresh=False, start_date) -> pd.DataFrame
    compute_funding_correlation_report(refresh=False) -> dict
"""
from __future__ import annotations

from typing import Optional

import pandas as pd

from lox.config import load_settings
from lox.data.fred import FredClient
from lox.funding.signals import build_funding_dataset
from lox.gov.dts import fetch_tga_daily


# Each pair declares the data needed and the trading interpretation. Keep this
# table small and well-justified — adding noise here makes the regime call
# unstable.
PAIR_META: list[dict] = [
    {
        "name": "SOFR-IORB ↔ Bank Reserves",
        "x": "sofr_iorb_bps", "y": "reserves_b", "kind": "level",
        "expected_sign": "negative",
        "thesis": "Reserve scarcity premium — less reserves → wider corridor.",
        "strong": "reserves scarcity is actively driving SOFR pressure",
        "broken": "reserves no longer the binding constraint",
        "flipped": "regime break — reserves and corridor moving together",
    },
    {
        "name": "SOFR-IORB ↔ ON RRP",
        "x": "sofr_iorb_bps", "y": "rrp_b", "kind": "level",
        "expected_sign": "negative",
        "thesis": "RRP as funding buffer — full RRP → corridor calm.",
        "strong": "RRP buffer is doing its job — funding stress absorbed by MMF cash",
        "broken": "RRP cushion broken — no longer correlated with corridor",
        "flipped": "RRP and corridor co-moving — unusual",
    },
    {
        "name": "SOFR-IORB ↔ Net Liquidity",
        "x": "sofr_iorb_bps", "y": "net_liq_t", "kind": "level",
        "expected_sign": "negative",
        "thesis": "Composite liquidity vs corridor — the canonical macro link.",
        "strong": "net liquidity is the primary corridor driver",
        "broken": "corridor decoupled from net liquidity — idiosyncratic stress",
        "flipped": "regime break",
    },
    {
        "name": "SOFR-EFFR ↔ Bank Reserves",
        "x": "sofr_effr_bps", "y": "reserves_b", "kind": "level",
        "expected_sign": "negative",
        "thesis": "Collateral premium — scarce reserves bid up secured rate vs unsecured.",
        "strong": "collateral premium widening with reserves drain",
        "broken": "collateral premium normalized — no scarcity bid",
        "flipped": "secured trading below unsecured persistently",
    },
    {
        "name": "ΔTGA ↔ ΔReserves",
        "x": "d_tga_b", "y": "d_reserves_b", "kind": "change",
        "expected_sign": "negative",
        "thesis": "Treasury cash account drain — should be ~1:1 with reserves.",
        "strong": "TGA flows fully passing through to reserves (no RRP absorption)",
        "broken": "TGA-reserves link broken — ON RRP or other absorbing the flow",
        "flipped": "TGA build coinciding with reserve growth — unusual",
    },
    {
        "name": "ΔRRP ↔ ΔReserves",
        "x": "d_rrp_b", "y": "d_reserves_b", "kind": "change",
        "expected_sign": "negative",
        "thesis": "RRP unwind → cash to reserves. Should be ~negative as MMFs deploy.",
        "strong": "RRP unwinding directly into reserves",
        "broken": "RRP and reserve flows decoupled — cash going elsewhere (deposits, bills)",
        "flipped": "RRP and reserves growing together — both expanding",
    },
    {
        "name": "ΔBills (Fed) ↔ ΔRRP",
        "x": "d_bills_b", "y": "d_rrp_b", "kind": "change",
        "expected_sign": "negative",
        "thesis": "Fed bill purchases pull MMF cash out of RRP into reserves.",
        "strong": "bill purchases mechanically draining RRP",
        "broken": "bills mechanism broken — RRP not responding to bill flow",
        "flipped": "bills and RRP rising together — unusual",
    },
    {
        "name": "ΔWALCL ↔ ΔReserves",
        "x": "d_walcl_b", "y": "d_reserves_b", "kind": "change",
        "expected_sign": "positive",
        "thesis": "Fed balance-sheet expansion adds reserves directly.",
        "strong": "balance sheet flows passing through to reserves",
        "broken": "WALCL-reserves link weak — flows absorbed by RRP/TGA",
        "flipped": "balance sheet expanding while reserves drain — TGA/RRP overwhelming",
    },
]

# Pairs to run lead-lag analysis on — directional relationships where x is
# hypothesized to lead y. Keep this minimal to avoid multiple-testing noise.
LAG_PAIRS: list[dict] = [
    {
        "name": "ΔTGA → SOFR-IORB",
        "x": "d_tga_b", "y": "sofr_iorb_bps",
        "expected_sign": "positive",  # TGA buildup → wider corridor
        "interpretation": "Treasury cash buildup leading corridor stress.",
    },
    {
        "name": "ΔRRP → SOFR-IORB",
        "x": "d_rrp_b", "y": "sofr_iorb_bps",
        "expected_sign": "negative",  # RRP drain → wider corridor
        "interpretation": "RRP drain leading corridor stress.",
    },
    {
        "name": "ΔWALCL → SOFR-IORB",
        "x": "d_walcl_b", "y": "sofr_iorb_bps",
        "expected_sign": "negative",  # BS expansion → tighter corridor
        "interpretation": "Balance sheet flows leading corridor moves.",
    },
]


# ── Fed ↔ equity transmission pairs ──────────────────────────────────────────
# These quantify whether the Fed's liquidity stance is currently propagating
# into equity levels and volatility. Display-only — do NOT feed into the
# funding regime score (equity reflexivity would muddle the funding call).
#
# Interpretation: a "strong" coupling here means the Fed's plumbing is the
# active driver of equities right now. "Broken" means equities are moving on
# something else (earnings, fiscal, AI capex, sentiment) — the Fed-equity
# transmission is muted, which is itself a regime signal.
EQUITY_PAIR_META: list[dict] = [
    {
        "name": "SOFR-IORB ↔ VIX",
        "x": "sofr_iorb_bps", "y": "vix", "kind": "level",
        "expected_sign": "positive",
        "thesis": "Funding stress feeds equity vol — corridor widens, VIX bids.",
        "strong": "funding stress passing through to equity vol",
        "broken": "VIX moving independent of funding — sentiment/earnings driven",
        "flipped": "vol compressing as corridor widens — atypical",
    },
    {
        "name": "Net Liquidity ↔ VIX",
        "x": "net_liq_t", "y": "vix", "kind": "level",
        "expected_sign": "negative",
        "thesis": "More net liquidity → vol suppression (the canonical 'Fed put' channel).",
        "strong": "liquidity is the dominant vol suppressant right now",
        "broken": "vol decoupled from liquidity — Fed put channel muted",
        "flipped": "vol compressing while liquidity drains — risk-on complacency",
    },
    {
        "name": "ΔNet Liquidity ↔ ΔSPX",
        "x": "d_net_liq_t", "y": "d_sp500_pct", "kind": "change",
        "expected_sign": "positive",
        "thesis": "Howell/Bianco: net-liquidity flows pass through to equity returns.",
        "strong": "net liquidity is actively pushing SPX",
        "broken": "SPX decoupled from net liquidity — fiscal/AI capex dominant",
        "flipped": "SPX moving opposite to liquidity — regime break",
    },
    {
        "name": "ΔReserves ↔ ΔSPX",
        "x": "d_reserves_b", "y": "d_sp500_pct", "kind": "change",
        "expected_sign": "positive",
        "thesis": "Reserves are the cleanest pass-through of Fed action into risk assets.",
        "strong": "reserves flowing directly into equity bid",
        "broken": "reserve flows not reaching equities — sitting at banks",
        "flipped": "reserves growing while SPX falls — credit/risk-off override",
    },
    {
        "name": "ΔRRP ↔ ΔSPX",
        "x": "d_rrp_b", "y": "d_sp500_pct", "kind": "change",
        "expected_sign": "negative",
        "thesis": "RRP unwind releases MMF cash into the system — risk-on mechanically.",
        "strong": "RRP drain is fuelling equity rally",
        "broken": "RRP flows not affecting equities — cushion gone, no mechanism left",
        "flipped": "RRP and SPX rising together — both bid by external flow",
    },
]

# Equity lead-lag — does Fed liquidity *lead* equity returns?
EQUITY_LAG_PAIRS: list[dict] = [
    {
        "name": "ΔNet Liquidity → ΔSPX",
        "x": "d_net_liq_t", "y": "d_sp500_pct",
        "expected_sign": "positive",
        "interpretation": "Net liquidity flow leading equity returns (Howell channel).",
    },
    {
        "name": "ΔWALCL → ΔSPX",
        "x": "d_walcl_b", "y": "d_sp500_pct",
        "expected_sign": "positive",
        "interpretation": "Fed balance-sheet pace leading equity drift.",
    },
    {
        "name": "ΔReserves → ΔSPX",
        "x": "d_reserves_b", "y": "d_sp500_pct",
        "expected_sign": "positive",
        "interpretation": "Reserve injections leading equity returns.",
    },
    {
        "name": "SOFR-IORB → VIX",
        "x": "sofr_iorb_bps", "y": "vix",
        "expected_sign": "positive",
        "interpretation": "Funding stress leading equity vol expansion.",
    },
]


def build_correlation_dataset(
    *,
    refresh: bool = False,
    start_date: str = "2018-01-01",
) -> pd.DataFrame:
    """
    Daily business-day DataFrame with all funding/plumbing series.

    Columns:
        sofr_iorb_bps, sofr_effr_bps    (rates, daily)
        rrp_b, tga_b                    (plumbing daily, $B)
        reserves_b, walcl_b, bills_b    (plumbing weekly ffilled to daily, $B)
        net_liq_t                       (composite, $T)
        d_*_b                           (5-business-day diffs for change pairs)

    Returns empty DataFrame if any critical fetch fails (no API key, etc.).
    """
    settings = load_settings()
    if not settings.FRED_API_KEY:
        return pd.DataFrame()

    fred = FredClient(api_key=settings.FRED_API_KEY)

    # Rates from the funding dataset (already business-day aligned)
    try:
        fdf = build_funding_dataset(settings=settings, start_date=start_date, refresh=refresh)
    except Exception:
        return pd.DataFrame()
    rates = fdf[["date", "CORRIDOR_SPREAD_BPS", "SOFR_EFFR_BPS"]].rename(columns={
        "CORRIDOR_SPREAD_BPS": "sofr_iorb_bps",
        "SOFR_EFFR_BPS": "sofr_effr_bps",
    }).copy()
    rates["date"] = pd.to_datetime(rates["date"])

    # Plumbing fetches (each may fail independently — degrade gracefully)
    def _fred_b(series_id: str, divisor: float = 1.0) -> pd.DataFrame:
        try:
            df = fred.fetch_series(series_id=series_id, start_date=start_date, refresh=refresh)
        except Exception:
            return pd.DataFrame(columns=["date", "value"])
        if df is None or df.empty:
            return pd.DataFrame(columns=["date", "value"])
        df = df.copy()
        df["date"] = pd.to_datetime(df["date"], errors="coerce")
        df["value"] = pd.to_numeric(df["value"], errors="coerce") / divisor
        return df.dropna(subset=["date", "value"])[["date", "value"]]

    rrp = _fred_b("RRPONTSYD", 1.0).rename(columns={"value": "rrp_b"})
    reserves = _fred_b("WRESBAL", 1000.0).rename(columns={"value": "reserves_b"})  # M → B
    walcl = _fred_b("WALCL", 1000.0).rename(columns={"value": "walcl_b"})
    bills = _fred_b("WSHOBL", 1000.0).rename(columns={"value": "bills_b"})
    # Equity transmission inputs — display-only, never feed into regime score.
    # FRED SP500 only has ~10y of history; that's plenty for 60d rolling + 3y baseline.
    sp500 = _fred_b("SP500", 1.0).rename(columns={"value": "sp500"})
    vix = _fred_b("VIXCLS", 1.0).rename(columns={"value": "vix"})

    try:
        tga = fetch_tga_daily(refresh=refresh, lookback_days=2200)
        tga["date"] = pd.to_datetime(tga["date"])
        tga = tga.rename(columns={"tga_close_b": "tga_b"})[["date", "tga_b"]]
    except Exception:
        tga = pd.DataFrame(columns=["date", "tga_b"])

    # Build a business-day spine
    end = pd.Timestamp.today().normalize()
    bidx = pd.bdate_range(start=pd.to_datetime(start_date), end=end)
    out = pd.DataFrame({"date": bidx})

    for f in [rates, rrp, reserves, walcl, bills, tga, sp500, vix]:
        if f is None or f.empty:
            continue
        out = out.merge(f, on="date", how="left")

    # Forward-fill all plumbing levels. Weekly H.4.1 series need ffill to give
    # daily rolling correlations an observation each day; daily series (RRP,
    # TGA) need ffill across federal holidays where reporting is skipped.
    # Without this, ANY holiday in a 60-day window makes the rolling corr NaN.
    for col in ("rrp_b", "tga_b", "reserves_b", "walcl_b", "bills_b", "sp500", "vix"):
        if col in out.columns:
            out[col] = out[col].ffill()

    # Net liquidity composite ($T) — Howell/Bianco definition: Fed balance
    # sheet minus TGA minus ON RRP. Deliberately WALCL, not bank reserves
    # (WRESBAL) — reserves already nets out most of TGA/RRP's balance-sheet
    # impact, so reserves-TGA-RRP double-subtracts and produces a series with
    # ~zero correlation to the standard WALCL-based net liquidity print (and
    # a level ~$4T off from what's commonly quoted). This is the series the
    # "Howell/Bianco" pair thesis below (EQUITY_PAIR_META) refers to.
    if all(c in out.columns for c in ("walcl_b", "tga_b", "rrp_b")):
        out["net_liq_t"] = (out["walcl_b"] - out["tga_b"] - out["rrp_b"]) / 1000.0

    # Week-over-week (Wed-to-Wed) changes for change-pair correlations.
    # This is critical: WRESBAL/WALCL/WSHOBL only print Wednesdays, while
    # TGA and RRP print daily. Computing daily 5-day diffs gives smooth daily
    # variation on TGA/RRP but step-function diffs on the weekly series — they
    # don't correlate properly. Sampling all to Wednesday cadence makes the
    # change-pair correlations apples-to-apples.
    wed_mask = out["date"].dt.dayofweek == 2
    wed_cols = ["tga_b", "rrp_b", "reserves_b", "walcl_b", "bills_b", "net_liq_t", "sp500"]
    wed_only = out.loc[wed_mask, ["date"] + [c for c in wed_cols if c in out.columns]].copy()
    diff_cols: list[str] = []
    for col in ("tga_b", "rrp_b", "reserves_b", "walcl_b", "bills_b", "net_liq_t"):
        if col not in wed_only.columns:
            continue
        wed_only[f"d_{col}"] = wed_only[col].diff()
        diff_cols.append(f"d_{col}")
    # SP500: pct change (so the units match across vol regimes — a $50 SPX move
    # in 2024 is not the same as in 2018). Multiplied by 100 for readability.
    if "sp500" in wed_only.columns:
        wed_only["d_sp500_pct"] = wed_only["sp500"].pct_change() * 100.0
        diff_cols.append("d_sp500_pct")
    if diff_cols:
        out = out.merge(wed_only[["date"] + diff_cols], on="date", how="left")
        for col in diff_cols:
            out[col] = out[col].ffill()

    return out


def _classify_strength(
    current: float | None,
    baseline: float | None,
    expected_sign: str,
) -> tuple[str, str]:
    """
    Return (label, status) where status is one of:
        "strong"  — current correlation is at-or-beyond baseline in expected direction
        "weak"    — current much weaker than baseline (decoupling)
        "broken"  — current near zero
        "flipped" — current has opposite sign from expected
        "normal"  — current roughly matches baseline
    """
    if current is None or baseline is None:
        return ("[dim]—[/dim]", "unknown")

    expected_neg = (expected_sign == "negative")
    cur_sign_matches = (current < 0) if expected_neg else (current > 0)

    # Normalize so positive = "in expected direction". This catches the case
    # where baseline was actually sign-flipped (weak) and current swung toward
    # the expected direction — that's a meaningful "newly active" coupling,
    # not "normal."
    expected_dir = -1.0 if expected_sign == "negative" else 1.0
    cur_norm = current * expected_dir
    base_norm = baseline * expected_dir
    delta_norm = cur_norm - base_norm

    if cur_norm < -0.15:
        # "Flipped" should mean a genuine transition: baseline was correctly
        # signed (in the expected direction) and current has reversed. If
        # baseline was ALREADY wrong-signed (base_norm below the same
        # threshold), nothing just "broke" — it's a persistent inversion, not
        # a new regime break. Without this check, two wrong-signed prints of
        # similar magnitude (e.g. +0.15 -> +0.19 when negative is expected)
        # get mislabeled "regime break" even though delta_norm ~ 0.
        if base_norm >= 0.15:
            return ("[red]regime break — flipped[/red]", "flipped")
        return ("[red]decoupled — broken[/red]", "broken")
    if cur_norm < 0.15:
        return ("[red]decoupled — broken[/red]", "broken")
    if delta_norm > 0.15:
        return ("[bold yellow]stronger coupling[/bold yellow]", "strong")
    if delta_norm < -0.20:
        return ("[yellow]weaker coupling[/yellow]", "weak")
    return ("[dim]normal[/dim]", "normal")


def compute_pair_correlations(
    df: pd.DataFrame,
    *,
    window: int = 60,
    hist_window_days: int = 252 * 3,
    meta_list: list[dict] | None = None,
) -> list[dict]:
    """
    For each entry in `meta_list` (default PAIR_META), compute current and
    historical-baseline rolling correlations and assign a status label.
    """
    results: list[dict] = []
    if df.empty:
        return results

    for meta in (meta_list if meta_list is not None else PAIR_META):
        x, y = meta["x"], meta["y"]
        if x not in df.columns or y not in df.columns:
            continue
        sx = pd.to_numeric(df[x], errors="coerce")
        sy = pd.to_numeric(df[y], errors="coerce")
        roll = sx.rolling(window).corr(sy)
        roll_valid = roll.dropna()
        if roll_valid.empty:
            continue

        current = float(roll_valid.iloc[-1])
        # Baseline = median of past rolling correlations, excluding the most
        # recent `window` observations (avoid the current period contaminating
        # the baseline it's being compared against).
        hist = roll_valid.iloc[:-window] if len(roll_valid) > window else roll_valid
        if hist.empty:
            baseline = current
        else:
            baseline = float(hist.tail(hist_window_days).median())

        label, status = _classify_strength(current, baseline, meta["expected_sign"])
        interp_key = {
            "strong": "strong", "weak": "broken", "broken": "broken", "flipped": "flipped"
        }.get(status)
        interpretation = meta.get(interp_key) if interp_key else None

        # Effective sample size: several inputs (WRESBAL, WALCL, WSHOBL, and
        # any d_* change column) only update weekly and are forward-filled to
        # a daily grid. A "60-day rolling correlation" on those is really
        # ~12 independent weekly prints wearing a 60-observation costume —
        # correlations look precise but carry far less statistical power than
        # the window size implies. n_eff = distinct values of the sparser
        # series inside the window is a data-driven proxy for the real
        # degrees of freedom, without hardcoding which columns are weekly.
        n_eff = int(min(sx.tail(window).nunique(), sy.tail(window).nunique()))
        thin_sample = n_eff < 20

        results.append({
            **meta,
            "current": current,
            "baseline": baseline,
            "delta": current - baseline,
            "label": label,
            "status": status,
            "interpretation": interpretation,
            "n_eff": n_eff,
            "thin_sample": thin_sample,
        })
    return results


def _scan_lags(
    sx: pd.Series,
    sy: pd.Series,
    *,
    window: int,
    max_lag_days: int,
    end: int | None = None,
) -> tuple[list[tuple[int, float | None]], int, float]:
    """
    Search lag in [0, max_lag_days] for the lag that maximizes |correlation|
    of sx.shift(lag) vs sy, evaluated at row `end` (default: last row).
    x leads y by `lag` days. Returns (full curve, best_lag, best_corr).
    """
    sub_x = sx if end is None else sx.iloc[:end]
    sub_y = sy if end is None else sy.iloc[:end]
    curve: list[tuple[int, float | None]] = []
    best_lag, best_corr = 0, 0.0
    for lag in range(max_lag_days + 1):
        shifted = sub_x.shift(lag)
        c = shifted.rolling(window).corr(sub_y).iloc[-1] if len(sub_x) > window + lag else None
        c_val = float(c) if c is not None and pd.notna(c) else None
        curve.append((lag, c_val))
        if c_val is not None and abs(c_val) > abs(best_corr):
            best_corr = c_val
            best_lag = lag
    return curve, best_lag, best_corr


def compute_lead_lag(
    df: pd.DataFrame,
    *,
    window: int = 60,
    max_lag_days: int = 15,
    lag_pairs: list[dict] | None = None,
    stability_probe_days: int = 21,
) -> list[dict]:
    """
    For each entry in `lag_pairs` (default LAG_PAIRS), search lag in
    [0, max_lag_days] for the lag that maximizes |correlation| and report it.
    x leads y by `lag` days.

    Also reports, per pair:
      - lag_curve: the full (lag, corr) scan, not just the argmax — a single
        max-|corr| pick over many lags on a short window overfits easily;
        the curve lets a caller judge whether the max is a clean peak or
        noise (see n_eff / unstable below).
      - n_eff: effective independent observations backing the CURRENT
        window's correlation. Change-pairs (d_*) and any weekly H.4.1-backed
        level (reserves_b/walcl_b/bills_b) are forward-filled from a weekly
        print, so a "60-day window" is often only ~12 independent data
        points, not 60 — n_eff surfaces the real count.
      - unstable: whether the best lag found `stability_probe_days` trading
        days ago materially disagrees (sign flip, or lag moved by more than
        ~40% of the search range) with today's best lag. A relationship
        whose "best lag" jumps around month to month on the same search is
        noise, not a tradeable lead-lag edge, however large a single
        snapshot's |corr| looks.
    """
    results: list[dict] = []
    if df.empty:
        return results

    for meta in (lag_pairs if lag_pairs is not None else LAG_PAIRS):
        x, y = meta["x"], meta["y"]
        if x not in df.columns or y not in df.columns:
            continue
        sx = pd.to_numeric(df[x], errors="coerce")
        sy = pd.to_numeric(df[y], errors="coerce")

        lag_curve, best_lag, best_corr = _scan_lags(sx, sy, window=window, max_lag_days=max_lag_days)

        if best_lag == 0 and abs(best_corr) < 0.1:
            continue  # no meaningful relationship found

        # Compare contemporaneous (lag 0) vs best lag — does lag actually add signal?
        contemp = sx.rolling(window).corr(sy).iloc[-1]
        contemp_v = float(contemp) if pd.notna(contemp) else 0.0

        sign_matches = (
            (best_corr > 0 and meta["expected_sign"] == "positive") or
            (best_corr < 0 and meta["expected_sign"] == "negative")
        )

        n_eff = int(min(sx.tail(window).nunique(), sy.tail(window).nunique()))

        # Stability probe: same scan, evaluated `stability_probe_days` ago.
        unstable = False
        prior_best_lag: int | None = None
        prior_best_corr: float | None = None
        probe_end = len(sx) - stability_probe_days
        if probe_end > window + max_lag_days:
            _, prior_best_lag, prior_best_corr = _scan_lags(
                sx, sy, window=window, max_lag_days=max_lag_days, end=probe_end
            )
            sign_flip = (best_corr > 0) != (prior_best_corr > 0)
            lag_jump = abs(best_lag - prior_best_lag) > max(10, max_lag_days * 0.4)
            unstable = sign_flip or lag_jump

        # A lag of 0 (contemporaneous) or a sign that fights the thesis is
        # informative but not a leading indicator — keep it out of the
        # tradeable bucket explicitly rather than lumping it with "too weak".
        diagnostic_only = best_lag == 0 or not sign_matches

        results.append({
            **meta,
            "best_lag": best_lag,
            "best_corr": best_corr,
            "contemp_corr": contemp_v,
            "sign_matches": sign_matches,
            "lag_curve": lag_curve,
            "n_eff": n_eff,
            "thin_sample": n_eff < 20,
            "unstable": unstable,
            "prior_best_lag": prior_best_lag,
            "prior_best_corr": prior_best_corr,
            "diagnostic_only": diagnostic_only,
            "tradeable": (
                abs(best_corr) > 0.30
                and sign_matches
                and best_lag >= 3
                and n_eff >= 20
                and not unstable
            ),
        })
    return results


def classify_funding_regime(
    pair_results: list[dict],
    lag_results: list[dict],
) -> dict:
    """
    Top-line regime call based on which correlations dominate. Returns:
        {
            "regime": str,
            "rationale": str,
            "divergences": list[str],   — concrete broken/flipped pairs worth flagging
            "leading_indicators": list[str],  — pairs where lead-lag is tradeable
        }
    """
    by_name = {p["name"]: p for p in pair_results}

    sofr_reserves = by_name.get("SOFR-IORB ↔ Bank Reserves")
    sofr_rrp = by_name.get("SOFR-IORB ↔ ON RRP")
    sofr_netliq = by_name.get("SOFR-IORB ↔ Net Liquidity")
    sofr_effr_res = by_name.get("SOFR-EFFR ↔ Bank Reserves")

    regime = "BALANCED"
    rationale = "no single mechanism dominant"

    def _strong_neg(p):
        return p and p["current"] is not None and p["current"] < -0.45

    def _broken_or_weak(p):
        return p and p["status"] in ("broken", "weak", "flipped")

    if _strong_neg(sofr_reserves) and _broken_or_weak(sofr_rrp):
        regime = "RESERVE-CONSTRAINED"
        rationale = "reserves dominant driver of corridor; RRP cushion no longer active"
    elif _strong_neg(sofr_reserves):
        regime = "RESERVE-LINKED"
        rationale = "reserves coupled to corridor, but other absorbers still functioning"
    elif _strong_neg(sofr_rrp) and not _strong_neg(sofr_reserves):
        regime = "RRP-CUSHIONED"
        rationale = "MMF cash buffer is absorbing corridor stress"
    elif _strong_neg(sofr_netliq):
        regime = "NET-LIQUIDITY-DRIVEN"
        rationale = "composite liquidity is the primary corridor driver"
    elif _broken_or_weak(sofr_netliq) and _broken_or_weak(sofr_reserves):
        regime = "DECOUPLED"
        rationale = "corridor moving independent of plumbing — idiosyncratic stress"

    # Divergence flags — only the meaningful ones (broken couplings or large
    # regime shifts toward expected direction)
    divergences: list[str] = []
    for p in pair_results:
        if p["status"] in ("broken", "flipped"):
            divergences.append(
                f"{p['name']}: {p['interpretation']} (now {p['current']:+.2f}, was {p['baseline']:+.2f})"
            )
        elif p["status"] == "strong":
            # "stronger coupling" with meaningful swing from baseline = newly active mechanism
            divergences.append(
                f"{p['name']}: {p['interpretation']} (now {p['current']:+.2f}, was {p['baseline']:+.2f})"
            )

    # Collateral-scarcity tag (SOFR-EFFR basis)
    if _strong_neg(sofr_effr_res):
        divergences.append(f"Collateral premium active: SOFR-EFFR basis correlated with reserves at {sofr_effr_res['current']:+.2f}")

    # Tradeable leading indicators
    leading: list[str] = []
    for l in lag_results:
        if l.get("tradeable"):
            arrow = "↑" if l["best_corr"] > 0 else "↓"
            leading.append(
                f"{l['name']}: {l['best_lag']}-day lead, corr {arrow}{abs(l['best_corr']):.2f}  →  {l['interpretation']}"
            )

    return {
        "regime": regime,
        "rationale": rationale,
        "divergences": divergences,
        "leading_indicators": leading,
    }


def compute_funding_correlation_report(*, refresh: bool = False) -> dict:
    """
    Top-level entry point — builds dataset, computes all correlations, classifies regime.

    Returns:
        {
            "asof": "YYYY-MM-DD" | None,
            "pairs": list[pair_result_dict],            # plumbing pairs
            "lags": list[lag_result_dict],              # plumbing lead-lag
            "equity_pairs": list[pair_result_dict],     # Fed↔equities pairs (display-only)
            "equity_lags": list[lag_result_dict],       # Fed↔equities lead-lag (display-only)
            "regime": str,
            "rationale": str,
            "divergences": list[str],
            "leading_indicators": list[str],
        }

    Equity pairs are kept separate and never feed into the regime classifier:
    funding scoring should reflect funding mechanics, not market reflexivity.
    """
    empty = {
        "asof": None, "pairs": [], "lags": [],
        "equity_pairs": [], "equity_lags": [],
        "regime": None, "rationale": None,
        "divergences": [], "leading_indicators": [],
    }
    try:
        df = build_correlation_dataset(refresh=refresh)
    except Exception:
        return empty
    if df.empty:
        return empty

    # asof = last business day where we have any rates data
    valid = df.dropna(subset=["sofr_iorb_bps"], how="all") if "sofr_iorb_bps" in df.columns else df
    asof = str(pd.to_datetime(valid["date"].iloc[-1]).date()) if not valid.empty else None

    pairs = compute_pair_correlations(df)
    lags = compute_lead_lag(df)
    regime_info = classify_funding_regime(pairs, lags)

    # Equity transmission — wider lag horizon (Howell channel is 2-12 weeks,
    # not days). Skips gracefully when sp500/vix columns absent.
    equity_pairs = compute_pair_correlations(df, meta_list=EQUITY_PAIR_META)
    equity_lags = compute_lead_lag(df, lag_pairs=EQUITY_LAG_PAIRS, max_lag_days=60)

    return {
        "asof": asof,
        "pairs": pairs,
        "lags": lags,
        "equity_pairs": equity_pairs,
        "equity_lags": equity_lags,
        **regime_info,
    }
