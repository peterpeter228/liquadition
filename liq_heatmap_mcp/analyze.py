"""
Analysis logic for liquidation heatmaps.
Supports both algorithmic (no LLM) and LLM-based analysis.
"""

import json
import logging
import re
from dataclasses import dataclass, field
from typing import Any, Literal, Optional

import cv2
import httpx
import numpy as np
from PIL import Image
from scipy import ndimage
from scipy.signal import find_peaks

from .config import get_config
from .utils import (
    Timer,
    check_tesseract_available,
    get_current_price,
    image_to_base64,
    pil_to_np,
    resize_image_for_llm,
)

logger = logging.getLogger(__name__)


@dataclass
class LiquidationLevel:
    """A detected liquidation level."""
    side: Literal["above", "below"]
    price: float
    band: tuple[float, float]  # (low, high)
    strength: float  # 0-1
    confidence: float  # 0-1
    evidence: str

    def to_dict(self) -> dict:
        return {
            "side": self.side,
            "price": self.price,
            "band": list(self.band),
            "strength": round(self.strength, 3),
            "confidence": round(self.confidence, 3),
            "evidence": self.evidence,
        }


@dataclass
class AnalysisResult:
    """Result of heatmap analysis."""
    mode_used: Literal["algo", "llm"]
    current_price: Optional[float]
    levels: list[LiquidationLevel]
    confidence_overall: float
    latency_ms: dict[str, int]
    errors: list[str] = field(default_factory=list)

    def to_dict(self) -> dict:
        return {
            "mode_used": self.mode_used,
            "current_price": self.current_price,
            "levels": [level.to_dict() for level in self.levels],
            "confidence_overall": round(self.confidence_overall, 3),
            "latency_ms": self.latency_ms,
            "errors": self.errors if self.errors else None,
        }


class AlgoAnalyzer:
    """
    Algorithmic analyzer that doesn't use LLM.
    Uses image processing and optional OCR.
    """

    def __init__(self):
        self.ocr_available = check_tesseract_available()
        if self.ocr_available:
            logger.info("Tesseract OCR is available")
        else:
            logger.info("Tesseract OCR not available, using fallback methods")

    async def analyze(
        self,
        image: Image.Image,
        symbol: str,
        top_n: int = 5,
    ) -> AnalysisResult:
        """
        Analyze the heatmap image using algorithmic methods.
        
        Steps:
        1. Get current price from Binance
        2. Try to extract price axis mapping via OCR or estimation
        3. Detect intensity peaks in the heatmap
        4. Map peaks to prices and classify as above/below current
        """
        errors: list[str] = []
        latency: dict[str, int] = {}
        
        # Get current price
        with Timer() as price_timer:
            current_price = await get_current_price(symbol)
        latency["price_fetch"] = price_timer.elapsed_ms
        
        if current_price is None:
            errors.append("Failed to fetch current price from Binance")
        
        # Convert image to numpy
        img_np = pil_to_np(image)
        img_h, img_w = img_np.shape[:2]
        
        with Timer() as analyze_timer:
            # Try to get price axis mapping
            price_mapping = await self._get_price_mapping(
                img_np, symbol, current_price, errors
            )
            
            # Extract intensity profile
            intensity_profile = self._extract_intensity_profile(img_np)
            
            # Find peaks
            peaks = self._find_intensity_peaks(intensity_profile, top_n * 2)
            
            # Map peaks to levels
            levels = self._peaks_to_levels(
                peaks, intensity_profile, price_mapping, current_price, img_h, top_n
            )
        
        latency["analyze"] = analyze_timer.elapsed_ms
        
        # Calculate overall confidence
        if levels:
            confidence_overall = sum(l.confidence for l in levels) / len(levels)
        else:
            confidence_overall = 0.0
            errors.append("No liquidation levels detected")
        
        # Reduce confidence if price mapping was estimated
        if price_mapping.get("estimated", False):
            confidence_overall *= 0.7
        
        return AnalysisResult(
            mode_used="algo",
            current_price=current_price,
            levels=levels,
            confidence_overall=confidence_overall,
            latency_ms=latency,
            errors=errors,
        )

    async def _get_price_mapping(
        self,
        img_np: np.ndarray,
        symbol: str,
        current_price: Optional[float],
        errors: list[str],
    ) -> dict:
        """
        Try to extract price axis mapping from the image.
        Returns a dict with 'top_price', 'bottom_price', 'estimated' flag.
        """
        img_h, img_w = img_np.shape[:2]
        
        # Try OCR if available
        if self.ocr_available:
            try:
                prices = self._ocr_price_axis(img_np)
                if prices and len(prices) >= 2:
                    return {
                        "top_price": max(prices),
                        "bottom_price": min(prices),
                        "estimated": False,
                    }
            except Exception as e:
                logger.warning(f"OCR failed: {e}")
                errors.append(f"OCR failed: {str(e)}")
        
        # Fallback: estimate based on current price
        if current_price:
            # Assume chart shows ±15% from current price
            range_pct = 0.15
            return {
                "top_price": current_price * (1 + range_pct),
                "bottom_price": current_price * (1 - range_pct),
                "estimated": True,
            }
        
        # Last resort: use placeholder values
        errors.append("Using placeholder price range - accuracy will be low")
        if symbol == "BTC":
            return {"top_price": 110000, "bottom_price": 80000, "estimated": True}
        else:  # ETH
            return {"top_price": 4500, "bottom_price": 3000, "estimated": True}

    def _ocr_price_axis(self, img_np: np.ndarray) -> list[float]:
        """Extract price values from the right axis using OCR."""
        import pytesseract
        
        img_h, img_w = img_np.shape[:2]
        
        # Extract right side of image (price axis)
        axis_width = min(100, int(img_w * 0.15))
        axis_region = img_np[:, -axis_width:]
        
        # Preprocess for OCR
        gray = cv2.cvtColor(axis_region, cv2.COLOR_BGR2GRAY)
        _, thresh = cv2.threshold(gray, 0, 255, cv2.THRESH_BINARY + cv2.THRESH_OTSU)
        
        # Run OCR
        text = pytesseract.image_to_string(thresh, config="--psm 6 digits")
        
        # Extract numbers
        prices = []
        for match in re.finditer(r"[\d,]+\.?\d*", text):
            try:
                value = float(match.group().replace(",", ""))
                if value > 100:  # Filter out noise
                    prices.append(value)
            except ValueError:
                continue
        
        return sorted(set(prices), reverse=True)

    def _extract_intensity_profile(self, img_np: np.ndarray) -> np.ndarray:
        """
        Extract the vertical intensity profile of the heatmap.
        Focuses on bright/colorful regions that indicate liquidation levels.
        """
        # Convert to HSV
        hsv = cv2.cvtColor(img_np, cv2.COLOR_BGR2HSV)
        
        # Extract value (brightness) and saturation channels
        saturation = hsv[:, :, 1].astype(float)
        value = hsv[:, :, 2].astype(float)
        
        # Heatmap intensity = high saturation * brightness
        # Focus on yellow/green areas (common heatmap colors)
        hue = hsv[:, :, 0]
        
        # Create mask for heatmap colors (yellow-green spectrum: 20-80 in OpenCV hue)
        # Also include red spectrum for some heatmaps
        mask_yellow_green = ((hue >= 20) & (hue <= 80)).astype(float)
        mask_red = ((hue <= 10) | (hue >= 170)).astype(float)
        color_mask = np.maximum(mask_yellow_green, mask_red * 0.8)
        
        # Combine into intensity
        intensity = saturation * value * color_mask / (255 * 255)
        
        # Sum across horizontal axis to get vertical profile
        # Ignore edges (axis regions)
        img_w = img_np.shape[1]
        margin = int(img_w * 0.1)
        intensity_profile = np.mean(intensity[:, margin:-margin], axis=1)
        
        # Smooth the profile
        intensity_profile = ndimage.gaussian_filter1d(intensity_profile, sigma=3)
        
        return intensity_profile

    def _find_intensity_peaks(
        self,
        profile: np.ndarray,
        max_peaks: int,
    ) -> list[tuple[int, float]]:
        """Find peaks in the intensity profile."""
        # Normalize profile
        if profile.max() > 0:
            normalized = profile / profile.max()
        else:
            return []
        
        # Find peaks
        peaks, properties = find_peaks(
            normalized,
            height=0.15,  # Minimum height
            distance=10,  # Minimum distance between peaks
            prominence=0.05,  # Minimum prominence
        )
        
        if len(peaks) == 0:
            return []
        
        # Get peak heights
        heights = properties.get("peak_heights", normalized[peaks])
        
        # Sort by height and take top N
        peak_data = list(zip(peaks, heights))
        peak_data.sort(key=lambda x: x[1], reverse=True)
        
        return peak_data[:max_peaks]

    def _peaks_to_levels(
        self,
        peaks: list[tuple[int, float]],
        profile: np.ndarray,
        price_mapping: dict,
        current_price: Optional[float],
        img_h: int,
        top_n: int,
    ) -> list[LiquidationLevel]:
        """Convert peaks to liquidation levels."""
        levels = []
        
        top_price = price_mapping["top_price"]
        bottom_price = price_mapping["bottom_price"]
        price_range = top_price - bottom_price
        
        for y_pos, strength in peaks:
            # Map y position to price
            # y=0 is top of image (top_price), y=img_h is bottom (bottom_price)
            price_ratio = y_pos / img_h
            price = top_price - (price_ratio * price_range)
            
            # Calculate band (region around peak)
            band_pixels = 15  # pixels around peak
            band_low_y = min(y_pos + band_pixels, img_h - 1)
            band_high_y = max(y_pos - band_pixels, 0)
            
            band_low = top_price - (band_low_y / img_h * price_range)
            band_high = top_price - (band_high_y / img_h * price_range)
            
            # Determine side relative to current price
            if current_price:
                side = "above" if price > current_price else "below"
            else:
                # If no current price, use middle of range
                mid_price = (top_price + bottom_price) / 2
                side = "above" if price > mid_price else "below"
            
            # Calculate confidence based on strength and mapping quality
            base_confidence = min(strength + 0.3, 1.0)
            if price_mapping.get("estimated", False):
                base_confidence *= 0.7
            
            level = LiquidationLevel(
                side=side,
                price=round(price, 2),
                band=(round(band_low, 2), round(band_high, 2)),
                strength=float(strength),
                confidence=float(base_confidence),
                evidence=f"Intensity peak at y={y_pos}, strength={strength:.2f}",
            )
            levels.append(level)
        
        # Sort by strength and take top N
        levels.sort(key=lambda x: x.strength, reverse=True)
        return levels[:top_n]


class LLMAnalyzer:
    """
    LLM-based analyzer using CometAPI (OpenAI-compatible).
    """

    def __init__(self):
        config = get_config()
        self.api_key = config.comet_api_key
        self.base_url = config.comet_base_url
        self.model = config.comet_model
        self.reasoning = config.comet_reasoning

    @property
    def available(self) -> bool:
        return bool(self.api_key)

    async def analyze(
        self,
        image: Image.Image,
        symbol: str,
        top_n: int = 5,
    ) -> AnalysisResult:
        """
        Analyze the heatmap image using LLM vision.
        """
        if not self.available:
            return AnalysisResult(
                mode_used="llm",
                current_price=None,
                levels=[],
                confidence_overall=0.0,
                latency_ms={},
                errors=["LLM not available - COMET_API_KEY not set"],
            )
        
        errors: list[str] = []
        latency: dict[str, int] = {}
        
        # Get current price for validation
        with Timer() as price_timer:
            actual_price = await get_current_price(symbol)
        latency["price_fetch"] = price_timer.elapsed_ms
        
        # Resize image for LLM
        resized_image = resize_image_for_llm(image, max_width=1280)
        image_b64 = image_to_base64(resized_image, format="JPEG")
        
        # Build prompt
        prompt = self._build_prompt(symbol, top_n)
        
        # Call LLM
        with Timer() as llm_timer:
            try:
                response = await self._call_llm(image_b64, prompt)
            except Exception as e:
                logger.error(f"LLM call failed: {e}")
                return AnalysisResult(
                    mode_used="llm",
                    current_price=actual_price,
                    levels=[],
                    confidence_overall=0.0,
                    latency_ms=latency,
                    errors=[f"LLM call failed: {str(e)}"],
                )
        latency["llm"] = llm_timer.elapsed_ms
        
        # Parse response
        try:
            result = self._parse_response(response, actual_price, errors)
            result.latency_ms = latency
            return result
        except Exception as e:
            logger.error(f"Failed to parse LLM response: {e}")
            return AnalysisResult(
                mode_used="llm",
                current_price=actual_price,
                levels=[],
                confidence_overall=0.0,
                latency_ms=latency,
                errors=[f"Failed to parse LLM response: {str(e)}"],
            )

    def _build_prompt(self, symbol: str, top_n: int) -> str:
        return f"""You are analyzing a {symbol}/USDT liquidation heatmap chart.

Identify the top {top_n} most significant liquidation levels visible in the heatmap.
The brighter/more intense regions indicate higher liquidation concentration.

Return your analysis as a JSON object with this exact structure:
{{
  "current_price": <estimated current price from the chart>,
  "levels": [
    {{
      "side": "above" or "below",
      "price": <price level>,
      "band": [<low_price>, <high_price>],
      "strength": <0.0 to 1.0>,
      "confidence": <0.0 to 1.0>,
      "evidence": "<brief explanation>"
    }}
  ],
  "confidence_overall": <0.0 to 1.0>
}}

Rules:
- "side" is relative to the current price you identify
- "strength" indicates how intense/significant the liquidation level appears
- "confidence" indicates how certain you are about this level
- "band" is the price range around the level
- Sort levels by strength (highest first)
- Only return valid JSON, no other text"""

    async def _call_llm(self, image_b64: str, prompt: str) -> str:
        """Call the LLM API with vision input."""
        headers = {
            "Authorization": f"Bearer {self.api_key}",
            "Content-Type": "application/json",
        }
        
        payload = {
            "model": self.model,
            "messages": [
                {
                    "role": "user",
                    "content": [
                        {
                            "type": "image_url",
                            "image_url": {
                                "url": f"data:image/jpeg;base64,{image_b64}",
                            },
                        },
                        {
                            "type": "text",
                            "text": prompt,
                        },
                    ],
                }
            ],
            "max_tokens": 2000,
            "temperature": 0.1,
        }
        
        # Try to add reasoning parameter if supported
        if self.reasoning:
            payload["reasoning_effort"] = self.reasoning
        
        async with httpx.AsyncClient(timeout=60.0) as client:
            response = await client.post(
                f"{self.base_url}/chat/completions",
                headers=headers,
                json=payload,
            )
            
            if response.status_code == 400:
                # Maybe reasoning parameter not supported, retry without it
                if "reasoning_effort" in payload:
                    del payload["reasoning_effort"]
                    response = await client.post(
                        f"{self.base_url}/chat/completions",
                        headers=headers,
                        json=payload,
                    )
            
            response.raise_for_status()
            data = response.json()
            
            return data["choices"][0]["message"]["content"]

    def _parse_response(
        self,
        response: str,
        actual_price: Optional[float],
        errors: list[str],
    ) -> AnalysisResult:
        """Parse the LLM response into an AnalysisResult."""
        # Extract JSON from response (handle markdown code blocks)
        json_match = re.search(r"```(?:json)?\s*([\s\S]*?)```", response)
        if json_match:
            json_str = json_match.group(1)
        else:
            json_str = response
        
        # Clean up and parse
        json_str = json_str.strip()
        data = json.loads(json_str)
        
        # Extract current price and validate
        llm_price = data.get("current_price")
        current_price = llm_price
        
        if actual_price and llm_price:
            price_diff_pct = abs(llm_price - actual_price) / actual_price
            if price_diff_pct > 0.05:  # More than 5% difference
                errors.append(
                    f"LLM price ({llm_price}) differs from actual ({actual_price:.2f}) "
                    f"by {price_diff_pct*100:.1f}% - using actual price"
                )
                current_price = actual_price
        elif actual_price:
            current_price = actual_price
        
        # Parse levels
        levels = []
        for level_data in data.get("levels", []):
            try:
                band = level_data.get("band", [0, 0])
                level = LiquidationLevel(
                    side=level_data["side"],
                    price=float(level_data["price"]),
                    band=(float(band[0]), float(band[1])),
                    strength=float(level_data.get("strength", 0.5)),
                    confidence=float(level_data.get("confidence", 0.5)),
                    evidence=level_data.get("evidence", "LLM detected"),
                )
                levels.append(level)
            except (KeyError, ValueError, TypeError) as e:
                logger.warning(f"Failed to parse level: {e}")
                continue
        
        confidence_overall = data.get("confidence_overall", 0.5)
        if not levels:
            confidence_overall = 0.0
            errors.append("LLM did not return any valid levels")
        
        return AnalysisResult(
            mode_used="llm",
            current_price=current_price,
            levels=levels,
            confidence_overall=confidence_overall,
            latency_ms={},
            errors=errors,
        )


async def analyze_heatmap(
    image: Image.Image,
    symbol: str,
    mode: Literal["algo", "llm", "auto", "compare"] = "auto",
    top_n: int = 5,
) -> dict:
    """
    Main entry point for heatmap analysis.
    
    Args:
        image: The cropped heatmap image
        symbol: Trading symbol (BTC or ETH)
        mode: Analysis mode
        top_n: Number of top levels to return
    
    Returns:
        Analysis result as a dictionary
    """
    algo_analyzer = AlgoAnalyzer()
    llm_analyzer = LLMAnalyzer()
    
    if mode == "algo":
        result = await algo_analyzer.analyze(image, symbol, top_n)
        return result.to_dict()
    
    elif mode == "llm":
        if not llm_analyzer.available:
            return {
                "mode_used": "llm",
                "error": "LLM not available - COMET_API_KEY not set",
                "levels": [],
                "confidence_overall": 0.0,
            }
        result = await llm_analyzer.analyze(image, symbol, top_n)
        return result.to_dict()
    
    elif mode == "auto":
        # Try algo first
        algo_result = await algo_analyzer.analyze(image, symbol, top_n)
        
        # If confidence is low and LLM is available, try LLM
        if algo_result.confidence_overall < 0.55 and llm_analyzer.available:
            llm_result = await llm_analyzer.analyze(image, symbol, top_n)
            if llm_result.confidence_overall > algo_result.confidence_overall:
                result_dict = llm_result.to_dict()
                result_dict["fallback_from"] = "algo"
                result_dict["algo_confidence"] = algo_result.confidence_overall
                return result_dict
        
        return algo_result.to_dict()
    
    elif mode == "compare":
        # Run both analyzers
        algo_result = await algo_analyzer.analyze(image, symbol, top_n)
        
        if llm_analyzer.available:
            llm_result = await llm_analyzer.analyze(image, symbol, top_n)
        else:
            llm_result = AnalysisResult(
                mode_used="llm",
                current_price=None,
                levels=[],
                confidence_overall=0.0,
                latency_ms={},
                errors=["LLM not available - COMET_API_KEY not set"],
            )
        
        # Determine recommendation
        algo_score = algo_result.confidence_overall
        llm_score = llm_result.confidence_overall
        
        algo_latency = sum(algo_result.latency_ms.values())
        llm_latency = sum(llm_result.latency_ms.values())
        
        if llm_score > algo_score + 0.1:
            recommended = "llm"
            reason = f"LLM has higher confidence ({llm_score:.2f} vs {algo_score:.2f})"
        elif algo_score > llm_score:
            recommended = "algo"
            reason = f"Algo has higher confidence ({algo_score:.2f} vs {llm_score:.2f})"
        elif algo_latency < llm_latency * 0.5:
            recommended = "algo"
            reason = f"Similar confidence, but algo is faster ({algo_latency}ms vs {llm_latency}ms)"
        else:
            recommended = "llm" if llm_analyzer.available else "algo"
            reason = "Similar performance"
        
        return {
            "algo_result": algo_result.to_dict(),
            "llm_result": llm_result.to_dict(),
            "comparison": {
                "recommended": recommended,
                "reason": reason,
                "algo_confidence": algo_score,
                "llm_confidence": llm_score,
                "algo_latency_ms": algo_latency,
                "llm_latency_ms": llm_latency,
            },
        }
    
    else:
        raise ValueError(f"Unknown mode: {mode}")
