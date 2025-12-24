"""Configuration and environment variables."""

import os
from pathlib import Path
from typing import Literal

# API Configuration
COMET_API_KEY = os.getenv("COMET_API_KEY", "")
COMET_BASE_URL = os.getenv("COMET_BASE_URL", "https://api.cometapi.com/v1")
COMET_MODEL = os.getenv("COMET_MODEL", "gpt-5.2")
COMET_REASONING = os.getenv("COMET_REASONING", "xhigh")

# Cookie configuration for bypassing restrictions
COINGLASS_COOKIE = os.getenv("COINGLASS_COOKIE", "")
COINANK_COOKIE = os.getenv("COINANK_COOKIE", "")

# Cache and debug
SCREENSHOT_CACHE_DIR = Path(os.getenv("SCREENSHOT_CACHE_DIR", "/tmp/liq-heatmap"))
LOG_LEVEL = os.getenv("LOG_LEVEL", "INFO")
DEBUG_CROP = os.getenv("DEBUG_CROP", "0") == "1"

# Ensure cache directory exists
SCREENSHOT_CACHE_DIR.mkdir(parents=True, exist_ok=True)

# Data source URLs
URLS = {
    "coinank": {
        "BTC": "https://coinank.com/chart/derivatives/liq-heat-map/btcusdt/1d",
        "ETH": "https://coinank.com/chart/derivatives/liq-heat-map/ethusdt/1d",
    },
    "coinglass": {
        "BTC": "https://www.coinglass.com/pro/futures/LiquidationHeatMap?coin=BTC&type=pair",
        "ETH": "https://www.coinglass.com/pro/futures/LiquidationHeatMap?coin=ETH&type=pair",
    },
}

# Binance API for price
BINANCE_TICKER_URL = "https://api.binance.com/api/v3/ticker/price"

# Default values
DEFAULT_CROP_MODE: Literal["dom", "auto", "dom_then_auto"] = "dom_then_auto"
DEFAULT_TOP_N = 5
CONFIDENCE_THRESHOLD = 0.55  # auto mode switches to LLM below this

# Chart detection parameters
CHART_MIN_WIDTH = 400
CHART_MIN_HEIGHT = 200
CHART_ASPECT_RATIO_MIN = 1.2  # width/height should be > this for heatmap
AXIS_PADDING_RIGHT = 70  # pixels for price axis
AXIS_PADDING_DEFAULT = 10

# OCR availability check
def check_ocr_available() -> bool:
    """Check if pytesseract/tesseract is available."""
    try:
        import pytesseract
        pytesseract.get_tesseract_version()
        return True
    except Exception:
        return False

OCR_AVAILABLE = check_ocr_available()

# LLM availability
LLM_AVAILABLE = bool(COMET_API_KEY)
