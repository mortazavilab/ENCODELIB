#!/bin/bash
# ENCODE fastmcp Server Startup Script

# Colors for output
GREEN='\033[0;32m'
BLUE='\033[0;34m'
YELLOW='\033[1;33m'
NC='\033[0m' # No Color

echo -e "${BLUE}================================================${NC}"
echo -e "${BLUE}ENCODE fastmcp Server${NC}"
echo -e "${BLUE}================================================${NC}"
echo ""

# Find Python executable - prioritize 'python' over 'python3'
PYTHON=""
if command -v python &> /dev/null; then
    PYTHON=$(command -v python)
elif command -v python3 &> /dev/null; then
    PYTHON=$(command -v python3)
else
    echo -e "${YELLOW}Error: Python is not installed${NC}"
    exit 1
fi

echo -e "${GREEN}✓ Using Python: $PYTHON${NC}"
PYTHON_VERSION=$($PYTHON --version 2>&1)
echo -e "${GREEN}✓ Version: $PYTHON_VERSION${NC}"
echo ""

# Check if fastmcp is installed
if ! $PYTHON -c "import fastmcp" 2>/dev/null; then
    echo -e "${YELLOW}fastmcp not found. Installing dependencies...${NC}"
    $PYTHON -m pip install -r requirements-server.txt
fi

# Get current directory
SCRIPT_DIR="$( cd "$( dirname "${BASH_SOURCE[0]}" )" && pwd )"
cd "$SCRIPT_DIR"

echo -e "${GREEN}✓ Work directory: $(pwd)${NC}"
echo -e "${GREEN}✓ Cache directory: $(pwd)/.encode_cache${NC}"
echo -e "${GREEN}✓ Files directory: $(pwd)/files${NC}"
echo ""

echo -e "${BLUE}Starting server on http://0.0.0.0:8080${NC}"
echo ""

# Run the server
$PYTHON encode_server.py
