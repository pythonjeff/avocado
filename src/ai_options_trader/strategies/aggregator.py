from __future__ import annotations

from dataclasses import dataclass

from ai_options_trader.strategies.base import CandidateTrade


_LEVERED_INVERSE_EQUITY = {
    # Canonical examples + common leveraged inverse equity ETFs
    "SPXU",
    "SQQQ",
    "TZA",
    "SDOW",
    "SOXS",
    "SRTY",
    "LABD",
    "TWM",
    "SDS",
    "QID",
}


@dataclass(frozen=True)
class AggregationResult:
    selected: list[CandidateTrade]
    dropped: list[tuple[CandidateTrade, str]]


class PortfolioAggregator:
    """
    MVP portfolio aggregator:
    - de-dups redundant exposures via risk_factors signature + factor caps
    - blocks mutually exclusive tickers (levered inverse equity, PSQ+SQQQ)
    - enforces sleeve budgets + total budget (best-effort cost accounting)
    """

    def __init__(
        self,
        *,
        factor_cap: int = 1,
    ) -> None:
        self.factor_cap = int(factor_cap)

    def aggregate(
        self,
        *,
        candidates: list[CandidateTrade],
        total_budget_usd: float,
        sleeve_budgets_pct: dict[str, float] | None = None,
    ) -> AggregationResult:
        sleeve_budgets_pct = dict(sleeve_budgets_pct or {})

        # Normalize budget pct; fall back to equal weights across sleeves if not provided.
        sleeves = sorted({c.sleeve for c in candidates if c.sleeve})
        if sleeves and not sleeve_budgets_pct:
            sleeve_budgets_pct = {s: 1.0 / float(len(sleeves)) for s in sleeves}

        # Remaining budgets
        total_rem = float(max(0.0, total_budget_usd))
        sleeve_rem: dict[str, float] = {}
        for s in sleeves:
            pct = float(sleeve_budgets_pct.get(s, 0.0) or 0.0)
            sleeve_rem[s] = float(max(0.0, pct * float(total_budget_usd)))

        dropped: list[tuple[CandidateTrade, str]] = []
        selected: list[CandidateTrade] = []

        # State for constraints
        used_levered_inverse = False
        used_psq = False
        used_sqqq = False
        used_factor_counts: dict[str, int] = {}
        used_signature: dict[tuple[str, ...], CandidateTrade] = {}

        # Greedy: highest score first
        ranked = sorted(candidates, key=lambda c: float(c.score), reverse=True)

        def _cost(c: CandidateTrade) -> float:
            try:
                return float(c.est_cost_usd or 0.0)
            except Exception:
                return 0.0

        for c in ranked:
            t = (c.ticker or "").strip().upper()

            # Enforce allowed instrument types? (Sleeves can filter earlier; keep safety here.)
            # No-op: handled upstream for MVP.

            # Mutually exclusive inverse-leverage rules
            if t in _LEVERED_INVERSE_EQUITY:
                if used_levered_inverse:
                    dropped.append((c, "levered_inverse_equity_cap"))
                    continue
                used_levered_inverse = True
            if t == "PSQ":
                if used_sqqq:
                    dropped.append((c, "psq_sqqq_exclusive"))
                    continue
                used_psq = True
            if t == "SQQQ":
                if used_psq:
                    dropped.append((c, "psq_sqqq_exclusive"))
                    continue
                used_sqqq = True

            # Signature de-dupe (same risk_factors): keep best only (unless probe).
            sig = tuple(c.risk_factors or ())
            if sig and not bool(c.probe):
                prev = used_signature.get(sig)
                if prev is not None:
                    dropped.append((c, "duplicate_risk_signature"))
                    continue

            # Factor caps (max 1 per factor unless probe)
            if c.risk_factors and not bool(c.probe):
                violated = False
                for f in c.risk_factors:
                    if int(used_factor_counts.get(f, 0)) >= int(self.factor_cap):
                        violated = True
                        break
                if violated:
                    dropped.append((c, "factor_cap"))
                    continue

            # Budgets
            cost = _cost(c)
            if cost > 0:
                if cost > total_rem:
                    dropped.append((c, "total_budget"))
                    continue
                srem = float(sleeve_rem.get(c.sleeve, 0.0))
                if cost > srem:
                    dropped.append((c, "sleeve_budget"))
                    continue

            # Accept
            selected.append(c)
            if sig and not bool(c.probe):
                used_signature[sig] = c
            if c.risk_factors and not bool(c.probe):
                for f in c.risk_factors:
                    used_factor_counts[f] = int(used_factor_counts.get(f, 0)) + 1
            if cost > 0:
                total_rem = float(max(0.0, total_rem - cost))
                sleeve_rem[c.sleeve] = float(max(0.0, float(sleeve_rem.get(c.sleeve, 0.0)) - cost))

        return AggregationResult(selected=selected, dropped=dropped)

