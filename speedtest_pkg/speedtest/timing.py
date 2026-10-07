"""Site timing and traceroute."""

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

def probe_site_timing(host: str, timeout: int = HTTP_TIMEOUT, ip_version: Optional[str] = None, debug: bool = False) -> Optional[Dict[str, Any]]:
    """Measure per-phase connection timings to a host using a single HTTPS GET.

    Returns DNS / TCP / TLS / TTFB / total times in milliseconds, or None if the
    host could not be reached. Requires no special privileges (unlike traceroute).
    """
    fmt = ("%{time_namelookup}|%{time_connect}|%{time_appconnect}|%{time_starttransfer}"
           "|%{time_total}|%{remote_ip}|%{http_code}|%{time_redirect}")
    cmd = ["curl", "-s", "-o", "/dev/null", "-A", USER_AGENT,
           "--connect-timeout", str(timeout), "--max-time", str(timeout), "-w", fmt]
    if ip_version == "4":
        cmd.append("-4")
    elif ip_version == "6":
        cmd.append("-6")
    cmd.append(f"https://{host}/")

    try:
        res = subprocess.run(cmd, capture_output=True, text=True, timeout=timeout + 3)
        out = (res.stdout or "").strip()
        if res.returncode != 0 or "|" not in out:
            if debug:
                err = (res.stderr or "").strip()[:120]
                print(f"{C.YELLOW}[DEBUG] Site timing failed for {host} (curl rc={res.returncode}): {err}{C.RESET}")
            return None
        parts = out.split("|")
        if len(parts) < 7:
            return None

        def secs_to_ms(v: str) -> float:
            try:
                return round(float(v) * 1000.0, 2)
            except (TypeError, ValueError):
                return 0.0

        dns_ms = secs_to_ms(parts[0])
        tcp_ms = secs_to_ms(parts[1])
        tls_ms = secs_to_ms(parts[2])
        ttfb_ms = secs_to_ms(parts[3])
        total_ms = secs_to_ms(parts[4])
        remote_ip = parts[5].strip()
        try:
            http_code = int(parts[6] or 0)
        except ValueError:
            http_code = 0
        redirect_ms = secs_to_ms(parts[7]) if len(parts) > 7 else 0.0

        if http_code == 0 or total_ms <= 0:
            return None

        return {
            "host": host,
            "remote_ip": remote_ip,
            "http_code": http_code,
            "dns_ms": dns_ms,
            "tcp_ms": round(tcp_ms - dns_ms, 2) if tcp_ms > dns_ms else 0.0,
            "tls_ms": round(tls_ms - tcp_ms, 2) if tls_ms > tcp_ms else 0.0,
            "server_ms": round(ttfb_ms - tls_ms, 2) if ttfb_ms > tls_ms else 0.0,
            "ttfb_ms": ttfb_ms,
            "total_ms": total_ms,
            "redirect_ms": redirect_ms,
        }
    except subprocess.TimeoutExpired:
        if debug:
            print(f"{C.YELLOW}[DEBUG] Site timing timed out for {host}{C.RESET}")
    except Exception as e:
        if debug:
            print(f"{C.YELLOW}[DEBUG] Unexpected site timing error for {host}: {e}{C.RESET}")
    return None



def run_site_timing_test(
    targets: Optional[List[Dict[str, str]]] = None,
    runs: int = SITE_TIMING_RUNS,
    quiet: bool = False,
    debug: bool = False,
    ip_version: Optional[str] = None
) -> List[Dict[str, Any]]:
    """Probe popular sites in parallel and return per-target timing summaries."""
    targets = targets or SITE_TIMING_TARGETS
    runs = max(1, runs)

    def probe_target(t: Dict[str, str]) -> Dict[str, Any]:
        samples: List[Dict[str, Any]] = []
        for _ in range(runs):
            probe = probe_site_timing(t["host"], timeout=HTTP_TIMEOUT, ip_version=ip_version, debug=debug)
            if probe:
                samples.append(probe)
        return {"name": t["name"], "host": t["host"], "samples": samples}

    results: List[Dict[str, Any]] = []
    with ThreadPoolExecutor(max_workers=min(max(len(targets), 1), SITE_TIMING_WORKERS)) as ex:
        for res in ex.map(probe_target, targets):
            results.append(res)

    # Summarize each target: median resists a single slow sample skewing the result.
    summary: List[Dict[str, Any]] = []
    for r in results:
        samples = r["samples"]
        entry: Dict[str, Any] = {"name": r["name"], "host": r["host"], "reachable": bool(samples)}
        entry["samples"] = len(samples)
        entry["loss_pct"] = round(((runs - len(samples)) / runs) * 100.0, 1)
        if samples:
            entry["remote_ip"] = samples[-1].get("remote_ip", "")
            entry["http_code"] = samples[-1].get("http_code", 0)
            for field in ("dns_ms", "tcp_ms", "tls_ms", "server_ms", "ttfb_ms", "total_ms"):
                entry[field] = calculate_statistics([s[field] for s in samples])["median"]
        summary.append(entry)

    if not quiet:
        reachable = sum(1 for s in summary if s["reachable"])
        print(f"  {C.DIM}Probed {len(summary)} targets ({reachable} reachable, {runs} run(s) each){C.RESET}")
    return summary



def find_traceroute_command() -> Optional[Tuple[List[str], str]]:
    """Locate a hop-by-hop traceroute implementation.

    Returns (base command, tool name) or None when neither traceroute nor
    tracepath is installed. Raw-socket probing needs privileges, so we shell
    out rather than implementing TTL expiry ourselves.
    """
    for binary, tool in (("traceroute", "traceroute"), ("tracepath", "tracepath")):
        path = shutil.which(binary)
        if path:
            return [path], tool
    return None



def parse_traceroute_output(output: str, max_hops: int = TRACEROUTE_DEFAULT_MAX_HOPS) -> List[Dict[str, Any]]:
    """Parse traceroute/tracepath output into structured hop records.

    Handles the classic traceroute layout (" 2  10.0.0.1  1.2 ms  1.1 ms"), the
    tracepath layout (" 2:  10.0.0.1   12.3ms"), and '*'/'?' no-reply hops.
    """
    hops: List[Dict[str, Any]] = []
    seen: Dict[int, Dict[str, Any]] = {}

    for line in (output or "").splitlines():
        line = line.strip()
        if not line:
            continue
        m = re.match(r"^(\d+):?[\s]+(.*)$", line)
        if not m:
            continue
        try:
            hop_num = int(m.group(1))
        except ValueError:
            continue
        if hop_num < 1 or hop_num > max_hops:
            continue
        rest = m.group(2)
        # tracepath emits a "pmtu"/"Resume" trailer that is not a hop measurement.
        if re.search(r"pmtu|Resume|Too many hops", rest, re.IGNORECASE):
            continue

        rtts = [float(x) for x in re.findall(r"([0-9]+\.?[0-9]*)\s*ms", rest)]
        ip_m = re.search(r"\b(\d{1,3}(?:\.\d{1,3}){3}|[0-9a-fA-F]{0,4}(?::[0-9a-fA-F]{0,4}){2,})\b", rest)
        addr = ip_m.group(1) if ip_m else ""

        entry = seen.get(hop_num)
        if entry is None:
            entry = {"hop": hop_num, "ip": addr or None, "rtt_ms": None, "timeout": True, "_rtts": []}
            seen[hop_num] = entry
        elif not entry["ip"] and addr:
            entry["ip"] = addr
        entry["_rtts"].extend(rtts)

    for hop_num in sorted(seen):
        entry = seen[hop_num]
        samples = entry.pop("_rtts")
        if samples:
            entry["rtt_ms"] = round(sum(samples) / len(samples), 2)
            entry["timeout"] = False
        else:
            entry["rtt_ms"] = None
            entry["timeout"] = True
        hops.append(entry)
    return hops



def run_traceroute(
    host: str,
    max_hops: int = TRACEROUTE_DEFAULT_MAX_HOPS,
    quiet: bool = False,
    debug: bool = False,
    ip_version: Optional[str] = None
) -> Optional[Dict[str, Any]]:
    """Run a hop-by-hop path trace to `host` using the system traceroute tool."""
    found = find_traceroute_command()
    if not found:
        if debug:
            print(f"{C.YELLOW}[DEBUG] Neither traceroute nor tracepath installed; skipping hop trace for {host}{C.RESET}")
        return None

    base_cmd, tool = found
    cmd = list(base_cmd)
    if tool == "tracepath":
        cmd += ["-n", "-m", str(max_hops)]
        per_hop_budget = 6
    else:
        # traceroute: -n disables reverse DNS, -q 1 keeps it fast, -w bounds per-probe wait.
        cmd += ["-n", "-q", "1", "-w", "2", "-m", str(max_hops)]
        per_hop_budget = 3
    if ip_version == "4":
        cmd.append("-4")
    elif ip_version == "6":
        cmd.append("-6")
    cmd.append(host)

    # Unresponsive hops can stall a trace; bound the whole run generously but finitely.
    try:
        res = subprocess.run(cmd, capture_output=True, text=True, timeout=max_hops * per_hop_budget + 10)
    except subprocess.TimeoutExpired:
        if debug:
            print(f"{C.YELLOW}[DEBUG] traceroute timed out for {host}{C.RESET}")
        return None
    except Exception as e:
        if debug:
            print(f"{C.YELLOW}[DEBUG] traceroute failed for {host}: {e}{C.RESET}")
        return None

    hops = parse_traceroute_output(res.stdout, max_hops=max_hops)
    if not hops:
        if debug:
            print(f"{C.YELLOW}[DEBUG] No hops parsed from {tool} output for {host}{C.RESET}")
        return None

    responding = [h for h in hops if h.get("rtt_ms") is not None]
    return {
        "host": host,
        "tool": tool,
        "hop_count": len(hops),
        "responding_hops": len(responding),
        "timeout_hops": len(hops) - len(responding),
        "final_hop": hops[-1],
        "max_rtt_ms": max((h["rtt_ms"] for h in responding), default=None),
        "hops": hops,
    }



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


