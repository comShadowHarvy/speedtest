"""Core constants, colors, and shared utilities."""

import argparse
import csv
import html
import json
import os
import re
import shutil
import socket
import subprocess
import sys
import tempfile
import threading
import time
import urllib.parse
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime
from typing import Any, Dict, List, Optional, Tuple, Union

# Popular sites for per-phase reachability timing (traceroute-style diagnostics).
# Each entry is probed for DNS / TCP / TLS / TTFB timings to answer
# "which part of reaching this site is slow for me?".
SITE_TIMING_TARGETS = [
    {"name": "YouTube", "host": "www.youtube.com"},
    {"name": "Google", "host": "www.google.com"},
    {"name": "Amazon", "host": "www.amazon.com"},
    {"name": "Netflix", "host": "www.netflix.com"},
    {"name": "Cloudflare", "host": "www.cloudflare.com"},
    {"name": "Microsoft", "host": "www.microsoft.com"},
    {"name": "Apple", "host": "www.apple.com"},
    {"name": "GitHub", "host": "github.com"},
]

SITE_TIMING_WORKERS = 8
SITE_TIMING_RUNS = 3
TRACEROUTE_DEFAULT_MAX_HOPS = 20
TRACEROUTE_MAX_HOPS = 64
TRACEROUTE_DEFAULT_HOSTS = ["www.google.com", "www.amazon.com"]

# --- Version & Constants ---
VERSION = "3.3.0"
MAX_RETRIES = 2
BASE_RETRY_DELAY = 1.0  # Initial retry delay in seconds
MAX_RETRY_DELAY = 6.0   # Maximum retry delay in seconds

# Timeout constants (in seconds)
HTTP_TIMEOUT = 5
DOWNLOAD_TIMEOUT = 18
CHECK_TIMEOUT = 4
DNS_TIMEOUT = 3
DEFAULT_WORKERS = 4

HISTORY_FILE = os.path.expanduser("~/.speedtest_history.json")
MAX_HISTORY_ENTRIES = 500

# Public DNS Resolver Configurations (IPv4)
DNS_RESOLVERS = [
    {"name": "Cloudflare", "ip": "1.1.1.1", "port": 53, "doh": "https://cloudflare-dns.com/dns-query"},
    {"name": "Google", "ip": "8.8.8.8", "port": 53, "doh": "https://dns.google/resolve"},
    {"name": "Quad9", "ip": "9.9.9.9", "port": 53, "doh": "https://dns.quad9.net/dns-query"},
    {"name": "OpenDNS", "ip": "208.67.222.222", "port": 53, "doh": "https://doh.opendns.com/dns-query"},
    {"name": "AdGuard", "ip": "94.140.14.14", "port": 53, "doh": "https://dns.adguard-dns.com/dns-query"},
]

# Public DNS Resolver Configurations (IPv6)
IPV6_DNS_RESOLVERS = [
    {"name": "Cloudflare IPv6", "ip": "2606:4700:4700::1111", "port": 53},
    {"name": "Google IPv6", "ip": "2001:4860:4860::8888", "port": 53},
    {"name": "Quad9 IPv6", "ip": "2620:fe::fe", "port": 53},
]

# Known DNS Provider Details & Configuration Addresses
DNS_PROVIDER_DETAILS = {
    "Cloudflare": {
        "primary": "1.1.1.1",
        "secondary": "1.0.0.1",
        "ipv6_primary": "2606:4700:4700::1111",
        "ipv6_secondary": "2606:4700:4700::1001",
        "features": "Fastest response time, strict privacy (no logging)",
    },
    "Google": {
        "primary": "8.8.8.8",
        "secondary": "8.8.4.4",
        "ipv6_primary": "2001:4860:4860::8888",
        "ipv6_secondary": "2001:4860:4860::8844",
        "features": "Global anycast stability, high reliability",
    },
    "Quad9": {
        "primary": "9.9.9.9",
        "secondary": "149.112.112.112",
        "ipv6_primary": "2620:fe::fe",
        "ipv6_secondary": "2620:fe::9",
        "features": "Automatic malware, phishing & ransomware blocking",
    },
    "OpenDNS": {
        "primary": "208.67.222.222",
        "secondary": "208.67.220.220",
        "ipv6_primary": "2620:119:35::35",
        "ipv6_secondary": "2620:119:53::53",
        "features": "Cisco security, web filtering, parental controls",
    },
    "AdGuard": {
        "primary": "94.140.14.14",
        "secondary": "94.140.15.15",
        "ipv6_primary": "2a10:50c0::ad1:ff",
        "ipv6_secondary": "2a10:50c0::ad2:ff",
        "features": "System-wide ad, tracker, and malware blocking",
    },
}

# Standard DNS lookup hostnames
DNS_QUERIES = ["google.com", "github.com", "cloudflare.com", "wikipedia.org"]

USER_AGENT = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36"

# Pre-compiled regex patterns (flexible quote & asset naming support)
JS_PATH_PATTERN = re.compile(r'src=["\'](/app-[a-zA-Z0-9._-]+\.js)["\']')
TOKEN_PATTERN = re.compile(r'token["\']?\s*:\s*["\']([A-Za-z0-9_-]+)["\']')
SPARKLINE_CHARS = [" ", "▂", "▃", "▄", "▅", "▆", "▇", "█"]

class C:
    """ANSI color codes for terminal output styling."""
    RESET = "\033[0m"
    BOLD = "\033[1m"
    DIM = "\033[2m"
    ITALIC = "\033[3m"
    UNDERLINE = "\033[4m"

    # Colors
    CYAN = "\033[96m"
    GREEN = "\033[92m"
    YELLOW = "\033[93m"
    RED = "\033[91m"
    BLUE = "\033[94m"
    MAGENTA = "\033[95m"
    WHITE = "\033[97m"

    @classmethod
    def disable(cls):
        """Disables all ANSI color codes."""
        cls.RESET = cls.BOLD = cls.DIM = cls.ITALIC = cls.UNDERLINE = ""
        cls.CYAN = cls.GREEN = cls.YELLOW = cls.RED = cls.BLUE = cls.MAGENTA = cls.WHITE = ""



class Spinner:
    """Live animated progress spinner with dynamic status and throughput updates."""
    def __init__(self, message: str, quiet: bool = False):
        self.message = message
        self.quiet = quiet
        self.stop_event = threading.Event()
        self.thread: Optional[threading.Thread] = None
        self.dynamic_status = ""

    def update_status(self, status: str):
        """Update live status message displayed alongside the spinner."""
        self.dynamic_status = status

    def _spin(self):
        chars = ["⠋", "⠙", "⠹", "⠸", "⠼", "⠴", "⠦", "⠧", "⠇", "⠏"]
        idx = 0
        while not self.stop_event.is_set():
            extra = f" {C.YELLOW}[{self.dynamic_status}]{C.RESET}" if self.dynamic_status else ""
            sys.stdout.write(f"\r  {C.CYAN}{chars[idx % len(chars)]}{C.RESET} {self.message}...{extra} ")
            sys.stdout.flush()
            idx += 1
            time.sleep(0.08)

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



def generate_sparkline(values: List[float]) -> str:
    """Generates an ASCII/Unicode sparkline representation of numeric data."""
    if not values:
        return ""
    min_val = min(values)
    max_val = max(values)
    val_range = max_val - min_val
    if val_range == 0:
        return SPARKLINE_CHARS[3] * len(values)

    spark = ""
    for v in values:
        idx = int(((v - min_val) / val_range) * (len(SPARKLINE_CHARS) - 1))
        spark += SPARKLINE_CHARS[max(0, min(len(SPARKLINE_CHARS) - 1, idx))]
    return spark



def make_http_request(
    url: str,
    user_agent: str = USER_AGENT,
    timeout: int = HTTP_TIMEOUT,
    headers: Optional[Dict[str, str]] = None,
    debug: bool = False,
    ip_version: Optional[str] = None
) -> Optional[str]:
    """Make an HTTP request using curl with error handling and IP family selection."""
    cmd = ["curl", "-s", "-L", "-A", user_agent, "--max-time", str(timeout)]
    if ip_version == "4":
        cmd.append("-4")
    elif ip_version == "6":
        cmd.append("-6")

    if headers:
        for k, v in headers.items():
            cmd.extend(["-H", f"{k}: {v}"])
    cmd.append(url)

    try:
        res = subprocess.run(cmd, capture_output=True, text=True, timeout=timeout + 2)
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
    """Calculate and apply exponential backoff delay."""
    delay = min(base_delay * (2 ** attempt), max_delay)
    time.sleep(delay)



def is_ipv6_available() -> bool:
    """Fast check whether IPv6 network connectivity and route is active."""
    try:
        s = socket.socket(socket.AF_INET6, socket.SOCK_DGRAM)
        s.settimeout(0.8)
        s.connect(("2606:4700:4700::1111", 53))
        s.close()
        return True
    except Exception:
        return False



def build_dns_query(hostname: str, query_type: str = "A", txid: Optional[bytes] = None) -> bytes:
    """Build a standard DNS query packet (Type A or AAAA).

    A random transaction ID is generated per query unless one is supplied, so
    replies can be matched to this specific query (RFC 1035 §4.1.1).
    """
    if txid is None:
        txid = os.urandom(2)
    header = txid + b"\x01\x00\x00\x01\x00\x00\x00\x00\x00\x00"
    qname = b"".join(bytes([len(part)]) + part.encode("ascii") for part in hostname.split(".")) + b"\x00"
    qtype = b"\x00\x1c" if query_type.upper() == "AAAA" else b"\x00\x01"  # Type AAAA (28) or A (1)
    qclass = b"\x00\x01"  # Class IN
    return header + qname + qtype + qclass



def is_valid_dns_response(data: bytes, txid: bytes) -> bool:
    """Check that a datagram is a successful DNS reply to the query with id `txid`.

    Rejects replies whose transaction ID does not match (stale/off-path packets),
    that are not responses (QR bit clear), or that carry a non-zero RCODE
    (SERVFAIL/REFUSED/NXDOMAIN must not be scored as resolver latency).
    """
    if len(data) < 12 or data[:2] != txid:
        return False
    flags = int.from_bytes(data[2:4], "big")
    if not (flags & 0x8000):  # QR: response bit
        return False
    return (flags & 0x000F) == 0  # RCODE == NOERROR



def get_dns_latency(resolver: Dict[str, Any], hostname: str, timeout: int = DNS_TIMEOUT, debug: bool = False) -> Optional[float]:
    """Query a DNS resolver via UDP socket and measure lookup time in ms."""
    try:
        ip = resolver["ip"]
        port = resolver.get("port", 53)
        is_ipv6 = ":" in ip
        query_type = "AAAA" if is_ipv6 else "A"
        query_packet = build_dns_query(hostname, query_type)
        txid = query_packet[:2]

        sock_family = socket.AF_INET6 if is_ipv6 else socket.AF_INET
        s = socket.socket(sock_family, socket.SOCK_DGRAM)
        s.settimeout(timeout)
        try:
            start = time.perf_counter()
            s.sendto(query_packet, (ip, port))
            data, _ = s.recvfrom(512)
            elapsed = (time.perf_counter() - start) * 1000
            if not is_valid_dns_response(data, txid):
                if debug:
                    print(f"{C.YELLOW}[DEBUG] Ignoring invalid/stale DNS reply from {resolver.get('name', ip)} ({ip}) for {hostname}{C.RESET}")
                return None
            return round(elapsed, 2)
        finally:
            s.close()
    except (socket.timeout, socket.gaierror, OSError) as e:
        if debug:
            print(f"{C.YELLOW}[DEBUG] DNS lookup failed for {resolver.get('name', ip)} ({ip}) on {hostname}: {e}{C.RESET}")
    except Exception as e:
        if debug:
            print(f"{C.YELLOW}[DEBUG] Unexpected DNS error for {resolver.get('name', ip)}: {e}{C.RESET}")
    return None



def get_doh_latency(doh_url: str, hostname: str = "google.com", timeout: int = DNS_TIMEOUT, debug: bool = False) -> Optional[float]:
    """Benchmark DNS-over-HTTPS (DoH) resolution time in ms."""
    try:
        url = f"{doh_url}?name={hostname}&type=A"
        headers = {"Accept": "application/dns-json"}
        start = time.perf_counter()
        res = make_http_request(url, headers=headers, timeout=timeout, debug=debug)
        elapsed = (time.perf_counter() - start) * 1000
        if res and ("Answer" in res or "Status" in res):
            return round(elapsed, 2)
    except Exception as e:
        if debug:
            print(f"{C.YELLOW}[DEBUG] DoH resolution error for {doh_url}: {e}{C.RESET}")
    return None



def get_dns_category(name: str, ip: str) -> str:
    """Categorizes DNS resolver role and capability for reporting."""
    name_lower = name.lower()
    if "local gateway" in name_lower or "router" in name_lower:
        return "Local Router Cache (Fastest)"
    elif "system dns" in name_lower:
        return "Current System Default"
    elif "cloudflare" in name_lower:
        return "Ultra-Fast & Privacy (No Logs)"
    elif "google" in name_lower:
        return "Global Anycast Reliability"
    elif "quad9" in name_lower:
        return "Malware & Phishing Threat Blocking"
    elif "adguard" in name_lower:
        return "System-Wide Ad & Tracker Blocking"
    elif "opendns" in name_lower:
        return "Cisco Security & Web Filtering"
    return "Public Resolver"



def measure_idle_ping(
    host: Optional[str] = None,
    count: int = 5,
    timeout: int = 2,
    ip_version: Optional[str] = None
) -> Dict[str, Any]:
    """Accurately measure idle baseline ping latency, jitter, and packet loss via ICMP ping with UDP fallback."""
    if not host:
        host = "2606:4700:4700::1111" if ip_version == "6" else "1.1.1.1"

    is_ipv6 = ":" in host or ip_version == "6"
    loss_pct = 0.0
    samples: List[float] = []

    # 1. Try ICMP ping first
    try:
        if sys.platform == "darwin":
            cmd = ["ping6" if is_ipv6 else "ping", "-c", str(count), "-t", str(timeout), host]
        else:
            cmd = ["ping", "-c", str(count), "-W", str(timeout)]
            if ip_version == "6" or is_ipv6:
                cmd.append("-6")
            elif ip_version == "4":
                cmd.append("-4")
            cmd.append(host)

        res = subprocess.run(cmd, capture_output=True, text=True, timeout=count * timeout + 2)
        if res.returncode == 0 or res.stdout:
            # Parse packet loss
            loss_m = re.search(r"(\d+(?:\.\d+)?)%\s*(?:packet\s*)?loss", res.stdout)
            if loss_m:
                loss_pct = round(float(loss_m.group(1)), 1)

            # Parse individual ping lines (e.g. time=15.2 ms or time<1 ms)
            time_matches = re.findall(r"time[=<]([0-9.]+)\s*ms", res.stdout)
            if time_matches:
                samples = [round(float(t), 2) for t in time_matches]
    except Exception:
        # ICMP probe failed (no privileges / ICMP blocked); fallback to UDP probe below.
        pass

    # 2. UDP DNS socket probe fallback if ICMP failed or produced no samples
    if not samples:
        sent = count
        received = 0
        resolver = {"name": "Probe", "ip": host, "port": 53}
        for _ in range(count):
            lat = get_dns_latency(resolver, "google.com", timeout=timeout, debug=False)
            if lat is not None:
                samples.append(lat)
                received += 1
            time.sleep(0.05)
        loss_pct = round(((sent - received) / sent) * 100.0, 1) if sent > 0 else 0.0

    stats = calculate_statistics(samples) if samples else {"min": 0.0, "max": 0.0, "avg": 0.0, "median": 0.0}
    jitter = calculate_jitter(samples) if samples else 0.0

    return {
        "host": host,
        "loss": loss_pct,
        "stats": stats,
        "jitter": jitter,
        "samples": samples
    }



def measure_packet_loss(host: str = "1.1.1.1", count: int = 5, timeout: int = 2) -> float:
    """Measure packet loss percentage via ICMP ping with UDP socket probe fallback."""
    return measure_idle_ping(host=host, count=count, timeout=timeout)["loss"]



def get_speed_tier(dl_mbps: float) -> str:
    """Classifies bandwidth speed tier based on download throughput."""
    if dl_mbps >= 2000:
        return "Multi-Gigabit Fiber (Hyper Speed)"
    elif dl_mbps >= 900:
        return "Gigabit Fiber (Ultra High Speed)"
    elif dl_mbps >= 300:
        return "Ultra-Fast Broadband"
    elif dl_mbps >= 100:
        return "High-Speed Broadband"
    elif dl_mbps >= 25:
        return "Standard Broadband"
    elif dl_mbps >= 10:
        return "Entry-Level Broadband"
    else:
        return "Basic / Low-Speed Connection"



def calculate_network_suitability(
    dl_mbps: float,
    ul_mbps: float,
    ping_ms: float,
    jitter_ms: float,
    bb_grade: str,
    packet_loss_pct: float = 0.0
) -> Dict[str, Any]:
    """Calculate overall Network Quality Score (0-100) and real-world application ratings."""
    gaming_score = 100.0
    if ping_ms > 100:
        gaming_score -= 40
    elif ping_ms > 50:
        gaming_score -= 20
    elif ping_ms > 30:
        gaming_score -= 10

    if jitter_ms > 20:
        gaming_score -= 25
    elif jitter_ms > 10:
        gaming_score -= 15

    if bb_grade in ("D", "F"):
        gaming_score -= 25
    elif bb_grade in ("C",):
        gaming_score -= 12

    if packet_loss_pct > 2.0:
        gaming_score -= 30
    elif packet_loss_pct > 0.5:
        gaming_score -= 15

    gaming_score = max(0.0, min(100.0, gaming_score))
    if gaming_score >= 88:
        gaming_status = "Excellent (Competitive Esports)"
    elif gaming_score >= 70:
        gaming_status = "Good (Smooth Casual Gaming)"
    elif gaming_score >= 50:
        gaming_status = "Fair (Occasional Latency Spikes)"
    else:
        gaming_status = "Poor (Noticeable Lag & Stutter)"

    streaming_score = 100.0
    if dl_mbps < 5:
        streaming_score = 15
    elif dl_mbps < 25:
        streaming_score = 60
    elif dl_mbps < 50:
        streaming_score = 85
    elif dl_mbps < 100:
        streaming_score = 95

    if packet_loss_pct > 3.0:
        streaming_score -= 20

    streaming_score = max(0.0, min(100.0, streaming_score))
    if streaming_score >= 90:
        streaming_status = "Flawless (Multi-Device 4K/8K HDR)"
    elif streaming_score >= 65:
        streaming_status = "Good (Single 4K / Multi-1080p)"
    else:
        streaming_status = "Limited (1080p / 720p Max)"

    video_call_score = 100.0
    if ul_mbps < 3:
        video_call_score -= 40
    elif ul_mbps < 10:
        video_call_score -= 15

    if ping_ms > 80:
        video_call_score -= 25
    if jitter_ms > 15:
        video_call_score -= 20
    if packet_loss_pct > 1.0:
        video_call_score -= 25

    video_call_score = max(0.0, min(100.0, video_call_score))
    if video_call_score >= 88:
        video_call_status = "Studio Quality (Flawless HD/4K Calls)"
    elif video_call_score >= 65:
        video_call_status = "Good (Reliable HD Group Calls)"
    else:
        video_call_status = "Degraded (Audio/Video Artifacts)"

    overall_score = round((gaming_score * 0.35) + (streaming_score * 0.35) + (video_call_score * 0.30), 1)

    return {
        "overall_score": overall_score,
        "speed_tier": get_speed_tier(dl_mbps),
        "gaming": {"score": round(gaming_score, 1), "status": gaming_status},
        "streaming": {"score": round(streaming_score, 1), "status": streaming_status},
        "video_call": {"score": round(video_call_score, 1), "status": video_call_status}
    }



def calculate_bufferbloat_grade(unloaded_ping: float, loaded_ping: float) -> Tuple[str, float]:
    """Calculate bufferbloat latency delta and assign standard letter grade (A+ to F)."""
    delta = round(max(0.0, loaded_ping - unloaded_ping), 2)
    if delta <= 5.0:
        grade = "A+"
    elif delta <= 15.0:
        grade = "A"
    elif delta <= 30.0:
        grade = "B"
    elif delta <= 60.0:
        grade = "C"
    elif delta <= 120.0:
        grade = "D"
    else:
        grade = "F"
    return grade, delta



def calculate_directional_bufferbloat(
    unloaded_ping: float,
    dl_loaded_pings: List[float],
    ul_loaded_pings: List[float]
) -> Dict[str, Any]:
    """Calculates directional bufferbloat metrics (Download Loaded vs Upload Loaded vs Idle)."""
    dl_loaded_avg = round(sum(dl_loaded_pings) / len(dl_loaded_pings), 2) if dl_loaded_pings else unloaded_ping
    ul_loaded_avg = round(sum(ul_loaded_pings) / len(ul_loaded_pings), 2) if ul_loaded_pings else unloaded_ping

    dl_grade, dl_delta = calculate_bufferbloat_grade(unloaded_ping, dl_loaded_avg)
    ul_grade, ul_delta = calculate_bufferbloat_grade(unloaded_ping, ul_loaded_avg)

    # Worst-case composite grade
    grade_order = ["A+", "A", "B", "C", "D", "F"]
    composite_grade = max(dl_grade, ul_grade, key=lambda g: grade_order.index(g) if g in grade_order else 5)
    max_delta = max(dl_delta, ul_delta)

    return {
        "grade": composite_grade,
        "delta_ms": max_delta,
        "unloaded_ping_ms": unloaded_ping,
        "download_loaded_ping_ms": dl_loaded_avg,
        "download_delta_ms": dl_delta,
        "download_grade": dl_grade,
        "upload_loaded_ping_ms": ul_loaded_avg,
        "upload_delta_ms": ul_delta,
        "upload_grade": ul_grade,
        "loaded_ping_ms": max(dl_loaded_avg, ul_loaded_avg)
    }



def calculate_jitter(latency_list: List[float]) -> float:
    """Calculates network jitter (mean deviation between consecutive ping packets)."""
    if len(latency_list) < 2:
        return 0.0
    diffs = [abs(latency_list[i] - latency_list[i - 1]) for i in range(1, len(latency_list))]
    return round(sum(diffs) / len(diffs), 2)



def calculate_statistics(values: List[float]) -> Dict[str, float]:
    """Calculate min, max, avg, and median statistics for a list of values."""
    if not values:
        return {"min": 0.0, "max": 0.0, "avg": 0.0, "median": 0.0}
    sorted_vals = sorted(values)
    avg = round(sum(values) / len(values), 2)
    median = (
        sorted_vals[len(sorted_vals) // 2]
        if len(sorted_vals) % 2
        else (sorted_vals[len(sorted_vals) // 2 - 1] + sorted_vals[len(sorted_vals) // 2]) / 2.0
    )
    return {
        "min": round(min(values), 2),
        "max": round(max(values), 2),
        "avg": avg,
        "median": round(median, 2)
    }



MAX_RUNS = 20
MAX_MONITOR_MINUTES = 1440
MAX_CONSECUTIVE_MONITOR_FAILURES = 3


