"""Speedtest engines."""

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
            fast_home = make_http_request("https://fast.com", timeout=HTTP_TIMEOUT, debug=debug, ip_version=ip_version)
            if not fast_home:
                raise ValueError("Failed to fetch fast.com homepage")

            js_path = JS_PATH_PATTERN.search(fast_home)
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
                        # Best-effort cleanup; file may already be gone.
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


