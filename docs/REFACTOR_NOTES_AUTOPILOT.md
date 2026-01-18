# Autopilot Command Refactoring Notes

## Current State
- **File**: `src/ai_options_trader/cli_commands/autopilot_cmd.py`
- **Size**: 2020 lines
- **Structure**: One giant `run_once()` function with ~1900 lines of logic

## Complexity Issues
- All logic is inline in a single function
- Multiple execution modes (predictions, multi-sleeve, legacy)
- Complex branching for budget modes, execution modes, LLM integration
- Heavy interdependencies between sections

## Recommended Refactoring (Manual)
This file requires careful manual refactoring due to:
1. Complex state management across execution modes
2. Interactive prompts with branching logic
3. Execution safety guards that need careful preservation

### Suggested Module Structure:
```
autopilot/
├── __init__.py
├── utils.py (✅ created)
├── predictions.py - Predictions-only mode logic
├── sleeves.py - Multi-sleeve orchestration
├── budgeting.py - Budget calculation and allocation
├── positions.py - Position management and review
├── ideas.py - Forecast generation and ranking
├── proposals.py - Trade proposal generation
├── explainability.py - WHY THESE TRADES logic
├── execution.py - Order execution logic
└── llm.py - LLM integration for all modes
```

## Priority
**LOW** - This is a critical execution path. Refactor only when:
1. A specific bug or feature requires it
2. Test coverage is sufficient
3. Manual review by author is available

Focus on other large files first (options_cmd, fiscal/signals, etc.) that have clearer separation opportunities.
