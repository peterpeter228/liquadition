#!/bin/bash
# Start the Liquidation Heatmap MCP Server

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
cd "$SCRIPT_DIR"

# Activate virtual environment
if [ -d ".venv" ]; then
    source .venv/bin/activate
else
    echo "Error: Virtual environment not found. Run ./setup.sh first."
    exit 1
fi

# Default values
HOST="${HOST:-0.0.0.0}"
PORT="${PORT:-8025}"
TRANSPORT="${TRANSPORT:-sse}"
LOG_LEVEL="${LOG_LEVEL:-INFO}"

echo "Starting Liquidation Heatmap MCP Server..."
echo "  Host: $HOST"
echo "  Port: $PORT"
echo "  Transport: $TRANSPORT"
echo "  SSE URL: http://$HOST:$PORT/sse/"
echo ""

python -m liq_heatmap_mcp \
    --host "$HOST" \
    --port "$PORT" \
    --transport "$TRANSPORT" \
    --log-level "$LOG_LEVEL"
