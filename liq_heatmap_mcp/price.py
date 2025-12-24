"""Price fetching module using Binance API."""

import asyncio
import logging
from typing import Optional

import httpx

from .config import BINANCE_TICKER_URL

logger = logging.getLogger(__name__)


async def get_current_price(symbol: str) -> Optional[float]:
    """
    Fetch current price from Binance.
    
    Args:
        symbol: BTC or ETH
    
    Returns:
        Current price in USDT or None if failed
    """
    ticker_symbol = f"{symbol}USDT"
    
    try:
        async with httpx.AsyncClient(timeout=10) as client:
            response = await client.get(
                BINANCE_TICKER_URL,
                params={"symbol": ticker_symbol}
            )
            response.raise_for_status()
            data = response.json()
            price = float(data.get("price", 0))
            logger.info(f"Fetched {ticker_symbol} price: {price}")
            return price
    except Exception as e:
        logger.error(f"Failed to fetch price for {ticker_symbol}: {e}")
        return None


async def get_prices(symbols: list[str]) -> dict[str, Optional[float]]:
    """Fetch prices for multiple symbols."""
    tasks = [get_current_price(s) for s in symbols]
    results = await asyncio.gather(*tasks)
    return dict(zip(symbols, results))
