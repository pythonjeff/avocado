"""
Example: Using the scenario analysis tool to stress test a tail-risk hedging portfolio.
"""

# Portfolio setup:
# - 20% net short equity (defensive positioning)
# - Positive vega (long volatility via tail hedges)
# - Has convex tail hedges (far OTM puts)
# - Daily theta bleed of ~5 bps

# Command:
"""
lox labs scenarios \
  --scenarios "rates_rise_moderate,ten_year_collapse,vix_spike,liquidity_drain,stagflation,goldilocks" \
  --net-delta -0.20 \
  --vega 0.10 \
  --theta -0.0005 \
  --tail-hedges
"""

# Expected output (example):
"""
╭──────────────────────────────────────────────────────────╮
│ Scenario Analysis                                        │
├──────────────────────────────────────────────────────────┤
│ Baseline Regime: DISINFLATIONARY / LOW REAL YIELDS      │
│ Portfolio: Net Delta -20%, Vega 0.10, Tail Hedges: Yes  │
╰──────────────────────────────────────────────────────────╯

Scenario                  Severity    Portfolio P&L  Confidence  Summary
─────────────────────────────────────────────────────────────────────────────────────────
Rates Rise (Moderate)     MODERATE         -2.3%     medium      Portfolio loses -2.3%. Tail hedges bleed.
Ten Year Collapse         MODERATE         +4.2%     medium      Portfolio gains +4.2%. Tail hedges perform well.
VIX Spike                 SEVERE          +13.8%     medium      Portfolio gains +13.8%. Tail hedges perform well.
Liquidity Drain           MODERATE         -0.8%     medium      Portfolio flat (-0.8%).
Stagflation               SEVERE           -1.5%     medium      Portfolio loses -1.5%.
Goldilocks                MILD             -3.1%     high        Portfolio loses -3.1%. Tail hedges bleed.


Detailed Breakdown

Rates Rise (Moderate) (10Y yield +100 bps, 2Y +100 bps)
  Key Drivers:
    • Tail hedges: -2.0% (theta bleed)
  Risks:

Ten Year Collapse (10Y yield -100 bps, curve steepens, VIX +30%)
  Key Drivers:
    • Vega exposure: +3.0% (VIX +30%)
    • Tail hedges: +1.5% (convexity)
  Risks:

VIX Spike (VIX doubles, credit spreads widen, 10Y -50 bps)
  Key Drivers:
    • Equity exposure: -4.0% (net delta -20%)
    • Vega exposure: +8.0% (VIX +100%)
    • Tail hedges: +10.0% (convexity)
  Risks:
    • Funding stress: SOFR-IORB +15 bps (execution risk)

Liquidity Drain (RRP depleted, reserves -$500B, TGA +$200B, funding spreads +15 bps)
  Key Drivers:
  Risks:
    • Funding stress: SOFR-IORB +15 bps (execution risk)

Stagflation (CPI +150 bps, payrolls -0.5% ann, rates stay elevated)
  Key Drivers:
    • Vega exposure: +0.8% (VIX +11%)
  Risks:

Goldilocks (CPI 2.2%, payrolls +1.5% ann, 10Y -30 bps, VIX 14)
  Key Drivers:
    • Tail hedges: -2.5% (theta bleed)
  Risks:


╭──────────────────────────────────────────────────────╮
│ Risk Summary                                         │
├──────────────────────────────────────────────────────┤
│ Best scenario: VIX Spike (+13.8%)                    │
│ Worst scenario: Goldilocks (-3.1%)                   │
│ Range: 16.9% spread                                  │
╰──────────────────────────────────────────────────────╯
"""

# Key insights from this output:
# 1. Portfolio is well-positioned for stress (VIX spike = +13.8%)
# 2. Vulnerable to calm markets (goldilocks = -3.1% due to theta bleed)
# 3. Range is 16.9% - substantial but expected for tail-risk book
# 4. Liquidity drain is relatively neutral (-0.8%) - good defensive positioning

# Potential actions:
# - If concerned about theta bleed, consider reducing OTM puts
# - If worried about goldilocks, add some upside exposure or reduce hedge size
# - Monitor liquidity regime (use `lox labs monetary fedfunds-outlook`)
# - Re-run scenarios monthly or when regime changes
