"""
MCP Server implementation for Liquidation Heatmap capture and analysis.
"""

import asyncio
import json
import logging
from typing import Any, Literal, Optional

from mcp.server import Server
from mcp.server.stdio import stdio_server
from mcp.types import (
    Resource,
    TextContent,
    ImageContent,
    EmbeddedResource,
    Tool,
)

from .analyze import analyze_heatmap
from .capture import CaptureResult, get_capture_instance, cleanup_capture
from .config import get_config, SOURCE_URLS
from .report import generate_report
from .utils import (
    Timer,
    bytes_to_base64,
    cache_image,
    generate_resource_uri,
    get_cached_image,
    get_last_capture,
    get_timestamp,
    image_to_bytes,
    set_last_capture,
    setup_logging,
    base64_to_image,
)

logger = logging.getLogger(__name__)


def create_mcp_server() -> Server:
    """Create and configure the MCP server."""
    server = Server("liq-heatmap-mcp")
    setup_logging()
    
    # Register tools
    @server.list_tools()
    async def list_tools() -> list[Tool]:
        """List available tools."""
        return [
            Tool(
                name="heatmap_capture",
                description="Capture and crop a liquidation heatmap chart from Coinank or Coinglass",
                inputSchema={
                    "type": "object",
                    "properties": {
                        "source": {
                            "type": "string",
                            "enum": ["coinank", "coinglass"],
                            "description": "Data source for the heatmap",
                        },
                        "symbol": {
                            "type": "string",
                            "enum": ["BTC", "ETH"],
                            "description": "Trading symbol",
                        },
                        "timeframe": {
                            "type": "string",
                            "default": "1d",
                            "description": "Chart timeframe (currently only 1d supported)",
                        },
                        "crop": {
                            "type": "string",
                            "enum": ["dom", "auto", "dom_then_auto"],
                            "default": "dom_then_auto",
                            "description": "Cropping strategy",
                        },
                        "include_axes": {
                            "type": "boolean",
                            "default": True,
                            "description": "Include price axes in the crop",
                        },
                        "include_histogram": {
                            "type": "boolean",
                            "default": False,
                            "description": "Include histogram (coinglass only)",
                        },
                        "image_return": {
                            "type": "string",
                            "enum": ["resource", "image", "none"],
                            "default": "resource",
                            "description": "How to return the image",
                        },
                    },
                    "required": ["source", "symbol"],
                },
            ),
            Tool(
                name="heatmap_analyze",
                description="Analyze a liquidation heatmap to detect key levels. Supports algo (fast, no LLM), llm (uses vision API), auto (tries algo first), or compare (both modes)",
                inputSchema={
                    "type": "object",
                    "properties": {
                        "source": {
                            "type": "string",
                            "enum": ["coinank", "coinglass"],
                            "description": "Data source (for context)",
                        },
                        "symbol": {
                            "type": "string",
                            "enum": ["BTC", "ETH"],
                            "description": "Trading symbol",
                        },
                        "timeframe": {
                            "type": "string",
                            "default": "1d",
                            "description": "Chart timeframe",
                        },
                        "mode": {
                            "type": "string",
                            "enum": ["algo", "llm", "auto", "compare"],
                            "default": "auto",
                            "description": "Analysis mode",
                        },
                        "top_n": {
                            "type": "integer",
                            "default": 5,
                            "description": "Number of top levels to return",
                        },
                        "image_input": {
                            "type": ["string", "object"],
                            "default": "from_last_capture",
                            "description": "Image source: 'from_last_capture', {resource_uri: string}, or {image_base64: string}",
                        },
                    },
                    "required": ["source", "symbol"],
                },
            ),
            Tool(
                name="heatmap_report",
                description="One-click: capture, analyze, and generate a markdown report",
                inputSchema={
                    "type": "object",
                    "properties": {
                        "source": {
                            "type": "string",
                            "enum": ["coinank", "coinglass"],
                            "description": "Data source",
                        },
                        "symbol": {
                            "type": "string",
                            "enum": ["BTC", "ETH"],
                            "description": "Trading symbol",
                        },
                        "timeframe": {
                            "type": "string",
                            "default": "1d",
                            "description": "Chart timeframe",
                        },
                        "mode": {
                            "type": "string",
                            "enum": ["algo", "llm", "auto", "compare"],
                            "default": "auto",
                            "description": "Analysis mode",
                        },
                        "top_n": {
                            "type": "integer",
                            "default": 5,
                            "description": "Number of top levels",
                        },
                        "language": {
                            "type": "string",
                            "enum": ["zh", "en"],
                            "default": "en",
                            "description": "Report language",
                        },
                    },
                    "required": ["source", "symbol"],
                },
            ),
        ]

    @server.call_tool()
    async def call_tool(name: str, arguments: dict) -> list[TextContent | ImageContent | EmbeddedResource]:
        """Handle tool calls."""
        try:
            if name == "heatmap_capture":
                return await handle_capture(arguments)
            elif name == "heatmap_analyze":
                return await handle_analyze(arguments)
            elif name == "heatmap_report":
                return await handle_report(arguments)
            else:
                return [TextContent(type="text", text=json.dumps({"error": f"Unknown tool: {name}"}))]
        except Exception as e:
            logger.exception(f"Error in tool {name}")
            return [TextContent(type="text", text=json.dumps({"error": str(e)}))]

    @server.list_resources()
    async def list_resources() -> list[Resource]:
        """List available resources (cached images)."""
        last_capture = get_last_capture()
        if last_capture and "resource_uri" in last_capture:
            return [
                Resource(
                    uri=last_capture["resource_uri"],
                    name=f"Heatmap: {last_capture.get('source', 'unknown')}/{last_capture.get('symbol', 'unknown')}",
                    mimeType="image/png",
                    description="Last captured heatmap image",
                )
            ]
        return []

    @server.read_resource()
    async def read_resource(uri: str) -> bytes:
        """Read a cached image resource."""
        data = get_cached_image(uri)
        if data is None:
            raise ValueError(f"Resource not found: {uri}")
        return data

    return server


async def handle_capture(args: dict) -> list[TextContent | ImageContent | EmbeddedResource]:
    """Handle heatmap_capture tool call."""
    source = args["source"]
    symbol = args["symbol"]
    timeframe = args.get("timeframe", "1d")
    crop = args.get("crop", "dom_then_auto")
    include_axes = args.get("include_axes", True)
    include_histogram = args.get("include_histogram", False)
    image_return = args.get("image_return", "resource")
    
    logger.info(f"Capturing heatmap: {source}/{symbol}/{timeframe}")
    
    with Timer() as capture_timer:
        capture = await get_capture_instance()
        result = await capture.capture(
            source=source,
            symbol=symbol,
            timeframe=timeframe,
            crop=crop,
            include_axes=include_axes,
            include_histogram=include_histogram,
        )
    
    # Generate resource URI and cache image
    timestamp = get_timestamp()
    resource_uri = generate_resource_uri(source, symbol, timestamp)
    image_bytes = image_to_bytes(result.image, format="PNG")
    cache_image(resource_uri, image_bytes)
    
    # Store last capture for subsequent analysis
    set_last_capture({
        "source": source,
        "symbol": symbol,
        "timeframe": timeframe,
        "resource_uri": resource_uri,
        "image_bytes": image_bytes,
        "crop_rect": result.crop_rect.to_dict(),
        "method": result.method,
        "captured_at": result.captured_at,
    })
    
    # Build response
    response_data = {
        "url": result.url,
        "captured_at": result.captured_at,
        "crop_method": result.method,
        "crop_rect": result.crop_rect.to_dict(),
        "image_size": {"width": result.image.width, "height": result.image.height},
        "latency_ms": capture_timer.elapsed_ms,
    }
    
    if result.errors:
        response_data["errors"] = result.errors
    
    contents: list[TextContent | ImageContent | EmbeddedResource] = []
    
    if image_return == "resource":
        response_data["image"] = {
            "kind": "resource",
            "uri": resource_uri,
            "mimeType": "image/png",
        }
        contents.append(TextContent(type="text", text=json.dumps(response_data, indent=2)))
    
    elif image_return == "image":
        response_data["image"] = {
            "kind": "embedded",
            "mimeType": "image/png",
        }
        contents.append(TextContent(type="text", text=json.dumps(response_data, indent=2)))
        contents.append(ImageContent(
            type="image",
            data=bytes_to_base64(image_bytes),
            mimeType="image/png",
        ))
    
    else:  # none
        response_data["image"] = {"kind": "none"}
        contents.append(TextContent(type="text", text=json.dumps(response_data, indent=2)))
    
    return contents


async def handle_analyze(args: dict) -> list[TextContent]:
    """Handle heatmap_analyze tool call."""
    source = args["source"]
    symbol = args["symbol"]
    timeframe = args.get("timeframe", "1d")
    mode = args.get("mode", "auto")
    top_n = args.get("top_n", 5)
    image_input = args.get("image_input", "from_last_capture")
    
    logger.info(f"Analyzing heatmap: {source}/{symbol} mode={mode}")
    
    # Get image
    from PIL import Image
    import io
    
    if image_input == "from_last_capture":
        last_capture = get_last_capture()
        if not last_capture or "image_bytes" not in last_capture:
            return [TextContent(type="text", text=json.dumps({
                "error": "No previous capture found. Run heatmap_capture first.",
            }))]
        image = Image.open(io.BytesIO(last_capture["image_bytes"]))
    
    elif isinstance(image_input, dict):
        if "resource_uri" in image_input:
            image_bytes = get_cached_image(image_input["resource_uri"])
            if image_bytes is None:
                return [TextContent(type="text", text=json.dumps({
                    "error": f"Resource not found: {image_input['resource_uri']}",
                }))]
            image = Image.open(io.BytesIO(image_bytes))
        
        elif "image_base64" in image_input:
            image = base64_to_image(image_input["image_base64"])
        
        else:
            return [TextContent(type="text", text=json.dumps({
                "error": "Invalid image_input format",
            }))]
    else:
        return [TextContent(type="text", text=json.dumps({
            "error": f"Invalid image_input: {image_input}",
        }))]
    
    # Run analysis
    with Timer() as analyze_timer:
        result = await analyze_heatmap(image, symbol, mode, top_n)
    
    # Add total latency
    if "latency_ms" not in result:
        result["latency_ms"] = {}
    result["latency_ms"]["total"] = analyze_timer.elapsed_ms
    
    # Add source info
    result["source"] = source
    result["symbol"] = symbol
    result["timeframe"] = timeframe
    
    return [TextContent(type="text", text=json.dumps(result, indent=2))]


async def handle_report(args: dict) -> list[TextContent]:
    """Handle heatmap_report tool call."""
    source = args["source"]
    symbol = args["symbol"]
    timeframe = args.get("timeframe", "1d")
    mode = args.get("mode", "auto")
    top_n = args.get("top_n", 5)
    language = args.get("language", "en")
    
    logger.info(f"Generating report: {source}/{symbol} mode={mode} lang={language}")
    
    # Capture
    with Timer() as capture_timer:
        capture = await get_capture_instance()
        capture_result = await capture.capture(
            source=source,
            symbol=symbol,
            timeframe=timeframe,
            crop="dom_then_auto",
            include_axes=True,
            include_histogram=False,
        )
    
    # Store for potential future use
    timestamp = get_timestamp()
    resource_uri = generate_resource_uri(source, symbol, timestamp)
    image_bytes = image_to_bytes(capture_result.image, format="PNG")
    cache_image(resource_uri, image_bytes)
    set_last_capture({
        "source": source,
        "symbol": symbol,
        "timeframe": timeframe,
        "resource_uri": resource_uri,
        "image_bytes": image_bytes,
        "crop_rect": capture_result.crop_rect.to_dict(),
        "method": capture_result.method,
        "captured_at": capture_result.captured_at,
    })
    
    # Analyze
    with Timer() as analyze_timer:
        analysis_result = await analyze_heatmap(
            capture_result.image,
            symbol,
            mode,
            top_n,
        )
    
    # Generate report
    debug_info = {
        "method": capture_result.method,
        "crop_rect": capture_result.crop_rect.to_dict(),
        "capture_latency_ms": capture_timer.elapsed_ms,
        "analyze_latency_ms": analyze_timer.elapsed_ms,
    }
    
    report_markdown = generate_report(
        analysis_result,
        source,
        symbol,
        timeframe,
        language,
        debug_info,
    )
    
    # Build response
    response = {
        "source": source,
        "symbol": symbol,
        "timeframe": timeframe,
        "mode_used": analysis_result.get("mode_used") or (
            analysis_result.get("comparison", {}).get("recommended") if "comparison" in analysis_result else None
        ),
        "levels": analysis_result.get("levels", []),
        "confidence_overall": analysis_result.get("confidence_overall", 0),
        "report_markdown": report_markdown,
        "debug": debug_info,
    }
    
    if analysis_result.get("errors"):
        response["errors"] = analysis_result["errors"]
    
    return [TextContent(type="text", text=json.dumps(response, indent=2))]


async def run_server(host: str = "0.0.0.0", port: int = 8025, transport: str = "sse"):
    """Run the MCP server."""
    server = create_mcp_server()
    
    if transport == "sse":
        from mcp.server.sse import SseServerTransport
        from starlette.applications import Starlette
        from starlette.routing import Mount, Route
        from starlette.responses import JSONResponse
        import uvicorn
        
        sse = SseServerTransport("/messages/")
        
        async def handle_sse(request):
            async with sse.connect_sse(
                request.scope, request.receive, request._send
            ) as streams:
                await server.run(
                    streams[0], streams[1], server.create_initialization_options()
                )
        
        async def health_check(request):
            return JSONResponse({"status": "ok", "server": "liq-heatmap-mcp"})
        
        app = Starlette(
            debug=False,
            routes=[
                Route("/health", health_check),
                Mount("/sse", routes=[
                    Route("/", handle_sse),
                ]),
            ],
        )
        
        # Mount SSE endpoint
        app.routes.append(Mount("/messages", app=sse.handle_post_message))
        
        logger.info(f"Starting SSE server on {host}:{port}")
        logger.info(f"SSE endpoint: http://{host}:{port}/sse/")
        logger.info(f"Health check: http://{host}:{port}/health")
        
        config = uvicorn.Config(app, host=host, port=port, log_level="info")
        server_instance = uvicorn.Server(config)
        await server_instance.serve()
    
    else:
        # Stdio transport (for testing)
        async with stdio_server() as (read_stream, write_stream):
            await server.run(read_stream, write_stream, server.create_initialization_options())
