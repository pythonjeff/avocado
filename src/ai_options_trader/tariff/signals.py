from __future__ import annotations

import pandas as pd

from ai_options_trader.tariff.models import TariffRegimeState, TariffInputs
from ai_options_trader.tariff.theory import TariffRegimeSpec, DEFAULT_TARIFF_SPEC
from ai_options_trader.tariff.transforms import (
    zscore,
    returns,
    rel_returns,
    cost_momentum,
    rolling_beta,
)

try:
    # Optional: if present, use named weights to build a composite cost proxy
    from ai_options_trader.tariff.proxies import DEFAULT_COST_PROXY_WEIGHTS
except Exception:  # pragma: no cover
    DEFAULT_COST_PROXY_WEIGHTS = {}


def _composite_cost_proxy(cost_df: pd.DataFrame, z_window: int) -> pd.Series:
    """
    Build a composite cost proxy from multiple columns.

    Method:
    1) z-score each proxy over a rolling window
    2) combine using DEFAULT_COST_PROXY_WEIGHTS when available
       - if weights missing or don't match columns, fall back to equal-weight

    Returns: Series named 'cost_proxy'
    """
    cost_df = cost_df.sort_index()

    # z-score each column
    z_cols = {}
    for c in cost_df.columns:
        s = cost_df[c].astype(float)
        z_cols[c] = zscore(s, window=z_window)

    z_mat = pd.DataFrame(z_cols).dropna(how="all")

    # Build weights aligned to available columns
    cols = list(z_mat.columns)
    if DEFAULT_COST_PROXY_WEIGHTS:
        w = pd.Series({c: DEFAULT_COST_PROXY_WEIGHTS.get(c, 0.0) for c in cols}, dtype=float)
        if w.sum() > 0:
            w = w / w.sum()
            return (z_mat.mul(w, axis=1).sum(axis=1)).rename("cost_proxy")

    # Equal-weight fallback
    return z_mat.mean(axis=1).rename("cost_proxy")


def build_tariff_regime_state(
    cost_df: pd.DataFrame | None = None,
    equity_prices: pd.DataFrame | None = None,
    # Backward-compatible aliases:
    cost_proxies: pd.DataFrame | None = None,
    equity_prices_df: pd.DataFrame | None = None,
    universe: list[str] | None = None,
    benchmark: str = "XLY",
    basket_name: str = "import_retail_apparel",
    start_date: str = "2016-01-01",
    spec: TariffRegimeSpec = DEFAULT_TARIFF_SPEC,
) -> TariffRegimeState:
    """
    Compute tariff/cost-push regime state.

    Components:
    - Cost Pressure Momentum (CPM): momentum of composite cost proxy (short minus long diff)
    - Equity Price Denial (EPD): rolling beta of basket relative returns vs CPM
      *Gated*: only contributes when z_cpm > 0 (cost pressure is above neutral)
    - Earnings Fragility (EF): placeholder 0.0 until wired

    Output:
    - TariffRegimeState with score, regime boolean, and transparent components.
    """
    if cost_df is None:
        cost_df = cost_proxies
    if equity_prices is None:
        equity_prices = equity_prices_df
    if cost_df is None or equity_prices is None:
        raise ValueError("Must provide cost_df and equity_prices (or aliases).")
    if universe is None or len(universe) == 0:
        raise ValueError("Must provide universe tickers list.")
    if benchmark is None or not benchmark.strip():
        raise ValueError("Must provide benchmark symbol.")

    cost_df = cost_df.sort_index()
    equity_prices = equity_prices.sort_index()

    # Composite cost proxy
    cost_proxy = _composite_cost_proxy(cost_df, z_window=spec.z_window_days)

    # Cost Pressure Momentum (CPM) + z-score
    cpm = cost_momentum(cost_proxy, short=spec.cost_short_days, long=spec.cost_long_days)
    z_cpm = zscore(cpm, window=spec.z_window_days)

    # Equity returns and benchmark
    r = equity_prices.apply(returns).dropna(how="all")
    if benchmark not in r.columns:
        raise ValueError(f"Benchmark {benchmark} not present in equity_prices columns.")
    bench_ret = r[benchmark].rename("bench")

    # Basket relative returns (equal-weight for now)
    rels = []
    for sym in universe:
        if sym in r.columns:
            rels.append(rel_returns(r[sym], bench_ret).rename(sym))

    if not rels:
        raise ValueError("No universe tickers present in equity_prices after returns().")

    rel_mat = pd.concat(rels, axis=1).dropna(how="all")
    basket_rel = rel_mat.mean(axis=1).rename("basket_rel")

    # Denial beta: basket_rel ~ cost_mom
    aligned = pd.concat([basket_rel, cpm], axis=1).dropna()
    beta_cost = rolling_beta(
        y=aligned["basket_rel"],
        x=aligned["cost_mom"],
        window=spec.denial_window_days,
    )
    z_beta_cost = zscore(beta_cost, window=spec.z_window_days)

    # Earnings fragility placeholder (wire later)
    z_ef = pd.Series(index=z_beta_cost.index, data=0.0, name="z_earnings_fragility")

    # Gate denial: only active if cost pressure is positive
    z_cpm_aligned = z_cpm.reindex(z_beta_cost.index)
    denial_active = (z_cpm_aligned > 0).astype(float)

    # Composite score
    score = (
        spec.w_cost * z_cpm_aligned
        + spec.w_denial * (-z_beta_cost * denial_active)
        + spec.w_fragility * z_ef
    ).rename("tariff_regime_score")

    score = score.dropna()
    if score.empty:
        raise ValueError("Score series is empty after alignment. Check data coverage/windows.")

    latest = score.iloc[-1]
    asof = str(score.index[-1].date())

    # Latest components (aligned)
    z_cpm_last = float(z_cpm_aligned.reindex(score.index).iloc[-1])
    beta_last = float(beta_cost.reindex(score.index).iloc[-1])
    z_beta_last = float(z_beta_cost.reindex(score.index).iloc[-1])
    denial_last = float(denial_active.reindex(score.index).iloc[-1])

    inputs = TariffInputs(
        z_cost_pressure=z_cpm_last,
        equity_denial_beta=beta_last,
        z_earnings_fragility=float(z_ef.reindex(score.index).iloc[-1]),
        tariff_regime_score=float(latest),
        is_tariff_regime=bool(latest > spec.threshold),
        components={
            "z_cpm": z_cpm_last,
            "beta_cost": beta_last,
            "z_beta_cost": z_beta_last,
            "denial_active": denial_last,
        },
    )

    return TariffRegimeState(
        asof=asof,
        start_date=start_date,
        basket=basket_name,
        universe=universe,
        benchmark=benchmark,
        inputs=inputs,
        notes=(
            "Tariff regime score = cost pressure momentum (weighted composite of z-scored proxies) "
            "+ equity denial (rolling beta, gated when z_cpm>0). "
            "Earnings fragility placeholder (0.0) until wired."
        ),
    )
