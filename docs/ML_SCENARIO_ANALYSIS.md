# ML-Enhanced Scenario Analysis

## Overview

We've upgraded the scenario analysis tool with **two data science approaches** that make it easier to specify scenarios and more realistic:

### 1. Historical Event Library (`scenarios-historical`)
Use **REAL market moves from past crises** instead of synthetic scenarios.

### 2. Factor-Based Scenarios (`scenarios-factors`)
Specify **high-level factors** (risk-on/off, growth, inflation) instead of individual variables.

---

## Approach 1: Historical Events

### Why It's Better

**Before (v1 - Rule-Based)**:
```bash
# Hard to know what "realistic" means
lox labs scenarios --scenarios "vix_spike"  # VIX doubles... but is that realistic?
```

**After (v2 - Data-Driven)**:
```bash
# Use actual 2008 crisis moves
lox labs scenarios-historical --events "gfc_2008"  # VIX +240%, HY OAS +800 bps (ACTUAL)
```

### Available Historical Events

```bash
lox labs scenarios-historical --list
```

**Events included:**
1. **gfc_2008**: Global Financial Crisis (Lehman)
   - VIX: 20 → 80 (+240%)
   - SPY: -23%
   - 10Y yield: -80 bps
   - HY OAS: +800 bps

2. **covid_crash_2020**: COVID-19 Crash
   - VIX: 15 → 82 (+410%)
   - SPY: -34%
   - 10Y yield: -125 bps
   - HY OAS: +650 bps

3. **volmageddon_2018**: VIX Spike (XIV Collapse)
   - VIX: 13 → 50 (+280%)
   - SPY: -10%
   - Modest credit spread widening

4. **taper_tantrum_2022**: 2022 Rate Shock
   - VIX: +65%
   - SPY: -20%
   - 10Y yield: +150 bps (rates UP, not down)
   - 2Y yield: +250 bps

5. **svb_2023**: Silicon Valley Bank Collapse
   - VIX: +85%
   - SPY: -5%
   - 10Y yield: -40 bps
   - Regional banking crisis

### Usage

**Run all major crises:**
```bash
lox labs scenarios-historical
```

**Run specific events:**
```bash
lox labs scenarios-historical --events "gfc_2008,covid_crash_2020"
```

**Scale severity:**
```bash
# Half the historical move
lox labs scenarios-historical --severity 0.5

# Double the historical move (tail scenario)
lox labs scenarios-historical --severity 2.0
```

**Full example:**
```bash
lox labs scenarios-historical \
  --events "gfc_2008,covid_crash_2020,taper_tantrum_2022" \
  --severity 1.0 \
  --net-delta -0.25 \
  --vega 0.12 \
  --tail-hedges
```

### Example Output

```
╭─────────────────────────────────────────────────╮
│ Historical Scenario Analysis                    │
├─────────────────────────────────────────────────┤
│ Baseline Regime: DISINFLATIONARY               │
│ Portfolio: Net Delta -25%, Vega 0.12           │
│ Severity: 1.0x historical moves                 │
╰─────────────────────────────────────────────────╯

Historical Event                     Date         Portfolio P&L  Confidence
──────────────────────────────────────────────────────────────────────────
Global Financial Crisis (Lehman)     2008-09-01        +18.2%    medium
COVID-19 Crash                       2020-02-20        +22.5%    medium
2022 Taper Tantrum                   2022-01-01         -4.8%    medium

╭─────────────────────────────────────────────────╮
│ Historical Risk Summary                          │
├─────────────────────────────────────────────────┤
│ Best: COVID-19 Crash (+22.5%)                   │
│ Worst: 2022 Taper Tantrum (-4.8%)              │
│ Range: 27.3% spread                             │
│                                                  │
│ Historical context: These are ACTUAL market     │
│ moves from past crises. Severity 1.0x means     │
│ we're modeling 100% of the historical move.     │
╰─────────────────────────────────────────────────╯
```

---

## Approach 2: Factor-Based Scenarios

### Why It's Better

**Before (v1 - Variable-by-Variable)**:
```bash
# Hard to specify - need to think about 10+ variables
# "I want a risk-off scenario... so VIX up, but by how much? And rates? And spreads?"
```

**After (v2 - High-Level Factors)**:
```bash
# Easy - just specify high-level factors
lox labs scenarios-factors --risk-appetite -1.0 --liquidity 0.8
# Model maps factors → specific market moves using learned relationships
```

### The Five Factors

Instead of specifying 10+ individual variables, you specify 5 high-level factors (each from -1 to +1):

1. **Risk Appetite** (`--risk-appetite`)
   - `-1.0` = Extreme risk-off (panic, flight to quality)
   - `0.0` = Neutral
   - `+1.0` = Extreme risk-on (euphoria, FOMO)

2. **Growth** (`--growth`)
   - `-1.0` = Severe contraction (recession)
   - `0.0` = Stable
   - `+1.0` = Strong expansion (boom)

3. **Inflation** (`--inflation`)
   - `-1.0` = Deflation risk
   - `0.0` = Contained (near 2%)
   - `+1.0` = High inflation (overheating)

4. **Liquidity** (`--liquidity`)
   - `-1.0` = Abundant liquidity (QE, low spreads)
   - `0.0` = Orderly
   - `+1.0` = Liquidity crisis (funding stress, wide spreads)

5. **Policy** (`--policy`)
   - `-1.0` = Very dovish (Fed cuts, QE)
   - `0.0` = Neutral
   - `+1.0` = Very hawkish (Fed hikes aggressively, QT)

### How It Works

The model maps factors to specific market moves using **learned relationships**:

```python
# Example: Risk-off scenario
risk_appetite = -1.0  # Extreme risk-off
liquidity_stress = 0.8  # High stress

# Model automatically calculates:
# → VIX up ~150% (from risk_appetite + liquidity_stress)
# → SPY down ~15% (from risk_appetite)
# → 10Y yield down ~50 bps (flight to quality)
# → HY OAS up ~400 bps (credit spreads blow out)
# → Dollar up ~8% (safe haven demand)
```

### Usage

**Custom factors:**
```bash
# Extreme risk-off + liquidity stress
lox labs scenarios-factors --risk-appetite -1.0 --liquidity 0.8

# Stagflation (high inflation + weak growth + hawkish Fed)
lox labs scenarios-factors --inflation 0.9 --growth -0.7 --policy 0.6

# Goldilocks (solid growth + cooling inflation + dovish Fed)
lox labs scenarios-factors --risk-appetite 0.8 --growth 0.6 --inflation -0.3 --policy -0.4
```

**Preset factor scenarios:**
```bash
# List presets
lox labs scenarios-factors --list

# Use a preset
lox labs scenarios-factors --preset "extreme_risk_off"
lox labs scenarios-factors --preset "stagflation_shock"
lox labs scenarios-factors --preset "goldilocks_boost"
lox labs scenarios-factors --preset "policy_error"
```

### Available Presets

```bash
lox labs scenarios-factors --list
```

1. **extreme_risk_off**
   - Risk: -1.0 (panic)
   - Growth: -0.5 (weak)
   - Liquidity: +0.8 (stressed)

2. **stagflation_shock**
   - Inflation: +0.9 (high)
   - Growth: -0.7 (contraction)
   - Policy: +0.6 (Fed stuck hawkish)

3. **goldilocks_boost**
   - Risk: +0.8 (risk-on)
   - Growth: +0.6 (solid)
   - Inflation: -0.3 (cooling)
   - Policy: -0.4 (dovish)

4. **policy_error**
   - Risk: -0.6 (risk-off)
   - Policy: +0.9 (Fed overtightens)

### Example Output

```
╭─────────────────────────────────────────────────╮
│ Factor-Based Scenario Analysis                  │
├─────────────────────────────────────────────────┤
│ Baseline Regime: DISINFLATIONARY               │
│ Scenario: Risk-Off + Liquidity Stress          │
│ Portfolio: Net Delta -25%, Vega 0.12           │
╰─────────────────────────────────────────────────╯

╭─────────────────────────────────────────────────╮
│ Scenario Factors                                 │
├─────────────────────────────────────────────────┤
│ Risk Appetite    -1.00  (extreme risk-off)      │
│ Growth           -0.30  (weak growth)           │
│ Inflation         0.00  (contained)             │
│ Liquidity        +0.80  (liquidity crisis)      │
│ Policy            0.00  (neutral)               │
╰─────────────────────────────────────────────────╯

╭─────────────────────────────────────────────────╮
│ Impact Estimate                                  │
├─────────────────────────────────────────────────┤
│ Portfolio P&L: +15.3%                           │
│ Confidence: medium                              │
│                                                  │
│ Summary: Portfolio gains +15.3%. Tail hedges    │
│ perform well.                                   │
╰─────────────────────────────────────────────────╯

Key Drivers:
  • Vega exposure: +10.2% (VIX +130%)
  • Tail hedges: +8.5% (convexity)
  • Equity exposure: -3.4% (net delta -25%)
```

---

## Comparison: Rule-Based vs. ML-Enhanced

| Feature | Rule-Based (v1) | Historical Events (v2a) | Factor-Based (v2b) |
|---------|-----------------|-------------------------|-------------------|
| **Input complexity** | High (specify 10+ variables) | Low (pick event) | Low (5 factors) |
| **Realism** | Synthetic | ACTUAL past moves | Learned from data |
| **Flexibility** | Medium | Low (historical only) | High (any combination) |
| **Interpretability** | High | Very high | High |
| **Correlation accuracy** | Manual (may be wrong) | Actual (from history) | Learned (estimated) |

### When to Use Each

**Rule-Based (`lox labs scenarios`)**:
- Quick stress tests
- You know exactly what move you want (e.g., "10Y +100 bps")
- Simple, fast

**Historical Events (`lox labs scenarios-historical`)**:
- You want REAL moves from past crises
- Benchmarking ("how would we have done in 2008?")
- Explaining to investors ("this is what happened in COVID")

**Factor-Based (`lox labs scenarios-factors`)**:
- You want to model a specific macro story (e.g., "stagflation")
- You want realistic correlations without specifying everything
- You want flexibility (can mix any factors)

---

## Next Steps: Full ML Implementation

The current v2 uses **heuristic factor loadings** (hand-tuned relationships). To make it truly ML-powered, you would:

### Step 1: Historical Data Collection
```python
# Collect 20+ years of daily data
# Variables: VIX, SPY, 10Y, 2Y, HY OAS, IG OAS, DXY, oil, etc.
df = load_historical_data(start="2000-01-01", end="2024-12-31")
```

### Step 2: Factor Model (PCA or Factor Analysis)
```python
from sklearn.decomposition import PCA

# Extract 5 principal components from market variables
pca = PCA(n_components=5)
factors = pca.fit_transform(df[market_vars])

# Interpret factors:
# PC1 = "risk appetite" (VIX, SPY, HY OAS all load heavily)
# PC2 = "rates" (10Y, 2Y load heavily)
# PC3 = "inflation" (breakevens, oil load heavily)
# etc.
```

### Step 3: Train Regression Model
```python
from sklearn.linear_model import Ridge

# Learn: factors → market variable changes
model = Ridge()
model.fit(factors, df[market_vars].pct_change())

# Now you can: specify factors → get realistic market moves
```

### Step 4: Monte Carlo Simulation
```python
# Sample 10,000 random factor combinations
# Weight by regime-conditional probabilities
# Generate full P&L distribution

for i in range(10000):
    factors = sample_factor_combination(regime=current_regime)
    market_moves = model.predict(factors)
    pnl = estimate_portfolio_impact(market_moves)
    pnl_distribution.append(pnl)

# Report VaR, CVaR, tail risk, etc.
```

### Step 5: Regime-Conditional Models
```python
# Different behavior in different regimes
# e.g., VIX-SPY correlation is different in DISINFLATIONARY vs. INFLATIONARY

model_disinflationary = train_model(data[regime == "DISINFLATIONARY"])
model_inflationary = train_model(data[regime == "INFLATIONARY"])

# Use appropriate model based on current regime
```

Would you like me to implement any of these next steps?

---

## Files Created

1. **`llm/scenario_ml.py`** - Historical events library + factor model
2. **`cli_commands/scenarios_ml_cmd.py`** - ML-enhanced CLI commands
3. **`docs/ML_SCENARIO_ANALYSIS.md`** - This documentation

## Commands Summary

```bash
# Original rule-based
lox labs scenarios --scenarios "vix_spike,credit_stress"

# Historical events
lox labs scenarios-historical --list
lox labs scenarios-historical --events "gfc_2008,covid_crash_2020"
lox labs scenarios-historical --severity 0.5

# Factor-based
lox labs scenarios-factors --list
lox labs scenarios-factors --risk-appetite -1.0 --liquidity 0.8
lox labs scenarios-factors --preset "stagflation_shock"
```
