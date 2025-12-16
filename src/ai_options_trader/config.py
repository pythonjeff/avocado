from __future__ import annotations

from pydantic import BaseModel
from pydantic_settings import BaseSettings, SettingsConfigDict

class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8", extra="ignore")

    ALPACA_API_KEY: str
    ALPACA_API_SECRET: str
    ALPACA_PAPER: bool = True
    ALPACA_DATA_KEY: str | None = None
    ALPACA_DATA_SECRET: str | None = None
    OPENAI_API_KEY: str | None = None
    OPENAI_MODEL: str = "gpt-4o-mini"
    FRED_API_KEY: str | None = None

    # Backwards-compatible snake_case accessors used across the codebase.
    # Pydantic v2 uses field names as attribute names; these properties allow both styles.
    @property
    def alpaca_api_key(self) -> str:
        return self.ALPACA_API_KEY

    @property
    def alpaca_api_secret(self) -> str:
        return self.ALPACA_API_SECRET

    @property
    def alpaca_paper(self) -> bool:
        return self.ALPACA_PAPER

    @property
    def alpaca_data_key(self) -> str | None:
        return self.ALPACA_DATA_KEY

    @property
    def alpaca_data_secret(self) -> str | None:
        return self.ALPACA_DATA_SECRET

    @property
    def openai_api_key(self) -> str | None:
        return self.OPENAI_API_KEY

    @property
    def openai_model(self) -> str:
        return self.OPENAI_MODEL

    @property
    def fred_api_key(self) -> str | None:
        return self.FRED_API_KEY

class StrategyConfig(BaseModel):
    target_dte_days: int = 30
    target_delta_abs: float = 0.35
    dte_min: int = 14
    dte_max: int = 90

    min_open_interest: int = 10
    min_volume: int = 1
    max_spread_pct: float = 0.99  # 15%

class RiskConfig(BaseModel):
    max_equity_pct_per_trade: float = 0.10
    max_contracts: int = 20
    max_premium_per_contract: float | None = None  # e.g., 5.00 means $500/contract

def load_settings() -> Settings:
    return Settings()
