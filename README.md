# Network Speed Benchmark Tool

A cross-platform CLI tool for testing network speed, measuring connectivity, and generating detailed reports with geolocation detection.

**Version: 1.5.7** | Asynchronous background DNS testing, direct UDP DNS resolver latency measurements, improved setup script, and bug fixes

## Features

- **Speed Testing**: Download and upload speed measurements
- **Network Diagnostics**: Ping latency and jitter analysis
- **Geolocation Detection**: ISP and location information
- **Connectivity Check**: Verify internet connectivity before testing
- **Data Export**: Export results in JSON and CSV formats
- **Retry Logic**: Automatic retries on failed tests (up to 2 attempts)
- **Multi-Platform Support**: Works on Arch Linux, Fedora, Debian/Ubuntu, Bazzite, and Termux
- **Browser Spoofing**: Bypasses corporate firewall restrictions with Chrome user-agent
- **Colored Output**: Beautiful terminal formatting with ANSI colors
- **Quiet Mode**: Clean output for scripting and automation
- **Debug Mode**: Troubleshooting with detailed diagnostic output
- **Input Validation**: Validates file paths and parameters before execution

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
-h, --help              Show help message and exit
-n, --runs NUM          Number of benchmark iterations (default: 3, max: 20)
--dns                   Run DNS resolution test in background alongside speed tests
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

**Run custom number of tests:**
```bash
python3 speedtest.sh --runs 5
```

**Export results to JSON:**
```bash
python3 speedtest.sh --json results.json
```

**Export results to CSV:**
```bash
python3 speedtest.sh --csv results.csv
```

**Quiet mode (for automation):**
```bash
python3 speedtest.sh --quiet --json output.json
```

**Debug mode (troubleshooting):**
```bash
python3 speedtest.sh --debug
```

**Show version:**
```bash
python3 speedtest.sh --version
```

**Disable colors for log files:**
```bash
python3 speedtest.sh --no-color > speedtest.log
```

## Advanced Features

### Retry Logic

Failed tests automatically retry up to 2 times with a 2-second delay between attempts, ensuring more reliable results on unstable networks.

### File Path Validation

The tool automatically validates file paths for JSON and CSV exports. Missing directories are created automatically if possible.

### Exit Codes

The script returns proper exit codes for automation:

- `0` - Success (at least one test service available)
- `1` - File write error (JSON/CSV export failed)
- `2` - All services blocked (network connectivity issues)

### Debug Mode

Enable `--debug` flag for detailed troubleshooting:

```bash
python3 speedtest.sh --debug
```

Shows:

- Version and configuration on startup
- Detailed error messages for failed operations
- Individual retry attempts and failures
- Network detection status

## Output

Each test produces a detailed summary including:

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