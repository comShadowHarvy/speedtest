#!/usr/bin/env bash

set -e

echo "========================================================="
echo "       Network Speed & Diagnostic Benchmark Setup        "
echo "========================================================="

# Function to install python packages safely using pip if system packages aren't available
install_speedtest_pip() {
    echo "[+] Installing speedtest-cli via pip..."
    pip3 install --break-system-packages speedtest-cli 2>/dev/null || pip install speedtest-cli 2>/dev/null || true
}

# 1. Termux (Android)
if [ -d "/data/data/com.termux" ]; then
    echo "[+] Termux detected."
    pkg update -y
    pkg install -y python curl
    install_speedtest_pip

# 2. macOS (Homebrew)
elif [ "$(uname)" = "Darwin" ]; then
    echo "[+] macOS detected."
    if command -v brew &> /dev/null; then
        brew install python curl speedtest-cli || true
    else
        echo "[!] Homebrew not found. Falling back to pip..."
        install_speedtest_pip
    fi

# 3. Arch Linux / Manjaro / EndeavourOS
elif command -v pacman &> /dev/null; then
    echo "[+] Arch Linux / Pacman detected."
    sudo pacman -S --needed --noconfirm python curl speedtest-cli || install_speedtest_pip

# 4. Fedora / RHEL / CentOS / Bazzite
elif command -v dnf &> /dev/null; then
    echo "[+] Fedora / RHEL / Bazzite detected."
    sudo dnf install -y python3 curl
    if ! sudo dnf install -y speedtest-cli 2>/dev/null; then
        install_speedtest_pip
    fi

# 5. Debian / Ubuntu / Mint / Pop!_OS / Kali
elif command -v apt-get &> /dev/null; then
    echo "[+] Debian / Ubuntu detected."
    sudo apt-get update -y
    sudo apt-get install -y python3 python3-pip curl speedtest-cli || install_speedtest_pip

# 6. openSUSE / SLES
elif command -v zypper &> /dev/null; then
    echo "[+] openSUSE detected."
    sudo zypper install -y python3 curl python3-pip
    install_speedtest_pip

# 7. Alpine Linux
elif command -v apk &> /dev/null; then
    echo "[+] Alpine Linux detected."
    sudo apk add --no-cache python3 py3-pip curl
    install_speedtest_pip

# 8. Void Linux
elif command -v xbps-install &> /dev/null; then
    echo "[+] Void Linux detected."
    sudo xbps-install -Sy python3 python3-pip curl
    install_speedtest_pip

# 9. Solus
elif command -v eopkg &> /dev/null; then
    echo "[+] Solus detected."
    sudo eopkg install -y python3 curl python3-pip
    install_speedtest_pip

else
    echo "[!] Unknown distribution. Attempting fallback via pip..."
    install_speedtest_pip
fi

# Set executable permissions
if [ -f "speedtest.sh" ]; then
    chmod +x speedtest.sh
    echo "[+] Made speedtest.sh executable."
fi

echo -e "\n[✔] Setup complete! Run your benchmark with:"
echo "    ./speedtest.sh"
echo "    bash speedtest.sh"
echo "    python3 speedtest.sh --runs 3 --dns --html report.html --open"