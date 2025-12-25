"""
Screenshot capture and cropping logic for liquidation heatmaps.
"""

import asyncio
import logging
from dataclasses import dataclass
from typing import Literal, Optional, Tuple

import cv2
import numpy as np
from PIL import Image
from playwright.async_api import async_playwright, Browser, Page, ElementHandle

from .config import CHART_SELECTORS, SOURCE_URLS, get_config
from .utils import (
    Timer,
    np_to_pil,
    pil_to_np,
    save_debug_image,
)

logger = logging.getLogger(__name__)


@dataclass
class CropRect:
    """Rectangle representing a crop area."""
    x: int
    y: int
    w: int
    h: int

    def to_dict(self) -> dict:
        return {"x": self.x, "y": self.y, "w": self.w, "h": self.h}

    @classmethod
    def from_bbox(cls, bbox: dict) -> "CropRect":
        return cls(
            x=int(bbox["x"]),
            y=int(bbox["y"]),
            w=int(bbox["width"]),
            h=int(bbox["height"]),
        )


@dataclass
class CaptureResult:
    """Result of a capture operation."""
    image: Image.Image
    crop_rect: CropRect
    url: str
    captured_at: str
    method: str  # "dom" or "auto"
    errors: list[str]


class HeatmapCapture:
    """Handles capturing and cropping liquidation heatmaps."""

    def __init__(self):
        self.browser: Optional[Browser] = None
        self._playwright = None

    async def _ensure_browser(self) -> Browser:
        """Ensure browser is initialized."""
        if self.browser is None:
            self._playwright = await async_playwright().start()
            self.browser = await self._playwright.chromium.launch(
                headless=True,
                args=[
                    "--no-sandbox",
                    "--disable-setuid-sandbox",
                    "--disable-dev-shm-usage",
                    "--disable-gpu",
                ]
            )
        return self.browser

    async def close(self):
        """Close browser and cleanup."""
        if self.browser:
            await self.browser.close()
            self.browser = None
        if self._playwright:
            await self._playwright.stop()
            self._playwright = None

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
        Capture and crop the heatmap chart.
        
        Args:
            source: Data source (coinank or coinglass)
            symbol: Trading symbol (BTC or ETH)
            timeframe: Chart timeframe (currently only 1d supported)
            crop: Cropping strategy
            include_axes: Whether to include price axes
            include_histogram: Whether to include histogram (coinglass)
        
        Returns:
            CaptureResult with cropped image and metadata
        """
        from .utils import get_timestamp

        config = get_config()
        url = SOURCE_URLS[source][symbol]
        errors: list[str] = []
        
        browser = await self._ensure_browser()
        context = await browser.new_context(
            viewport={"width": 1920, "height": 1080},
            device_scale_factor=1,
        )
        
        # Add cookies if available
        cookie = config.coinglass_cookie if source == "coinglass" else config.coinank_cookie
        if cookie:
            await self._set_cookies(context, source, cookie)
        
        page = await context.new_page()
        captured_at = get_timestamp()
        
        try:
            # Navigate and wait for page load
            await page.goto(url, wait_until="networkidle", timeout=30000)
            await asyncio.sleep(2)  # Extra wait for chart rendering
            
            # Try DOM-based cropping first
            crop_rect = None
            method = "auto"
            
            if crop in ("dom", "dom_then_auto"):
                try:
                    crop_rect = await self._dom_crop(
                        page, source, include_axes, include_histogram
                    )
                    method = "dom"
                    logger.info(f"DOM crop successful: {crop_rect}")
                except Exception as e:
                    logger.warning(f"DOM crop failed: {e}")
                    errors.append(f"DOM crop failed: {str(e)}")
                    if crop == "dom":
                        raise
            
            # Take full screenshot
            screenshot_bytes = await page.screenshot(type="png", full_page=False)
            full_image = Image.open(__import__("io").BytesIO(screenshot_bytes))
            
            # Save debug image
            save_debug_image(full_image, f"{source}_{symbol}_full")
            
            # Apply auto crop if needed
            if crop_rect is None or crop in ("auto",):
                try:
                    crop_rect = await self._auto_crop(
                        full_image, include_axes, include_histogram
                    )
                    method = "auto"
                    logger.info(f"Auto crop successful: {crop_rect}")
                except Exception as e:
                    logger.warning(f"Auto crop failed: {e}")
                    errors.append(f"Auto crop failed: {str(e)}")
                    # Use a reasonable default crop
                    crop_rect = self._default_crop(full_image)
                    method = "fallback"
            
            # Crop the image
            cropped = full_image.crop((
                crop_rect.x,
                crop_rect.y,
                crop_rect.x + crop_rect.w,
                crop_rect.y + crop_rect.h,
            ))
            
            # Save debug cropped image
            save_debug_image(cropped, f"{source}_{symbol}_cropped")
            
            return CaptureResult(
                image=cropped,
                crop_rect=crop_rect,
                url=url,
                captured_at=captured_at,
                method=method,
                errors=errors,
            )
            
        finally:
            await page.close()
            await context.close()

    async def _set_cookies(self, context, source: str, cookie_string: str):
        """Set cookies for the browser context."""
        domain = ".coinglass.com" if source == "coinglass" else ".coinank.com"
        cookies = []
        for part in cookie_string.split(";"):
            if "=" in part:
                name, value = part.strip().split("=", 1)
                cookies.append({
                    "name": name,
                    "value": value,
                    "domain": domain,
                    "path": "/",
                })
        if cookies:
            await context.add_cookies(cookies)

    async def _dom_crop(
        self,
        page: Page,
        source: str,
        include_axes: bool,
        include_histogram: bool,
    ) -> CropRect:
        """
        Use DOM analysis to find and crop the chart element.
        
        This method:
        1. Waits for chart elements to be ready
        2. Finds all canvas/svg elements
        3. Scores them to find the most likely heatmap
        4. Returns the bounding box with appropriate padding
        """
        selectors = CHART_SELECTORS[source]
        
        # Wait for canvas or svg elements
        try:
            await page.wait_for_selector(
                f"{selectors['canvas']}, {selectors['svg']}",
                timeout=15000,
                state="visible"
            )
        except Exception:
            # Try container selectors as fallback
            await page.wait_for_selector(
                selectors["container"],
                timeout=10000,
                state="visible"
            )
        
        # Find all potential chart elements
        elements = await page.query_selector_all(
            f"{selectors['canvas']}, {selectors['svg']}"
        )
        
        if not elements:
            raise ValueError("No chart elements found")
        
        # Score each element to find the best heatmap candidate
        best_element = None
        best_score = -1
        viewport_size = page.viewport_size
        
        for element in elements:
            try:
                bbox = await element.bounding_box()
                if bbox is None:
                    continue
                
                # Skip very small elements
                if bbox["width"] < 200 or bbox["height"] < 150:
                    continue
                
                # Calculate score based on:
                # 1. Area (larger is better)
                # 2. Position (centered horizontally is better)
                # 3. Aspect ratio (wide charts are better for heatmaps)
                
                area = bbox["width"] * bbox["height"]
                center_x = bbox["x"] + bbox["width"] / 2
                viewport_center = viewport_size["width"] / 2
                center_distance = abs(center_x - viewport_center) / viewport_center
                
                aspect_ratio = bbox["width"] / bbox["height"]
                # Ideal aspect ratio for heatmap is around 1.5-3
                aspect_score = 1.0 - abs(aspect_ratio - 2.0) / 2.0
                aspect_score = max(0, aspect_score)
                
                score = (
                    area * 0.4 +
                    (1 - center_distance) * 1000 * 0.3 +
                    aspect_score * 1000 * 0.3
                )
                
                logger.debug(
                    f"Element score: {score:.0f} "
                    f"(area={area}, center_dist={center_distance:.2f}, "
                    f"aspect={aspect_ratio:.2f})"
                )
                
                if score > best_score:
                    best_score = score
                    best_element = element
                    
            except Exception as e:
                logger.debug(f"Error scoring element: {e}")
                continue
        
        if best_element is None:
            raise ValueError("No suitable chart element found")
        
        bbox = await best_element.bounding_box()
        
        # Adjust bounding box
        x = int(bbox["x"])
        y = int(bbox["y"])
        w = int(bbox["width"])
        h = int(bbox["height"])
        
        # Add padding for axes if requested
        if include_axes:
            # Add right padding for price axis
            axis_padding = 80
            w = min(w + axis_padding, viewport_size["width"] - x)
        
        # For coinglass, handle histogram
        if source == "coinglass" and not include_histogram:
            # Try to exclude the right histogram by limiting width
            # Heuristic: histogram is usually about 15-20% of total width
            max_chart_width = int(viewport_size["width"] * 0.75)
            if w > max_chart_width:
                w = max_chart_width
        
        # Add small padding around the chart
        padding = 5
        x = max(0, x - padding)
        y = max(0, y - padding)
        w = min(w + 2 * padding, viewport_size["width"] - x)
        h = min(h + 2 * padding, viewport_size["height"] - y)
        
        return CropRect(x=x, y=y, w=w, h=h)

    async def _auto_crop(
        self,
        image: Image.Image,
        include_axes: bool,
        include_histogram: bool,
    ) -> CropRect:
        """
        Use OpenCV to automatically detect and crop the heatmap region.
        
        This method:
        1. Converts to HSV and creates a mask for high-saturation regions
        2. Applies morphological operations to clean up the mask
        3. Finds the largest contour that looks like a heatmap
        4. Returns the bounding box
        """
        img_np = pil_to_np(image)
        hsv = cv2.cvtColor(img_np, cv2.COLOR_BGR2HSV)
        
        # Create mask for colorful (high saturation) regions
        # Heatmaps typically have high saturation colors
        lower_sat = np.array([0, 50, 50])
        upper_sat = np.array([180, 255, 255])
        mask = cv2.inRange(hsv, lower_sat, upper_sat)
        
        # Also detect dark background regions (common in heatmaps)
        gray = cv2.cvtColor(img_np, cv2.COLOR_BGR2GRAY)
        _, dark_mask = cv2.threshold(gray, 60, 255, cv2.THRESH_BINARY_INV)
        
        # Combine masks
        combined_mask = cv2.bitwise_or(mask, dark_mask)
        
        # Morphological operations to clean up
        kernel = cv2.getStructuringElement(cv2.MORPH_RECT, (15, 15))
        combined_mask = cv2.morphologyEx(combined_mask, cv2.MORPH_CLOSE, kernel)
        combined_mask = cv2.morphologyEx(combined_mask, cv2.MORPH_OPEN, kernel)
        
        # Save debug mask
        if get_config().debug_crop:
            mask_image = np_to_pil(combined_mask)
            save_debug_image(mask_image, "auto_crop_mask")
        
        # Find contours
        contours, _ = cv2.findContours(
            combined_mask, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE
        )
        
        if not contours:
            raise ValueError("No contours found in image")
        
        # Find the largest contour that looks like a chart
        best_contour = None
        best_score = -1
        img_h, img_w = img_np.shape[:2]
        
        for contour in contours:
            x, y, w, h = cv2.boundingRect(contour)
            area = w * h
            
            # Skip very small regions
            if area < img_w * img_h * 0.1:
                continue
            
            # Score based on size, position, and aspect ratio
            aspect = w / h if h > 0 else 0
            center_x = x + w / 2
            
            # Prefer centered, wide regions
            center_score = 1 - abs(center_x - img_w / 2) / (img_w / 2)
            aspect_score = 1.0 if 1.0 < aspect < 4.0 else 0.5
            size_score = area / (img_w * img_h)
            
            score = center_score * 0.3 + aspect_score * 0.3 + size_score * 0.4
            
            if score > best_score:
                best_score = score
                best_contour = contour
        
        if best_contour is None:
            raise ValueError("No suitable chart region found")
        
        x, y, w, h = cv2.boundingRect(best_contour)
        
        # Adjust for axes
        if include_axes:
            # Extend right side for price axis
            axis_width = 80
            w = min(w + axis_width, img_w - x)
        
        # Handle histogram exclusion
        if not include_histogram:
            # Limit to ~75% of image width from the left
            max_w = int(img_w * 0.75)
            if w > max_w and x < img_w * 0.2:
                w = max_w
        
        # Add small padding
        padding = 10
        x = max(0, x - padding)
        y = max(0, y - padding)
        w = min(w + 2 * padding, img_w - x)
        h = min(h + 2 * padding, img_h - y)
        
        return CropRect(x=x, y=y, w=w, h=h)

    def _default_crop(self, image: Image.Image) -> CropRect:
        """Return a default crop that covers most of the image."""
        w, h = image.size
        # Use center 80% of the image
        margin_x = int(w * 0.1)
        margin_y = int(h * 0.1)
        return CropRect(
            x=margin_x,
            y=margin_y,
            w=w - 2 * margin_x,
            h=h - 2 * margin_y,
        )


# Global capture instance
_capture_instance: Optional[HeatmapCapture] = None


async def get_capture_instance() -> HeatmapCapture:
    """Get or create the global capture instance."""
    global _capture_instance
    if _capture_instance is None:
        _capture_instance = HeatmapCapture()
    return _capture_instance


async def cleanup_capture():
    """Cleanup the global capture instance."""
    global _capture_instance
    if _capture_instance is not None:
        await _capture_instance.close()
        _capture_instance = None
