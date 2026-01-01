from __future__ import annotations

from ai_options_trader.liquidity.models import LiquidityState
from ai_options_trader.regimes.schema import RegimeVector, add_bool_feature, add_feature


def liquidity_feature_vector(state: LiquidityState) -> RegimeVector:
    f: dict[str, float] = {}
    li = state.inputs

    add_feature(f, "liquidity.ust_10y", li.ust_10y)
    add_feature(f, "liquidity.ust_2y", li.ust_2y)
    add_feature(f, "liquidity.ust_10y_chg_20d_bps", li.ust_10y_chg_20d_bps)
    add_feature(f, "liquidity.ust_10y_chg_60d_bps", li.ust_10y_chg_60d_bps)
    add_feature(f, "liquidity.curve_10y_2y", li.curve_10y_2y)

    add_feature(f, "liquidity.hy_oas", li.hy_oas)
    add_feature(f, "liquidity.ig_oas", li.ig_oas)
    add_feature(f, "liquidity.baa10ym", li.baa10ym)
    add_feature(f, "liquidity.hy_minus_ig_oas", (li.hy_oas - li.ig_oas) if (li.hy_oas is not None and li.ig_oas is not None) else None)

    add_feature(f, "liquidity.fed_funds", li.fed_funds)
    add_feature(f, "liquidity.cpi_yoy", li.cpi_yoy)
    add_feature(f, "liquidity.real_policy_rate", li.real_policy_rate)

    add_feature(f, "liquidity.tga_level", li.tga_level)
    add_feature(f, "liquidity.tga_chg_28d", li.tga_chg_28d)
    add_feature(f, "liquidity.rrp_level", li.rrp_level)
    add_feature(f, "liquidity.rrp_chg_20d", li.rrp_chg_20d)

    add_feature(f, "liquidity.z_hy_oas", li.z_hy_oas)
    add_feature(f, "liquidity.z_ig_oas", li.z_ig_oas)
    add_feature(f, "liquidity.z_ust_10y_chg_20d", li.z_ust_10y_chg_20d)
    add_feature(f, "liquidity.z_hy_minus_ig_oas", li.z_hy_minus_ig_oas)
    add_feature(f, "liquidity.z_curve_10y_2y", li.z_curve_10y_2y)
    add_feature(f, "liquidity.z_real_policy_rate", li.z_real_policy_rate)
    add_feature(f, "liquidity.z_tga_chg_28d", li.z_tga_chg_28d)
    add_feature(f, "liquidity.z_rrp_chg_20d", li.z_rrp_chg_20d)

    add_feature(f, "liquidity.tightness_score", li.liquidity_tightness_score)
    add_bool_feature(f, "liquidity.tight", li.is_liquidity_tight)

    if li.components:
        for k, v in li.components.items():
            add_feature(f, f"liquidity.component.{k}", v)

    return RegimeVector(asof=state.asof, features=f, notes="Liquidity regime (credit + rates) as scalar features.")


