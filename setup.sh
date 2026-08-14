#!/usr/bin/env bash

set -e

echo "========================================"
echo "    Network Speed Benchmark Setup       "
echo "========================================"

# Function to install python packages safely using pip if system packages aren't available
install_speedtest_pip() {
    echo "[+] Installing speedtest-cli via pip..."
    pip install --break-system-packages speedtest-cli 2>/dev/null || pip install speedtest-cli
}

# 1. Termux (Android)
if [ -d "/data/data/com.termux" ]; then
    echo "[+] Termux detected."
    pkg update -y
    pkg install -y python curl
    install_speedtest_pip

# 2. Arch Linux
elif command -v pacman &> /dev/null; then
    echo "[+] Arch Linux detected."
    sudo pacman -S --needed --noconfirm python curl speedtest-cli

# 3. Fedora / Bazzite
elif command -v dnf &> /dev/null; then
    echo "[+] Fedora / RHEL-based distro detected."
    sudo dnf install -y python3 curl
    # Install speedtest-cli via pip if dnf package isn't present
    if ! sudo dnf install -y speedtest-cli 2>/dev/null; then
        install_speedtest_pip
    fi

# 4. Debian / Ubuntu / Mint / Pop!_OS
elif command -v apt-get &> /dev/null; then
    echo "[+] Debian / Ubuntu detected."
    sudo apt-get update -y
    sudo apt-get install -y python3 python3-pip curl speedtest-cli

else
    echo "[!] Unknown distro. Attempting fallback via pip..."
    install_speedtest_pip
fi

# Set executable permissions for the python benchmark
if [ -f "speed_benchmark.py" ]; then
    chmod +x speed_benchmark.py
    echo "[+] Made speed_benchmark.py executable."
fi

echo -e "\n[✔] Setup complete! Run your benchmark with: python speed_benchmark.py"