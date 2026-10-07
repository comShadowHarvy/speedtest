"""CLI orchestration: benchmark cycles, validation, entry point."""

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
from .dns import run_dns_test, get_fastest_dns_recommendation
from .ui import print_banner, print_dns_leaderboard, print_site_timing_table, print_traceroute
from .network import check_endpoints, get_network_adapter_info, get_lan_ip, get_geo_info
from .engines import get_speedtest, get_fastcom, get_cloudflare, get_custom_speedtest
from .timing import probe_site_timing, run_site_timing_test, find_traceroute_command, parse_traceroute_output, run_traceroute, ping_monitor
from .history import save_history_record, display_history
from .reports import export_html_report, export_markdown_report, export_json_report, export_csv_report, get_preferred_browser, open_browser_report

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
    # Invariant: machine-readable output implies no human-readable chatter on stdout,
    # regardless of how the caller populated args.
    if getattr(args, "json_stdout", False):
        args.quiet = True
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

    # 2. Traceroute-style site reachability timing (opt-in via --traceroute).
    # Strictly opt-in: only an explicit True enables real network probing, so a
    # truthy-but-not-boolean flag value can never trigger these probes.
    site_timings: List[Dict[str, Any]] = []
    traceroute_results: List[Dict[str, Any]] = []
    if getattr(args, "traceroute", False) is True:
        if not args.quiet and not getattr(args, "json_stdout", False):
            print(f"\n{C.CYAN}{C.BOLD}--- Measuring Site Reachability Timings ---{C.RESET}")
        sp_trace = Spinner("Probing popular sites", quiet=args.quiet)
        sp_trace.start()
        try:
            targets = SITE_TIMING_TARGETS
            custom_trace_host = getattr(args, "trace_target", None)
            if custom_trace_host:
                targets = [{"name": "Custom", "host": custom_trace_host}]

            site_timings = run_site_timing_test(
                targets=targets,
                runs=getattr(args, "trace_runs", SITE_TIMING_RUNS),
                quiet=True,
                debug=args.debug,
                ip_version=ip_ver
            )

            # Hop-by-hop layer: only when a traceroute binary is actually available.
            # Traces run concurrently: a lossy network can burn the full per-probe
            # wait on every hop, so serial tracing would dominate the run time.
            if find_traceroute_command():
                max_hops = min(getattr(args, "trace_hops", TRACEROUTE_DEFAULT_MAX_HOPS), TRACEROUTE_MAX_HOPS)
                trace_hosts = [custom_trace_host] if custom_trace_host else TRACEROUTE_DEFAULT_HOSTS
                with ThreadPoolExecutor(max_workers=min(len(trace_hosts), 4)) as tex:
                    futures = [tex.submit(run_traceroute, th, max_hops, True, args.debug, ip_ver)
                               for th in trace_hosts]
                    for fut in as_completed(futures):
                        try:
                            trace = fut.result()
                        except Exception as e:
                            if args.debug:
                                print(f"{C.YELLOW}[DEBUG] traceroute failed: {e}{C.RESET}")
                            continue
                        if trace:
                            traceroute_results.append(trace)
                # Keep a stable, user-defined order rather than completion order.
                order = {th: i for i, th in enumerate(trace_hosts)}
                traceroute_results.sort(key=lambda t: order.get(t.get("host"), 99))
            sp_trace.stop(f"Site timing completed ({len(site_timings)} target(s)).")
        except Exception as e:
            sp_trace.stop(f"Site timing encountered an issue: {e}")

        if not getattr(args, "json_stdout", False) and not args.quiet:
            print_site_timing_table(site_timings)
            for tr in traceroute_results:
                print_traceroute(tr)
            if site_timings and not find_traceroute_command():
                print(f" {C.DIM}[i] Hop-by-hop tracing unavailable: install 'traceroute' or 'iputils-tracepath' for path traces.{C.RESET}")

    # 3. Display Historical Benchmark Results immediately after DNS test
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
        "dns": dns_results,
        "site_timings": site_timings or None,
        "traceroutes": traceroute_results or None,
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

    # Errors/alerts go to stderr in --json-stdout mode so stdout stays machine-parseable JSON.
    msg_stream = sys.stderr if getattr(args, "json_stdout", False) else sys.stdout

    # JSON stdout output for automation / pipes
    if getattr(args, "json_stdout", False):
        print(json.dumps(export_data, indent=2))

    # File exports
    if args.json:
        if export_json_report(args.json, export_data, args.debug):
            if not args.quiet:
                print(f"{C.GREEN}[✔] JSON data exported to {args.json}{C.RESET}")
        else:
            print(f"{C.RED}[!] Failed to write JSON: {args.json}{C.RESET}", file=msg_stream)
            exit_code = 1

    if args.csv:
        if export_csv_report(args.csv, st_results, fast_results, cf_results, custom_results, args.debug):
            if not args.quiet:
                print(f"{C.GREEN}[✔] CSV data exported to {args.csv}{C.RESET}")
        else:
            print(f"{C.RED}[!] Failed to write CSV: {args.csv}{C.RESET}", file=msg_stream)
            exit_code = 1

    if getattr(args, "markdown", None):
        if export_markdown_report(args.markdown, export_data, args.debug):
            if not args.quiet:
                print(f"{C.GREEN}[✔] Markdown report exported to {args.markdown}{C.RESET}")
        else:
            print(f"{C.RED}[!] Failed to write Markdown report: {args.markdown}{C.RESET}", file=msg_stream)
            exit_code = 1

    if args.html and not getattr(args, "no_html", False):
        if export_html_report(args.html, export_data, args.debug):
            if not args.quiet and not getattr(args, "json_stdout", False):
                print(f"{C.GREEN}[✔] Glassmorphism HTML Report exported to {args.html}{C.RESET}")
            if args.open:
                open_browser_report(args.html, quiet=args.quiet, debug=args.debug)
        else:
            print(f"{C.RED}[!] Failed to write HTML report: {args.html}{C.RESET}", file=msg_stream)
            exit_code = 1

    # SLA Threshold Checks - only meaningful when at least one measurement succeeded,
    # otherwise every threshold would be reported as violated by the 0.0 fallback values.
    has_measurements = bool(st_results or fast_results or cf_results or custom_results)
    if has_measurements:
        if getattr(args, "threshold_dl", None) is not None:
            if max_dl < args.threshold_dl:
                print(f"{C.RED}[SLA ALERT] Download speed ({max_dl} Mbps) is below required threshold ({args.threshold_dl} Mbps)!{C.RESET}", file=msg_stream)
                exit_code = 3
        if getattr(args, "threshold_ul", None) is not None:
            if max_ul < args.threshold_ul:
                print(f"{C.RED}[SLA ALERT] Upload speed ({max_ul} Mbps) is below required threshold ({args.threshold_ul} Mbps)!{C.RESET}", file=msg_stream)
                exit_code = 3
        if getattr(args, "threshold_ping", None) is not None:
            if ping_stats["avg"] > args.threshold_ping:
                print(f"{C.RED}[SLA ALERT] Ping latency ({ping_stats['avg']} ms) exceeds threshold limit ({args.threshold_ping} ms)!{C.RESET}", file=msg_stream)
                exit_code = 3

    # No engine returned a single usable measurement: report dedicated exit code 2
    # (unless an export already failed with code 1, which is more actionable).
    if not has_measurements:
        return exit_code or 2

    return exit_code



def validate_args(args) -> Optional[str]:
    """Validate CLI argument combinations/ranges.

    Returns an error message string when the arguments are invalid, otherwise None.
    Kept separate from run_benchmark() so it can be unit tested directly.
    """
    runs = getattr(args, "runs", 3)
    if runs < 1 or runs > MAX_RUNS:
        return f"--runs must be between 1 and {MAX_RUNS} (got: {runs})"

    timeout = getattr(args, "timeout", DOWNLOAD_TIMEOUT)
    if timeout < 1:
        return f"--timeout must be at least 1 second (got: {timeout})"

    monitor = getattr(args, "monitor", None)
    if monitor is not None:
        if monitor < 1:
            return f"--monitor interval must be at least 1 minute (got: {monitor})"
        if monitor > MAX_MONITOR_MINUTES:
            return f"--monitor interval must be at most {MAX_MONITOR_MINUTES} minutes (got: {monitor})"

    engine = getattr(args, "engine", "all")
    server = getattr(args, "server", None)
    if engine == "custom" and not server:
        return "--engine custom requires --server <URL> to point at a downloadable endpoint"
    if engine not in ("all", "custom") and server:
        return f"--server is only meaningful with '--engine all' or '--engine custom' (current engine: {engine})"
    if server:
        scheme = urllib.parse.urlparse(server).scheme.lower()
        if scheme not in ("http", "https"):
            return f"--server must use http:// or https:// (got: {scheme or 'no scheme'})"

    for flag, value in (
        ("--threshold-dl", getattr(args, "threshold_dl", None)),
        ("--threshold-ul", getattr(args, "threshold_ul", None)),
        ("--threshold-ping", getattr(args, "threshold_ping", None)),
    ):
        if value is not None and value <= 0:
            return f"{flag} must be greater than 0 (got: {value})"

    hops = getattr(args, "trace_hops", None)
    if hops is not None and (hops < 1 or hops > TRACEROUTE_MAX_HOPS):
        return f"--trace-hops must be between 1 and {TRACEROUTE_MAX_HOPS} (got: {hops})"

    trace_runs = getattr(args, "trace_runs", None)
    if trace_runs is not None and (trace_runs < 1 or trace_runs > 10):
        return f"--trace-runs must be between 1 and 10 (got: {trace_runs})"

    trace_target = getattr(args, "trace_target", None)
    if trace_target:
        # Accept bare host or a full URL, but never a URL with an unsupported scheme.
        candidate = trace_target if "://" in trace_target else f"http://{trace_target}"
        scheme = urllib.parse.urlparse(candidate).scheme.lower()
        if scheme not in ("http", "https"):
            return f"--trace-target must be a hostname or http(s) URL (got: {trace_target})"
        host = urllib.parse.urlparse(candidate).hostname
        if not host:
            return f"--trace-target has no hostname (got: {trace_target})"

    return None



def run_benchmark() -> int:
    """Main entry point supporting single run, continuous monitoring, and CLI flags."""
    parser = argparse.ArgumentParser(
        description=f"Network Speed & Diagnostic Benchmark Tool v{VERSION} by Shadowharvy",
        epilog="Examples:\n"
               "  speedtest.sh -n 3 --dns\n"
               "  speedtest.sh --engine cloudflare --threshold-dl 100\n"
               "  speedtest.sh --history --history-graph\n"
               "  speedtest.sh --json-stdout | jq .",
        formatter_class=argparse.RawDescriptionHelpFormatter
    )
    parser.add_argument("-n", "--runs", type=int, default=3, help="Number of benchmark iterations (default: 3, max: 20)")

    dns_group = parser.add_mutually_exclusive_group()
    dns_group.add_argument("--dns", action="store_true", default=True, help="Run background DNS & DoH resolution tests (default: enabled)")
    dns_group.add_argument("--no-dns", action="store_true", help="Explicitly disable DNS & DoH resolution tests")

    parser.add_argument("--engine", type=str, choices=["all", "speedtest", "ookla", "fast", "cloudflare", "custom"], default="all", help="Select speed engine filter (default: all)")
    parser.add_argument("--server", type=str, metavar="URL", help="Custom HTTP/HTTPS speedtest download URL to benchmark")
    parser.add_argument("--timeout", type=int, default=DOWNLOAD_TIMEOUT, metavar="SECS", help=f"Per-stream transfer timeout in seconds (default: {DOWNLOAD_TIMEOUT})")

    ip_group = parser.add_mutually_exclusive_group()
    ip_group.add_argument("-4", "--ipv4", action="store_true", help="Force IPv4 network requests")
    ip_group.add_argument("-6", "--ipv6", action="store_true", help="Force IPv6 network requests")

    parser.add_argument("--history", action="store_true", help="Display historical benchmark trends and averages")
    parser.add_argument("--history-graph", action="store_true", help="Render sparkline trend graph with history")
    parser.add_argument("--history-clear", action="store_true", help="Clear historical benchmark log file")

    html_group = parser.add_mutually_exclusive_group()
    html_group.add_argument("--html", type=str, nargs="?", const="report.html", default="report.html", metavar="FILE", help="Export standalone interactive HTML dashboard report (default: report.html)")
    html_group.add_argument("--no-html", action="store_true", help="Explicitly disable default HTML dashboard export")

    parser.add_argument("--markdown", type=str, metavar="FILE", help="Export GitHub-flavored Markdown summary report")

    open_group = parser.add_mutually_exclusive_group()
    open_group.add_argument("--open", action="store_true", default=True, help="Auto-open exported HTML report in browser after test (default: enabled)")
    open_group.add_argument("--no-open", action="store_true", help="Explicitly disable auto-opening HTML report in browser after test")

    parser.add_argument("--open-only", action="store_true", help="Open existing HTML report in preferred browser and exit without running benchmark")
    parser.add_argument("--json", type=str, metavar="FILE", help="Export results to a JSON file")
    parser.add_argument("--json-stdout", action="store_true", help="Output machine-readable JSON directly to stdout")
    parser.add_argument("--csv", type=str, metavar="FILE", help="Export results to a CSV file")
    parser.add_argument("--threshold-dl", type=float, metavar="MBPS", help="Minimum required download speed (exits with code 3 if violated)")
    parser.add_argument("--threshold-ul", type=float, metavar="MBPS", help="Minimum required upload speed (exits with code 3 if violated)")
    parser.add_argument("--threshold-ping", type=float, metavar="MS", help="Maximum acceptable ping latency (exits with code 3 if violated)")
    parser.add_argument("--monitor", type=int, metavar="MINS", help="Continuous monitoring mode interval in minutes")
    trace_group = parser.add_mutually_exclusive_group()
    trace_group.add_argument("--traceroute", action="store_true", default=True, help="Measure per-site DNS/TCP/TLS/TTFB timings (YouTube, Google, Amazon, etc.) plus hop-by-hop paths when a traceroute binary is available (default: enabled)")
    trace_group.add_argument("--no-traceroute", action="store_true", help="Explicitly skip traceroute-style site timing and hop traces")
    parser.add_argument("--trace-target", type=str, metavar="HOST", help="Probe only this host instead of the built-in popular-site list (implies timing data for it)")
    parser.add_argument("--trace-hops", type=int, default=TRACEROUTE_DEFAULT_MAX_HOPS, metavar="N", help=f"Maximum hops for path traces (default: {TRACEROUTE_DEFAULT_MAX_HOPS}, max: {TRACEROUTE_MAX_HOPS})")
    parser.add_argument("--trace-runs", type=int, default=SITE_TIMING_RUNS, metavar="N", help=f"Samples per site for median timing (default: {SITE_TIMING_RUNS}, max: 10)")
    parser.add_argument("--quiet", action="store_true", help="Suppress banner and live progress output")
    parser.add_argument("--no-color", action="store_true", help="Disable ANSI terminal colors")
    parser.add_argument("--debug", action="store_true", help="Enable debug logs for troubleshooting")
    parser.add_argument("--version", action="version", version=f"%(prog)s {VERSION}", help="Show version and exit")
    args = parser.parse_args()

    if getattr(args, "no_dns", False):
        args.dns = False

    if getattr(args, "no_traceroute", False):
        args.traceroute = False

    # --trace-target is only meaningful with the traceroute suite enabled.
    if getattr(args, "trace_target", None):
        args.traceroute = True

        # Normalize a URL down to just the hostname for probing.
        raw_target = args.trace_target
        args.trace_target = urllib.parse.urlparse(
            raw_target if "://" in raw_target else f"http://{raw_target}"
        ).hostname or raw_target

    if getattr(args, "no_html", False):
        args.html = None

    if getattr(args, "no_open", False) or args.json_stdout or args.monitor:
        args.open = False

    if args.json_stdout:
        args.quiet = True

    if args.no_color or args.json_stdout:
        C.disable()

    if getattr(args, "open_only", False):
        report_path = args.html if (args.html and not getattr(args, "no_html", False)) else "report.html"
        opened = open_browser_report(report_path, quiet=args.quiet, debug=args.debug)
        return 0 if opened else 1

    if args.history or args.history_clear:
        return display_history(clear=args.history_clear, no_color=args.no_color, show_graph=True)

    error = validate_args(args)
    if error:
        print(f"{C.RED}[!] Error: {error}{C.RESET}")
        return 1

    if not args.json_stdout:
        print_banner(args.quiet)

    if args.monitor:
        print(f"{C.CYAN}{C.BOLD}[i] Continuous Monitoring Mode Active (Interval: {args.monitor} mins). Press Ctrl+C to stop.{C.RESET}\n")
        cycle = 1
        consecutive_failures = 0
        while True:
            print(f"{C.MAGENTA}{C.BOLD}--- Monitoring Cycle #{cycle} [{datetime.now().strftime('%H:%M:%S')}] ---{C.RESET}")
            cycle_code = run_benchmark_cycle(args)
            # Exit 2 means no engine produced a measurement (e.g. all endpoints blocked).
            consecutive_failures = consecutive_failures + 1 if cycle_code == 2 else 0
            if consecutive_failures >= MAX_CONSECUTIVE_MONITOR_FAILURES:
                print(f"{C.RED}[!] Aborting monitoring: {consecutive_failures} consecutive cycles produced no measurements.{C.RESET}")
                return 2
            cycle += 1
            try:
                time.sleep(args.monitor * 60)
            except KeyboardInterrupt:
                print(f"\n{C.YELLOW}[!] Monitoring stopped by user after {cycle - 1} cycle(s){C.RESET}")
                return 0

    return run_benchmark_cycle(args)


if __name__ == "__main__":
    try:
        sys.exit(run_benchmark())
    except KeyboardInterrupt:
        print(f"\n{C.YELLOW}[!] Benchmark interrupted by user{C.RESET}")
        sys.exit(130)
    except Exception as e:
        print(f"{C.RED}[!] Unexpected error: {e}{C.RESET}")
