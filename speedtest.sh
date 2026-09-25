#!/usr/bin/env bash
""":"
# Network Speed Benchmark Tool Launcher
# Enables universal execution via: bash speedtest.sh, sh speedtest.sh, ./speedtest.sh, or python3 speedtest.sh
exec python3 "$0" "$@"
"""
# -*- coding: utf-8 -*-
"""
Network Speed Benchmark Tool
Author: Shadowharvy
Version: 3.1.0
Description: High-performance, cross-platform network speed & diagnostic benchmark tool for Linux, macOS, and Termux.
Features: Multi-Engine Speed Testing (Ookla, Fast.com, Cloudflare, Custom), Adaptive Multi-Stream Saturation,
          Directional Bufferbloat (Idle / DL / UL), Dual-Stack IPv4/IPv6, ICMP Packet Loss, System & DoH DNS Benchmarking,
          Hardware Link Speed (Gbps) & Wi-Fi Diagnostics, Live Throughput Progress, Unicode History Sparklines,
          SLA Threshold Alerts, Machine-Readable JSON/Markdown/CSV Exports, and Standalone Glassmorphism HTML Dashboard.
"""

import argparse
import csv
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

# --- Version & Constants ---
VERSION = "3.2.0"
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


def build_dns_query(hostname: str, query_type: str = "A") -> bytes:
    """Build a standard DNS query packet (Type A or AAAA)."""
    header = b"\xaa\xbb\x01\x00\x00\x01\x00\x00\x00\x00\x00\x00"
    qname = b"".join(bytes([len(part)]) + part.encode("ascii") for part in hostname.split(".")) + b"\x00"
    qtype = b"\x00\x1c" if query_type.upper() == "AAAA" else b"\x00\x01"  # Type AAAA (28) or A (1)
    qclass = b"\x00\x01"  # Class IN
    return header + qname + qtype + qclass


def get_dns_latency(resolver: Dict[str, Any], hostname: str, timeout: int = DNS_TIMEOUT, debug: bool = False) -> Optional[float]:
    """Query a DNS resolver via UDP socket and measure lookup time in ms."""
    try:
        ip = resolver["ip"]
        port = resolver.get("port", 53)
        is_ipv6 = ":" in ip
        query_type = "AAAA" if is_ipv6 else "A"
        query_packet = build_dns_query(hostname, query_type)

        sock_family = socket.AF_INET6 if is_ipv6 else socket.AF_INET
        s = socket.socket(sock_family, socket.SOCK_DGRAM)
        s.settimeout(timeout)
        try:
            start = time.perf_counter()
            s.sendto(query_packet, (ip, port))
            data, _ = s.recvfrom(512)
            elapsed = (time.perf_counter() - start) * 1000
            if len(data) >= 12:
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


def get_system_dns_resolvers() -> List[Dict[str, Any]]:
    """Discover system-configured DNS nameservers dynamically across Linux, macOS, and Termux."""
    dns_ips: List[str] = []

    # 1. systemd-resolved (Linux)
    try:
        res = subprocess.run(["resolvectl", "status"], capture_output=True, text=True, timeout=2)
        if res.returncode == 0:
            dns_ips.extend(re.findall(r"DNS Servers:\s*([0-9a-fA-F:.]+)", res.stdout))
    except Exception:
        pass

    # 2. NetworkManager nmcli (Linux)
    try:
        res = subprocess.run(["nmcli", "dev", "show"], capture_output=True, text=True, timeout=2)
        if res.returncode == 0:
            dns_ips.extend(re.findall(r"IP[46]\.DNS\[\d+\]:\s*([0-9a-fA-F:.]+)", res.stdout))
    except Exception:
        pass

    # 3. macOS scutil
    try:
        res = subprocess.run(["scutil", "--dns"], capture_output=True, text=True, timeout=2)
        if res.returncode == 0:
            dns_ips.extend(re.findall(r"nameserver\[\d+\]\s*:\s*([0-9a-fA-F:.]+)", res.stdout))
    except Exception:
        pass

    # 4. Android / Termux getprop
    try:
        for prop in ["net.dns1", "net.dns2", "net.dns3", "net.dns4"]:
            res = subprocess.run(["getprop", prop], capture_output=True, text=True, timeout=2)
            if res.returncode == 0 and res.stdout.strip():
                dns_ips.append(res.stdout.strip())
    except Exception:
        pass

    # 5. /etc/resolv.conf fallback
    for conf_file in ["/etc/resolv.conf", "/run/systemd/resolve/resolv.conf"]:
        if os.path.exists(conf_file):
            try:
                with open(conf_file, "r") as f:
                    for line in f:
                        line = line.strip()
                        if line.startswith("nameserver"):
                            parts = line.split()
                            if len(parts) >= 2:
                                ip_cand = parts[1].split("%")[0]
                                if ip_cand not in ("127.0.0.1", "127.0.0.53"):
                                    dns_ips.append(ip_cand)
            except Exception:
                pass

    unique_ips: List[str] = []
    for ip in dns_ips:
        clean_ip = ip.strip()
        if clean_ip and clean_ip not in unique_ips and clean_ip not in ("127.0.0.1", "127.0.0.53"):
            unique_ips.append(clean_ip)

    return [{"name": f"System DNS ({ip})", "ip": ip, "port": 53} for ip in unique_ips]


def run_dns_test(
    runs: int = 3,
    quiet: bool = False,
    debug: bool = False,
    gateway_ip: Optional[str] = None,
    test_doh: bool = True,
    enable_ipv6: bool = True
) -> Dict[str, Any]:
    """Run high-performance concurrent DNS resolution benchmarks against public, gateway, system, and DoH resolvers."""
    if not quiet:
        print(f"{C.CYAN}{C.BOLD}--- Running DNS & DoH Resolution Test ---{C.RESET}")

    resolvers_to_test = list(DNS_RESOLVERS)

    # Only include IPv6 resolvers if IPv6 network route is truly functional
    if enable_ipv6 and is_ipv6_available():
        for r_v6 in IPV6_DNS_RESOLVERS:
            if not any(r["ip"] == r_v6["ip"] for r in resolvers_to_test):
                resolvers_to_test.append(r_v6)

    if gateway_ip and gateway_ip not in ("Unknown", "Unavailable", "N/A"):
        if not any(r["ip"] == gateway_ip for r in resolvers_to_test):
            resolvers_to_test.insert(0, {"name": f"Local Gateway ({gateway_ip})", "ip": gateway_ip, "port": 53})

    system_dns = get_system_dns_resolvers()
    for sys_r in system_dns:
        if not any(r["ip"] == sys_r["ip"] for r in resolvers_to_test):
            resolvers_to_test.append(sys_r)

    dns_results: Dict[str, Any] = {}
    doh_results: Dict[str, Any] = {}
    all_times: List[float] = []

    def probe_and_test_resolver(r: Dict[str, Any]) -> Tuple[Dict[str, Any], List[float]]:
        # Fast liveness probe first: check 1 query with short timeout
        probe = get_dns_latency(r, DNS_QUERIES[0], timeout=1.5, debug=debug)
        if probe is None:
            return r, []
        times = [probe]
        for _ in range(runs):
            for query in DNS_QUERIES:
                lat = get_dns_latency(r, query, timeout=DNS_TIMEOUT, debug=debug)
                if lat is not None:
                    times.append(lat)
        return r, times

    # Concurrently benchmark all resolvers
    with ThreadPoolExecutor(max_workers=min(max(len(resolvers_to_test), 1), 8)) as ex:
        futs = {ex.submit(probe_and_test_resolver, r): r for r in resolvers_to_test}
        for f in as_completed(futs):
            resolver, resolver_times = f.result()
            resolver_name = resolver["name"]
            if resolver_times:
                stats = calculate_statistics(resolver_times)
                dns_results[resolver_name] = {
                    "resolver_ip": resolver["ip"],
                    "queries": len(resolver_times),
                    "latency_ms": stats
                }
                all_times.extend(resolver_times)
                if not quiet:
                    print(f"  {resolver_name:<34} {C.GREEN}✓ {stats['avg']:>6.2f} ms avg{C.RESET} {C.DIM}(min: {stats['min']}, max: {stats['max']}){C.RESET}")
            else:
                if not quiet:
                    print(f"  {resolver_name:<34} {C.RED}✗ Failed / Unreachable{C.RESET}")

    if test_doh:
        if not quiet:
            print(f"  {C.DIM}Testing DNS-over-HTTPS (DoH) Latencies...{C.RESET}")

        def bench_doh(r: Dict[str, Any]) -> Tuple[str, Optional[str], List[float]]:
            doh_url = r.get("doh")
            if not doh_url:
                return r["name"], None, []
            times = []
            for _ in range(max(1, runs - 1)):
                for q in DNS_QUERIES[:2]:
                    lat = get_doh_latency(doh_url, q, DNS_TIMEOUT, debug)
                    if lat is not None:
                        times.append(lat)
            return r["name"], doh_url, times

        with ThreadPoolExecutor(max_workers=len(DNS_RESOLVERS)) as doh_ex:
            doh_futs = [doh_ex.submit(bench_doh, r) for r in DNS_RESOLVERS if r.get("doh")]
            for f in as_completed(doh_futs):
                name, doh_url, d_times = f.result()
                if d_times and doh_url:
                    doh_stats = calculate_statistics(d_times)
                    doh_results[f"{name} (DoH)"] = {
                        "url": doh_url,
                        "latency_ms": doh_stats
                    }

    overall_stats = calculate_statistics(all_times) if all_times else {"min": 0.0, "max": 0.0, "avg": 0.0, "median": 0.0}

    return {
        "dns_resolvers": dns_results,
        "doh_resolvers": doh_results,
        "overall_latency_ms": overall_stats,
        "total_queries": len(all_times)
    }


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


def get_fastest_dns_recommendation(dns_results: Optional[Dict[str, Any]]) -> Optional[Dict[str, Any]]:
    """Analyze DNS benchmarking results and generate tailored DNS recommendation profiles."""
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
    overall_fastest = valid[0]

    # Build ranked leaderboard
    leaderboard = []
    for idx, r in enumerate(valid):
        leaderboard.append({
            "rank": idx + 1,
            "name": r[0],
            "ip": r[1],
            "latency_ms": r[2],
            "category": get_dns_category(r[0], r[1])
        })

    # Separate public providers from system/gateway resolvers
    public_resolvers = [r for r in valid if not r[0].startswith(("System DNS", "Local Gateway", "Router"))]
    system_resolvers = [r for r in valid if r[0].startswith(("System DNS", "Local Gateway", "Router"))]

    fastest_public = public_resolvers[0] if public_resolvers else overall_fastest
    base_provider_name = fastest_public[0].replace(" (IPv6)", "").replace(" (DoH)", "").strip()
    provider_info = DNS_PROVIDER_DETAILS.get(base_provider_name, {
        "primary": fastest_public[1],
        "secondary": "N/A",
        "ipv6_primary": "N/A",
        "ipv6_secondary": "N/A",
        "features": "Low-latency public resolver",
    })

    system_avg = system_resolvers[0][2] if system_resolvers else None
    public_avg = fastest_public[2]

    if system_avg is not None:
        if public_avg < system_avg and (system_avg - public_avg) > 3.0:
            savings_pct = round(((system_avg - public_avg) / system_avg) * 100, 1)
            savings_ms = round(system_avg - public_avg, 2)
            status_msg = f"Switch to {base_provider_name} for {savings_pct}% faster resolution (saving {savings_ms} ms vs current System DNS)."
            is_optimal = False
        elif system_avg <= public_avg:
            savings_pct = 0.0
            status_msg = f"Your current System/Gateway DNS ({system_resolvers[0][1]}) is already delivering optimal latency ({system_avg:.1f} ms avg)! Fastest public alternative: {base_provider_name} ({provider_info['primary']})."
            is_optimal = True
        else:
            savings_pct = 0.0
            status_msg = f"Your current System DNS and {base_provider_name} perform similarly (~{public_avg:.1f} ms)."
            is_optimal = True
    else:
        slowest = valid[-1]
        savings_pct = round(((slowest[2] - public_avg) / slowest[2]) * 100, 1) if slowest[2] > 0 else 0.0
        status_msg = f"Recommended: {base_provider_name} (Primary: {provider_info['primary']}, Secondary: {provider_info['secondary']}) with {public_avg:.1f} ms avg resolution."
        is_optimal = False

    def find_benchmark_stat(keyword: str) -> Tuple[Optional[float], Optional[int]]:
        for item in leaderboard:
            if keyword.lower() in item["name"].lower():
                return item["latency_ms"], item["rank"]
        return None, None

    cf_info = DNS_PROVIDER_DETAILS.get("Cloudflare", {})
    quad9_info = DNS_PROVIDER_DETAILS.get("Quad9", {})
    adguard_info = DNS_PROVIDER_DETAILS.get("AdGuard", {})
    google_info = DNS_PROVIDER_DETAILS.get("Google", {})

    cf_lat, cf_rank = find_benchmark_stat("Cloudflare")
    quad9_lat, quad9_rank = find_benchmark_stat("Quad9")
    adguard_lat, adguard_rank = find_benchmark_stat("AdGuard")
    google_lat, google_rank = find_benchmark_stat("Google")

    profiles = {
        "best_speed_privacy": {
            "name": "Cloudflare",
            "primary": cf_info.get("primary", "1.1.1.1"),
            "secondary": cf_info.get("secondary", "1.0.0.1"),
            "ipv6_primary": cf_info.get("ipv6_primary", "2606:4700:4700::1111"),
            "latency_ms": cf_lat if cf_lat is not None else public_avg,
            "rank": cf_rank,
            "features": cf_info.get("features", "Fastest response time, strict privacy (no logging)")
        },
        "best_security": {
            "name": "Quad9",
            "primary": quad9_info.get("primary", "9.9.9.9"),
            "secondary": quad9_info.get("secondary", "149.112.112.112"),
            "ipv6_primary": quad9_info.get("ipv6_primary", "2620:fe::fe"),
            "latency_ms": quad9_lat,
            "rank": quad9_rank,
            "features": quad9_info.get("features", "Automatic malware, phishing & ransomware blocking")
        },
        "best_adblocking": {
            "name": "AdGuard",
            "primary": adguard_info.get("primary", "94.140.14.14"),
            "secondary": adguard_info.get("secondary", "94.140.15.15"),
            "ipv6_primary": adguard_info.get("ipv6_primary", "2a10:50c0::ad1:ff"),
            "latency_ms": adguard_lat,
            "rank": adguard_rank,
            "features": adguard_info.get("features", "System-wide ad, tracker, and malware blocking")
        },
        "best_reliability": {
            "name": "Google",
            "primary": google_info.get("primary", "8.8.8.8"),
            "secondary": google_info.get("secondary", "8.8.4.4"),
            "ipv6_primary": google_info.get("ipv6_primary", "2001:4860:4860::8888"),
            "latency_ms": google_lat,
            "rank": google_rank,
            "features": google_info.get("features", "Global anycast stability, high reliability")
        }
    }

    return {
        "name": base_provider_name,
        "ip": provider_info["primary"],
        "primary": provider_info["primary"],
        "secondary": provider_info["secondary"],
        "ipv6_primary": provider_info["ipv6_primary"],
        "ipv6_secondary": provider_info.get("ipv6_secondary", "N/A"),
        "latency_ms": public_avg,
        "savings_pct": savings_pct,
        "features": provider_info["features"],
        "status_message": status_msg,
        "is_optimal": is_optimal,
        "leaderboard": leaderboard,
        "profiles": profiles,
        "system_dns_name": system_resolvers[0][0] if system_resolvers else "N/A",
        "system_dns_latency": system_avg if system_avg else "N/A",
        "slowest_name": valid[-1][0],
        "slowest_latency_ms": valid[-1][2],
    }


def print_dns_leaderboard(dns_rec: Dict[str, Any], width: int = 76) -> None:
    """Print formatted DNS leaderboard and smart recommendation profiles."""
    top_bar = "═" * width
    h_line = "─" * width
    print(f"\n{C.CYAN}{C.BOLD}{top_bar}{C.RESET}")
    print(f"{C.CYAN}{C.BOLD}{'DNS RESOLUTION LEADERBOARD':^{width}}{C.RESET}")
    print(f"{C.CYAN}{C.BOLD}{top_bar}{C.RESET}")
    print(f"  {C.BOLD}{'Rank':<8} {'Resolver':<28} {'Latency':<12} {'Category / Features'}{C.RESET}")
    print(f"  {C.DIM}{h_line}{C.RESET}")

    for idx, item in enumerate(dns_rec.get("leaderboard", [])):
        rank_str = f"#{idx+1}"
        badge = ["🥇", "🥈", "🥉"][idx] if idx < 3 else "  "
        display_rank = f"{badge} {rank_str:<4}"
        lat_val = item["latency_ms"]
        lat_color = C.GREEN if lat_val < 35 else (C.YELLOW if lat_val < 100 else C.RED)
        print(f"  {display_rank:<8} {item['name'][:27]:<28} {lat_color}{lat_val:>6.2f} ms{C.RESET}   {C.DIM}{item['category']}{C.RESET}")

    print(f"  {C.DIM}{h_line}{C.RESET}")
    print(f"  {C.MAGENTA}{C.BOLD}🏆 DNS Recommendations for Your Network:{C.RESET}")

    # Profile 1: Best Speed & Privacy
    speed_prof = dns_rec.get("profiles", {}).get("best_speed_privacy", dns_rec)
    v6_part = f" | IPv6: {speed_prof.get('ipv6_primary')}" if speed_prof.get('ipv6_primary') else ""
    print(f"  • {C.BOLD}🚀 Best for Speed & Privacy:{C.RESET} {C.CYAN}{speed_prof.get('name')}{C.RESET} (Primary: {C.GREEN}{speed_prof.get('primary')}{C.RESET} | Secondary: {speed_prof.get('secondary')}{v6_part})")
    print(f"    {C.DIM}↳ {speed_prof.get('features')}{C.RESET}")

    # Profile 2: Best Security
    sec_prof = dns_rec.get("profiles", {}).get("best_security", DNS_PROVIDER_DETAILS.get("Quad9", {}))
    print(f"  • {C.BOLD}🛡️ Best for Security:{C.RESET} {C.CYAN}Quad9{C.RESET} (Primary: {C.GREEN}{sec_prof.get('primary')}{C.RESET} | Secondary: {sec_prof.get('secondary')})")
    print(f"    {C.DIM}↳ {sec_prof.get('features')}{C.RESET}")

    # Profile 3: Best Ad-Block
    ad_prof = dns_rec.get("profiles", {}).get("best_adblocking", DNS_PROVIDER_DETAILS.get("AdGuard", {}))
    print(f"  • {C.BOLD}🚫 Best for Ad Blocking:{C.RESET} {C.CYAN}AdGuard{C.RESET} (Primary: {C.GREEN}{ad_prof.get('primary')}{C.RESET} | Secondary: {ad_prof.get('secondary')})")
    print(f"    {C.DIM}↳ {ad_prof.get('features')}{C.RESET}")

    # Status Message
    if dns_rec.get("is_optimal"):
        print(f"  • {C.BOLD}⚡ Current Status:{C.RESET} {C.GREEN}Your current DNS ({dns_rec.get('system_dns_name')}) is already optimal ({dns_rec.get('system_dns_latency')} ms)!{C.RESET}")
    else:
        print(f"  • {C.BOLD}⚡ Current Status:{C.RESET} {C.YELLOW}Switching to {speed_prof.get('name')} will speed up lookups by {dns_rec.get('savings_pct')}%!{C.RESET}")
    print(f"{C.CYAN}{C.BOLD}{top_bar}{C.RESET}\n")


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


def print_banner(quiet: bool) -> None:
    """Display modern stylized application banner."""
    if quiet:
        return
    print(f"\n{C.CYAN}{C.BOLD}================================================================{C.RESET}")
    print(f"{C.CYAN}{C.BOLD}             NETWORK SPEED & DIAGNOSTIC BENCHMARK               {C.RESET}")
    print(f"{C.DIM}          Created by: {C.MAGENTA}{C.BOLD}Shadowharvy{C.RESET} | Version: {C.GREEN}{C.BOLD}v{VERSION}{C.RESET}")
    print(f"{C.CYAN}{C.BOLD}================================================================{C.RESET}\n")


def check_endpoints(quiet: bool, debug: bool = False, ip_version: Optional[str] = None) -> Tuple[bool, bool, bool]:
    """Performs pre-flight connectivity checks for Ookla, Fast.com, and Cloudflare."""
    if not quiet:
        print(f"{C.BLUE}[i] Performing Pre-Flight Endpoint Probes...{C.RESET}")

    st_ok, fast_ok, cf_ok = False, False, False

    # Check Ookla
    res_st = make_http_request("https://www.speedtest.net/speedtest-config.php", timeout=CHECK_TIMEOUT, debug=debug, ip_version=ip_version)
    if res_st and "client" in res_st:
        st_ok = True

    # Check Fast.com
    html = make_http_request("https://fast.com", timeout=CHECK_TIMEOUT, debug=debug, ip_version=ip_version)
    if html:
        js_path = JS_PATH_PATTERN.search(html)
        if js_path:
            js_url = f"https://fast.com{js_path.group(1)}"
            js_content = make_http_request(js_url, timeout=CHECK_TIMEOUT, debug=debug, ip_version=ip_version)
            if js_content:
                token = TOKEN_PATTERN.search(js_content)
                if token:
                    api_url = f"https://api.fast.com/netflix/speedtest/v2?https=true&token={token.group(1)}&urlCount=1"
                    api_res = make_http_request(api_url, timeout=CHECK_TIMEOUT, debug=debug, ip_version=ip_version)
                    if api_res and "targets" in api_res:
                        fast_ok = True

    # Check Cloudflare
    res_cf = make_http_request("https://speed.cloudflare.com/__down?bytes=1", timeout=CHECK_TIMEOUT, debug=debug, ip_version=ip_version)
    if res_cf is not None:
        cf_ok = True

    if not quiet:
        st_status = f"{C.GREEN}Accessible{C.RESET}" if st_ok else f"{C.RED}Blocked / Unreachable{C.RESET}"
        fast_status = f"{C.GREEN}Accessible{C.RESET}" if fast_ok else f"{C.RED}Blocked / Unreachable{C.RESET}"
        cf_status = f"{C.GREEN}Accessible{C.RESET}" if cf_ok else f"{C.RED}Blocked / Unreachable{C.RESET}"
        print(f"    {C.BOLD}Ookla (Speedtest):{C.RESET}  {st_status}")
        print(f"    {C.BOLD}Fast.com (Netflix):{C.RESET} {fast_status}")
        print(f"    {C.BOLD}Cloudflare CDN:{C.RESET}     {cf_status}\n")

    return st_ok, fast_ok, cf_ok


def get_network_adapter_info(debug: bool = False) -> Dict[str, str]:
    """Detects active network interface, gateway IP, link speed, Wi-Fi SSID, frequency, and signal."""
    info = {
        "interface": "Unknown",
        "gateway": "Unknown",
        "link_speed": "N/A",
        "interface_type": "Ethernet",
        "wifi_ssid": "N/A (Wired/Unknown)",
        "wifi_signal": "N/A",
        "wifi_frequency": "N/A",
        "wifi_channel": "N/A",
        "mtu": "1500"
    }

    # 1. Linux route & interface detection
    try:
        res = subprocess.run(["ip", "route", "show", "default"], capture_output=True, text=True, timeout=2)
        if res.returncode == 0 and res.stdout:
            parts = res.stdout.strip().split()
            if "via" in parts and "dev" in parts:
                info["gateway"] = parts[parts.index("via") + 1]
                info["interface"] = parts[parts.index("dev") + 1]
    except Exception:
        pass

    # 2. macOS route detection fallback
    if info["interface"] == "Unknown" and sys.platform == "darwin":
        try:
            res = subprocess.run(["route", "-n", "get", "default"], capture_output=True, text=True, timeout=2)
            if res.returncode == 0 and res.stdout:
                gw_m = re.search(r"gateway:\s*([0-9a-fA-F:.]+)", res.stdout)
                if_m = re.search(r"interface:\s*(\w+)", res.stdout)
                if gw_m:
                    info["gateway"] = gw_m.group(1)
                if if_m:
                    info["interface"] = if_m.group(1)
        except Exception:
            pass

    iface = info["interface"]
    if iface != "Unknown":
        if iface.startswith(("wl", "wlan", "wifi", "en0")):
            info["interface_type"] = "Wi-Fi"
        elif iface.startswith(("wg", "tun", "tap", "ppp", "vpn")):
            info["interface_type"] = "VPN / Tunnel"

        # Link speed from sysfs (Linux)
        speed_file = f"/sys/class/net/{iface}/speed"
        if os.path.exists(speed_file):
            try:
                with open(speed_file, "r") as f:
                    speed_val = f.read().strip()
                    if speed_val.isdigit() and int(speed_val) > 0:
                        speed_mbps = int(speed_val)
                        if speed_mbps >= 1000:
                            info["link_speed"] = f"{speed_mbps / 1000:.1f} Gbps"
                        else:
                            info["link_speed"] = f"{speed_mbps} Mbps"
            except Exception:
                pass

        # MTU from sysfs (Linux)
        mtu_file = f"/sys/class/net/{iface}/mtu"
        if os.path.exists(mtu_file):
            try:
                with open(mtu_file, "r") as f:
                    info["mtu"] = f.read().strip()
            except Exception:
                pass

        # Wi-Fi link bitrate via iw (Linux)
        try:
            res_iw = subprocess.run(["iw", "dev", iface, "link"], capture_output=True, text=True, timeout=2)
            if res_iw.returncode == 0 and res_iw.stdout:
                info["interface_type"] = "Wi-Fi"
                tx_m = re.search(r"tx bitrate:\s*([0-9.]+)\s*(\w+Bit/s)", res_iw.stdout)
                ssid_m = re.search(r"SSID:\s*(.+)", res_iw.stdout)
                sig_m = re.search(r"signal:\s*(-?\d+)\s*dBm", res_iw.stdout)
                freq_m = re.search(r"freq:\s*(\d+)", res_iw.stdout)
                if tx_m:
                    info["link_speed"] = f"{tx_m.group(1)} {tx_m.group(2)}"
                if ssid_m:
                    info["wifi_ssid"] = ssid_m.group(1).strip()
                if sig_m:
                    info["wifi_signal"] = f"{sig_m.group(1)} dBm"
                if freq_m:
                    freq_int = int(freq_m.group(1))
                    band = "6 GHz" if freq_int > 5900 else ("5 GHz" if freq_int > 4900 else "2.4 GHz")
                    info["wifi_frequency"] = f"{freq_int} MHz ({band})"
        except Exception:
            pass

        # Wi-Fi details via nmcli (Linux)
        if info["wifi_ssid"] in ("N/A (Wired/Unknown)", "N/A"):
            try:
                res = subprocess.run(["nmcli", "-t", "-f", "active,ssid,signal,freq,chan", "dev", "wifi"], capture_output=True, text=True, timeout=2)
                if res.returncode == 0 and res.stdout:
                    for line in res.stdout.strip().split("\n"):
                        if line.startswith("yes:"):
                            fields = line.split(":")
                            if len(fields) >= 3:
                                info["wifi_ssid"] = fields[1]
                                info["wifi_signal"] = f"{fields[2]}%"
                                info["interface_type"] = "Wi-Fi"
                            if len(fields) >= 4 and fields[3]:
                                freq_val = fields[3].strip()
                                if not freq_val.endswith("MHz") and not freq_val.endswith("GHz"):
                                    freq_val = f"{freq_val} MHz"
                                info["wifi_frequency"] = freq_val
                            if len(fields) >= 5 and fields[4]:
                                info["wifi_channel"] = f"Ch {fields[4]}"
                            break
            except Exception:
                pass

        # Wi-Fi details via iwconfig (Linux fallback)
        if info["wifi_ssid"] in ("N/A (Wired/Unknown)", "N/A"):
            try:
                res = subprocess.run(["iwconfig", iface], capture_output=True, text=True, timeout=2)
                if res.returncode == 0 and res.stdout:
                    info["interface_type"] = "Wi-Fi"
                    ssid_m = re.search(r'ESSID:"([^"]+)"', res.stdout)
                    sig_m = re.search(r'Signal level=(-\d+\s*dBm|\d+/\d+)', res.stdout)
                    freq_m = re.search(r'Frequency:([0-9.]+\s*GHz)', res.stdout)
                    bitrate_m = re.search(r'Bit Rate=([0-9.]+\s*Mb/s)', res.stdout)
                    if ssid_m:
                        info["wifi_ssid"] = ssid_m.group(1)
                    if sig_m:
                        info["wifi_signal"] = sig_m.group(1)
                    if freq_m:
                        info["wifi_frequency"] = freq_m.group(1)
                    if bitrate_m and info["link_speed"] == "N/A":
                        info["link_speed"] = bitrate_m.group(1)
            except Exception:
                pass

        # macOS Wi-Fi details
        if sys.platform == "darwin" and info["wifi_ssid"] in ("N/A (Wired/Unknown)", "N/A"):
            try:
                airport_path = "/System/Library/PrivateFrameworks/Apple80211.framework/Versions/Current/Resources/airport"
                if os.path.exists(airport_path):
                    res = subprocess.run([airport_path, "-I"], capture_output=True, text=True, timeout=2)
                    if res.returncode == 0 and res.stdout:
                        ssid_m = re.search(r'\sSSID:\s*(.+)', res.stdout)
                        sig_m = re.search(r'\sagrCtlRSSI:\s*(-\d+)', res.stdout)
                        chan_m = re.search(r'\schannel:\s*(\d+)', res.stdout)
                        rate_m = re.search(r'\slastTxRate:\s*(\d+)', res.stdout)
                        if ssid_m:
                            info["wifi_ssid"] = ssid_m.group(1).strip()
                            info["interface_type"] = "Wi-Fi"
                        if sig_m:
                            info["wifi_signal"] = f"{sig_m.group(1)} dBm"
                        if chan_m:
                            info["wifi_channel"] = f"Ch {chan_m.group(1)}"
                        if rate_m and info["link_speed"] == "N/A":
                            info["link_speed"] = f"{rate_m.group(1)} Mbps"
            except Exception:
                pass

        # Wi-Fi details via /proc/net/wireless (Linux kernel zero-dependency fallback)
        if info["wifi_signal"] in ("N/A", "") and os.path.exists("/proc/net/wireless"):
            try:
                with open("/proc/net/wireless", "r") as f:
                    for line in f.readlines()[2:]:
                        parts = line.strip().split()
                        if len(parts) >= 4:
                            dev_name = parts[0].strip(":")
                            if dev_name == iface:
                                info["interface_type"] = "Wi-Fi"
                                link_qual = parts[2].rstrip(".")
                                level_dbm = parts[3].rstrip(".")
                                info["wifi_signal"] = f"{level_dbm} dBm (Quality: {link_qual})"
                                break
            except Exception:
                pass

        # macOS MTU detection
        if sys.platform == "darwin" and info["mtu"] == "1500":
            try:
                res_if = subprocess.run(["ifconfig", iface], capture_output=True, text=True, timeout=2)
                if res_if.returncode == 0:
                    mtu_m = re.search(r"mtu\s+(\d+)", res_if.stdout)
                    if mtu_m:
                        info["mtu"] = mtu_m.group(1)
            except Exception:
                pass

    return info


def get_lan_ip(family: str = "4", debug: bool = False) -> str:
    """Gets primary local LAN IP address for IPv4 or IPv6."""
    try:
        if family == "6":
            with socket.socket(socket.AF_INET6, socket.SOCK_DGRAM) as s:
                s.settimeout(2)
                s.connect(("2606:4700:4700::1111", 80))
                return s.getsockname()[0]
        else:
            with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as s:
                s.settimeout(2)
                s.connect(("1.1.1.1", 80))
                return s.getsockname()[0]
    except Exception as e:
        if debug:
            print(f"{C.YELLOW}[DEBUG] Failed to get LAN IP (v{family}): {e}{C.RESET}")
        return "Unavailable"


def get_geo_info(debug: bool = False, ip_version: Optional[str] = None) -> Dict[str, Any]:
    """Retrieves public IP, ISP, ASN, and Geolocation info with dual-stack IPv4/IPv6 support."""
    geo: Dict[str, Any] = {
        "ip": "Unavailable",
        "ipv6": "Unavailable",
        "isp": "Unknown ISP",
        "org": "Unknown",
        "city": "Unknown",
        "country": "Unknown",
        "country_code": "N/A"
    }

    # Primary IPv4 Geolocation
    try:
        res = make_http_request("http://ip-api.com/json/?fields=status,message,country,countryCode,regionName,city,isp,org,as,query", timeout=HTTP_TIMEOUT, debug=debug, ip_version="4" if ip_version != "6" else None)
        if res:
            data = json.loads(res)
            if isinstance(data, dict) and data.get("status") == "success":
                geo["ip"] = data.get("query", "Unavailable")
                geo["isp"] = data.get("isp", "Unknown ISP")
                geo["org"] = data.get("org", data.get("isp", "Unknown"))
                geo["city"] = data.get("city", "Unknown")
                geo["country"] = data.get("country", "Unknown")
                geo["country_code"] = data.get("countryCode", "N/A")
    except Exception as e:
        if debug:
            print(f"{C.YELLOW}[DEBUG] Primary geo lookup failed: {e}{C.RESET}")

    # Fallback IPv4 if needed
    if geo["ip"] == "Unavailable":
        try:
            ip_str = make_http_request("https://api.ipify.org?format=json", timeout=3, debug=debug, ip_version="4")
            if ip_str:
                geo["ip"] = json.loads(ip_str).get("ip", "Unavailable")
        except Exception:
            pass

    # IPv6 detection probe
    try:
        res_v6 = make_http_request("https://api64.ipify.org?format=json", timeout=3, debug=debug, ip_version="6")
        if res_v6:
            v6_val = json.loads(res_v6).get("ip", "")
            if ":" in v6_val:
                geo["ipv6"] = v6_val
    except Exception:
        pass

    return geo


def get_speedtest(debug: bool = False, retries: int = MAX_RETRIES, ip_version: Optional[str] = None) -> Optional[Dict[str, Optional[float]]]:
    """Runs official Ookla speedtest binary if installed, or falls back to speedtest-cli."""
    # 1. Check for official Ookla CLI first (speedtest --format=json)
    ookla_bin = shutil.which("speedtest")
    if ookla_bin:
        for attempt in range(retries + 1):
            try:
                cmd = [ookla_bin, "--format=json", "--accept-license", "--accept-gdpr"]
                if ip_version == "4":
                    cmd.append("-4")
                elif ip_version == "6":
                    cmd.append("-6")
                res = subprocess.run(cmd, capture_output=True, text=True, timeout=45)
                if res.returncode == 0 and res.stdout:
                    data = json.loads(res.stdout)
                    dl_bytes_sec = data.get("download", {}).get("bandwidth", 0)
                    ul_bytes_sec = data.get("upload", {}).get("bandwidth", 0)
                    ping_lat = data.get("ping", {}).get("latency", 0.0)
                    jitter_lat = data.get("ping", {}).get("jitter", 0.0)
                    dl_latency = data.get("download", {}).get("latency", {}).get("iqm", None)
                    ul_latency = data.get("upload", {}).get("latency", {}).get("iqm", None)

                    # Bandwidth is in bytes per second: 1 byte/s = 8 / 1,000,000 Mbps
                    dl_mbps = round((dl_bytes_sec * 8) / 1000000.0, 2)
                    ul_mbps = round((ul_bytes_sec * 8) / 1000000.0, 2)

                    if dl_mbps > 0:
                        return {
                            "ping": round(float(ping_lat), 2) if ping_lat else None,
                            "jitter": round(float(jitter_lat), 2) if jitter_lat else None,
                            "download": dl_mbps,
                            "upload": ul_mbps,
                            "dl_latency": round(float(dl_latency), 2) if dl_latency else None,
                            "ul_latency": round(float(ul_latency), 2) if ul_latency else None,
                            "engine_type": "Ookla Native"
                        }
            except Exception as e:
                if debug:
                    print(f"{C.YELLOW}[DEBUG] Ookla native test attempt {attempt + 1} failed: {e}{C.RESET}")
                if attempt < retries:
                    exponential_backoff_delay(attempt)

    # 2. Fallback to python speedtest-cli
    for attempt in range(retries + 1):
        try:
            cmd = ["speedtest-cli", "--simple", "--secure"]
            if ip_version == "4":
                cmd.append("-4")
            elif ip_version == "6":
                cmd.append("-6")
            res = subprocess.run(cmd, capture_output=True, text=True, timeout=50)
            ping_m = re.search(r"Ping:\s*([0-9.]+)", res.stdout)
            dl_m = re.search(r"Download:\s*([0-9.]+)", res.stdout)
            ul_m = re.search(r"Upload:\s*([0-9.]+)", res.stdout)

            if dl_m:
                return {
                    "ping": float(ping_m.group(1)) if ping_m else None,
                    "jitter": None,
                    "download": float(dl_m.group(1)) if dl_m else None,
                    "upload": float(ul_m.group(1)) if ul_m else None,
                    "engine_type": "speedtest-cli"
                }
        except Exception as e:
            if debug:
                print(f"{C.YELLOW}[DEBUG] speedtest-cli attempt {attempt + 1}/{retries + 1} failed: {e}{C.RESET}")
            if attempt < retries:
                exponential_backoff_delay(attempt)
    return None


def get_fastcom(
    debug: bool = False,
    retries: int = MAX_RETRIES,
    timeout: int = DOWNLOAD_TIMEOUT,
    progress_callback: Optional[callable] = None,
    ip_version: Optional[str] = None
) -> Optional[Dict[str, float]]:
    """Fetches Fast.com download speed via adaptive multi-stream parallel downloads with IPv4/IPv6 support."""
    for attempt in range(retries + 1):
        try:
            html = make_http_request("https://fast.com", timeout=HTTP_TIMEOUT, debug=debug, ip_version=ip_version)
            if not html:
                raise ValueError("Failed to fetch fast.com homepage")

            js_path = JS_PATH_PATTERN.search(html)
            if not js_path:
                raise ValueError("JavaScript file not found")

            js_url = f"https://fast.com{js_path.group(1)}"
            js_content = make_http_request(js_url, timeout=HTTP_TIMEOUT, debug=debug, ip_version=ip_version)
            if not js_content:
                raise ValueError("Failed to fetch JavaScript")

            token = TOKEN_PATTERN.search(js_content)
            if not token:
                raise ValueError("Token not found in JavaScript")

            api_url = f"https://api.fast.com/netflix/speedtest/v2?https=true&token={token.group(1)}&urlCount=4"
            api_res = make_http_request(api_url, timeout=HTTP_TIMEOUT, debug=debug, ip_version=ip_version)
            if not api_res:
                raise ValueError("Failed to fetch API targets")

            data = json.loads(api_res)
            if not isinstance(data, dict):
                raise ValueError("Invalid API response format")

            targets = [item.get("url") for item in data.get("targets", []) if isinstance(item, dict) and "url" in item]
            if not targets:
                raise ValueError("No valid targets found")

            # Adaptive byte range (15MB chunk per stream for fast and accurate saturation)
            def download_stream(target_url):
                t0 = time.perf_counter()
                cmd = ["curl", "-s", "-L", "-A", USER_AGENT, "--connect-timeout", "4", "--max-time", str(timeout)]
                if ip_version == "4":
                    cmd.append("-4")
                elif ip_version == "6":
                    cmd.append("-6")
                cmd.extend(["-r", "0-15000000", "-w", "%{size_download}", "-o", "/dev/null", target_url])
                try:
                    res = subprocess.run(cmd, capture_output=True, text=True, timeout=timeout + 3)
                    t1 = time.perf_counter()
                    bytes_dl = int(float(res.stdout.strip() or 0))
                    return bytes_dl, max(0.001, t1 - t0)
                except Exception:
                    return 0, 0

            start_time = time.perf_counter()
            with ThreadPoolExecutor(max_workers=min(len(targets), 4)) as ex:
                futs = [ex.submit(download_stream, url) for url in targets]
                results = [f.result() for f in futs]
            elapsed = time.perf_counter() - start_time

            total_bytes = sum(r[0] for r in results)
            if elapsed > 0 and total_bytes > 0:
                mbps = (total_bytes * 8.0) / (elapsed * 1000000.0)
                if progress_callback:
                    progress_callback(f"{mbps:.1f} Mbps")
                return {"download": round(mbps, 2)}
        except Exception as e:
            if debug:
                print(f"{C.YELLOW}[DEBUG] Fast.com attempt {attempt + 1}/{retries + 1} failed: {e}{C.RESET}")
            if attempt < retries:
                exponential_backoff_delay(attempt)
    return None


def get_cloudflare(
    debug: bool = False,
    retries: int = MAX_RETRIES,
    timeout: int = DOWNLOAD_TIMEOUT,
    dl_ping_collector: Optional[List[float]] = None,
    ul_ping_collector: Optional[List[float]] = None,
    progress_callback: Optional[callable] = None,
    ip_version: Optional[str] = None
) -> Optional[Dict[str, float]]:
    """Runs Cloudflare CDN speed test with adaptive multi-stream download, upload, and directional bufferbloat."""
    for attempt in range(retries + 1):
        try:
            # 1. Download Test (4 parallel streams of 10MB chunks = 40MB total)
            down_url = "https://speed.cloudflare.com/__down?bytes=10000000"

            def dl_worker(url):
                t0 = time.perf_counter()
                cmd = ["curl", "-s", "-L", "-A", USER_AGENT, "--connect-timeout", "4", "--max-time", str(timeout)]
                if ip_version == "4":
                    cmd.append("-4")
                elif ip_version == "6":
                    cmd.append("-6")
                cmd.extend(["-w", "%{size_download}", "-o", "/dev/null", url])
                try:
                    res = subprocess.run(cmd, capture_output=True, text=True, timeout=timeout + 3)
                    t1 = time.perf_counter()
                    bytes_dl = int(float(res.stdout.strip() or 0))
                    return bytes_dl, max(0.001, t1 - t0)
                except Exception:
                    return 0, 0

            # Start DL ping monitoring if collector provided
            dl_stop = threading.Event()
            dl_ping_thread = None
            if dl_ping_collector is not None:
                dl_ping_thread = threading.Thread(target=ping_monitor, args=(dl_stop, dl_ping_collector, None, ip_version), daemon=True)
                dl_ping_thread.start()

            t_start_dl = time.perf_counter()
            with ThreadPoolExecutor(max_workers=DEFAULT_WORKERS) as ex:
                futs = [ex.submit(dl_worker, down_url) for _ in range(DEFAULT_WORKERS)]
                dl_results = [f.result() for f in futs]
            t_dl = time.perf_counter() - t_start_dl

            if dl_ping_thread:
                dl_stop.set()
                dl_ping_thread.join(timeout=0.4)

            total_dl_bytes = sum(r[0] for r in dl_results)
            dl_mbps = round((total_dl_bytes * 8.0) / (t_dl * 1000000.0), 2) if t_dl > 0 else 0.0
            if progress_callback:
                progress_callback(f"DL: {dl_mbps:.1f} Mbps")

            # 2. Upload Test (Upload 4MB payload across 2 parallel workers = 8MB total)
            up_url = "https://speed.cloudflare.com/__up"
            tmp = tempfile.NamedTemporaryFile(delete=False)
            tmp_path = tmp.name
            try:
                tmp.write(b"\x00" * (4 * 1024 * 1024))  # 4MB clean zero buffer
                tmp.close()

                def ul_worker(url, filepath):
                    t0 = time.perf_counter()
                    cmd = ["curl", "-s", "-L", "-A", USER_AGENT, "--connect-timeout", "4", "--max-time", str(timeout), "-X", "POST"]
                    if ip_version == "4":
                        cmd.append("-4")
                    elif ip_version == "6":
                        cmd.append("-6")
                    cmd.extend(["--data-binary", f"@{filepath}", "-w", "%{size_upload}", "-o", "/dev/null", url])
                    try:
                        res = subprocess.run(cmd, capture_output=True, text=True, timeout=timeout + 3)
                        t1 = time.perf_counter()
                        bytes_ul = int(float(res.stdout.strip() or 0))
                        return bytes_ul, max(0.001, t1 - t0)
                    except Exception:
                        return 0, 0

                # Start UL ping monitoring if collector provided
                ul_stop = threading.Event()
                ul_ping_thread = None
                if ul_ping_collector is not None:
                    ul_ping_thread = threading.Thread(target=ping_monitor, args=(ul_stop, ul_ping_collector, None, ip_version), daemon=True)
                    ul_ping_thread.start()

                t_start_ul = time.perf_counter()
                with ThreadPoolExecutor(max_workers=2) as ex:
                    futs_ul = [ex.submit(ul_worker, up_url, tmp_path) for _ in range(2)]
                    ul_results = [f.result() for f in futs_ul]
                t_ul = time.perf_counter() - t_start_ul

                if ul_ping_thread:
                    ul_stop.set()
                    ul_ping_thread.join(timeout=0.4)
            finally:
                if os.path.exists(tmp_path):
                    try:
                        os.unlink(tmp_path)
                    except OSError:
                        pass

            total_ul_bytes = sum(r[0] for r in ul_results)
            ul_mbps = round((total_ul_bytes * 8.0) / (t_ul * 1000000.0), 2) if t_ul > 0 else 0.0
            if progress_callback:
                progress_callback(f"DL: {dl_mbps:.1f} | UL: {ul_mbps:.1f} Mbps")

            if dl_mbps > 0:
                return {"download": dl_mbps, "upload": ul_mbps}
        except Exception as e:
            if debug:
                print(f"{C.YELLOW}[DEBUG] Cloudflare attempt {attempt + 1}/{retries + 1} failed: {e}{C.RESET}")
            if attempt < retries:
                exponential_backoff_delay(attempt)
    return None


def get_custom_speedtest(server_url: str, debug: bool = False, retries: int = MAX_RETRIES, timeout: int = DOWNLOAD_TIMEOUT, ip_version: Optional[str] = None) -> Optional[Dict[str, float]]:
    """Benchmark network throughput against a custom user-defined HTTP/HTTPS URL."""
    for attempt in range(retries + 1):
        try:
            t0 = time.perf_counter()
            cmd = ["curl", "-s", "-L", "-A", USER_AGENT, "--max-time", str(timeout)]
            if ip_version == "4":
                cmd.append("-4")
            elif ip_version == "6":
                cmd.append("-6")
            cmd.extend(["-w", "%{size_download}", "-o", "/dev/null", server_url])
            res = subprocess.run(cmd, capture_output=True, text=True, timeout=timeout + 2)
            t1 = time.perf_counter()
            bytes_dl = int(res.stdout.strip() or 0)
            elapsed = t1 - t0
            if elapsed > 0 and bytes_dl > 0:
                mbps = (bytes_dl * 8.0) / (elapsed * 1000000.0)
                return {"download": round(mbps, 2)}
        except Exception as e:
            if debug:
                print(f"{C.YELLOW}[DEBUG] Custom server test failed: {e}{C.RESET}")
            if attempt < retries:
                exponential_backoff_delay(attempt)
    return None


def ping_monitor(stop_event: threading.Event, ping_samples: List[float], host: Optional[str] = None, ip_version: Optional[str] = None):
    """Continuously measure ping latency during active transfers for bufferbloat analysis."""
    if not host:
        host = "2606:4700:4700::1111" if ip_version == "6" else "1.1.1.1"
    resolver = {"name": "Monitor", "ip": host, "port": 53}
    while not stop_event.is_set():
        lat = get_dns_latency(resolver, "google.com", timeout=2, debug=False)
        if lat is not None:
            ping_samples.append(lat)
        time.sleep(0.12)


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


def save_history_record(record_data: Dict[str, Any], debug: bool = False) -> None:
    """Append a benchmark record to ~/.speedtest_history.json."""
    try:
        history = []
        if os.path.exists(HISTORY_FILE):
            try:
                with open(HISTORY_FILE, "r") as f:
                    history = json.load(f)
            except Exception:
                history = []
        history.append(record_data)
        with open(HISTORY_FILE, "w") as f:
            json.dump(history, f, indent=2)
    except Exception as e:
        if debug:
            print(f"{C.YELLOW}[DEBUG] Failed to save history: {e}{C.RESET}")


def export_html_report(filepath: str, export_data: Dict[str, Any], debug: bool = False) -> bool:
    """Generates a state-of-the-art, interactive glassmorphism standalone HTML report dashboard."""
    try:
        ts = export_data.get("timestamp", "").replace("T", " ")[:19]
        ver = export_data.get("version", VERSION)
        net = export_data.get("network", {})
        geo = net.get("geo", {})
        adapter = net.get("adapter", {})
        stats = export_data.get("statistics", {})
        suitability = export_data.get("suitability", {})
        dns_rec = export_data.get("dns_recommendation", {})
        dns_data = export_data.get("dns", {})

        st_dl = stats.get("speedtest_download_mbps", {}).get("avg", 0.0)
        fast_dl = stats.get("fast_download_mbps", {}).get("avg", 0.0)
        cf_dl = stats.get("cloudflare_download_mbps", {}).get("avg", 0.0)
        custom_dl = stats.get("custom_download_mbps", {}).get("avg", 0.0)
        cf_ul = stats.get("cloudflare_upload_mbps", {}).get("avg", 0.0)
        st_ul = stats.get("speedtest_upload_mbps", {}).get("avg", 0.0)

        actual_max_dl = max(st_dl, fast_dl, cf_dl, custom_dl)
        actual_max_ul = max(st_ul, cf_ul)
        bar_max_dl = max(1.0, actual_max_dl)
        bar_max_ul = max(1.0, actual_max_ul)

        ping = stats.get("ping_ms", {}).get("avg", 0.0)
        jitter = stats.get("jitter_ms", 0.0)
        packet_loss = stats.get("packet_loss_pct", 0.0)
        bb = stats.get("bufferbloat", {})

        score = suitability.get("overall_score", 0.0)
        tier = suitability.get("speed_tier", "Standard Broadband")

        # Sparkline data from recent history if available
        recent_history: List[Dict[str, Any]] = []
        if os.path.exists(HISTORY_FILE):
            try:
                with open(HISTORY_FILE, "r") as f:
                    recent_history = json.load(f)[-10:]
            except Exception:
                pass

        history_rows = ""
        for h in recent_history:
            h_ts = h.get("timestamp", "").replace("T", " ")[:16]
            h_stats = h.get("statistics", {})
            h_dl = max(
                h_stats.get("speedtest_download_mbps", {}).get("avg", 0.0),
                h_stats.get("fast_download_mbps", {}).get("avg", 0.0),
                h_stats.get("cloudflare_download_mbps", {}).get("avg", 0.0),
                h_stats.get("custom_download_mbps", {}).get("avg", 0.0)
            )
            h_ping = h_stats.get("ping_ms", {}).get("avg", 0.0)
            h_bb = h_stats.get("bufferbloat", {}).get("grade", "N/A")
            h_score = h.get("suitability", {}).get("overall_score", "N/A")
            history_rows += f"<tr><td>{h_ts}</td><td><strong>{h_dl:.1f} Mbps</strong></td><td>{h_ping:.1f} ms</td><td><span class='badge'>{h_bb}</span></td><td><strong>{h_score}/100</strong></td></tr>"

        score_color = "#10b981" if score >= 85 else ("#06b6d4" if score >= 70 else ("#f59e0b" if score >= 50 else "#ef4444"))
        score_circumference = 314.16
        dash_offset = score_circumference - (score_circumference * (score / 100.0))

        raw_json_escaped = json.dumps(export_data).replace("</script>", "<\\/script>")

        html_content = f"""<!DOCTYPE html>
<html lang="en" data-theme="dark">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>Network Speed Benchmark Dashboard - {ts}</title>
    <link rel="preconnect" href="https://fonts.googleapis.com">
    <link rel="preconnect" href="https://fonts.gstatic.com" crossorigin>
    <link href="https://fonts.googleapis.com/css2?family=Outfit:wght@400;500;600;700;800;900&family=JetBrains+Mono:wght@400;500;600;700&display=swap" rel="stylesheet">
    <style>
        :root {{
            --bg-body: #050814;
            --bg-gradient: radial-gradient(circle at 15% 15%, #0f172a 0%, #030712 100%);
            --card-bg: rgba(17, 24, 39, 0.72);
            --card-border: rgba(255, 255, 255, 0.08);
            --card-hover-border: rgba(6, 182, 212, 0.4);
            --text-main: #f8fafc;
            --text-dim: #94a3b8;
            --accent-cyan: #06b6d4;
            --accent-green: #10b981;
            --accent-yellow: #f59e0b;
            --accent-purple: #8b5cf6;
            --accent-red: #ef4444;
            --gauge-track: #1e293b;
            --chip-bg: rgba(255, 255, 255, 0.05);
            --btn-bg: rgba(30, 41, 59, 0.8);
            --btn-hover: rgba(6, 182, 212, 0.2);
            --shadow-card: 0 10px 30px -10px rgba(0, 0, 0, 0.5);
        }}
        [data-theme="light"] {{
            --bg-body: #f8fafc;
            --bg-gradient: radial-gradient(circle at 15% 15%, #f1f5f9 0%, #e2e8f0 100%);
            --card-bg: rgba(255, 255, 255, 0.88);
            --card-border: rgba(148, 163, 184, 0.25);
            --card-hover-border: rgba(6, 182, 212, 0.6);
            --text-main: #0f172a;
            --text-dim: #64748b;
            --gauge-track: #e2e8f0;
            --chip-bg: rgba(15, 23, 42, 0.04);
            --btn-bg: rgba(255, 255, 255, 0.95);
            --btn-hover: rgba(6, 182, 212, 0.15);
            --shadow-card: 0 10px 25px -5px rgba(100, 116, 139, 0.15);
        }}
        * {{ box-sizing: border-box; transition: background-color 0.3s cubic-bezier(0.4, 0, 0.2, 1), border-color 0.3s ease, color 0.2s ease; }}
        body {{
            font-family: 'Outfit', -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, sans-serif;
            background: var(--bg-gradient);
            background-color: var(--bg-body);
            color: var(--text-main);
            margin: 0;
            padding: 32px 20px;
            min-height: 100vh;
            line-height: 1.5;
        }}
        code, .font-mono {{ font-family: 'JetBrains Mono', monospace; }}
        .container {{ max-width: 1180px; margin: 0 auto; }}
        .header {{
            display: flex;
            justify-content: space-between;
            align-items: center;
            border-bottom: 1px solid var(--card-border);
            padding-bottom: 24px;
            margin-bottom: 32px;
            flex-wrap: wrap;
            gap: 18px;
        }}
        .header-title h1 {{
            margin: 0;
            font-size: 32px;
            font-weight: 900;
            letter-spacing: -0.8px;
            background: linear-gradient(135deg, var(--accent-cyan), #38bdf8, var(--accent-purple));
            -webkit-background-clip: text;
            -webkit-text-fill-color: transparent;
        }}
        .header-title p {{ margin: 6px 0 0 0; color: var(--text-dim); font-size: 14px; font-weight: 500; }}
        .header-controls {{ display: flex; gap: 10px; align-items: center; flex-wrap: wrap; }}
        .btn {{
            background: var(--btn-bg);
            border: 1px solid var(--card-border);
            color: var(--text-main);
            padding: 9px 15px;
            border-radius: 10px;
            cursor: pointer;
            font-family: inherit;
            font-size: 13px;
            font-weight: 600;
            display: inline-flex;
            align-items: center;
            gap: 7px;
            box-shadow: 0 2px 5px rgba(0, 0, 0, 0.08);
        }}
        .btn:hover {{ border-color: var(--accent-cyan); color: var(--accent-cyan); background: var(--btn-hover); transform: translateY(-1px); }}
        .btn:active {{ transform: translateY(0); }}
        .grid {{
            display: grid;
            grid-template-columns: repeat(auto-fit, minmax(340px, 1fr));
            gap: 22px;
            margin-bottom: 26px;
        }}
        .card {{
            background: var(--card-bg);
            border: 1px solid var(--card-border);
            border-radius: 20px;
            padding: 26px;
            backdrop-filter: blur(16px);
            -webkit-backdrop-filter: blur(16px);
            box-shadow: var(--shadow-card);
            position: relative;
            overflow: hidden;
        }}
        .card:hover {{ border-color: var(--card-hover-border); }}
        .card-title {{
            font-size: 13px;
            text-transform: uppercase;
            letter-spacing: 1.4px;
            color: var(--text-dim);
            font-weight: 800;
            margin-bottom: 20px;
            display: flex;
            justify-content: space-between;
            align-items: center;
        }}
        .gauge-container {{
            display: flex;
            flex-direction: column;
            align-items: center;
            justify-content: center;
            padding: 10px 0 16px 0;
            position: relative;
        }}
        .svg-gauge {{ width: 160px; height: 160px; transform: rotate(-90deg); filter: drop-shadow(0 0 12px {score_color}44); }}
        .svg-gauge circle {{ fill: none; stroke-width: 10; stroke-linecap: round; }}
        .svg-gauge .bg-ring {{ stroke: var(--gauge-track); }}
        .svg-gauge .val-ring {{
            stroke: {score_color};
            stroke-dasharray: 314.16;
            stroke-dashoffset: {dash_offset};
            transition: stroke-dashoffset 1.4s ease-out;
        }}
        .gauge-center {{
            position: absolute;
            top: 50%;
            left: 50%;
            transform: translate(-50%, -50%);
            display: flex;
            flex-direction: column;
            align-items: center;
            justify-content: center;
            pointer-events: none;
        }}
        .score-val {{ font-size: 38px; font-weight: 900; line-height: 1; color: {score_color}; }}
        .score-lbl {{ font-size: 11px; text-transform: uppercase; letter-spacing: 1px; color: var(--text-dim); margin-top: 4px; font-weight: 700; }}
        .info-row {{
            display: flex;
            justify-content: space-between;
            align-items: center;
            padding: 9px 0;
            border-bottom: 1px solid var(--card-border);
            font-size: 14px;
        }}
        .info-row:last-child {{ border-bottom: none; }}
        .info-label {{ color: var(--text-dim); font-weight: 500; }}
        .info-val {{ font-weight: 600; text-align: right; }}
        .badge {{
            display: inline-block;
            padding: 4px 11px;
            border-radius: 9999px;
            font-size: 12px;
            font-weight: 700;
            background: rgba(6, 182, 212, 0.14);
            color: var(--accent-cyan);
            border: 1px solid rgba(6, 182, 212, 0.3);
            letter-spacing: 0.2px;
        }}
        .badge-green {{ background: rgba(16, 185, 129, 0.15); color: var(--accent-green); border-color: rgba(16, 185, 129, 0.35); }}
        .badge-yellow {{ background: rgba(245, 158, 11, 0.15); color: var(--accent-yellow); border-color: rgba(245, 158, 11, 0.35); }}
        .badge-purple {{ background: rgba(139, 92, 246, 0.15); color: var(--accent-purple); border-color: rgba(139, 92, 246, 0.35); }}
        .badge-red {{ background: rgba(239, 68, 68, 0.15); color: var(--accent-red); border-color: rgba(239, 68, 68, 0.35); }}
        .bar-container {{ margin-top: 10px; }}
        .bar-label {{ display: flex; justify-content: space-between; font-size: 13px; margin-bottom: 6px; font-weight: 600; }}
        .bar-bg {{ background: var(--gauge-track); height: 16px; border-radius: 8px; overflow: hidden; margin-bottom: 16px; }}
        .bar-fill {{ height: 100%; border-radius: 8px; transition: width 1.2s cubic-bezier(0.4, 0, 0.2, 1); }}
        .bb-grid {{
            display: grid;
            grid-template-columns: repeat(3, 1fr);
            gap: 12px;
            margin: 16px 0;
            text-align: center;
        }}
        .bb-box {{
            background: var(--chip-bg);
            border: 1px solid var(--card-border);
            border-radius: 12px;
            padding: 12px 8px;
        }}
        .bb-box-title {{ font-size: 11px; text-transform: uppercase; color: var(--text-dim); font-weight: 700; margin-bottom: 4px; }}
        .bb-box-val {{ font-size: 18px; font-weight: 800; color: var(--text-main); }}
        .bb-box-badge {{ margin-top: 6px; }}
        table {{ width: 100%; border-collapse: collapse; font-size: 13px; margin-top: 10px; }}
        th, td {{ padding: 11px 12px; text-align: left; border-bottom: 1px solid var(--card-border); }}
        th {{ color: var(--text-dim); text-transform: uppercase; font-size: 11px; letter-spacing: 0.8px; font-weight: 800; }}
        .copy-ip-btn {{
            background: none;
            border: none;
            color: var(--text-dim);
            cursor: pointer;
            padding: 2px 6px;
            border-radius: 4px;
            font-size: 11px;
            margin-left: 6px;
        }}
        .copy-ip-btn:hover {{ background: var(--chip-bg); color: var(--accent-cyan); }}
        #toast {{
            position: fixed;
            bottom: 24px;
            right: 24px;
            background: var(--accent-cyan);
            color: #030712;
            padding: 10px 18px;
            border-radius: 10px;
            font-size: 13px;
            font-weight: 700;
            box-shadow: 0 10px 25px rgba(0,0,0,0.3);
            display: none;
            z-index: 1000;
        }}
        @media print {{
            body {{ background: #fff !important; color: #000 !important; padding: 0 !important; }}
            .header-controls, .btn, .copy-ip-btn, #toast {{ display: none !important; }}
            .card {{ border: 1px solid #ccc !important; box-shadow: none !important; background: #fff !important; page-break-inside: avoid; }}
            .score-val, .header-title h1 {{ color: #000 !important; -webkit-text-fill-color: #000 !important; }}
        }}
        @media (max-width: 680px) {{
            .grid {{ grid-template-columns: 1fr; }}
            .bb-grid {{ grid-template-columns: 1fr; }}
            .header {{ flex-direction: column; align-items: flex-start; }}
        }}
    </style>
</head>
<body>
    <div id="toast">Copied to clipboard!</div>
    <div class="container">
        <div class="header">
            <div class="header-title">
                <h1>Network Benchmark Report</h1>
                <p>Generated: <strong>{ts}</strong> | Tool: <strong>v{ver}</strong> | Host ISP: <strong>{geo.get("isp", "Local Network")}</strong></p>
            </div>
            <div class="header-controls">
                <button class="btn" onclick="toggleTheme()">🌓 Theme</button>
                <button class="btn" onclick="copySummary()">📋 Copy Summary</button>
                <button class="btn" onclick="downloadJSON()">💾 Export JSON</button>
                <button class="btn" onclick="window.print()">🖨️ Print / PDF</button>
            </div>
        </div>

        <div class="grid">
            <!-- Card 1: Network Quality Score & Tier -->
            <div class="card">
                <div class="card-title">Network Quality Score <span class="badge badge-green">{tier}</span></div>
                <div class="gauge-container">
                    <svg class="svg-gauge" viewBox="0 0 120 120">
                        <circle class="bg-ring" cx="60" cy="60" r="50"></circle>
                        <circle class="val-ring" cx="60" cy="60" r="50"></circle>
                    </svg>
                    <div class="gauge-center">
                        <div class="score-val">{score}</div>
                        <div class="score-lbl">out of 100</div>
                    </div>
                </div>
                <div class="info-row"><span class="info-label">🎮 Gaming Esports:</span><span class="info-val">{suitability.get("gaming", {}).get("status", "N/A")}</span></div>
                <div class="info-row"><span class="info-label">🎥 4K/8K Streaming:</span><span class="info-val">{suitability.get("streaming", {}).get("status", "N/A")}</span></div>
                <div class="info-row"><span class="info-label">📹 HD Video Calls:</span><span class="info-val">{suitability.get("video_call", {}).get("status", "N/A")}</span></div>
            </div>

            <!-- Card 2: Directional Bufferbloat Deep-Dive -->
            <div class="card">
                <div class="card-title">Directional Bufferbloat <span class="badge badge-purple">Grade: {bb.get("grade", "N/A")}</span></div>
                <div class="bb-grid">
                    <div class="bb-box">
                        <div class="bb-box-title">Idle Baseline</div>
                        <div class="bb-box-val" style="color:var(--accent-yellow)">{bb.get("unloaded_ping_ms", ping):.1f} <small style="font-size:12px">ms</small></div>
                        <div class="bb-box-badge"><span class="badge">Reference</span></div>
                    </div>
                    <div class="bb-box">
                        <div class="bb-box-title">DL Active (Down)</div>
                        <div class="bb-box-val">{bb.get("download_loaded_ping_ms", ping):.1f} <small style="font-size:12px">ms</small></div>
                        <div class="bb-box-badge"><span class="badge badge-green">+{bb.get("download_delta_ms", 0)}ms ({bb.get("download_grade", "N/A")})</span></div>
                    </div>
                    <div class="bb-box">
                        <div class="bb-box-title">UL Active (Up)</div>
                        <div class="bb-box-val">{bb.get("upload_loaded_ping_ms", ping):.1f} <small style="font-size:12px">ms</small></div>
                        <div class="bb-box-badge"><span class="badge badge-yellow">+{bb.get("upload_delta_ms", 0)}ms ({bb.get("upload_grade", "N/A")})</span></div>
                    </div>
                </div>
                <div class="info-row"><span class="info-label">Peak Loaded Spike:</span><span class="info-val" style="color:var(--accent-cyan)">+{bb.get("delta_ms", 0)} ms</span></div>
                <div class="info-row"><span class="info-label">Network Jitter:</span><span class="info-val">{jitter} ms</span></div>
                <div class="info-row"><span class="info-label">ICMP Packet Loss:</span><span class="info-val" style="color:{'var(--accent-green)' if packet_loss == 0 else 'var(--accent-red)'}">{packet_loss}%</span></div>
            </div>

            <!-- Card 3: Network Adapter & Infrastructure -->
            <div class="card">
                <div class="card-title">Network & Hardware Diagnostics</div>
                <div class="info-row"><span class="info-label">Public WAN IP:</span><span class="info-val font-mono">{geo.get("ip", "N/A")}</span></div>
                {f'<div class="info-row"><span class="info-label">Public IPv6:</span><span class="info-val font-mono">{geo.get("ipv6")}</span></div>' if geo.get("ipv6") and geo.get("ipv6") != "Unavailable" else ''}
                <div class="info-row"><span class="info-label">ISP & Location:</span><span class="info-val">{geo.get("isp", "Unknown")} ({geo.get("city", "")}, {geo.get("country", "")})</span></div>
                <div class="info-row"><span class="info-label">Interface:</span><span class="info-val font-mono">{adapter.get("interface", "Unknown")} ({adapter.get("interface_type", "Ethernet")})</span></div>
                <div class="info-row"><span class="info-label">Hardware Link Speed:</span><span class="info-val" style="color:var(--accent-green)">{adapter.get("link_speed", "N/A")}</span></div>
                {f'<div class="info-row"><span class="info-label">Wi-Fi Network:</span><span class="info-val">{adapter.get("wifi_ssid")} ({adapter.get("wifi_signal")})</span></div>' if adapter.get("wifi_ssid") not in ("N/A (Wired/Unknown)", "N/A") else ''}
                {f'<div class="info-row"><span class="info-label">Wi-Fi Band:</span><span class="info-val">{adapter.get("wifi_frequency")}</span></div>' if adapter.get("wifi_frequency") not in ("N/A", "") else ''}
                <div class="info-row"><span class="info-label">Local Gateway IP:</span><span class="info-val font-mono">{adapter.get("gateway", "N/A")}</span></div>
                <div class="info-row"><span class="info-label">Interface MTU:</span><span class="info-val font-mono">{adapter.get("mtu", "1500")}</span></div>
            </div>
        </div>

        <!-- Multi-Engine Bandwidth Comparisons -->
        <div class="card" style="margin-bottom: 26px;">
            <div class="card-title">Multi-Engine Bandwidth Benchmarks (Mbps)</div>
            <div class="bar-container">
                {f'''
                <div class="bar-label"><span>Ookla Speedtest (Download)</span><span style="color:var(--accent-green)">{st_dl:.2f} Mbps</span></div>
                <div class="bar-bg"><div class="bar-fill" style="width:{(st_dl/bar_max_dl)*100}%; background:linear-gradient(90deg, #10b981, #34d399)"></div></div>
                ''' if st_dl > 0 else ''}

                {f'''
                <div class="bar-label"><span>Fast.com / Netflix CDN (Download)</span><span style="color:var(--accent-cyan)">{fast_dl:.2f} Mbps</span></div>
                <div class="bar-bg"><div class="bar-fill" style="width:{(fast_dl/bar_max_dl)*100}%; background:linear-gradient(90deg, #06b6d4, #38bdf8)"></div></div>
                ''' if fast_dl > 0 else ''}

                {f'''
                <div class="bar-label"><span>Cloudflare CDN (Download)</span><span style="color:var(--accent-purple)">{cf_dl:.2f} Mbps</span></div>
                <div class="bar-bg"><div class="bar-fill" style="width:{(cf_dl/bar_max_dl)*100}%; background:linear-gradient(90deg, #8b5cf6, #a78bfa)"></div></div>
                ''' if cf_dl > 0 else ''}

                {f'''
                <div class="bar-label"><span>Custom Endpoint (Download)</span><span style="color:var(--accent-cyan)">{custom_dl:.2f} Mbps</span></div>
                <div class="bar-bg"><div class="bar-fill" style="width:{(custom_dl/bar_max_dl)*100}%; background:linear-gradient(90deg, #0284c7, #38bdf8)"></div></div>
                ''' if custom_dl > 0 else ''}

                {f'''
                <div class="bar-label"><span>Cloudflare CDN (Upload)</span><span style="color:var(--accent-yellow)">{cf_ul:.2f} Mbps</span></div>
                <div class="bar-bg"><div class="bar-fill" style="width:{(cf_ul/bar_max_ul)*100}%; background:linear-gradient(90deg, #f59e0b, #fbbf24)"></div></div>
                ''' if cf_ul > 0 else ''}

                {f'''
                <div class="bar-label"><span>Ookla Speedtest (Upload)</span><span style="color:var(--accent-yellow)">{st_ul:.2f} Mbps</span></div>
                <div class="bar-bg"><div class="bar-fill" style="width:{(st_ul/bar_max_ul)*100}%; background:linear-gradient(90deg, #d97706, #f59e0b)"></div></div>
                ''' if st_ul > 0 else ''}
            </div>
        </div>

        {f'''
        <!-- DNS Resolution Leaderboard & Profiles -->
        <div class="card" style="margin-bottom: 26px;">
            <div class="card-title">DNS Resolution Leaderboard & Latency Ranking</div>
            <table>
                <thead>
                    <tr><th>Rank</th><th>Resolver Name</th><th>IP Address</th><th>Avg Latency</th><th>Category / Best For</th></tr>
                </thead>
                <tbody>
                    {''.join([f"<tr><td><strong>{'🥇 1' if item['rank']==1 else ('🥈 2' if item['rank']==2 else ('🥉 3' if item['rank']==3 else f'#{item['rank']}'))}</strong></td><td><strong>{item['name']}</strong></td><td><code class='font-mono'>{item['ip']}</code><button class='copy-ip-btn' onclick='copyText(\"{item['ip']}\")'>📋</button></td><td style='color:var(--accent-green)'><strong>{item['latency_ms']:.2f} ms</strong></td><td><span class='badge'>{item['category']}</span></td></tr>" for item in dns_rec.get("leaderboard", [])])}
                </tbody>
            </table>

            <div style="background: rgba(139, 92, 246, 0.08); border: 1px solid rgba(139, 92, 246, 0.35); border-radius: 16px; padding: 20px; margin-top: 24px;">
                <div style="font-weight: 800; font-size: 16px; margin-bottom: 8px; color: var(--accent-purple);">
                    🏆 Recommended DNS Configurations for Your Network
                </div>
                <p style="margin: 0 0 16px 0; color: var(--text-dim); font-size: 14px;">{dns_rec.get("status_message")}</p>
                <div style="display: grid; grid-template-columns: repeat(auto-fit, minmax(260px, 1fr)); gap: 14px;">
                    <div style="background: var(--card-bg); border: 1px solid rgba(139, 92, 246, 0.4); padding: 16px; border-radius: 12px;">
                        <strong style="color:var(--accent-purple)">🚀 Best for Speed & Privacy</strong><br>
                        <strong>{dns_rec.get('profiles', {}).get('best_speed_privacy', {}).get('name', 'Cloudflare')}</strong><br>
                        <small style="color:var(--text-dim)">Primary: <code class="font-mono">{dns_rec.get('profiles', {}).get('best_speed_privacy', {}).get('primary')}</code> <button class="copy-ip-btn" onclick="copyText('{dns_rec.get('profiles', {}).get('best_speed_privacy', {}).get('primary')}')">📋</button></small><br>
                        <small style="color:var(--text-dim)">Secondary: <code class="font-mono">{dns_rec.get('profiles', {}).get('best_speed_privacy', {}).get('secondary')}</code></small><br>
                        <small style="color:var(--text-dim)">IPv6: <code class="font-mono">{dns_rec.get('profiles', {}).get('best_speed_privacy', {}).get('ipv6_primary')}</code></small>
                    </div>
                    <div style="background: var(--card-bg); border: 1px solid rgba(16, 185, 129, 0.4); padding: 16px; border-radius: 12px;">
                        <strong style="color:var(--accent-green)">🛡️ Best for Security (Threat Block)</strong><br>
                        <strong>Quad9</strong><br>
                        <small style="color:var(--text-dim)">Primary: <code class="font-mono">{dns_rec.get('profiles', {}).get('best_security', {}).get('primary', '9.9.9.9')}</code> <button class="copy-ip-btn" onclick="copyText('{dns_rec.get('profiles', {}).get('best_security', {}).get('primary', '9.9.9.9')}')">📋</button></small><br>
                        <small style="color:var(--text-dim)">Secondary: <code class="font-mono">{dns_rec.get('profiles', {}).get('best_security', {}).get('secondary', '149.112.112.112')}</code></small><br>
                        <small style="color:var(--text-dim)">IPv6: <code class="font-mono">2620:fe::fe</code></small>
                    </div>
                    <div style="background: var(--card-bg); border: 1px solid rgba(6, 182, 212, 0.4); padding: 16px; border-radius: 12px;">
                        <strong style="color:var(--accent-cyan)">🚫 Best for Ad & Tracker Blocking</strong><br>
                        <strong>AdGuard DNS</strong><br>
                        <small style="color:var(--text-dim)">Primary: <code class="font-mono">{dns_rec.get('profiles', {}).get('best_adblocking', {}).get('primary', '94.140.14.14')}</code> <button class="copy-ip-btn" onclick="copyText('{dns_rec.get('profiles', {}).get('best_adblocking', {}).get('primary', '94.140.14.14')}')">📋</button></small><br>
                        <small style="color:var(--text-dim)">Secondary: <code class="font-mono">{dns_rec.get('profiles', {}).get('best_adblocking', {}).get('secondary', '94.140.15.15')}</code></small><br>
                        <small style="color:var(--text-dim)">IPv6: <code class="font-mono">2a10:50c0::ad1:ff</code></small>
                    </div>
                    <div style="background: var(--card-bg); border: 1px solid rgba(245, 158, 11, 0.4); padding: 16px; border-radius: 12px;">
                        <strong style="color:var(--accent-yellow)">🌐 Best for Anycast Reliability</strong><br>
                        <strong>Google Public DNS</strong><br>
                        <small style="color:var(--text-dim)">Primary: <code class="font-mono">{dns_rec.get('profiles', {}).get('best_reliability', {}).get('primary', '8.8.8.8')}</code> <button class="copy-ip-btn" onclick="copyText('{dns_rec.get('profiles', {}).get('best_reliability', {}).get('primary', '8.8.8.8')}')">📋</button></small><br>
                        <small style="color:var(--text-dim)">Secondary: <code class="font-mono">{dns_rec.get('profiles', {}).get('best_reliability', {}).get('secondary', '8.8.4.4')}</code></small><br>
                        <small style="color:var(--text-dim)">IPv6: <code class="font-mono">2001:4860:4860::8888</code></small>
                    </div>
                </div>
            </div>
        </div>
        ''' if dns_rec else ''}

        {f'''
        <div class="card" style="margin-top: 26px;">
            <div class="card-title">Recent Historical Benchmark Runs</div>
            <table>
                <thead>
                    <tr><th>Date / Time</th><th>Max Download</th><th>Ping</th><th>Bufferbloat</th><th>Quality Score</th></tr>
                </thead>
                <tbody>{history_rows}</tbody>
            </table>
        </div>
        ''' if history_rows else ''}
    </div>

    <script>
        const rawBenchmarkData = {raw_json_escaped};

        function showToast(msg) {{
            const t = document.getElementById('toast');
            t.innerText = msg;
            t.style.display = 'block';
            setTimeout(() => {{ t.style.display = 'none'; }}, 2200);
        }}

        function copyText(txt) {{
            navigator.clipboard.writeText(txt).then(() => showToast('Copied: ' + txt));
        }}

        function toggleTheme() {{
            const current = document.documentElement.getAttribute('data-theme');
            const next = current === 'light' ? 'dark' : 'light';
            document.documentElement.setAttribute('data-theme', next);
            try {{ localStorage.setItem('speedtest_theme', next); }} catch(e) {{}}
            showToast('Switched to ' + next + ' theme');
        }}
        try {{
            const saved = localStorage.getItem('speedtest_theme');
            if (saved) document.documentElement.setAttribute('data-theme', saved);
        }} catch(e) {{}}

        function copySummary() {{
            const ulStr = "{f'{actual_max_ul:.2f} Mbps' if actual_max_ul > 0 else 'N/A'}";
            const summary = `🚀 Network Speed Benchmark Report\\n📅 Date: {ts}\\n⚡ Max Download: {actual_max_dl:.2f} Mbps | Upload: ${{ulStr}}\\n📶 Ping: {ping} ms | Jitter: {jitter} ms | Loss: {packet_loss}%\\n🛡️ Bufferbloat: {bb.get("grade", "N/A")} (+{bb.get("delta_ms", 0)}ms)\\n⭐ Quality Score: {score}/100 ({tier})`;
            navigator.clipboard.writeText(summary).then(() => showToast('Summary copied to clipboard!'));
        }}

        function downloadJSON() {{
            const dataStr = "data:text/json;charset=utf-8," + encodeURIComponent(JSON.stringify(rawBenchmarkData, null, 2));
            const dlAnchor = document.createElement('a');
            dlAnchor.setAttribute("href", dataStr);
            dlAnchor.setAttribute("download", `speedtest_report_${{new Date().toISOString().slice(0,10)}}.json`);
            document.body.appendChild(dlAnchor);
            dlAnchor.click();
            dlAnchor.remove();
            showToast('JSON report downloaded');
        }}
    </script>
</body>
</html>
"""
        with open(filepath, "w") as f:
            f.write(html_content)
        return True
    except Exception as e:
        if debug:
            print(f"{C.YELLOW}[DEBUG] Failed to export HTML report: {e}{C.RESET}")
        return False


def export_markdown_report(filepath: str, export_data: Dict[str, Any], debug: bool = False) -> bool:
    """Generates a structured GitHub-flavored Markdown report."""
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
        custom_dl = stats.get("custom_download_mbps", {}).get("avg", 0.0)
        cf_ul = stats.get("cloudflare_upload_mbps", {}).get("avg", 0.0)
        st_ul = stats.get("speedtest_upload_mbps", {}).get("avg", 0.0)

        ping = stats.get("ping_ms", {}).get("avg", 0.0)
        jitter = stats.get("jitter_ms", 0.0)
        packet_loss = stats.get("packet_loss_pct", 0.0)
        bb = stats.get("bufferbloat", {})

        md = f"""# Network Speed Benchmark Report

- **Date / Time:** `{ts}`
- **Tool Version:** `v{ver}`
- **Public IP (WAN):** `{geo.get("ip", "N/A")}` ({geo.get("isp", "Unknown")})
- **Speed Tier:** **{suitability.get("speed_tier", "N/A")}**
- **Quality Score:** **{suitability.get("overall_score", "N/A")}/100**

---

## ⚡ Bandwidth Speeds

| Engine | Download (Mbps) | Upload (Mbps) |
| :--- | :--- | :--- |
| **Ookla Speedtest** | {st_dl:.2f} Mbps | {f'{st_ul:.2f} Mbps' if st_ul > 0 else 'N/A'} |
| **Fast.com (Netflix)** | {fast_dl:.2f} Mbps | N/A |
| **Cloudflare CDN** | {cf_dl:.2f} Mbps | {f'{cf_ul:.2f} Mbps' if cf_ul > 0 else 'N/A'} |
{f'| **Custom Endpoint** | {custom_dl:.2f} Mbps | N/A |' if custom_dl > 0 else ''}

---

## 📶 Latency, Stability & Directional Bufferbloat

| Metric | Result |
| :--- | :--- |
| **Idle Baseline Ping** | `{bb.get("unloaded_ping_ms", ping)} ms` |
| **Download Active Ping** | `{bb.get("download_loaded_ping_ms", ping)} ms` (+{bb.get("download_delta_ms", 0)} ms, **Grade: {bb.get("download_grade", "N/A")}**) |
| **Upload Active Ping** | `{bb.get("upload_loaded_ping_ms", ping)} ms` (+{bb.get("upload_delta_ms", 0)} ms, **Grade: {bb.get("upload_grade", "N/A")}**) |
| **Composite Bufferbloat** | **{bb.get("grade", "N/A")}** (+{bb.get("delta_ms", 0)} ms loaded spike) |
| **Network Jitter** | `{jitter} ms` |
| **Packet Loss** | `{packet_loss}%` |

---

## 🖥️ Network Hardware & Diagnostics

- **Interface:** `{adapter.get("interface", "Unknown")}` ({adapter.get("interface_type", "Ethernet")})
- **Link Speed:** `{adapter.get("link_speed", "N/A")}`
- **Gateway IP:** `{adapter.get("gateway", "N/A")}`
- **Interface MTU:** `{adapter.get("mtu", "1500")}`
{f'- **Wi-Fi SSID & Signal:** `{adapter.get("wifi_ssid")}` ({adapter.get("wifi_signal")})' if adapter.get("wifi_ssid") not in ("N/A (Wired/Unknown)", "N/A") else ''}
{f'- **Wi-Fi Frequency:** `{adapter.get("wifi_frequency")}`' if adapter.get("wifi_frequency") not in ("N/A", "") else ''}

---

## 🎮 Real-World Readiness

- **Gaming:** {suitability.get("gaming", {}).get("status", "N/A")} ({suitability.get("gaming", {}).get("score", 0)}/100)
- **4K/8K Streaming:** {suitability.get("streaming", {}).get("status", "N/A")} ({suitability.get("streaming", {}).get("score", 0)}/100)
- **Video Calls:** {suitability.get("video_call", {}).get("status", "N/A")} ({suitability.get("video_call", {}).get("score", 0)}/100)

---

## 💡 DNS Resolution Leaderboard & Recommendations

{f"""| Rank | Resolver | IP Address | Latency | Category / Best For |
| :---: | :--- | :--- | :---: | :--- |
""" + "".join([f"| {'🥇 1' if item['rank']==1 else ('🥈 2' if item['rank']==2 else ('🥉 3' if item['rank']==3 else f'#{item['rank']}'))} | **{item['name']}** | `{item['ip']}` | **{item['latency_ms']:.2f} ms** | {item['category']} |\n" for item in dns_rec.get("leaderboard", [])]) + f"""
### 🏆 Recommended Profiles for Your Network:
- **🚀 Best for Speed & Privacy:** **{dns_rec.get('profiles', {}).get('best_speed_privacy', {}).get('name', 'Cloudflare')}** (Primary: `{dns_rec.get('profiles', {}).get('best_speed_privacy', {}).get('primary')}`, Secondary: `{dns_rec.get('profiles', {}).get('best_speed_privacy', {}).get('secondary')}` | IPv6: `{dns_rec.get('profiles', {}).get('best_speed_privacy', {}).get('ipv6_primary')}`)
- **🛡️ Best for Security & Threat Blocking:** **Quad9** (Primary: `{dns_rec.get('profiles', {}).get('best_security', {}).get('primary', '9.9.9.9')}`, Secondary: `{dns_rec.get('profiles', {}).get('best_security', {}).get('secondary', '149.112.112.112')}` | IPv6: `2620:fe::fe`)
- **🚫 Best for Ad & Tracker Blocking:** **AdGuard** (Primary: `{dns_rec.get('profiles', {}).get('best_adblocking', {}).get('primary', '94.140.14.14')}`, Secondary: `{dns_rec.get('profiles', {}).get('best_adblocking', {}).get('secondary', '94.140.15.15')}` | IPv6: `2a10:50c0::ad1:ff`)
- **🌐 Best for Anycast Reliability:** **Google** (Primary: `{dns_rec.get('profiles', {}).get('best_reliability', {}).get('primary', '8.8.8.8')}`, Secondary: `{dns_rec.get('profiles', {}).get('best_reliability', {}).get('secondary', '8.8.4.4')}` | IPv6: `2001:4860:4860::8888`)
- **⚡ Status:** {dns_rec.get("status_message")}
""" if dns_rec else "- *DNS resolution benchmarking skipped.*"}

---
*Report generated by Network Speed Benchmark Tool v{ver}*
"""
        with open(filepath, "w") as f:
            f.write(md)
        return True
    except Exception as e:
        if debug:
            print(f"{C.YELLOW}[DEBUG] Failed to write Markdown report: {e}{C.RESET}")
        return False


def open_browser_report(filepath: str) -> None:
    """Automatically open exported HTML report in default web browser."""
    try:
        abs_path = os.path.abspath(filepath)
        if sys.platform == "darwin":
            subprocess.run(["open", abs_path], check=False)
        elif os.name == "posix":
            subprocess.run(["xdg-open", abs_path], check=False)
    except Exception:
        pass


def display_history(clear: bool = False, no_color: bool = False, show_graph: bool = True, inline: bool = False) -> int:
    """Displays formatted historical benchmark trends and sparkline graphs."""
    if no_color:
        C.disable()
    if clear:
        if os.path.exists(HISTORY_FILE):
            os.remove(HISTORY_FILE)
            print(f"{C.GREEN}[✔] Speedtest benchmark history cleared.{C.RESET}")
        else:
            print(f"{C.YELLOW}[i] No history file found to clear.{C.RESET}")
        return 0

    if not os.path.exists(HISTORY_FILE):
        if inline:
            print(f" {C.DIM}[i] No prior benchmark history found yet. Results from this run will be saved.{C.RESET}\n")
        else:
            print(f"{C.YELLOW}[i] No benchmark history found. Run a speed test first!{C.RESET}")
        return 0

    try:
        with open(HISTORY_FILE, "r") as f:
            history = json.load(f)
    except Exception as e:
        if inline:
            print(f" {C.YELLOW}[i] Could not read prior history file: {e}{C.RESET}\n")
        else:
            print(f"{C.RED}[!] Failed to read history file: {e}{C.RESET}")
        return 1

    if not history:
        if inline:
            print(f" {C.DIM}[i] Benchmark history is currently empty.{C.RESET}\n")
        else:
            print(f"{C.YELLOW}[i] Benchmark history is empty.{C.RESET}")
        return 0

    w = 88
    top_bar = "═" * w
    h_line = "─" * w
    title = "PRIOR BENCHMARK HISTORY & TRENDS" if inline else "HISTORICAL BENCHMARK LOGS"
    print(f"\n{C.MAGENTA}{C.BOLD}{top_bar}{C.RESET}")
    print(f"{C.MAGENTA}{C.BOLD}{title:^{w}}{C.RESET}")
    print(f"{C.MAGENTA}{C.BOLD}{top_bar}{C.RESET}")
    print(f"{C.BOLD}  Date/Time          ISP / Interface   Ookla DL   Fast DL   CF DL     Ping     Bufferbloat  Score{C.RESET}")
    print(f"{C.DIM}  {h_line[:86]}{C.RESET}")

    ookla_dls, fast_dls, cf_dls, pings, scores = [], [], [], [], []

    for entry in history[-15:]:
        dt = entry.get("timestamp", "").replace("T", " ")[:16]
        net = entry.get("network", {})
        isp = net.get("geo", {}).get("isp", net.get("isp", "Unknown"))
        if len(isp) > 12:
            isp = isp[:10] + ".."
        iface = net.get("adapter", {}).get("interface", "")
        if_info = f"{isp} ({iface})" if iface else isp

        stats = entry.get("statistics", {})
        st_dl = stats.get("speedtest_download_mbps", {}).get("avg", 0.0)
        fast_dl = stats.get("fast_download_mbps", {}).get("avg", 0.0)
        cf_dl = stats.get("cloudflare_download_mbps", {}).get("avg", 0.0)
        ping = stats.get("ping_ms", {}).get("avg", 0.0)
        bb = stats.get("bufferbloat", {})
        bb_str = f"{bb.get('grade', 'N/A')} (+{bb.get('delta_ms', 0)}ms)" if bb else "N/A"
        score = entry.get("suitability", {}).get("overall_score", 0.0)

        if st_dl:
            ookla_dls.append(st_dl)
        if fast_dl:
            fast_dls.append(fast_dl)
        if cf_dl:
            cf_dls.append(cf_dl)
        if ping:
            pings.append(ping)
        if score:
            scores.append(score)

        st_str = f"{st_dl:.1f} M" if st_dl else "N/A"
        fast_str = f"{fast_dl:.1f} M" if fast_dl else "N/A"
        cf_str = f"{cf_dl:.1f} M" if cf_dl else "N/A"
        ping_str = f"{ping:.1f} ms" if ping else "N/A"
        score_str = f"{score:.0f}/100" if score else "N/A"

        print(f"  {dt:<18} {if_info:<17} {st_str:<10} {fast_str:<9} {cf_str:<9} {ping_str:<8} {bb_str:<12} {score_str}")

    print(f"{C.MAGENTA}{C.BOLD}{top_bar}{C.RESET}")
    print(f"{C.BOLD} Overall Historical Averages ({len(history)} total runs):{C.RESET}")
    st_avg = round(sum(ookla_dls) / len(ookla_dls), 2) if ookla_dls else 0.0
    fast_avg = round(sum(fast_dls) / len(fast_dls), 2) if fast_dls else 0.0
    cf_avg = round(sum(cf_dls) / len(cf_dls), 2) if cf_dls else 0.0
    ping_avg = round(sum(pings) / len(pings), 2) if pings else 0.0
    score_avg = round(sum(scores) / len(scores), 1) if scores else 0.0

    print(f"  Ookla DL: {C.GREEN}{st_avg} Mbps{C.RESET} | Fast DL: {C.GREEN}{fast_avg} Mbps{C.RESET} | Cloudflare DL: {C.GREEN}{cf_avg} Mbps{C.RESET} | Ping: {C.YELLOW}{ping_avg} ms{C.RESET} | Score: {C.CYAN}{score_avg}/100{C.RESET}")

    if show_graph and (cf_dls or ookla_dls or fast_dls):
        all_speeds = [max(entry.get("statistics", {}).get("cloudflare_download_mbps", {}).get("avg", 0.0),
                          entry.get("statistics", {}).get("speedtest_download_mbps", {}).get("avg", 0.0),
                          entry.get("statistics", {}).get("fast_download_mbps", {}).get("avg", 0.0))
                      for entry in history[-25:] if entry.get("statistics")]
        all_speeds = [s for s in all_speeds if s > 0]
        if len(all_speeds) >= 2:
            spark = generate_sparkline(all_speeds)
            print(f"  Speed Trend ({len(all_speeds)} runs): [{C.CYAN}{spark}{C.RESET}] (min: {min(all_speeds):.1f} Mbps, max: {max(all_speeds):.1f} Mbps)")

    print(f"{C.MAGENTA}{C.BOLD}{top_bar}{C.RESET}\n")
    return 0


def run_single_benchmark(
    engine: str,
    run_num: int,
    st_ok: bool,
    fast_ok: bool,
    cf_ok: bool,
    quiet: bool,
    debug: bool,
    dl_pings: Optional[List[float]] = None,
    ul_pings: Optional[List[float]] = None,
    custom_url: Optional[str] = None,
    timeout: int = DOWNLOAD_TIMEOUT,
    ip_version: Optional[str] = None
) -> Optional[Dict[str, Any]]:
    """Run a single benchmark iteration for specified engine with directional loaded ping monitoring."""
    res = None
    sp = Spinner(f"Run {run_num} ({engine.title()})", quiet=quiet)
    sp.start()

    try:
        if engine == "speedtest" and st_ok:
            stop_ping = threading.Event()
            ping_th = None
            if dl_pings is not None:
                ping_th = threading.Thread(target=ping_monitor, args=(stop_ping, dl_pings, None, ip_version), daemon=True)
                ping_th.start()
            try:
                res = get_speedtest(debug, MAX_RETRIES, ip_version=ip_version)
            finally:
                if ping_th:
                    stop_ping.set()
                    ping_th.join(timeout=0.4)

            if res and res.get("download"):
                if res.get("dl_latency") is not None and dl_pings is not None:
                    dl_pings.append(float(res["dl_latency"]))
                if res.get("ul_latency") is not None and ul_pings is not None:
                    ul_pings.append(float(res["ul_latency"]))
                ul_str = f" | {C.YELLOW}UL: {res.get('upload', 'N/A')} Mbps{C.RESET}" if res.get("upload") else ""
                ping_str = f" {C.DIM}(Ping: {res.get('ping', 'N/A')}ms){C.RESET}" if res.get("ping") else ""
                sp.stop(f"Run {run_num}... {C.GREEN}DL: {res['download']} Mbps{C.RESET}{ul_str}{ping_str}")
            else:
                sp.stop(f"Run {run_num}... {C.RED}Failed (Skipped){C.RESET}")

        elif engine == "fast" and fast_ok:
            stop_ping = threading.Event()
            ping_th = None
            if dl_pings is not None:
                ping_th = threading.Thread(target=ping_monitor, args=(stop_ping, dl_pings, None, ip_version), daemon=True)
                ping_th.start()
            try:
                res = get_fastcom(debug, MAX_RETRIES, timeout=timeout, progress_callback=sp.update_status, ip_version=ip_version)
            finally:
                if ping_th:
                    stop_ping.set()
                    ping_th.join(timeout=0.4)

            if res and res.get("download"):
                sp.stop(f"Run {run_num}... {C.GREEN}DL: {res['download']} Mbps{C.RESET}")
            else:
                sp.stop(f"Run {run_num}... {C.RED}Failed (Skipped){C.RESET}")

        elif engine == "cloudflare" and cf_ok:
            res = get_cloudflare(
                debug=debug,
                retries=MAX_RETRIES,
                timeout=timeout,
                dl_ping_collector=dl_pings,
                ul_ping_collector=ul_pings,
                progress_callback=sp.update_status,
                ip_version=ip_version
            )
            if res and res.get("download"):
                ul_str = f" | {C.YELLOW}UL: {res.get('upload', 'N/A')} Mbps{C.RESET}" if res.get("upload") else ""
                sp.stop(f"Run {run_num}... {C.GREEN}DL: {res['download']} Mbps{C.RESET}{ul_str}")
            else:
                sp.stop(f"Run {run_num}... {C.RED}Failed (Skipped){C.RESET}")

        elif engine == "custom" and custom_url:
            stop_ping = threading.Event()
            ping_th = None
            if dl_pings is not None:
                ping_th = threading.Thread(target=ping_monitor, args=(stop_ping, dl_pings, None, ip_version), daemon=True)
                ping_th.start()
            try:
                res = get_custom_speedtest(custom_url, debug, MAX_RETRIES, timeout=timeout, ip_version=ip_version)
            finally:
                if ping_th:
                    stop_ping.set()
                    ping_th.join(timeout=0.4)

            if res and res.get("download"):
                sp.stop(f"Run {run_num}... {C.GREEN}DL: {res['download']} Mbps{C.RESET}")
            else:
                sp.stop(f"Run {run_num}... {C.RED}Failed (Skipped){C.RESET}")
    except Exception as e:
        sp.stop(f"Run {run_num}... {C.RED}Error: {e}{C.RESET}")

    return res


def run_benchmark_cycle(args) -> int:
    """Run one complete benchmark cycle with diagnostics, scoring, and data exports."""
    ip_ver = "4" if getattr(args, "ipv4", False) else ("6" if getattr(args, "ipv6", False) else None)
    st_ok, fast_ok, cf_ok = check_endpoints(args.quiet, args.debug, ip_version=ip_ver)

    if not args.quiet:
        print(f"{C.BLUE}[i] Detecting Network Adapters, Link Speeds & Dual-Stack IP...{C.RESET}")
    lan_ip = get_lan_ip("4", args.debug)
    lan_ipv6 = get_lan_ip("6", args.debug) if getattr(args, "ipv6", False) or not getattr(args, "ipv4", False) else "Unavailable"
    geo = get_geo_info(args.debug, ip_version=ip_ver)
    adapter = get_network_adapter_info(args.debug)
    idle_ping_info = measure_idle_ping(count=5, timeout=2, ip_version=ip_ver)
    packet_loss = idle_ping_info["loss"]
    idle_ping_samples = idle_ping_info["samples"]
    idle_stats = idle_ping_info["stats"]
    idle_jitter = idle_ping_info["jitter"]

    if not args.quiet:
        print(f"    {C.BOLD}Local IP (LAN):{C.RESET} {C.YELLOW}{lan_ip}{C.RESET} (IPv4)" + (f" | {C.YELLOW}{lan_ipv6}{C.RESET} (IPv6)" if lan_ipv6 != "Unavailable" else ""))
        print(f"    {C.BOLD}Public IP (WAN):{C.RESET}{C.YELLOW}{geo['ip']}{C.RESET} ({geo['isp']} - {geo['city']}, {geo['country']})")
        if geo.get("ipv6") and geo.get("ipv6") != "Unavailable":
            print(f"    {C.BOLD}Public IPv6:{C.RESET}    {C.YELLOW}{geo['ipv6']}{C.RESET}")
        print(f"    {C.BOLD}Interface:{C.RESET}      {C.YELLOW}{adapter['interface']}{C.RESET} ({adapter['interface_type']} - Link: {adapter['link_speed']})")
        print(f"    {C.BOLD}Gateway IP:{C.RESET}     {C.YELLOW}{adapter['gateway']}{C.RESET}")
        if adapter["interface_type"] == "Wi-Fi" or adapter["wifi_ssid"] not in ("N/A (Wired/Unknown)", "N/A"):
            wifi_extra = f" | {adapter['wifi_frequency']}" if adapter['wifi_frequency'] != 'N/A' else ""
            print(f"    {C.BOLD}Wi-Fi SSID:{C.RESET}     {C.YELLOW}{adapter['wifi_ssid']}{C.RESET} (Signal: {adapter['wifi_signal']}{wifi_extra})")
        idle_ms_str = f" (Idle RTT: {idle_stats['avg']} ms)" if idle_stats.get("avg", 0) > 0 else ""
        print(f"    {C.BOLD}Packet Loss:{C.RESET}    {C.YELLOW}{packet_loss}%{C.RESET}{idle_ms_str}\n")

    st_results: List[Dict[str, Any]] = []
    fast_results: List[Dict[str, Any]] = []
    cf_results: List[Dict[str, Any]] = []
    custom_results: List[Dict[str, Any]] = []
    dns_results: Optional[Dict[str, Any]] = None
    dl_ping_samples: List[float] = []
    ul_ping_samples: List[float] = []

    # 1. DNS Resolution Probes (Fast parallel execution, ~1-1.5s)
    dns_results: Optional[Dict[str, Any]] = None
    dns_rec: Optional[Dict[str, Any]] = None
    if getattr(args, "dns", True) and not getattr(args, "no_dns", False):
        sp_dns = Spinner("Benchmarking DNS Resolvers & Latency", quiet=args.quiet)
        sp_dns.start()
        try:
            enable_v6 = getattr(args, "ipv6", False) or not getattr(args, "ipv4", False)
            dns_results = run_dns_test(
                runs=min(args.runs, 3),
                quiet=True,
                debug=args.debug,
                gateway_ip=adapter.get("gateway"),
                test_doh=True,
                enable_ipv6=enable_v6
            )
            dns_rec = get_fastest_dns_recommendation(dns_results)
            sp_dns.stop("DNS Resolution Probes completed.")
        except Exception as e:
            sp_dns.stop(f"DNS Resolution Probes encountered an issue: {e}")
            dns_results = None

        if not getattr(args, "json_stdout", False) and not args.quiet and dns_rec:
            print_dns_leaderboard(dns_rec)

    # 2. Display Historical Benchmark Results immediately after DNS test
    if not getattr(args, "json_stdout", False) and not args.quiet:
        display_history(no_color=args.no_color, show_graph=True, inline=True)

    # 3. Active Speed Benchmarks for Current Setup
    if not args.quiet and not getattr(args, "json_stdout", False):
        print(f"{C.CYAN}{C.BOLD}🚀 Starting active speed benchmark tests for current setup...{C.RESET}\n")

    # Engine Filtering
    target_engine = getattr(args, "engine", "all")
    custom_url = getattr(args, "server", None)
    timeout = getattr(args, "timeout", DOWNLOAD_TIMEOUT)

    # 1. Ookla
    if (st_ok or getattr(args, "debug", False)) and target_engine in ("all", "speedtest", "ookla"):
        if not args.quiet:
            print(f"{C.CYAN}{C.BOLD}--- Running Speedtest.net (Ookla) Benchmark ---{C.RESET}")
        for i in range(1, args.runs + 1):
            res = run_single_benchmark("speedtest", i, st_ok, fast_ok, cf_ok, args.quiet, args.debug, dl_ping_samples, ul_ping_samples, timeout=timeout, ip_version=ip_ver)
            if res:
                st_results.append(res)
            time.sleep(0.3)

    # 2. Fast.com
    if fast_ok and target_engine in ("all", "fast"):
        if not args.quiet:
            print(f"\n{C.CYAN}{C.BOLD}--- Running Fast.com (Netflix CDN) Benchmark ---{C.RESET}")
        for i in range(1, args.runs + 1):
            res = run_single_benchmark("fast", i, st_ok, fast_ok, cf_ok, args.quiet, args.debug, dl_ping_samples, ul_ping_samples, timeout=timeout, ip_version=ip_ver)
            if res:
                fast_results.append(res)
            time.sleep(0.3)

    # 3. Cloudflare
    if cf_ok and target_engine in ("all", "cloudflare"):
        if not args.quiet:
            print(f"\n{C.CYAN}{C.BOLD}--- Running Cloudflare CDN Benchmark ---{C.RESET}")
        for i in range(1, args.runs + 1):
            res = run_single_benchmark("cloudflare", i, st_ok, fast_ok, cf_ok, args.quiet, args.debug, dl_ping_samples, ul_ping_samples, timeout=timeout, ip_version=ip_ver)
            if res:
                cf_results.append(res)
            time.sleep(0.3)

    # 4. Custom Server URL
    if custom_url and target_engine in ("all", "custom"):
        if not args.quiet:
            print(f"\n{C.CYAN}{C.BOLD}--- Running Custom Endpoint Benchmark ({custom_url}) ---{C.RESET}")
        for i in range(1, args.runs + 1):
            res = run_single_benchmark("custom", i, True, True, True, args.quiet, args.debug, dl_ping_samples, ul_ping_samples, custom_url=custom_url, timeout=timeout, ip_version=ip_ver)
            if res:
                custom_results.append(res)
            time.sleep(0.3)

    st_dls = [r["download"] for r in st_results if r.get("download")]
    st_uls = [r["upload"] for r in st_results if r.get("upload")]
    st_pings = [r["ping"] for r in st_results if r.get("ping")]
    fast_dls = [r["download"] for r in fast_results if r.get("download")]
    cf_dls = [r["download"] for r in cf_results if r.get("download")]
    cf_uls = [r["upload"] for r in cf_results if r.get("upload")]
    custom_dls = [r["download"] for r in custom_results if r.get("download")]

    st_dl_stats = calculate_statistics(st_dls)
    st_ul_stats = calculate_statistics(st_uls)
    fast_dl_stats = calculate_statistics(fast_dls)
    cf_dl_stats = calculate_statistics(cf_dls)
    cf_ul_stats = calculate_statistics(cf_uls)
    custom_dl_stats = calculate_statistics(custom_dls)

    if st_pings:
        ping_stats = calculate_statistics(st_pings)
        jitter = calculate_jitter(st_pings)
    elif idle_ping_samples:
        ping_stats = idle_stats
        jitter = idle_jitter
    else:
        ping_stats = calculate_statistics([])
        jitter = 0.0

    # Fallback ping baseline if idle / speedtest didn't provide ping
    unloaded_ping_avg = ping_stats["avg"] if ping_stats["avg"] > 0 else (
        idle_stats["avg"] if idle_stats.get("avg", 0) > 0 else (
            dns_results["overall_latency_ms"]["avg"] if dns_results and dns_results.get("overall_latency_ms", {}).get("avg", 0) > 0 else 15.0
        )
    )
    if ping_stats["avg"] == 0.0 and unloaded_ping_avg > 0:
        ping_stats["avg"] = unloaded_ping_avg

    bufferbloat_info = calculate_directional_bufferbloat(unloaded_ping_avg, dl_ping_samples, ul_ping_samples)
    bb_grade = bufferbloat_info["grade"]
    bb_delta = bufferbloat_info["delta_ms"]

    max_dl = max(st_dl_stats["avg"], fast_dl_stats["avg"], cf_dl_stats["avg"], custom_dl_stats["avg"])
    max_ul = max(st_ul_stats["avg"], cf_ul_stats["avg"])

    suitability = calculate_network_suitability(max_dl, max_ul, ping_stats["avg"], jitter, bb_grade, packet_loss)
    if not dns_rec and dns_results:
        dns_rec = get_fastest_dns_recommendation(dns_results)

    # Console Summary Display
    if not getattr(args, "json_stdout", False):
        w = 76
        h_line = "─" * w
        top_bar = "═" * w
        print(f"\n{C.MAGENTA}{C.BOLD}{top_bar}{C.RESET}")
        print(f"{C.MAGENTA}{C.BOLD}{'BENCHMARK SUMMARY':^{w}}{C.RESET}")
        print(f"{C.MAGENTA}{C.BOLD}{top_bar}{C.RESET}")
        print(f" {C.BOLD}Author:{C.RESET}         Shadowharvy | Tool Version: v{VERSION}")
        print(f" {C.BOLD}Local IP:{C.RESET}       {lan_ip} ({adapter['interface']})")
        if lan_ipv6 != "Unavailable":
            print(f" {C.BOLD}Local IPv6:{C.RESET}    {lan_ipv6}")
        print(f" {C.BOLD}Public IP:{C.RESET}      {geo['ip']} ({geo['isp']})")
        if geo.get("ipv6") and geo.get("ipv6") != "Unavailable":
            print(f" {C.BOLD}Public IPv6:{C.RESET}   {geo['ipv6']}")
        print(f" {C.BOLD}Speed Tier:{C.RESET}     {C.CYAN}{C.BOLD}{suitability['speed_tier']}{C.RESET}")
        print(f" {C.BOLD}Location:{C.RESET}       {geo['city']}, {geo['country']}")
        print(f" {C.DIM}{h_line}{C.RESET}")

        if st_ok and target_engine in ("all", "speedtest", "ookla"):
            print(f" {C.BOLD}Ookla Download:{C.RESET} {C.GREEN}{st_dl_stats['avg']} Mbps{C.RESET} {C.DIM}(min: {st_dl_stats['min']}, max: {st_dl_stats['max']}){C.RESET}")
            if st_ul_stats['avg'] > 0:
                print(f" {C.BOLD}Ookla Upload:{C.RESET}   {C.YELLOW}{st_ul_stats['avg']} Mbps{C.RESET} {C.DIM}(min: {st_ul_stats['min']}, max: {st_ul_stats['max']}){C.RESET}")
        if fast_ok and target_engine in ("all", "fast"):
            print(f" {C.BOLD}Fast Download:{C.RESET}  {C.GREEN}{fast_dl_stats['avg']} Mbps{C.RESET} {C.DIM}(min: {fast_dl_stats['min']}, max: {fast_dl_stats['max']}){C.RESET}")
        if cf_ok and target_engine in ("all", "cloudflare"):
            print(f" {C.BOLD}Cloudflare DL:{C.RESET}  {C.GREEN}{cf_dl_stats['avg']} Mbps{C.RESET} {C.DIM}(min: {cf_dl_stats['min']}, max: {cf_dl_stats['max']}){C.RESET}")
            if cf_ul_stats['avg'] > 0:
                print(f" {C.BOLD}Cloudflare UL:{C.RESET}  {C.YELLOW}{cf_ul_stats['avg']} Mbps{C.RESET} {C.DIM}(min: {cf_ul_stats['min']}, max: {cf_ul_stats['max']}){C.RESET}")
        if custom_url and target_engine in ("all", "custom"):
            print(f" {C.BOLD}Custom DL:{C.RESET}      {C.GREEN}{custom_dl_stats['avg']} Mbps{C.RESET} {C.DIM}(min: {custom_dl_stats['min']}, max: {custom_dl_stats['max']}){C.RESET}")

        print(f" {C.BOLD}Average Ping:{C.RESET}   {C.YELLOW}{ping_stats['avg']} ms{C.RESET} | {C.BOLD}Jitter:{C.RESET} {C.YELLOW}{jitter} ms{C.RESET} | {C.BOLD}Loss:{C.RESET} {C.YELLOW}{packet_loss}%{C.RESET}")
        print(f" {C.BOLD}Bufferbloat:{C.RESET}    {C.CYAN}{bb_grade}{C.RESET} {C.DIM}(DL: +{bufferbloat_info['download_delta_ms']}ms [{bufferbloat_info['download_grade']}], UL: +{bufferbloat_info['upload_delta_ms']}ms [{bufferbloat_info['upload_grade']}]){C.RESET}")
        print(f" {C.BOLD}Quality Score:{C.RESET}  {C.GREEN}{C.BOLD}{suitability['overall_score']}/100{C.RESET}")
        print(f"   ├─ 🎮 Gaming:     {C.CYAN}{suitability['gaming']['status']}{C.RESET}")
        print(f"   ├─ 🎥 Streaming:  {C.CYAN}{suitability['streaming']['status']}{C.RESET}")
        print(f"   └─ 📹 Video Call: {C.CYAN}{suitability['video_call']['status']}{C.RESET}")

        if dns_rec:
            if dns_rec.get("is_optimal"):
                opt_str = f"{C.GREEN}Optimal ({dns_rec.get('system_dns_latency')} ms){C.RESET}"
            else:
                opt_str = f"{C.YELLOW}+{dns_rec.get('savings_pct')}% faster via {dns_rec.get('name')}{C.RESET} {C.DIM}({dns_rec.get('primary')} - {dns_rec.get('latency_ms')} ms){C.RESET}"
            print(f" {C.BOLD}DNS Status:{C.RESET}     {opt_str}")

        print(f"{C.MAGENTA}{C.BOLD}{top_bar}{C.RESET}\n")

    record_data: Dict[str, Any] = {
        "timestamp": datetime.now().isoformat(),
        "version": VERSION,
        "network": {"lan_ip": lan_ip, "lan_ipv6": lan_ipv6, "geo": geo, "adapter": adapter},
        "statistics": {
            "speedtest_download_mbps": st_dl_stats,
            "speedtest_upload_mbps": st_ul_stats,
            "fast_download_mbps": fast_dl_stats,
            "cloudflare_download_mbps": cf_dl_stats,
            "cloudflare_upload_mbps": cf_ul_stats,
            "custom_download_mbps": custom_dl_stats,
            "ping_ms": ping_stats,
            "jitter_ms": jitter,
            "packet_loss_pct": packet_loss,
            "bufferbloat": bufferbloat_info
        },
        "suitability": suitability,
        "dns_recommendation": dns_rec,
        "dns": dns_results
    }
    save_history_record(record_data, args.debug)

    export_data: Dict[str, Any] = {
        **record_data,
        "raw_results": {
            "speedtest": st_results,
            "fast": fast_results,
            "cloudflare": cf_results,
            "custom": custom_results
        }
    }

    exit_code = 0

    # JSON stdout output for automation / pipes
    if getattr(args, "json_stdout", False):
        print(json.dumps(export_data, indent=2))

    # File exports
    if args.json:
        try:
            with open(args.json, "w") as f:
                json.dump(export_data, f, indent=4)
            if not args.quiet:
                print(f"{C.GREEN}[✔] JSON data exported to {args.json}{C.RESET}")
        except Exception as e:
            print(f"{C.RED}[!] Failed to write JSON: {e}{C.RESET}")
            exit_code = 1

    if args.csv:
        try:
            with open(args.csv, "w", newline="") as f:
                writer = csv.writer(f)
                writer.writerow(["Engine", "Run", "Download (Mbps)", "Upload (Mbps)", "Ping (ms)", "Jitter (ms)", "DL_Latency (ms)", "UL_Latency (ms)"])
                for idx, r in enumerate(st_results):
                    writer.writerow(["Speedtest", idx + 1, r.get("download", ""), r.get("upload", ""), r.get("ping", ""), r.get("jitter", ""), r.get("dl_latency", ""), r.get("ul_latency", "")])
                for idx, r in enumerate(fast_results):
                    writer.writerow(["Fast.com", idx + 1, r.get("download", ""), "", "", "", "", ""])
                for idx, r in enumerate(cf_results):
                    writer.writerow(["Cloudflare", idx + 1, r.get("download", ""), r.get("upload", ""), "", "", "", ""])
                for idx, r in enumerate(custom_results):
                    writer.writerow(["Custom", idx + 1, r.get("download", ""), "", "", "", "", ""])
            if not args.quiet:
                print(f"{C.GREEN}[✔] CSV data exported to {args.csv}{C.RESET}")
        except Exception as e:
            print(f"{C.RED}[!] Failed to write CSV: {e}{C.RESET}")
            exit_code = 1

    if getattr(args, "markdown", None):
        if export_markdown_report(args.markdown, export_data, args.debug):
            if not args.quiet:
                print(f"{C.GREEN}[✔] Markdown report exported to {args.markdown}{C.RESET}")
        else:
            print(f"{C.RED}[!] Failed to write Markdown report: {args.markdown}{C.RESET}")
            exit_code = 1

    if args.html and not getattr(args, "no_html", False):
        if export_html_report(args.html, export_data, args.debug):
            if not args.quiet and not getattr(args, "json_stdout", False):
                print(f"{C.GREEN}[✔] Glassmorphism HTML Report exported to {args.html}{C.RESET}")
            if args.open:
                open_browser_report(args.html)
        else:
            if not getattr(args, "json_stdout", False):
                print(f"{C.RED}[!] Failed to write HTML report: {args.html}{C.RESET}")
            exit_code = 1

    # SLA Threshold Checks
    if getattr(args, "threshold_dl", None) is not None:
        if max_dl < args.threshold_dl:
            print(f"{C.RED}[SLA ALERT] Download speed ({max_dl} Mbps) is below required threshold ({args.threshold_dl} Mbps)!{C.RESET}")
            exit_code = 3
    if getattr(args, "threshold_ul", None) is not None:
        if max_ul < args.threshold_ul:
            print(f"{C.RED}[SLA ALERT] Upload speed ({max_ul} Mbps) is below required threshold ({args.threshold_ul} Mbps)!{C.RESET}")
            exit_code = 3
    if getattr(args, "threshold_ping", None) is not None:
        if ping_stats["avg"] > args.threshold_ping:
            print(f"{C.RED}[SLA ALERT] Ping latency ({ping_stats['avg']} ms) exceeds threshold limit ({args.threshold_ping} ms)!{C.RESET}")
            exit_code = 3

    if not st_ok and not fast_ok and not cf_ok and not custom_url:
        return 2

    return exit_code


def run_benchmark() -> int:
    """Main entry point supporting single run, continuous monitoring, and CLI flags."""
    parser = argparse.ArgumentParser(
        description=f"Network Speed & Diagnostic Benchmark Tool v{VERSION} by Shadowharvy",
        epilog="Examples:\n"
               "  speedtest.sh -n 3 --dns --open\n"
               "  speedtest.sh --engine cloudflare --threshold-dl 100\n"
               "  speedtest.sh --history --history-graph\n"
               "  speedtest.sh --json-stdout | jq .",
        formatter_class=argparse.RawDescriptionHelpFormatter
    )
    parser.add_argument("-n", "--runs", type=int, default=3, help="Number of benchmark iterations (default: 3, max: 20)")
    parser.add_argument("--dns", action="store_true", default=True, help="Run background DNS & DoH resolution tests (default: enabled)")
    parser.add_argument("--no-dns", action="store_true", help="Explicitly disable DNS & DoH resolution tests")
    parser.add_argument("--engine", type=str, choices=["all", "speedtest", "ookla", "fast", "cloudflare", "custom"], default="all", help="Select speed engine filter (default: all)")
    parser.add_argument("--server", type=str, metavar="URL", help="Custom HTTP/HTTPS speedtest download URL to benchmark")
    parser.add_argument("--timeout", type=int, default=DOWNLOAD_TIMEOUT, metavar="SECS", help=f"Per-stream transfer timeout in seconds (default: {DOWNLOAD_TIMEOUT})")
    parser.add_argument("-4", "--ipv4", action="store_true", help="Force IPv4 network requests")
    parser.add_argument("-6", "--ipv6", action="store_true", help="Force IPv6 network requests")
    parser.add_argument("--history", action="store_true", help="Display historical benchmark trends and averages")
    parser.add_argument("--history-graph", action="store_true", help="Render sparkline trend graph with history")
    parser.add_argument("--history-clear", action="store_true", help="Clear historical benchmark log file")
    parser.add_argument("--html", type=str, nargs="?", const="report.html", default="report.html", metavar="FILE", help="Export standalone interactive HTML dashboard report (default: report.html)")
    parser.add_argument("--no-html", action="store_true", help="Explicitly disable default HTML dashboard export")
    parser.add_argument("--markdown", type=str, metavar="FILE", help="Export GitHub-flavored Markdown summary report")
    parser.add_argument("--open", action="store_true", help="Auto-open exported HTML report in default browser")
    parser.add_argument("--json", type=str, metavar="FILE", help="Export results to a JSON file")
    parser.add_argument("--json-stdout", action="store_true", help="Output machine-readable JSON directly to stdout")
    parser.add_argument("--csv", type=str, metavar="FILE", help="Export results to a CSV file")
    parser.add_argument("--threshold-dl", type=float, metavar="MBPS", help="Minimum required download speed (exits with code 3 if violated)")
    parser.add_argument("--threshold-ul", type=float, metavar="MBPS", help="Minimum required upload speed (exits with code 3 if violated)")
    parser.add_argument("--threshold-ping", type=float, metavar="MS", help="Maximum acceptable ping latency (exits with code 3 if violated)")
    parser.add_argument("--monitor", type=int, metavar="MINS", help="Continuous monitoring mode interval in minutes")
    parser.add_argument("--quiet", action="store_true", help="Suppress banner and live progress output")
    parser.add_argument("--no-color", action="store_true", help="Disable ANSI terminal colors")
    parser.add_argument("--debug", action="store_true", help="Enable debug logs for troubleshooting")
    parser.add_argument("--version", action="version", version=f"%(prog)s {VERSION}", help="Show version and exit")
    args = parser.parse_args()

    if getattr(args, "no_html", False):
        args.html = None

    if args.json_stdout:
        args.quiet = True

    if args.no_color or args.json_stdout:
        C.disable()

    if args.history or args.history_clear:
        return display_history(clear=args.history_clear, no_color=args.no_color, show_graph=True)

    if args.runs < 1 or args.runs > 20:
        print(f"{C.RED}[!] Error: --runs must be between 1 and 20{C.RESET}")
        return 1

    if not args.json_stdout:
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