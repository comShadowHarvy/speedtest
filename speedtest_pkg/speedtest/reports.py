"""Export reports."""

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

def export_html_report(filepath: str, export_data: Dict[str, Any], debug: bool = False) -> bool:
    """Generates a state-of-the-art, interactive glassmorphism standalone HTML report dashboard."""
    try:
        ts = html.escape(str(export_data.get("timestamp", "")).replace("T", " ")[:19])
        ver = html.escape(str(export_data.get("version", VERSION)))
        net = export_data.get("network") or {}
        geo = net.get("geo") or {}
        adapter = net.get("adapter") or {}
        stats = export_data.get("statistics") or {}
        suitability = export_data.get("suitability") or {}
        # dns_recommendation is None when DNS testing is skipped/failed.
        dns_rec = export_data.get("dns_recommendation") or {}
        dns_data = export_data.get("dns") or {}

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
                    raw_history = json.load(f)
                if isinstance(raw_history, list):
                    recent_history = [e for e in raw_history[-10:] if isinstance(e, dict)]
            except Exception:
                # Malformed or unreadable history file; start with empty history.
                pass

        history_rows = ""
        for h in recent_history:
            h_ts = html.escape(str(h.get("timestamp", "")).replace("T", " ")[:16])
            h_stats = h.get("statistics") or {}
            try:
                h_dl = max(
                    float((h_stats.get("speedtest_download_mbps") or {}).get("avg", 0.0) or 0.0),
                    float((h_stats.get("fast_download_mbps") or {}).get("avg", 0.0) or 0.0),
                    float((h_stats.get("cloudflare_download_mbps") or {}).get("avg", 0.0) or 0.0),
                    float((h_stats.get("custom_download_mbps") or {}).get("avg", 0.0) or 0.0)
                )
            except (TypeError, ValueError):
                h_dl = 0.0
            h_ping = (h_stats.get("ping_ms") or {}).get("avg", 0.0)
            h_bb = html.escape(str((h_stats.get("bufferbloat") or {}).get("grade", "N/A")))
            h_score = html.escape(str((h.get("suitability") or {}).get("overall_score", "N/A")))
            history_rows += f"<tr><td>{h_ts}</td><td><strong>{h_dl:.1f} Mbps</strong></td><td>{h_ping:.1f} ms</td><td><span class='badge'>{h_bb}</span></td><td><strong>{h_score}/100</strong></td></tr>"

        dns_rows = ""
        for item in dns_rec.get("leaderboard", []):
            rank = item.get("rank", 1)
            rank_display = "🥇 1" if rank == 1 else ("🥈 2" if rank == 2 else ("🥉 3" if rank == 3 else f"#{rank}"))
            d_name = html.escape(str(item.get("name", "")))
            d_ip_raw = str(item.get("ip", ""))
            d_ip = html.escape(d_ip_raw)
            d_cat = html.escape(str(item.get("category", "")))
            try:
                d_lat = float(item.get("latency_ms", 0.0) or 0.0)
            except (TypeError, ValueError):
                d_lat = 0.0
            # The click handler is a JS string inside an HTML attribute: HTML-escaping
            # alone is not enough (the parser decodes &quot; back to " before JS sees
            # it), so JSON-encode the argument first and escape the result for HTML.
            d_ip_js = html.escape(json.dumps(d_ip_raw), quote=True)
            dns_rows += f"<tr><td><strong>{rank_display}</strong></td><td><strong>{d_name}</strong></td><td><code class='font-mono'>{d_ip}</code><button class='copy-ip-btn' onclick='copyText({d_ip_js})'>📋</button></td><td style='color:var(--accent-green)'><strong>{d_lat:.2f} ms</strong></td><td><span class='badge'>{d_cat}</span></td></tr>"

        # Site reachability timing rows (--traceroute). All values are host-provided,
        # so names/hosts/IPs are HTML-escaped and numbers are coerced defensively.
        # Site reachability tiles with a proportional phase-breakdown bar.
        # All text is host-provided, so names/hosts/IPs are HTML-escaped and
        # numeric fields are coerced so malformed data cannot break the report.
        site_timing_rows = ""
        for st in (export_data.get("site_timings") or []):
            st_name = html.escape(str(st.get("name", "?")))
            st_host = html.escape(str(st.get("host", "")))
            if not st.get("reachable"):
                site_timing_rows += (
                    f"<div class='site-tile down'>"
                    f"<div class='site-tile-head'><span class='site-name'>{st_name}</span>"
                    f"<span class='site-total' style='color:var(--accent-red)'>—</span></div>"
                    f"<div class='site-host'>{st_host}</div>"
                    f"<div class='site-phases' style='margin-top:8px'>"
                    f"<span class='badge badge-red'>Unreachable</span></div></div>"
                )
                continue

            def _f(key: str, _src: Dict[str, Any] = st) -> float:
                try:
                    return max(0.0, float(_src.get(key, 0.0) or 0.0))
                except (TypeError, ValueError):
                    return 0.0

            total = _f("total_ms")
            dns_v, tcp_v, tls_v, srv_v, ttfb_v = (_f("dns_ms"), _f("tcp_ms"),
                                                   _f("tls_ms"), _f("server_ms"), _f("ttfb_ms"))
            dl_v = max(0.0, total - ttfb_v)
            if total <= 0:
                t_color = "#ef4444"
            elif total < 300:
                t_color = "#10b981"
            elif total < 800:
                t_color = "#f59e0b"
            else:
                t_color = "#ef4444"

            # Scale bar segments against the total so the bar always fills exactly.
            denom = total if total > 0 else 1.0
            seg = ""
            for css_class, value in (("ph-dns", dns_v), ("ph-tcp", tcp_v),
                                     ("ph-tls", tls_v), ("ph-srv", srv_v), ("ph-dl", dl_v)):
                pct = (value / denom) * 100.0
                if pct <= 0:
                    continue
                seg += f"<span class='{css_class}' style='width:{pct:.2f}%'></span>"
            if not seg:
                seg = "<span class='ph-dl' style='width:100%'></span>"

            st_ip = html.escape(str(st.get("remote_ip", "")))
            code = int(_f("http_code"))
            site_timing_rows += (
                f"<div class='site-tile'>"
                f"<div class='site-tile-head'>"
                f"<span class='site-name'>{st_name}</span>"
                f"<span class='site-total' style='color:{t_color}'>{total:.0f} ms</span></div>"
                f"<div class='site-host'>{st_host} · {st_ip}</div>"
                f"<div class='phase-bar'>{seg}</div>"
                f"<div class='site-phases'>"
                f"<span>DNS <b>{dns_v:.0f}</b></span>"
                f"<span>TCP <b>{tcp_v:.0f}</b></span>"
                f"<span>TLS <b>{tls_v:.0f}</b></span>"
                f"<span>Server <b>{srv_v:.0f}</b></span>"
                f"<span>TTFB <b>{ttfb_v:.0f}</b></span>"
                f"<span class='badge'>HTTP {code}</span>"
                f"</div></div>"
            )

        traceroute_blocks = ""
        for tr in (export_data.get("traceroutes") or []):
            items = ""
            for hop in tr.get("hops", []):
                if hop.get("timeout") or hop.get("rtt_ms") is None:
                    items += (f"<li class='hop-node dead'>"
                              f"<span class='hop-dot'></span>"
                              f"<div class='hop-row'><span class='hop-num'>Hop {hop.get('hop')}</span>"
                              f"<span class='hop-addr' style='color:var(--text-dim)'>* * * no reply</span></div></li>")
                    continue
                try:
                    rtt = float(hop["rtt_ms"])
                except (TypeError, ValueError):
                    rtt = 0.0
                if rtt < 30:
                    cls, r_color = "", "#10b981"
                elif rtt < 100:
                    cls, r_color = "warn", "#f59e0b"
                else:
                    cls, r_color = "bad", "#ef4444"
                addr = html.escape(str(hop.get("ip") or "?"))
                items += (f"<li class='hop-node {cls}'>"
                          f"<span class='hop-dot'></span>"
                          f"<div class='hop-row'>"
                          f"<span class='hop-num'>Hop {hop.get('hop')}</span>"
                          f"<code class='hop-addr font-mono'>{addr}</code>"
                          f"<span class='hop-rtt' style='color:{r_color}'>{rtt:.2f} ms</span>"
                          f"</div></li>")
            traceroute_blocks += (
                f"<div class='hop-wrap'>"
                f"<div class='hop-title'>🗺️ Hop-by-Hop Path to {html.escape(str(tr.get('host', '')))}"
                f"<span class='badge badge-purple'>{tr.get('responding_hops', 0)}/{tr.get('hop_count', 0)} hops"
                f" · {html.escape(str(tr.get('tool', '?')))}</span></div>"
                f"<ol class='hop-list'>{items}</ol></div>"
            )

        score_color = "#10b981" if score >= 85 else ("#06b6d4" if score >= 70 else ("#f59e0b" if score >= 50 else "#ef4444"))
        score_circumference = 314.16
        dash_offset = score_circumference - (score_circumference * (score / 100.0))

        # Embed benchmark data as a JS literal that cannot terminate the surrounding
        # <script> block or inject template literals/JS strings downstream:
        # escape <, >, & and the JS line separators, which are invalid in string literals.
        raw_json_escaped = (
            json.dumps(export_data)
            .replace("<", "\\u003c")
            .replace(">", "\\u003e")
            .replace("&", "\\u0026")
            .replace("\u2028", "\\u2028")
            .replace("\u2029", "\\u2029")
        )

        # JS string literal (double-quoted, escaped) for values used inside template
        # literals below, so backticks/${} in host-provided data cannot break out.
        js_ts = json.dumps(ts)
        js_tier = json.dumps(str(tier))

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
        tbody tr {{ transition: background 0.15s ease; }}
        tbody tr:nth-child(even) {{ background: rgba(148, 163, 184, 0.045); }}
        tbody tr:hover {{ background: rgba(6, 182, 212, 0.07); }}
        th.num, td.num {{ text-align: right; font-variant-numeric: tabular-nums; }}

        /* Site reachability tiles with a proportional phase-breakdown bar */
        .site-grid {{ display: grid; grid-template-columns: repeat(auto-fill, minmax(260px, 1fr)); gap: 14px; margin-top: 6px; }}
        .site-tile {{
            background: var(--chip-bg); border: 1px solid var(--card-border);
            border-radius: 14px; padding: 14px 15px; transition: border-color .2s ease, transform .2s ease;
        }}
        .site-tile:hover {{ border-color: var(--card-hover-border); transform: translateY(-2px); }}
        .site-tile.down {{ border-color: rgba(239, 68, 68, 0.45); background: rgba(239, 68, 68, 0.07); }}
        .site-tile-head {{ display: flex; justify-content: space-between; align-items: baseline; gap: 10px; }}
        .site-name {{ font-weight: 800; font-size: 15px; letter-spacing: -0.2px; }}
        .site-total {{ font-weight: 900; font-size: 17px; font-variant-numeric: tabular-nums; }}
        .site-host {{ font-size: 11px; color: var(--text-dim); margin-top: 2px; word-break: break-all; }}
        .phase-bar {{
            display: flex; height: 9px; border-radius: 9999px; overflow: hidden;
            margin: 11px 0 8px; background: var(--gauge-track);
        }}
        .phase-bar span {{ display: block; height: 100%; }}
        .ph-dns {{ background: #38bdf8; }}
        .ph-tcp {{ background: #10b981; }}
        .ph-tls {{ background: #a78bfa; }}
        .ph-srv {{ background: #f59e0b; }}
        .ph-dl  {{ background: rgba(148, 163, 184, 0.45); }}
        .site-phases {{ display: flex; flex-wrap: wrap; gap: 4px 12px; font-size: 11px; color: var(--text-dim); }}
        .site-phases b {{ color: var(--text-main); font-variant-numeric: tabular-nums; }}
        .legend {{ display: flex; flex-wrap: wrap; gap: 6px 16px; margin-top: 14px; font-size: 11px; color: var(--text-dim); }}
        .legend i {{ display: inline-block; width: 9px; height: 9px; border-radius: 3px; margin-right: 6px; vertical-align: middle; }}

        /* Hop-by-hop vertical timeline */
        .hop-wrap {{ margin-top: 18px; }}
        .hop-title {{ font-weight: 700; font-size: 14px; margin-bottom: 10px; display: flex; align-items: center; gap: 8px; flex-wrap: wrap; }}
        .hop-list {{ list-style: none; margin: 0; padding: 0 0 0 6px; }}
        .hop-node {{ position: relative; padding: 0 0 14px 30px; }}
        .hop-node::before {{
            content: ''; position: absolute; left: 5px; top: 16px; bottom: -2px;
            width: 2px; background: linear-gradient(180deg, var(--card-border), transparent);
        }}
        .hop-node:last-child::before {{ display: none; }}
        .hop-dot {{
            position: absolute; left: 0; top: 5px; width: 12px; height: 12px; border-radius: 50%;
            background: var(--accent-cyan); border: 2px solid var(--card-bg);
            box-shadow: 0 0 0 2px rgba(6, 182, 212, 0.25);
        }}
        .hop-node.warn .hop-dot {{ background: var(--accent-yellow); box-shadow: 0 0 0 2px rgba(245, 158, 11, 0.25); }}
        .hop-node.bad .hop-dot {{ background: var(--accent-red); box-shadow: 0 0 0 2px rgba(239, 68, 68, 0.25); }}
        .hop-node.dead .hop-dot {{ background: var(--text-dim); box-shadow: none; }}
        .hop-row {{ display: flex; align-items: center; gap: 10px; flex-wrap: wrap; }}
        .hop-num {{ font-size: 11px; color: var(--text-dim); font-weight: 700; min-width: 26px; }}
        .hop-addr {{ font-size: 13px; font-weight: 600; word-break: break-all; }}
        .hop-rtt {{ margin-left: auto; font-size: 13px; font-weight: 800; font-variant-numeric: tabular-nums; }}
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
                <p>Generated: <strong>{ts}</strong> | Tool: <strong>v{ver}</strong> | Host ISP: <strong>{html.escape(str(geo.get("isp", "Local Network")))}</strong></p>
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
                <div class="info-row"><span class="info-label">Public WAN IP:</span><span class="info-val font-mono">{html.escape(str(geo.get("ip", "N/A")))}</span></div>
                {f'<div class="info-row"><span class="info-label">Public IPv6:</span><span class="info-val font-mono">{html.escape(str(geo.get("ipv6")))}</span></div>' if geo.get("ipv6") and geo.get("ipv6") != "Unavailable" else ''}
                <div class="info-row"><span class="info-label">ISP & Location:</span><span class="info-val">{html.escape(str(geo.get("isp", "Unknown")))} ({html.escape(str(geo.get("city", "")))}, {html.escape(str(geo.get("country", "")))})</span></div>
                <div class="info-row"><span class="info-label">Interface:</span><span class="info-val font-mono">{html.escape(str(adapter.get("interface", "Unknown")))} ({html.escape(str(adapter.get("interface_type", "Ethernet")))})</span></div>
                <div class="info-row"><span class="info-label">Hardware Link Speed:</span><span class="info-val" style="color:var(--accent-green)">{html.escape(str(adapter.get("link_speed", "N/A")))}</span></div>
                {f'<div class="info-row"><span class="info-label">Wi-Fi Network:</span><span class="info-val">{html.escape(str(adapter.get("wifi_ssid")))} ({html.escape(str(adapter.get("wifi_signal")))})</span></div>' if adapter.get("wifi_ssid") not in ("N/A (Wired/Unknown)", "N/A") else ''}
                {f'<div class="info-row"><span class="info-label">Wi-Fi Band:</span><span class="info-val">{html.escape(str(adapter.get("wifi_frequency")))}</span></div>' if adapter.get("wifi_frequency") not in ("N/A", "") else ''}
                <div class="info-row"><span class="info-label">Local Gateway IP:</span><span class="info-val font-mono">{html.escape(str(adapter.get("gateway", "N/A")))}</span></div>
                <div class="info-row"><span class="info-label">Interface MTU:</span><span class="info-val font-mono">{html.escape(str(adapter.get("mtu", "1500")))}</span></div>
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
        <!-- Site Reachability Timing (--traceroute) -->
        <div class="card" style="margin-bottom: 26px;">
            <div class="card-title">🧭 Site Reachability Timing (Traceroute-Style)</div>
            <div class="site-grid">{site_timing_rows}</div>
            <div class="legend">
                <span><i class="ph-dns"></i>DNS</span>
                <span><i class="ph-tcp"></i>TCP connect</span>
                <span><i class="ph-tls"></i>TLS handshake</span>
                <span><i class="ph-srv"></i>Server think</span>
                <span><i class="ph-dl"></i>Content transfer</span>
            </div>
            {traceroute_blocks}
        </div>
        ''' if site_timing_rows else ''}

        {f'''
        <!-- DNS Resolution Leaderboard & Profiles -->
        <div class="card" style="margin-bottom: 26px;">
            <div class="card-title">DNS Resolution Leaderboard & Latency Ranking</div>
            <table>
                <thead>
                    <tr><th>Rank</th><th>Resolver Name</th><th>IP Address</th><th>Avg Latency</th><th>Category / Best For</th></tr>
                </thead>
                <tbody>{dns_rows}</tbody>
            </table>

            <div style="background: rgba(139, 92, 246, 0.08); border: 1px solid rgba(139, 92, 246, 0.35); border-radius: 16px; padding: 20px; margin-top: 24px;">
                <div style="font-weight: 800; font-size: 16px; margin-bottom: 8px; color: var(--accent-purple);">
                    🏆 Recommended DNS Configurations for Your Network
                </div>
                <p style="margin: 0 0 16px 0; color: var(--text-dim); font-size: 14px;">{html.escape(str(dns_rec.get("status_message", "")))}</p>
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
        const REPORT_TS = {js_ts};
        const REPORT_TIER = {js_tier};
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
            const summary = `🚀 Network Speed Benchmark Report\\n📅 Date: ${{REPORT_TS}}\\n⚡ Max Download: {actual_max_dl:.2f} Mbps | Upload: ${{ulStr}}\\n📶 Ping: {ping} ms | Jitter: {jitter} ms | Loss: {packet_loss}%\\n🛡️ Bufferbloat: {bb.get("grade", "N/A")} (+{bb.get("delta_ms", 0)}ms)\\n⭐ Quality Score: {score}/100 (${{REPORT_TIER}})`;
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



def md_escape(value: Any) -> str:
    """Make a value safe for Markdown tables and inline code spans.

    Host-provided strings (ISP, Wi-Fi SSID, DNS names) can contain pipes that
    break table layout, or backticks/newlines that break inline code spans.
    """
    s = str(value)
    s = s.replace("\\", "\\\\").replace("|", "\\|").replace("\r\n", " ").replace("\n", " ").replace("\r", " ")
    s = s.replace("`", "'")
    return s



def export_markdown_report(filepath: str, export_data: Dict[str, Any], debug: bool = False) -> bool:
    """Generates a structured GitHub-flavored Markdown report."""
    try:
        dir_name = os.path.dirname(os.path.abspath(filepath))
        if dir_name:
            os.makedirs(dir_name, exist_ok=True)
        ts = str(export_data.get("timestamp", "")).replace("T", " ")[:19]
        ver = md_escape(export_data.get("version", VERSION))
        net = export_data.get("network") or {}
        geo = net.get("geo") or {}
        adapter = net.get("adapter") or {}
        stats = export_data.get("statistics") or {}
        suitability = export_data.get("suitability") or {}
        dns_rec = export_data.get("dns_recommendation") or {}

        m_isp = md_escape(geo.get("isp", "Unknown"))
        m_ip = md_escape(geo.get("ip", "N/A"))
        m_tier = md_escape(suitability.get("speed_tier", "N/A"))
        m_iface = md_escape(adapter.get("interface", "Unknown"))
        m_iface_type = md_escape(adapter.get("interface_type", "Ethernet"))
        m_link = md_escape(adapter.get("link_speed", "N/A"))
        m_gw = md_escape(adapter.get("gateway", "N/A"))
        m_mtu = md_escape(adapter.get("mtu", "1500"))
        m_status = md_escape(dns_rec.get("status_message", ""))
        m_gaming = md_escape(suitability.get("gaming", {}).get("status", "N/A"))
        m_streaming = md_escape(suitability.get("streaming", {}).get("status", "N/A"))
        m_calls = md_escape(suitability.get("video_call", {}).get("status", "N/A"))
        m_ssid = md_escape(adapter.get("wifi_ssid"))
        m_signal = md_escape(adapter.get("wifi_signal"))
        m_freq = md_escape(adapter.get("wifi_frequency"))

        # DNS leaderboard table, built with escaped cells so resolver names/IPs
        # containing pipes cannot break the table layout.
        md_dns_table = ""
        if dns_rec:
            medals = {1: "🥇 1", 2: "🥈 2", 3: "🥉 3"}
            rows = ["| Rank | Resolver | IP Address | Latency | Category / Best For |",
                    "| :---: | :--- | :--- | :---: | :--- |"]
            for idx, item in enumerate(dns_rec.get("leaderboard", []), start=1):
                try:
                    lat = float(item.get("latency_ms", 0.0) or 0.0)
                except (TypeError, ValueError):
                    lat = 0.0
                rank_label = medals.get(idx, f"#{idx}")
                rows.append(
                    f"| {rank_label} | **{md_escape(item.get('name', ''))}** | "
                    f"`{md_escape(item.get('ip', ''))}` | **{lat:.2f} ms** | "
                    f"{md_escape(item.get('category', ''))} |"
                )
            md_dns_table = "\n".join(rows) + "\n"

        # Site reachability timing section (--traceroute).
        md_trace_section = ""
        site_timings = export_data.get("site_timings") or []
        if site_timings:
            trace_lines = ["## 🧭 Site Reachability Timing (Traceroute-Style)", "",
                           "| Site | Host | Edge IP | DNS | TCP | TLS | Server | Total | Status |",
                           "| :--- | :--- | :--- | ---: | ---: | ---: | ---: | ---: | :--- |"]

            def _num(entry: Dict[str, Any], key: str) -> float:
                try:
                    return float(entry.get(key, 0.0) or 0.0)
                except (TypeError, ValueError):
                    return 0.0

            for st in site_timings:
                if not st.get("reachable"):
                    trace_lines.append(
                        f"| **{md_escape(st.get('name', '?'))}** | `{md_escape(st.get('host', ''))}` | "
                        f"| | | | | | | **Unreachable** |"
                    )
                    continue
                total = _num(st, "total_ms")
                if total < 300:
                    verdict = "Excellent"
                elif total < 800:
                    verdict = "Fair"
                else:
                    verdict = "Slow"
                trace_lines.append(
                    f"| **{md_escape(st.get('name', '?'))}** | `{md_escape(st.get('host', ''))}` | "
                    f"`{md_escape(st.get('remote_ip', ''))}` | {_num(st, 'dns_ms'):.1f} ms | "
                    f"{_num(st, 'tcp_ms'):.1f} ms | {_num(st, 'tls_ms'):.1f} ms | "
                    f"{_num(st, 'server_ms'):.1f} ms | **{total:.1f} ms** | {verdict} |"
                )

            for tr in (export_data.get("traceroutes") or []):
                trace_lines += ["", f"### 🗺️ Hop-by-Hop Path to {md_escape(tr.get('host', ''))}",
                                f"_via {md_escape(tr.get('tool', '?'))}: "
                                f"{tr.get('responding_hops', 0)}/{tr.get('hop_count', 0)} hops responded_", "",
                                "| Hop | Address | RTT |", "| ---: | :--- | ---: |"]
                for hop in tr.get("hops", []):
                    if hop.get("timeout") or hop.get("rtt_ms") is None:
                        trace_lines.append(f"| {hop.get('hop')} | `*` | no reply |")
                    else:
                        trace_lines.append(
                            f"| {hop.get('hop')} | `{md_escape(hop.get('ip') or '?')}` | {float(hop['rtt_ms']):.2f} ms |")

            md_trace_section = "\n".join(trace_lines) + "\n"

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
- **Public IP (WAN):** `{m_ip}` ({m_isp})
- **Speed Tier:** **{m_tier}**
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

- **Interface:** `{m_iface}` ({m_iface_type})
- **Link Speed:** `{m_link}`
- **Gateway IP:** `{m_gw}`
- **Interface MTU:** `{m_mtu}`
{f'- **Wi-Fi SSID & Signal:** `{m_ssid}` ({m_signal})' if adapter.get("wifi_ssid") not in ("N/A (Wired/Unknown)", "N/A") else ''}
{f'- **Wi-Fi Frequency:** `{m_freq}`' if adapter.get("wifi_frequency") not in ("N/A", "") else ''}

---

## 🎮 Real-World Readiness

- **Gaming:** {m_gaming} ({suitability.get("gaming", {}).get("score", 0)}/100)
- **4K/8K Streaming:** {m_streaming} ({suitability.get("streaming", {}).get("score", 0)}/100)
- **Video Calls:** {m_calls} ({suitability.get("video_call", {}).get("score", 0)}/100)

{md_trace_section}
---

## 💡 DNS Resolution Leaderboard & Recommendations

{md_dns_table if dns_rec else "- *DNS resolution benchmarking skipped.*"}
### 🏆 Recommended Profiles for Your Network:
- **🚀 Best for Speed & Privacy:** **{dns_rec.get('profiles', {}).get('best_speed_privacy', {}).get('name', 'Cloudflare')}** (Primary: `{dns_rec.get('profiles', {}).get('best_speed_privacy', {}).get('primary')}`, Secondary: `{dns_rec.get('profiles', {}).get('best_speed_privacy', {}).get('secondary')}` | IPv6: `{dns_rec.get('profiles', {}).get('best_speed_privacy', {}).get('ipv6_primary')}`)
- **🛡️ Best for Security & Threat Blocking:** **Quad9** (Primary: `{dns_rec.get('profiles', {}).get('best_security', {}).get('primary', '9.9.9.9')}`, Secondary: `{dns_rec.get('profiles', {}).get('best_security', {}).get('secondary', '149.112.112.112')}` | IPv6: `2620:fe::fe`)
- **🚫 Best for Ad & Tracker Blocking:** **AdGuard** (Primary: `{dns_rec.get('profiles', {}).get('best_adblocking', {}).get('primary', '94.140.14.14')}`, Secondary: `{dns_rec.get('profiles', {}).get('best_adblocking', {}).get('secondary', '94.140.15.15')}` | IPv6: `2a10:50c0::ad1:ff`)
- **🌐 Best for Anycast Reliability:** **Google** (Primary: `{dns_rec.get('profiles', {}).get('best_reliability', {}).get('primary', '8.8.8.8')}`, Secondary: `{dns_rec.get('profiles', {}).get('best_reliability', {}).get('secondary', '8.8.4.4')}` | IPv6: `2001:4860:4860::8888`)
- **⚡ Status:** {m_status}

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



def export_json_report(filepath: str, export_data: Dict[str, Any], debug: bool = False) -> bool:
    """Exports structured benchmark results to a formatted JSON file."""
    try:
        dir_name = os.path.dirname(os.path.abspath(filepath))
        if dir_name:
            os.makedirs(dir_name, exist_ok=True)
        with open(filepath, "w") as f:
            json.dump(export_data, f, indent=4)
        return True
    except Exception as e:
        if debug:
            print(f"{C.YELLOW}[DEBUG] Failed to write JSON report: {e}{C.RESET}")
        return False



def export_csv_report(
    filepath: str,
    st_results: List[Dict[str, Any]],
    fast_results: List[Dict[str, Any]],
    cf_results: List[Dict[str, Any]],
    custom_results: List[Dict[str, Any]],
    debug: bool = False
) -> bool:
    """Exports raw per-iteration speed benchmark measurements to a CSV file."""
    try:
        dir_name = os.path.dirname(os.path.abspath(filepath))
        if dir_name:
            os.makedirs(dir_name, exist_ok=True)
        with open(filepath, "w", newline="") as f:
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
        return True
    except Exception as e:
        if debug:
            print(f"{C.YELLOW}[DEBUG] Failed to write CSV report: {e}{C.RESET}")
        return False



def get_preferred_browser() -> Tuple[Optional[List[str]], str]:
    """Determine preferred browser command based on what is installed:
    1. Firefox
    2. Brave
    3. Google Chrome / Chromium
    4. System default (open/xdg-open)
    Returns: (command_args_list, display_name)
    """
    # 1. Firefox
    if shutil.which("firefox"):
        return ["firefox"], "Firefox"

    # 2. Brave
    for cmd in ["brave", "brave-browser"]:
        if shutil.which(cmd):
            return [cmd], "Brave"

    # 3. Google Chrome / Chromium
    for cmd in ["google-chrome", "google-chrome-stable", "chromium", "chromium-browser"]:
        if shutil.which(cmd):
            return [cmd], "Google Chrome"

    # macOS application bundle fallbacks
    if sys.platform == "darwin":
        if os.path.exists("/Applications/Firefox.app"):
            return ["open", "-a", "Firefox"], "Firefox"
        if os.path.exists("/Applications/Brave Browser.app"):
            return ["open", "-a", "Brave Browser"], "Brave"
        if os.path.exists("/Applications/Google Chrome.app"):
            return ["open", "-a", "Google Chrome"], "Google Chrome"
        return ["open"], "default browser"

    # Linux / BSD fallback
    if shutil.which("xdg-open"):
        return ["xdg-open"], "default browser"

    return None, "default browser"



def open_browser_report(filepath: str, quiet: bool = False, debug: bool = False) -> bool:
    """Open exported HTML report in Firefox, Brave, or Google Chrome based on what is installed."""
    try:
        abs_path = os.path.abspath(filepath)
        if not os.path.exists(abs_path):
            if not quiet:
                print(f"{C.RED}[!] HTML report file not found: {abs_path}{C.RESET}")
            return False

        browser_cmd, browser_name = get_preferred_browser()
        if browser_cmd:
            cmd = browser_cmd + [abs_path]
            if not quiet:
                print(f" {C.GREEN}[✔] Opening HTML report in {browser_name}...{C.RESET}")

            subprocess.Popen(
                cmd,
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
                start_new_session=True,
            )
            return True
        else:
            import webbrowser
            if not quiet:
                print(f" {C.GREEN}[✔] Opening HTML report in default browser...{C.RESET}")
            webbrowser.open(f"file://{abs_path}")
            return True
    except Exception as e:
        if debug:
            print(f"{C.YELLOW}[DEBUG] Failed to open browser: {e}{C.RESET}")
        return False


