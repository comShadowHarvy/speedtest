#!/usr/bin/env python3
"""
Network Speed Benchmark Tool
Author: Shadowharvy
Description: Cross-platform speed testing tool for Arch, Fedora, Debian, Termux, and Bazzite.
Features: Ping, Download, Upload, Jitter, ISP/Geo Detection, Connectivity Check, Cloudflare CDN,
          Bufferbloat Testing, Wi-Fi Adapter Info, History Tracking, HTML Report Export,
          Network Quality & Suitability Scoring, DNS Recommendation, and Continuous Monitoring.
"""

import argparse
import csv
import json
import os
import re
import socket
import subprocess
import sys
import tempfile
import threading
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime
from typing import Dict, Optional, Tuple, List, Any

# --- Version & Constants ---
VERSION = "2.0.0"
MAX_RETRIES = 2
BASE_RETRY_DELAY = 1  # Initial retry delay in seconds
MAX_RETRY_DELAY = 8   # Maximum retry delay in seconds (exponential backoff cap)

# Timeout constants (in seconds)
HTTP_TIMEOUT = 5
DOWNLOAD_TIMEOUT = 15
CHECK_TIMEOUT = 4
DNS_TIMEOUT = 3
DEFAULT_WORKERS = 4   # Number of parallel threads

HISTORY_FILE = os.path.expanduser("~/.speedtest_history.json")

# DNS Resolver Configuration
DNS_RESOLVERS = [
    {"name": "Google", "ip": "8.8.8.8", "port": 53},
    {"name": "Cloudflare", "ip": "1.1.1.1", "port": 53},
    {"name": "Quad9", "ip": "9.9.9.9", "port": 53},
]

# DNS Queries to test
DNS_QUERIES = ["google.com", "github.com", "cloudflare.com"]

# Spoof a standard Google Chrome browser to bypass Corporate Firewall User-Agent filtering
USER_AGENT = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"

# Pre-compiled regex patterns for performance
JS_PATH_PATTERN = re.compile(r'src="(/app-[a-f0-9]+\.js)"')
TOKEN_PATTERN = re.compile(r'token:"([A-Za-z0-9]+)"')


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


class Spinner:
    """Animated progress spinner for live terminal feedback."""
    def __init__(self, message: str, quiet: bool = False):
        self.message = message
        self.quiet = quiet
        self.stop_event = threading.Event()
        self.thread = None

    def _spin(self):
        chars = ["⠋", "⠙", "⠹", "⠸", "⠼", "⠴", "⠦", "⠧", "⠇", "⠏"]
        idx = 0
        while not self.stop_event.is_set():
            sys.stdout.write(f"\r  {C.CYAN}{chars[idx % len(chars)]}{C.RESET} {self.message}... ")
            sys.stdout.flush()
            idx += 1
            time.sleep(0.1)

    def start(self):
        if not self.quiet:
            self.stop_event.clear()
            self.thread = threading.Thread(target=self._spin, daemon=True)
            self.thread.start()

    def stop(self, done_text: str = ""):
        if not self.quiet:
            self.stop_event.set()
            if self.thread:
                self.thread.join(timeout=0.5)
            sys.stdout.write("\r\033[K")
            if done_text:
                print(f"  {done_text}")
            sys.stdout.flush()


def make_http_request(url: str, user_agent: str = USER_AGENT, timeout: int = HTTP_TIMEOUT, debug: bool = False) -> Optional[str]:
    """Make HTTP request using curl via subprocess with proper error handling."""
    try:
        res = subprocess.run(
            ["curl", "-s", "-L", "-A", user_agent, "--max-time", str(timeout), url],
            capture_output=True,
            text=True,
            timeout=timeout + 2
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
    """Calculate and apply exponential backoff delay with jitter."""
    delay = min(base_delay * (2 ** attempt), max_delay)
    time.sleep(delay)


def build_dns_query(hostname: str) -> bytes:
    """Build a standard DNS A record query packet."""
    header = b"\xaa\xbb\x01\x00\x00\x01\x00\x00\x00\x00\x00\x00"
    qname = b"".join(bytes([len(part)]) + part.encode("ascii") for part in hostname.split(".")) + b"\x00"
    qtype = b"\x00\x01"   # Type A
    qclass = b"\x00\x01"  # Class IN
    return header + qname + qtype + qclass


def get_dns_latency(resolver: Dict[str, Any], hostname: str, timeout: int = DNS_TIMEOUT, debug: bool = False) -> Optional[float]:
    """Query a DNS resolver via UDP socket and measure lookup time."""
    try:
        query_packet = build_dns_query(hostname)
        s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        s.settimeout(timeout)
        try:
            start = time.time()
            s.sendto(query_packet, (resolver["ip"], resolver.get("port", 53)))
            data, _ = s.recvfrom(512)
            elapsed = (time.time() - start) * 1000
            if len(data) >= 12:
                return round(elapsed, 2)
        finally:
            s.close()
    except (socket.timeout, socket.gaierror, OSError) as e:
        if debug:
            print(f"{C.YELLOW}[DEBUG] UDP DNS query failed for {resolver['name']} ({resolver['ip']}) on {hostname}: {e}{C.RESET}")
    except Exception as e:
        if debug:
            print(f"{C.YELLOW}[DEBUG] Unexpected DNS error for {resolver['name']}: {e}{C.RESET}")
    return None


def run_dns_test(runs: int = 3, quiet: bool = False, debug: bool = False, gateway_ip: Optional[str] = None) -> Optional[Dict[str, Any]]:
    """Run DNS resolution test against multiple resolvers including the local gateway."""
    if not quiet:
        print(f"{C.CYAN}{C.BOLD}--- Running DNS Resolution Test ---{C.RESET}")
    
    resolvers_to_test = list(DNS_RESOLVERS)
    if gateway_ip and gateway_ip not in ("Unknown", "Unavailable"):
        if not any(r["ip"] == gateway_ip for r in resolvers_to_test):
            resolvers_to_test.insert(0, {"name": f"Local Gateway ({gateway_ip})", "ip": gateway_ip, "port": 53})

    dns_results = {}
    all_times = []
    
    for resolver in resolvers_to_test:
        resolver_name = resolver["name"]
        resolver_times = []
        
        for run in range(runs):
            for query in DNS_QUERIES:
                latency = get_dns_latency(resolver, query, DNS_TIMEOUT, debug)
                if latency:
                    resolver_times.append(latency)
                    all_times.append(latency)
        
        if resolver_times:
            stats = calculate_statistics(resolver_times)
            dns_results[resolver_name] = {
                "resolver_ip": resolver["ip"],
                "queries": len(resolver_times),
                "latency_ms": stats
            }
            if not quiet:
                print(f"  {resolver_name}... {C.GREEN}✓ {stats['avg']} ms avg{C.RESET} {C.DIM}(min: {stats['min']}, max: {stats['max']}){C.RESET}")
        else:
            if not quiet:
                print(f"  {resolver_name}... {C.RED}✗ Failed{C.RESET}")
    
    overall_stats = calculate_statistics(all_times) if all_times else {"min": 0.0, "max": 0.0, "avg": 0.0, "median": 0.0}
    
    return {
        "dns_resolvers": dns_results,
        "overall_latency_ms": overall_stats,
        "total_queries": len(all_times)
    }


def get_fastest_dns_recommendation(dns_results: Optional[Dict[str, Any]]) -> Optional[Dict[str, Any]]:
    """Determine the fastest DNS resolver and compute latency savings percentage."""
    if not dns_results or not dns_results.get("dns_resolvers"):
        return None
    resolvers = dns_results["dns_resolvers"]
    valid = []
    for name, data in resolvers.items():
        avg = data.get("latency_ms", {}).get("avg", 0.0)
        if avg > 0:
            valid.append((name, data["resolver_ip"], avg))
    if not valid:
        return None
    valid.sort(key=lambda x: x[2])
    fastest = valid[0]
    slowest = valid[-1]
    savings_pct = round(((slowest[2] - fastest[2]) / slowest[2]) * 100, 1) if slowest[2] > 0 else 0.0
    return {
        "name": fastest[0],
        "ip": fastest[1],
        "latency_ms": fastest[2],
        "savings_pct": savings_pct,
        "slowest_name": slowest[0]
    }


def calculate_network_suitability(dl_mbps: float, ul_mbps: float, ping_ms: float, jitter_ms: float, bb_grade: str) -> Dict[str, Any]:
    """Calculate overall Network Quality Score (0-100) and real-world application ratings."""
    # 1. Gaming Rating
    gaming_score = 100.0
    if ping_ms > 100: gaming_score -= 40
    elif ping_ms > 50: gaming_score -= 20
    elif ping_ms > 30: gaming_score -= 10

    if jitter_ms > 20: gaming_score -= 25
    elif jitter_ms > 10: gaming_score -= 15

    if bb_grade in ("D", "F"): gaming_score -= 30
    elif bb_grade in ("C",): gaming_score -= 15

    gaming_score = max(0.0, min(100.0, gaming_score))
    if gaming_score >= 85: gaming_status = "Excellent (Competitive)"
    elif gaming_score >= 70: gaming_status = "Good (Casual)"
    elif gaming_score >= 50: gaming_status = "Fair (Occasional Lags)"
    else: gaming_status = "Poor (High Lag)"

    # 2. 4K Streaming Rating
    streaming_score = 100.0
    if dl_mbps < 5: streaming_score = 10
    elif dl_mbps < 25: streaming_score = 60
    elif dl_mbps < 50: streaming_score = 85

    if streaming_score >= 85: streaming_status = "Excellent (Multi-Device 4K/8K)"
    elif streaming_score >= 60: streaming_status = "Good (Single 4K Stream)"
    else: streaming_status = "Poor (1080p Max)"

    # 3. Video Call Rating
    video_call_score = 100.0
    if ul_mbps < 3: video_call_score -= 40
    elif ul_mbps < 10: video_call_score -= 15

    if ping_ms > 80: video_call_score -= 30
    if jitter_ms > 15: video_call_score -= 20

    video_call_score = max(0.0, min(100.0, video_call_score))
    if video_call_score >= 85: video_call_status = "Flawless (HD/4K Group Calls)"
    elif video_call_score >= 65: video_call_status = "Good (HD Calls)"
    else: video_call_status = "Poor (Audio/Video Dropouts)"

    # Overall Score
    overall_score = round((gaming_score * 0.35) + (streaming_score * 0.35) + (video_call_score * 0.30), 1)

    return {
        "overall_score": overall_score,
        "gaming": {"score": round(gaming_score, 1), "status": gaming_status},
        "streaming": {"score": round(streaming_score, 1), "status": streaming_status},
        "video_call": {"score": round(video_call_score, 1), "status": video_call_status}
    }


def print_banner(quiet: bool) -> None:
    """Display the application banner with version information."""
    if quiet:
        return
    print(f"\n{C.CYAN}{C.BOLD}===================================================={C.RESET}")
    print(f"{C.CYAN}{C.BOLD}             NETWORK SPEED BENCHMARK TOOL           {C.RESET}")
    print(f"{C.DIM}          Created by: {C.MAGENTA}{C.BOLD}Shadowharvy{C.RESET} (v{VERSION})")
    print(f"{C.CYAN}{C.BOLD}===================================================={C.RESET}\n")


def check_endpoints(quiet: bool, debug: bool = False) -> Tuple[bool, bool, bool]:
    """Performs pre-flight connectivity checks for Ookla, Fast.com, and Cloudflare."""
    if not quiet:
        print(f"{C.BLUE}[i] Performing Pre-Flight Connectivity Check...{C.RESET}")
    
    st_ok = False
    fast_ok = False
    cf_ok = False

    res_st = make_http_request("https://www.speedtest.net/speedtest-config.php", timeout=CHECK_TIMEOUT, debug=debug)
    if res_st and "client" in res_st:
        st_ok = True

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

    res_cf = make_http_request("https://speed.cloudflare.com/__down?bytes=1", timeout=CHECK_TIMEOUT, debug=debug)
    if res_cf is not None:
        cf_ok = True

    if not quiet:
        st_status = f"{C.GREEN}Accessible{C.RESET}" if st_ok else f"{C.RED}Blocked/Unreachable{C.RESET}"
        fast_status = f"{C.GREEN}Accessible{C.RESET}" if fast_ok else f"{C.RED}Blocked/Unreachable{C.RESET}"
        cf_status = f"{C.GREEN}Accessible{C.RESET}" if cf_ok else f"{C.RED}Blocked/Unreachable{C.RESET}"
        print(f"    {C.BOLD}Ookla (Speedtest):{C.RESET} {st_status}")
        print(f"    {C.BOLD}Netflix (Fast):{C.RESET}    {fast_status}")
        print(f"    {C.BOLD}Cloudflare CDN:{C.RESET}    {cf_status}\n")

    return st_ok, fast_ok, cf_ok


def get_network_adapter_info(debug: bool = False) -> Dict[str, str]:
    """Detects active network interface, gateway IP, Wi-Fi SSID, and signal strength."""
    info = {
        "interface": "Unknown",
        "gateway": "Unknown",
        "wifi_ssid": "N/A (Wired/Unknown)",
        "wifi_signal": "N/A"
    }
    try:
        res = subprocess.run(["ip", "route", "show", "default"], capture_output=True, text=True, timeout=3)
        if res.returncode == 0 and res.stdout:
            parts = res.stdout.strip().split()
            if "via" in parts and "dev" in parts:
                info["gateway"] = parts[parts.index("via") + 1]
                info["interface"] = parts[parts.index("dev") + 1]
    except Exception as e:
        if debug:
            print(f"{C.YELLOW}[DEBUG] Route query failed: {e}{C.RESET}")

    if info["interface"] != "Unknown":
        iface = info["interface"]
        try:
            res = subprocess.run(["nmcli", "-t", "-f", "active,ssid,signal", "dev", "wifi"], capture_output=True, text=True, timeout=3)
            if res.returncode == 0 and res.stdout:
                for line in res.stdout.strip().split("\n"):
                    if line.startswith("yes:"):
                        fields = line.split(":")
                        if len(fields) >= 3:
                            info["wifi_ssid"] = fields[1]
                            info["wifi_signal"] = f"{fields[2]}%"
                            break
        except Exception:
            pass

        if info["wifi_ssid"] in ("N/A (Wired/Unknown)", "N/A"):
            try:
                res = subprocess.run(["iwconfig", iface], capture_output=True, text=True, timeout=3)
                if res.returncode == 0 and res.stdout:
                    ssid_m = re.search(r'ESSID:"([^"]+)"', res.stdout)
                    sig_m = re.search(r'Signal level=(-\d+\s*dBm|\d+/\d+)', res.stdout)
                    if ssid_m: info["wifi_ssid"] = ssid_m.group(1)
                    if sig_m: info["wifi_signal"] = sig_m.group(1)
            except Exception:
                pass

    return info


def get_lan_ip(debug: bool = False) -> str:
    """Gets primary local LAN IP address."""
    try:
        with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as s:
            s.settimeout(2)
            s.connect(("1.1.1.1", 80))
            return s.getsockname()[0]
    except Exception as e:
        if debug:
            print(f"{C.YELLOW}[DEBUG] Failed to get LAN IP: {e}{C.RESET}")
        return "Unavailable"


def get_geo_info(debug: bool = False) -> Dict[str, str]:
    """Gets public IP, ISP, and Location information."""
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
    except Exception as e:
        if debug:
            print(f"{C.YELLOW}[DEBUG] Failed to get geolocation: {e}{C.RESET}")
    return {"ip": "Unavailable", "isp": "Unknown", "city": "Unknown", "country": "Unknown"}


def get_speedtest(debug: bool = False, retries: int = MAX_RETRIES) -> Optional[Dict[str, Optional[float]]]:
    """Runs speedtest-cli and extracts ping, download, and upload speeds."""
    for attempt in range(retries + 1):
        try:
            res = subprocess.run(
                ["speedtest-cli", "--simple", "--secure"], capture_output=True, text=True, timeout=60
            )
            ping_m = re.search(r"Ping:\s*([0-9.]+)", res.stdout)
            dl_m = re.search(r"Download:\s*([0-9.]+)", res.stdout)
            ul_m = re.search(r"Upload:\s*([0-9.]+)", res.stdout)

            if dl_m:
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
    """Fetches Fast.com download speed directly via multi-stream parallel downloads."""
    for attempt in range(retries + 1):
        try:
            html = make_http_request("https://fast.com", timeout=HTTP_TIMEOUT, debug=debug)
            if not html: raise ValueError("Failed to fetch fast.com homepage")
            
            js_path = JS_PATH_PATTERN.search(html)
            if not js_path: raise ValueError("JavaScript file not found")

            js_url = f"https://fast.com{js_path.group(1)}"
            js_content = make_http_request(js_url, timeout=HTTP_TIMEOUT, debug=debug)
            if not js_content: raise ValueError("Failed to fetch JavaScript")
            
            token = TOKEN_PATTERN.search(js_content)
            if not token: raise ValueError("Token not found in JavaScript")

            api_url = f"https://api.fast.com/netflix/speedtest/v2?https=true&token={token.group(1)}&urlCount=3"
            api_res = make_http_request(api_url, timeout=HTTP_TIMEOUT, debug=debug)
            if not api_res: raise ValueError("Failed to fetch API targets")
            
            data = json.loads(api_res)
            if not isinstance(data, dict): raise ValueError("Invalid API response format")

            targets = [item.get("url") for item in data.get("targets", []) if isinstance(item, dict) and "url" in item]
            if not targets: raise ValueError("No valid targets found")

            def download_stream(target_url):
                t0 = time.time()
                res = subprocess.run(
                    ["curl", "-s", "-L", "-A", USER_AGENT, "-r", "0-25000000", "-w", "%{size_download}", "-o", "/dev/null", target_url],
                    capture_output=True, text=True, timeout=DOWNLOAD_TIMEOUT
                )
                t1 = time.time()
                try:
                    return int(res.stdout.strip() or 0), t1 - t0
                except:
                    return 0, 0

            start_time = time.time()
            with ThreadPoolExecutor(max_workers=len(targets)) as ex:
                futs = [ex.submit(download_stream, url) for url in targets]
                results = [f.result() for f in futs]
            elapsed = time.time() - start_time
            
            total_bytes = sum(r[0] for r in results)
            if elapsed > 0 and total_bytes > 0:
                mbps = (total_bytes * 8) / (elapsed * 1000000)
                return {"download": round(mbps, 2)}
        except Exception as e:
            if debug:
                print(f"{C.YELLOW}[DEBUG] Fast.com attempt {attempt + 1}/{retries + 1} failed: {e}{C.RESET}")
            if attempt < retries:
                exponential_backoff_delay(attempt)
    return None


def get_cloudflare(debug: bool = False, retries: int = MAX_RETRIES) -> Optional[Dict[str, float]]:
    """Runs Cloudflare CDN speed test (multi-stream download & upload)."""
    for attempt in range(retries + 1):
        try:
            down_url = "https://speed.cloudflare.com/__down?bytes=25000000"
            def dl_worker(url):
                t0 = time.time()
                res = subprocess.run(
                    ["curl", "-s", "-L", "-A", USER_AGENT, "-w", "%{size_download}", "-o", "/dev/null", url],
                    capture_output=True, text=True, timeout=DOWNLOAD_TIMEOUT
                )
                t1 = time.time()
                try:
                    return int(res.stdout.strip() or 0), t1 - t0
                except:
                    return 0, 0

            t_start_dl = time.time()
            with ThreadPoolExecutor(max_workers=DEFAULT_WORKERS) as ex:
                futs = [ex.submit(dl_worker, down_url) for _ in range(DEFAULT_WORKERS)]
                dl_results = [f.result() for f in futs]
            t_dl = time.time() - t_start_dl
            total_dl_bytes = sum(r[0] for r in dl_results)
            dl_mbps = round((total_dl_bytes * 8) / (t_dl * 1000000), 2) if t_dl > 0 else 0.0

            up_url = "https://speed.cloudflare.com/__up"
            tmp = tempfile.NamedTemporaryFile(delete=False)
            tmp.write(os.urandom(1 * 1024 * 1024))
            tmp.close()

            def ul_worker(url, filepath):
                t0 = time.time()
                res = subprocess.run(
                    ["curl", "-s", "-L", "-A", USER_AGENT, "-X", "POST", "--data-binary", f"@{filepath}", "-w", "%{size_upload}", "-o", "/dev/null", url],
                    capture_output=True, text=True, timeout=DOWNLOAD_TIMEOUT
                )
                t1 = time.time()
                try:
                    return int(res.stdout.strip() or 0), t1 - t0
                except:
                    return 0, 0

            t_start_ul = time.time()
            with ThreadPoolExecutor(max_workers=2) as ex:
                futs_ul = [ex.submit(ul_worker, up_url, tmp.name) for _ in range(2)]
                ul_results = [f.result() for f in futs_ul]
            t_ul = time.time() - t_start_ul
            os.unlink(tmp.name)

            total_ul_bytes = sum(r[0] for r in ul_results)
            ul_mbps = round((total_ul_bytes * 8) / (t_ul * 1000000), 2) if t_ul > 0 else 0.0

            if dl_mbps > 0:
                return {"download": dl_mbps, "upload": ul_mbps}
        except Exception as e:
            if debug:
                print(f"{C.YELLOW}[DEBUG] Cloudflare attempt {attempt + 1}/{retries + 1} failed: {e}{C.RESET}")
            if attempt < retries:
                exponential_backoff_delay(attempt)
    return None


def ping_monitor(stop_event: threading.Event, ping_samples: List[float]):
    """Continuously measure ping latency during active transfers for bufferbloat analysis."""
    resolver = {"name": "Cloudflare", "ip": "1.1.1.1", "port": 53}
    while not stop_event.is_set():
        latency = get_dns_latency(resolver, "google.com", timeout=2, debug=False)
        if latency:
            ping_samples.append(latency)
        time.sleep(0.2)


def calculate_bufferbloat_grade(unloaded_ping: float, loaded_ping: float) -> Tuple[str, float]:
    """Calculate bufferbloat increase delta and assign letter grade (A+ to F)."""
    delta = round(max(0.0, loaded_ping - unloaded_ping), 2)
    if delta <= 5.0: grade = "A+"
    elif delta <= 15.0: grade = "A"
    elif delta <= 30.0: grade = "B"
    elif delta <= 60.0: grade = "C"
    elif delta <= 100.0: grade = "D"
    else: grade = "F"
    return grade, delta


def calculate_jitter(latency_list: List[float]) -> float:
    """Calculates network jitter."""
    if len(latency_list) < 2: return 0.0
    diffs = [abs(latency_list[i] - latency_list[i - 1]) for i in range(1, len(latency_list))]
    return round(sum(diffs) / len(diffs), 2)


def calculate_statistics(values: List[float]) -> Dict[str, float]:
    """Calculate min, max, avg, and median statistics for a list of values."""
    if not values:
        return {"min": 0.0, "max": 0.0, "avg": 0.0, "median": 0.0}
    sorted_vals = sorted(values)
    avg = round(sum(values) / len(values), 2)
    median = sorted_vals[len(sorted_vals) // 2] if len(sorted_vals) % 2 else (sorted_vals[len(sorted_vals) // 2 - 1] + sorted_vals[len(sorted_vals) // 2]) / 2
    return {"min": round(min(values), 2), "max": round(max(values), 2), "avg": avg, "median": round(median, 2)}


def validate_file_path(filepath: str, mode: str = 'w', debug: bool = False) -> bool:
    """Validates that a file path is writable and directory exists."""
    try:
        dirpath = os.path.dirname(filepath)
        if dirpath and not os.path.exists(dirpath):
            os.makedirs(dirpath, exist_ok=True)
        if mode == 'w':
            with open(filepath, 'a'): pass
        return True
    except Exception as e:
        if debug: print(f"{C.YELLOW}[DEBUG] File path validation failed: {e}{C.RESET}")
        return False


def save_history_record(record_data: Dict[str, Any], debug: bool = False) -> None:
    """Append a benchmark run record to ~/.speedtest_history.json."""
    try:
        history = []
        if os.path.exists(HISTORY_FILE):
            try:
                with open(HISTORY_FILE, "r") as f: history = json.load(f)
            except Exception: history = []
        history.append(record_data)
        with open(HISTORY_FILE, "w") as f: json.dump(history, f, indent=2)
    except Exception as e:
        if debug: print(f"{C.YELLOW}[DEBUG] Failed to save history: {e}{C.RESET}")


def export_html_report(filepath: str, export_data: Dict[str, Any], debug: bool = False) -> bool:
    """Generates an interactive, standalone HTML report dashboard."""
    try:
        ts = export_data.get("timestamp", "").replace("T", " ")[:19]
        ver = export_data.get("version", VERSION)
        net = export_data.get("network", {})
        geo = net.get("geo", {})
        adapter = net.get("adapter", {})
        stats = export_data.get("statistics", {})
        suitability = export_data.get("suitability", {})
        dns_rec = export_data.get("dns_recommendation", {})

        st_dl = stats.get("speedtest_download_mbps", {}).get("avg", 0.0)
        fast_dl = stats.get("fast_download_mbps", {}).get("avg", 0.0)
        cf_dl = stats.get("cloudflare_download_mbps", {}).get("avg", 0.0)

        st_ul = stats.get("speedtest_upload_mbps", {}).get("avg", 0.0)
        cf_ul = stats.get("cloudflare_upload_mbps", {}).get("avg", 0.0)

        ping = stats.get("ping_ms", {}).get("avg", 0.0)
        jitter = stats.get("jitter_ms", 0.0)
        bb = stats.get("bufferbloat", {})

        max_dl = max(1.0, st_dl, fast_dl, cf_dl)

        html_content = f"""<!DOCTYPE html>
<html lang="en">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>Speedtest Benchmark Report - {ts}</title>
    <style>
        :root {{
            --bg-color: #0f172a;
            --card-bg: #1e293b;
            --text-main: #f8fafc;
            --text-dim: #94a3b8;
            --accent-cyan: #06b6d4;
            --accent-green: #10b981;
            --accent-yellow: #f59e0b;
            --accent-purple: #8b5cf6;
            --border: #334155;
        }}
        body {{
            font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, Helvetica, Arial, sans-serif;
            background-color: var(--bg-color);
            color: var(--text-main);
            margin: 0;
            padding: 24px;
        }}
        .container {{
            max-width: 1000px;
            margin: 0 auto;
        }}
        .header {{
            display: flex;
            justify-content: space-between;
            align-items: center;
            border-bottom: 2px solid var(--border);
            padding-bottom: 16px;
            margin-bottom: 24px;
        }}
        .title {{
            font-size: 24px;
            font-weight: bold;
            color: var(--accent-cyan);
        }}
        .meta {{
            font-size: 14px;
            color: var(--text-dim);
        }}
        .grid {{
            display: grid;
            grid-template-columns: repeat(auto-fit, minmax(300px, 1fr));
            gap: 20px;
            margin-bottom: 24px;
        }}
        .card {{
            background: var(--card-bg);
            border: 1px solid var(--border);
            border-radius: 12px;
            padding: 20px;
        }}
        .card-title {{
            font-size: 14px;
            text-transform: uppercase;
            letter-spacing: 1px;
            color: var(--text-dim);
            margin-bottom: 12px;
        }}
        .metric-main {{
            font-size: 36px;
            font-weight: bold;
            color: var(--accent-green);
        }}
        .bar-container {{
            margin-top: 12px;
        }}
        .bar-label {{
            display: flex;
            justify-content: space-between;
            font-size: 13px;
            margin-bottom: 4px;
        }}
        .bar-bg {{
            background: #334155;
            height: 12px;
            border-radius: 6px;
            overflow: hidden;
            margin-bottom: 12px;
        }}
        .bar-fill {{
            height: 100%;
            border-radius: 6px;
            transition: width 0.5s ease;
        }}
        .badge {{
            display: inline-block;
            padding: 4px 10px;
            border-radius: 20px;
            font-size: 12px;
            font-weight: bold;
            background: rgba(6, 182, 212, 0.2);
            color: var(--accent-cyan);
        }}
        .recommendation {{
            background: rgba(139, 92, 246, 0.15);
            border: 1px solid var(--accent-purple);
            border-radius: 8px;
            padding: 16px;
            margin-top: 16px;
        }}
    </style>
</head>
<body>
    <div class="container">
        <div class="header">
            <div>
                <div class="title">Network Speed Benchmark Report</div>
                <div class="meta">Generated: {ts} | Tool Version: v{ver}</div>
            </div>
            <div class="badge">Quality Score: {suitability.get("overall_score", "N/A")}/100</div>
        </div>

        <div class="grid">
            <div class="card">
                <div class="card-title">Network Info</div>
                <p><strong>ISP:</strong> {geo.get("isp", "Unknown")} ({geo.get("ip", "N/A")})</p>
                <p><strong>Location:</strong> {geo.get("city", "Unknown")}, {geo.get("country", "Unknown")}</p>
                <p><strong>Interface:</strong> {adapter.get("interface", "Unknown")} ({adapter.get("gateway", "N/A")})</p>
                <p><strong>Wi-Fi SSID:</strong> {adapter.get("wifi_ssid", "N/A")} ({adapter.get("wifi_signal", "N/A")})</p>
            </div>

            <div class="card">
                <div class="card-title">Latency & Quality</div>
                <p><strong>Average Ping:</strong> <span style="color:var(--accent-yellow)">{ping} ms</span></p>
                <p><strong>Jitter:</strong> {jitter} ms</p>
                <p><strong>Bufferbloat Rating:</strong> <span class="badge">{bb.get("grade", "N/A")} (+{bb.get("delta_ms", 0)} ms)</span></p>
            </div>

            <div class="card">
                <div class="card-title">Real-World Readiness</div>
                <p>🎮 <strong>Gaming:</strong> {suitability.get("gaming", {}).get("status", "N/A")}</p>
                <p>🎥 <strong>4K Streaming:</strong> {suitability.get("streaming", {}).get("status", "N/A")}</p>
                <p>📹 <strong>Video Calls:</strong> {suitability.get("video_call", {}).get("status", "N/A")}</p>
            </div>
        </div>

        <div class="card">
            <div class="card-title">Download Speed Comparison (Mbps)</div>
            <div class="bar-container">
                <div class="bar-label"><span>Ookla (Speedtest.net)</span><span>{st_dl} Mbps</span></div>
                <div class="bar-bg"><div class="bar-fill" style="width:{(st_dl/max_dl)*100}%; background:var(--accent-green)"></div></div>

                <div class="bar-label"><span>Fast.com (Netflix CDN)</span><span>{fast_dl} Mbps</span></div>
                <div class="bar-bg"><div class="bar-fill" style="width:{(fast_dl/max_dl)*100}%; background:var(--accent-cyan)"></div></div>

                <div class="bar-label"><span>Cloudflare CDN</span><span>{cf_dl} Mbps</span></div>
                <div class="bar-bg"><div class="bar-fill" style="width:{(cf_dl/max_dl)*100}%; background:var(--accent-purple)"></div></div>
            </div>
        </div>

        {f'''
        <div class="recommendation">
            💡 <strong>DNS Recommendation:</strong> Switch to <strong>{dns_rec.get("name")} ({dns_rec.get("ip")})</strong> for 
            <strong>{dns_rec.get("savings_pct")}% faster DNS resolution</strong> compared to {dns_rec.get("slowest_name")}.
        </div>
        ''' if dns_rec else ''}
    </div>
</body>
</html>
"""
        with open(filepath, "w") as f:
            f.write(html_content)
        return True
    except Exception as e:
        if debug: print(f"{C.YELLOW}[DEBUG] Failed to export HTML report: {e}{C.RESET}")
        return False


def display_history(clear: bool = False, no_color: bool = False) -> int:
    """Displays formatted historical benchmark trends or clears history log."""
    if no_color: C.disable()
    if clear:
        if os.path.exists(HISTORY_FILE):
            os.remove(HISTORY_FILE)
            print(f"{C.GREEN}[✔] Speedtest benchmark history cleared.{C.RESET}")
        else:
            print(f"{C.YELLOW}[i] No history file found to clear.{C.RESET}")
        return 0

    if not os.path.exists(HISTORY_FILE):
        print(f"{C.YELLOW}[i] No benchmark history found. Run a speed test first!{C.RESET}")
        return 0

    try:
        with open(HISTORY_FILE, "r") as f: history = json.load(f)
    except Exception as e:
        print(f"{C.RED}[!] Failed to read history file: {e}{C.RESET}")
        return 1

    if not history:
        print(f"{C.YELLOW}[i] Benchmark history is empty.{C.RESET}")
        return 0

    print(f"\n{C.MAGENTA}{C.BOLD}==================================================================================={C.RESET}")
    print(f"{C.MAGENTA}{C.BOLD}                           HISTORICAL BENCHMARK LOGS                                {C.RESET}")
    print(f"{C.MAGENTA}{C.BOLD}==================================================================================={C.RESET}")
    print(f"{C.BOLD}  Date/Time            ISP / Wi-Fi       Ookla DL   Fast DL   CF DL     Ping     Bufferbloat{C.RESET}")
    print(f"{C.DIM}  -----------------------------------------------------------------------------------{C.RESET}")

    ookla_dls, fast_dls, cf_dls, pings = [], [], [], []

    for entry in history[-15:]:
        dt = entry.get("timestamp", "").replace("T", " ")[:16]
        net = entry.get("network", {})
        isp = net.get("geo", {}).get("isp", net.get("isp", "Unknown"))
        iface = net.get("adapter", {}).get("interface", "")
        if_info = f"{isp} ({iface})" if iface else isp

        stats = entry.get("statistics", {})
        st_dl = stats.get("speedtest_download_mbps", {}).get("avg", 0.0)
        fast_dl = stats.get("fast_download_mbps", {}).get("avg", 0.0)
        cf_dl = stats.get("cloudflare_download_mbps", {}).get("avg", 0.0)
        ping = stats.get("ping_ms", {}).get("avg", 0.0)
        bb = stats.get("bufferbloat", {})
        bb_str = f"{bb.get('grade', 'N/A')} (+{bb.get('delta_ms', 0)}ms)" if bb else "N/A"

        if st_dl: ookla_dls.append(st_dl)
        if fast_dl: fast_dls.append(fast_dl)
        if cf_dl: cf_dls.append(cf_dl)
        if ping: pings.append(ping)

        st_str = f"{st_dl:.1f} M" if st_dl else "N/A"
        fast_str = f"{fast_dl:.1f} M" if fast_dl else "N/A"
        cf_str = f"{cf_dl:.1f} M" if cf_dl else "N/A"
        ping_str = f"{ping:.1f} ms" if ping else "N/A"

        print(f"  {dt:<19} {if_info:<16} {st_str:<10} {fast_str:<9} {cf_str:<9} {ping_str:<8} {bb_str}")

    print(f"{C.MAGENTA}{C.BOLD}==================================================================================={C.RESET}")
    print(f"{C.BOLD} Overall Averages ({len(history)} runs):{C.RESET}")
    st_avg = round(sum(ookla_dls)/len(ookla_dls), 2) if ookla_dls else 0.0
    fast_avg = round(sum(fast_dls)/len(fast_dls), 2) if fast_dls else 0.0
    cf_avg = round(sum(cf_dls)/len(cf_dls), 2) if cf_dls else 0.0
    ping_avg = round(sum(pings)/len(pings), 2) if pings else 0.0
    print(f"  Ookla DL: {C.GREEN}{st_avg} Mbps{C.RESET} | Fast DL: {C.GREEN}{fast_avg} Mbps{C.RESET} | Cloudflare DL: {C.GREEN}{cf_avg} Mbps{C.RESET} | Ping: {C.YELLOW}{ping_avg} ms{C.RESET}")
    print(f"{C.MAGENTA}{C.BOLD}==================================================================================={C.RESET}\n")
    return 0


def run_single_benchmark(engine: str, run_num: int, st_ok: bool, fast_ok: bool, cf_ok: bool, quiet: bool, debug: bool, loaded_pings: Optional[List[float]] = None) -> Optional[Dict[str, Any]]:
    """Run a single benchmark iteration for specified engine with optional loaded ping monitoring."""
    stop_ping = threading.Event()
    ping_thread = None

    if loaded_pings is not None:
        ping_thread = threading.Thread(target=ping_monitor, args=(stop_ping, loaded_pings), daemon=True)
        ping_thread.start()

    res = None
    sp = Spinner(f"Run {run_num} ({engine.title()})", quiet=quiet)
    sp.start()

    try:
        if engine == "speedtest" and st_ok:
            res = get_speedtest(debug, MAX_RETRIES)
            if res and res.get("download"):
                sp.stop(f"Run {run_num}... {C.GREEN}DL: {res['download']} Mbps{C.RESET} | {C.YELLOW}UL: {res['upload']} Mbps{C.RESET} {C.DIM}(Ping: {res['ping']}ms){C.RESET}")
            else: sp.stop(f"Run {run_num}... {C.RED}Failed (Skipped){C.RESET}")
        elif engine == "fast" and fast_ok:
            res = get_fastcom(debug, MAX_RETRIES)
            if res and res.get("download"):
                sp.stop(f"Run {run_num}... {C.GREEN}DL: {res['download']} Mbps{C.RESET}")
            else: sp.stop(f"Run {run_num}... {C.RED}Failed (Skipped){C.RESET}")
        elif engine == "cloudflare" and cf_ok:
            res = get_cloudflare(debug, MAX_RETRIES)
            if res and res.get("download"):
                sp.stop(f"Run {run_num}... {C.GREEN}DL: {res['download']} Mbps{C.RESET} | {C.YELLOW}UL: {res['upload']} Mbps{C.RESET}")
            else: sp.stop(f"Run {run_num}... {C.RED}Failed (Skipped){C.RESET}")
    finally:
        if ping_thread:
            stop_ping.set()
            ping_thread.join(timeout=0.5)

    return res


def run_benchmark_cycle(args) -> int:
    """Run one complete benchmark cycle."""
    st_ok, fast_ok, cf_ok = check_endpoints(args.quiet, args.debug)

    if not args.quiet: print(f"{C.BLUE}[i] Detecting Network Interfaces & Adapter Info...{C.RESET}")
    lan_ip = get_lan_ip(args.debug)
    geo = get_geo_info(args.debug)
    adapter = get_network_adapter_info(args.debug)
    
    if not args.quiet:
        print(f"    {C.BOLD}Local IP (LAN):{C.RESET} {C.YELLOW}{lan_ip}{C.RESET}")
        print(f"    {C.BOLD}Public IP (WAN):{C.RESET}{C.YELLOW}{geo['ip']}{C.RESET} ({geo['isp']} - {geo['city']}, {geo['country']})")
        print(f"    {C.BOLD}Interface:{C.RESET}      {C.YELLOW}{adapter['interface']}{C.RESET} (Gateway: {adapter['gateway']})")
        print(f"    {C.BOLD}Wi-Fi SSID:{C.RESET}     {C.YELLOW}{adapter['wifi_ssid']}{C.RESET} (Signal: {adapter['wifi_signal']})\n")

    st_results: List[Dict[str, Any]] = []
    fast_results: List[Dict[str, Any]] = []
    cf_results: List[Dict[str, Any]] = []
    dns_results: Optional[Dict[str, Any]] = None
    loaded_ping_samples: List[float] = []

    # DNS Test
    dns_future = None
    dns_executor = None
    if args.dns:
        if not args.quiet: print(f"{C.BLUE}[i] Starting Background DNS Resolution Test...{C.RESET}\n")
        dns_executor = ThreadPoolExecutor(max_workers=1)
        dns_future = dns_executor.submit(run_dns_test, args.runs, True, args.debug, adapter.get("gateway"))

    # Ookla
    if st_ok:
        if not args.quiet: print(f"{C.CYAN}{C.BOLD}--- Running Speedtest.net (Ookla) Benchmark ---{C.RESET}")
        for i in range(1, args.runs + 1):
            res = run_single_benchmark("speedtest", i, st_ok, fast_ok, cf_ok, args.quiet, args.debug, loaded_ping_samples)
            if res: st_results.append(res)
            time.sleep(0.5)

    # Fast.com
    if fast_ok:
        if not args.quiet: print(f"\n{C.CYAN}{C.BOLD}--- Running Fast.com (Netflix CDN) Benchmark ---{C.RESET}")
        for i in range(1, args.runs + 1):
            res = run_single_benchmark("fast", i, st_ok, fast_ok, cf_ok, args.quiet, args.debug, loaded_ping_samples)
            if res: fast_results.append(res)
            time.sleep(0.5)

    # Cloudflare
    if cf_ok:
        if not args.quiet: print(f"\n{C.CYAN}{C.BOLD}--- Running Cloudflare CDN Benchmark ---{C.RESET}")
        for i in range(1, args.runs + 1):
            res = run_single_benchmark("cloudflare", i, st_ok, fast_ok, cf_ok, args.quiet, args.debug, loaded_ping_samples)
            if res: cf_results.append(res)
            time.sleep(0.5)

    if dns_future:
        try: dns_results = dns_future.result(timeout=15)
        except Exception: dns_results = None
        if dns_executor: dns_executor.shutdown(wait=False)

    st_dls = [r["download"] for r in st_results if r.get("download")]
    st_uls = [r["upload"] for r in st_results if r.get("upload")]
    st_pings = [r["ping"] for r in st_results if r.get("ping")]
    fast_dls = [r["download"] for r in fast_results if r.get("download")]
    cf_dls = [r["download"] for r in cf_results if r.get("download")]
    cf_uls = [r["upload"] for r in cf_results if r.get("upload")]

    st_dl_stats = calculate_statistics(st_dls)
    st_ul_stats = calculate_statistics(st_uls)
    fast_dl_stats = calculate_statistics(fast_dls)
    cf_dl_stats = calculate_statistics(cf_dls)
    cf_ul_stats = calculate_statistics(cf_uls)
    ping_stats = calculate_statistics(st_pings)
    jitter = calculate_jitter(st_pings) if st_pings else 0.0

    unloaded_ping_avg = ping_stats["avg"] if ping_stats["avg"] > 0 else 30.0
    loaded_ping_stats = calculate_statistics(loaded_ping_samples)
    bb_grade, bb_delta = calculate_bufferbloat_grade(unloaded_ping_avg, loaded_ping_stats["avg"])

    bufferbloat_info = {
        "grade": bb_grade,
        "unloaded_ping_ms": unloaded_ping_avg,
        "loaded_ping_ms": loaded_ping_stats["avg"],
        "delta_ms": bb_delta
    }

    # Highest measured download/upload across engines
    max_dl = max(st_dl_stats["avg"], fast_dl_stats["avg"], cf_dl_stats["avg"])
    max_ul = max(st_ul_stats["avg"], cf_ul_stats["avg"])

    suitability = calculate_network_suitability(max_dl, max_ul, ping_stats["avg"], jitter, bb_grade)
    dns_rec = get_fastest_dns_recommendation(dns_results)

    # Summary
    print(f"\n{C.MAGENTA}{C.BOLD}===================================================={C.RESET}")
    print(f"{C.MAGENTA}{C.BOLD}                  BENCHMARK SUMMARY                 {C.RESET}")
    print(f"{C.MAGENTA}{C.BOLD}===================================================={C.RESET}")
    print(f" {C.BOLD}Author:{C.RESET}         Shadowharvy")
    print(f" {C.BOLD}Local IP:{C.RESET}       {lan_ip} ({adapter['interface']})")
    print(f" {C.BOLD}Public IP:{C.RESET}      {geo['ip']} ({geo['isp']})")
    print(f" {C.BOLD}Wi-Fi / AP:{C.RESET}     {adapter['wifi_ssid']} ({adapter['wifi_signal']})")
    print(f" {C.BOLD}Location:{C.RESET}       {geo['city']}, {geo['country']}")
    print(f" {C.DIM}----------------------------------------------------{C.RESET}")
    
    if st_ok: print(f" {C.BOLD}Ookla Download:{C.RESET} {C.GREEN}{st_dl_stats['avg']} Mbps{C.RESET} {C.DIM}(min: {st_dl_stats['min']}, max: {st_dl_stats['max']}){C.RESET}")
    if fast_ok: print(f" {C.BOLD}Fast Download:{C.RESET}  {C.GREEN}{fast_dl_stats['avg']} Mbps{C.RESET} {C.DIM}(min: {fast_dl_stats['min']}, max: {fast_dl_stats['max']}){C.RESET}")
    if cf_ok: print(f" {C.BOLD}Cloudflare DL:{C.RESET}  {C.GREEN}{cf_dl_stats['avg']} Mbps{C.RESET} {C.DIM}(min: {cf_dl_stats['min']}, max: {cf_dl_stats['max']}){C.RESET}")

    print(f" {C.BOLD}Average Ping:{C.RESET}   {C.YELLOW}{ping_stats['avg']} ms{C.RESET} | {C.BOLD}Jitter:{C.RESET} {C.YELLOW}{jitter} ms{C.RESET}")
    print(f" {C.BOLD}Bufferbloat:{C.RESET}    {C.CYAN}{bb_grade}{C.RESET} {C.DIM}(+{bb_delta} ms loaded spike){C.RESET}")
    print(f" {C.BOLD}Quality Score:{C.RESET}  {C.GREEN}{C.BOLD}{suitability['overall_score']}/100{C.RESET}")
    print(f"   ├─ 🎮 Gaming:     {C.CYAN}{suitability['gaming']['status']}{C.RESET}")
    print(f"   ├─ 🎥 Streaming:  {C.CYAN}{suitability['streaming']['status']}{C.RESET}")
    print(f"   └─ 📹 Video Call: {C.CYAN}{suitability['video_call']['status']}{C.RESET}")
    
    if dns_results:
        print(f" {C.BOLD}DNS Latency:{C.RESET}   {C.YELLOW}{dns_results['overall_latency_ms']['avg']} ms{C.RESET}")
        for resolver_name, resolver_data in dns_results['dns_resolvers'].items():
            latency = resolver_data['latency_ms']['avg']
            print(f"   └─ {resolver_name}: {C.YELLOW}{latency} ms{C.RESET}")
        if dns_rec:
            print(f" {C.MAGENTA}💡 DNS Tip: Switch to {dns_rec['name']} ({dns_rec['ip']}) for {dns_rec['savings_pct']}% faster resolution!{C.RESET}")
    
    print(f"{C.MAGENTA}{C.BOLD}===================================================={C.RESET}\n")

    record_data: Dict[str, Any] = {
        "timestamp": datetime.now().isoformat(),
        "version": VERSION,
        "network": {"lan_ip": lan_ip, "geo": geo, "adapter": adapter},
        "statistics": {
            "speedtest_download_mbps": st_dl_stats,
            "speedtest_upload_mbps": st_ul_stats,
            "fast_download_mbps": fast_dl_stats,
            "cloudflare_download_mbps": cf_dl_stats,
            "cloudflare_upload_mbps": cf_ul_stats,
            "ping_ms": ping_stats,
            "jitter_ms": jitter,
            "bufferbloat": bufferbloat_info
        },
        "suitability": suitability,
        "dns_recommendation": dns_rec,
        "dns": dns_results
    }
    save_history_record(record_data, args.debug)

    export_data: Dict[str, Any] = {
        **record_data,
        "raw_results": {"speedtest": st_results, "fast": fast_results, "cloudflare": cf_results}
    }

    exit_code = 0
    if args.json:
        try:
            with open(args.json, "w") as f: json.dump(export_data, f, indent=4)
            if not args.quiet: print(f"{C.GREEN}[✔] JSON data exported to {args.json}{C.RESET}")
        except Exception as e:
            print(f"{C.RED}[!] Failed to write JSON: {e}{C.RESET}")
            exit_code = 1

    if args.csv:
        try:
            with open(args.csv, "w", newline="") as f:
                writer = csv.writer(f)
                writer.writerow(["Engine", "Run", "Download (Mbps)", "Upload (Mbps)", "Ping (ms)"])
                for idx, r in enumerate(st_results): writer.writerow(["Speedtest", idx + 1, r.get("download", ""), r.get("upload", ""), r.get("ping", "")])
                for idx, r in enumerate(fast_results): writer.writerow(["Fast.com", idx + 1, r.get("download", ""), "", ""])
                for idx, r in enumerate(cf_results): writer.writerow(["Cloudflare", idx + 1, r.get("download", ""), r.get("upload", ""), ""])
            if not args.quiet: print(f"{C.GREEN}[✔] CSV data exported to {args.csv}{C.RESET}")
        except Exception as e:
            print(f"{C.RED}[!] Failed to write CSV: {e}{C.RESET}")
            exit_code = 1

    if args.html:
        if export_html_report(args.html, export_data, args.debug):
            if not args.quiet: print(f"{C.GREEN}[✔] Interactive HTML Report exported to {args.html}{C.RESET}")
        else:
            print(f"{C.RED}[!] Failed to write HTML report: {args.html}{C.RESET}")
            exit_code = 1
    
    if not st_ok and not fast_ok and not cf_ok:
        return 2
    
    return exit_code


def run_benchmark() -> int:
    """Main entry point supporting single run or continuous monitoring mode."""
    parser = argparse.ArgumentParser(
        description="Network Speed Benchmark Tool by Shadowharvy",
        epilog="Example: python3 speedtest.sh --runs 3 --dns --html report.html"
    )
    parser.add_argument("-n", "--runs", type=int, default=3, help="Number of benchmark iterations (default: 3)")
    parser.add_argument("--dns", action="store_true", help="Run background DNS resolution test")
    parser.add_argument("--history", action="store_true", help="Display benchmark performance history")
    parser.add_argument("--history-clear", action="store_true", help="Clear historical benchmark log file")
    parser.add_argument("--html", type=str, metavar="FILE", help="Export interactive HTML report dashboard")
    parser.add_argument("--json", type=str, metavar="FILE", help="Export results to a JSON file")
    parser.add_argument("--csv", type=str, metavar="FILE", help="Export results to a CSV file")
    parser.add_argument("--monitor", type=int, metavar="MINS", help="Continuous monitoring mode interval in minutes")
    parser.add_argument("--quiet", action="store_true", help="Suppress progress output, show only summary")
    parser.add_argument("--no-color", action="store_true", help="Disable ANSI color output")
    parser.add_argument("--debug", action="store_true", help="Enable debug output for troubleshooting")
    parser.add_argument("--version", action="version", version=f"%(prog)s {VERSION}", help="Show version and exit")
    args = parser.parse_args()

    if args.no_color: C.disable()

    if args.history or args.history_clear:
        return display_history(clear=args.history_clear, no_color=args.no_color)

    if args.runs < 1 or args.runs > 20:
        print(f"{C.RED}[!] Error: --runs must be between 1 and 20{C.RESET}")
        return 1

    print_banner(args.quiet)

    if args.monitor:
        print(f"{C.CYAN}{C.BOLD}[i] Continuous Monitoring Mode Active (Interval: {args.monitor} mins). Press Ctrl+C to stop.{C.RESET}\n")
        cycle = 1
        while True:
            print(f"{C.MAGENTA}{C.BOLD}--- Monitoring Cycle #{cycle} [{datetime.now().strftime('%H:%M:%S')}] ---{C.RESET}")
            run_benchmark_cycle(args)
            cycle += 1
            time.sleep(args.monitor * 60)

    return run_benchmark_cycle(args)


if __name__ == "__main__":
    try:
        sys.exit(run_benchmark())
    except KeyboardInterrupt:
        print(f"\n{C.YELLOW}[!] Benchmark interrupted by user{C.RESET}")
        sys.exit(130)
    except Exception as e:
        print(f"{C.RED}[!] Unexpected error: {e}{C.RESET}")
        sys.exit(1)