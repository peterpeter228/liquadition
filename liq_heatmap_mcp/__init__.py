"""
Liquidation Heatmap MCP Server

MCP Server for capturing and analyzing BTC/ETH liquidation heatmaps
from Coinank and Coinglass.
"""

__version__ = "0.1.0"
__author__ = "Liquidation Heatmap MCP"

from .server import create_mcp_server

__all__ = ["create_mcp_server", "__version__"]
