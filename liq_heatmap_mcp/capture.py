"""Screenshot capture and cropping module using Playwright."""

import asyncio
import base64
import hashlib
import logging
import time
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Literal, Optional

import cv2
import numpy as np
from PIL import Image
from playwright.async_api import async_playwright, Page, Browser

from .config import (
    URLS,
    SCREENSHOT_CACHE_DIR,
    DEBUG_CROP,
    COINGLASS_COOKIE,
    COINANK_COOKIE,
    CHART_MIN_WIDTH,
    CHART_MIN_HEIGHT,
    CHART_ASPECT_RATIO_MIN,
    AXIS_PADDING_RIGHT,
    AXIS_PADDING_DEFAULT,
)

logger = logging.getLogger(__name__)


@dataclass
class CropRect:
    x: int
    y: int
    w: int
    h: int

    def to_dict(self) -> dict:
        return {"x": self.x, "y": self.y, "w": self.w, "h": self.h}


@dataclass
class CaptureResult:
    url: str
    captured_at: str
    crop_rect: CropRect
    image_bytes: bytes
    mime_type: str = "image/png"
    crop_method: str = "dom"
    errors: list[str] = field(default_factory=list)

    def to_dict(self, include_image: bool = False) -> dict:
        result = {
            "url": self.url,
            "captured_at": self.captured_at,
            "crop_rect": self.crop_rect.to_dict(),
            "crop_method": self.crop_method,
        }
        if self.errors:
            result["errors"] = self.errors
        if include_image:
            result["image_base64"] = base64.b64encode(self.image_bytes).decode()
        return result

    def get_resource_uri(self, source: str, symbol: str) -> str:
        """Generate a unique resource URI for this capture."""
        ts = datetime.now(timezone.utc).strftime("%Y%m%d%H%M%S")
        return f"heatmap://{source}/{symbol}/{ts}"


class HeatmapCapture:
    """Handles screenshot capture and cropping for liquidation heatmaps."""

    def __init__(self):
        self._browser: Optional[Browser] = None
        self._last_capture: Optional[CaptureResult] = None
        self._capture_cache: dict[str, CaptureResult] = {}

    async def _ensure_browser(self) -> Browser:
        """Ensure browser is initialized."""
        if self._browser is None:
            pw = await async_playwright().start()
            self._browser = await pw.chromium.launch(
                headless=True,
                args=[
                    "--disable-blink-features=AutomationControlled",
                    "--no-sandbox",
                    "--disable-setuid-sandbox",
                    "--disable-dev-shm-usage",
                ]
            )
        return self._browser

    async def close(self):
        """Close browser if open."""
        if self._browser:
            await self._browser.close()
            self._browser = None

    def get_last_capture(self) -> Optional[CaptureResult]:
        """Get the last capture result."""
        return self._last_capture

    async def capture(
        self,
        source: Literal["coinank", "coinglass"],
        symbol: Literal["BTC", "ETH"],
        timeframe: str = "1d",
        crop: Literal["dom", "auto", "dom_then_auto"] = "dom_then_auto",
        include_axes: bool = True,
        include_histogram: bool = False,
    ) -> CaptureResult:
        """
        Capture the liquidation heatmap chart.
        
        Args:
            source: Data source (coinank or coinglass)
            symbol: Trading pair (BTC or ETH)
            timeframe: Timeframe (currently only 1d supported)
            crop: Cropping strategy
            include_axes: Include price axis on the right
            include_histogram: Include histogram (coinglass only)
        
        Returns:
            CaptureResult with cropped image
        """
        url = URLS.get(source, {}).get(symbol)
        if not url:
            raise ValueError(f"Invalid source/symbol: {source}/{symbol}")

        # Adjust URL for timeframe if needed
        if source == "coinank" and timeframe != "1d":
            url = url.replace("/1d", f"/{timeframe}")

        browser = await self._ensure_browser()
        context = await browser.new_context(
            viewport={"width": 1920, "height": 1080},
            user_agent="Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
        )

        # Set cookies if provided
        if source == "coinglass" and COINGLASS_COOKIE:
            await self._set_cookies(context, COINGLASS_COOKIE, ".coinglass.com")
        elif source == "coinank" and COINANK_COOKIE:
            await self._set_cookies(context, COINANK_COOKIE, ".coinank.com")

        page = await context.new_page()
        errors: list[str] = []
        crop_rect: Optional[CropRect] = None
        crop_method = "dom"

        try:
            logger.info(f"Navigating to {url}")
            await page.goto(url, wait_until="networkidle", timeout=30000)
            
            # Wait for chart to render
            await self._wait_for_chart(page, source)
            
            # Additional wait for animations
            await asyncio.sleep(2)

            # Try DOM cropping first
            if crop in ("dom", "dom_then_auto"):
                try:
                    crop_rect = await self._dom_crop(
                        page, source, include_axes, include_histogram
                    )
                    crop_method = "dom"
                    logger.info(f"DOM crop successful: {crop_rect}")
                except Exception as e:
                    errors.append(f"DOM crop failed: {str(e)}")
                    logger.warning(f"DOM crop failed: {e}")
                    if crop == "dom":
                        raise

            # Capture screenshot
            full_screenshot = await page.screenshot(type="png", full_page=False)
            
            # If DOM crop failed or auto mode, try image-based cropping
            if crop_rect is None or crop == "auto":
                try:
                    crop_rect = self._auto_crop(
                        full_screenshot, include_axes, include_histogram
                    )
                    crop_method = "auto"
                    logger.info(f"Auto crop successful: {crop_rect}")
                except Exception as e:
                    errors.append(f"Auto crop failed: {str(e)}")
                    logger.warning(f"Auto crop failed: {e}")
                    if crop_rect is None:
                        # Fallback: use center portion
                        crop_rect = self._fallback_crop(full_screenshot)
                        crop_method = "fallback"
                        errors.append("Using fallback center crop")

            # Apply crop
            cropped_image = self._apply_crop(full_screenshot, crop_rect)
            
            # Save debug images if enabled
            if DEBUG_CROP:
                self._save_debug_images(full_screenshot, cropped_image, source, symbol)

            result = CaptureResult(
                url=url,
                captured_at=datetime.now(timezone.utc).isoformat(),
                crop_rect=crop_rect,
                image_bytes=cropped_image,
                crop_method=crop_method,
                errors=errors,
            )

            self._last_capture = result
            cache_key = f"{source}_{symbol}_{timeframe}"
            self._capture_cache[cache_key] = result

            return result

        finally:
            await context.close()

    async def _set_cookies(self, context, cookie_str: str, domain: str):
        """Parse and set cookies from a cookie string."""
        cookies = []
        for part in cookie_str.split(";"):
            part = part.strip()
            if "=" in part:
                name, value = part.split("=", 1)
                cookies.append({
                    "name": name.strip(),
                    "value": value.strip(),
                    "domain": domain,
                    "path": "/",
                })
        if cookies:
            await context.add_cookies(cookies)

    async def _wait_for_chart(self, page: Page, source: str):
        """Wait for the chart to be fully rendered."""
        selectors = {
            "coinank": [
                "canvas",
                "svg",
                "[class*='chart']",
                "[class*='heatmap']",
            ],
            "coinglass": [
                "canvas",
                "[class*='liquidation']",
                "[class*='heatmap']",
                "[class*='chart']",
            ],
        }

        for selector in selectors.get(source, ["canvas", "svg"]):
            try:
                await page.wait_for_selector(selector, timeout=10000)
                logger.debug(f"Found element: {selector}")
                break
            except Exception:
                continue

        # Wait for canvas to have content
        try:
            await page.wait_for_function(
                """() => {
                    const canvases = document.querySelectorAll('canvas');
                    for (const c of canvases) {
                        if (c.width > 400 && c.height > 200) return true;
                    }
                    return false;
                }""",
                timeout=15000,
            )
        except Exception as e:
            logger.warning(f"Canvas wait timeout: {e}")

    async def _dom_crop(
        self,
        page: Page,
        source: str,
        include_axes: bool,
        include_histogram: bool,
    ) -> CropRect:
        """Find and return the bounding box of the chart element."""
        
        # Find all candidate elements
        candidates = await page.evaluate("""() => {
            const results = [];
            const elements = document.querySelectorAll('canvas, svg, [class*="chart"], [class*="heatmap"]');
            
            for (const el of elements) {
                const rect = el.getBoundingClientRect();
                if (rect.width < 400 || rect.height < 200) continue;
                
                const score = (
                    rect.width * rect.height * 0.001 +  // Area
                    (rect.width / rect.height > 1.2 ? 50 : 0) +  // Aspect ratio bonus
                    (window.innerWidth / 2 - Math.abs(rect.left + rect.width/2 - window.innerWidth/2)) * 0.1  // Centered bonus
                );
                
                results.push({
                    tagName: el.tagName,
                    className: el.className,
                    x: Math.round(rect.x),
                    y: Math.round(rect.y),
                    width: Math.round(rect.width),
                    height: Math.round(rect.height),
                    score: score,
                });
            }
            
            return results.sort((a, b) => b.score - a.score);
        }""")

        if not candidates:
            raise ValueError("No chart elements found")

        # Select best candidate
        best = candidates[0]
        logger.info(f"Best chart candidate: {best}")

        x = best["x"]
        y = best["y"]
        w = best["width"]
        h = best["height"]

        # Adjust for axes
        if include_axes:
            w += AXIS_PADDING_RIGHT
        else:
            w += AXIS_PADDING_DEFAULT

        # For coinglass, try to exclude histogram if not wanted
        if source == "coinglass" and not include_histogram:
            # Histogram is typically on the right side, reduce width
            w = int(w * 0.85)

        # Ensure bounds are valid
        x = max(0, x - AXIS_PADDING_DEFAULT)
        y = max(0, y - AXIS_PADDING_DEFAULT)

        return CropRect(x=x, y=y, w=w, h=h)

    def _auto_crop(
        self,
        screenshot: bytes,
        include_axes: bool,
        include_histogram: bool,
    ) -> CropRect:
        """Use OpenCV to find the heatmap region automatically."""
        # Convert to numpy array
        nparr = np.frombuffer(screenshot, np.uint8)
        img = cv2.imdecode(nparr, cv2.IMREAD_COLOR)
        
        if img is None:
            raise ValueError("Failed to decode screenshot")

        h, w = img.shape[:2]

        # Convert to HSV for color analysis
        hsv = cv2.cvtColor(img, cv2.COLOR_BGR2HSV)

        # Heatmaps typically have high saturation colors (yellows, greens, reds)
        # and dark backgrounds
        
        # Create mask for saturated colors
        lower_sat = np.array([0, 50, 50])
        upper_sat = np.array([180, 255, 255])
        sat_mask = cv2.inRange(hsv, lower_sat, upper_sat)

        # Also detect dark regions (background of heatmap)
        lower_dark = np.array([0, 0, 0])
        upper_dark = np.array([180, 255, 80])
        dark_mask = cv2.inRange(hsv, lower_dark, upper_dark)

        # Combine masks
        combined = cv2.bitwise_or(sat_mask, dark_mask)

        # Morphological operations to clean up
        kernel = cv2.getStructuringElement(cv2.MORPH_RECT, (15, 15))
        combined = cv2.morphologyEx(combined, cv2.MORPH_CLOSE, kernel)
        combined = cv2.morphologyEx(combined, cv2.MORPH_OPEN, kernel)

        # Find contours
        contours, _ = cv2.findContours(combined, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)

        if not contours:
            raise ValueError("No heatmap region found")

        # Find the largest contour that looks like a chart
        best_contour = None
        best_score = 0

        for contour in contours:
            x, y, cw, ch = cv2.boundingRect(contour)
            area = cw * ch
            aspect = cw / ch if ch > 0 else 0

            # Score based on size and aspect ratio
            if cw < CHART_MIN_WIDTH or ch < CHART_MIN_HEIGHT:
                continue
            if aspect < CHART_ASPECT_RATIO_MIN:
                continue

            # Prefer larger, centered regions
            center_x = x + cw / 2
            center_bonus = 1 - abs(center_x - w / 2) / (w / 2)
            score = area * (1 + center_bonus) * (1 if aspect > 1.5 else 0.8)

            if score > best_score:
                best_score = score
                best_contour = contour

        if best_contour is None:
            raise ValueError("No suitable chart region found")

        x, y, cw, ch = cv2.boundingRect(best_contour)

        # Adjust for axes
        if include_axes:
            cw += AXIS_PADDING_RIGHT
        
        if not include_histogram:
            # Reduce width to exclude potential histogram
            cw = int(cw * 0.9)

        # Add small padding
        x = max(0, x - AXIS_PADDING_DEFAULT)
        y = max(0, y - AXIS_PADDING_DEFAULT)
        cw = min(w - x, cw + AXIS_PADDING_DEFAULT * 2)
        ch = min(h - y, ch + AXIS_PADDING_DEFAULT * 2)

        # Save mask for debugging
        if DEBUG_CROP:
            mask_path = SCREENSHOT_CACHE_DIR / "debug_mask.png"
            cv2.imwrite(str(mask_path), combined)

        return CropRect(x=x, y=y, w=cw, h=ch)

    def _fallback_crop(self, screenshot: bytes) -> CropRect:
        """Fallback to center portion of the image."""
        nparr = np.frombuffer(screenshot, np.uint8)
        img = cv2.imdecode(nparr, cv2.IMREAD_COLOR)
        h, w = img.shape[:2]

        # Take center 70% of width and height
        margin_x = int(w * 0.15)
        margin_y = int(h * 0.15)

        return CropRect(
            x=margin_x,
            y=margin_y,
            w=w - 2 * margin_x,
            h=h - 2 * margin_y,
        )

    def _apply_crop(self, screenshot: bytes, crop_rect: CropRect) -> bytes:
        """Apply crop rectangle to screenshot."""
        nparr = np.frombuffer(screenshot, np.uint8)
        img = cv2.imdecode(nparr, cv2.IMREAD_COLOR)
        
        h, w = img.shape[:2]
        x1 = max(0, crop_rect.x)
        y1 = max(0, crop_rect.y)
        x2 = min(w, crop_rect.x + crop_rect.w)
        y2 = min(h, crop_rect.y + crop_rect.h)

        cropped = img[y1:y2, x1:x2]
        
        # Encode back to PNG
        _, buffer = cv2.imencode(".png", cropped)
        return buffer.tobytes()

    def _save_debug_images(
        self,
        full: bytes,
        cropped: bytes,
        source: str,
        symbol: str,
    ):
        """Save debug images for inspection."""
        ts = datetime.now().strftime("%Y%m%d_%H%M%S")
        
        full_path = SCREENSHOT_CACHE_DIR / f"debug_{source}_{symbol}_{ts}_full.png"
        cropped_path = SCREENSHOT_CACHE_DIR / f"debug_{source}_{symbol}_{ts}_cropped.png"
        
        with open(full_path, "wb") as f:
            f.write(full)
        with open(cropped_path, "wb") as f:
            f.write(cropped)
        
        logger.info(f"Debug images saved: {full_path}, {cropped_path}")


# Global instance
_capture_instance: Optional[HeatmapCapture] = None


def get_capture_instance() -> HeatmapCapture:
    """Get or create the global capture instance."""
    global _capture_instance
    if _capture_instance is None:
        _capture_instance = HeatmapCapture()
    return _capture_instance
