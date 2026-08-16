# Network Speed Benchmark Tool

A cross-platform CLI tool for testing network speed, measuring connectivity, analyzing bufferbloat, generating interactive HTML reports, and evaluating real-world gaming/streaming readiness with geolocation & Wi-Fi adapter detection.

**Version: 2.0.0** | Interactive HTML Reports, Network Quality Scoring, Gaming/Streaming Readiness, DNS Optimization Tips, and Continuous Monitoring

## Features

- **Multi-Engine Speed Testing**: Ookla (Speedtest.net), Fast.com (Netflix CDN), and Cloudflare CDN
- **Multi-Stream Downloads**: Parallel worker threads for saturating high-bandwidth connections
- **Interactive HTML Dashboard (`--html`)**: Standalone dark-mode HTML reports with embedded CSS/SVG visual charts
- **Network Quality & Suitability Scoring**: 0–100 overall score with Gaming (low lag), 4K/8K Streaming, and HD/4K Video Call readiness
- **Optimal DNS Recommendation**: Compares UDP DNS latencies and suggests the fastest DNS server with percentage resolution speedup tips
- **Bufferbloat / Loaded Latency**: Measures ping spikes under active transfer load and assigns grades ($A^+$ to $F$)
- **Background DNS Resolution**: Asynchronous UDP latency measurements for Google (8.8.8.8), Cloudflare (1.1.1.1), and Quad9 (9.9.9.9)
- **Continuous Monitoring Mode (`--monitor`)**: Periodically logs speed benchmarks on a custom interval to track ISP performance over 24 hours
- **Network Adapter & Wi-Fi Diagnostics**: Detects active network interface (`wlan0`, `eth0`), Gateway IP, Wi-Fi SSID, and Signal Quality
- **Historical Benchmark Logs**: Auto-saves benchmark records to `~/.speedtest_history.json` with `--history` viewing
- **Live Terminal Spinner**: Real-time animated progress indicators during active tests
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
--html FILE             Export interactive HTML dashboard report
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

**Run with background DNS testing:**
```bash
python3 speedtest.sh --dns
```

**Export interactive HTML report dashboard:**
```bash
python3 speedtest.sh --dns --html report.html
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

**Export results to JSON & CSV:**
```bash
python3 speedtest.sh --json results.json --csv results.csv
```

**Quiet mode (for automation):**
```bash
python3 speedtest.sh --quiet --json output.json
```

## Advanced Features

### Interactive HTML Dashboard (`--html report.html`)

Generates a standalone dark-mode HTML report featuring visual speed comparison bars across Ookla, Fast.com, and Cloudflare, network info cards, latency metrics, and optimal DNS resolver tips.

### Network Quality Scoring

Calculates a **0–100 Overall Score** and evaluates real-world application readiness:
- 🎮 **Online Gaming**: Evaluated on Ping, Jitter, and Bufferbloat spikes
- 🎥 **4K / 8K Video Streaming**: Evaluated on Download bandwidth
- 📹 **4K Video Call**: Evaluated on Upload bandwidth, Ping, and Jitter

### Bufferbloat & Loaded Latency

Measures ICMP/UDP latency spikes while download and upload transfers are actively executing compared to idle latency:
- **A+** ($0 - 5 \text{ ms}$ increase) - Flawless for real-time gaming & video calls
- **A** ($6 - 15 \text{ ms}$)
- **B** ($16 - 30 \text{ ms}$)
- **C** ($31 - 60 \text{ ms}$)
- **D** ($61 - 100 \text{ ms}$)
- **F** ($> 100 \text{ ms}$) - Severe bufferbloat latency spikes under load

## Author

Created by **Shadowharvy**