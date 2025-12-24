# Liquidation Heatmap MCP Server Dockerfile
FROM python:3.11-slim-bookworm

# Set environment variables
ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    PIP_NO_CACHE_DIR=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1 \
    DEBIAN_FRONTEND=noninteractive

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
    libxcomposite1 \
    libxdamage1 \
    libxfixes3 \
    libxrandr2 \
    libgbm1 \
    libasound2 \
    libpango-1.0-0 \
    libcairo2 \
    libatspi2.0-0 \
    libxshmfence1 \
    # OpenCV dependencies
    libgl1-mesa-glx \
    libglib2.0-0 \
    # Optional: Tesseract OCR (uncomment to enable)
    # tesseract-ocr \
    # tesseract-ocr-eng \
    # Utilities
    curl \
    && rm -rf /var/lib/apt/lists/*

# Create app user
RUN useradd -m -u 1000 appuser

# Set working directory
WORKDIR /app

# Copy requirements first for caching
COPY requirements.txt .

# Install Python dependencies
RUN pip install --no-cache-dir -r requirements.txt

# Install Playwright and browsers
RUN pip install playwright && \
    playwright install chromium && \
    playwright install-deps chromium

# Copy application code
COPY liq_heatmap_mcp/ ./liq_heatmap_mcp/
COPY pyproject.toml .

# Install the package
RUN pip install -e .

# Create cache directory
RUN mkdir -p /tmp/liq-heatmap && chown appuser:appuser /tmp/liq-heatmap

# Switch to non-root user
USER appuser

# Expose port
EXPOSE 8000

# Health check - check if port is listening
HEALTHCHECK --interval=30s --timeout=10s --start-period=30s --retries=3 \
    CMD curl -sf http://localhost:8000/sse -o /dev/null -w '%{http_code}' | grep -q '200\|400' || exit 1

# Default command
CMD ["python", "-m", "liq_heatmap_mcp", "--host", "0.0.0.0", "--port", "8000", "--transport", "sse"]
