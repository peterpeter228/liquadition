"""MCP Server implementation with FastMCP."""

import asyncio
import base64
import json
import logging
import time
from datetime import datetime, timezone
from typing import Any, Literal, Optional

from fastmcp import FastMCP

from .capture import CaptureResult, get_capture_instance
from .analyze import AnalysisResult, CompareResult, get_analyzer_instance
from .report import generate_report
from .config import LOG_LEVEL, SCREENSHOT_CACHE_DIR

# Configure logging
logging.basicConfig(
    level=getattr(logging, LOG_LEVEL),
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
)
logger = logging.getLogger(__name__)

# Create FastMCP server
mcp = FastMCP(
    name="Liquidation Heatmap MCP",
    version="0.1.0",
    description="Capture and analyze BTC/ETH liquidation heatmaps from Coinank and Coinglass",
)

# Resource storage for captured images
_image_resources: dict[str, bytes] = {}


def _store_image_resource(uri: str, image_bytes: bytes) -> None:
    """Store image for resource retrieval."""
    _image_resources[uri] = image_bytes
    # Limit cache size
    if len(_image_resources) > 20:
        oldest = list(_image_resources.keys())[0]
        del _image_resources[oldest]


@mcp.resource("heatmap://{source}/{symbol}/{timestamp}")
async def get_heatmap_image(source: str, symbol: str, timestamp: str) -> bytes:
    """Retrieve a captured heatmap image by URI."""
    uri = f"heatmap://{source}/{symbol}/{timestamp}"
    if uri in _image_resources:
        return _image_resources[uri]
    raise ValueError(f"Image not found: {uri}")


@mcp.tool()
async def heatmap_capture(
    source: Literal["coinank", "coinglass"] = "coinglass",
    symbol: Literal["BTC", "ETH"] = "BTC",
    timeframe: str = "1d",
    crop: Literal["dom", "auto", "dom_then_auto"] = "dom_then_auto",
    include_axes: bool = True,
    include_histogram: bool = False,
    image_return: Literal["resource", "image", "none"] = "resource",
) -> dict[str, Any]:
    """
    Capture a liquidation heatmap chart screenshot.
    
    Opens the webpage and captures only the chart area (excluding navigation,
    sidebars, and other UI elements).
    
    Args:
        source: Data source - "coinank" or "coinglass"
        symbol: Trading pair - "BTC" or "ETH"
        timeframe: Chart timeframe (currently "1d" supported)
        crop: Cropping strategy:
            - "dom": Use DOM element detection
            - "auto": Use image-based detection (OpenCV)
            - "dom_then_auto": Try DOM first, fall back to auto
        include_axes: Include price axis on the right (default true)
        include_histogram: Include histogram on coinglass (default false)
        image_return: How to return the image:
            - "resource": Return as MCP resource URI (recommended)
            - "image": Return as base64 embedded image
            - "none": Don't return image data
    
    Returns:
        JSON with url, captured_at, crop_rect, and image reference
    """
    start_time = time.time()
    logger.info(f"Capturing heatmap: {source}/{symbol}/{timeframe}")
    
    try:
        capture = get_capture_instance()
        result: CaptureResult = await capture.capture(
            source=source,
            symbol=symbol,
            timeframe=timeframe,
            crop=crop,
            include_axes=include_axes,
            include_histogram=include_histogram,
        )
        
        capture_ms = int((time.time() - start_time) * 1000)
        
        # Build response
        response = {
            "url": result.url,
            "captured_at": result.captured_at,
            "crop_rect": result.crop_rect.to_dict(),
            "crop_method": result.crop_method,
            "latency_ms": {"capture": capture_ms},
        }
        
        if result.errors:
            response["errors"] = result.errors
        
        # Handle image return
        if image_return == "resource":
            uri = result.get_resource_uri(source, symbol)
            _store_image_resource(uri, result.image_bytes)
            response["image"] = {
                "kind": "resource",
                "uri": uri,
                "mimeType": result.mime_type,
            }
        elif image_return == "image":
            # Return as embedded base64 (not recommended for large images)
            response["image"] = {
                "kind": "base64",
                "mimeType": result.mime_type,
                "data": base64.b64encode(result.image_bytes).decode(),
            }
        else:
            response["image"] = {"kind": "none"}
        
        logger.info(f"Capture completed in {capture_ms}ms")
        return response
        
    except Exception as e:
        logger.error(f"Capture failed: {e}")
        return {
            "error": str(e),
            "captured_at": datetime.now(timezone.utc).isoformat(),
        }


@mcp.tool()
async def heatmap_analyze(
    source: Literal["coinank", "coinglass"] = "coinglass",
    symbol: Literal["BTC", "ETH"] = "BTC",
    timeframe: str = "1d",
    mode: Literal["algo", "llm", "auto", "compare"] = "auto",
    top_n: int = 5,
    image_input: str = "from_last_capture",
) -> dict[str, Any]:
    """
    Analyze a liquidation heatmap to extract key levels.
    
    Supports two analysis modes:
    - algo: Pure local algorithm (OpenCV + optional OCR), faster
    - llm: LLM-based vision analysis (requires COMET_API_KEY), more accurate
    
    Args:
        source: Data source for context
        symbol: Trading pair - "BTC" or "ETH"
        timeframe: Chart timeframe
        mode: Analysis mode:
            - "algo": Local algorithm only
            - "llm": LLM vision only (requires API key)
            - "auto": Try algo, fall back to LLM if confidence low
            - "compare": Run both and compare results
        top_n: Number of top liquidation levels to return
        image_input: Image source:
            - "from_last_capture": Use the last captured image
            - Resource URI (heatmap://...): Fetch from resource
            - Base64 string: Use directly as image data
    
    Returns:
        JSON with mode_used, latency_ms, current_price, levels, and confidence
    """
    start_time = time.time()
    logger.info(f"Analyzing heatmap: {source}/{symbol}/{timeframe}, mode={mode}")
    
    try:
        # Get image bytes
        image_bytes: Optional[bytes] = None
        
        if image_input == "from_last_capture":
            capture = get_capture_instance()
            last_capture = capture.get_last_capture()
            if last_capture:
                image_bytes = last_capture.image_bytes
            else:
                # Auto-capture if no previous capture
                logger.info("No previous capture, capturing now...")
                result = await capture.capture(source=source, symbol=symbol, timeframe=timeframe)
                image_bytes = result.image_bytes
        elif image_input.startswith("heatmap://"):
            # Fetch from resource
            parts = image_input.replace("heatmap://", "").split("/")
            if len(parts) >= 3:
                image_bytes = _image_resources.get(image_input)
            if not image_bytes:
                raise ValueError(f"Resource not found: {image_input}")
        else:
            # Assume base64
            try:
                image_bytes = base64.b64decode(image_input)
            except Exception:
                raise ValueError("Invalid image_input format")
        
        if not image_bytes:
            raise ValueError("No image available for analysis")
        
        # Run analysis
        analyzer = get_analyzer_instance()
        result = await analyzer.analyze(
            image_bytes=image_bytes,
            source=source,
            symbol=symbol,
            timeframe=timeframe,
            mode=mode,
            top_n=top_n,
        )
        
        total_ms = int((time.time() - start_time) * 1000)
        
        # Build response
        if isinstance(result, CompareResult):
            response = result.to_dict()
            response["latency_ms"] = {
                "total": total_ms,
                "algo": result.algo_result.latency_ms.get("analyze", 0),
                "llm": result.llm_result.latency_ms.get("llm", 0) if result.llm_result else 0,
            }
        else:
            response = result.to_dict()
            response["latency_ms"]["total"] = total_ms
        
        logger.info(f"Analysis completed in {total_ms}ms, mode={response.get('mode_used', mode)}")
        return response
        
    except Exception as e:
        logger.error(f"Analysis failed: {e}")
        return {
            "error": str(e),
            "mode_used": mode,
            "latency_ms": {"total": int((time.time() - start_time) * 1000)},
        }


@mcp.tool()
async def heatmap_report(
    source: Literal["coinank", "coinglass"] = "coinglass",
    symbol: Literal["BTC", "ETH"] = "BTC",
    timeframe: str = "1d",
    mode: Literal["algo", "llm", "auto", "compare"] = "auto",
    top_n: int = 5,
    language: Literal["zh", "en"] = "zh",
) -> dict[str, Any]:
    """
    One-click: capture → analyze → generate Markdown report.
    
    Captures the heatmap, analyzes it, and generates a formatted report
    with key liquidation levels, price magnet paths, and risk warnings.
    
    Args:
        source: Data source - "coinank" or "coinglass"
        symbol: Trading pair - "BTC" or "ETH"
        timeframe: Chart timeframe
        mode: Analysis mode (algo/llm/auto/compare)
        top_n: Number of top levels to include
        language: Report language - "zh" (Chinese) or "en" (English)
    
    Returns:
        JSON with levels, report_markdown, and debug info
    """
    start_time = time.time()
    logger.info(f"Generating report: {source}/{symbol}/{timeframe}")
    
    errors: list[str] = []
    
    try:
        # Step 1: Capture
        capture_start = time.time()
        capture = get_capture_instance()
        capture_result = await capture.capture(
            source=source,
            symbol=symbol,
            timeframe=timeframe,
        )
        capture_ms = int((time.time() - capture_start) * 1000)
        
        if capture_result.errors:
            errors.extend(capture_result.errors)
        
        # Step 2: Analyze
        analyze_start = time.time()
        analyzer = get_analyzer_instance()
        analysis_result = await analyzer.analyze(
            image_bytes=capture_result.image_bytes,
            source=source,
            symbol=symbol,
            timeframe=timeframe,
            mode=mode,
            top_n=top_n,
        )
        analyze_ms = int((time.time() - analyze_start) * 1000)
        
        # Step 3: Generate report
        report_markdown = generate_report(
            result=analysis_result,
            source=source,
            symbol=symbol,
            timeframe=timeframe,
            language=language,
            captured_at=capture_result.captured_at,
        )
        
        total_ms = int((time.time() - start_time) * 1000)
        
        # Build response
        if isinstance(analysis_result, CompareResult):
            levels_data = (
                analysis_result.llm_result.to_dict()["levels"]
                if analysis_result.recommended == "llm" and analysis_result.llm_result
                else analysis_result.algo_result.to_dict()["levels"]
            )
            confidence = (
                analysis_result.llm_result.confidence_overall
                if analysis_result.recommended == "llm" and analysis_result.llm_result
                else analysis_result.algo_result.confidence_overall
            )
        else:
            levels_data = analysis_result.to_dict()["levels"]
            confidence = analysis_result.confidence_overall
        
        response = {
            "levels": levels_data,
            "report_markdown": report_markdown,
            "debug": {
                "crop_rect": capture_result.crop_rect.to_dict(),
                "crop_method": capture_result.crop_method,
                "confidence": confidence,
                "latency_ms": {
                    "capture": capture_ms,
                    "analyze": analyze_ms,
                    "total": total_ms,
                },
            },
        }
        
        if errors:
            response["errors"] = errors
        
        logger.info(f"Report generated in {total_ms}ms")
        return response
        
    except Exception as e:
        logger.error(f"Report generation failed: {e}")
        return {
            "error": str(e),
            "report_markdown": f"# Error\n\nFailed to generate report: {str(e)}",
            "latency_ms": {"total": int((time.time() - start_time) * 1000)},
        }


@mcp.tool()
async def health_check() -> dict[str, Any]:
    """
    Health check endpoint for service monitoring.
    
    Returns:
        Service health status
    """
    from .config import LLM_AVAILABLE, OCR_AVAILABLE
    return {
        "status": "healthy",
        "service": "liq-heatmap-mcp",
        "version": "0.1.0",
        "capabilities": {
            "llm_available": LLM_AVAILABLE,
            "ocr_available": OCR_AVAILABLE,
        },
    }


def get_mcp_server() -> FastMCP:
    """Get the FastMCP server instance."""
    return mcp
