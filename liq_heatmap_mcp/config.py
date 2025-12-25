"""
Configuration management for the Liquidation Heatmap MCP Server.
"""

import os
from dataclasses import dataclass, field
from pathlib import Path
from typing import Literal, Optional


@dataclass
class Config:
    """Application configuration loaded from environment variables."""

    # LLM Configuration
    comet_api_key: Optional[str] = field(
        default_factory=lambda: os.getenv("COMET_API_KEY")
    )
    comet_base_url: str = field(
        default_factory=lambda: os.getenv(
            "COMET_BASE_URL", "https://api.cometapi.com/v1"
        )
    )
    comet_model: str = field(
        default_factory=lambda: os.getenv("COMET_MODEL", "gpt-4o")
    )
    comet_reasoning: str = field(
        default_factory=lambda: os.getenv("COMET_REASONING", "xhigh")
    )

    # Cookie configuration for sites
    coinglass_cookie: Optional[str] = field(
        default_factory=lambda: os.getenv("COINGLASS_COOKIE")
    )
    coinank_cookie: Optional[str] = field(
        default_factory=lambda: os.getenv("COINANK_COOKIE")
    )

    # Cache and debug settings
    screenshot_cache_dir: Path = field(
        default_factory=lambda: Path(
            os.getenv("SCREENSHOT_CACHE_DIR", "/tmp/liq-heatmap")
        )
    )
    log_level: str = field(
        default_factory=lambda: os.getenv("LOG_LEVEL", "INFO")
    )
    debug_crop: bool = field(
        default_factory=lambda: os.getenv("DEBUG_CROP", "0") == "1"
    )

    # Server settings
    host: str = "0.0.0.0"
    port: int = 8025
    transport: Literal["sse", "streamable-http"] = "sse"

    def __post_init__(self):
        """Ensure cache directory exists."""
        self.screenshot_cache_dir.mkdir(parents=True, exist_ok=True)

    @property
    def llm_available(self) -> bool:
        """Check if LLM is available."""
        return bool(self.comet_api_key)


# Data source URLs
SOURCE_URLS = {
    "coinank": {
        "BTC": "https://coinank.com/chart/derivatives/liq-heat-map/btcusdt/1d",
        "ETH": "https://coinank.com/chart/derivatives/liq-heat-map/ethusdt/1d",
    },
    "coinglass": {
        "BTC": "https://www.coinglass.com/pro/futures/LiquidationHeatMap?coin=BTC&type=pair",
        "ETH": "https://www.coinglass.com/pro/futures/LiquidationHeatMap?coin=ETH&type=pair",
    },
}

# Binance ticker API
BINANCE_TICKER_URL = "https://api.binance.com/api/v3/ticker/price"

# Chart detection selectors for each source
CHART_SELECTORS = {
    "coinank": {
        "canvas": "canvas",
        "svg": "svg",
        "container": ".chart-container, .tv-lightweight-charts, [class*='chart'], [class*='heatmap']",
    },
    "coinglass": {
        "canvas": "canvas",
        "svg": "svg",
        "container": ".chart-container, .tv-lightweight-charts, [class*='chart'], [class*='heatmap'], [class*='HeatMap']",
    },
}

# Default config singleton
_config: Optional[Config] = None


def get_config() -> Config:
    """Get the global configuration instance."""
    global _config
    if _config is None:
        _config = Config()
    return _config


def set_config(config: Config) -> None:
    """Set the global configuration instance."""
    global _config
    _config = config
