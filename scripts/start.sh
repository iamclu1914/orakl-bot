#!/bin/bash

# ORAKL Options Flow Bot - Startup Script

# Colors for output
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
NC='\033[0m' # No Color

# Get script directory
SCRIPT_DIR="$( cd "$( dirname "${BASH_SOURCE[0]}" )" && pwd )"
BOT_DIR="$(dirname "$SCRIPT_DIR")"

echo -e "${GREEN}========================================${NC}"
echo -e "${GREEN}     ORAKL OPTIONS FLOW BOT${NC}"
echo -e "${GREEN}     Starting at $(date)${NC}"
echo -e "${GREEN}========================================${NC}"

# Change to bot directory
cd "$BOT_DIR"

# Check if virtual environment exists
if [ -d "venv" ]; then
    echo -e "${YELLOW}Activating virtual environment...${NC}"
    source venv/bin/activate
fi

# Function to start the bot
start_bot() {
    python3 main.py
    return $?
}

# Main loop with auto-restart
while true; do
    start_bot
    EXIT_CODE=$?
    
    if [ $EXIT_CODE -eq 0 ]; then
        echo -e "${GREEN}ORAKL Bot stopped normally.${NC}"
        break
    else
        echo -e "${RED}ORAKL Bot crashed with exit code $EXIT_CODE${NC}"
        echo -e "${YELLOW}Restarting in 10 seconds...${NC}"
        sleep 10
    fi
done

echo "Press any key to exit..."
read -n 1
