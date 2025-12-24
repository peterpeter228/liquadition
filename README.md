# Liquidation Heatmap MCP Server

MCP Server for capturing and analyzing BTC/ETH liquidation heatmaps from **Coinank** and **Coinglass**.

## Features

- 📸 **Smart Screenshot Capture**: DOM-based and OpenCV auto-cropping to extract only the heatmap chart
- 🔍 **Dual Analysis Modes**:
  - **Algo**: Fast, local algorithm using OpenCV + optional OCR
  - **LLM**: Vision-based analysis using CometAPI (GPT-5.2)
- 📊 **Auto/Compare Modes**: Automatic fallback and side-by-side comparison
- 📝 **Markdown Reports**: Template-based report generation with risk warnings
- 🔌 **SSE Transport**: Ready for CherryStudio integration

## Quick Start

### Docker Deployment (Recommended)

```bash
# Clone the repository
git clone <repo-url>
cd liq-heatmap-mcp

# Copy and configure environment
cp .env.example .env
# Edit .env to add your COMET_API_KEY (optional)

# Build and run
docker-compose up -d

# Check logs
docker-compose logs -f
```

### Manual Installation

```bash
# Create virtual environment
python -m venv venv
source venv/bin/activate  # Linux/Mac
# or: venv\Scripts\activate  # Windows

# Install dependencies
pip install -r requirements.txt

# Install Playwright browsers
playwright install chromium

# Run the server
python -m liq_heatmap_mcp --host 0.0.0.0 --port 8000 --transport sse
```

## CherryStudio Configuration

### SSE URL Configuration

In CherryStudio, add a new MCP server with:

- **Type**: SSE
- **URL**: `http://localhost:8000/sse`
- **Name**: Liquidation Heatmap

### Example Tool Calls

#### 1. Capture Heatmap

```json
{
  "tool": "heatmap_capture",
  "arguments": {
    "source": "coinglass",
    "symbol": "BTC",
    "timeframe": "1d",
    "crop": "dom_then_auto",
    "include_axes": true,
    "image_return": "resource"
  }
}
```

**Response**:
```json
{
  "url": "https://www.coinglass.com/pro/futures/LiquidationHeatMap?coin=BTC&type=pair",
  "captured_at": "2024-12-24T10:30:00Z",
  "crop_rect": {"x": 200, "y": 100, "w": 1200, "h": 600},
  "crop_method": "dom",
  "latency_ms": {"capture": 3500},
  "image": {
    "kind": "resource",
    "uri": "heatmap://coinglass/BTC/20241224103000",
    "mimeType": "image/png"
  }
}
```

#### 2. Analyze Heatmap

```json
{
  "tool": "heatmap_analyze",
  "arguments": {
    "source": "coinglass",
    "symbol": "BTC",
    "mode": "compare",
    "top_n": 5,
    "image_input": "from_last_capture"
  }
}
```

**Response (compare mode)**:
```json
{
  "algo_result": {
    "mode_used": "algo",
    "latency_ms": {"analyze": 150},
    "current_price": 98500.00,
    "levels": [
      {
        "side": "above",
        "price": 102000.00,
        "band": [101500.00, 102500.00],
        "strength": 0.85,
        "confidence": 0.65,
        "evidence": "Peak detected at y=120, intensity=0.85"
      }
    ],
    "confidence_overall": 0.55
  },
  "llm_result": {
    "mode_used": "llm",
    "latency_ms": {"llm": 2500},
    "current_price": 98500.00,
    "levels": [
      {
        "side": "above",
        "price": 102350.00,
        "band": [101800.00, 102900.00],
        "strength": 0.88,
        "confidence": 0.82,
        "evidence": "Strong yellow concentration indicating high leverage long liquidations"
      }
    ],
    "confidence_overall": 0.78
  },
  "recommended": "llm",
  "recommendation_reason": "LLM has higher confidence (0.78 vs 0.55)",
  "latency_ms": {"total": 2800, "algo": 150, "llm": 2500}
}
```

#### 3. Generate Report

```json
{
  "tool": "heatmap_report",
  "arguments": {
    "source": "coinglass",
    "symbol": "BTC",
    "mode": "auto",
    "top_n": 5,
    "language": "zh"
  }
}
```

**Response**:
```json
{
  "levels": [...],
  "report_markdown": "# BTC 清算热力图分析\n\n**数据源**: Coinglass | **时间周期**: 1d\n...",
  "debug": {
    "crop_rect": {"x": 200, "y": 100, "w": 1200, "h": 600},
    "confidence": 0.72,
    "latency_ms": {"capture": 3500, "analyze": 2600, "total": 6200}
  }
}
```

## MCP Tools Reference

### `heatmap_capture`

Capture a liquidation heatmap screenshot.

| Parameter | Type | Default | Description |
|-----------|------|---------|-------------|
| source | `"coinank"` \| `"coinglass"` | `"coinglass"` | Data source |
| symbol | `"BTC"` \| `"ETH"` | `"BTC"` | Trading pair |
| timeframe | string | `"1d"` | Chart timeframe |
| crop | `"dom"` \| `"auto"` \| `"dom_then_auto"` | `"dom_then_auto"` | Cropping strategy |
| include_axes | boolean | `true` | Include price axis |
| include_histogram | boolean | `false` | Include histogram (coinglass) |
| image_return | `"resource"` \| `"image"` \| `"none"` | `"resource"` | Image return method |

### `heatmap_analyze`

Analyze a heatmap to extract liquidation levels.

| Parameter | Type | Default | Description |
|-----------|------|---------|-------------|
| source | `"coinank"` \| `"coinglass"` | `"coinglass"` | Data source context |
| symbol | `"BTC"` \| `"ETH"` | `"BTC"` | Trading pair |
| timeframe | string | `"1d"` | Chart timeframe |
| mode | `"algo"` \| `"llm"` \| `"auto"` \| `"compare"` | `"auto"` | Analysis mode |
| top_n | integer | `5` | Number of levels to return |
| image_input | string | `"from_last_capture"` | Image source |

### `heatmap_report`

One-click capture → analyze → report generation.

| Parameter | Type | Default | Description |
|-----------|------|---------|-------------|
| source | `"coinank"` \| `"coinglass"` | `"coinglass"` | Data source |
| symbol | `"BTC"` \| `"ETH"` | `"BTC"` | Trading pair |
| timeframe | string | `"1d"` | Chart timeframe |
| mode | `"algo"` \| `"llm"` \| `"auto"` \| `"compare"` | `"auto"` | Analysis mode |
| top_n | integer | `5` | Number of levels |
| language | `"zh"` \| `"en"` | `"zh"` | Report language |

## Environment Variables

| Variable | Required | Default | Description |
|----------|----------|---------|-------------|
| `COMET_API_KEY` | No | - | CometAPI key for LLM mode |
| `COMET_BASE_URL` | No | `https://api.cometapi.com/v1` | API base URL |
| `COMET_MODEL` | No | `gpt-5.2` | Model name |
| `COMET_REASONING` | No | `xhigh` | Reasoning effort level |
| `COINGLASS_COOKIE` | No | - | Cookie for Coinglass |
| `COINANK_COOKIE` | No | - | Cookie for Coinank |
| `SCREENSHOT_CACHE_DIR` | No | `/tmp/liq-heatmap` | Cache directory |
| `LOG_LEVEL` | No | `INFO` | Logging level |
| `DEBUG_CROP` | No | `0` | Enable debug image saving |

## Analysis Modes

### Algo Mode (Default for `auto`)

- Uses OpenCV for image processing
- Extracts intensity profile from HSV color space
- Peak detection with scipy
- Optional OCR for price axis reading
- **Pros**: Fast (~150ms), no API cost
- **Cons**: Lower accuracy, struggles with complex charts

### LLM Mode

- Uses CometAPI with GPT-5.2 vision
- Sends compressed JPEG to API
- Parses structured JSON response
- **Pros**: Higher accuracy, understands context
- **Cons**: Slower (~2-3s), requires API key

### Auto Mode

Tries algo first, falls back to LLM if `confidence_overall < 0.55`.

### Compare Mode

Runs both modes in parallel, returns comparison with recommendation.

## Cropping Strategies

### DOM Cropping (Priority)

1. Waits for canvas/SVG elements to render
2. Scores elements by area, aspect ratio, and center position
3. Selects best candidate as chart region
4. Adds padding for price axis

### Auto Cropping (Fallback)

1. Converts to HSV color space
2. Creates mask for saturated colors (heatmap) and dark regions (background)
3. Applies morphological operations
4. Finds largest contour matching chart characteristics

## Docker with OCR Support

To enable Tesseract OCR for better price axis detection:

```bash
# Use the OCR profile
docker-compose --profile ocr up -d

# Or build and run the OCR image
docker build -f Dockerfile.ocr -t liq-heatmap-mcp-ocr .
docker run -p 8000:8000 -e COMET_API_KEY=xxx liq-heatmap-mcp-ocr
```

## Troubleshooting

### Browser Launch Fails

```bash
# Install Playwright dependencies
playwright install-deps chromium
```

### Low Confidence Results

1. Enable `DEBUG_CROP=1` to inspect cropped images
2. Check if the chart is fully loaded (increase wait time)
3. Try different crop strategies
4. Use LLM mode for complex charts

### API Errors

- Verify `COMET_API_KEY` is set correctly
- Check API quota and rate limits
- If reasoning parameter fails, it auto-downgrades

## License

MIT

---

**⚠️ Disclaimer**: This tool is for informational purposes only and does not constitute investment advice. Cryptocurrency trading involves substantial risk.
