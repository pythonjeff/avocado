# Scenario Analysis Tool

## Overview

The **scenario analysis** tool stress-tests your portfolio under different market conditions. It combines:
1. **All regime data** (macro, funding, liquidity, volatility, credit, etc.)
2. **Your current portfolio** (net delta, vega, theta, tail hedges)
3. **Predefined scenarios** (e.g., "rates rise", "VIX spike", "liquidity drain")

...to estimate P&L impact and identify vulnerabilities.

## Quick Start

### List All Available Scenarios

```bash
lox labs scenarios --list
```

This shows all predefined scenarios organized by category:
- **Rates**: rising rates, ten-year collapse
- **Inflation**: inflation spike, stagflation
- **Growth**: growth shock, goldilocks
- **Volatility**: VIX spike
- **Liquidity**: liquidity drain
- **Credit**: credit stress

### Run Default Scenarios

```bash
lox labs scenarios
```

Runs 4 default scenarios:
- Rates rise (moderate)
- Ten year collapse
- VIX spike
- Liquidity drain

### Custom Scenarios

```bash
lox labs scenarios --scenarios "vix_spike,credit_stress,stagflation,goldilocks"
```

### Customize Portfolio Parameters

```bash
lox labs scenarios \
  --net-delta -0.3 \
  --vega 0.15 \
  --theta -0.001 \
  --tail-hedges
```

Parameters:
- `--net-delta`: Net equity exposure as % of NAV (e.g., `-0.2` = 20% net short)
- `--vega`: Vega exposure (normalized to NAV, e.g., `0.1` = 10% NAV per VIX point)
- `--theta`: Daily time decay as % of NAV (e.g., `-0.0005` = -5 bps/day)
- `--tail-hedges` / `--no-tail-hedges`: Whether portfolio has convex tail hedges

### Refresh Data

```bash
lox labs scenarios --refresh
```

Forces refresh of all market data (ignores cache).

## Output

### Scenario Comparison Table

```
╭────────────────────────────────────────────────────────────────╮
│ Scenario Analysis                                              │
├────────────────────────────────────────────────────────────────┤
│ Baseline Regime: DISINFLATIONARY / LOW REAL YIELDS            │
│ Portfolio: Net Delta -20%, Vega 0.10, Tail Hedges: Yes        │
╰────────────────────────────────────────────────────────────────╯

Scenario                       Severity    Portfolio P&L  Confidence  Summary
──────────────────────────────────────────────────────────────────────────────
Rates Rise (Moderate)          MODERATE         -2.5%     medium      Portfolio loses -2.5%. Tail hedges bleed.
Ten Year Collapse              MODERATE         +3.8%     medium      Portfolio gains +3.8%. Tail hedges perform well.
VIX Spike                      SEVERE          +12.4%     medium      Portfolio gains +12.4%. Tail hedges perform well.
Liquidity Drain                MODERATE         -1.2%     medium      Portfolio flat (-1.2%).
```

### Detailed Breakdown

For each scenario, you get:
- **Key Drivers**: What's driving the P&L (equity, vega, tail hedges, credit, etc.)
- **Risks**: Execution risks, model uncertainty, etc.

Example:
```
VIX Spike (VIX doubles, credit spreads widen, 10Y -50 bps)
  Key Drivers:
    • Equity exposure: -4.0% (net delta -20%)
    • Vega exposure: +8.2% (VIX +100%)
    • Tail hedges: +10.5% (convexity)
  Risks:
    • Funding stress: SOFR-IORB +15 bps (execution risk)
```

### Risk Summary

```
╭─────────────────────────────────────────────────────────╮
│ Risk Summary                                            │
├─────────────────────────────────────────────────────────┤
│ Best scenario: VIX Spike (+12.4%)                       │
│ Worst scenario: Rates Rise (Moderate) (-2.5%)          │
│ Range: 14.9% spread                                     │
╰─────────────────────────────────────────────────────────╯
```

## Available Scenarios

### Rates

- **rates_rise_mild**: 10Y +50 bps, 2Y +50 bps
- **rates_rise_moderate**: 10Y +100 bps, 2Y +100 bps (default)
- **rates_rise_severe**: 10Y +200 bps, 2Y +200 bps
- **ten_year_collapse**: 10Y -100 bps, curve steepens, VIX +30% (default)

### Inflation

- **inflation_spike**: CPI +150 bps YoY, momentum accelerates, breakevens +50 bps
- **stagflation**: High inflation + weak growth (CPI +150 bps, payrolls -0.5%)

### Growth

- **growth_shock**: Payrolls -2% ann, unemployment +150 bps, 10Y -75 bps, VIX +50%
- **goldilocks**: CPI 2.2%, payrolls +1.5% ann, 10Y -30 bps, VIX 14

### Volatility

- **vix_spike**: VIX doubles, credit spreads widen, 10Y -50 bps (default)

### Liquidity

- **liquidity_drain**: RRP depleted, reserves -$500B, TGA +$200B, funding spreads +15 bps (default)

### Credit

- **credit_stress**: HY OAS +300 bps, IG OAS +100 bps, VIX +80%

## Model Notes

This is a **heuristic model** for quick stress testing. Key assumptions:

1. **Equity exposure**: Assumes VIX/SPX inverse relationship (rough: VIX up 50% → SPX down ~10%)
2. **Vega**: Simplified linear relationship (1 unit vega = 1% NAV per 10 VIX points)
3. **Tail hedges**: Assume convexity kicks in when VIX > +30% (very rough)
4. **Credit**: Simplified impact for severe spread widening
5. **Liquidity costs**: Execution slippage in funding stress

### For Production Use

To upgrade this to a production-grade risk system, you'd want:
- Full position-level greeks (delta, gamma, vega, theta, rho)
- Vol surface modeling (not just VIX level)
- Correlation matrix (equity-rates-vol-credit)
- Historical scenario backtesting
- Monte Carlo simulation
- Execution cost models
- Counterparty risk

But this tool is great for **quick directional intuition** and **identifying macro vulnerabilities**.

## Example Workflow

1. **List scenarios**: `lox labs scenarios --list`
2. **Run baseline**: `lox labs scenarios`
3. **Identify worst case**: Look at "Worst scenario" in Risk Summary
4. **Deep dive**: Read detailed breakdown for that scenario
5. **Adjust portfolio**: Consider hedges or position sizing changes
6. **Re-test**: Run scenarios again with adjusted parameters

## Integration with Other Commands

- Use `lox labs monetary fedfunds-outlook` to understand current liquidity regime
- Use `lox weekly` to see current portfolio state and NAV
- Use `lox account` to get actual position greeks (if available)
- Use `lox labs scenarios` to stress test those positions

## Tips

- **Net delta**: If you're running a tail-risk hedging book, typical net delta is -10% to -30%
- **Vega**: If you're long volatility (tail hedges), typical vega is 0.05 to 0.20
- **Tail hedges**: Set `--tail-hedges` if you have far OTM puts or other convex hedges
- **Refresh**: Use `--refresh` if you want the most current market data (slower)

## Future Enhancements

Potential additions:
- [ ] Custom scenario builder (user can define their own shifts)
- [ ] Historical scenario replay (e.g., "2008 GFC", "March 2020 COVID crash")
- [ ] Monte Carlo mode (run 1,000s of random scenarios)
- [ ] Integration with actual portfolio positions (auto-calculate greeks)
- [ ] Time decay simulation (show P&L over 30/60/90 days)
- [ ] LLM narrative generation (explain why this scenario matters)
- [ ] Optimal hedge recommendations (what to add to reduce worst-case loss)
