# Network Speed Benchmark Tool

A cross-platform CLI tool for testing network speed, measuring connectivity, analyzing bufferbloat, and generating detailed reports with geolocation & Wi-Fi adapter detection.

**Version: 1.5.7** | Multi-threaded engines, Cloudflare CDN, Bufferbloat testing, Wi-Fi info, live progress spinner, and history tracking

## Features

- **Multi-Engine Speed Testing**: Ookla (Speedtest.net), Fast.com (Netflix CDN), and Cloudflare CDN
- **Multi-Stream Downloads**: Parallel worker threads for saturating high-bandwidth connections
- **Bufferbloat / Loaded Latency**: Measures ping spikes under active transfer load and assigns grades ($A^+$ to $F$)
- **Background DNS Resolution**: Asynchronous UDP latency measurements for Google (8.8.8.8), Cloudflare (1.1.1.1), and Quad9 (9.9.9.9)
- **Network Adapter & Wi-Fi Diagnostics**: Detects active network interface (`wlan0`, `eth0`), Gateway IP, Wi-Fi SSID, and Signal Quality
- **Historical Benchmark Logs**: Auto-saves benchmark records to `~/.speedtest_history.json` with `--history` viewing
- **Live Terminal Spinner**: Real-time animated progress indicators during active tests
- **Data Export**: Export results in structured JSON and CSV formats
- **Browser Spoofing**: Bypasses corporate firewall restrictions using a modern Chrome user-agent
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
--history               Display historical benchmark performance logs & averages
--history-clear         Clear historical benchmark log file
--json FILE             Export results to a JSON file
--csv FILE              Export results to a CSV file
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

### Bufferbloat & Loaded Latency

Measures ICMP/UDP latency spikes while download and upload transfers are actively executing compared to idle latency:
- **A+** ($0 - 5 \text{ ms}$ increase) - Excellent quality for gaming & video calls
- **A** ($6 - 15 \text{ ms}$)
- **B** ($16 - 30 \text{ ms}$)
- **C** ($31 - 60 \text{ ms}$)
- **D** ($61 - 100 \text{ ms}$)
- **F** ($> 100 \text{ ms}$) - Severe bufferbloat latency spikes under load

### Multi-Stream Speed Engine

Fast.com and Cloudflare speed engines launch parallel concurrent streams (`ThreadPoolExecutor`) to saturate fiber/gigabit connections.

## Author

Created by **Shadowharvy**