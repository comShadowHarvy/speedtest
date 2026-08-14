# Network Speed Benchmark Tool

A cross-platform CLI tool for testing network speed, measuring connectivity, and generating detailed reports with geolocation detection.

## Features

- **Speed Testing**: Download and upload speed measurements
- **Network Diagnostics**: Ping latency and jitter analysis
- **Geolocation Detection**: ISP and location information
- **Connectivity Check**: Verify internet connectivity before testing
- **Data Export**: Export results in JSON and CSV formats
- **Multi-Platform Support**: Works on Arch Linux, Fedora, Debian/Ubuntu, Bazzite, and Termux
- **Browser Spoofing**: Bypasses corporate firewall restrictions with Chrome user-agent
- **Colored Output**: Beautiful terminal formatting with ANSI colors
- **Quiet Mode**: Clean output for scripting and automation

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

The setup script will:

1. Detect your Linux distribution or Termux environment
2. Install required packages (`python3`, `curl`, `speedtest-cli`)
3. Make scripts executable

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
-h, --help              Show help message
--download              Test download speed
--upload                Test upload speed
--ping                  Test ping latency
--jitter                Test jitter
--list                  List available speedtest servers
--simple                Simple output format
--json                  Output results as JSON
--csv FILE              Export results to CSV file
--no-color              Disable colored output
--quiet                 Suppress banner and info messages
```

### Examples

**Run full speed test:**
```bash
python3 speedtest.sh
```

**Test download speed only:**
```bash
python3 speedtest.sh --download
```

**Export results to JSON:**
```bash
python3 speedtest.sh --json > results.json
```

**Export results to CSV:**
```bash
python3 speedtest.sh --csv results.csv
```

**Quiet mode (for automation):**
```bash
python3 speedtest.sh --quiet --json
```

## Output

The tool provides detailed information including:

- Download/Upload speeds (Mbps)
- Ping latency (ms)
- Jitter measurement
- ISP information
- Geolocation (Country, City, Timezone)
- Timestamp of test

## Author

Created by **Shadowharvy**

## License

[Add license information if applicable]

## Contributing

Contributions are welcome! Feel free to submit issues and pull requests.

## Troubleshooting

### "speedtest-cli not found" error

Run the setup script or manually install: `pip install speedtest-cli`

### Permission denied

Make scripts executable:

```bash
chmod +x speedtest.sh setup.sh
```

### Network timeout

- Check your internet connection
- Try using a VPN if behind a corporate firewall
- Ensure `curl` is properly installed

### Sudo password prompt

The setup script may request sudo access for system package installation. This is normal and required.

## Notes

- The tool uses a Chrome browser user-agent to bypass corporate firewall restrictions
- For accurate results, close bandwidth-heavy applications during testing
- Results vary based on time of day and network congestion
- Multiple tests are recommended for consistent measurements