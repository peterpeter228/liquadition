# Liquidation Heatmap MCP Server
# Ubuntu-based image with Playwright, OpenCV, and optional Tesseract OCR

FROM python:3.11-slim-bookworm

# Set environment variables
ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    PIP_NO_CACHE_DIR=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1 \
    PLAYWRIGHT_BROWSERS_PATH=/ms-playwright

# Install system dependencies
RUN apt-get update && apt-get install -y --no-install-recommends \
    # Playwright dependencies
    libnss3 \
    libnspr4 \
    libatk1.0-0 \
    libatk-bridge2.0-0 \
    libcups2 \
    libdrm2 \
    libdbus-1-3 \
    libxkbcommon0 \
    libatspi2.0-0 \
    libxcomposite1 \
    libxdamage1 \
    libxfixes3 \
    libxrandr2 \
    libgbm1 \
    libasound2 \
    libpango-1.0-0 \
    libcairo2 \
    libx11-6 \
    libxcb1 \
    libxext6 \
    fonts-liberation \
    fonts-noto-cjk \
    # OpenCV dependencies
    libgl1 \
    libglib2.0-0 \
    # Optional OCR (Tesseract)
    tesseract-ocr \
    tesseract-ocr-eng \
    libtesseract-dev \
    # Build tools
    gcc \
    g++ \
    # Cleanup
    && rm -rf /var/lib/apt/lists/*

# Create app directory
WORKDIR /app

# Copy requirements first for better caching
COPY requirements.txt .

# Install Python dependencies
RUN pip install --no-cache-dir -r requirements.txt \
    && pip install --no-cache-dir pytesseract

# Install Playwright and browsers
RUN pip install playwright \
    && playwright install chromium \
    && playwright install-deps chromium

# Copy application code
COPY pyproject.toml .
COPY liq_heatmap_mcp/ ./liq_heatmap_mcp/

# Install the package
RUN pip install -e .

# Create cache directory
RUN mkdir -p /tmp/liq-heatmap

# Expose port
EXPOSE 8025

# Health check
HEALTHCHECK --interval=30s --timeout=10s --start-period=5s --retries=3 \
    CMD curl -f http://localhost:8025/health || exit 1

# Run the server
ENTRYPOINT ["python", "-m", "liq_heatmap_mcp"]
CMD ["--host", "0.0.0.0", "--port", "8025", "--transport", "sse"]
