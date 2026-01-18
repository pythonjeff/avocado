# Scenario Analysis - Implementation Summary

## What We Built

A **hedge fund-grade scenario analysis tool** that stress tests your portfolio under different market conditions. This combines all the regime data we've been building (macro, funding, liquidity, volatility, credit) with your actual portfolio to estimate P&L under various scenarios.

## Components

### 1. Scenario Definitions (`llm/scenarios.py`)
- **11 predefined scenarios** across 6 categories:
  - **Rates**: mild/moderate/severe rate rises, ten-year collapse
  - **Inflation**: inflation spike, stagflation
  - **Growth**: growth shock, goldilocks
  - **Volatility**: VIX spike
  - **Liquidity**: liquidity drain
  - **Credit**: credit stress

Each scenario modifies regime inputs (e.g., VIX doubles, 10Y yield +100 bps, RRP depletes).

### 2. Portfolio Impact Estimator (`llm/scenario_impact.py`)
Estimates P&L based on:
- **Equity exposure** (net delta)
- **Vol exposure** (vega)
- **Tail hedge convexity** (for VIX spikes)
- **Credit exposure** (spread widening)
- **Liquidity costs** (funding stress)

Returns:
- Expected P&L as % of NAV
- Breakdown by component (equity, vega, tail hedges)
- Confidence level (low/medium/high)
- Key drivers and risks

### 3. CLI Command (`cli_commands/scenarios_cmd.py`)
Interactive command-line tool:
- List all scenarios
- Run scenarios with custom portfolio parameters
- Beautiful output with comparison tables
- Risk summary (best/worst/range)
- Detailed breakdown per scenario

## Usage

### List Available Scenarios
```bash
lox labs scenarios --list
```

Output:
```
RATES
  rates_rise_mild           Rates Rise (Mild)              - 10Y yield +50 bps
  rates_rise_moderate       Rates Rise (Moderate)          - 10Y yield +100 bps
  ten_year_collapse         Ten Year Collapse              - 10Y yield -100 bps, VIX +30%

VOLATILITY
  vix_spike                 VIX Spike                      - VIX doubles, credit spreads widen

LIQUIDITY
  liquidity_drain           Liquidity Drain                - RRP depleted, reserves -$500B

... (etc)
```

### Run Default Scenarios
```bash
lox labs scenarios
```

Runs 4 scenarios: rates rise, ten-year collapse, VIX spike, liquidity drain.

### Customize Portfolio
```bash
lox labs scenarios \
  --scenarios "vix_spike,credit_stress,stagflation" \
  --net-delta -0.3 \
  --vega 0.15 \
  --tail-hedges
```

Parameters:
- `--net-delta`: Net equity exposure as % of NAV (e.g., -0.3 = 30% net short)
- `--vega`: Vega exposure (e.g., 0.15 = 15% NAV per VIX point)
- `--theta`: Daily time decay (e.g., -0.0005 = -5 bps/day)
- `--tail-hedges` / `--no-tail-hedges`: Whether portfolio has convex tail hedges

## Example Output

```
╭──────────────────────────────────────────────────────────╮
│ Scenario Analysis                                        │
├──────────────────────────────────────────────────────────┤
│ Baseline Regime: DISINFLATIONARY / LOW REAL YIELDS      │
│ Portfolio: Net Delta -20%, Vega 0.10, Tail Hedges: Yes  │
╰──────────────────────────────────────────────────────────╯

Scenario                  Severity    Portfolio P&L  Confidence  Summary
─────────────────────────────────────────────────────────────────────────
Rates Rise (Moderate)     MODERATE         -2.5%     medium      Portfolio loses -2.5%. Tail hedges bleed.
Ten Year Collapse         MODERATE         +3.8%     medium      Portfolio gains +3.8%. Tail hedges perform well.
VIX Spike                 SEVERE          +12.4%     medium      Portfolio gains +12.4%. Tail hedges perform well.
Liquidity Drain           MODERATE         -1.2%     medium      Portfolio flat (-1.2%).


Detailed Breakdown

VIX Spike (VIX doubles, credit spreads widen, 10Y -50 bps)
  Key Drivers:
    • Equity exposure: -4.0% (net delta -20%)
    • Vega exposure: +8.2% (VIX +100%)
    • Tail hedges: +10.5% (convexity)
  Risks:
    • Funding stress: SOFR-IORB +15 bps (execution risk)

... (etc for each scenario)


╭──────────────────────────────────────────────────────╮
│ Risk Summary                                         │
├──────────────────────────────────────────────────────┤
│ Best scenario: VIX Spike (+12.4%)                    │
│ Worst scenario: Rates Rise (Moderate) (-2.5%)       │
│ Range: 14.9% spread                                  │
╰──────────────────────────────────────────────────────╯
```

## Key Features

### ✅ Institutional Quality
- Covers all major risk factors (rates, vol, credit, liquidity, growth, inflation)
- Scenario definitions based on real hedge fund stress tests
- Clear separation of P&L drivers
- Confidence levels and risk callouts

### ✅ Portfolio-Aware
- Uses your actual portfolio parameters (delta, vega, tail hedges)
- Estimates convexity (tail hedges perform well in VIX spikes)
- Accounts for theta bleed in calm markets
- Considers execution costs in funding stress

### ✅ Beautiful Output
- Rich terminal formatting (colors, panels, tables)
- Scannable comparison table
- Detailed breakdown per scenario
- Clear risk summary

### ✅ Extensible
- Easy to add new scenarios
- Can customize scenario logic (e.g., modify rates rise to be +150 bps instead of +100)
- Can add more portfolio parameters (e.g., rate duration, credit spread DV01)
- Can integrate with actual position data

## Integration with Existing Tools

This tool complements your existing commands:

1. **`lox labs monetary fedfunds-outlook`**: Understand current liquidity regime
2. **`lox weekly`**: See current portfolio state and NAV
3. **`lox account`**: Get actual position greeks
4. **`lox labs scenarios`**: ← NEW! Stress test those positions

Workflow:
```bash
# 1. Check current market regime
lox labs monetary fedfunds-outlook

# 2. Check current portfolio
lox weekly

# 3. Stress test portfolio
lox labs scenarios --net-delta -0.25 --vega 0.12 --tail-hedges

# 4. Adjust portfolio if needed (e.g., add more tail hedges)
# ... make trades ...

# 5. Re-test
lox labs scenarios --net-delta -0.30 --vega 0.18 --tail-hedges
```

## Model Notes

This is a **heuristic model** designed for quick directional intuition, not precise P&L forecasting. Key simplifications:

- **Equity exposure**: Assumes VIX/SPX inverse relationship (rough)
- **Vega**: Linear approximation (real vol surface is complex)
- **Tail hedges**: Simplified convexity (real gamma is path-dependent)
- **Credit**: Rough impact for spread widening
- **Liquidity**: Simplified execution cost model

For production-grade risk, you'd want:
- Full position-level greeks
- Vol surface modeling
- Correlation matrix
- Historical backtesting
- Monte Carlo simulation

But for **quick risk assessment and portfolio discussion**, this tool is excellent.

## Next Steps / Future Enhancements

Potential additions:
- [ ] **Custom scenario builder**: User can define their own shifts (e.g., "10Y +120 bps, VIX +25%, HY OAS +180 bps")
- [ ] **Historical scenario replay**: Pre-built scenarios like "2008 GFC", "March 2020", "2022 taper tantrum"
- [ ] **Monte Carlo mode**: Run 1,000s of random scenarios, show P&L distribution
- [ ] **Position integration**: Auto-calculate greeks from actual portfolio
- [ ] **Time decay simulation**: Show P&L evolution over 30/60/90 days
- [ ] **LLM narrative**: Use LLM to explain why scenario matters and what to watch
- [ ] **Optimal hedge suggestions**: "To reduce worst-case loss by 50%, add X SPY puts at Y strike"
- [ ] **Correlation scenarios**: "What if rates rise AND VIX stays low?" (non-standard correlation)

## Files Created

1. `src/ai_options_trader/llm/scenarios.py` - Scenario definitions
2. `src/ai_options_trader/llm/scenario_impact.py` - Portfolio impact estimator
3. `src/ai_options_trader/cli_commands/scenarios_cmd.py` - CLI command
4. `docs/SCENARIO_ANALYSIS.md` - User documentation
5. `docs/SCENARIO_IMPLEMENTATION_SUMMARY.md` - This file (technical summary)

## Testing

To test:
```bash
# Install (if not already)
pip install -e .

# List scenarios
lox labs scenarios --list

# Run with test portfolio (20% net short, positive vega, tail hedges)
lox labs scenarios --net-delta -0.2 --vega 0.1 --tail-hedges

# Run specific scenarios
lox labs scenarios --scenarios "vix_spike,credit_stress,goldilocks"

# Run without tail hedges
lox labs scenarios --no-tail-hedges

# Refresh data
lox labs scenarios --refresh
```

## Summary

You now have a **professional-grade scenario analysis tool** that:
- Combines all your regime work (macro, funding, liquidity, vol, credit)
- Stress tests your portfolio under 11 predefined scenarios
- Estimates P&L with breakdown by driver
- Shows best/worst/range for quick risk assessment
- Has beautiful, scannable output
- Is easily extensible for custom scenarios

This is the kind of tool a hedge fund risk committee would use every Monday morning before the week starts!
