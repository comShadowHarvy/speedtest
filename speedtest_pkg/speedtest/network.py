"""Network adapter, geo, endpoints."""

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

def check_endpoints(quiet: bool, debug: bool = False, ip_version: Optional[str] = None) -> Tuple[bool, bool, bool]:
    """Performs pre-flight connectivity checks for Ookla, Fast.com, and Cloudflare."""
    if not quiet:
        print(f"{C.BLUE}[i] Performing Pre-Flight Endpoint Probes...{C.RESET}")

    st_ok, fast_ok, cf_ok = False, False, False

    # Check Ookla
    res_st = make_http_request("https://www.speedtest.net/speedtest-config.php", timeout=CHECK_TIMEOUT, debug=debug, ip_version=ip_version)
    if res_st and "client" in res_st:
        st_ok = True

    # Check Fast.com (note: avoid naming this "html", which shadows the html module)
    fast_home = make_http_request("https://fast.com", timeout=CHECK_TIMEOUT, debug=debug, ip_version=ip_version)
    if fast_home:
        js_path = JS_PATH_PATTERN.search(fast_home)
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
        # iproute2 (ip) not installed; fallback to macOS route command below.
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
            # macOS route command not available; interface stays "Unknown".
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
                # sysfs read failed (permission/system error); keep any prior value or N/A.
                pass

        # MTU from sysfs (Linux)
        mtu_file = f"/sys/class/net/{iface}/mtu"
        if os.path.exists(mtu_file):
            try:
                with open(mtu_file, "r") as f:
                    info["mtu"] = f.read().strip()
            except Exception:
                # sysfs read failed; MTU stays as default or N/A.
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
            # iw not installed or failed to parse link info; fall through to nmcli/iwconfig.
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
                # nmcli not installed or failed; fall through to iwconfig/macOS airport.
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
                # iwconfig not installed or failed to parse; fall through to macOS airport.
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
                # airport binary not present; fallback to /proc/net/wireless for signal.
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
                # Cannot read /proc/net/wireless (e.g., permission); signal stays N/A.
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
                # ifconfig unavailable on this macOS; MTU stays at default 1500.
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


GEO_PROVIDERS = (
    # (url, ip_version) - HTTPS providers first: plain HTTP to a geo endpoint leaks
    # the user's WAN IP in cleartext to the network/ISP.
    ("https://ipwho.is/", None),
    ("http://ip-api.com/json/?fields=status,message,country,countryCode,regionName,city,isp,org,as,query", "4"),
)



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

    # Primary geolocation: try each provider until one returns usable data.
    for url, forced_v4 in GEO_PROVIDERS:
        try:
            res = make_http_request(
                url,
                timeout=HTTP_TIMEOUT,
                debug=debug,
                ip_version=forced_v4 if forced_v4 else ip_version
            )
            if not res:
                continue
            data = json.loads(res)
            if not isinstance(data, dict):
                continue

            if url.startswith("https://ipwho.is"):
                if not data.get("success", True):
                    continue
                conn = data.get("connection") or {}
                geo["ip"] = data.get("ip", "Unavailable")
                geo["isp"] = conn.get("isp") or data.get("isp") or "Unknown ISP"
                geo["org"] = conn.get("org") or data.get("org") or "Unknown"
                geo["city"] = data.get("city", "Unknown")
                geo["country"] = data.get("country", "Unknown")
                geo["country_code"] = data.get("country_code", "N/A")
            else:
                if data.get("status") != "success":
                    continue
                geo["ip"] = data.get("query", "Unavailable")
                geo["isp"] = data.get("isp", "Unknown ISP")
                geo["org"] = data.get("org", data.get("isp", "Unknown"))
                geo["city"] = data.get("city", "Unknown")
                geo["country"] = data.get("country", "Unknown")
                geo["country_code"] = data.get("countryCode", "N/A")

            if geo["ip"] != "Unavailable":
                break
        except Exception as e:
            # Provider failed or returned malformed JSON; try next provider.
            if debug:
                print(f"{C.YELLOW}[DEBUG] Geo lookup via {url.split('?')[0]} failed: {e}{C.RESET}")

    # Fallback IPv4 if needed
    if geo["ip"] == "Unavailable":
        try:
            ip_str = make_http_request("https://api.ipify.org?format=json", timeout=3, debug=debug, ip_version="4")
            if ip_str:
                parsed = json.loads(ip_str)
                if isinstance(parsed, dict):
                    geo["ip"] = parsed.get("ip", "Unavailable")
        except Exception:
            pass

            pass
    # IPv6 detection probe
    try:
        res_v6 = make_http_request("https://api64.ipify.org?format=json", timeout=3, debug=debug, ip_version="6")
        if res_v6:
            parsed_v6 = json.loads(res_v6)
            v6_val = parsed_v6.get("ip", "") if isinstance(parsed_v6, dict) else ""
            if ":" in v6_val:
                geo["ipv6"] = v6_val
    except Exception:
        # IPv6 probe failed (no IPv6 route / no DNS); IPv6 geo stays unknown.
        pass

    return geo


