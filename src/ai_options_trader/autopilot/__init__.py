"""
Autopilot module - modular trade automation.

Components:
- utils: Shared utilities and constants
- budget: Cash allocation and budget planning
- positions: Position analysis and stop-loss detection  
- proposals: Trade proposal generation and allocation
- ideas: Trade idea generation (playbook/ML)
- options: Option leg attachment
- display: Output formatting helpers
"""
from ai_options_trader.autopilot.utils import (
    to_float,
    extract_underlying,
    HEDGE_TICKERS,
    LEVERED_INVERSE_EQUITY,
    INVERSE_PROXY,
)
from ai_options_trader.autopilot.budget import (
    BudgetPlan,
    build_budget_plans,
    format_budget_status,
)
from ai_options_trader.autopilot.positions import (
    fetch_positions,
    stop_candidates,
    get_held_underlyings,
    get_option_underlyings,
    is_option_position,
)
from ai_options_trader.autopilot.proposals import (
    TradeProposal,
    AllocationResult,
    build_proposals,
)
from ai_options_trader.autopilot.ideas import (
    generate_ideas,
    apply_thesis_reweighting,
)
from ai_options_trader.autopilot.options import attach_option_legs
from ai_options_trader.autopilot.display import (
    display_positions_table,
    display_status_panel,
    display_proposals_table,
    display_budget_summary,
)

__all__ = [
    # Utils
    "to_float",
    "extract_underlying",
    "HEDGE_TICKERS",
    "LEVERED_INVERSE_EQUITY",
    "INVERSE_PROXY",
    # Budget
    "BudgetPlan",
    "build_budget_plans",
    "format_budget_status",
    # Positions
    "fetch_positions",
    "stop_candidates",
    "get_held_underlyings",
    "get_option_underlyings",
    "is_option_position",
    # Proposals
    "TradeProposal",
    "AllocationResult",
    "build_proposals",
    # Ideas
    "generate_ideas",
    "apply_thesis_reweighting",
    # Options
    "attach_option_legs",
    # Display
    "display_positions_table",
    "display_status_panel",
    "display_proposals_table",
    "display_budget_summary",
]
