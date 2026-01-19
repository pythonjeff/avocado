"""Budget planning for autopilot trades."""
from __future__ import annotations

from dataclasses import dataclass


@dataclass
class BudgetPlan:
    """A budget allocation plan."""
    name: str
    budget_equity: float
    budget_options: float
    note: str

    @property
    def total(self) -> float:
        return self.budget_equity + self.budget_options


def build_budget_plans(
    *,
    cash: float,
    mode: str = "strict",
    allocation: str = "auto",
    min_new_trades: int = 2,
) -> list[BudgetPlan]:
    """
    Build budget allocation plan(s) based on mode and allocation.
    
    Args:
        cash: Available cash
        mode: "strict" or "flex"
        allocation: "auto", "equity100", "50_50", "70_30", or "both"
        min_new_trades: Minimum trades to target (used in flex note)
    
    Returns:
        List of BudgetPlan objects
    """
    budget_total = max(0.0, cash)
    
    if mode == "flex":
        return [BudgetPlan(
            name="flex",
            budget_equity=budget_total,
            budget_options=budget_total,
            note=f"Budget mode: FLEX (allocate across >= {min_new_trades} trade(s))",
        )]
    
    # Strict mode
    def _strict_plan(kind: str) -> BudgetPlan:
        k = (kind or "auto").strip().lower()
        
        if k == "equity100":
            return BudgetPlan(
                name="equity100",
                budget_equity=budget_total,
                budget_options=0.0,
                note="Allocation: 100% equities",
            )
        
        if k == "50_50":
            return BudgetPlan(
                name="50_50",
                budget_equity=0.50 * budget_total,
                budget_options=0.50 * budget_total,
                note="Allocation: 50% equities / 50% options",
            )
        
        if k == "70_30":
            return BudgetPlan(
                name="70_30",
                budget_equity=0.70 * budget_total,
                budget_options=0.30 * budget_total,
                note="Allocation: 70% equities / 30% options",
            )
        
        # Auto: drawdown-aware default
        if budget_total >= 500.0:
            return BudgetPlan(
                name="auto",
                budget_equity=0.70 * budget_total,
                budget_options=0.30 * budget_total,
                note="Allocation: 70/30 (auto, cash >= $500)",
            )
        
        return BudgetPlan(
            name="auto",
            budget_equity=budget_total,
            budget_options=0.0,
            note="Allocation: 100% equities (auto, cash < $500)",
        )
    
    if allocation == "both":
        return [
            _strict_plan("equity100"),
            _strict_plan("50_50"),
            _strict_plan("70_30"),
        ]
    
    return [_strict_plan(allocation)]


def format_budget_status(
    plans: list[BudgetPlan],
    mode: str,
    cash: float,
    min_trades: int,
    max_trades: int,
) -> str:
    """Format budget status for display."""
    lines = [f"Trade budget (cash): ${cash:,.2f}"]
    
    if mode == "flex":
        lines.append(plans[0].note)
    elif len(plans) == 1:
        p = plans[0]
        lines.append(
            f"{p.note} (shares≈${p.budget_equity:,.2f} "
            f"options≈${p.budget_options:,.2f})"
        )
    else:
        for p in plans:
            lines.append(
                f"- {p.name}: {p.note} "
                f"(shares≈${p.budget_equity:,.2f} options≈${p.budget_options:,.2f})"
            )
    
    lines.append(f"Target new trades: {min_trades}..{max_trades}")
    return "\n".join(lines)
