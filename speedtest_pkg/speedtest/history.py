"""History management."""

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

def save_history_record(record_data: Dict[str, Any], debug: bool = False) -> None:
    """Append a benchmark record to ~/.speedtest_history.json with retention cap and atomic write."""
    try:
        history = []
        if os.path.exists(HISTORY_FILE):
            try:
                with open(HISTORY_FILE, "r") as f:
                    data = json.load(f)
                    if isinstance(data, list):
                        history = data
            except Exception:
                history = []
        history.append(record_data)
        if len(history) > MAX_HISTORY_ENTRIES:
            history = history[-MAX_HISTORY_ENTRIES:]

        dir_name = os.path.dirname(os.path.abspath(HISTORY_FILE))
        os.makedirs(dir_name, exist_ok=True)
        temp_path = None
        try:
            with tempfile.NamedTemporaryFile("w", dir=dir_name, delete=False, suffix=".tmp") as tf:
                json.dump(history, tf, indent=2)
                temp_path = tf.name
            os.replace(temp_path, HISTORY_FILE)
        except Exception:
            if temp_path and os.path.exists(temp_path):
                try:
                    os.unlink(temp_path)
                except Exception:
                    # Best-effort cleanup; file may already be gone.
                    pass
            raise
    except Exception as e:
        if debug:
            print(f"{C.YELLOW}[DEBUG] Failed to save history: {e}{C.RESET}")



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

    # Tolerate hand-edited/legacy files: keep only well-formed list entries.
    if not isinstance(history, list):
        history = []
    history = [e for e in history if isinstance(e, dict)]

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
        dt = str(entry.get("timestamp") or "").replace("T", " ")[:16]
        net = entry.get("network") or {}
        isp = (net.get("geo") or {}).get("isp", net.get("isp", "Unknown"))
        if not isp:
            isp = "Unknown"
        if len(isp) > 12:
            isp = isp[:10] + ".."
        iface = (net.get("adapter") or {}).get("interface", "")
        if_info = f"{isp} ({iface})" if iface else isp

        stats = entry.get("statistics") or {}

        def _avg(section: Optional[Dict[str, Any]]) -> float:
            try:
                return float((stats.get(section) or {}).get("avg", 0.0) or 0.0)
            except (TypeError, ValueError):
                return 0.0

        st_dl = _avg("speedtest_download_mbps")
        fast_dl = _avg("fast_download_mbps")
        cf_dl = _avg("cloudflare_download_mbps")
        ping = _avg("ping_ms")
        bb = stats.get("bufferbloat") or {}
        bb_str = f"{bb.get('grade', 'N/A')} (+{bb.get('delta_ms', 0)}ms)" if bb else "N/A"
        score = (entry.get("suitability") or {}).get("overall_score", 0.0)

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
        all_speeds = [max((entry.get("statistics") or {}).get("cloudflare_download_mbps", {}).get("avg", 0.0),
                          (entry.get("statistics") or {}).get("speedtest_download_mbps", {}).get("avg", 0.0),
                          (entry.get("statistics") or {}).get("fast_download_mbps", {}).get("avg", 0.0))
                      for entry in history[-25:] if entry.get("statistics")]
        all_speeds = [s for s in all_speeds if s > 0]
        if len(all_speeds) >= 2:
            spark = generate_sparkline(all_speeds)
            print(f"  Speed Trend ({len(all_speeds)} runs): [{C.CYAN}{spark}{C.RESET}] (min: {min(all_speeds):.1f} Mbps, max: {max(all_speeds):.1f} Mbps)")

    print(f"{C.MAGENTA}{C.BOLD}{top_bar}{C.RESET}\n")
    return 0


