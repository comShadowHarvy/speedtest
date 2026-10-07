"""Terminal UI helpers."""

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



def print_site_timing_table(results: List[Dict[str, Any]], width: int = 76) -> None:
    """Print a per-site DNS/TCP/TLS/TTFB timing table."""
    if not results:
        return
    h_line = "─" * width
    print(f"\n{C.CYAN}{C.BOLD}{'SITE REACHABILITY TIMING (median of N runs)':^{width}}{C.RESET}")
    print(f"{C.CYAN}{C.DIM}{h_line}{C.RESET}")
    print(f"  {C.BOLD}{'Site':<12} {'DNS':>7} {'TCP':>7} {'TLS':>7} {'Server':>8} {'TTFB':>8} {'Total':>8}  Status{C.RESET}")
    print(f"  {C.DIM}{h_line}{C.RESET}")

    for r in results:
        name = str(r.get("name", "?"))[:12]
        if not r.get("reachable"):
            print(f"  {name:<12} {'-':>7} {'-':>7} {'-':>7} {'-':>8} {'-':>8} {'-':>8}  {C.RED}Unreachable{C.RESET}")
            continue

        total = r.get("total_ms", 0.0)
        if total <= 0:
            color, status = C.RED, "No data"
        elif total < 300:
            color, status = C.GREEN, "Excellent"
        elif total < 800:
            color, status = C.YELLOW, "Fair"
        else:
            color, status = C.RED, "Slow"
        code = r.get("http_code", 0)
        code_note = f"HTTP {code}" if code else ""
        print(f"  {name:<12} {r.get('dns_ms', 0):>6.1f}m {r.get('tcp_ms', 0):>6.1f}m "
              f"{r.get('tls_ms', 0):>6.1f}m {r.get('server_ms', 0):>7.1f}m "
              f"{r.get('ttfb_ms', 0):>7.1f}m {color}{total:>7.1f}m{C.RESET}  "
              f"{color}{status}{C.RESET} {C.DIM}{code_note}{C.RESET}")
    print(f"{C.CYAN}{C.DIM}{h_line}{C.RESET}")



def print_traceroute(trace: Dict[str, Any], width: int = 76) -> None:
    """Print a hop-by-hop path trace."""
    if not trace:
        return
    print(f"\n{C.MAGENTA}{C.BOLD}{'HOP-BY-HOP PATH TRACE':^{width}}{C.RESET}")
    print(f"{C.MAGENTA}{C.DIM}{'─' * width}{C.RESET}")
    for hop in trace.get("hops", []):
        num = hop.get("hop")
        if hop.get("timeout") or hop.get("rtt_ms") is None:
            print(f"  {C.YELLOW}{num:>2}{C.RESET}  {C.DIM}* * *  (no reply){C.RESET}")
            continue
        rtt = hop["rtt_ms"]
        color = C.GREEN if rtt < 30 else (C.YELLOW if rtt < 100 else C.RED)
        print(f"  {C.BOLD}{num:>2}{C.RESET}  {str(hop.get('ip') or '?'):<40} {color}{rtt:>8.2f} ms{C.RESET}")
    summary = (f"  {trace.get('responding_hops', 0)}/{trace.get('hop_count', 0)} hops responded"
               f" via {trace.get('tool', '?')}")
    if trace.get("timeout_hops"):
        summary += f" {C.DIM}({trace['timeout_hops']} no-reply){C.RESET}"
    print(f"{C.MAGENTA}{C.DIM}{'─' * width}{C.RESET}")
    print(f"{C.DIM}{summary}{C.RESET}")



def print_banner(quiet: bool) -> None:
    """Display modern stylized application banner."""
    if quiet:
        return
    print(f"\n{C.CYAN}{C.BOLD}================================================================{C.RESET}")
    print(f"{C.CYAN}{C.BOLD}             NETWORK SPEED & DIAGNOSTIC BENCHMARK               {C.RESET}")
    print(f"{C.DIM}          Created by: {C.MAGENTA}{C.BOLD}Shadowharvy{C.RESET} | Version: {C.GREEN}{C.BOLD}v{VERSION}{C.RESET}")
    print(f"{C.CYAN}{C.BOLD}================================================================{C.RESET}\n")


