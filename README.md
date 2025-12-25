# Liquidation Heatmap MCP Server

MCP Server for capturing and analyzing BTC/ETH liquidation heatmaps from Coinank and Coinglass.

## Features

- **SSE Transport**: Compatible with CherryStudio and other MCP clients
- **Two Analysis Modes**:
  - **Algo Mode**: Fast, local analysis using OpenCV + optional OCR (no LLM required)
  - **LLM Mode**: Vision-based analysis using CometAPI/OpenAI-compatible API
- **Smart Screenshot Cropping**: DOM-based + OpenCV fallback to extract only the chart area
- **Resource-based Image Handling**: Avoids large base64 strings in responses

## Quick Start

### Docker (Recommended)

```bash
# Clone and navigate to the project
cd liq-heatmap-mcp

# Create .env file (optional, for LLM support)
cat > .env << EOF
COMET_API_KEY=your_api_key_here
COMET_BASE_URL=https://api.cometapi.com/v1
COMET_MODEL=gpt-4o
EOF

# Build and run
docker-compose up -d

# Check health
curl http://localhost:8025/health
```

### Local Installation (Ubuntu 22.04+)

**Quick Setup (Recommended):**
```bash
# One-line setup
chmod +x setup.sh && ./setup.sh

# Start the server
./start.sh
```

**Manual Setup:**
```bash
# Install system dependencies
sudo apt-get update
sudo apt-get install -y python3-venv python3-full

# Create virtual environment (required for Python 3.12+)
python3 -m venv .venv
source .venv/bin/activate

# Install Python packages
pip install -r requirements.txt

# Install Playwright and Chromium browser
pip install playwright
playwright install chromium
playwright install-deps chromium

# Copy environment config
cp .env.example .env

# Run the server
python -m liq_heatmap_mcp --host 0.0.0.0 --port 8025 --transport sse
```

**Note:** Ubuntu 24.04+ with Python 3.12 requires a virtual environment due to PEP 668.

## CherryStudio Configuration

Add this MCP server to CherryStudio:

### SSE Configuration

```json
{
  "mcpServers": {
    "liq-heatmap": {
      "type": "sse",
      "url": "http://localhost:8025/sse/"
    }
  }
}
```

Or if running on a remote server:

```json
{
  "mcpServers": {
    "liq-heatmap": {
      "type": "sse", 
      "url": "http://your-server-ip:8025/sse/"
    }
  }
}
```

## MCP Tools

### 1. `heatmap_capture`

Capture and crop a liquidation heatmap chart.

**Input:**
```json
{
  "source": "coinglass",
  "symbol": "BTC",
  "timeframe": "1d",
  "crop": "dom_then_auto",
  "include_axes": true,
  "include_histogram": false,
  "image_return": "resource"
}
```

**Output:**
```json
{
  "url": "https://www.coinglass.com/pro/futures/LiquidationHeatMap?coin=BTC&type=pair",
  "captured_at": "2024-12-25T10:30:00Z",
  "crop_method": "dom",
  "crop_rect": {"x": 150, "y": 100, "w": 1200, "h": 600},
  "image_size": {"width": 1200, "height": 600},
  "latency_ms": 3500,
  "image": {
    "kind": "resource",
    "uri": "heatmap://coinglass/btc/abc123def456",
    "mimeType": "image/png"
  }
}
```

### 2. `heatmap_analyze`

Analyze a liquidation heatmap to detect key levels.

**Input:**
```json
{
  "source": "coinglass",
  "symbol": "BTC",
  "timeframe": "1d",
  "mode": "compare",
  "top_n": 5,
  "image_input": "from_last_capture"
}
```

**Output (compare mode):**
```json
{
  "algo_result": {
    "mode_used": "algo",
    "current_price": 98500.50,
    "levels": [
      {
        "side": "above",
        "price": 102500.00,
        "band": [101800.00, 103200.00],
        "strength": 0.85,
        "confidence": 0.72,
        "evidence": "Intensity peak at y=150, strength=0.85"
      },
      {
        "side": "below",
        "price": 95000.00,
        "band": [94200.00, 95800.00],
        "strength": 0.78,
        "confidence": 0.68,
        "evidence": "Intensity peak at y=380, strength=0.78"
      }
    ],
    "confidence_overall": 0.70,
    "latency_ms": {"price_fetch": 120, "analyze": 450}
  },
  "llm_result": {
    "mode_used": "llm",
    "current_price": 98500.50,
    "levels": [
      {
        "side": "above",
        "price": 102800.00,
        "band": [102000.00, 103500.00],
        "strength": 0.90,
        "confidence": 0.85,
        "evidence": "Strong liquidation cluster visible in yellow-green band"
      }
    ],
    "confidence_overall": 0.82,
    "latency_ms": {"price_fetch": 120, "llm": 2800}
  },
  "comparison": {
    "recommended": "llm",
    "reason": "LLM has higher confidence (0.82 vs 0.70)",
    "algo_confidence": 0.70,
    "llm_confidence": 0.82,
    "algo_latency_ms": 570,
    "llm_latency_ms": 2920
  }
}
```

### 3. `heatmap_report`

One-click capture, analyze, and generate a markdown report.

**Input:**
```json
{
  "source": "coinank",
  "symbol": "ETH",
  "timeframe": "1d",
  "mode": "auto",
  "top_n": 5,
  "language": "zh"
}
```

**Output:**
```json
{
  "source": "coinank",
  "symbol": "ETH",
  "timeframe": "1d",
  "mode_used": "algo",
  "levels": [...],
  "confidence_overall": 0.75,
  "report_markdown": "# ETH/USDT 清算热力图分析\n\n**数据源:** Coinank\n...",
  "debug": {
    "method": "dom",
    "crop_rect": {"x": 100, "y": 80, "w": 1100, "h": 550},
    "capture_latency_ms": 3200,
    "analyze_latency_ms": 480
  }
}
```

## Environment Variables

| Variable | Description | Default |
|----------|-------------|---------|
| `COMET_API_KEY` | API key for LLM (optional) | - |
| `COMET_BASE_URL` | LLM API base URL | `https://api.cometapi.com/v1` |
| `COMET_MODEL` | LLM model name | `gpt-4o` |
| `COMET_REASONING` | Reasoning effort level | `xhigh` |
| `COINGLASS_COOKIE` | Cookie for Coinglass auth (optional) | - |
| `COINANK_COOKIE` | Cookie for Coinank auth (optional) | - |
| `SCREENSHOT_CACHE_DIR` | Directory for cached screenshots | `/tmp/liq-heatmap` |
| `LOG_LEVEL` | Logging level | `INFO` |
| `DEBUG_CROP` | Save debug crop images (0/1) | `0` |

## Analysis Modes

### `algo` - Algorithmic Analysis (No LLM)

- Uses OpenCV for image processing
- Optional OCR (Tesseract) for price axis reading
- Fast (~500ms), works offline
- Lower accuracy without OCR

### `llm` - LLM Vision Analysis

- Uses CometAPI/OpenAI-compatible vision API
- Higher accuracy for complex charts
- Slower (~3s), requires API key
- Auto-validates prices with Binance ticker

### `auto` - Automatic Mode (Default)

- Tries `algo` first
- Falls back to `llm` if confidence < 55%
- Best balance of speed and accuracy

### `compare` - Comparison Mode

- Runs both modes
- Returns results from both
- Provides recommendation based on confidence and latency

## Cropping Strategies

### `dom_then_auto` (Default)

1. **DOM Analysis**: Finds the largest canvas/SVG element that looks like a heatmap chart
2. **Auto Fallback**: If DOM fails, uses OpenCV contour detection

### `dom`

Only uses DOM-based cropping. Fails if no suitable element found.

### `auto`

Only uses OpenCV-based automatic cropping.

## Example Usage in CherryStudio

### Basic Analysis

```
User: 请分析当前 BTC 的清算热力图
Assistant: (使用 heatmap_report 工具分析 Coinglass BTC 热力图...)

根据分析结果，当前 BTC 的主要清算位置如下：

**上方阻力位：**
- $102,500 (强度 85%)
- $105,000 (强度 72%)

**下方支撑位：**
- $95,000 (强度 78%)
- $92,000 (强度 65%)

当前价格 $98,500 附近清算密度较低，上方 $102,500 处存在较大清算集中区，可能成为短期阻力。

⚠️ 以上分析仅供参考，不构成投资建议。
```

### Compare Both Modes

```
User: Compare algo and LLM analysis for ETH heatmap
Assistant: (使用 heatmap_analyze mode=compare 分析...)

Comparison Results:
- Algo: 570ms, confidence 0.70
- LLM: 2920ms, confidence 0.82

Recommendation: LLM (higher confidence)

The LLM identified an additional level at $3,850 that algo missed.
```

## Troubleshooting

### Browser Launch Fails

```bash
# Install Playwright dependencies
playwright install-deps chromium
```

### OCR Not Working

OCR is optional. Without it, the system will estimate price ranges based on current market price.

To enable OCR:
```bash
# Ubuntu/Debian
apt-get install tesseract-ocr tesseract-ocr-eng
pip install pytesseract
```

### LLM Requests Fail

1. Check `COMET_API_KEY` is set correctly
2. Verify `COMET_BASE_URL` points to valid endpoint
3. Check network connectivity

Without LLM, the system falls back to algo mode automatically.

## API Endpoints

| Endpoint | Description |
|----------|-------------|
| `GET /health` | Health check |
| `GET /sse/` | SSE connection endpoint |
| `POST /messages/` | Message handling endpoint |

## License

MIT License

## Disclaimer

⚠️ This tool is for informational purposes only and does not constitute investment advice. Cryptocurrency trading involves significant risk. Always conduct your own research and manage risk appropriately.
