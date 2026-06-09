#!/bin/bash
# VaxAI — Quick Setup Script

echo "💉 VaxAI Setup"
echo "=============="

# Check Python
if ! command -v python3 &>/dev/null; then
  echo "❌ Python 3 not found. Please install it from python.org"
  exit 1
fi

echo "✅ Python $(python3 --version)"

# Create virtualenv
echo "→ Creating virtual environment..."
python3 -m venv venv
source venv/bin/activate 2>/dev/null || . venv/Scripts/activate 2>/dev/null

# Install dependencies
echo "→ Installing dependencies..."
pip install -r requirements.txt -q

# Copy .env
if [ ! -f .env ]; then
  cp .env.example .env
  echo "→ Created .env file — add your OPENAI_API_KEY to enable AI features"
fi

echo ""
echo "✅ Setup complete!"
echo ""
echo "To start the app:"
echo "  source venv/bin/activate"
echo "  python3 app.py"
echo ""
echo "Then open: http://localhost:5050"
