"""DNS benchmarking."""

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
from .core import (
    C, Spinner, VERSION, MAX_RETRIES, BASE_RETRY_DELAY, MAX_RETRY_DELAY,
    HTTP_TIMEOUT, DOWNLOAD_TIMEOUT, CHECK_TIMEOUT, DNS_TIMEOUT, DEFAULT_WORKERS,
    HISTORY_FILE, MAX_HISTORY_ENTRIES, MAX_RUNS, MAX_MONITOR_MINUTES,
    MAX_CONSECUTIVE_MONITOR_FAILURES, DNS_RESOLVERS, IPV6_DNS_RESOLVERS,
    DNS_PROVIDER_DETAILS, DNS_QUERIES, USER_AGENT, JS_PATH_PATTERN, TOKEN_PATTERN,
    SPARKLINE_CHARS, SITE_TIMING_TARGETS, SITE_TIMING_WORKERS, SITE_TIMING_RUNS,
    TRACEROUTE_DEFAULT_MAX_HOPS, TRACEROUTE_MAX_HOPS, TRACEROUTE_DEFAULT_HOSTS,
    generate_sparkline, make_http_request, exponential_backoff_delay,
    is_ipv6_available, build_dns_query, is_valid_dns_response,
    get_dns_latency, get_doh_latency, get_dns_category,
    measure_idle_ping, measure_packet_loss, get_speed_tier,
    calculate_network_suitability, calculate_bufferbloat_grade,
    calculate_directional_bufferbloat, calculate_jitter, calculate_statistics,
)

def get_system_dns_resolvers() -> List[Dict[str, Any]]:
    """Discover system-configured DNS nameservers dynamically across Linux, macOS, and Termux."""
    dns_ips: List[str] = []

    # 1. systemd-resolved (Linux)
    try:
        res = subprocess.run(["resolvectl", "status"], capture_output=True, text=True, timeout=2)
        if res.returncode == 0:
            dns_ips.extend(re.findall(r"DNS Servers:\s*([0-9a-fA-F:.]+)", res.stdout))
    except Exception:
        # resolvectl not installed or unavailable on this system; skip gracefully.
        pass

    # 2. NetworkManager nmcli (Linux)
    try:
        res = subprocess.run(["nmcli", "dev", "show"], capture_output=True, text=True, timeout=2)
        if res.returncode == 0:
            dns_ips.extend(re.findall(r"IP[46]\.DNS\[\d+\]:\s*([0-9a-fA-F:.]+)", res.stdout))
    except Exception:
        # nmcli not installed or unavailable on this system; skip gracefully.
        pass

    # 3. macOS scutil
    try:
        res = subprocess.run(["scutil", "--dns"], capture_output=True, text=True, timeout=2)
        if res.returncode == 0:
            dns_ips.extend(re.findall(r"nameserver\[\d+\]\s*:\s*([0-9a-fA-F:.]+)", res.stdout))
    except Exception:
        # scutil not installed or unavailable on this system; skip gracefully.
        pass

    # 4. Android / Termux getprop
    try:
        for prop in ["net.dns1", "net.dns2", "net.dns3", "net.dns4"]:
            res = subprocess.run(["getprop", prop], capture_output=True, text=True, timeout=2)
            if res.returncode == 0 and res.stdout.strip():
                dns_ips.append(res.stdout.strip())
    except Exception:
        # getprop (Android/Termux) not installed or not permitted; skip gracefully.
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
                # Cannot read the resolver config (e.g., permission denied); skip.
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


