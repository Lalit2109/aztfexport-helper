#!/bin/bash
# Setup script for Azure Infrastructure Export

set -e

echo "=========================================="
echo "Azure Infrastructure Export - Setup"
echo "=========================================="
echo ""

# Check prerequisites
echo "Checking prerequisites..."

# Check Python
if ! command -v python3 &> /dev/null; then
    echo "✗ Python 3 is not installed"
    exit 1
fi
echo "✓ Python 3 found: $(python3 --version)"

# Check Go (for aztfexport)
if ! command -v go &> /dev/null; then
    echo "⚠️  Go is not installed (required for aztfexport)"
    echo "   Install from: https://golang.org/dl/"
    exit 1
fi
echo "✓ Go found: $(go version)"

# Check Azure CLI (optional but recommended)
if ! command -v az &> /dev/null; then
    echo "⚠️  Azure CLI not found (optional but recommended)"
    echo "   Install from: https://docs.microsoft.com/cli/azure/install-azure-cli"
else
    echo "✓ Azure CLI found: $(az --version | head -n 1)"
fi

echo ""

# Install Python dependencies
echo "Installing Python dependencies..."
pip3 install -r requirements.txt
echo "✓ Python dependencies installed"
echo ""

# Install aztfexport
echo "Installing aztfexport..."
if command -v aztfexport &> /dev/null; then
    echo "✓ aztfexport is already installed"
    aztfexport --version
else
    echo "Installing aztfexport via Go..."
    go install github.com/Azure/aztfexport@latest
    
    # Add to PATH
    GOPATH=$(go env GOPATH)
    export PATH=$PATH:$GOPATH/bin
    
    if command -v aztfexport &> /dev/null; then
        echo "✓ aztfexport installed successfully"
        aztfexport --version
        echo ""
        echo "⚠️  Add to your PATH:"
        echo "   export PATH=\$PATH:$GOPATH/bin"
        echo "   Or add to ~/.bashrc or ~/.zshrc"
    else
        echo "✗ Failed to install aztfexport"
        echo "   Try manually: go install github.com/Azure/aztfexport@latest"
        exit 1
    fi
fi

echo ""

# Setup .env file
if [ ! -f .env ]; then
    echo "Creating .env file..."
    cp .env.example .env
    echo "✓ Created .env file"
    echo "⚠️  Please edit .env with your Azure credentials"
else
    echo "✓ .env file already exists"
fi

echo ""

# Check config file
if [ -f config/subscriptions.yaml ]; then
    echo "✓ Configuration file exists"
    SUB_COUNT=$(grep -c "id:" config/subscriptions.yaml || echo "0")
    echo "  Found $SUB_COUNT subscription(s) in config"
    if [ "$SUB_COUNT" -eq "0" ]; then
        echo "⚠️  No subscriptions configured. Edit config/subscriptions.yaml"
    fi
else
    echo "⚠️  Configuration file not found"
fi

echo ""
echo "=========================================="
echo "Setup complete!"
echo "=========================================="
echo ""
echo "Next steps:"
echo "1. Edit config/subscriptions.yaml with your subscription IDs"
echo "2. Configure .env with Azure credentials (if not using Azure CLI)"
echo "3. Run: python src/main.py"
echo ""

