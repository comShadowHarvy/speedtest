#!/usr/bin/env python3
"""
Network Speed Benchmark Tool
Author: Shadowharvy
Description: Cross-platform speed testing tool for Arch, Fedora, Debian, Termux, and Bazzite.
Features: Ping, Download, Upload, Jitter, ISP/Geo Detection, Connectivity Check, and Data Export.
"""

import argparse
import csv
import json
import os
import re
import socket
import subprocess
import sys
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime
from typing import Dict, Optional, Tuple, List, Any
from urllib.request import urlopen
from urllib.error import URLError, HTTPError

# --- Version & Constants ---
VERSION = "1.2.0"
MAX_RETRIES = 2
BASE_RETRY_DELAY = 1  # Initial retry delay in seconds
MAX_RETRY_DELAY = 8   # Maximum retry delay in seconds (exponential backoff cap)

# Timeout constants (in seconds)
HTTP_TIMEOUT = 5
DOWNLOAD_TIMEOUT = 15
CHECK_TIMEOUT = 4
DEFAULT_WORKERS = 2   # Number of parallel threads

# Spoof a standard Google Chrome browser to bypass Corporate Firewall User-Agent filtering
USER_AGENT = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"

# Pre-compiled regex patterns for performance
JS_PATH_PATTERN = re.compile(r'src="(/app-[a-f0-9]+\.js)"')
TOKEN_PATTERN = re.compile(r'token:"([A-Za-z0-9]+)"')

def make_http_request(url: str, user_agent: str = USER_AGENT, timeout: int = HTTP_TIMEOUT, debug: bool = False) -> Optional[str]:
    """Make HTTP request using curl via subprocess with proper error handling.
    
    Args:
        url: URL to request.
        user_agent: User-Agent header.
        timeout: Request timeout in seconds.
        debug: If True, print debug information on failure.
    
    Returns:
        Response body or None on failure.
    """
    try:
        res = subprocess.run(
            ["curl", "-s", "-L", "-A", user_agent, "--max-time", str(timeout), url],
            capture_output=True,
            text=True,
            timeout=timeout + 2  # Give subprocess extra time
        )
        if res.returncode == 0:
            return res.stdout
    except subprocess.TimeoutExpired:
        if debug:
            print(f"{C.YELLOW}[DEBUG] HTTP request timeout for {url}{C.RESET}")
    except Exception as e:
        if debug:
            print(f"{C.YELLOW}[DEBUG] HTTP request failed for {url}: {e}{C.RESET}")
    return None


def exponential_backoff_delay(attempt: int, base_delay: float = BASE_RETRY_DELAY, max_delay: float = MAX_RETRY_DELAY) -> None:
    """Calculate and apply exponential backoff delay with jitter.
    
    Args:
        attempt: Current attempt number (0-indexed).
        base_delay: Initial delay in seconds.
        max_delay: Maximum delay cap in seconds.
    """
    delay = min(base_delay * (2 ** attempt), max_delay)
    time.sleep(delay)


class C:
    """ANSI color codes for terminal output styling."""
    RESET = "\033[0m"
    BOLD = "\033[1m"
    CYAN = "\033[96m"
    GREEN = "\033[92m"
    YELLOW = "\033[93m"
    RED = "\033[91m"
    BLUE = "\033[94m"
    MAGENTA = "\033[95m"
    DIM = "\033[2m"

    @classmethod
    def disable(cls):
        """Disables all ANSI color codes for clean log output or --no-color flag."""
        cls.RESET = cls.BOLD = cls.CYAN = cls.GREEN = ""
        cls.YELLOW = cls.RED = cls.BLUE = cls.MAGENTA = cls.DIM = ""


def print_banner(quiet: bool) -> None:
    """Display the application banner with version information.
    
    Args:
        quiet: If True, suppress banner output.
    """
    if quiet:
        return
    print(f"\n{C.CYAN}{C.BOLD}===================================================={C.RESET}")
    print(f"{C.CYAN}{C.BOLD}             NETWORK SPEED BENCHMARK TOOL           {C.RESET}")
    print(f"{C.DIM}          Created by: {C.MAGENTA}{C.BOLD}Shadowharvy{C.RESET} (v{VERSION})")
    print(f"{C.CYAN}{C.BOLD}===================================================={C.RESET}\n")


def check_endpoints(quiet: bool, debug: bool = False) -> Tuple[bool, bool]:
    """Performs a strict deep-API check with browser spoofing.
    
    Args:
        quiet: If True, suppress progress output.
        debug: If True, print detailed debug information.
    
    Returns:
        Tuple of (speedtest_accessible, fastcom_accessible) as booleans.
    """
    if not quiet:
        print(f"{C.BLUE}[i] Performing Pre-Flight Connectivity Check...{C.RESET}")
    
    st_ok = False
    fast_ok = False

    # Deep Check Speedtest.net
    res_st = make_http_request(
        "https://www.speedtest.net/speedtest-config.php",
        timeout=CHECK_TIMEOUT,
        debug=debug
    )
    if res_st and "client" in res_st:
        st_ok = True

    # Deep Check Fast.com
    html = make_http_request("https://fast.com", timeout=CHECK_TIMEOUT, debug=debug)
    if html:
        js_path = JS_PATH_PATTERN.search(html)
        if js_path:
            js_url = f"https://fast.com{js_path.group(1)}"
            js_content = make_http_request(js_url, timeout=CHECK_TIMEOUT, debug=debug)
            if js_content:
                token = TOKEN_PATTERN.search(js_content)
                if token:
                    api_url = f"https://api.fast.com/netflix/speedtest/v2?https=true&token={token.group(1)}&urlCount=1"
                    api_res = make_http_request(api_url, timeout=CHECK_TIMEOUT, debug=debug)
                    if api_res and "targets" in api_res:
                        fast_ok = True

    if not quiet:
        st_status = f"{C.GREEN}Accessible{C.RESET}" if st_ok else f"{C.RED}Blocked/Unreachable{C.RESET}"
        fast_status = f"{C.GREEN}Accessible{C.RESET}" if fast_ok else f"{C.RED}Blocked/Unreachable{C.RESET}"
        print(f"    {C.BOLD}Ookla (Speedtest):{C.RESET} {st_status}")
        print(f"    {C.BOLD}Netflix (Fast):{C.RESET}    {fast_status}\n")

    return st_ok, fast_ok


def get_lan_ip(debug: bool = False) -> str:
    """Gets the primary local LAN IP address by connecting to a public DNS.
    
    Args:
        debug: If True, print debug information on failure.
    
    Returns:
        Local IP address or 'Unavailable' if detection fails.
    """
    try:
        with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as s:
            s.settimeout(2)
            s.connect(("1.1.1.1", 80))
            lan_ip = s.getsockname()[0]
            return lan_ip
    except (socket.error, OSError) as e:
        if debug:
            print(f"{C.YELLOW}[DEBUG] Failed to get LAN IP: {e}{C.RESET}")
        return "Unavailable"


def get_geo_info(debug: bool = False) -> Dict[str, str]:
    """Gets public IP, ISP, and Location using ip-api.com via curl with browser spoofing.
    
    Args:
        debug: If True, print debug information on failure.
    
    Returns:
        Dictionary with keys: ip, isp, city, country. Defaults to 'Unavailable'/'Unknown' on failure.
    """
    try:
        res = make_http_request("http://ip-api.com/json/", timeout=HTTP_TIMEOUT, debug=debug)
        if res:
            data = json.loads(res)
            if isinstance(data, dict) and data.get("status") == "success":
                return {
                    "ip": data.get("query", "Unavailable"),
                    "isp": data.get("isp", "Unknown ISP"),
                    "city": data.get("city", "Unknown"),
                    "country": data.get("country", "Unknown")
                }
    except (json.JSONDecodeError, ValueError) as e:
        if debug:
            print(f"{C.YELLOW}[DEBUG] Failed to parse geolocation response: {e}{C.RESET}")
    except Exception as e:
        if debug:
            print(f"{C.YELLOW}[DEBUG] Failed to get geolocation: {e}{C.RESET}")
    return {"ip": "Unavailable", "isp": "Unknown", "city": "Unknown", "country": "Unknown"}


def get_speedtest(debug: bool = False, retries: int = MAX_RETRIES) -> Optional[Dict[str, Optional[float]]]:
    """Runs speedtest-cli and extracts ping, download, and upload speeds with exponential backoff retry.
    
    Args:
        debug: If True, print debug information.
        retries: Number of retries on failure.
    
    Returns:
        Dictionary with keys: ping, download, upload (all as floats). None if all retries fail.
    """
    # speedtest-cli uses python urllib which usually gets past basic proxy filters,
    # but we add --secure just in case it hits an HTTPS inspection proxy at work.
    for attempt in range(retries + 1):
        try:
            res = subprocess.run(
                ["speedtest-cli", "--simple", "--secure"], capture_output=True, text=True, timeout=60
            )
            ping_m = re.search(r"Ping:\s*([0-9.]+)", res.stdout)
            dl_m = re.search(r"Download:\s*([0-9.]+)", res.stdout)
            ul_m = re.search(r"Upload:\s*([0-9.]+)", res.stdout)

            if dl_m:  # Only return if we got at least download speed
                return {
                    "ping": float(ping_m.group(1)) if ping_m else None,
                    "download": float(dl_m.group(1)) if dl_m else None,
                    "upload": float(ul_m.group(1)) if ul_m else None,
                }
        except Exception as e:
            if debug:
                print(f"{C.YELLOW}[DEBUG] Speedtest attempt {attempt + 1}/{retries + 1} failed: {e}{C.RESET}")
            if attempt < retries:
                exponential_backoff_delay(attempt)
    return None


def get_fastcom(debug: bool = False, retries: int = MAX_RETRIES) -> Optional[Dict[str, float]]:
    """Fetches fast.com download speed directly via curl, spoofing a browser with exponential backoff retry.
    
    Args:
        debug: If True, print debug information.
        retries: Number of retries on failure.
    
    Returns:
        Dictionary with key: download (as float). None if all retries fail.
    """
    for attempt in range(retries + 1):
        try:
            html = make_http_request("https://fast.com", timeout=HTTP_TIMEOUT, debug=debug)
            if not html:
                raise ValueError("Failed to fetch fast.com homepage")
            
            js_path = JS_PATH_PATTERN.search(html)
            if not js_path:
                raise ValueError("JavaScript file not found")

            js_url = f"https://fast.com{js_path.group(1)}"
            js_content = make_http_request(js_url, timeout=HTTP_TIMEOUT, debug=debug)
            if not js_content:
                raise ValueError("Failed to fetch JavaScript")
            
            token = TOKEN_PATTERN.search(js_content)
            if not token:
                raise ValueError("Token not found in JavaScript")

            api_url = f"https://api.fast.com/netflix/speedtest/v2?https=true&token={token.group(1)}&urlCount=3"
            api_res = make_http_request(api_url, timeout=HTTP_TIMEOUT, debug=debug)
            if not api_res:
                raise ValueError("Failed to fetch API targets")
            
            data = json.loads(api_res)
            if not isinstance(data, dict):
                raise ValueError("Invalid API response format")

            targets = [item.get("url") for item in data.get("targets", []) if isinstance(item, dict) and "url" in item]
            if not targets:
                raise ValueError("No valid targets found")

            start_time = time.time()
            # Ensure the actual file download request also uses the User Agent
            res = subprocess.run(
                ["curl", "-s", "-L", "-A", USER_AGENT, "-r", "0-25000000", "-o", "/dev/null", targets[0]],
                timeout=DOWNLOAD_TIMEOUT
            )
            elapsed = time.time() - start_time
            
            if elapsed > 0 and res.returncode == 0:
                mbps = (25000000 * 8) / (elapsed * 1000000)
                return {"download": round(mbps, 2)}
        except (json.JSONDecodeError, ValueError, subprocess.TimeoutExpired) as e:
            if debug:
                print(f"{C.YELLOW}[DEBUG] Fast.com attempt {attempt + 1}/{retries + 1} failed: {e}{C.RESET}")
            if attempt < retries:
                exponential_backoff_delay(attempt)
        except Exception as e:
            if debug:
                print(f"{C.YELLOW}[DEBUG] Fast.com attempt {attempt + 1}/{retries + 1} failed unexpectedly: {e}{C.RESET}")
            if attempt < retries:
                exponential_backoff_delay(attempt)
    return None


def calculate_jitter(latency_list: List[float]) -> float:
    """Calculates network jitter as average variance between successive latency measurements.
    
    Args:
        latency_list: List of latency measurements in milliseconds.
    
    Returns:
        Average jitter value. 0.0 if less than 2 samples.
    """
    if len(latency_list) < 2:
        return 0.0
    diffs = [abs(latency_list[i] - latency_list[i - 1]) for i in range(1, len(latency_list))]
    return round(sum(diffs) / len(diffs), 2)


def calculate_statistics(values: List[float]) -> Dict[str, float]:
    """Calculate statistics (min, max, avg, median) for a list of values.
    
    Args:
        values: List of numerical values.
    
    Returns:
        Dictionary with min, max, avg, and median statistics.
    """
    if not values:
        return {"min": 0.0, "max": 0.0, "avg": 0.0, "median": 0.0}
    
    sorted_vals = sorted(values)
    avg = round(sum(values) / len(values), 2)
    median = sorted_vals[len(sorted_vals) // 2] if len(sorted_vals) % 2 else (sorted_vals[len(sorted_vals) // 2 - 1] + sorted_vals[len(sorted_vals) // 2]) / 2
    
    return {
        "min": round(min(values), 2),
        "max": round(max(values), 2),
        "avg": avg,
        "median": round(median, 2)
    }


def validate_file_path(filepath: str, mode: str = 'w', debug: bool = False) -> bool:
    """Validates that a file path is writable and directory exists.
    
    Args:
        filepath: Path to validate.
        mode: 'r' for read, 'w' for write.
        debug: If True, print debug information.
    
    Returns:
        True if valid, False otherwise.
    """
    try:
        dirpath = os.path.dirname(filepath)
        if dirpath and not os.path.exists(dirpath):
            os.makedirs(dirpath, exist_ok=True)
            if debug:
                print(f"{C.BLUE}[i] Created directory: {dirpath}{C.RESET}")
        
        if mode == 'w':
            # Test if we can write
            with open(filepath, 'a'):
                pass
        return True
    except Exception as e:
        if debug:
            print(f"{C.YELLOW}[DEBUG] File path validation failed: {e}{C.RESET}")
        return False


def run_single_benchmark(engine: str, run_num: int, st_ok: bool, fast_ok: bool, quiet: bool, debug: bool) -> Optional[Dict[str, Any]]:
    """Run a single benchmark iteration for specified engine.
    
    Args:
        engine: Benchmark engine ('speedtest' or 'fast').
        run_num: Run iteration number for display.
        st_ok: Whether Speedtest is accessible.
        fast_ok: Whether Fast.com is accessible.
        quiet: Suppress output if True.
        debug: Enable debug output if True.
    
    Returns:
        Dictionary with benchmark results or None on failure.
    """
    if engine == "speedtest" and st_ok:
        if not quiet:
            print(f"  Run {run_num}... ", end="", flush=True)
        res = get_speedtest(debug, MAX_RETRIES)
        if res and res.get("download"):
            if not quiet:
                print(f"{C.GREEN}DL: {res['download']} Mbps{C.RESET} | {C.YELLOW}UL: {res['upload']} Mbps{C.RESET} {C.DIM}(Ping: {res['ping']}ms){C.RESET}")
            return res
        if not quiet:
            print(f"{C.RED}Failed (Skipped){C.RESET}")
    elif engine == "fast" and fast_ok:
        if not quiet:
            print(f"  Run {run_num}... ", end="", flush=True)
        res = get_fastcom(debug, MAX_RETRIES)
        if res and res.get("download"):
            if not quiet:
                print(f"{C.GREEN}DL: {res['download']} Mbps{C.RESET}")
            return res
        if not quiet:
            print(f"{C.RED}Failed (Skipped){C.RESET}")
    return None


def run_benchmark() -> int:
    """Main benchmark orchestration function. Runs all tests and exports results.
    
    Returns:
        Exit code: 0 for success, 1 for partial failure, 2 for complete failure.
    """
    # --- Parse CLI Arguments ---
    parser = argparse.ArgumentParser(
        description="Network Speed Benchmark Tool by Shadowharvy",
        epilog="Example: python3 speedtest.sh --runs 3 --json results.json"
    )
    parser.add_argument("-n", "--runs", type=int, default=3, help="Number of benchmark iterations (default: 3)")
    parser.add_argument("--quiet", action="store_true", help="Suppress progress output, show only summary")
    parser.add_argument("--no-color", action="store_true", help="Disable ANSI color output")
    parser.add_argument("--json", type=str, metavar="FILE", help="Export results to a JSON file")
    parser.add_argument("--csv", type=str, metavar="FILE", help="Export results to a CSV file")
    parser.add_argument("--debug", action="store_true", help="Enable debug output for troubleshooting")
    parser.add_argument("--version", action="version", version=f"%(prog)s {VERSION}", help="Show version and exit")
    args = parser.parse_args()

    # Validate arguments
    if args.runs < 1 or args.runs > 20:
        print(f"{C.RED}[!] Error: --runs must be between 1 and 20{C.RESET}")
        return 1
    
    # Validate file paths
    if args.json and not validate_file_path(args.json, debug=args.debug):
        print(f"{C.RED}[!] Error: Cannot write to JSON file: {args.json}{C.RESET}")
        return 1
    
    if args.csv and not validate_file_path(args.csv, debug=args.debug):
        print(f"{C.RED}[!] Error: Cannot write to CSV file: {args.csv}{C.RESET}")
        return 1

    if args.no_color:
        C.disable()

    print_banner(args.quiet)
    
    if args.debug:
        print(f"{C.BLUE}[DEBUG] Debug mode enabled. Version: {VERSION}{C.RESET}")
        print(f"{C.BLUE}[DEBUG] Runs configured: {args.runs}{C.RESET}\n")

    # --- Pre-Flight Checks ---
    st_ok, fast_ok = check_endpoints(args.quiet, args.debug)

    # --- Fetching Network Info ---
    if not args.quiet: print(f"{C.BLUE}[i] Fetching Network Interfaces & Geolocation...{C.RESET}")
    lan_ip = get_lan_ip(args.debug)
    geo = get_geo_info(args.debug)
    
    if not args.quiet:
        print(f"    {C.BOLD}Local IP (LAN):{C.RESET} {C.YELLOW}{lan_ip}{C.RESET}")
        print(f"    {C.BOLD}Public IP (WAN):{C.RESET}{C.YELLOW}{geo['ip']}{C.RESET} ({geo['isp']} - {geo['city']}, {geo['country']})\n")

    st_results: List[Dict[str, Any]] = []
    fast_results: List[Dict[str, Any]] = []

    # --- 1. Speedtest.net ---
    if st_ok:
        if not args.quiet:
            print(f"{C.CYAN}{C.BOLD}--- Running Speedtest.net (Ookla) Benchmark ---{C.RESET}")
        for i in range(1, args.runs + 1):
            res = run_single_benchmark("speedtest", i, st_ok, fast_ok, args.quiet, args.debug)
            if res:
                st_results.append(res)
            time.sleep(1)
    else:
        if not args.quiet:
            print(f"{C.RED}{C.BOLD}--- Skipping Speedtest.net (Blocked by Network) ---{C.RESET}")

    # --- 2. Fast.com ---
    if fast_ok:
        if not args.quiet:
            print(f"\n{C.CYAN}{C.BOLD}--- Running Fast.com (Netflix CDN) Benchmark ---{C.RESET}")
        for i in range(1, args.runs + 1):
            res = run_single_benchmark("fast", i, st_ok, fast_ok, args.quiet, args.debug)
            if res:
                fast_results.append(res)
            time.sleep(1)
    else:
        if not args.quiet:
            print(f"\n{C.RED}{C.BOLD}--- Skipping Fast.com (Blocked by Network) ---{C.RESET}")

    # --- Calculations with Statistics ---
    st_dls = [r["download"] for r in st_results if r.get("download")]
    st_uls = [r["upload"] for r in st_results if r.get("upload")]
    st_pings = [r["ping"] for r in st_results if r.get("ping")]
    fast_dls = [r["download"] for r in fast_results if r.get("download")]

    # Calculate statistics for all metrics
    st_dl_stats = calculate_statistics(st_dls)
    st_ul_stats = calculate_statistics(st_uls)
    fast_dl_stats = calculate_statistics(fast_dls)
    ping_stats = calculate_statistics(st_pings)
    jitter = calculate_jitter(st_pings) if st_pings else 0.0
    
    # Use averages for export
    st_dl_avg = st_dl_stats["avg"]
    st_ul_avg = st_ul_stats["avg"]
    fast_dl_avg = fast_dl_stats["avg"]
    ping_avg = ping_stats["avg"]

    # --- Print Summary ---
    print(f"\n{C.MAGENTA}{C.BOLD}===================================================={C.RESET}")
    print(f"{C.MAGENTA}{C.BOLD}                  BENCHMARK SUMMARY                 {C.RESET}")
    print(f"{C.MAGENTA}{C.BOLD}===================================================={C.RESET}")
    print(f" {C.BOLD}Author:{C.RESET}         Shadowharvy")
    print(f" {C.BOLD}Local IP:{C.RESET}       {lan_ip}")
    print(f" {C.BOLD}Public IP:{C.RESET}      {geo['ip']} ({geo['isp']})")
    print(f" {C.BOLD}Location:{C.RESET}       {geo['city']}, {geo['country']}")
    print(f" {C.DIM}----------------------------------------------------{C.RESET}")
    
    if st_ok:
        print(f" {C.BOLD}Ookla Download:{C.RESET} {C.GREEN}{st_dl_stats['avg']} Mbps{C.RESET} {C.DIM}(min: {st_dl_stats['min']}, max: {st_dl_stats['max']}) ({len(st_dls)}/{args.runs}){C.RESET}")
        print(f" {C.BOLD}Ookla Upload:{C.RESET}   {C.GREEN}{st_ul_stats['avg']} Mbps{C.RESET} {C.DIM}(min: {st_ul_stats['min']}, max: {st_ul_stats['max']}){C.RESET}")
    else:
        print(f" {C.BOLD}Ookla Benchmark:{C.RESET} {C.RED}Blocked by Network{C.RESET}")

    if fast_ok:
        print(f" {C.BOLD}Fast Download:{C.RESET}  {C.GREEN}{fast_dl_stats['avg']} Mbps{C.RESET} {C.DIM}(min: {fast_dl_stats['min']}, max: {fast_dl_stats['max']}) ({len(fast_dls)}/{args.runs}){C.RESET}")
    else:
        print(f" {C.BOLD}Fast Benchmark:{C.RESET}  {C.RED}Blocked by Network{C.RESET}")
        
    print(f" {C.BOLD}Average Ping:{C.RESET}   {C.YELLOW}{ping_stats['avg']} ms{C.RESET} {C.DIM}(min: {ping_stats['min']}, max: {ping_stats['max']}){C.RESET}")
    print(f" {C.BOLD}Jitter:{C.RESET}         {C.YELLOW}{jitter} ms{C.RESET}")
    print(f"{C.MAGENTA}{C.BOLD}===================================================={C.RESET}\n")

    # --- Data Export Logic ---
    export_data: Dict[str, Any] = {
        "timestamp": datetime.now().isoformat(),
        "version": VERSION,
        "network": {"lan_ip": lan_ip, "geo": geo, "status": {"speedtest": "ok" if st_ok else "blocked", "fast": "ok" if fast_ok else "blocked"}},
        "statistics": {
            "speedtest_download_mbps": st_dl_stats,
            "speedtest_upload_mbps": st_ul_stats,
            "fast_download_mbps": fast_dl_stats,
            "ping_ms": ping_stats,
            "jitter_ms": jitter
        },
        "raw_results": {"speedtest": st_results, "fast": fast_results}
    }

    # --- Data Export with Error Handling ---
    exit_code = 0
    
    if args.json:
        try:
            with open(args.json, "w") as f:
                json.dump(export_data, f, indent=4)
            if not args.quiet: print(f"{C.GREEN}[✔] JSON data exported to {args.json}{C.RESET}")
        except Exception as e:
            print(f"{C.RED}[!] Failed to write JSON: {e}{C.RESET}")
            exit_code = 1

    if args.csv:
        try:
            with open(args.csv, "w", newline="") as f:
                writer = csv.writer(f)
                writer.writerow(["Engine", "Run", "Download (Mbps)", "Upload (Mbps)", "Ping (ms)"])
                for idx, r in enumerate(st_results):
                    writer.writerow(["Speedtest", idx + 1, r.get("download", ""), r.get("upload", ""), r.get("ping", "")])
                for idx, r in enumerate(fast_results):
                    writer.writerow(["Fast.com", idx + 1, r.get("download", ""), "", ""])
            if not args.quiet: print(f"{C.GREEN}[✔] CSV data exported to {args.csv}{C.RESET}")
        except Exception as e:
            print(f"{C.RED}[!] Failed to write CSV: {e}{C.RESET}")
            exit_code = 1
    
    # Return exit code (success if any test ran, failure if all blocked)
    if not st_ok and not fast_ok:
        return 2  # All services blocked
    
    return exit_code


if __name__ == "__main__":
    try:
        sys.exit(run_benchmark())
    except KeyboardInterrupt:
        print(f"\n{C.YELLOW}[!] Benchmark interrupted by user{C.RESET}")
        sys.exit(130)
    except Exception as e:
        print(f"{C.RED}[!] Unexpected error: {e}{C.RESET}")
        sys.exit(1)