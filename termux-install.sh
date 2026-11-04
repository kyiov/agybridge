#!/bin/bash

# Avoid interactive prompts
export DEBIAN_FRONTEND=noninteractive

if [ "$(whoami)" = "root" ]; then
    echo "Running as root is not supported on Termux. Exiting..."
    exit 1
fi

echo "Configuring Termux package mirrors..."

target_mirror="https://packages-cf.termux.dev/apt/termux-main"
fallback_mirror="https://packages.termux.dev/apt/termux-main"
if [ -f "$PREFIX/etc/apt/sources.list" ] && grep -q "$target_mirror" "$PREFIX/etc/apt/sources.list"; then
    echo "Mirror already configured to Cloudflare mirror, skipping."
else
    echo "Setting Termux mirror..."
    if [ -f "$PREFIX/etc/apt/sources.list" ]; then
        cp "$PREFIX/etc/apt/sources.list" "$PREFIX/etc/apt/sources.list.backup.$(date +%s)"
    fi
    
    cat > "$PREFIX/etc/apt/sources.list" << 'EOF'
deb https://packages-cf.termux.dev/apt/termux-main stable main
EOF
    echo "Mirror updated to: $target_mirror"
fi

ensure_dpkg_ready() {
    echo "Verifying dpkg/apt state..."
    if pgrep -f "apt|dpkg" >/dev/null 2>&1; then
        echo "Waiting for existing apt/dpkg processes to complete..."
        while pgrep -f "apt|dpkg" >/dev/null 2>&1; do sleep 1; done
    fi
    for f in "$PREFIX/var/lib/dpkg/lock" \
             "$PREFIX/var/lib/apt/lists/lock" \
             "$PREFIX/var/cache/apt/archives/lock"; do
        [ -e "$f" ] && rm -f "$f"
    done
    dpkg --configure -a || true
}

echo "Updating package lists..."
ensure_dpkg_ready
apt_output=$(apt update 2>&1)
if [ $? -ne 0 ]; then
    if echo "$apt_output" | grep -qi "is not signed"; then
        echo "Unsigned repo detected, switching to official mirror and repairing keyring..."
        sed -i "s#${target_mirror}#${fallback_mirror}#g" "$PREFIX/etc/apt/sources.list" || true
        rm -rf "$PREFIX/var/lib/apt/lists/"* || true
        rm -f "$PREFIX/var/lib/dpkg/lock" "$PREFIX/var/lib/apt/lists/lock" "$PREFIX/var/cache/apt/archives/lock" || true
        apt-get install --reinstall -y termux-keyring || true
        ensure_dpkg_ready
        apt update
    else
        echo "apt update failed:"
        echo "$apt_output" | head -20
        exit 1
    fi
fi

need_update=false
packages_to_install=""

for pkg in uv python nodejs git; do
    if ! command -v $pkg &> /dev/null; then
        need_update=true
        packages_to_install="$packages_to_install $pkg"
    fi
done

if [ "$need_update" = true ]; then
    echo "Installing required packages: $packages_to_install"
    ensure_dpkg_ready
    pkg install $packages_to_install -y
fi

if ! command -v pm2 &> /dev/null; then
    echo "Installing PM2..."
    npm install pm2 -g
fi

if [ -f "./web.py" ]; then
    :
elif [ -f "./agybridge/web.py" ]; then
    cd ./agybridge
else
    repo_url="${REPO_URL:-https://github.com/your-username/agybridge.git}"
    echo "Cloning repository from $repo_url..."
    git clone "$repo_url" agybridge
    cd ./agybridge
fi

if [ ! -d ".venv" ]; then
    echo "Creating virtual environment..."
    PYTHON_VERSION=$(python -V 2>&1 | grep -oP '\d+\.\d+' | head -1)
    if [ -n "$PYTHON_VERSION" ]; then
        uv python pin "$PYTHON_VERSION"
    fi
    uv venv
fi

echo "Installing Python dependencies..."
uv sync || uv pip install -r requirements.txt

echo "Starting service with PM2..."
source .venv/bin/activate
pm2 start .venv/bin/python --name agybridge -- web.py
cd ..
