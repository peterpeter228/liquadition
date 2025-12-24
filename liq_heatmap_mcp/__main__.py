"""Main entry point for the MCP server."""

import argparse
import logging
from typing import Literal

from .server import get_mcp_server
from .config import LOG_LEVEL, LLM_AVAILABLE, OCR_AVAILABLE


def main():
    """Main entry point."""
    parser = argparse.ArgumentParser(
        description="Liquidation Heatmap MCP Server",
        formatter_class=argparse.ArgumentDefaultsHelpFormatter,
    )
    parser.add_argument(
        "--host",
        type=str,
        default="0.0.0.0",
        help="Host to bind to",
    )
    parser.add_argument(
        "--port",
        type=int,
        default=8000,
        help="Port to listen on",
    )
    parser.add_argument(
        "--transport",
        type=str,
        choices=["sse", "streamable-http", "stdio"],
        default="sse",
        help="Transport protocol",
    )
    parser.add_argument(
        "--log-level",
        type=str,
        choices=["DEBUG", "INFO", "WARNING", "ERROR"],
        default=LOG_LEVEL,
        help="Logging level",
    )
    
    args = parser.parse_args()
    
    # Configure logging
    logging.basicConfig(
        level=getattr(logging, args.log_level),
        format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
    )
    logger = logging.getLogger(__name__)
    
    logger.info("=" * 60)
    logger.info("Liquidation Heatmap MCP Server")
    logger.info("=" * 60)
    logger.info(f"Transport: {args.transport}")
    logger.info(f"Host: {args.host}, Port: {args.port}")
    logger.info(f"LLM available: {LLM_AVAILABLE}")
    logger.info(f"OCR available: {OCR_AVAILABLE}")
    logger.info("=" * 60)
    
    mcp = get_mcp_server()
    
    if args.transport == "sse":
        # SSE transport using uvicorn
        logger.info(f"Starting SSE server at http://{args.host}:{args.port}")
        logger.info(f"SSE endpoint: http://{args.host}:{args.port}/sse")
        mcp.run(
            transport="sse",
            host=args.host,
            port=args.port,
        )
    elif args.transport == "streamable-http":
        logger.info(f"Starting streamable-http server at http://{args.host}:{args.port}")
        mcp.run(
            transport="streamable-http",
            host=args.host,
            port=args.port,
        )
    else:  # stdio
        logger.info("Starting stdio transport")
        mcp.run(transport="stdio")


if __name__ == "__main__":
    main()
