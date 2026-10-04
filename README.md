# Network Speed & Diagnostic Benchmark Tool

A high-performance, cross-platform CLI tool for network speed benchmarking, dual-stack IPv4/IPv6 diagnostics, directional bufferbloat analysis (DL/UL), DNS & DoH resolution tests, hardware link speed detection, interactive HTML dashboard generation, and SLA threshold monitoring.

**Version: 3.2.0** | Universal Shell Execution, Multi-Gigabit Saturation, Parallelized DNS Engine, Specialized DNS Profiles, Directional Bufferbloat (DL/UL), Dual-Stack IPv4/IPv6, Hardware Link Speeds, Unicode Sparklines, DoH Benchmarking, and Modern Glassmorphism Dashboard

---

## Key Features

- **Universal Shell Execution**: Runs seamlessly via `./speedtest.sh`, `bash speedtest.sh`, `sh speedtest.sh`, or `python3 speedtest.sh`.
- **Multi-Engine Speed Testing**:
  - **Ookla (Speedtest.net)**: Native official Ookla binary auto-detection (`speedtest --format=json`) with native IQM loaded latency extraction, falling back to `speedtest-cli`.
  - **Fast.com (Netflix CDN)**: Multi-stream adaptive chunking (saturates 1Gbps+ connections) with resilient JS token extraction.
  - **Cloudflare CDN**: Multi-worker parallel download & streaming upload tests with automatic temporary file cleanup.
  - **Custom Server (`--server <URL>`)**: Benchmark any custom HTTP/HTTPS CDN or endpoint.
- **Engine Filter (`--engine`)**: Select specific engines (`cloudflare`, `fast`, `speedtest`, `ookla`, `custom`, `all`).
- **Directional Bufferbloat & Loaded Latency ($A^+$ to $F$)**:
  - Measures authentic baseline idle ping vs. active download loaded ping vs. active upload loaded ping.
  - Calculates directional latency deltas ($\Delta$ ms) and assigns distinct letter grades for Download and Upload bufferbloat.
- **Dedicated Baseline Idle Ping & Jitter**: Accurate baseline RTT measurement via ICMP ping with UDP socket probe fallback, ensuring accurate metrics even on download-only benchmarks.
- **Dual-Stack IPv4 & IPv6 with Route Verification**: Automatic dual-stack detection with `-4` / `--ipv4` and `-6` / `--ipv6` switches, with proactive route availability probes to avoid unrouted IPv6 hangs.
- **High-Speed Parallelized DNS Resolution Engine**:
  - Concurrent thread pool for DNS resolver benchmarking (cuts test time by over 10x).
  - Benchmarks system `/etc/resolv.conf`, `resolvectl`, `nmcli`, `scutil` (macOS), Android `getprop`, and Local Gateway IP.
  - Tests public IPv4 & IPv6 resolvers: Cloudflare, Google, Quad9, OpenDNS, AdGuard.
  - Tests DNS-over-HTTPS (DoH) latencies.
- **Specialized Multi-Profile DNS Recommendations**:
  - Tailored recommendations across 4 specialized profiles:
    - 🚀 **Speed & Privacy**: Cloudflare (`1.1.1.1` / `1.0.0.1` / `2606:4700:4700::1111`)
    - 🛡️ **Threat & Malware Protection**: Quad9 (`9.9.9.9` / `149.112.112.112`)
    - 🚫 **Ad & Tracker Blocking**: AdGuard (`94.140.14.14` / `94.140.15.15`)
    - 🌐 **Global Anycast Reliability**: Google Public DNS (`8.8.8.8` / `8.8.4.4`)
  - Displays dynamic latency benchmarks, rank, and percentage speedup vs. current system resolver.
- **Hardware & Network Adapter Diagnostics**: Detects active network interface, connection type (Ethernet, Wi-Fi, VPN), NIC Link Speed (e.g., 1.0 Gbps / 2.5 Gbps / 10 Gbps), Wi-Fi SSID, Signal dBm & %, Channel, Frequency Band (2.4/5/6 GHz), and MTU (including `/proc/net/wireless` and macOS `scutil` fallbacks).
- **Interactive Glassmorphism HTML Dashboard (`report.html` & auto-opened by default)**: Self-contained, responsive dashboard with Outfit & JetBrains Mono typography, animated SVG score gauge, directional bufferbloat visualizer, 1-click copy for DNS IPs with toast notifications, client-side JSON export, dark/light mode toggle (saved to `localStorage`), and PDF printing support (100% offline-ready). Automatically exported to `report.html` and opened in your preferred browser (Firefox → Brave → Chrome) after testing (disable with `--no-open` or `--no-html`).
- **Terminal Sparklines & History (`--history` & `--history-graph`)**: Visualizes historical speed trends directly in the terminal using Unicode sparklines (` ▂▃▅▆▇█`).
- **SLA Threshold Alerts**: Set minimum download/upload thresholds or max latency limits (`--threshold-dl`, `--threshold-ul`, `--threshold-ping`) for automated monitoring and CI/CD pipelines (exits with code `3` if violated).
- **Data Export Formats**: Structured JSON, stdout JSON (`--json-stdout`), CSV (with DL/UL latency & jitter columns), GitHub Markdown (`--markdown`), and HTML.
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
--html [FILE]           Export interactive glassmorphism HTML dashboard (default: report.html)
--no-html               Explicitly disable HTML report export
--open                  Auto-open exported HTML report in browser after test (default: enabled)
--no-open               Explicitly disable auto-opening HTML report in browser
--open-only             Open existing HTML report in preferred browser and exit without running benchmark
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
--monitor MINS          Continuous monitoring mode interval in minutes (1..1440)
--quiet                 Suppress banner and live progress output, show only summary
--no-color              Disable ANSI terminal colors
--debug                 Enable debug logs for troubleshooting
--version               Show version and exit
```

### Argument Validation

Invalid flag combinations fail fast, before any benchmark work is done:

- `--runs` must be between 1 and 20
- `--timeout` must be at least 1 second
- `--monitor` must be between 1 and 1440 minutes
- `--threshold-dl`, `--threshold-ul`, `--threshold-ping` must be greater than 0
- `--engine custom` requires `--server <URL>`
- `--server` cannot be combined with a non-`all`, non-`custom` engine
- `--server` must use `http://` or `https://` (blocks `file://` and other local/scheme abuse)
- `--dns`/`--no-dns`, `-4`/`-6`, `--html`/`--no-html`, `--open`/`--no-open` are mutually exclusive

### Exit Codes

| Code | Meaning |
| ---- | ------- |
| 0 | Success |
| 1 | Invalid arguments, or a report export failed |
| 2 | No benchmark engine produced a measurement |
| 3 | An SLA threshold was violated |
| 130 | Interrupted by user (Ctrl+C) |

In `--json-stdout` mode, JSON is the only thing written to stdout; SLA alerts
and export errors go to stderr so the output stays pipeable into `jq`.
SLA thresholds are only evaluated when at least one measurement succeeded, so
a fully failed run reports exit code 2 instead of false threshold breaches.

In `--monitor` mode, monitoring aborts with exit code 2 after 3 consecutive
cycles produced no measurements, and `Ctrl+C` exits cleanly with code 0.

---

## Examples

### 1. Standard Benchmark with DNS & HTML Dashboard
```bash
./speedtest.sh --runs 3 --dns --open
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

### 8. Custom Engine Only (skip all built-in engines)
```bash
./speedtest.sh --engine custom --server "https://speed.hetzner.de/100MB.bin"
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