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
    """Add Volatility Regime section to market data table."""
    t.add_row("", "")
    t.add_row("[bold]Volatility Regime[/bold]", "")
    
    if macro_state.inputs.vix is not None:
        vix = macro_state.inputs.vix
        # VIX regime classification
        if vix < 15:
            vix_regime = "(low - complacent)"
        elif vix < 20:
            vix_regime = "(normal)"
        elif vix < 30:
            vix_regime = "(elevated)"
        else:
            vix_regime = "(HIGH - stress)"
        
        # Historical context (rough percentiles)
        if vix < 13:
            pct_context = "~10th %ile (hedges cheap)"
        elif vix < 16:
            pct_context = "~25th %ile"
        elif vix < 20:
            pct_context = "~50th %ile (median)"
        elif vix < 25:
            pct_context = "~75th %ile"
        else:
            pct_context = "~90th+ %ile (hedges expensive)"
        
        t.add_row("  VIX (1-month)", f"{vix:.1f} {vix_regime}")
        t.add_row("    -> Context", pct_context)
    
    # VIX Mid-Term (3-month)
    if macro_state.inputs.vixm is not None:
        vixm = macro_state.inputs.vixm
        t.add_row("  VIXM (3-month)", f"{vixm:.1f}")
    
    # VIX Term Structure
    if macro_state.inputs.vix_term_structure is not None:
        term_struct = macro_state.inputs.vix_term_structure
        
        # Interpret the term structure
        if term_struct < -3:
            struct_regime = "STEEP CONTANGO"
            struct_desc = "Normal market - near-term calm, hedges decay fast"
        elif term_struct < -1:
            struct_regime = "CONTANGO"
            struct_desc = "Orderly market - hedges have time decay"
        elif term_struct < 1:
            struct_regime = "FLAT"
            struct_desc = "Neutral - modest time decay"
        elif term_struct < 3:
            struct_regime = "BACKWARDATION"
            struct_desc = "Near-term stress priced - buy 3mo+ for value"
        else:
            struct_regime = "STEEP BACKWARDATION"
            struct_desc = "Acute stress - near-term hedges expensive, consider selling 1mo"
        
        t.add_row("  VIX term structure", f"{term_struct:+.1f} ({struct_regime})")
        t.add_row("    -> Implication", struct_desc)
    
    # Hedge timing recommendation based on VIX and term structure
    if macro_state.inputs.vix is not None and macro_state.inputs.vix_term_structure is not None:
        vix = macro_state.inputs.vix
        term_struct = macro_state.inputs.vix_term_structure
        
        # Decision matrix for hedge timing
        if vix < 16 and term_struct < -1:
            timing = "FAVORABLE: Add 3-6mo hedges (cheap vol + time decay manageable)"
        elif vix < 16 and term_struct > 2:
            timing = "MIXED: Vol cheap but acute stress priced (add 6mo+)"
        elif vix > 25 and term_struct > 2:
            timing = "UNFAVORABLE: Hedges expensive + acute stress priced (hold/reduce)"
        elif vix > 25 and term_struct < -1:
            timing = "ANOMALY: High VIX but contango (market expects mean reversion)"
        else:
            timing = "NEUTRAL: Monitor for better entry"
        
        t.add_row("    -> Hedge timing", timing)
    
    # Note: MOVE index not available on FRED, would show here if we had it
    # if macro_state.inputs.move is not None:
    #     t.add_row("  MOVE (bond vol)", f"{macro_state.inputs.move:.0f}")


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
