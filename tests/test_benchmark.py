#!/usr/bin/env python3
"""
Unit tests for Network Speed Benchmark Tool (speedtest.sh)
"""

import csv
import io
import json
import os
import re
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import MagicMock, call, mock_open, patch

# Add parent directory to sys.path
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

# Import functions from speedtest.sh using modern importlib.util loader
import importlib.util
from importlib.machinery import SourceFileLoader

script_path = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "speedtest.sh"))
loader = SourceFileLoader("speedtest", script_path)
spec = importlib.util.spec_from_loader("speedtest", loader)
if spec is None:
    raise ImportError(f"Cannot create module spec for {script_path}")
speedtest = importlib.util.module_from_spec(spec)
sys.modules["speedtest"] = speedtest
loader.exec_module(speedtest)


class TestStatistics(unittest.TestCase):
    def test_empty_list(self):
        stats = speedtest.calculate_statistics([])
        self.assertEqual(stats, {"min": 0.0, "max": 0.0, "avg": 0.0, "median": 0.0})

    def test_single_value(self):
        stats = speedtest.calculate_statistics([100.5])
        self.assertEqual(stats, {"min": 100.5, "max": 100.5, "avg": 100.5, "median": 100.5})

    def test_odd_length_list(self):
        stats = speedtest.calculate_statistics([10.0, 30.0, 20.0])
        self.assertEqual(stats["min"], 10.0)
        self.assertEqual(stats["max"], 30.0)
        self.assertEqual(stats["avg"], 20.0)
        self.assertEqual(stats["median"], 20.0)

    def test_even_length_list(self):
        stats = speedtest.calculate_statistics([10.0, 20.0, 30.0, 40.0])
        self.assertEqual(stats["min"], 10.0)
        self.assertEqual(stats["max"], 40.0)
        self.assertEqual(stats["avg"], 25.0)
        self.assertEqual(stats["median"], 25.0)

    def test_precision_rounding(self):
        stats = speedtest.calculate_statistics([10.1234, 20.5678])
        self.assertEqual(stats["min"], 10.12)
        self.assertEqual(stats["max"], 20.57)


class TestJitterCalculation(unittest.TestCase):
    def test_empty_or_single_item(self):
        self.assertEqual(speedtest.calculate_jitter([]), 0.0)
        self.assertEqual(speedtest.calculate_jitter([15.0]), 0.0)

    def test_multiple_items(self):
        # Latencies: 10, 15, 12 -> diffs: |15-10|=5, |12-15|=3 -> avg = 4.0
        self.assertEqual(speedtest.calculate_jitter([10.0, 15.0, 12.0]), 4.0)

    def test_identical_values(self):
        self.assertEqual(speedtest.calculate_jitter([20.0, 20.0, 20.0]), 0.0)


class TestBufferbloatGrade(unittest.TestCase):
    def test_grades(self):
        cases = [
            (20.0, 23.0, "A+", 3.0),
            (20.0, 25.0, "A+", 5.0),
            (20.0, 32.0, "A", 12.0),
            (20.0, 35.0, "A", 15.0),
            (20.0, 45.0, "B", 25.0),
            (20.0, 50.0, "B", 30.0),
            (20.0, 75.0, "C", 55.0),
            (20.0, 80.0, "C", 60.0),
            (20.0, 110.0, "D", 90.0),
            (20.0, 120.0, "D", 100.0),
            (20.0, 180.0, "F", 160.0),
        ]
        for unloaded, loaded, expected_grade, expected_delta in cases:
            with self.subTest(unloaded=unloaded, loaded=loaded):
                grade, delta = speedtest.calculate_bufferbloat_grade(unloaded, loaded)
                self.assertEqual(grade, expected_grade)
                self.assertEqual(delta, expected_delta)

    def test_negative_or_zero_delta(self):
        # When loaded latency is lower than or equal to unloaded latency
        grade, delta = speedtest.calculate_bufferbloat_grade(25.0, 20.0)
        self.assertEqual(grade, "A+")
        self.assertEqual(delta, 0.0)


class TestDirectionalBufferbloat(unittest.TestCase):
    def test_directional_metrics(self):
        unloaded = 15.0
        dl_pings = [18.0, 20.0, 19.0]  # avg ~19.0 (+4ms -> A+)
        ul_pings = [45.0, 50.0, 55.0]  # avg ~50.0 (+35ms -> C)
        bb = speedtest.calculate_directional_bufferbloat(unloaded, dl_pings, ul_pings)
        self.assertEqual(bb["unloaded_ping_ms"], 15.0)
        self.assertEqual(bb["download_grade"], "A+")
        self.assertEqual(bb["upload_grade"], "C")
        self.assertEqual(bb["grade"], "C")
        self.assertEqual(bb["download_delta_ms"], 4.0)
        self.assertEqual(bb["upload_delta_ms"], 35.0)

    def test_directional_empty_samples(self):
        unloaded = 20.0
        bb = speedtest.calculate_directional_bufferbloat(unloaded, [], [])
        self.assertEqual(bb["download_grade"], "A+")
        self.assertEqual(bb["upload_grade"], "A+")
        self.assertEqual(bb["grade"], "A+")
        self.assertEqual(bb["delta_ms"], 0.0)


class TestSpeedTier(unittest.TestCase):
    def test_speed_tiers(self):
        cases = [
            (2500, "Multi-Gigabit"),
            (1000, "Gigabit"),
            (500, "Ultra-Fast"),
            (150, "High-Speed"),
            (50, "Standard"),
            (15, "Entry-Level"),
            (5, "Basic / Low-Speed"),
        ]
        for mbps, expected in cases:
            with self.subTest(mbps=mbps):
                self.assertIn(expected, speedtest.get_speed_tier(mbps))


class TestNetworkSuitability(unittest.TestCase):
    def test_perfect_connection(self):
        suitability = speedtest.calculate_network_suitability(
            dl_mbps=1000.0, ul_mbps=500.0, ping_ms=5.0, jitter_ms=1.0, bb_grade="A+", packet_loss_pct=0.0
        )
        self.assertEqual(suitability["overall_score"], 100.0)
        self.assertIn("Excellent", suitability["gaming"]["status"])
        self.assertIn("Flawless", suitability["streaming"]["status"])
        self.assertIn("Studio Quality", suitability["video_call"]["status"])

    def test_poor_connection(self):
        suitability = speedtest.calculate_network_suitability(
            dl_mbps=3.0, ul_mbps=1.0, ping_ms=150.0, jitter_ms=35.0, bb_grade="F", packet_loss_pct=5.0
        )
        self.assertLess(suitability["overall_score"], 50.0)
        self.assertIn("Poor", suitability["gaming"]["status"])

    def test_zero_bandwidth(self):
        suitability = speedtest.calculate_network_suitability(
            dl_mbps=0.0, ul_mbps=0.0, ping_ms=0.0, jitter_ms=0.0, bb_grade="N/A", packet_loss_pct=100.0
        )
        self.assertEqual(suitability["overall_score"], 35.0)


class TestSparkline(unittest.TestCase):
    def test_sparkline_generation(self):
        values = [10.0, 50.0, 100.0, 25.0, 80.0]
        spark = speedtest.generate_sparkline(values)
        self.assertEqual(len(spark), len(values))
        self.assertEqual(spark[0], " ")
        self.assertEqual(spark[2], "█")

    def test_sparkline_empty_or_identical(self):
        self.assertEqual(speedtest.generate_sparkline([]), "")
        self.assertEqual(speedtest.generate_sparkline([50.0, 50.0, 50.0]), "▄▄▄")


class TestDNSQueryBuilder(unittest.TestCase):
    def test_dns_packet_structure_a(self):
        packet = speedtest.build_dns_query("google.com", "A", txid=b"\xaa\xbb")
        self.assertTrue(len(packet) > 12)
        # Header ID
        self.assertEqual(packet[:2], b"\xaa\xbb")
        # Recursion desired flag set
        self.assertEqual(packet[2:4], b"\x01\x00")
        # Contains google and com length bytes
        self.assertIn(b"\x06google\x03com\x00", packet)
        # Type A suffix
        self.assertTrue(packet.endswith(b"\x00\x01\x00\x01"))

    def test_dns_packet_structure_aaaa(self):
        packet = speedtest.build_dns_query("cloudflare.com", "AAAA", txid=b"\xaa\xbb")
        self.assertTrue(len(packet) > 12)
        self.assertEqual(packet[:2], b"\xaa\xbb")
        # Type AAAA (28 = 0x001c)
        self.assertTrue(packet.endswith(b"\x00\x1c\x00\x01"))

    def test_dns_subdomains(self):
        packet = speedtest.build_dns_query("sub.domain.example.com", "A")
        self.assertIn(b"\x03sub\x06domain\x07example\x03com\x00", packet)

    def test_random_transaction_id_per_query(self):
        ids = {speedtest.build_dns_query("example.com", "A")[:2] for _ in range(20)}
        self.assertGreater(len(ids), 1, "transaction IDs must not be fixed")


class TestDNSResponseValidation(unittest.TestCase):
    def _reply(self, txid=b"\x12\x34", flags=0x8180, body=b"", ancount=1):
        return txid + flags.to_bytes(2, "big") + b"\x00\x01" + ancount.to_bytes(2, "big") + b"\x00\x00\x00\x00" + body

    def test_accepts_matching_noerror_response(self):
        self.assertTrue(speedtest.is_valid_dns_response(self._reply(), b"\x12\x34"))

    def test_rejects_mismatched_transaction_id(self):
        self.assertFalse(speedtest.is_valid_dns_response(self._reply(txid=b"\x99\x99"), b"\x12\x34"))

    def test_rejects_query_packet_echo(self):
        # QR bit clear -> it is a query, not a response
        query = speedtest.build_dns_query("example.com", "A", txid=b"\x12\x34")
        self.assertFalse(speedtest.is_valid_dns_response(query, b"\x12\x34"))

    def test_rejects_error_rcodes(self):
        for rcode in (1, 2, 3, 5):  # FORMERR, SERVFAIL, NXDOMAIN, REFUSED
            flags = 0x8180 | rcode
            self.assertFalse(speedtest.is_valid_dns_response(self._reply(flags=flags), b"\x12\x34"))

    def test_rejects_short_datagram(self):
        self.assertFalse(speedtest.is_valid_dns_response(b"\x12\x34\x81", b"\x12\x34"))

    def test_get_dns_latency_ignores_stale_reply(self):
        stale = self._reply(txid=b"\x00\x00")
        sock = MagicMock()
        sock.recvfrom.return_value = (stale, ("1.1.1.1", 53))
        with patch("socket.socket", return_value=sock):
            result = speedtest.get_dns_latency({"name": "CF", "ip": "1.1.1.1"}, "example.com")
        self.assertIsNone(result)
        sock.close.assert_called_once()

    def test_get_dns_latency_accepts_valid_reply(self):
        sock = MagicMock()
        # Echo back the transaction ID of the query that was actually sent.
        def echo(query, addr):
            sock.recvfrom.return_value = (speedtest.build_dns_query("example.com", "A", txid=query[:2])[:2] + b"\x81\x80\x00\x01\x00\x01\x00\x00\x00\x00", addr)
            return MagicMock()
        sock.sendto.side_effect = echo
        with patch("socket.socket", return_value=sock):
            result = speedtest.get_dns_latency({"name": "CF", "ip": "1.1.1.1"}, "example.com")
        self.assertIsNotNone(result)
        self.assertGreaterEqual(result, 0.0)


class TestFastestDNSRecommendation(unittest.TestCase):
    def test_recommendation_calculation(self):
        mock_dns = {
            "dns_resolvers": {
                "Cloudflare": {"resolver_ip": "1.1.1.1", "latency_ms": {"avg": 10.0}},
                "Google": {"resolver_ip": "8.8.8.8", "latency_ms": {"avg": 20.0}},
                "SlowDNS": {"resolver_ip": "10.0.0.1", "latency_ms": {"avg": 50.0}},
            }
        }
        rec = speedtest.get_fastest_dns_recommendation(mock_dns)
        self.assertIsNotNone(rec)
        self.assertEqual(rec["name"], "Cloudflare")
        self.assertEqual(rec["primary"], "1.1.1.1")
        self.assertEqual(rec["secondary"], "1.0.0.1")
        self.assertEqual(rec["slowest_name"], "SlowDNS")
        self.assertEqual(rec["savings_pct"], 80.0)
        self.assertIn("1.1.1.1", rec["status_message"])

    def test_empty_dns_results(self):
        self.assertIsNone(speedtest.get_fastest_dns_recommendation(None))
        self.assertIsNone(speedtest.get_fastest_dns_recommendation({"dns_resolvers": {}}))


class TestDNSProfiles(unittest.TestCase):
    def test_profiles_structure(self):
        mock_dns = {
            "dns_resolvers": {
                "Cloudflare": {"resolver_ip": "1.1.1.1", "latency_ms": {"avg": 8.0}},
                "Quad9": {"resolver_ip": "9.9.9.9", "latency_ms": {"avg": 12.0}},
                "AdGuard": {"resolver_ip": "94.140.14.14", "latency_ms": {"avg": 15.0}},
                "CleanBrowsing": {"resolver_ip": "185.228.168.168", "latency_ms": {"avg": 20.0}},
            }
        }
        rec = speedtest.get_fastest_dns_recommendation(mock_dns)
        self.assertIn("profiles", rec)
        profiles = rec["profiles"]
        self.assertIn("best_speed_privacy", profiles)
        self.assertIn("best_security", profiles)
        self.assertIn("best_adblocking", profiles)
        self.assertIn("best_reliability", profiles)
        self.assertEqual(profiles["best_security"]["name"], "Quad9")
        self.assertEqual(profiles["best_adblocking"]["name"], "AdGuard")
        self.assertEqual(profiles["best_reliability"]["name"], "Google")


class TestPrintDNSLeaderboard(unittest.TestCase):
    def test_print_leaderboard_output(self):
        mock_dns = {
            "dns_resolvers": {
                "Cloudflare": {"resolver_ip": "1.1.1.1", "latency_ms": {"avg": 8.0}},
                "Quad9": {"resolver_ip": "9.9.9.9", "latency_ms": {"avg": 12.0}},
            }
        }
        rec = speedtest.get_fastest_dns_recommendation(mock_dns)
        buf = io.StringIO()
        with patch("sys.stdout", buf):
            speedtest.print_dns_leaderboard(rec)
        out = buf.getvalue()
        self.assertIn("DNS RESOLUTION LEADERBOARD", out)
        self.assertIn("Cloudflare", out)
        self.assertIn("Quad9", out)
        self.assertIn("Best for Speed & Privacy", out)


class TestGeoInfo(unittest.TestCase):
    IPWHO_OK = json.dumps({
        "success": True, "ip": "1.2.3.4", "city": "Ottawa",
        "country": "Canada", "country_code": "CA",
        "connection": {"isp": "ExampleISP", "org": "ExampleOrg", "asn": 64500},
    })
    IPAPI_OK = json.dumps({
        "status": "success", "query": "5.6.7.8", "city": "Toronto",
        "country": "Canada", "countryCode": "CA",
        "isp": "LegacyISP", "org": "LegacyOrg",
    })

    def _route(self, mapping):
        def side_effect(url, **kwargs):
            for frag, payload in mapping.items():
                if frag in url:
                    return payload
            return None
        return side_effect

    def test_prefers_https_provider(self):
        with patch("speedtest.make_http_request", side_effect=self._route({"ipwho.is": self.IPWHO_OK})):
            geo = speedtest.get_geo_info()
        self.assertEqual(geo["ip"], "1.2.3.4")
        self.assertEqual(geo["isp"], "ExampleISP")
        self.assertEqual(geo["org"], "ExampleOrg")
        self.assertEqual(geo["country_code"], "CA")

    def test_falls_back_to_legacy_provider(self):
        with patch("speedtest.make_http_request", side_effect=self._route({"ip-api.com": self.IPAPI_OK})):
            geo = speedtest.get_geo_info()
        self.assertEqual(geo["ip"], "5.6.7.8")
        self.assertEqual(geo["isp"], "LegacyISP")

    def test_skips_provider_reporting_failure(self):
        failed = json.dumps({"success": False, "message": "quota exceeded"})
        with patch("speedtest.make_http_request", side_effect=self._route({"ipwho.is": failed, "ip-api.com": self.IPAPI_OK})):
            geo = speedtest.get_geo_info()
        self.assertEqual(geo["ip"], "5.6.7.8")

    def test_all_providers_fail_returns_defaults(self):
        with patch("speedtest.make_http_request", return_value=None):
            geo = speedtest.get_geo_info()
        self.assertEqual(geo["ip"], "Unavailable")
        self.assertEqual(geo["ipv6"], "Unavailable")

    def test_malformed_json_does_not_raise(self):
        with patch("speedtest.make_http_request", return_value="<html>not json</html>"):
            geo = speedtest.get_geo_info()
        self.assertEqual(geo["ip"], "Unavailable")

    def test_https_provider_is_tried_first(self):
        self.assertTrue(speedtest.GEO_PROVIDERS[0][0].startswith("https://"))


class TestModuleShadowing(unittest.TestCase):
    """Local variables must never shadow the stdlib modules the tool relies on."""

    IMPORTED_MODULES = ("argparse", "csv", "html", "json", "os", "re", "shutil",
                        "socket", "subprocess", "sys", "tempfile", "threading", "time")

    def test_no_local_variable_shadows_import(self):
        import ast
        with open(speedtest.__file__, "r") as f:
            tree = ast.parse(f.read())
        offenders = []
        for node in ast.walk(tree):
            if not isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
                continue
            for child in ast.walk(node):
                targets = []
                if isinstance(child, ast.Assign):
                    targets = child.targets
                elif isinstance(child, (ast.AnnAssign, ast.NamedExpr)):
                    targets = [child.target]
                for t in targets:
                    for sub in ast.walk(t):
                        if isinstance(sub, ast.Name) and sub.id in self.IMPORTED_MODULES:
                            offenders.append(f"{node.name}: {sub.id}")
        self.assertEqual(offenders, [], f"shadowed module names: {offenders}")

    def test_html_module_still_usable_after_endpoint_checks(self):
        with patch("speedtest.make_http_request", return_value="<html></html>"):
            speedtest.check_endpoints(quiet=True)
        self.assertEqual(speedtest.html.escape("<b>"), "&lt;b&gt;")


class TestReportsExport(unittest.TestCase):
    def setUp(self):
        self.test_data = {
            "timestamp": "2026-09-13T12:00:00.000000",
            "version": "3.2.0",
            "network": {
                "lan_ip": "192.168.1.50",
                "lan_ipv6": "Unavailable",
                "geo": {"ip": "1.2.3.4", "isp": "Test ISP", "city": "City", "country": "Country"},
                "adapter": {
                    "interface": "eth0",
                    "gateway": "192.168.1.1",
                    "link_speed": "1.0 Gbps",
                    "interface_type": "Ethernet",
                    "wifi_ssid": "N/A",
                    "wifi_signal": "N/A",
                    "mtu": "1500",
                },
            },
            "statistics": {
                "speedtest_download_mbps": {"avg": 500.0, "min": 480.0, "max": 520.0, "median": 500.0},
                "speedtest_upload_mbps": {"avg": 250.0, "min": 240.0, "max": 260.0, "median": 250.0},
                "fast_download_mbps": {"avg": 490.0},
                "cloudflare_download_mbps": {"avg": 510.0},
                "cloudflare_upload_mbps": {"avg": 260.0},
                "custom_download_mbps": {"avg": 0.0},
                "ping_ms": {"avg": 8.5},
                "jitter_ms": 1.2,
                "packet_loss_pct": 0.0,
                "bufferbloat": {
                    "grade": "A+",
                    "delta_ms": 2.1,
                    "unloaded_ping_ms": 8.5,
                    "loaded_ping_ms": 10.6,
                    "download_loaded_ping_ms": 9.5,
                    "download_delta_ms": 1.0,
                    "download_grade": "A+",
                    "upload_loaded_ping_ms": 10.6,
                    "upload_delta_ms": 2.1,
                    "upload_grade": "A+",
                },
            },
            "suitability": {
                "overall_score": 98.0,
                "speed_tier": "Ultra-Fast Broadband",
                "gaming": {"status": "Excellent (Competitive)", "score": 98.0},
                "streaming": {"status": "Flawless (4K/8K)", "score": 100.0},
                "video_call": {"status": "Studio Quality", "score": 96.0},
            },
            "dns_recommendation": {
                "name": "Cloudflare",
                "ip": "1.1.1.1",
                "primary": "1.1.1.1",
                "secondary": "1.0.0.1",
                "ipv6_primary": "2606:4700:4700::1111",
                "latency_ms": 5.2,
                "savings_pct": 50.0,
                "features": "Fastest response time, strict privacy",
                "status_message": "Switch to Cloudflare for 50.0% faster resolution.",
                "leaderboard": [
                    {"rank": 1, "name": "Cloudflare", "ip": "1.1.1.1", "latency_ms": 5.2, "category": "Ultra-Fast & Privacy"},
                    {"rank": 2, "name": "Google", "ip": "8.8.8.8", "latency_ms": 8.1, "category": "Global Anycast"},
                ],
                "profiles": {
                    "best_speed_privacy": {"name": "Cloudflare", "primary": "1.1.1.1", "secondary": "1.0.0.1", "ipv6_primary": "2606:4700:4700::1111"},
                    "best_security": {"name": "Quad9", "primary": "9.9.9.9", "secondary": "149.112.112.112"},
                    "best_adblocking": {"name": "AdGuard", "primary": "94.140.14.14", "secondary": "94.140.15.15"},
                },
            },
            "dns": {
                "dns_resolvers": {
                    "Cloudflare": {"resolver_ip": "1.1.1.1", "latency_ms": {"avg": 5.2, "min": 4.8, "max": 5.8}},
                    "Google": {"resolver_ip": "8.8.8.8", "latency_ms": {"avg": 8.1, "min": 7.5, "max": 9.0}},
                }
            },
        }

    def test_export_html_report(self):
        with tempfile.NamedTemporaryFile(suffix=".html", delete=False) as tf:
            tf_path = tf.name
        try:
            with patch("speedtest.HISTORY_FILE", "/nonexistent/history.json"):
                success = speedtest.export_html_report(tf_path, self.test_data)
            self.assertTrue(success)
            self.assertTrue(os.path.exists(tf_path))
            with open(tf_path, "r") as f:
                content = f.read()
                self.assertIn("Network Speed Benchmark", content)
                self.assertIn("500.00 Mbps", content)
                self.assertIn("Cloudflare", content)
                self.assertIn("Directional Bufferbloat", content)
        finally:
            if os.path.exists(tf_path):
                os.unlink(tf_path)

    def test_export_html_report_with_history(self):
        mock_history = [
            {
                "timestamp": "2026-09-20T10:00:00",
                "statistics": {"speedtest_download_mbps": {"avg": 600.0}, "ping_ms": {"avg": 7.0}, "bufferbloat": {"grade": "A+"}},
                "suitability": {"overall_score": 99.0},
            }
        ]
        with tempfile.NamedTemporaryFile(suffix=".html", delete=False) as tf, \
             tempfile.NamedTemporaryFile(suffix=".json", delete=False) as hf:
            tf_path = tf.name
            hf_path = hf.name
            with open(hf_path, "w") as f:
                json.dump(mock_history, f)
        try:
            with patch("speedtest.HISTORY_FILE", hf_path):
                success = speedtest.export_html_report(tf_path, self.test_data)
            self.assertTrue(success)
            with open(tf_path, "r") as f:
                content = f.read()
            self.assertIn("600.0 Mbps", content)
            self.assertIn("Recent Historical Benchmark Runs", content)
        finally:
            if os.path.exists(tf_path):
                os.unlink(tf_path)
            if os.path.exists(hf_path):
                os.unlink(hf_path)

    def test_export_html_report_xss_escaping(self):
        malicious_data = json.loads(json.dumps(self.test_data))
        malicious_data["network"]["geo"]["isp"] = "<script>alert('xss-isp')</script>"
        malicious_data["network"]["adapter"]["wifi_ssid"] = "Evil\"<WiFi>&"
        malicious_data["dns_recommendation"]["status_message"] = "Notice <b>bold</b> & dangerous"

        with tempfile.NamedTemporaryFile(suffix=".html", delete=False) as tf:
            tf_path = tf.name
        try:
            with patch("speedtest.HISTORY_FILE", "/nonexistent/history.json"):
                success = speedtest.export_html_report(tf_path, malicious_data)
            self.assertTrue(success)
            with open(tf_path, "r") as f:
                content = f.read()
            html_body = content.split("<script>")[0]
            # Assert tags are escaped in the HTML body
            self.assertNotIn("<script>alert('xss-isp')</script>", html_body)
            self.assertIn("&lt;script&gt;alert(&#x27;xss-isp&#x27;)&lt;/script&gt;", html_body)
            self.assertIn("Evil&quot;&lt;WiFi&gt;&amp;", html_body)
            self.assertIn("Notice &lt;b&gt;bold&lt;/b&gt; &amp; dangerous", html_body)
        finally:
            if os.path.exists(tf_path):
                os.unlink(tf_path)

    def test_export_html_report_zero_upload(self):
        data = json.loads(json.dumps(self.test_data))
        data["statistics"]["speedtest_upload_mbps"] = {"avg": 0.0, "min": 0.0, "max": 0.0}
        data["statistics"]["cloudflare_upload_mbps"] = {"avg": 0.0}
        with tempfile.NamedTemporaryFile(suffix=".html", delete=False) as tf:
            tf_path = tf.name
        try:
            with patch("speedtest.HISTORY_FILE", "/nonexistent/history.json"):
                success = speedtest.export_html_report(tf_path, data)
            self.assertTrue(success)
            with open(tf_path, "r") as f:
                content = f.read()
                self.assertNotIn("1.00 Mbps", content)
                self.assertIn("N/A", content)
        finally:
            if os.path.exists(tf_path):
                os.unlink(tf_path)

    def test_export_html_report_script_block_injection(self):
        # A </script> inside host-provided data must not terminate the data island.
        data = json.loads(json.dumps(self.test_data))
        data["network"]["geo"]["isp"] = "</script><script>alert('pwned')</script>"
        data["network"]["geo"]["city"] = "</SCRIPT ><img src=x onerror=alert(1)>"
        with tempfile.NamedTemporaryFile(suffix=".html", delete=False) as tf:
            tf_path = tf.name
        try:
            with patch("speedtest.HISTORY_FILE", "/nonexistent/history.json"):
                self.assertTrue(speedtest.export_html_report(tf_path, data))
            with open(tf_path, "r") as f:
                content = f.read()
            script_blocks = re.findall(r"<script>(.*?)</script>", content, re.DOTALL)
            self.assertTrue(script_blocks)
            # Exactly one script element: the payload never terminates the data island.
            self.assertEqual(content.count("<script>"), 1)
            self.assertEqual(content.count("</script>"), 1)
            self.assertIn("\\u003c/script\\u003e", content)
        finally:
            if os.path.exists(tf_path):
                os.unlink(tf_path)

    def test_export_html_report_dns_copy_button_is_js_safe(self):
        data = json.loads(json.dumps(self.test_data))
        data["dns_recommendation"]["leaderboard"] = [{
            "rank": 1,
            "name": "Evil",
            "ip": "1.1.1.1'+alert(1)+'",
            "latency_ms": 5.0,
            "category": "Public",
        }]
        with tempfile.NamedTemporaryFile(suffix=".html", delete=False) as tf:
            tf_path = tf.name
        try:
            with patch("speedtest.HISTORY_FILE", "/nonexistent/history.json"):
                self.assertTrue(speedtest.export_html_report(tf_path, data))
            with open(tf_path, "r") as f:
                content = f.read()
            m = re.search(r"onclick='copyText\((.*?)\)'", content)
            self.assertIsNotNone(m, "copy button handler missing")
            # The argument must round-trip through JSON as a single literal string.
            self.assertEqual(json.loads(m.group(1).replace("&quot;", '"').replace("&#x27;", "'")), "1.1.1.1'+alert(1)+'")
        finally:
            if os.path.exists(tf_path):
                os.unlink(tf_path)

    def test_export_html_report_summary_template_injection(self):
        # Backticks/${} in the speed tier must not break out of the JS template literal.
        data = json.loads(json.dumps(self.test_data))
        data["suitability"]["speed_tier"] = "Evil`);alert(1);//"
        with tempfile.NamedTemporaryFile(suffix=".html", delete=False) as tf:
            tf_path = tf.name
        try:
            with patch("speedtest.HISTORY_FILE", "/nonexistent/history.json"):
                self.assertTrue(speedtest.export_html_report(tf_path, data))
            with open(tf_path, "r") as f:
                content = f.read()
            m = re.search(r'const REPORT_TIER = ("(?:[^"\\]|\\.)*");', content)
            self.assertIsNotNone(m)
            self.assertEqual(json.loads(m.group(1)), "Evil`);alert(1);//")
        finally:
            if os.path.exists(tf_path):
                os.unlink(tf_path)

    def test_export_markdown_report(self):
        with tempfile.NamedTemporaryFile(suffix=".md", delete=False) as tf:
            tf_path = tf.name
        try:
            success = speedtest.export_markdown_report(tf_path, self.test_data)
            self.assertTrue(success)
            self.assertTrue(os.path.exists(tf_path))
            with open(tf_path, "r") as f:
                content = f.read()
                self.assertIn("# Network Speed Benchmark Report", content)
                self.assertIn("500.00 Mbps", content)
                self.assertIn("Directional Bufferbloat", content)
        finally:
            if os.path.exists(tf_path):
                os.unlink(tf_path)

    def test_md_escape_neutralizes_table_breaking_values(self):
        self.assertEqual(speedtest.md_escape("a|b"), "a\\|b")
        self.assertEqual(speedtest.md_escape("line1\nline2"), "line1 line2")
        self.assertEqual(speedtest.md_escape("cr\r\nlf"), "cr lf")
        self.assertEqual(speedtest.md_escape("back`tick"), "back'tick")
        self.assertEqual(speedtest.md_escape("back\\slash"), "back\\\\slash")
        self.assertEqual(speedtest.md_escape(42), "42")

    def test_markdown_report_escapes_host_values(self):
        data = json.loads(json.dumps(self.test_data))
        data["network"]["geo"]["isp"] = "Evil|ISP"
        data["network"]["adapter"]["wifi_ssid"] = "My|SSID"
        data["dns_recommendation"]["leaderboard"] = [
            {"rank": 1, "name": "Pipe|Name", "ip": "1.1.1.1", "latency_ms": 5.0, "category": "Fast|Secure"}
        ]
        with tempfile.NamedTemporaryFile(suffix=".md", delete=False) as tf:
            tf_path = tf.name
        try:
            self.assertTrue(speedtest.export_markdown_report(tf_path, data))
            with open(tf_path, "r") as f:
                content = f.read()
            self.assertIn("Evil\\|ISP", content)
            self.assertIn("Pipe\\|Name", content)
            self.assertIn("Fast\\|Secure", content)
        finally:
            if os.path.exists(tf_path):
                os.unlink(tf_path)

    def test_markdown_report_creates_missing_directories(self):
        with tempfile.TemporaryDirectory() as td:
            target = os.path.join(td, "nested", "deeper", "report.md")
            self.assertTrue(speedtest.export_markdown_report(target, self.test_data))
            self.assertTrue(os.path.exists(target))

    def test_markdown_report_handles_non_string_timestamp(self):
        data = json.loads(json.dumps(self.test_data))
        data["timestamp"] = None
        with tempfile.NamedTemporaryFile(suffix=".md", delete=False) as tf:
            tf_path = tf.name
        try:
            self.assertTrue(speedtest.export_markdown_report(tf_path, data))
        finally:
            if os.path.exists(tf_path):
                os.unlink(tf_path)

    def test_markdown_report_non_numeric_dns_latency(self):
        data = json.loads(json.dumps(self.test_data))
        data["dns_recommendation"]["leaderboard"] = [
            {"rank": 1, "name": "X", "ip": "1.1.1.1", "latency_ms": "n/a", "category": "C"}
        ]
        with tempfile.NamedTemporaryFile(suffix=".md", delete=False) as tf:
            tf_path = tf.name
        try:
            self.assertTrue(speedtest.export_markdown_report(tf_path, data))
            with open(tf_path, "r") as f:
                self.assertIn("0.00 ms", f.read())
        finally:
            if os.path.exists(tf_path):
                os.unlink(tf_path)

    def _export_both_with_missing_sections(self, data):
        results = []
        for suffix, fn in ((".md", speedtest.export_markdown_report), (".html", speedtest.export_html_report)):
            with tempfile.NamedTemporaryFile(suffix=suffix, delete=False) as tf:
                path = tf.name
            try:
                with patch("speedtest.HISTORY_FILE", "/nonexistent/history.json"):
                    results.append((fn(path, data), path))
            finally:
                pass
        return results

    def test_exports_handle_null_dns_recommendation(self):
        # --no-dns stores dns_recommendation as None; exporters must not crash.
        data = json.loads(json.dumps(self.test_data))
        data["dns_recommendation"] = None
        for ok, path in self._export_both_with_missing_sections(data):
            self.assertTrue(ok, f"export failed for {path}")
            with open(path, "r") as f:
                content = f.read()
            # HTML omits the DNS section entirely; Markdown states it was skipped.
            if path.endswith(".html"):
                self.assertNotIn("DNS Resolution Leaderboard", content)
            else:
                self.assertIn("DNS resolution benchmarking skipped", content)
            os.unlink(path)

    def test_exports_handle_null_top_level_sections(self):
        data = json.loads(json.dumps(self.test_data))
        for key in ("network", "statistics", "suitability", "dns_recommendation"):
            data[key] = None
        data["network"] = {"geo": None, "adapter": None}
        for ok, path in self._export_both_with_missing_sections(data):
            self.assertTrue(ok, f"export failed for {path}")
            os.unlink(path)

    def test_export_json_report(self):
        with tempfile.NamedTemporaryFile(suffix=".json", delete=False) as tf:
            tf_path = tf.name
        try:
            success = speedtest.export_json_report(tf_path, self.test_data)
            self.assertTrue(success)
            with open(tf_path, "r") as f:
                loaded = json.load(f)
            self.assertEqual(loaded["version"], "3.2.0")
            self.assertEqual(loaded["suitability"]["overall_score"], 98.0)
        finally:
            if os.path.exists(tf_path):
                os.unlink(tf_path)

    def test_export_json_report_failure(self):
        # Invalid directory path
        success = speedtest.export_json_report("/proc/nonexistent/sub/report.json", self.test_data)
        self.assertFalse(success)

    def test_export_csv_report(self):
        st_res = [{"download": 500.0, "upload": 250.0, "ping": 8.5, "jitter": 1.2, "dl_latency": 9.5, "ul_latency": 10.6}]
        fast_res = [{"download": 490.0}]
        cf_res = [{"download": 510.0, "upload": 260.0}]
        custom_res = [{"download": 0.0}]

        with tempfile.NamedTemporaryFile(suffix=".csv", delete=False) as tf:
            tf_path = tf.name
        try:
            success = speedtest.export_csv_report(tf_path, st_res, fast_res, cf_res, custom_res)
            self.assertTrue(success)
            with open(tf_path, "r") as f:
                reader = list(csv.reader(f))
            self.assertEqual(reader[0], ["Engine", "Run", "Download (Mbps)", "Upload (Mbps)", "Ping (ms)", "Jitter (ms)", "DL_Latency (ms)", "UL_Latency (ms)"])
            self.assertEqual(reader[1][0], "Speedtest")
            self.assertEqual(reader[2][0], "Fast.com")
            self.assertEqual(reader[3][0], "Cloudflare")
            self.assertEqual(reader[4][0], "Custom")
        finally:
            if os.path.exists(tf_path):
                os.unlink(tf_path)

    def test_export_csv_report_failure(self):
        success = speedtest.export_csv_report("/proc/nonexistent/sub/report.csv", [], [], [], [])
        self.assertFalse(success)


class TestSaveHistoryRecord(unittest.TestCase):
    def test_save_creates_new_file(self):
        with tempfile.TemporaryDirectory() as td:
            hf = os.path.join(td, "history.json")
            with patch.object(speedtest, "HISTORY_FILE", hf):
                record = {"run": 1, "score": 95}
                speedtest.save_history_record(record)
                self.assertTrue(os.path.exists(hf))
                with open(hf, "r") as f:
                    data = json.load(f)
                self.assertEqual(len(data), 1)
                self.assertEqual(data[0]["score"], 95)

    def test_save_appends_to_existing(self):
        with tempfile.TemporaryDirectory() as td:
            hf = os.path.join(td, "history.json")
            with open(hf, "w") as f:
                json.dump([{"run": 1}], f)
            with patch.object(speedtest, "HISTORY_FILE", hf):
                speedtest.save_history_record({"run": 2})
                with open(hf, "r") as f:
                    data = json.load(f)
                self.assertEqual(len(data), 2)
                self.assertEqual(data[1]["run"], 2)

    def test_save_handles_corrupt_history(self):
        with tempfile.TemporaryDirectory() as td:
            hf = os.path.join(td, "history.json")
            with open(hf, "w") as f:
                f.write("{corrupt-data...")
            with patch.object(speedtest, "HISTORY_FILE", hf):
                speedtest.save_history_record({"run": 1})
                with open(hf, "r") as f:
                    data = json.load(f)
                self.assertEqual(len(data), 1)
                self.assertEqual(data[0]["run"], 1)

    def test_save_prunes_at_limit(self):
        with tempfile.TemporaryDirectory() as td:
            hf = os.path.join(td, "history.json")
            initial_records = [{"run": i} for i in range(15)]
            with open(hf, "w") as f:
                json.dump(initial_records, f)
            with patch.object(speedtest, "HISTORY_FILE", hf), patch.object(speedtest, "MAX_HISTORY_ENTRIES", 10):
                speedtest.save_history_record({"run": 999})
                with open(hf, "r") as f:
                    data = json.load(f)
                self.assertEqual(len(data), 10)
                self.assertEqual(data[-1]["run"], 999)


class TestHttpRequestAndBackoff(unittest.TestCase):
    @patch("subprocess.run")
    def test_make_http_request_success(self, mock_run):
        mock_proc = MagicMock(returncode=0, stdout="Success Content")
        mock_run.return_value = mock_proc
        res = speedtest.make_http_request("https://example.com", headers={"X-Custom": "val"}, ip_version="4")
        self.assertEqual(res, "Success Content")
        cmd = mock_run.call_args[0][0]
        self.assertIn("-4", cmd)
        self.assertIn("-H", cmd)
        self.assertIn("X-Custom: val", cmd)
        self.assertIn("https://example.com", cmd)

    @patch("subprocess.run")
    def test_make_http_request_failure(self, mock_run):
        mock_proc = MagicMock(returncode=1, stdout="")
        mock_run.return_value = mock_proc
        res = speedtest.make_http_request("https://example.com")
        self.assertIsNone(res)

    @patch("subprocess.run", side_effect=subprocess.TimeoutExpired(cmd=["curl"], timeout=5))
    def test_make_http_request_timeout(self, mock_run):
        res = speedtest.make_http_request("https://example.com", timeout=5)
        self.assertIsNone(res)

    @patch("time.sleep")
    def test_exponential_backoff_delay(self, mock_sleep):
        speedtest.exponential_backoff_delay(0, base_delay=1.0, max_delay=6.0)
        mock_sleep.assert_called_with(1.0)
        speedtest.exponential_backoff_delay(2, base_delay=1.0, max_delay=6.0)
        mock_sleep.assert_called_with(4.0)
        speedtest.exponential_backoff_delay(5, base_delay=1.0, max_delay=6.0)
        mock_sleep.assert_called_with(6.0)


class TestIPv6Availability(unittest.TestCase):
    @patch("socket.socket")
    def test_ipv6_available_success(self, mock_socket_cls):
        mock_sock = mock_socket_cls.return_value
        mock_sock.__enter__.return_value = mock_sock
        mock_sock.connect.return_value = None
        self.assertTrue(speedtest.is_ipv6_available())

    @patch("socket.socket")
    def test_ipv6_available_failure(self, mock_socket_cls):
        mock_sock = mock_socket_cls.return_value
        mock_sock.__enter__.return_value = mock_sock
        mock_sock.connect.side_effect = OSError("Network is unreachable")
        self.assertFalse(speedtest.is_ipv6_available())


class TestIdlePingMeasurement(unittest.TestCase):
    @patch("subprocess.run")
    def test_idle_ping_icmp_success(self, mock_run):
        mock_proc = MagicMock()
        mock_proc.returncode = 0
        mock_proc.stdout = """
64 bytes from 1.1.1.1: icmp_seq=1 ttl=57 time=10.2 ms
64 bytes from 1.1.1.1: icmp_seq=2 ttl=57 time=12.8 ms
64 bytes from 1.1.1.1: icmp_seq=3 ttl=57 time=11.0 ms
--- 1.1.1.1 ping statistics ---
3 packets transmitted, 3 received, 0.0% packet loss
"""
        mock_run.return_value = mock_proc
        res = speedtest.measure_idle_ping(host="1.1.1.1", count=3)
        self.assertEqual(res["loss"], 0.0)
        self.assertEqual(len(res["samples"]), 3)
        self.assertEqual(res["stats"]["min"], 10.2)
        self.assertEqual(res["stats"]["max"], 12.8)
        self.assertGreater(res["stats"]["avg"], 10.0)

    @patch("speedtest.measure_idle_ping", return_value={"loss": 12.5})
    def test_measure_packet_loss(self, mock_idle):
        loss = speedtest.measure_packet_loss("1.1.1.1", count=5)
        self.assertEqual(loss, 12.5)
        mock_idle.assert_called_once_with(host="1.1.1.1", count=5, timeout=2)


class TestSpeedtestEngines(unittest.TestCase):
    @patch("shutil.which", return_value="/usr/bin/speedtest")
    @patch("subprocess.run")
    def test_ookla_json_iqm_parsing(self, mock_run, mock_which):
        sample_ookla_json = {
            "download": {"bandwidth": 125000000, "latency": {"iqm": 14.5}},
            "upload": {"bandwidth": 62500000, "latency": {"iqm": 22.3}},
            "ping": {"latency": 9.2, "jitter": 1.1},
        }
        mock_proc = MagicMock()
        mock_proc.returncode = 0
        mock_proc.stdout = json.dumps(sample_ookla_json)
        mock_run.return_value = mock_proc

        res = speedtest.get_speedtest(debug=False, retries=0)
        self.assertIsNotNone(res)
        self.assertEqual(res["download"], 1000.0)  # 125M bytes/s * 8 / 1M = 1000 Mbps
        self.assertEqual(res["upload"], 500.0)  # 62.5M bytes/s * 8 / 1M = 500 Mbps
        self.assertEqual(res["ping"], 9.2)
        self.assertEqual(res["jitter"], 1.1)
        self.assertEqual(res["dl_latency"], 14.5)
        self.assertEqual(res["ul_latency"], 22.3)
        self.assertEqual(res["engine_type"], "Ookla Native")

    @patch("shutil.which", return_value=None)
    @patch("subprocess.run")
    def test_speedtest_cli_fallback(self, mock_run, mock_which):
        mock_proc = MagicMock()
        mock_proc.returncode = 0
        mock_proc.stdout = """
Ping: 14.2 ms
Download: 150.25 Mbit/s
Upload: 45.80 Mbit/s
"""
        mock_run.return_value = mock_proc
        res = speedtest.get_speedtest(debug=False, retries=0)
        self.assertIsNotNone(res)
        self.assertEqual(res["download"], 150.25)
        self.assertEqual(res["upload"], 45.80)
        self.assertEqual(res["ping"], 14.2)
        self.assertEqual(res["engine_type"], "speedtest-cli")

    @patch("shutil.which", return_value=None)
    @patch("subprocess.run", side_effect=Exception("command failed"))
    def test_speedtest_both_fail(self, mock_run, mock_which):
        res = speedtest.get_speedtest(debug=False, retries=0)
        self.assertIsNone(res)

    @patch("subprocess.run")
    def test_get_custom_speedtest_success(self, mock_run):
        mock_proc = MagicMock(returncode=0, stdout="12500000")  # 12.5 MB
        mock_run.return_value = mock_proc
        with patch("time.perf_counter", side_effect=[0.0, 1.0]):
            res = speedtest.get_custom_speedtest("https://example.com/testfile", retries=0)
        self.assertIsNotNone(res)
        # 12.5 MB in 1.0s = 100 Mbps
        self.assertEqual(res["download"], 100.0)

    @patch("subprocess.run", side_effect=Exception("Failed"))
    def test_get_custom_speedtest_failure(self, mock_run):
        res = speedtest.get_custom_speedtest("https://example.com/testfile", retries=0)
        self.assertIsNone(res)

    @patch("subprocess.run")
    def test_get_cloudflare_success(self, mock_run):
        mock_proc = MagicMock(returncode=0, stdout="10000000")  # 10 MB per worker
        mock_run.return_value = mock_proc
        res = speedtest.get_cloudflare(debug=False, retries=0, timeout=5)
        self.assertIsNotNone(res)
        self.assertIn("download", res)
        self.assertIn("upload", res)
        self.assertGreater(res["download"], 0.0)

    @patch("speedtest.make_http_request")
    @patch("subprocess.run")
    def test_get_fastcom_success(self, mock_run, mock_http):
        mock_http.side_effect = [
            '<script src="/app-12345.js"></script>',
            'token: "secret_token"',
            json.dumps({"targets": [{"url": "https://cdn.fast.com/chunk"}]}),
        ]
        mock_proc = MagicMock(returncode=0, stdout="12500000")
        mock_run.return_value = mock_proc
        res = speedtest.get_fastcom(debug=False, retries=0, timeout=5)
        self.assertIsNotNone(res)
        self.assertIn("download", res)
        self.assertGreater(res["download"], 0.0)


class TestNetworkAdapterAndSystemDNS(unittest.TestCase):
    @patch("subprocess.run")
    def test_get_network_adapter_info_linux(self, mock_run):
        def fake_run(cmd, *args, **kwargs):
            if cmd[:4] == ["ip", "route", "show", "default"]:
                return MagicMock(returncode=0, stdout="default via 192.168.1.1 dev eth0 proto dhcp")
            return MagicMock(returncode=1, stdout="")

        mock_run.side_effect = fake_run
        with patch("os.path.exists", return_value=True), \
             patch("builtins.open", mock_open(read_data="1000\n")):
            info = speedtest.get_network_adapter_info(debug=False)
        self.assertEqual(info["interface"], "eth0")
        self.assertEqual(info["gateway"], "192.168.1.1")
        self.assertEqual(info["interface_type"], "Ethernet")

    @patch("subprocess.run", side_effect=FileNotFoundError)
    @patch("os.path.exists")
    def test_get_system_dns_resolvers_resolv_conf(self, mock_exists, mock_run):
        mock_exists.side_effect = lambda path: path == "/etc/resolv.conf"
        resolv_content = """
nameserver 1.1.1.1
nameserver 8.8.8.8
nameserver 127.0.0.53
"""
        with patch("builtins.open", mock_open(read_data=resolv_content)):
            resolvers = speedtest.get_system_dns_resolvers()
        self.assertEqual(len(resolvers), 2)
        ips = [r["ip"] for r in resolvers]
        self.assertIn("1.1.1.1", ips)
        self.assertIn("8.8.8.8", ips)
        self.assertNotIn("127.0.0.53", ips)


class TestCheckEndpoints(unittest.TestCase):
    @patch("speedtest.make_http_request")
    def test_check_endpoints_all_accessible(self, mock_http):
        def side_effect(url, **kwargs):
            if "speedtest.net" in url:
                return '{"client": {"ip": "1.2.3.4"}}'
            elif "fast.com" in url and "app" not in url and "netflix" not in url:
                return '<script src="/app-123.js"></script>'
            elif "app-123.js" in url:
                return 'token:"valid_token"'
            elif "netflix" in url:
                return '{"targets": [{"url": "https://fast.com"}]}'
            elif "cloudflare.com" in url:
                return "1"
            return None

        mock_http.side_effect = side_effect
        st, fast, cf = speedtest.check_endpoints(quiet=True)
        self.assertTrue(st)
        self.assertTrue(fast)
        self.assertTrue(cf)

    @patch("speedtest.make_http_request", return_value=None)
    def test_check_endpoints_all_blocked(self, mock_http):
        st, fast, cf = speedtest.check_endpoints(quiet=True)
        self.assertFalse(st)
        self.assertFalse(fast)
        self.assertFalse(cf)


class TestDisplayHistory(unittest.TestCase):
    def test_display_history_inline_no_file(self):
        buf = io.StringIO()
        with patch("os.path.exists", return_value=False), patch("sys.stdout", buf):
            speedtest.display_history(inline=True)
        out = buf.getvalue()
        self.assertIn("No prior benchmark history found yet", out)

    def test_display_history_inline_with_data(self):
        sample_history = [
            {
                "timestamp": "2026-09-25T12:00:00",
                "network": {"geo": {"isp": "TestISP"}, "adapter": {"interface": "eth0"}},
                "statistics": {
                    "speedtest_download_mbps": {"avg": 500.0},
                    "cloudflare_download_mbps": {"avg": 450.0},
                    "ping_ms": {"avg": 10.0},
                    "bufferbloat": {"grade": "A+", "delta_ms": 2.0},
                },
                "suitability": {"overall_score": 95.0},
            }
        ]
        buf = io.StringIO()
        with patch("os.path.exists", return_value=True), \
             patch("builtins.open", mock_open(read_data=json.dumps(sample_history))), \
             patch("sys.stdout", buf):
            speedtest.display_history(inline=True, show_graph=True)
        out = buf.getvalue()
        self.assertIn("PRIOR BENCHMARK HISTORY & TRENDS", out)
        self.assertIn("TestISP", out)
        self.assertIn("500.0 M", out)
        self.assertIn("Overall Historical Averages", out)

    def test_display_history_corrupt_data(self):
        buf = io.StringIO()
        with patch("os.path.exists", return_value=True), \
             patch("builtins.open", mock_open(read_data="INVALID_JSON")), \
             patch("sys.stdout", buf):
            speedtest.display_history(inline=True)
        out = buf.getvalue()
        self.assertIn("Could not read prior history file", out)

    def test_display_history_non_list_payload(self):
        # A hand-edited/legacy file containing an object must not crash with TypeError.
        buf = io.StringIO()
        with patch("os.path.exists", return_value=True), \
             patch("builtins.open", mock_open(read_data=json.dumps({"oops": True}))), \
             patch("sys.stdout", buf):
            code = speedtest.display_history(inline=True)
        self.assertEqual(code, 0)
        self.assertIn("empty", buf.getvalue())

    def test_display_history_filters_non_dict_entries(self):
        payload = json.dumps([{"timestamp": "2026-09-25T12:00:00", "network": {"geo": {"isp": "KeepISP"}}, "statistics": {}, "suitability": {}}, "garbage", 42, None])
        buf = io.StringIO()
        with patch("os.path.exists", return_value=True), \
             patch("builtins.open", mock_open(read_data=payload)), \
             patch("sys.stdout", buf):
            code = speedtest.display_history(inline=True)
        self.assertEqual(code, 0)
        self.assertIn("KeepISP", buf.getvalue())


class TestBrowserPriority(unittest.TestCase):
    def test_firefox_priority(self):
        def fake_which(cmd):
            return "/usr/bin/" + cmd if cmd in ("firefox", "brave", "google-chrome") else None

        with patch("shutil.which", side_effect=fake_which):
            cmd, name = speedtest.get_preferred_browser()
            self.assertEqual(cmd, ["firefox"])
            self.assertEqual(name, "Firefox")

    def test_brave_priority_when_no_firefox(self):
        def fake_which(cmd):
            return "/usr/bin/" + cmd if cmd in ("brave", "google-chrome") else None

        with patch("shutil.which", side_effect=fake_which):
            cmd, name = speedtest.get_preferred_browser()
            self.assertEqual(cmd, ["brave"])
            self.assertEqual(name, "Brave")

    def test_chrome_priority_when_no_firefox_or_brave(self):
        def fake_which(cmd):
            return "/usr/bin/" + cmd if cmd == "google-chrome" else None

        with patch("shutil.which", side_effect=fake_which):
            cmd, name = speedtest.get_preferred_browser()
            self.assertEqual(cmd, ["google-chrome"])
            self.assertEqual(name, "Google Chrome")

    def test_fallback_to_xdg_open(self):
        def fake_which(cmd):
            return "/usr/bin/xdg-open" if cmd == "xdg-open" else None

        with patch("shutil.which", side_effect=fake_which), patch("sys.platform", "linux"):
            cmd, name = speedtest.get_preferred_browser()
            self.assertEqual(cmd, ["xdg-open"])
            self.assertEqual(name, "default browser")

    def test_open_browser_report_nonexistent_file(self):
        with patch("os.path.exists", return_value=False):
            res = speedtest.open_browser_report("nonexistent_report.html", quiet=True)
            self.assertFalse(res)

    def test_open_browser_report_launches_popen(self):
        with patch("os.path.exists", return_value=True), \
             patch("speedtest.get_preferred_browser", return_value=(["firefox"], "Firefox")), \
             patch("subprocess.Popen") as mock_popen:
            res = speedtest.open_browser_report("report.html", quiet=True)
            self.assertTrue(res)
            mock_popen.assert_called_once()
            args, kwargs = mock_popen.call_args
            self.assertEqual(args[0][0], "firefox")
            self.assertTrue(kwargs.get("start_new_session"))


class TestCliDefaults(unittest.TestCase):
    def test_default_args(self):
        with patch("sys.argv", ["speedtest.sh"]), \
             patch("speedtest.run_benchmark_cycle", return_value=0) as mock_cycle, \
             patch("speedtest.print_banner"):
            speedtest.run_benchmark()
            mock_cycle.assert_called_once()
            args = mock_cycle.call_args[0][0]
            self.assertEqual(args.html, "report.html")
            self.assertTrue(args.open)

    def test_no_open_flag(self):
        with patch("sys.argv", ["speedtest.sh", "--no-open"]), \
             patch("speedtest.run_benchmark_cycle", return_value=0) as mock_cycle, \
             patch("speedtest.print_banner"):
            speedtest.run_benchmark()
            mock_cycle.assert_called_once()
            args = mock_cycle.call_args[0][0]
            self.assertFalse(args.open)

    def test_no_html_flag(self):
        with patch("sys.argv", ["speedtest.sh", "--no-html"]), \
             patch("speedtest.run_benchmark_cycle", return_value=0) as mock_cycle, \
             patch("speedtest.print_banner"):
            speedtest.run_benchmark()
            mock_cycle.assert_called_once()
            args = mock_cycle.call_args[0][0]
            self.assertIsNone(args.html)

    def test_no_dns_flag(self):
        with patch("sys.argv", ["speedtest.sh", "--no-dns"]), \
             patch("speedtest.run_benchmark_cycle", return_value=0) as mock_cycle, \
             patch("speedtest.print_banner"):
            speedtest.run_benchmark()
            mock_cycle.assert_called_once()
            args = mock_cycle.call_args[0][0]
            self.assertFalse(args.dns)

    def test_json_stdout_disables_open(self):
        with patch("sys.argv", ["speedtest.sh", "--json-stdout"]), \
             patch("speedtest.run_benchmark_cycle", return_value=0) as mock_cycle:
            speedtest.run_benchmark()
            mock_cycle.assert_called_once()
            args = mock_cycle.call_args[0][0]
            self.assertFalse(args.open)
            self.assertTrue(args.quiet)


class TestCliMutuallyExclusive(unittest.TestCase):
    def test_ipv4_and_ipv6_mutually_exclusive(self):
        with patch("sys.argv", ["speedtest.sh", "-4", "-6"]), \
             patch("sys.stderr", io.StringIO()):
            with self.assertRaises(SystemExit) as cm:
                speedtest.run_benchmark()
            self.assertEqual(cm.exception.code, 2)

    def test_html_and_no_html_mutually_exclusive(self):
        with patch("sys.argv", ["speedtest.sh", "--html", "out.html", "--no-html"]), \
             patch("sys.stderr", io.StringIO()):
            with self.assertRaises(SystemExit) as cm:
                speedtest.run_benchmark()
            self.assertEqual(cm.exception.code, 2)

    def test_open_and_no_open_mutually_exclusive(self):
        with patch("sys.argv", ["speedtest.sh", "--open", "--no-open"]), \
             patch("sys.stderr", io.StringIO()):
            with self.assertRaises(SystemExit) as cm:
                speedtest.run_benchmark()
            self.assertEqual(cm.exception.code, 2)

    def test_dns_and_no_dns_mutually_exclusive(self):
        with patch("sys.argv", ["speedtest.sh", "--dns", "--no-dns"]), \
             patch("sys.stderr", io.StringIO()):
            with self.assertRaises(SystemExit) as cm:
                speedtest.run_benchmark()
            self.assertEqual(cm.exception.code, 2)


class TestSlaThresholdsAndExitCodes(unittest.TestCase):
    def _create_mock_args(self, **kwargs):
        args = MagicMock()
        args.runs = 1
        args.engine = "all"
        args.quiet = True
        args.debug = False
        args.json_stdout = False
        args.open = False
        args.html = None
        args.json = None
        args.csv = None
        args.markdown = None
        args.no_color = True
        args.server = None
        args.dns = False
        args.ipv4 = False
        args.ipv6 = False
        args.timeout = 5
        args.threshold_dl = None
        args.threshold_ul = None
        args.threshold_ping = None
        for k, v in kwargs.items():
            setattr(args, k, v)
        return args

    @patch("speedtest.get_network_adapter_info", return_value={"interface": "eth0", "gateway": "192.168.1.1", "link_speed": "1 Gbps", "interface_type": "Ethernet", "wifi_ssid": "N/A", "wifi_signal": "N/A", "mtu": "1500"})
    @patch("speedtest.get_geo_info", return_value={"ip": "1.2.3.4", "isp": "ISP", "city": "City", "country": "Country"})
    @patch("speedtest.get_lan_ip", return_value="192.168.1.50")
    @patch("speedtest.check_endpoints", return_value=(True, True, True))
    @patch("speedtest.save_history_record")
    @patch("speedtest.measure_idle_ping", return_value={"loss": 0.0, "stats": {"min": 10.0, "max": 10.0, "avg": 10.0, "median": 10.0}, "jitter": 1.0, "samples": [10.0]})
    @patch("speedtest.get_speedtest", return_value={"download": 50.0, "upload": 20.0, "ping": 10.0, "jitter": 1.0, "dl_latency": 12.0, "ul_latency": 15.0, "engine_type": "Ookla"})
    @patch("speedtest.get_fastcom", return_value=None)
    @patch("speedtest.get_cloudflare", return_value=None)
    def test_sla_dl_threshold_breach(self, *mocks):
        args = self._create_mock_args(threshold_dl=100.0)  # Requires 100 Mbps, achieved 50 Mbps
        with patch("sys.stdout", io.StringIO()), patch("time.sleep"):
            code = speedtest.run_benchmark_cycle(args)
        self.assertEqual(code, 3)

    @patch("speedtest.get_network_adapter_info", return_value={"interface": "eth0", "gateway": "192.168.1.1", "link_speed": "1 Gbps", "interface_type": "Ethernet", "wifi_ssid": "N/A", "wifi_signal": "N/A", "mtu": "1500"})
    @patch("speedtest.get_geo_info", return_value={"ip": "1.2.3.4", "isp": "ISP", "city": "City", "country": "Country"})
    @patch("speedtest.get_lan_ip", return_value="192.168.1.50")
    @patch("speedtest.check_endpoints", return_value=(True, True, True))
    @patch("speedtest.save_history_record")
    @patch("speedtest.measure_idle_ping", return_value={"loss": 0.0, "stats": {"min": 10.0, "max": 10.0, "avg": 10.0, "median": 10.0}, "jitter": 1.0, "samples": [10.0]})
    @patch("speedtest.get_speedtest", return_value={"download": 50.0, "upload": 20.0, "ping": 10.0, "jitter": 1.0, "dl_latency": 12.0, "ul_latency": 15.0, "engine_type": "Ookla"})
    @patch("speedtest.get_fastcom", return_value=None)
    @patch("speedtest.get_cloudflare", return_value=None)
    def test_sla_ul_threshold_breach(self, *mocks):
        args = self._create_mock_args(threshold_ul=50.0)  # Requires 50 Mbps upload, achieved 20 Mbps
        with patch("sys.stdout", io.StringIO()), patch("time.sleep"):
            code = speedtest.run_benchmark_cycle(args)
        self.assertEqual(code, 3)

    @patch("speedtest.get_network_adapter_info", return_value={"interface": "eth0", "gateway": "192.168.1.1", "link_speed": "1 Gbps", "interface_type": "Ethernet", "wifi_ssid": "N/A", "wifi_signal": "N/A", "mtu": "1500"})
    @patch("speedtest.get_geo_info", return_value={"ip": "1.2.3.4", "isp": "ISP", "city": "City", "country": "Country"})
    @patch("speedtest.get_lan_ip", return_value="192.168.1.50")
    @patch("speedtest.check_endpoints", return_value=(True, True, True))
    @patch("speedtest.save_history_record")
    @patch("speedtest.measure_idle_ping", return_value={"loss": 0.0, "stats": {"min": 50.0, "max": 50.0, "avg": 50.0, "median": 50.0}, "jitter": 1.0, "samples": [50.0]})
    @patch("speedtest.get_speedtest", return_value={"download": 50.0, "upload": 20.0, "ping": 50.0, "jitter": 1.0, "dl_latency": 55.0, "ul_latency": 60.0, "engine_type": "Ookla"})
    @patch("speedtest.get_fastcom", return_value=None)
    @patch("speedtest.get_cloudflare", return_value=None)
    def test_sla_ping_threshold_breach(self, *mocks):
        args = self._create_mock_args(threshold_ping=20.0)  # Max ping 20ms, got 50ms
        with patch("sys.stdout", io.StringIO()), patch("time.sleep"):
            code = speedtest.run_benchmark_cycle(args)
        self.assertEqual(code, 3)

    @patch("speedtest.get_network_adapter_info", return_value={"interface": "eth0", "gateway": "192.168.1.1", "link_speed": "1 Gbps", "interface_type": "Ethernet", "wifi_ssid": "N/A", "wifi_signal": "N/A", "mtu": "1500"})
    @patch("speedtest.get_geo_info", return_value={"ip": "1.2.3.4", "isp": "ISP", "city": "City", "country": "Country"})
    @patch("speedtest.get_lan_ip", return_value="192.168.1.50")
    @patch("speedtest.check_endpoints", return_value=(False, False, False))
    @patch("speedtest.save_history_record")
    @patch("speedtest.measure_idle_ping", return_value={"loss": 100.0, "stats": {"min": 0.0, "max": 0.0, "avg": 0.0, "median": 0.0}, "jitter": 0.0, "samples": []})
    @patch("speedtest.get_speedtest", return_value=None)
    @patch("speedtest.get_fastcom", return_value=None)
    @patch("speedtest.get_cloudflare", return_value=None)
    def test_all_engines_fail_exit_code_2(self, *mocks):
        args = self._create_mock_args()
        with patch("sys.stdout", io.StringIO()), patch("time.sleep"):
            code = speedtest.run_benchmark_cycle(args)
        self.assertEqual(code, 2)

    @patch("speedtest.get_network_adapter_info", return_value={"interface": "eth0", "gateway": "192.168.1.1", "link_speed": "1 Gbps", "interface_type": "Ethernet", "wifi_ssid": "N/A", "wifi_signal": "N/A", "mtu": "1500"})
    @patch("speedtest.get_geo_info", return_value={"ip": "1.2.3.4", "isp": "ISP", "city": "City", "country": "Country"})
    @patch("speedtest.get_lan_ip", return_value="192.168.1.50")
    @patch("speedtest.check_endpoints", return_value=(True, True, True))
    @patch("speedtest.save_history_record")
    @patch("speedtest.measure_idle_ping", return_value={"loss": 100.0, "stats": {"min": 0.0, "max": 0.0, "avg": 0.0, "median": 0.0}, "jitter": 0.0, "samples": []})
    @patch("speedtest.get_speedtest", return_value=None)
    @patch("speedtest.get_fastcom", return_value=None)
    @patch("speedtest.get_cloudflare", return_value=None)
    def test_no_false_sla_alert_without_measurements(self, *mocks):
        # Every engine failed, but a threshold is set: must return 2, never 3 (0.0 is not a breach).
        args = self._create_mock_args(threshold_dl=1.0, threshold_ping=1.0)
        out = io.StringIO()
        with patch("sys.stdout", out), patch("time.sleep"):
            code = speedtest.run_benchmark_cycle(args)
        self.assertEqual(code, 2)
        self.assertNotIn("SLA ALERT", out.getvalue())

    @patch("speedtest.get_network_adapter_info", return_value={"interface": "eth0", "gateway": "192.168.1.1", "link_speed": "1 Gbps", "interface_type": "Ethernet", "wifi_ssid": "N/A", "wifi_signal": "N/A", "mtu": "1500"})
    @patch("speedtest.get_geo_info", return_value={"ip": "1.2.3.4", "isp": "ISP", "city": "City", "country": "Country"})
    @patch("speedtest.get_lan_ip", return_value="192.168.1.50")
    @patch("speedtest.check_endpoints", return_value=(True, True, True))
    @patch("speedtest.save_history_record")
    @patch("speedtest.measure_idle_ping", return_value={"loss": 0.0, "stats": {"min": 10.0, "max": 10.0, "avg": 10.0, "median": 10.0}, "jitter": 1.0, "samples": [10.0]})
    @patch("speedtest.get_speedtest", return_value={"download": 50.0, "upload": 20.0, "ping": 10.0, "jitter": 1.0, "dl_latency": 12.0, "ul_latency": 15.0, "engine_type": "Ookla"})
    @patch("speedtest.get_fastcom", return_value=None)
    @patch("speedtest.get_cloudflare", return_value=None)
    def test_json_stdout_keeps_sla_alert_off_stdout(self, *mocks):
        args = self._create_mock_args(json_stdout=True, quiet=False, threshold_dl=100.0)
        out, err = io.StringIO(), io.StringIO()
        with patch("sys.stdout", out), patch("sys.stderr", err), patch("time.sleep"):
            code = speedtest.run_benchmark_cycle(args)
        self.assertEqual(code, 3)
        json.loads(out.getvalue())  # stdout must remain valid JSON
        self.assertIn("SLA ALERT", err.getvalue())
        self.assertNotIn("SLA ALERT", out.getvalue())


class TestValidateArgs(unittest.TestCase):
    def _args(self, **kwargs):
        args = MagicMock()
        args.runs = 3
        args.timeout = 18
        args.monitor = None
        args.engine = "all"
        args.server = None
        args.threshold_dl = None
        args.threshold_ul = None
        args.threshold_ping = None
        for k, v in kwargs.items():
            setattr(args, k, v)
        return args

    def test_valid_defaults(self):
        self.assertIsNone(speedtest.validate_args(self._args()))

    def test_runs_out_of_range(self):
        self.assertIn("--runs", speedtest.validate_args(self._args(runs=0)))
        self.assertIn("--runs", speedtest.validate_args(self._args(runs=21)))

    def test_invalid_timeout(self):
        self.assertIn("--timeout", speedtest.validate_args(self._args(timeout=0)))

    def test_invalid_monitor_interval(self):
        self.assertIn("--monitor", speedtest.validate_args(self._args(monitor=0)))
        self.assertIn("--monitor", speedtest.validate_args(self._args(monitor=-5)))
        self.assertIn("--monitor", speedtest.validate_args(self._args(monitor=100000)))

    def test_custom_engine_requires_server(self):
        self.assertIn("--server", speedtest.validate_args(self._args(engine="custom")))
        self.assertIsNone(speedtest.validate_args(self._args(engine="custom", server="https://example.com/100MB.bin")))

    def test_server_rejected_for_other_engines(self):
        self.assertIn("--server", speedtest.validate_args(self._args(engine="fast", server="https://example.com/100MB.bin")))

    def test_server_scheme_must_be_http(self):
        for bad in ("file:///etc/passwd", "ftp://example.com/x.bin", "example.com/100MB.bin", "/tmp/local.bin"):
            with self.subTest(url=bad):
                self.assertIn("--server", speedtest.validate_args(self._args(engine="custom", server=bad)))
        self.assertIsNone(speedtest.validate_args(self._args(engine="custom", server="https://example.com/100MB.bin")))
        self.assertIsNone(speedtest.validate_args(self._args(engine="custom", server="http://example.com/100MB.bin")))

    def test_non_positive_thresholds(self):
        self.assertIn("--threshold-dl", speedtest.validate_args(self._args(threshold_dl=0)))
        self.assertIn("--threshold-ul", speedtest.validate_args(self._args(threshold_ul=-1)))
        self.assertIn("--threshold-ping", speedtest.validate_args(self._args(threshold_ping=0)))


class TestMonitorMode(unittest.TestCase):
    def _cycle_codes(self, codes):
        it = iter(codes)
        return lambda *a, **k: next(it)

    def _run(self, codes):
        with patch("sys.argv", ["speedtest.sh", "--monitor", "1", "--no-html", "--no-open", "--no-dns"]), \
             patch("speedtest.run_benchmark_cycle", side_effect=self._cycle_codes(codes)) as mock_cycle, \
             patch("speedtest.print_banner"), \
             patch("sys.stdout", io.StringIO()), \
             patch("time.sleep") as mock_sleep:
            code = speedtest.run_benchmark()
        return code, mock_cycle, mock_sleep

    def test_aborts_after_consecutive_no_measurement_cycles(self):
        code, mock_cycle, mock_sleep = self._run([2, 2, 2])
        self.assertEqual(code, 2)
        self.assertEqual(mock_cycle.call_count, speedtest.MAX_CONSECUTIVE_MONITOR_FAILURES)
        # No sleep after the cycle that triggered the abort.
        self.assertEqual(mock_sleep.call_count, speedtest.MAX_CONSECUTIVE_MONITOR_FAILURES - 1)

    def test_success_resets_failure_counter(self):
        # 2 failures, a success, then 3 failures: aborts on cycle 6, not cycle 3.
        code, mock_cycle, mock_sleep = self._run([2, 2, 0, 2, 2, 2])
        self.assertEqual(code, 2)
        self.assertEqual(mock_cycle.call_count, 6)
        self.assertEqual(mock_sleep.call_count, 5)

    def test_ctrl_c_during_sleep_exits_cleanly(self):
        with patch("sys.argv", ["speedtest.sh", "--monitor", "1", "--no-html", "--no-open", "--no-dns"]), \
             patch("speedtest.run_benchmark_cycle", return_value=0), \
             patch("speedtest.print_banner"), \
             patch("sys.stdout", io.StringIO()), \
             patch("time.sleep", side_effect=KeyboardInterrupt):
            self.assertEqual(speedtest.run_benchmark(), 0)


if __name__ == "__main__":
    unittest.main()
