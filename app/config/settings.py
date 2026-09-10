"""
Application configuration module.

Loads settings from environment variables with sensible defaults.
Never hard-codes API keys or secrets.
"""

import os
from pathlib import Path
from typing import Optional

import yaml
from dotenv import load_dotenv
from pydantic import Field
from pydantic_settings import BaseSettings

# Load .env file if it exists
load_dotenv()

# Project root directory
PROJECT_ROOT = Path(__file__).parent.parent.parent
APP_ROOT = Path(__file__).parent.parent
CONFIG_DIR = Path(__file__).parent


class AppSettings(BaseSettings):
    """Application-wide settings loaded from environment variables."""

    # Data provider
    data_provider: str = Field(default="yfinance", description="Primary data provider")
    market_data_api_key: Optional[str] = Field(
        default=None, description="API key for premium providers"
    )

    # Stock universe
    stock_universe: str = Field(
        default="NIFTY_200",
        description="Stock universe: NIFTY_50, NIFTY_100, NIFTY_200, NIFTY_500",
    )

    # Analysis
    default_analysis_period: int = Field(
        default=30, description="Default analysis period in trading days"
    )

    # Flask
    flask_secret_key: str = Field(
        default="dev-secret-key-change-in-production",
        description="Flask secret key",
    )
    flask_host: str = Field(default="127.0.0.1", description="Flask host")
    flask_port: int = Field(default=5000, description="Flask port")
    flask_debug: bool = Field(default=True, description="Flask debug mode")

    # Rate limiting
    max_requests_per_second: float = Field(
        default=2.0, description="Max requests per second to data provider"
    )
    request_timeout: int = Field(
        default=30, description="Request timeout in seconds"
    )

    class Config:
        env_file = ".env"
        env_file_encoding = "utf-8"
        case_sensitive = False


class ScoringWeights:
    """
    Scoring weights loaded from YAML configuration.

    All weights and thresholds are loaded from scoring_weights.yaml.
    This class provides validated access to scoring configuration.
    """

    def __init__(self, config_path: Optional[Path] = None):
        if config_path is None:
            config_path = CONFIG_DIR / "scoring_weights.yaml"

        with open(config_path, "r") as f:
            self._config = yaml.safe_load(f)

        self._validate()

    def _validate(self):
        """Validate that weights sum correctly."""
        cat = self.category_weights
        positive_sum = cat["movement"] + cat["volatility"] + cat["liquidity"] + cat["consistency"]
        if abs(positive_sum - 1.0) > 0.001:
            raise ValueError(
                f"Category weights (excluding risk_penalty) must sum to 1.0, "
                f"got {positive_sum}"
            )

        # Validate each sub-metric group sums to 1.0
        for group_name in [
            "movement_weights",
            "volatility_weights",
            "liquidity_weights",
            "consistency_weights",
            "risk_penalty_weights",
        ]:
            weights = self._config[group_name]
            total = sum(weights.values())
            if abs(total - 1.0) > 0.001:
                raise ValueError(
                    f"{group_name} must sum to 1.0, got {total}"
                )

    @property
    def version(self) -> str:
        return self._config["version"]

    @property
    def category_weights(self) -> dict:
        return self._config["category_weights"]

    @property
    def movement_weights(self) -> dict:
        return self._config["movement_weights"]

    @property
    def volatility_weights(self) -> dict:
        return self._config["volatility_weights"]

    @property
    def liquidity_weights(self) -> dict:
        return self._config["liquidity_weights"]

    @property
    def consistency_weights(self) -> dict:
        return self._config["consistency_weights"]

    @property
    def risk_penalty_weights(self) -> dict:
        return self._config["risk_penalty_weights"]

    @property
    def thresholds(self) -> dict:
        return self._config["thresholds"]


def get_settings() -> AppSettings:
    """Get application settings singleton."""
    return AppSettings()


def get_scoring_weights(config_path: Optional[Path] = None) -> ScoringWeights:
    """Get scoring weights from YAML configuration."""
    return ScoringWeights(config_path)
