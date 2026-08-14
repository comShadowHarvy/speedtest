#!/usr/bin/env python3
"""
Network Speed Benchmark Tool
Author: Shadowharvy
Description: Cross-platform speed testing tool for Arch, Fedora, Debian, Termux, and Bazzite.
Features: Ping, Download, Upload, Jitter, ISP/Geo Detection, Connectivity Check, and Data Export.
"""

import argparse
import csv
import json
import re
import socket
import subprocess
import time
from datetime import datetime

# --- Constants & Styling ---
# Spoof a standard Google Chrome browser to bypass Corporate Firewall User-Agent filtering
USER_AGENT = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"

class C:
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
        """Disables colors for clean log output or --no-color flag."""
        cls.RESET = cls.BOLD = cls.CYAN = cls.GREEN = ""
        cls.YELLOW = cls.RED = cls.BLUE = cls.MAGENTA = cls.DIM = ""


def print_banner(quiet):
    if quiet: return
    print(f"\n{C.CYAN}{C.BOLD}===================================================={C.RESET}")
    print(f"{C.CYAN}{C.BOLD}             NETWORK SPEED BENCHMARK TOOL           {C.RESET}")
    print(f"{C.DIM}              Created by: {C.MAGENTA}{C.BOLD}Shadowharvy{C.RESET}")
    print(f"{C.CYAN}{C.BOLD}===================================================={C.RESET}\n")


def check_endpoints(quiet):
    """Performs a strict deep-API check with browser spoofing."""
    if not quiet:
        print(f"{C.BLUE}[i] Performing Pre-Flight Connectivity Check...{C.RESET}")
    
    st_ok = False
    fast_ok = False

    # Deep Check Speedtest.net
    try:
        res_st = subprocess.run(
            ["curl", "-s", "-L", "-A", USER_AGENT, "--max-time", "4", "https://www.speedtest.net/speedtest-config.php"], 
            capture_output=True, 
            text=True
        )
        if res_st.returncode == 0 and "client" in res_st.stdout:
            st_ok = True
    except Exception:
        pass

    # Deep Check Fast.com
    try:
        html = subprocess.run(["curl", "-s", "-L", "-A", USER_AGENT, "--max-time", "4", "https://fast.com"], capture_output=True, text=True).stdout
        js_path = re.search(r'src="(/app-[a-f0-9]+\.js)"', html)
        if js_path:
            js_url = f"https://fast.com{js_path.group(1)}"
            js_content = subprocess.run(["curl", "-s", "-L", "-A", USER_AGENT, "--max-time", "4", js_url], capture_output=True, text=True).stdout
            token = re.search(r'token:"([A-Za-z0-9]+)"', js_content)
            if token:
                api_url = f"https://api.fast.com/netflix/speedtest/v2?https=true&token={token.group(1)}&urlCount=1"
                api_res = subprocess.run(["curl", "-s", "-L", "-A", USER_AGENT, "--max-time", "4", api_url], capture_output=True, text=True).stdout
                if "targets" in api_res:
                    fast_ok = True
    except Exception:
        pass

    if not quiet:
        st_status = f"{C.GREEN}Accessible{C.RESET}" if st_ok else f"{C.RED}Blocked/Unreachable{C.RESET}"
        fast_status = f"{C.GREEN}Accessible{C.RESET}" if fast_ok else f"{C.RED}Blocked/Unreachable{C.RESET}"
        print(f"    {C.BOLD}Ookla (Speedtest):{C.RESET} {st_status}")
        print(f"    {C.BOLD}Netflix (Fast):{C.RESET}    {fast_status}\n")

    return st_ok, fast_ok


def get_lan_ip():
    """Gets the primary local LAN IP address."""
    try:
        s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        s.settimeout(2)
        s.connect(("1.1.1.1", 80))
        lan_ip = s.getsockname()[0]
        s.close()
        return lan_ip
    except Exception:
        return "Unavailable"


def get_geo_info():
    """Gets public IP, ISP, and Location using ip-api.com via curl with browser spoofing."""
    try:
        res = subprocess.run(
            ["curl", "-s", "-A", USER_AGENT, "--max-time", "5", "http://ip-api.com/json/"],
            capture_output=True,
            text=True,
        )
        if res.returncode == 0:
            data = json.loads(res.stdout)
            if data.get("status") == "success":
                return {
                    "ip": data.get("query", "Unavailable"),
                    "isp": data.get("isp", "Unknown ISP"),
                    "city": data.get("city", "Unknown"),
                    "country": data.get("country", "Unknown")
                }
    except Exception:
        pass
    return {"ip": "Unavailable", "isp": "Unknown", "city": "Unknown", "country": "Unknown"}


def get_speedtest():
    """Runs speedtest-cli and extracts ping, download, and upload speeds."""
    # speedtest-cli uses python urllib which usually gets past basic proxy filters, 
    # but we add --secure just in case it hits an HTTPS inspection proxy at work.
    try:
        res = subprocess.run(
            ["speedtest-cli", "--simple", "--secure"], capture_output=True, text=True, timeout=60
        )
        ping_m = re.search(r"Ping:\s*([0-9.]+)", res.stdout)
        dl_m = re.search(r"Download:\s*([0-9.]+)", res.stdout)
        ul_m = re.search(r"Upload:\s*([0-9.]+)", res.stdout)

        return {
            "ping": float(ping_m.group(1)) if ping_m else None,
            "download": float(dl_m.group(1)) if dl_m else None,
            "upload": float(ul_m.group(1)) if ul_m else None,
        }
    except Exception:
        return None


def get_fastcom():
    """Fetches fast.com download speed directly via curl, spoofing a browser."""
    try:
        html = subprocess.run(["curl", "-s", "-L", "-A", USER_AGENT, "https://fast.com"], capture_output=True, text=True, timeout=10).stdout
        js_path = re.search(r'src="(/app-[a-f0-9]+\.js)"', html)
        if not js_path: return None

        js_url = f"https://fast.com{js_path.group(1)}"
        js_content = subprocess.run(["curl", "-s", "-L", "-A", USER_AGENT, js_url], capture_output=True, text=True, timeout=10).stdout
        token = re.search(r'token:"([A-Za-z0-9]+)"', js_content)
        if not token: return None

        api_url = f"https://api.fast.com/netflix/speedtest/v2?https=true&token={token.group(1)}&urlCount=3"
        api_res = subprocess.run(["curl", "-s", "-L", "-A", USER_AGENT, api_url], capture_output=True, text=True, timeout=10).stdout
        data = json.loads(api_res)

        targets = [item["url"] for item in data.get("targets", [])]
        if not targets: return None

        start_time = time.time()
        # Ensure the actual file download request also uses the User Agent
        res = subprocess.run(["curl", "-s", "-L", "-A", USER_AGENT, "-r", "0-25000000", "-o", "/dev/null", targets[0]], timeout=15)
        elapsed = time.time() - start_time
        
        if elapsed > 0 and res.returncode == 0:
            mbps = (25000000 * 8) / (elapsed * 1000000)
            return {"download": round(mbps, 2)}
    except Exception:
        pass
    return None


def calculate_jitter(latency_list):
    """Calculates network jitter (average variance between successive tests)."""
    if len(latency_list) < 2: return 0.0
    diffs = [abs(latency_list[i] - latency_list[i - 1]) for i in range(1, len(latency_list))]
    return round(sum(diffs) / len(diffs), 2)


def run_benchmark():
    # --- Parse CLI Arguments ---
    parser = argparse.ArgumentParser(description="Network Speed Benchmark Tool by Shadowharvy")
    parser.add_argument("-n", "--runs", type=int, default=5, help="Number of benchmark iterations (default: 5)")
    parser.add_argument("--quiet", action="store_true", help="Suppress progress output, show only summary")
    parser.add_argument("--no-color", action="store_true", help="Disable ANSI color output")
    parser.add_argument("--json", type=str, metavar="FILE", help="Export results to a JSON file")
    parser.add_argument("--csv", type=str, metavar="FILE", help="Export results to a CSV file")
    args = parser.parse_args()

    if args.no_color:
        C.disable()

    print_banner(args.quiet)

    # --- Pre-Flight Checks ---
    st_ok, fast_ok = check_endpoints(args.quiet)

    # --- Fetching Network Info ---
    if not args.quiet: print(f"{C.BLUE}[i] Fetching Network Interfaces & Geolocation...{C.RESET}")
    lan_ip = get_lan_ip()
    geo = get_geo_info()
    
    if not args.quiet:
        print(f"    {C.BOLD}Local IP (LAN):{C.RESET} {C.YELLOW}{lan_ip}{C.RESET}")
        print(f"    {C.BOLD}Public IP (WAN):{C.RESET}{C.YELLOW}{geo['ip']}{C.RESET} ({geo['isp']} - {geo['city']}, {geo['country']})\n")

    st_results = []
    fast_results = []

    # --- 1. Speedtest.net ---
    if st_ok:
        if not args.quiet: print(f"{C.CYAN}{C.BOLD}--- Running Speedtest.net (Ookla) Benchmark ---{C.RESET}")
        for i in range(1, args.runs + 1):
            if not args.quiet: print(f"  Run {i}/{args.runs}... ", end="", flush=True)
            res = get_speedtest()
            if res and res.get("download"):
                st_results.append(res)
                if not args.quiet:
                    print(f"{C.GREEN}DL: {res['download']} Mbps{C.RESET} | {C.YELLOW}UL: {res['upload']} Mbps{C.RESET} {C.DIM}(Ping: {res['ping']}ms){C.RESET}")
            else:
                if not args.quiet: print(f"{C.RED}Failed (Skipped){C.RESET}")
            time.sleep(1)
    else:
        if not args.quiet: print(f"{C.RED}{C.BOLD}--- Skipping Speedtest.net (Blocked by Network) ---{C.RESET}")

    # --- 2. Fast.com ---
    if fast_ok:
        if not args.quiet: print(f"\n{C.CYAN}{C.BOLD}--- Running Fast.com (Netflix CDN) Benchmark ---{C.RESET}")
        for i in range(1, args.runs + 1):
            if not args.quiet: print(f"  Run {i}/{args.runs}... ", end="", flush=True)
            res = get_fastcom()
            if res and res.get("download"):
                fast_results.append(res)
                if not args.quiet:
                    print(f"{C.GREEN}DL: {res['download']} Mbps{C.RESET}")
            else:
                if not args.quiet: print(f"{C.RED}Failed (Skipped){C.RESET}")
            time.sleep(1)
    else:
        if not args.quiet: print(f"\n{C.RED}{C.BOLD}--- Skipping Fast.com (Blocked by Network) ---{C.RESET}")

    # --- Calculations ---
    st_dls = [r["download"] for r in st_results if r.get("download")]
    st_uls = [r["upload"] for r in st_results if r.get("upload")]
    st_pings = [r["ping"] for r in st_results if r.get("ping")]
    fast_dls = [r["download"] for r in fast_results if r.get("download")]

    st_dl_avg = round(sum(st_dls) / len(st_dls), 2) if st_dls else 0.0
    st_ul_avg = round(sum(st_uls) / len(st_uls), 2) if st_uls else 0.0
    fast_dl_avg = round(sum(fast_dls) / len(fast_dls), 2) if fast_dls else 0.0
    ping_avg = round(sum(st_pings) / len(st_pings), 2) if st_pings else 0.0
    jitter = calculate_jitter(st_pings) if st_pings else 0.0

    # --- Print Summary ---
    print(f"\n{C.MAGENTA}{C.BOLD}===================================================={C.RESET}")
    print(f"{C.MAGENTA}{C.BOLD}                  BENCHMARK SUMMARY                 {C.RESET}")
    print(f"{C.MAGENTA}{C.BOLD}===================================================={C.RESET}")
    print(f" {C.BOLD}Author:{C.RESET}         Shadowharvy")
    print(f" {C.BOLD}Local IP:{C.RESET}       {lan_ip}")
    print(f" {C.BOLD}Public IP:{C.RESET}      {geo['ip']} ({geo['isp']})")
    print(f" {C.BOLD}Location:{C.RESET}       {geo['city']}, {geo['country']}")
    print(f" {C.DIM}----------------------------------------------------{C.RESET}")
    
    if st_ok:
        print(f" {C.BOLD}Ookla Download:{C.RESET} {C.GREEN}{st_dl_avg} Mbps{C.RESET} {C.DIM}({len(st_dls)}/{args.runs}){C.RESET}")
        print(f" {C.BOLD}Ookla Upload:{C.RESET}   {C.GREEN}{st_ul_avg} Mbps{C.RESET}")
    else:
        print(f" {C.BOLD}Ookla Benchmark:{C.RESET} {C.RED}Blocked by Network{C.RESET}")

    if fast_ok:
        print(f" {C.BOLD}Fast Download:{C.RESET}  {C.GREEN}{fast_dl_avg} Mbps{C.RESET} {C.DIM}({len(fast_dls)}/{args.runs}){C.RESET}")
    else:
        print(f" {C.BOLD}Fast Benchmark:{C.RESET}  {C.RED}Blocked by Network{C.RESET}")
        
    print(f" {C.BOLD}Average Ping:{C.RESET}   {C.YELLOW}{ping_avg} ms{C.RESET}")
    print(f" {C.BOLD}Jitter:{C.RESET}         {C.YELLOW}{jitter} ms{C.RESET}")
    print(f"{C.MAGENTA}{C.BOLD}===================================================={C.RESET}\n")

    # --- Data Export Logic ---
    export_data = {
        "timestamp": datetime.now().isoformat(),
        "network": {"lan_ip": lan_ip, "geo": geo, "status": {"speedtest": "ok" if st_ok else "blocked", "fast": "ok" if fast_ok else "blocked"}},
        "averages": {
            "speedtest_download_mbps": st_dl_avg,
            "speedtest_upload_mbps": st_ul_avg,
            "fast_download_mbps": fast_dl_avg,
            "ping_ms": ping_avg,
            "jitter_ms": jitter
        },
        "raw_results": {"speedtest": st_results, "fast": fast_results}
    }

    if args.json:
        try:
            with open(args.json, "w") as f:
                json.dump(export_data, f, indent=4)
            if not args.quiet: print(f"{C.GREEN}[✔] JSON data exported to {args.json}{C.RESET}")
        except Exception as e:
            print(f"{C.RED}[!] Failed to write JSON: {e}{C.RESET}")

    if args.csv:
        try:
            with open(args.csv, "w", newline="") as f:
                writer = csv.writer(f)
                writer.writerow(["Engine", "Run", "Download (Mbps)", "Upload (Mbps)", "Ping (ms)"])
                for idx, r in enumerate(st_results):
                    writer.writerow(["Speedtest", idx + 1, r.get("download", ""), r.get("upload", ""), r.get("ping", "")])
                for idx, r in enumerate(fast_results):
                    writer.writerow(["Fast.com", idx + 1, r.get("download", ""), "", ""])
            if not args.quiet: print(f"{C.GREEN}[✔] CSV data exported to {args.csv}{C.RESET}")
        except Exception as e:
            print(f"{C.RED}[!] Failed to write CSV: {e}{C.RESET}")


if __name__ == "__main__":
    run_benchmark()