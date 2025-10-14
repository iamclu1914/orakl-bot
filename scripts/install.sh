#!/bin/bash

echo "╔══════════════════════════════════════════════╗"
echo "║      ORAKL Options Flow Bot Installer       ║"
echo "╚══════════════════════════════════════════════╝"

# Check Python
if ! command -v python3 &> /dev/null; then
    echo "❌ Python 3 is required but not installed."
    exit 1
fi

# Create virtual environment
echo "📦 Creating virtual environment..."
python3 -m venv venv
source venv/bin/activate

# Install dependencies
echo "📦 Installing dependencies..."
pip install --upgrade pip
pip install -r requirements.txt

# Create .env from example
if [ ! -f .env ]; then
    echo "📝 Creating .env file..."
    cp env.example .env
    echo "⚠️  Please edit .env with your API keys"
fi

# Create logs directory
mkdir -p logs

# Make scripts executable
chmod +x scripts/*.sh
chmod +x main.py
chmod +x setup.py

echo "✅ Installation complete!"
echo ""
echo "Next steps:"
echo "1. Edit .env file with your API keys"
echo "2. Run: python setup.py (for auto-start setup)"
echo "3. Or run manually: python main.py"
