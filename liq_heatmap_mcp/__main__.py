"""
Entry point for the Liquidation Heatmap MCP Server.

Usage:
    python -m liq_heatmap_mcp --host 0.0.0.0 --port 8025 --transport sse
"""

import argparse
import asyncio
import logging
import sys

from .config import Config, set_config
from .server import run_server


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
        default=8025,
        help="Port to bind to",
    )
    parser.add_argument(
        "--transport",
        type=str,
        choices=["sse", "stdio"],
        default="sse",
        help="Transport protocol",
    )
    parser.add_argument(
        "--log-level",
        type=str,
        choices=["DEBUG", "INFO", "WARNING", "ERROR"],
        default="INFO",
        help="Logging level",
    )
    
    args = parser.parse_args()
    
    # Configure logging
    logging.basicConfig(
        level=getattr(logging, args.log_level),
        format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
        stream=sys.stderr,
    )
    
    logger = logging.getLogger(__name__)
    
    # Initialize config
    config = Config()
    config.host = args.host
    config.port = args.port
    config.transport = args.transport
    config.log_level = args.log_level
    set_config(config)
    
    logger.info(f"Starting Liquidation Heatmap MCP Server")
    logger.info(f"Host: {args.host}, Port: {args.port}, Transport: {args.transport}")
    logger.info(f"LLM Available: {config.llm_available}")
    logger.info(f"Cache Directory: {config.screenshot_cache_dir}")
    
    # Run server
    try:
        asyncio.run(run_server(args.host, args.port, args.transport))
    except KeyboardInterrupt:
        logger.info("Server stopped by user")
    except Exception as e:
        logger.exception(f"Server error: {e}")
        sys.exit(1)


if __name__ == "__main__":
    main()
