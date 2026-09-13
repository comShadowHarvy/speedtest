# Network Speed & Diagnostic Benchmark Tool

A high-performance, cross-platform CLI tool for network speed benchmarking, dual-stack IPv4/IPv6 diagnostics, directional bufferbloat analysis (DL/UL), DNS & DoH resolution tests, hardware link speed detection, interactive HTML dashboard generation, and SLA threshold monitoring.

**Version: 3.1.0** | Universal Shell Execution, Multi-Gigabit Saturation, Directional Bufferbloat (DL/UL), Dual-Stack IPv4/IPv6, Hardware Link Speeds, Live Throughput Progress, Unicode Sparklines, DoH Benchmarking, and Glassmorphism Dashboard

---

## Key Features

- **Universal Shell Execution**: Runs seamlessly via `./speedtest.sh`, `bash speedtest.sh`, `sh speedtest.sh`, or `python3 speedtest.sh`.
- **Multi-Engine Speed Testing**:
  - **Ookla (Speedtest.net)**: Native official Ookla binary auto-detection (`speedtest --format=json`) with fallback to `speedtest-cli`.
  - **Fast.com (Netflix CDN)**: Multi-stream adaptive chunking (saturates 1Gbps+ connections).
  - **Cloudflare CDN**: Multi-worker parallel download & streaming upload tests.
  - **Custom Server (`--server <URL>`)**: Benchmark any custom HTTP/HTTPS CDN or endpoint.
- **Engine Filter (`--engine`)**: Select specific engines (`cloudflare`, `fast`, `speedtest`, `ookla`, `custom`, `all`).
- **Directional Bufferbloat & Loaded Latency ($A^+$ to $F$)**:
  - Measures baseline idle ping vs. active download loaded ping vs. active upload loaded ping.
  - Calculates directional latency deltas ($\Delta$ ms) and assigns distinct letter grades for Download and Upload bufferbloat.
- **Dual-Stack IPv4 & IPv6 Support**: Automatic dual-stack detection with `-4` / `--ipv4` and `-6` / `--ipv6` switches.
- **Packet Loss Diagnostics**: Measures ICMP ping loss percentage ($0\%$ to $100\%$) with UDP socket probe fallback.
- **System, Gateway & DoH DNS Benchmarks**:
  - Benchmarks system `/etc/resolv.conf`, `resolvectl`, `nmcli`, `scutil` (macOS), Android `getprop`, and Local Gateway IP.
  - Tests public IPv4 & IPv6 resolvers: Cloudflare, Google, Quad9, OpenDNS, AdGuard.
  - Tests DNS-over-HTTPS (DoH) latencies.
  - Calculates fastest DNS recommendation and resolution speedup percentage.
- **Hardware & Network Adapter Diagnostics**: Detects active network interface, connection type (Ethernet, Wi-Fi, VPN), NIC Link Speed (e.g., 1.0 Gbps / 2.5 Gbps / 10 Gbps), Wi-Fi SSID, Signal dBm & %, Channel, Frequency Band (2.4/5/6 GHz), and MTU.
- **Interactive Glassmorphism HTML Dashboard (`--html` + `--open`)**: Self-contained, responsive dashboard with dark/light mode toggle (saved to `localStorage`), SVG score gauge, speed comparison charts, copy summary button, and PDF printing support (100% offline-ready).
- **Terminal Sparklines & History (`--history` & `--history-graph`)**: Visualizes historical speed trends directly in the terminal using Unicode sparklines (` ▂▃▅▆▇█`).
- **SLA Threshold Alerts**: Set minimum download/upload thresholds or max latency limits (`--threshold-dl`, `--threshold-ul`, `--threshold-ping`) for automated monitoring and CI/CD pipelines (exits with code `3` if violated).
- **Data Export Formats**: Structured JSON, stdout JSON (`--json-stdout`), CSV, GitHub Markdown (`--markdown`), and HTML.
- **Continuous Monitoring Mode (`--monitor`)**: Periodically logs speed benchmarks on a custom interval to track ISP performance 24/7.
- **Multi-Platform Support**: Works on Arch Linux, Fedora, Debian/Ubuntu, openSUSE, Alpine, Void, Solus, macOS, Bazzite, and Termux.

---

## Requirements

- Python 3.7+
- `curl` (for network transfers)
- `speedtest-cli` or official Ookla `speedtest` binary

---

## Installation

### Quick Setup

Run the setup script to automatically detect your operating system and configure dependencies:

```bash
chmod +x setup.sh
./setup.sh
```

### Manual Installation

**Arch Linux / Manjaro:**
```bash
sudo pacman -S python curl speedtest-cli
```

**Fedora / RHEL / Bazzite:**
```bash
sudo dnf install python3 curl speedtest-cli
```

**Debian / Ubuntu / Mint / Pop!_OS:**
```bash
sudo apt-get update && sudo apt-get install python3 python3-pip curl speedtest-cli
```

**macOS (Homebrew):**
```bash
brew install python curl speedtest-cli
```

**openSUSE:**
```bash
sudo zypper install python3 curl python3-pip
```

**Alpine Linux:**
```bash
sudo apk add python3 py3-pip curl
```

**Termux (Android):**
```bash
pkg update && pkg install python curl
pip install speedtest-cli
```

---

## Usage

You can run the benchmark directly:

```bash
./speedtest.sh [options]
```

Or with `bash` / `python3`:

```bash
bash speedtest.sh [options]
python3 speedtest.sh [options]
```

### CLI Options

```
-h, --help              Show help message and exit
-n, --runs NUM          Number of benchmark iterations (default: 3, max: 20)
--dns                   Run background DNS & DoH resolution tests
--no-dns                Explicitly skip DNS & DoH resolution tests
--engine ENGINE         Select engine: all, cloudflare, fast, speedtest, ookla, custom (default: all)
--server URL            Benchmark against a custom HTTP/HTTPS download URL
--timeout SECS          Per-stream transfer timeout in seconds (default: 18)
-4, --ipv4              Force IPv4 network requests
-6, --ipv6              Force IPv6 network requests
--html FILE             Export interactive glassmorphism HTML dashboard
--open                  Auto-open exported HTML report in default browser
--markdown FILE         Export GitHub-flavored Markdown summary report
--json FILE             Export structured benchmark data to a JSON file
--json-stdout           Output machine-readable JSON directly to stdout
--csv FILE              Export results to a CSV file
--threshold-dl MBPS     Minimum required download speed (exits with code 3 if violated)
--threshold-ul MBPS     Minimum required upload speed (exits with code 3 if violated)
--threshold-ping MS     Maximum acceptable ping latency (exits with code 3 if violated)
--history               Display historical benchmark logs and averages
--history-graph         Render sparkline trend graph with history
--history-clear         Clear historical benchmark log file
--monitor MINS          Continuous monitoring mode interval in minutes
--quiet                 Suppress banner and live progress output, show only summary
--no-color              Disable ANSI terminal colors
--debug                 Enable debug logs for troubleshooting
--version               Show version and exit
```

---

## Examples

### 1. Standard Benchmark with DNS & HTML Dashboard
```bash
./speedtest.sh --runs 3 --dns --html report.html --open
```

### 2. Fast Cloudflare-Only Speed Test
```bash
./speedtest.sh --engine cloudflare --dns
```

### 3. SLA Threshold Monitoring for Automation / CI
```bash
./speedtest.sh --engine cloudflare --threshold-dl 100 --threshold-ping 30
```

### 4. Machine-Readable JSON Output to stdout
```bash
./speedtest.sh --engine cloudflare --quiet --json-stdout | jq .statistics
```

### 5. Benchmark History with Sparkline Trend Graph
```bash
./speedtest.sh --history --history-graph
```

### 6. Continuous Monitoring Every 15 Minutes
```bash
./speedtest.sh --monitor 15 --dns
```

### 7. Custom CDN Server Benchmark
```bash
./speedtest.sh --server "https://speed.hetzner.de/100MB.bin" --dns
```

---

## Running Unit Tests

Run the included test suite to verify all calculations, algorithms, and report generators:

```bash
python3 -m unittest discover -s tests -v
```

---

## Author

Created by **Shadowharvy**