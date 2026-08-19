# Network Speed Benchmark Tool

A cross-platform CLI tool for testing network speed, measuring connectivity, analyzing bufferbloat, generating interactive HTML reports, and evaluating real-world gaming/streaming readiness with geolocation & Wi-Fi adapter detection.

**Version: 2.1.0** | System DNS Auto-Detection, Packet Loss Probes, Engine Selection Filtering (`--engine`), Auto-Open HTML Browser (`--open`), and Speed Tier Diagnostics

## Features

- **Multi-Engine Speed Testing**: Ookla (Speedtest.net), Fast.com (Netflix CDN), and Cloudflare CDN
- **Engine Filter (`--engine`)**: Select specific engines (`cloudflare`, `fast`, `speedtest`, `all`) for quick tests
- **Multi-Stream Downloads**: Parallel worker threads for saturating high-bandwidth connections
- **Packet Loss Diagnostics**: Measures ICMP/UDP packet loss percentage ($0\%$ to $100\%$)
- **System & Gateway DNS Auto-Detection**: Benchmarks system `/etc/resolv.conf` / `systemd-resolved` DNS along with Local Gateway IP, Google, Cloudflare, and Quad9
- **Auto-Open HTML Reports (`--html` + `--open`)**: Standalone dark-mode HTML reports that auto-open in default browser
- **Network Quality & Suitability Scoring**: 0–100 overall score with Gaming (low lag), 4K/8K Streaming, and HD/4K Video Call readiness
- **Speed Tier Classification**: Automatically categorizes connections (Gigabit, Ultra-Fast, Broadband, Basic)
- **Optimal DNS Recommendation**: Compares UDP DNS latencies and suggests the fastest DNS server with percentage resolution speedup tips
- **Bufferbloat / Loaded Latency**: Measures ping spikes under active transfer load and assigns grades ($A^+$ to $F$)
- **Continuous Monitoring Mode (`--monitor`)**: Periodically logs speed benchmarks on a custom interval to track ISP performance over 24 hours
- **Network Adapter & Wi-Fi Diagnostics**: Detects active network interface (`wlan0`, `eth0`), Gateway IP, Wi-Fi SSID, and Signal Quality
- **Historical Benchmark Logs**: Auto-saves benchmark records to `~/.speedtest_history.json` with `--history` viewing
- **Data Export**: Export results in structured JSON, CSV, and HTML formats
- **Multi-Platform Support**: Works on Arch Linux, Fedora, Debian/Ubuntu, Bazzite, and Termux

## Requirements

- Python 3.x
- `curl` (for HTTP requests)
- `speedtest-cli` (installed via setup script)

## Supported Platforms

- **Linux**: Arch, Fedora, Debian/Ubuntu, Mint, Pop!_OS
- **Bazzite** (Fedora-based)
- **Termux** (Android via Termux app)

## Installation

### Quick Setup

Run the setup script to automatically detect your system and install dependencies:

```bash
chmod +x setup.sh
./setup.sh
```

### Manual Installation

For a specific system, install dependencies manually:

**Arch Linux:**
```bash
sudo pacman -S python curl speedtest-cli
```

**Fedora/RHEL:**
```bash
sudo dnf install python3 curl speedtest-cli
```

**Debian/Ubuntu:**
```bash
sudo apt-get update && sudo apt-get install python3 python3-pip curl speedtest-cli
```

**Termux (Android):**
```bash
pkg update && pkg install python curl
pip install speedtest-cli
```

## Usage

Run the speedtest tool:

```bash
chmod +x speedtest.sh
python3 speedtest.sh [options]
```

### Options

```
-h, --help              Show help message and exit
-n, --runs NUM          Number of benchmark iterations (default: 3, max: 20)
--dns                   Run background DNS resolution test alongside speed tests
--engine ENGINE         Select engine filter: all, cloudflare, fast, speedtest (default: all)
--html FILE             Export interactive HTML dashboard report
--open                  Auto-open exported HTML report in default browser
--history               Display historical benchmark performance logs & averages
--history-clear         Clear historical benchmark log file
--json FILE             Export results to a JSON file
--csv FILE              Export results to a CSV file
--monitor MINS          Continuous monitoring mode interval in minutes
--quiet                 Suppress banner and progress output, show only summary
--no-color              Disable colored terminal output
--debug                 Enable debug output for troubleshooting
--version               Show version and exit
```

### Examples

**Run full speed test (3 runs by default):**
```bash
python3 speedtest.sh
```

**Run ultra-fast Cloudflare-only speed test with DNS benchmarks:**
```bash
python3 speedtest.sh --engine cloudflare --dns
```

**Export interactive HTML report dashboard and auto-open in browser:**
```bash
python3 speedtest.sh --dns --html report.html --open
```

**Continuous monitoring every 30 minutes:**
```bash
python3 speedtest.sh --monitor 30 --dns
```

**View benchmark history:**
```bash
python3 speedtest.sh --history
```

**Clear history logs:**
```bash
python3 speedtest.sh --history-clear
```

## Author

Created by **Shadowharvy**