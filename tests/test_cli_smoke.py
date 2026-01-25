"""
CLI smoke tests - verify commands load without errors.

These tests don't execute full functionality (which would require API keys),
but verify that the CLI structure is correctly wired up.
"""
from __future__ import annotations

import pytest
from typer.testing import CliRunner
from unittest.mock import patch, MagicMock

runner = CliRunner()


class TestCLIStructure:
    """Test that CLI commands are properly registered and accessible."""
    
    def test_cli_imports_without_error(self):
        """The CLI module should import without errors."""
        from ai_options_trader.cli import app
        assert app is not None
    
    def test_main_help(self):
        """The main CLI should show help without errors."""
        from ai_options_trader.cli import app
        result = runner.invoke(app, ["--help"])
        assert result.exit_code == 0
        assert "Lox Capital CLI" in result.output
    
    def test_labs_help(self):
        """The labs subcommand should show help."""
        from ai_options_trader.cli import app
        result = runner.invoke(app, ["labs", "--help"])
        assert result.exit_code == 0
        assert "research" in result.output.lower() or "regime" in result.output.lower()
    
    def test_options_help(self):
        """The options subcommand should show help."""
        from ai_options_trader.cli import app
        result = runner.invoke(app, ["options", "--help"])
        assert result.exit_code == 0
        assert "scanner" in result.output.lower() or "moonshot" in result.output.lower()
    
    def test_ideas_help(self):
        """The ideas subcommand should show help."""
        from ai_options_trader.cli import app
        result = runner.invoke(app, ["ideas", "--help"])
        assert result.exit_code == 0
        assert "trade" in result.output.lower() or "catalyst" in result.output.lower()
    
    def test_nav_help(self):
        """The nav subcommand should show help."""
        from ai_options_trader.cli import app
        result = runner.invoke(app, ["nav", "--help"])
        assert result.exit_code == 0
    
    def test_autopilot_help(self):
        """The autopilot subcommand should show help."""
        from ai_options_trader.cli import app
        result = runner.invoke(app, ["autopilot", "--help"])
        assert result.exit_code == 0


class TestRegimeCommands:
    """Test regime command structure."""
    
    @pytest.mark.parametrize("regime", [
        "volatility", "fiscal", "funding", "monetary",
        "rates", "commodities", "crypto", "housing", "usd", "solar"
    ])
    def test_regime_help(self, regime: str):
        """Each regime subcommand should show help."""
        from ai_options_trader.cli import app
        result = runner.invoke(app, ["labs", regime, "--help"])
        assert result.exit_code == 0


class TestAnalysisCommands:
    """Test analysis command structure."""
    
    def test_model_help(self):
        """The model subcommand should show help."""
        from ai_options_trader.cli import app
        result = runner.invoke(app, ["model", "--help"])
        assert result.exit_code == 0


class TestModuleImports:
    """Test that critical modules import correctly."""
    
    def test_strategies_module(self):
        """Strategies module should import."""
        from ai_options_trader.strategies import (
            CandidateTrade,
            SleeveConfig,
            PortfolioAggregator,
            SizeResult,
            choose_best_option,
        )
        assert CandidateTrade is not None
        assert choose_best_option is not None
    
    def test_data_module(self):
        """Data module should import."""
        from ai_options_trader.data.alpaca import make_clients, OptionCandidate
        from ai_options_trader.data.fred import FredClient
        assert make_clients is not None
        assert OptionCandidate is not None
        assert FredClient is not None
    
    def test_regime_modules(self):
        """Regime modules should import."""
        from ai_options_trader.volatility.regime import classify_volatility_regime
        from ai_options_trader.funding.regime import classify_funding_regime
        from ai_options_trader.commodities.regime import classify_commodities_regime
        assert classify_volatility_regime is not None
        assert classify_funding_regime is not None
        assert classify_commodities_regime is not None
    
    def test_llm_modules(self):
        """LLM modules should import from new structure."""
        from ai_options_trader.llm.scenarios.monte_carlo_v01 import MonteCarloV01
        from ai_options_trader.llm.scenarios.scenarios import SCENARIOS
        from ai_options_trader.llm.core.analyst import llm_analyze_regime
        assert MonteCarloV01 is not None
        assert SCENARIOS is not None
        assert llm_analyze_regime is not None
