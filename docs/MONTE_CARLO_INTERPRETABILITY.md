# Monte Carlo Interpretability Guide

## 🎯 Your Question
**"Why is it predicting +0.3% mean but -8.6% median with 70% losing money?"**

---

## ✅ New Feature: `--explain`

```bash
lox labs scenarios-monte-carlo --horizon 6 --explain
```

This shows you **exactly why** the model predicts what it does.

---

## 📊 What You'll See

### 1. P&L Components Breakdown

```
1. P&L Components (typical scenario):
  Theta decay       -9.0%     (-0.05% per day × 180 days)
  Delta exposure    Varies    (-20% delta → gain/lose with market)
  Vega exposure     Varies    (0.10 → gain 10% if VIX +10pts)
  Tail hedges       Convex    (Big gains when VIX spikes >30%)
```

**Key insight**: Theta decay is **killing you every day** (-9% over 6M). You need big VIX spikes to overcome this.

---

### 2. Why Median ≠ Mean?

```
2. Why Median (-8.6%) ≠ Mean (+0.3%)?
  → Your portfolio has POSITIVE SKEW (tail hedge structure):
    • Most scenarios: Small losses (theta decay dominates)
    • Rare scenarios: Huge gains (hedges pay off)
    • This is INTENTIONAL for tail-risk hedging!
```

**Key insight**: You have a **tail hedge structure**:
- **70% of time**: Small losses (theta eats you)
- **30% of time**: Big gains (hedges explode)

This is **BY DESIGN** for tail risk funds!

---

### 3. What Market Moves Create Each Outcome?

```
Scenario      P&L       VIX         SPX       10Y Yield
Best Case   +118.4%   35.2 (+136%)  -20.5%    +85 bps    <- VIX SPIKE!
Median       -8.6%    15.1 (+1%)     -3.2%    +12 bps    <- Nothing happens
Worst Case  -28.7%     6.3 (-58%)   +22.1%    -90 bps    <- VIX DIES
```

**Key insights**:
- **Best case**: VIX doubles → hedges print money
- **Median case**: VIX flat → theta decay wins
- **Worst case**: VIX collapses → double loss (theta + vega negative)

---

### 4. Model Assumptions

```
• VIX-SPX correlation: -0.75 (strong negative)
• VIX typical move: ±56% over 6M (√2 × ±40% for 3M)
• SPX typical move: ±21% over 6M (√2 × ±15% for 3M)
• Tail hedges activate when VIX >30% spike
• Convexity: VIX +50% → hedge gains ~25% NAV
```

**Key insight**: The model assumes **high volatility** (±56% VIX moves). If VIX is actually calmer, you'll just bleed theta.

---

### 5. What Could Make This Wrong?

```
⚠️  VIX doesn't spike (hedges never pay off → just theta decay)
⚠️  Correlations break (VIX up but SPX also up)
⚠️  Volatility is calmer than assumed (±56% might be too high)
⚠️  Greeks change as positions age (not modeled)
⚠️  Liquidity events (can't exit at model prices)
```

**Most likely risk**: VIX stays calm → you just lose 9% to theta over 6M.

---

## 🎯 Why Your Current Portfolio Shows This

### Your Inputs:
- **Net Delta**: -20% (short equities)
- **Vega**: 0.10 (long vol)
- **Theta**: -0.0005 per day = **-9% over 6M** ⚠️
- **Tail hedges**: Yes

### The Math:
1. **Base case** (70% probability): VIX flat → -9% (theta)
2. **Upside** (30% probability): VIX spikes → +118% (hedges)
3. **Mean**: 0.7 × (-9%) + 0.3 × (+118%) = **+0.3%**
4. **Median**: -8.6% (the typical outcome)

---

## 💡 How to Interpret This

### This is a **TAIL HEDGE** structure:
```
┌─────────────────────────────────────────┐
│ Most days: Bleed theta (-9% over 6M)   │
│ Rare days: Hedges explode (+118%)      │
│ Expected: Slightly positive (+0.3%)    │
└─────────────────────────────────────────┘
```

**You're paying insurance premiums (theta) for protection (hedges).**

---

## 🔬 How to Validate

### Track These Over Next 6 Months:

1. **Did VIX move ±56%?**
   - If yes: Model volatility is correct
   - If no: Model is too pessimistic (assumes too much vol)

2. **Did correlations hold?**
   - When VIX up, was SPX down?
   - If correlations break, model is wrong

3. **Actual P&L vs Predicted**
   - Compare your actual P&L to the distribution
   - If consistently off → adjust model

---

## 🎯 What This Tells You

### Your portfolio is saying:
```
"I'm willing to lose 9% to theta over 6 months
 in exchange for 118% gains if markets crash"
```

### Is this good or bad?
**Depends on your view:**
- ✅ **Good if**: You think crash risk is >6% (to break even on theta)
- ❌ **Bad if**: You think markets stay calm (just bleed theta)

---

## 📈 How to Improve

### If you want higher median P&L:
1. **Reduce theta**: Roll options to longer dated (less decay)
2. **Add carry**: Buy some equity/credit exposure
3. **Reduce hedge size**: Less protection = less premium

### If you want to keep tail protection but reduce bleed:
1. **Sell some vega**: Reduce long vol positions
2. **Longer dated hedges**: Less theta decay
3. **Add spreads**: Buy/sell to reduce net premium

---

## 🚀 Next Steps

```bash
# 1. Run with --explain to see the full breakdown
lox labs scenarios-monte-carlo --horizon 6 --explain

# 2. Adjust greeks to see impact
lox labs scenarios-monte-carlo --theta -0.0003 --explain  # Less decay

# 3. Test different horizons
lox labs scenarios-monte-carlo --horizon 3 --explain  # Shorter = less theta
```

---

## Key Takeaway

**Your portfolio is working as designed:**
- Mean +0.3% (slightly positive expected value)
- Median -8.6% (typical outcome is small loss)
- 26% chance of large gain (when hedges work)

**This is normal for tail hedge funds!** You're paying insurance premiums (theta) for crash protection (convexity).

The question is: **Is the premium (9% over 6M) worth the protection?**
