from __future__ import annotations

from ai_options_trader.portfolio.universe import get_universe
from ai_options_trader.strategies.base import SleeveConfig


def _macro_universe(basket_name: str) -> list[str]:
    uni = get_universe(basket_name or "starter")
    return [t.strip().upper() for t in (uni.basket_equity or []) if t and t.strip()]


def _vol_universe(_basket_name: str) -> list[str]:
    # MVP: liquid vol proxies + a couple simple hedges used for de-risking.
    return [
        "VIXY",
        "UVXY",
        "SVXY",
        "VXX",
        "VXZ",
        # Simple hedges / anchors
        "SPY",
        "QQQ",
        "SH",
        "PSQ",
    ]


def _ai_bubble_universe(_basket_name: str) -> list[str]:
    # MVP: QQQ/SMH + a small whitelist of mega-cap/semis (highly optionable).
    return [
        "QQQ",
        "SMH",
        "NVDA",
        "AMD",
        "MSFT",
        "GOOGL",
        "AMZN",
        "META",
        "TSLA",
        "PLTR",
        "AVGO",
    ]


def _housing_universe(_basket_name: str) -> list[str]:
    # Sleeve-specific basket; ignores --basket for now (explicit housing/MBS list).
    uni = get_universe("housing")
    return [t.strip().upper() for t in (uni.basket_equity or []) if t and t.strip()]


def get_sleeve_registry() -> dict[str, SleeveConfig]:
    """
    Canonical sleeve definitions.

    NOTE: This is config-only by design; the scoring pipeline is shared and lives elsewhere.
    """
    macro = SleeveConfig(
        name="macro",
        aliases=("core",),
        risk_budget_pct=0.60,
        universe_fn=_macro_universe,
        # Macro sleeve uses the shared matrix as-is (no weighting).
        feature_weights_by_prefix=None,
    )

    vol = SleeveConfig(
        name="vol",
        aliases=("volatility",),
        risk_budget_pct=0.25,
        universe_fn=_vol_universe,
        feature_weights_by_prefix={
            # Prefer explicit keys when known; prefix weighting is best-effort.
            "vol_": 2.0,
            "vol_pressure_score": 3.0,
            "rates_": 1.25,
            "usd_": 0.75,
            "funding_": 1.0,
        },
    )

    ai_bubble = SleeveConfig(
        name="ai-bubble",
        aliases=("ai_bubble", "tech_duration"),
        risk_budget_pct=0.15,
        universe_fn=_ai_bubble_universe,
        feature_weights_by_prefix={
            "rates_": 2.0,
            "macro_disconnect_score": 1.5,
            "usd_": 0.8,
            "vol_": 1.0,
        },
    )

    housing = SleeveConfig(
        name="housing",
        aliases=("mbs", "mortgage"),
        risk_budget_pct=0.20,
        universe_fn=_housing_universe,
        feature_weights_by_prefix={
            "housing_": 3.0,
            "rates_": 1.5,
            "funding_": 1.0,
            "usd_": 0.5,
        },
    )

    # Return a mapping from *name/alias* -> config (so CLI can accept aliases).
    out: dict[str, SleeveConfig] = {}
    for s in (macro, vol, ai_bubble, housing):
        for nm in s.all_names():
            out[nm] = s
    return out


def resolve_sleeves(names: list[str] | None) -> list[SleeveConfig]:
    reg = get_sleeve_registry()
    if not names:
        return [reg["macro"]]

    out: list[SleeveConfig] = []
    seen = set()
    for n in names:
        key = (n or "").strip().lower()
        if not key:
            continue
        cfg = reg.get(key)
        if cfg is None:
            raise ValueError(f"Unknown sleeve: {n!r}. Known: {sorted(set(reg.keys()))}")
        if cfg.name in seen:
            continue
        seen.add(cfg.name)
        out.append(cfg)
    return out

