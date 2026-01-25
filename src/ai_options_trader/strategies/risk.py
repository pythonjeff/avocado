from __future__ import annotations

from dataclasses import dataclass
from ai_options_trader.config import RiskConfig

@dataclass(frozen=True)
class SizeResult:
    max_contracts: int
    per_contract_cost: float
    budget_usd: float

def size_by_budget(budget_usd: float, per_contract_cost: float, risk: RiskConfig) -> SizeResult:
    if per_contract_cost <= 0:
        return SizeResult(max_contracts=0, per_contract_cost=per_contract_cost, budget_usd=budget_usd)

    max_by_budget = int(budget_usd // per_contract_cost)
    max_contracts = max(0, min(max_by_budget, risk.max_contracts))

    if risk.max_premium_per_contract is not None:
        if per_contract_cost > risk.max_premium_per_contract * 100:
            max_contracts = 0

    return SizeResult(max_contracts=max_contracts, per_contract_cost=per_contract_cost, budget_usd=budget_usd)
