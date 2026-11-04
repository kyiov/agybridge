#!/bin/bash
# macOS Installation Script (supports Apple Silicon and Intel)

# Check Homebrew
if ! command -v brew &> /dev/null; then
    echo "Homebrew not found. Installing Homebrew..."
    /bin/bash -c "$(curl -fsSL https://raw.githubusercontent.com/Homebrew/install/HEAD/install.sh)"
    
    if [[ -f "/opt/homebrew/bin/brew" ]]; then
        eval "$(/opt/homebrew/bin/brew shellenv)"
    elif [[ -f "/usr/local/bin/brew" ]]; then
        eval "$(/usr/local/bin/brew shellenv)"
    fi
fi

# Update brew and install git
brew update
brew install git

# Install uv package manager
curl -Ls https://astral.sh/uv/install.sh | sh

# Add uv to PATH
export PATH="$HOME/.local/bin:$PATH"

# Enter project directory
if [ -f "./web.py" ]; then
    :
elif [ -f "./agybridge/web.py" ]; then
    cd ./agybridge
fi

# Create and synchronize virtual environment
uv sync

# Activate virtual environment
if [ -f ".venv/bin/activate" ]; then
    source ".venv/bin/activate"
else
    echo "Virtual environment not found. Please verify uv installation."
    exit 1
fi

# Start application
python3 web.py
