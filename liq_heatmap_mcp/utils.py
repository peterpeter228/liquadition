"""
Utility functions for the Liquidation Heatmap MCP Server.
"""

import base64
import hashlib
import io
import logging
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional, Tuple

import httpx
import numpy as np
from PIL import Image

from .config import BINANCE_TICKER_URL, get_config

logger = logging.getLogger(__name__)


def setup_logging():
    """Configure logging based on config."""
    config = get_config()
    logging.basicConfig(
        level=getattr(logging, config.log_level.upper(), logging.INFO),
        format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
    )


def get_timestamp() -> str:
    """Get current UTC timestamp in ISO format."""
    return datetime.now(timezone.utc).isoformat()


def generate_resource_uri(source: str, symbol: str, timestamp: str) -> str:
    """Generate a unique resource URI for an image."""
    hash_input = f"{source}:{symbol}:{timestamp}"
    hash_value = hashlib.md5(hash_input.encode()).hexdigest()[:12]
    return f"heatmap://{source}/{symbol.lower()}/{hash_value}"


async def get_current_price(symbol: str) -> Optional[float]:
    """Get current price from Binance API."""
    ticker_symbol = f"{symbol.upper()}USDT"
    try:
        async with httpx.AsyncClient(timeout=10.0) as client:
            response = await client.get(
                BINANCE_TICKER_URL,
                params={"symbol": ticker_symbol}
            )
            response.raise_for_status()
            data = response.json()
            return float(data["price"])
    except Exception as e:
        logger.warning(f"Failed to get price for {ticker_symbol}: {e}")
        return None


def image_to_base64(image: Image.Image, format: str = "PNG") -> str:
    """Convert PIL Image to base64 string."""
    buffer = io.BytesIO()
    image.save(buffer, format=format)
    return base64.b64encode(buffer.getvalue()).decode("utf-8")


def base64_to_image(b64_string: str) -> Image.Image:
    """Convert base64 string to PIL Image."""
    image_data = base64.b64decode(b64_string)
    return Image.open(io.BytesIO(image_data))


def bytes_to_base64(data: bytes) -> str:
    """Convert bytes to base64 string."""
    return base64.b64encode(data).decode("utf-8")


def image_to_bytes(image: Image.Image, format: str = "PNG") -> bytes:
    """Convert PIL Image to bytes."""
    buffer = io.BytesIO()
    image.save(buffer, format=format)
    return buffer.getvalue()


def resize_image_for_llm(image: Image.Image, max_width: int = 1280) -> Image.Image:
    """Resize image to suitable size for LLM vision input."""
    if image.width <= max_width:
        return image
    
    ratio = max_width / image.width
    new_height = int(image.height * ratio)
    return image.resize((max_width, new_height), Image.Resampling.LANCZOS)


def save_debug_image(image: Image.Image, name: str, suffix: str = "") -> Optional[Path]:
    """Save image to cache directory for debugging."""
    config = get_config()
    if not config.debug_crop:
        return None
    
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    filename = f"{name}_{timestamp}{suffix}.png"
    filepath = config.screenshot_cache_dir / filename
    image.save(filepath)
    logger.debug(f"Saved debug image: {filepath}")
    return filepath


def np_to_pil(arr: np.ndarray) -> Image.Image:
    """Convert numpy array (BGR or RGB) to PIL Image."""
    if len(arr.shape) == 3 and arr.shape[2] == 3:
        # Assume BGR from OpenCV, convert to RGB
        import cv2
        arr = cv2.cvtColor(arr, cv2.COLOR_BGR2RGB)
    return Image.fromarray(arr)


def pil_to_np(image: Image.Image) -> np.ndarray:
    """Convert PIL Image to numpy array (BGR for OpenCV)."""
    import cv2
    arr = np.array(image)
    if len(arr.shape) == 3 and arr.shape[2] == 3:
        arr = cv2.cvtColor(arr, cv2.COLOR_RGB2BGR)
    return arr


class Timer:
    """Simple context manager for timing operations."""
    
    def __init__(self):
        self.start_time: Optional[float] = None
        self.end_time: Optional[float] = None
    
    def __enter__(self):
        self.start_time = time.perf_counter()
        return self
    
    def __exit__(self, *args):
        self.end_time = time.perf_counter()
    
    @property
    def elapsed_ms(self) -> int:
        """Get elapsed time in milliseconds."""
        if self.start_time is None or self.end_time is None:
            return 0
        return int((self.end_time - self.start_time) * 1000)


def check_tesseract_available() -> bool:
    """Check if Tesseract OCR is available."""
    try:
        import pytesseract
        pytesseract.get_tesseract_version()
        return True
    except Exception:
        return False


# Cache for image resources (simple in-memory cache)
_image_cache: dict[str, bytes] = {}


def cache_image(uri: str, data: bytes) -> None:
    """Cache image data by URI."""
    _image_cache[uri] = data
    # Limit cache size (keep last 20 images)
    if len(_image_cache) > 20:
        oldest_key = next(iter(_image_cache))
        del _image_cache[oldest_key]


def get_cached_image(uri: str) -> Optional[bytes]:
    """Get cached image data by URI."""
    return _image_cache.get(uri)


def clear_image_cache() -> None:
    """Clear the image cache."""
    _image_cache.clear()


# Store for last capture result
_last_capture: dict = {}


def set_last_capture(data: dict) -> None:
    """Store the last capture result."""
    global _last_capture
    _last_capture = data


def get_last_capture() -> dict:
    """Get the last capture result."""
    return _last_capture
