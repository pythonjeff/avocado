"""LLM-powered Fed funds outlook."""

from __future__ import annotations

import json

from openai import OpenAI

from ai_options_trader.config import Settings


SYSTEM_PROMPT = """You are a senior macro strategist with a PhD in monetary economics, analyzing liquidity transmission for an institutional tail-risk fund.

Your analysis must be:
1. **Mechanistic**: Specify transmission channels (reserves → funding → dealer capacity → risk premium)
2. **Forward-looking**: Provide 1-month and 3-month conditional forecasts
3. **Quantitative**: Cite specific thresholds, probabilities, and expected magnitudes
4. **Actionable**: Direct implications for hedge sizing and strike selection

Structure (hedge fund research memo style):

**I. Liquidity State Assessment** (2-3 sentences)
Characterize current buffer status (reserves, RRP, TGA flows). Distinguish latent stress (buffers depleted, rates stable) from realized stress (spreads widening). State the marginal source of liquidity and its runway.

**II. Baseline Forecast (60% probability, 1-3 month horizon)** (2-3 sentences)
Most likely path for funding conditions given current QT pace, TGA trajectory, and reserve levels. Expected SOFR-IORB range. Implications for risk asset liquidity premium.

**III. Tail Scenario (20-30% probability)** (2-3 sentences)
Specific trigger (e.g., "TGA rises $250B in 4 weeks while reserves fall to $2.6T"). Expected funding stress magnitude (SOFR-IORB >15bps). Transmission to equities (vol spike to 25-30, credit spreads widen 50bps+).

**IV. Portfolio Positioning** (2-3 sentences)
Recommended hedge sizing (size up/down/hold). Optimal structures (3-6mo puts vs 1-2mo, strike selection). Expected payoff if tail scenario materializes.

**V. Key Catalysts (Next 30 Days)** (2 sentences)
One data release or event that would confirm/invalidate the forecast. Specific threshold to watch.

Use Fed operating framework terminology. Ground every forecast in the data provided. Avoid generic commentary - every sentence should be actionable."""


def llm_fedfunds_outlook(
    *,
    settings: Settings,
    regimes: dict,
    model: str | None = None,
    temperature: float = 0.2,
) -> str:
    """
    Ask LLM for a Fed funds outlook given current macro/liquidity regimes.
    """
    if not settings.openai_api_key:
        return "OPENAI_API_KEY not set. Run with --no-llm or set OPENAI_API_KEY."

    macro_state = regimes["macro_state"]
    macro_regime = regimes["macro_regime"]
    liq_state = regimes["liquidity_state"]
    
    # Calculate key liquidity metrics from liq_state.inputs
    on_rrp_b = (liq_state.inputs.on_rrp_usd_bn or 0) / 1000  # Already in millions, convert to billions
    reserves_b = (liq_state.inputs.bank_reserves_usd_bn or 0) / 1000
    tga_b = (liq_state.inputs.tga_usd_bn or 0) / 1000
    net_liq_b = reserves_b + on_rrp_b - tga_b
    
    reserves_d13w_b = (liq_state.inputs.bank_reserves_chg_13w or 0) / 1000
    on_rrp_d13w_b = (liq_state.inputs.on_rrp_chg_13w or 0) / 1000
    tga_d4w_b = (liq_state.inputs.tga_chg_4w or 0) / 1000
    tga_d1w_b = tga_d4w_b / 4  # Estimate 1w from 4w
    fed_assets_d13w_b = (liq_state.inputs.fed_assets_chg_13w or 0) / 1000
    fed_assets_total_t = (liq_state.inputs.fed_assets_usd_bn or 0) / 1_000_000  # Millions to trillions
    
    # Liquidity buffer status
    if on_rrp_b < 50:
        buffer_status = "RRP DEPLETED (<$50B) — reserves are the marginal buffer"
    elif on_rrp_b < 200:
        buffer_status = "RRP buffer thinning ($50-200B) — transition zone"
    else:
        buffer_status = "RRP buffer ample (>$200B) — absorbing drains"
    
    # Funding stress indicators
    sofr_iorb_spread = liq_state.inputs.spread_corridor_bps or 0
    if sofr_iorb_spread > 10:
        funding_status = "STRESSED (SOFR-IORB widened >10bps) — actual market stress"
    elif sofr_iorb_spread > 5:
        funding_status = "TIGHTENING (SOFR-IORB 5-10bps) — early warning"
    else:
        funding_status = "ORDERLY (SOFR-IORB <5bps) — funding stable"
    
    # RRP floor and IORB
    rrp_floor = (liq_state.inputs.effr or 0) - 0.25 if liq_state.inputs.effr else 0
    iorb = liq_state.inputs.iorb or 0

    user_prompt = f"""INSTITUTIONAL LIQUIDITY ASSESSMENT — Federal Reserve Operating Environment

══════════════════════════════════════════════════════════════════
SECTION 1: RESERVE DYNAMICS & BUFFER STATUS
══════════════════════════════════════════════════════════════════

System Liquidity (Fed liabilities available to private sector):
  • Bank reserves:        ${reserves_b:.0f}B  (Δ13w: ${reserves_d13w_b:+.0f}B)
  • ON RRP facility:      ${on_rrp_b:.0f}B    (Δ13w: ${on_rrp_d13w_b:+.0f}B)
  • Net Liquidity Proxy:  ${net_liq_b:.0f}B   (Reserves + RRP - TGA)

Buffer Assessment: {buffer_status}

Quantitative Tightening:
  • Fed balance sheet:    ${fed_assets_total_t:.2f}T (down from $9.0T peak Apr '22)
  • QT pace:             ${fed_assets_d13w_b:+.0f}B/13w (${(fed_assets_d13w_b/13)*52:+.0f}B/yr annualized)

Treasury General Account (liquidity drain/source):
  • TGA level:           ${tga_b:.0f}B
  • Δ1w (estimated):     ${tga_d1w_b:+.0f}B
  • Δ4w:                 ${tga_d4w_b:+.0f}B
  • Direction:           {"DRAIN (Treasury building cash)" if tga_d4w_b > 10 else ("INJECTION (Treasury spending)" if tga_d4w_b < -10 else "NEUTRAL")}

══════════════════════════════════════════════════════════════════
SECTION 2: OVERNIGHT FUNDING MARKETS
══════════════════════════════════════════════════════════════════

Policy Corridor (administered rates):
  • RRP floor:           {rrp_floor:.2f}%
  • IORB ceiling:        {iorb:.2f}%

Market Rates & Spreads:
  • EFFR:                {liq_state.inputs.effr:.2f}%
  • SOFR:                {liq_state.inputs.sofr:.2f}%
  • SOFR-IORB:           {sofr_iorb_spread:.1f} bps
  • TGCR-IORB:           {(liq_state.inputs.tgcr - iorb) if liq_state.inputs.tgcr and iorb else 0:.1f} bps

Funding Status: {funding_status}

══════════════════════════════════════════════════════════════════
SECTION 3: MACRO & MARKET CONTEXT
══════════════════════════════════════════════════════════════════

Growth & Inflation:
  • CPI (YoY):           {macro_state.inputs.cpi_yoy:.2f}% | 3m momentum: {macro_state.inputs.cpi_3m_annualized:.2f}%
  • Median CPI:          {macro_state.inputs.median_cpi_yoy:.2f}% (stickiness proxy)
  • 5y5y breakeven:      {macro_state.inputs.breakeven_5y5y:.2f}% (market expectations)
  • Payrolls (3m ann):   {macro_state.inputs.payrolls_3m_annualized:.2f}%
  • Unemployment:        {macro_state.inputs.unemployment_rate:.1f}%

Policy Stance:
  • 2Y yield:            {macro_state.inputs.ust_2y:.2f}% (market-implied Fed path)
  • 10Y real yield:      {macro_state.inputs.real_yield_proxy_10y:.2f}% (policy restrictiveness)
  • Curve (2s10s):       {macro_state.inputs.curve_2s10s:.0f} bps {"[INVERTED]" if macro_state.inputs.curve_2s10s < 0 else ""}

Credit Stress:
  • HY OAS:              {macro_state.inputs.hy_oas:.0f} bps (high yield spread)
  • IG OAS:              {macro_state.inputs.ig_oas:.0f} bps (investment grade)
  • HY-IG spread:        {macro_state.inputs.hy_ig_spread:.0f} bps {"[STRESS >300]" if macro_state.inputs.hy_ig_spread and macro_state.inputs.hy_ig_spread > 300 else ""}

Volatility & Risk Appetite:
  • VIX:                 {macro_state.inputs.vix:.1f} {"(cheap hedges)" if macro_state.inputs.vix and macro_state.inputs.vix < 16 else ("(expensive hedges)" if macro_state.inputs.vix and macro_state.inputs.vix > 25 else "(neutral)")}

══════════════════════════════════════════════════════════════════
YOUR TASK: INSTITUTIONAL LIQUIDITY FORECAST
══════════════════════════════════════════════════════════════════

Produce a research-grade liquidity transmission analysis addressing:

1. **Current State**: Is stress latent or realized? What's the marginal buffer?

2. **Baseline Forecast (60% prob, 1-3mo)**: Most likely path for funding conditions, SOFR-IORB range, risk asset impact

3. **Tail Scenario (20-30% prob)**: Specific trigger, funding stress magnitude, equity/credit impact

4. **Portfolio Positioning**: Hedge sizing recommendation, optimal structures (tenor/strike), expected payoff

5. **Key Catalyst**: One data point/threshold to watch (next 30 days)

Be quantitative. Every forecast needs a probability, magnitude, and timeframe. This is for portfolio allocation decisions."""

    chosen_model = model or settings.openai_model
    client = OpenAI(api_key=settings.openai_api_key)
    
    completion = client.chat.completions.create(
        model=chosen_model,
        messages=[
            {"role": "system", "content": SYSTEM_PROMPT},
            {"role": "user", "content": user_prompt},
        ],
        temperature=temperature,
    )
    
    return completion.choices[0].message.content or "(LLM returned empty response)"

