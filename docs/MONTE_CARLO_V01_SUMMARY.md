# v0.1 Monte Carlo - Position-Level Upgrade

## ✅ What's New

### 1. **Position-Level Representation** (Biggest Gap Fixed!)

**Before (v0.0):**
```
Net Delta: -20%, Vega: 0.10, Theta: -0.05 bps/day
```
❌ Too abstract, no position detail

**After (v0.1):**
```
Positions:
  SPY/250321P00400000  PUT    +10   $5,500   -0.25  $450  -$15/day  85d
  SPY                  ETF    -20  $11,700   -1.00    -       -       -
  VIX/250221C00025000  CALL    +5   $1,400   +0.65  $280   -$8/day  33d
  HYG/250620P00072000  PUT    +15   $1,800   -0.18  $220  -$12/day 151d
```
✅ Every position tracked individually

---

### 2. **Separate S & IV Dynamics** (Critical for Vega)

**Before:**
- Single "market move" scalar
- Vega was hand-waved

**After:**
- **Equity path**: Drift + vol + jumps
- **IV path**: Mean-reverting with vol-of-vol
- **Correlation**: Corr(S, IV) = -0.65 in stagflation (negative skew)

---

### 3. **Taylor Approximation Per Instrument**

**P&L Formula (per option):**
```
ΔP ≈ Δ·ΔS + ½Γ(ΔS)² + Vega·Δσ - Θ·Δt
```

✅ **Explainable**: You see exactly where P&L comes from!

---

### 4. **Regime-Conditional Assumptions**

| Assumption | Stagflation | Goldilocks |
|------------|-------------|------------|
| Equity drift | -2% | +8% |
| Equity vol | 22% | 15% |
| Corr(S, IV) | -0.65 | -0.50 |
| Jump probability | 10% | 3% |

---

### 5. **Scenario Attribution**

**Top 3 Winning/Losing Scenarios:**
- Shows exact market moves
- Identifies which position hurt/helped most
- Flags jump events

---

## 🚀 How to Use

```bash
# Basic
lox labs mc-v01

# Regime-specific
lox labs mc-v01 --regime STAGFLATION

# Custom
lox labs mc-v01 -n 50000 --horizon 6
```

---

## ✅ Addresses Your Requirements

- ✅ **#1: Position-level representation** - Every option tracked
- ✅ **#2: Separate S & IV dynamics** - Correlated simulation
- ✅ **#3: Theta consistency** - $ per day, tracked over horizon
- ✅ **#4: Decision-relevant metrics** - Breakevens, attribution
- ✅ **#5: Scenario attribution** - Top winners/losers
- ✅ **#6: Macro scenarios** - Regime-conditional assumptions
- ✅ **#7: Clean UI** - Skewness, $ and %

**Ready to test!** 🚀
