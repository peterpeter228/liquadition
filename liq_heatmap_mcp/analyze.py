"""Analysis module with algo and LLM modes."""

import asyncio
import base64
import io
import json
import logging
import re
import time
from dataclasses import dataclass, field
from typing import Any, Literal, Optional

import cv2
import httpx
import numpy as np
from PIL import Image
from scipy.signal import find_peaks
from scipy.ndimage import gaussian_filter1d

from .config import (
    COMET_API_KEY,
    COMET_BASE_URL,
    COMET_MODEL,
    COMET_REASONING,
    CONFIDENCE_THRESHOLD,
    DEFAULT_TOP_N,
    OCR_AVAILABLE,
    LLM_AVAILABLE,
)
from .price import get_current_price
from .capture import CaptureResult, get_capture_instance

logger = logging.getLogger(__name__)


@dataclass
class LiquidationLevel:
    side: Literal["above", "below"]
    price: float
    band: tuple[float, float]
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
    mode_used: Literal["algo", "llm"]
    latency_ms: dict[str, int]
    current_price: Optional[float]
    levels: list[LiquidationLevel]
    confidence_overall: float
    errors: list[str] = field(default_factory=list)

    def to_dict(self) -> dict:
        result = {
            "mode_used": self.mode_used,
            "latency_ms": self.latency_ms,
            "current_price": self.current_price,
            "levels": [l.to_dict() for l in self.levels],
            "confidence_overall": round(self.confidence_overall, 3),
        }
        if self.errors:
            result["errors"] = self.errors
        return result


@dataclass
class CompareResult:
    algo_result: AnalysisResult
    llm_result: Optional[AnalysisResult]
    recommended: Literal["algo", "llm"]
    recommendation_reason: str

    def to_dict(self) -> dict:
        result = {
            "algo_result": self.algo_result.to_dict(),
            "llm_result": self.llm_result.to_dict() if self.llm_result else None,
            "recommended": self.recommended,
            "recommendation_reason": self.recommendation_reason,
        }
        return result


class AlgoAnalyzer:
    """Algorithm-based heatmap analyzer using OpenCV and optional OCR."""

    def __init__(self):
        self.ocr_available = OCR_AVAILABLE

    async def analyze(
        self,
        image_bytes: bytes,
        symbol: str,
        current_price: Optional[float],
        top_n: int = DEFAULT_TOP_N,
    ) -> AnalysisResult:
        """
        Analyze heatmap using image processing algorithms.
        
        Args:
            image_bytes: PNG image data
            symbol: BTC or ETH
            current_price: Current market price
            top_n: Number of top levels to return
        
        Returns:
            AnalysisResult with detected levels
        """
        start_time = time.time()
        errors: list[str] = []
        
        # Decode image
        nparr = np.frombuffer(image_bytes, np.uint8)
        img = cv2.imdecode(nparr, cv2.IMREAD_COLOR)
        
        if img is None:
            return AnalysisResult(
                mode_used="algo",
                latency_ms={"analyze": int((time.time() - start_time) * 1000)},
                current_price=current_price,
                levels=[],
                confidence_overall=0,
                errors=["Failed to decode image"],
            )

        h, w = img.shape[:2]
        
        # Try to extract price axis mapping
        price_map = None
        axis_confidence = 0.3  # Default low confidence
        
        if self.ocr_available:
            try:
                price_map, axis_confidence = self._extract_price_axis_ocr(img)
            except Exception as e:
                errors.append(f"OCR failed: {str(e)}")
                logger.warning(f"OCR extraction failed: {e}")
        
        if price_map is None:
            # Use relative positioning based on current price
            if current_price:
                # Estimate typical price range (±15% for heatmap)
                price_range = current_price * 0.3
                price_map = {
                    "min": current_price - price_range / 2,
                    "max": current_price + price_range / 2,
                    "height": h,
                }
                axis_confidence = 0.4
                errors.append("Price axis estimated from current price")
            else:
                errors.append("No price mapping available")
                axis_confidence = 0.2

        # Extract intensity profile
        intensity_profile = self._extract_intensity_profile(img)
        
        # Find peaks
        peaks = self._find_peaks(intensity_profile, top_n * 2)
        
        # Convert peaks to levels
        levels: list[LiquidationLevel] = []
        
        for peak_y, strength in peaks[:top_n]:
            if price_map:
                # Map y coordinate to price
                price = self._y_to_price(peak_y, price_map)
                
                # Calculate band (nearby area)
                band_pixels = 10  # ±10 pixels
                band_low = self._y_to_price(min(h - 1, peak_y + band_pixels), price_map)
                band_high = self._y_to_price(max(0, peak_y - band_pixels), price_map)
                
                # Determine side relative to current price
                side = "above" if price > (current_price or price) else "below"
                
                level = LiquidationLevel(
                    side=side,
                    price=round(price, 2),
                    band=(round(band_low, 2), round(band_high, 2)),
                    strength=strength,
                    confidence=axis_confidence * 0.8 + strength * 0.2,
                    evidence=f"Peak detected at y={peak_y}, intensity={strength:.2f}",
                )
                levels.append(level)
            else:
                # Relative positioning only
                relative_pos = 1 - (peak_y / h)
                level = LiquidationLevel(
                    side="above" if relative_pos > 0.5 else "below",
                    price=0,  # Unknown
                    band=(0, 0),
                    strength=strength,
                    confidence=0.3,
                    evidence=f"Peak at relative position {relative_pos:.2f}",
                )
                levels.append(level)

        # Sort levels by strength
        levels.sort(key=lambda x: x.strength, reverse=True)
        levels = levels[:top_n]

        # Calculate overall confidence
        if levels:
            avg_confidence = sum(l.confidence for l in levels) / len(levels)
            confidence_overall = avg_confidence * axis_confidence
        else:
            confidence_overall = 0.1
            errors.append("No liquidation levels detected")

        latency_ms = int((time.time() - start_time) * 1000)

        return AnalysisResult(
            mode_used="algo",
            latency_ms={"analyze": latency_ms},
            current_price=current_price,
            levels=levels,
            confidence_overall=round(confidence_overall, 3),
            errors=errors if errors else [],
        )

    def _extract_price_axis_ocr(self, img: np.ndarray) -> tuple[Optional[dict], float]:
        """Extract price axis values using OCR."""
        import pytesseract
        
        h, w = img.shape[:2]
        
        # Extract right edge (price axis area)
        axis_width = min(100, w // 5)
        axis_region = img[:, w - axis_width:]
        
        # Convert to grayscale and enhance
        gray = cv2.cvtColor(axis_region, cv2.COLOR_BGR2GRAY)
        _, thresh = cv2.threshold(gray, 150, 255, cv2.THRESH_BINARY)
        
        # OCR
        text = pytesseract.image_to_string(thresh, config="--psm 6 digits")
        
        # Parse numbers
        numbers = re.findall(r"[\d,]+\.?\d*", text)
        prices = []
        
        for num_str in numbers:
            try:
                num = float(num_str.replace(",", ""))
                if num > 100:  # Likely a price
                    prices.append(num)
            except ValueError:
                continue
        
        if len(prices) >= 2:
            prices.sort(reverse=True)
            return {
                "min": prices[-1],
                "max": prices[0],
                "height": h,
            }, 0.7
        
        return None, 0.3

    def _extract_intensity_profile(self, img: np.ndarray) -> np.ndarray:
        """Extract intensity profile from heatmap."""
        h, w = img.shape[:2]
        
        # Convert to HSV
        hsv = cv2.cvtColor(img, cv2.COLOR_BGR2HSV)
        
        # Extract value (brightness) and saturation
        saturation = hsv[:, :, 1].astype(float)
        value = hsv[:, :, 2].astype(float)
        
        # High saturation + high value indicates liquidation zones
        # (yellows, greens typically)
        intensity = saturation * value / 255.0
        
        # Exclude axis area (right 10%)
        chart_width = int(w * 0.9)
        intensity = intensity[:, :chart_width]
        
        # Sum along x-axis to get y-profile
        profile = np.sum(intensity, axis=1)
        
        # Normalize
        if profile.max() > 0:
            profile = profile / profile.max()
        
        # Smooth
        profile = gaussian_filter1d(profile, sigma=3)
        
        return profile

    def _find_peaks(
        self,
        profile: np.ndarray,
        n_peaks: int,
    ) -> list[tuple[int, float]]:
        """Find peaks in intensity profile."""
        # Find peaks
        peaks, properties = find_peaks(
            profile,
            height=0.1,
            distance=20,
            prominence=0.05,
        )
        
        if len(peaks) == 0:
            return []
        
        # Get heights
        heights = profile[peaks]
        
        # Sort by height
        sorted_indices = np.argsort(heights)[::-1]
        
        result = []
        for idx in sorted_indices[:n_peaks]:
            peak_y = peaks[idx]
            strength = float(heights[idx])
            result.append((peak_y, strength))
        
        return result

    def _y_to_price(self, y: int, price_map: dict) -> float:
        """Convert y coordinate to price."""
        h = price_map["height"]
        price_min = price_map["min"]
        price_max = price_map["max"]
        
        # y=0 is top (max price), y=h is bottom (min price)
        ratio = y / h
        price = price_max - ratio * (price_max - price_min)
        
        return price


class LLMAnalyzer:
    """LLM-based heatmap analyzer using CometAPI."""

    def __init__(self):
        self.api_key = COMET_API_KEY
        self.base_url = COMET_BASE_URL
        self.model = COMET_MODEL
        self.reasoning = COMET_REASONING

    async def analyze(
        self,
        image_bytes: bytes,
        symbol: str,
        current_price: Optional[float],
        top_n: int = DEFAULT_TOP_N,
    ) -> AnalysisResult:
        """
        Analyze heatmap using LLM vision.
        
        Args:
            image_bytes: PNG image data
            symbol: BTC or ETH
            current_price: Current market price for validation
            top_n: Number of top levels to return
        
        Returns:
            AnalysisResult with detected levels
        """
        start_time = time.time()
        errors: list[str] = []

        if not self.api_key:
            return AnalysisResult(
                mode_used="llm",
                latency_ms={"llm": 0},
                current_price=current_price,
                levels=[],
                confidence_overall=0,
                errors=["COMET_API_KEY not configured"],
            )

        # Compress image for API
        compressed = self._compress_image(image_bytes, max_width=1280)
        image_b64 = base64.b64encode(compressed).decode()

        # Build prompt
        prompt = self._build_prompt(symbol, current_price, top_n)

        try:
            # Call LLM API
            llm_start = time.time()
            response = await self._call_llm(image_b64, prompt)
            llm_time = int((time.time() - llm_start) * 1000)
            
            # Parse response
            result = self._parse_response(response, current_price, symbol)
            result.latency_ms["llm"] = llm_time
            
            # Validate current_price from LLM
            if result.current_price and current_price:
                diff = abs(result.current_price - current_price) / current_price
                if diff > 0.05:  # >5% difference
                    errors.append(f"LLM price ({result.current_price}) differs from market ({current_price})")
                    result.current_price = current_price
                    result.confidence_overall *= 0.8

            result.errors.extend(errors)
            return result

        except Exception as e:
            logger.error(f"LLM analysis failed: {e}")
            return AnalysisResult(
                mode_used="llm",
                latency_ms={"llm": int((time.time() - start_time) * 1000)},
                current_price=current_price,
                levels=[],
                confidence_overall=0,
                errors=[f"LLM API error: {str(e)}"],
            )

    def _compress_image(self, image_bytes: bytes, max_width: int = 1280) -> bytes:
        """Compress image for API call."""
        img = Image.open(io.BytesIO(image_bytes))
        
        # Resize if needed
        if img.width > max_width:
            ratio = max_width / img.width
            new_size = (max_width, int(img.height * ratio))
            img = img.resize(new_size, Image.Resampling.LANCZOS)
        
        # Convert to JPEG
        buffer = io.BytesIO()
        img.convert("RGB").save(buffer, format="JPEG", quality=85)
        return buffer.getvalue()

    def _build_prompt(self, symbol: str, current_price: Optional[float], top_n: int) -> str:
        price_info = f"Current {symbol} price is approximately ${current_price:,.2f}." if current_price else ""
        
        return f"""Analyze this {symbol}/USDT liquidation heatmap image. {price_info}

Identify the top {top_n} most significant liquidation levels (areas with high concentration of liquidation orders).

For each level, provide:
1. side: "above" or "below" the current price
2. price: the exact price level
3. band: [low, high] price range of the liquidation cluster
4. strength: 0-1 score indicating intensity of liquidation orders
5. confidence: 0-1 score for your confidence in this detection
6. evidence: brief explanation of why you identified this level

Respond ONLY with a valid JSON object in this exact format:
{{
  "current_price": <number>,
  "levels": [
    {{
      "side": "above" | "below",
      "price": <number>,
      "band": [<low>, <high>],
      "strength": <0-1>,
      "confidence": <0-1>,
      "evidence": "<string>"
    }}
  ],
  "confidence_overall": <0-1>,
  "notes": "<any additional observations>"
}}

Be precise with price values. Look for bright yellow/green areas indicating high liquidation density."""

    async def _call_llm(self, image_b64: str, prompt: str) -> dict:
        """Call the LLM API."""
        headers = {
            "Authorization": f"Bearer {self.api_key}",
            "Content-Type": "application/json",
        }

        # Build request body
        body = {
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
        }

        # Try to add reasoning parameter
        if self.reasoning:
            body["reasoning_effort"] = self.reasoning

        async with httpx.AsyncClient(timeout=60) as client:
            response = await client.post(
                f"{self.base_url}/chat/completions",
                headers=headers,
                json=body,
            )
            
            # If reasoning parameter not supported, retry without it
            if response.status_code == 400 and self.reasoning:
                del body["reasoning_effort"]
                response = await client.post(
                    f"{self.base_url}/chat/completions",
                    headers=headers,
                    json=body,
                )
            
            response.raise_for_status()
            return response.json()

    def _parse_response(
        self,
        response: dict,
        current_price: Optional[float],
        symbol: str,
    ) -> AnalysisResult:
        """Parse LLM response into AnalysisResult."""
        errors: list[str] = []
        
        try:
            content = response["choices"][0]["message"]["content"]
            
            # Extract JSON from response
            json_match = re.search(r"\{[\s\S]*\}", content)
            if not json_match:
                raise ValueError("No JSON found in response")
            
            data = json.loads(json_match.group())
            
            # Parse levels
            levels: list[LiquidationLevel] = []
            for level_data in data.get("levels", []):
                try:
                    level = LiquidationLevel(
                        side=level_data.get("side", "above"),
                        price=float(level_data.get("price", 0)),
                        band=tuple(level_data.get("band", [0, 0])),
                        strength=float(level_data.get("strength", 0.5)),
                        confidence=float(level_data.get("confidence", 0.5)),
                        evidence=str(level_data.get("evidence", "")),
                    )
                    levels.append(level)
                except Exception as e:
                    errors.append(f"Failed to parse level: {e}")
            
            llm_price = data.get("current_price")
            confidence_overall = float(data.get("confidence_overall", 0.5))
            
            return AnalysisResult(
                mode_used="llm",
                latency_ms={},
                current_price=llm_price if llm_price else current_price,
                levels=levels,
                confidence_overall=confidence_overall,
                errors=errors,
            )
            
        except Exception as e:
            logger.error(f"Failed to parse LLM response: {e}")
            return AnalysisResult(
                mode_used="llm",
                latency_ms={},
                current_price=current_price,
                levels=[],
                confidence_overall=0,
                errors=[f"Failed to parse response: {str(e)}"],
            )


class HeatmapAnalyzer:
    """Main analyzer that supports algo, llm, auto, and compare modes."""

    def __init__(self):
        self.algo = AlgoAnalyzer()
        self.llm = LLMAnalyzer()

    async def analyze(
        self,
        image_bytes: bytes,
        source: str,
        symbol: str,
        timeframe: str = "1d",
        mode: Literal["algo", "llm", "auto", "compare"] = "auto",
        top_n: int = DEFAULT_TOP_N,
    ) -> AnalysisResult | CompareResult:
        """
        Analyze heatmap image.
        
        Args:
            image_bytes: Image data
            source: Data source (coinank/coinglass)
            symbol: BTC or ETH
            timeframe: Timeframe
            mode: Analysis mode
            top_n: Number of levels to return
        
        Returns:
            AnalysisResult or CompareResult depending on mode
        """
        # Get current price
        current_price = await get_current_price(symbol)
        
        if mode == "compare":
            return await self._compare(image_bytes, symbol, current_price, top_n)
        elif mode == "llm":
            if not LLM_AVAILABLE:
                return AnalysisResult(
                    mode_used="llm",
                    latency_ms={},
                    current_price=current_price,
                    levels=[],
                    confidence_overall=0,
                    errors=["LLM mode requested but COMET_API_KEY not set"],
                )
            return await self.llm.analyze(image_bytes, symbol, current_price, top_n)
        elif mode == "algo":
            return await self.algo.analyze(image_bytes, symbol, current_price, top_n)
        else:  # auto
            return await self._auto(image_bytes, symbol, current_price, top_n)

    async def _auto(
        self,
        image_bytes: bytes,
        symbol: str,
        current_price: Optional[float],
        top_n: int,
    ) -> AnalysisResult:
        """Auto mode: try algo first, fall back to LLM if confidence is low."""
        algo_result = await self.algo.analyze(image_bytes, symbol, current_price, top_n)
        
        if algo_result.confidence_overall >= CONFIDENCE_THRESHOLD:
            return algo_result
        
        if not LLM_AVAILABLE:
            algo_result.errors.append(
                f"Confidence ({algo_result.confidence_overall:.2f}) below threshold "
                f"({CONFIDENCE_THRESHOLD}), but LLM not available"
            )
            return algo_result
        
        # Try LLM
        llm_result = await self.llm.analyze(image_bytes, symbol, current_price, top_n)
        
        if llm_result.confidence_overall > algo_result.confidence_overall:
            llm_result.errors.append(
                f"Switched from algo (confidence={algo_result.confidence_overall:.2f}) to LLM"
            )
            return llm_result
        
        return algo_result

    async def _compare(
        self,
        image_bytes: bytes,
        symbol: str,
        current_price: Optional[float],
        top_n: int,
    ) -> CompareResult:
        """Compare mode: run both algo and LLM, return comparison."""
        # Run both in parallel
        algo_task = self.algo.analyze(image_bytes, symbol, current_price, top_n)
        
        if LLM_AVAILABLE:
            llm_task = self.llm.analyze(image_bytes, symbol, current_price, top_n)
            algo_result, llm_result = await asyncio.gather(algo_task, llm_task)
        else:
            algo_result = await algo_task
            llm_result = None

        # Determine recommendation
        if llm_result is None:
            recommended = "algo"
            reason = "LLM not available (COMET_API_KEY not set)"
        elif llm_result.confidence_overall > algo_result.confidence_overall + 0.1:
            recommended = "llm"
            reason = f"LLM has higher confidence ({llm_result.confidence_overall:.2f} vs {algo_result.confidence_overall:.2f})"
        elif algo_result.confidence_overall > llm_result.confidence_overall + 0.1:
            recommended = "algo"
            reason = f"Algo has higher confidence ({algo_result.confidence_overall:.2f} vs {llm_result.confidence_overall:.2f})"
        else:
            # Similar confidence, prefer faster
            algo_latency = algo_result.latency_ms.get("analyze", 0)
            llm_latency = llm_result.latency_ms.get("llm", float("inf"))
            
            if algo_latency < llm_latency * 0.5:
                recommended = "algo"
                reason = f"Similar confidence but algo is faster ({algo_latency}ms vs {llm_latency}ms)"
            else:
                recommended = "llm"
                reason = f"Similar confidence, LLM preferred for accuracy"

        return CompareResult(
            algo_result=algo_result,
            llm_result=llm_result,
            recommended=recommended,
            recommendation_reason=reason,
        )


# Global instance
_analyzer_instance: Optional[HeatmapAnalyzer] = None


def get_analyzer_instance() -> HeatmapAnalyzer:
    """Get or create the global analyzer instance."""
    global _analyzer_instance
    if _analyzer_instance is None:
        _analyzer_instance = HeatmapAnalyzer()
    return _analyzer_instance
