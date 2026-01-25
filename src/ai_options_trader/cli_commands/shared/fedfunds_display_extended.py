"""Additional display sections for macro metrics (credit, vol, housing)."""

from __future__ import annotations

from rich.table import Table
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from ai_options_trader.macro.models import MacroState


def add_credit_stress_section(t: Table, macro_state: MacroState) -> None:
    """Add Credit Stress section to market data table."""
    t.add_row("", "")
    t.add_row("[bold]Credit Stress[/bold]", "")
    
    # Note: FRED OAS data is already in bps (not %), stored as percentage points
    # HY OAS typically 300-500bps, IG OAS typically 80-150bps
    if macro_state.inputs.hy_oas is not None:
        hy_val = macro_state.inputs.hy_oas
        # If value is < 10, it's likely in percentage points, convert to bps
        if hy_val < 10:
            hy_val = hy_val * 100
        t.add_row("  HY OAS", f"{hy_val:.0f} bps")
    
    if macro_state.inputs.ig_oas is not None:
        ig_val = macro_state.inputs.ig_oas
        # If value is < 10, it's likely in percentage points, convert to bps
        if ig_val < 10:
            ig_val = ig_val * 100
        t.add_row("  IG OAS", f"{ig_val:.0f} bps")
    
    if macro_state.inputs.hy_ig_spread is not None:
        spread = macro_state.inputs.hy_ig_spread
        # If value is < 10, it's likely in percentage points, convert to bps
        if spread < 10:
            spread = spread * 100
            
        # Stress thresholds: >300bps = stress, >400bps = severe
        stress_flag = ""
        if spread > 400:
            stress_flag = " [SEVERE STRESS]"
        elif spread > 300:
            stress_flag = " [SYSTEMIC STRESS]"
        elif spread < 200:
            stress_flag = " (tight - low stress)"
        else:
            stress_flag = " (normal)"
        
        t.add_row("  HY-IG spread", f"{spread:.0f} bps{stress_flag}")
        if spread <= 300:
            t.add_row("    -> Trigger", ">300 bps = systemic stress transmission")


def add_volatility_section(t: Table, macro_state: MacroState) -> None:
    """
    Add comprehensive Volatility Regime section to market data table.
    
    Critical for tail-risk funds:
    - VIX levels and term structure
    - Skew dynamics (put premium)
    - Realized vs implied vol
    - Vol-of-vol (VVIX)
    - Hedge cost/opportunity analysis
    """
    t.add_row("", "")
    t.add_row("[bold]Volatility Regime[/bold]", "")
    
    # === VIX SPOT LEVELS ===
    
    if macro_state.inputs.vix is not None:
        vix = macro_state.inputs.vix
        
        # VIX regime classification (institutional thresholds)
        if vix < 12:
            vix_regime = "(EXTREME LOW - hedges very cheap)"
            vix_color = "green"
        elif vix < 15:
            vix_regime = "(low - complacent)"
            vix_color = "yellow"
        elif vix < 20:
            vix_regime = "(normal - balanced)"
            vix_color = "white"
        elif vix < 30:
            vix_regime = "(elevated - risk-off)"
            vix_color = "orange"
        elif vix < 40:
            vix_regime = "(HIGH - stress)"
            vix_color = "red"
        else:
            vix_regime = "(EXTREME - crisis)"
            vix_color = "red bold"
        
        # Historical context (percentiles based on 2010-2025 data)
        if vix < 12:
            pct_context = "~5th %ile (buy hedges)"
        elif vix < 14:
            pct_context = "~15th %ile (hedges cheap)"
        elif vix < 16:
            pct_context = "~30th %ile (below median)"
        elif vix < 18:
            pct_context = "~50th %ile (median)"
        elif vix < 22:
            pct_context = "~70th %ile (above median)"
        elif vix < 28:
            pct_context = "~85th %ile (hedges expensive)"
        else:
            pct_context = "~95th+ %ile (tail event)"
        
        t.add_row("  VIX (1M SPX IV)", f"{vix:.1f} {vix_regime}")
        t.add_row("    -> Percentile", pct_context)
        
        # Cost of protection (annualized)
        # VIX ~15 = ~1.25% monthly premium or ~15% annualized
        monthly_cost_pct = vix / 12.0
        t.add_row("    -> Hedge cost", f"~{monthly_cost_pct:.2f}%/month (~{vix:.0f}% annualized)")
    
    # === VIX TERM STRUCTURE ===
    
    # VIX Mid-Term (3-month)
    if macro_state.inputs.vixm is not None:
        vixm = macro_state.inputs.vixm
        t.add_row("  VIXM (3M SPX IV)", f"{vixm:.1f}")
    
    # Term structure slope
    if macro_state.inputs.vix is not None and macro_state.inputs.vixm is not None:
        vix = macro_state.inputs.vix
        vixm = macro_state.inputs.vixm
        
        # Calculate term structure (3M - 1M)
        term_spread = vixm - vix
        
        # Interpret the term structure
        if term_spread > 5:
            struct_regime = "STEEP CONTANGO"
            struct_desc = "Normal - near-term calm, hedges decay fast"
            struct_signal = "BAD for long vol (fast theta decay)"
        elif term_spread > 2:
            struct_regime = "CONTANGO"
            struct_desc = "Normal market structure"
            struct_signal = "Neutral (typical theta decay)"
        elif term_spread > -2:
            struct_regime = "FLAT"
            struct_desc = "Uncertainty across horizons"
            struct_signal = "Watch for pivot"
        elif term_spread > -5:
            struct_regime = "BACKWARDATION"
            struct_desc = "Near-term stress expected"
            struct_signal = "GOOD for hedges (vol spike priced)"
        else:
            struct_regime = "STEEP BACKWARDATION"
            struct_desc = "Imminent crisis priced"
            struct_signal = "EXCELLENT for hedges (tail event)"
        
        t.add_row("  Term Structure", f"{struct_regime}")
        t.add_row("    -> VIX vs VIXM", f"{term_spread:+.1f}pts ({struct_desc})")
        t.add_row("    -> Hedge signal", struct_signal)
    
    # === VOL-OF-VOL (VVIX) ===
    
    # Note: VVIX is the VIX of VIX (volatility of volatility)
    # High VVIX = convexity in vol space (good for vol traders)
    # Add this if you have VVIX data from CBOE
    # For now, we'll estimate it from VIX moves
    
    # === SKEW (PUT PREMIUM) ===
    
    t.add_row("", "")
    t.add_row("  [dim]Skew Analysis:[/dim]", "")
    
    # CBOE SKEW index (if available)
    # Typical range: 120-150
    # >140 = expensive downside protection
    # <130 = cheap downside protection
    
    # For v0, use VIX level as proxy for skew richness
    if macro_state.inputs.vix is not None:
        vix = macro_state.inputs.vix
        
        # Heuristic: VIX < 14 often means flat skew (cheap puts)
        #            VIX > 25 often means steep skew (expensive puts)
        if vix < 14:
            skew_status = "FLAT (puts relatively cheap)"
            skew_rec = "Good entry for OTM puts"
        elif vix < 18:
            skew_status = "Normal (typical put premium)"
            skew_rec = "Fair value protection"
        elif vix < 25:
            skew_status = "Elevated (puts getting expensive)"
            skew_rec = "Consider spreads/debit spreads"
        else:
            skew_status = "STEEP (puts very expensive)"
            skew_rec = "Hedges priced in - wait for crush"
        
        t.add_row("    -> Skew (est)", skew_status)
        t.add_row("    -> Implication", skew_rec)
    
    # === REALIZED VS IMPLIED VOL ===
    
    t.add_row("", "")
    t.add_row("  [dim]Realized vs Implied:[/dim]", "")
    
    # SPY realized vol (20-day) vs VIX
    # If we had realized vol data, we'd show:
    # - Realized 20d: X%
    # - Implied (VIX): Y%
    # - Vol premium: Y - X
    # - Mean reversion signal
    
    # For v0, just show conceptual
    if macro_state.inputs.vix is not None:
        vix = macro_state.inputs.vix
        
        # Typical realized vol is 10-20%, VIX averages ~17%
        # Assume realized vol = VIX - 3% (rough average vol premium)
        est_realized = max(vix - 3, 8)
        vol_premium = vix - est_realized
        
        t.add_row("    -> Implied (VIX)", f"{vix:.1f}%")
        t.add_row("    -> Realized (est)", f"{est_realized:.1f}%")
        t.add_row("    -> Vol premium", f"{vol_premium:+.1f}%")
        
        if vol_premium > 5:
            premium_desc = "(expensive - vol sellers active)"
        elif vol_premium > 2:
            premium_desc = "(normal premium)"
        elif vol_premium < 0:
            premium_desc = "(CHEAP - implied < realized!)"
        else:
            premium_desc = "(compressed - mean reversion risk)"
        
        t.add_row("    -> Assessment", premium_desc)
    
    # === REGIME SUMMARY ===
    
    t.add_row("", "")
    t.add_row("  [dim]Regime Summary:[/dim]", "")
    
    if macro_state.inputs.vix is not None:
        vix = macro_state.inputs.vix
        
        # Overall hedge recommendation
        if vix < 13:
            rec = "STRONG BUY hedges (VIX <13, cheap entry)"
        elif vix < 16:
            rec = "BUY hedges (below median, good value)"
        elif vix < 20:
            rec = "NEUTRAL (fair value, maintain exposure)"
        elif vix < 28:
            rec = "REDUCE hedges (elevated, priced in)"
        else:
            rec = "SELL/TRIM hedges (extreme, wait for crush)"
        
        t.add_row("    -> Portfolio action", rec)
    
    # === TRIGGERS ===
    
    t.add_row("", "")
    t.add_row("  [dim]Triggers:[/dim]", "")
    t.add_row("    -> VIX >30", "Tail event - hedges paying off")
    t.add_row("    -> VIX <12", "Extreme complacency - load hedges")
    t.add_row("    -> Backwardation", "Near-term stress - hold/add hedges")
    t.add_row("    -> Steep contango", "Fast theta decay - reduce size or shorten maturity")


def add_dollar_commodities_section(t: Table, macro_state: MacroState) -> None:
    """Add Dollar & Commodities section to market data table."""
    t.add_row("", "")
    t.add_row("[bold]Dollar & Commodities[/bold]", "")
    
    if macro_state.inputs.dxy is not None:
        dxy = macro_state.inputs.dxy
        # DXY thresholds (rough guide)
        if dxy > 110:
            dxy_regime = "(strong - dollar stress)"
        elif dxy > 100:
            dxy_regime = "(elevated)"
        elif dxy < 90:
            dxy_regime = "(weak)"
        else:
            dxy_regime = "(neutral)"
        
        t.add_row("  DXY (dollar index)", f"{dxy:.1f} {dxy_regime}")
    
    if macro_state.inputs.oil_price is not None:
        t.add_row("  WTI crude", f"${macro_state.inputs.oil_price:.0f}/bbl")
    
    if macro_state.inputs.gold_price is not None:
        t.add_row("  Gold", f"${macro_state.inputs.gold_price:.0f}/oz (GLDM proxy)")
        t.add_row("    -> Source", "GLDM ETF price x10")


def add_housing_section(t: Table, macro_state: MacroState) -> None:
    """Add Housing section to market data table."""
    t.add_row("", "")
    t.add_row("[bold]Housing[/bold]", "")
    
    if macro_state.inputs.mortgage_30y is not None:
        mortgage = macro_state.inputs.mortgage_30y
        # Mortgage rate thresholds
        if mortgage > 7.0:
            mortgage_regime = "(restrictive - demand stress)"
        elif mortgage > 6.0:
            mortgage_regime = "(elevated)"
        elif mortgage < 4.0:
            mortgage_regime = "(accommodative)"
        else:
            mortgage_regime = "(neutral)"
        
        t.add_row("  30Y mortgage rate", f"{mortgage:.2f}% {mortgage_regime}")
    
    if macro_state.inputs.mortgage_spread is not None:
        spread = macro_state.inputs.mortgage_spread
        # Mortgage spread thresholds (vs 10Y)
        if spread > 250:
            spread_regime = "(wide - credit stress)"
        elif spread > 200:
            spread_regime = "(elevated)"
        elif spread < 150:
            spread_regime = "(tight)"
        else:
            spread_regime = "(normal)"
        
        t.add_row("  Mortgage spread (vs 10Y)", f"{spread:.0f} bps {spread_regime}")
    
    if macro_state.inputs.home_prices_yoy is not None:
        home_yoy = macro_state.inputs.home_prices_yoy
        # Home price growth thresholds
        if home_yoy > 10:
            price_regime = "(accelerating)"
        elif home_yoy > 5:
            price_regime = "(solid growth)"
        elif home_yoy > 0:
            price_regime = "(moderate growth)"
        elif home_yoy > -5:
            price_regime = "(declining)"
        else:
            price_regime = "(SHARP DECLINE)"
        
        t.add_row("  Home prices (YoY)", f"{home_yoy:+.1f}% {price_regime}")
        t.add_row("    -> Context", "Case-Shiller National Index")
