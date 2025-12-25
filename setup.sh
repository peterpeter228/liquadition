#!/bin/bash
# Setup script for Liquidation Heatmap MCP Server
# Works on Ubuntu 22.04+ with Python 3.11+

set -e

echo "=== Liquidation Heatmap MCP Server Setup ==="

# Check Python version
PYTHON_CMD=""
if command -v python3.11 &> /dev/null; then
    PYTHON_CMD="python3.11"
elif command -v python3.12 &> /dev/null; then
    PYTHON_CMD="python3.12"
elif command -v python3 &> /dev/null; then
    PYTHON_CMD="python3"
else
    echo "Error: Python 3.11+ not found"
    exit 1
fi

echo "Using Python: $PYTHON_CMD"

# Install system dependencies
echo "Installing system dependencies..."
sudo apt-get update
sudo apt-get install -y python3-venv python3-full \
    libnss3 libnspr4 libatk1.0-0 libatk-bridge2.0-0 \
    libcups2 libdrm2 libdbus-1-3 libxkbcommon0 \
    libatspi2.0-0 libxcomposite1 libxdamage1 libxfixes3 \
    libxrandr2 libgbm1 libasound2 libpango-1.0-0 \
    libcairo2 libx11-6 libxcb1 libxext6 \
    fonts-liberation fonts-noto-cjk \
    curl

# Optional: Install Tesseract OCR
echo "Installing Tesseract OCR (optional)..."
sudo apt-get install -y tesseract-ocr tesseract-ocr-eng || true

# Create virtual environment
VENV_DIR=".venv"
echo "Creating virtual environment in $VENV_DIR..."
$PYTHON_CMD -m venv $VENV_DIR

# Activate and install
echo "Installing Python dependencies..."
source $VENV_DIR/bin/activate
pip install --upgrade pip
pip install -r requirements.txt
pip install pytesseract || true

# Install Playwright and browser
echo "Installing Playwright and Chromium..."
pip install playwright
playwright install chromium
playwright install-deps chromium || sudo playwright install-deps chromium

# Create .env if not exists
if [ ! -f .env ]; then
    cp .env.example .env
    echo "Created .env file from .env.example"
fi

# Create cache directory
mkdir -p /tmp/liq-heatmap

echo ""
echo "=== Setup Complete ==="
echo ""
echo "To start the server:"
echo "  source .venv/bin/activate"
echo "  python -m liq_heatmap_mcp --host 0.0.0.0 --port 8025 --transport sse"
echo ""
echo "Or use the start script:"
echo "  ./start.sh"
echo ""
