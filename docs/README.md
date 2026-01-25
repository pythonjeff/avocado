# Lox Capital Documentation

This directory contains technical documentation for the Lox Capital AI Options Trading system.

## Quick Links

| Document | Description |
|----------|-------------|
| [EXECUTIVE_SUMMARY.md](EXECUTIVE_SUMMARY.md) | High-level overview of the system |
| [V3_QUICK_START.md](V3_QUICK_START.md) | Getting started guide |
| [COMMANDS_GUIDE.md](COMMANDS_GUIDE.md) | CLI command reference |
| [TECHNICAL_SPEC.md](TECHNICAL_SPEC.md) | Detailed technical specification |

## Documentation by Category

### Getting Started
- [V3_QUICK_START.md](V3_QUICK_START.md) - Installation and first steps
- [V3_SUMMARY.md](V3_SUMMARY.md) - V3 feature overview
- [V3_REAL_DATA_INTEGRATION.md](V3_REAL_DATA_INTEGRATION.md) - Connecting to live data

### Architecture & Design
- [TECHNICAL_SPEC.md](TECHNICAL_SPEC.md) - Complete technical specification
- [ARCHITECTURE_SLEEVES.md](ARCHITECTURE_SLEEVES.md) - Sleeve-based strategy architecture
- [PROJECT_CONSTITUTION.md](PROJECT_CONSTITUTION.md) - Project principles and goals
- [OBJECTIVES.md](OBJECTIVES.md) - System objectives and constraints

### Trading Strategy
- [METHODOLOGY.md](METHODOLOGY.md) - Trading methodology overview
- [HEDGE_FUND_APPROACH.md](HEDGE_FUND_APPROACH.md) - Hedge fund-style trading approach
- [HEDGE_VS_DIRECTIONAL.md](HEDGE_VS_DIRECTIONAL.md) - Comparing strategy types

### Commands & Usage
- [COMMANDS_GUIDE.md](COMMANDS_GUIDE.md) - Complete CLI reference
- [TRADE_IDEAS_COMMANDS.md](TRADE_IDEAS_COMMANDS.md) - Trade idea generation commands
- [HEDGE_COMMAND_GUIDE.md](HEDGE_COMMAND_GUIDE.md) - Hedging command reference

### Scenario Analysis
- [SCENARIO_ANALYSIS.md](SCENARIO_ANALYSIS.md) - Scenario analysis overview
- [ML_SCENARIO_ANALYSIS.md](ML_SCENARIO_ANALYSIS.md) - ML-enhanced scenarios
- [SCENARIO_IMPLEMENTATION_SUMMARY.md](SCENARIO_IMPLEMENTATION_SUMMARY.md) - Implementation details

### Monte Carlo
- [MONTE_CARLO_V01_SUMMARY.md](MONTE_CARLO_V01_SUMMARY.md) - Monte Carlo v0.1 engine
- [MONTE_CARLO_INTERPRETABILITY.md](MONTE_CARLO_INTERPRETABILITY.md) - Understanding MC results

### Reference
- [DEMO_OUTPUT.md](DEMO_OUTPUT.md) - Sample command outputs
- [EXECUTIVE_SUMMARY.md](EXECUTIVE_SUMMARY.md) - Executive overview

## Module Structure

The codebase is organized as follows:

```
src/ai_options_trader/
├── cli.py                  # Main CLI entry point
├── cli_commands/           # CLI command modules
│   ├── core/               # Status, dashboard, NAV, account
│   ├── regimes/            # Regime analysis commands
│   ├── options/            # Options scanning commands
│   ├── analysis/           # Scenarios, Monte Carlo, stress
│   ├── ideas/              # Trade idea generation
│   └── shared/             # Shared utilities
├── data/                   # Data fetchers (Alpaca, FRED, FMP)
├── llm/                    # LLM-powered analysis
│   ├── outlooks/           # Domain-specific outlooks
│   ├── scenarios/          # Scenario analysis, Monte Carlo
│   └── core/               # Analyst, sentiment, utilities
├── strategies/             # Strategy framework
├── portfolio/              # Portfolio management
├── regimes/                # Unified regime framework
└── [domain]/               # Domain modules (macro, funding, etc.)
```

## Environment Variables

Key configuration variables (see `.env.example`):

| Variable | Description |
|----------|-------------|
| `ALPACA_API_KEY` | Alpaca trading API key |
| `ALPACA_API_SECRET` | Alpaca trading API secret |
| `ALPACA_PAPER` | Use paper trading (`true`/`false`) |
| `OPENAI_API_KEY` | OpenAI API key for LLM analysis |
| `FRED_API_KEY` | FRED API key for macro data |
| `FMP_API_KEY` | Financial Modeling Prep API key |

## Contributing

When adding new documentation:
1. Add the file to this directory
2. Update this README with a link in the appropriate category
3. Use consistent markdown formatting
