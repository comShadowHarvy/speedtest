#!/usr/bin/env python3
"""
Unit tests for Network Speed Benchmark Tool (speedtest.sh)
"""

import os
import sys
import unittest
import json
import tempfile
import io
from unittest.mock import patch, MagicMock

# Add parent directory to sys.path to import speedtest module functions
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

# Import functions from speedtest.sh
from importlib.machinery import SourceFileLoader
script_path = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "speedtest.sh"))
speedtest = SourceFileLoader("speedtest", script_path).load_module()


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


class TestJitterCalculation(unittest.TestCase):
    def test_empty_or_single_item(self):
        self.assertEqual(speedtest.calculate_jitter([]), 0.0)
        self.assertEqual(speedtest.calculate_jitter([15.0]), 0.0)

    def test_multiple_items(self):
        # Latencies: 10, 15, 12 -> diffs: |15-10|=5, |12-15|=3 -> avg = 4.0
        self.assertEqual(speedtest.calculate_jitter([10.0, 15.0, 12.0]), 4.0)


class TestBufferbloatGrade(unittest.TestCase):
    def test_grade_a_plus(self):
        grade, delta = speedtest.calculate_bufferbloat_grade(20.0, 23.0)
        self.assertEqual(grade, "A+")
        self.assertEqual(delta, 3.0)

    def test_grade_a(self):
        grade, delta = speedtest.calculate_bufferbloat_grade(20.0, 32.0)
        self.assertEqual(grade, "A")
        self.assertEqual(delta, 12.0)

    def test_grade_b(self):
        grade, delta = speedtest.calculate_bufferbloat_grade(20.0, 45.0)
        self.assertEqual(grade, "B")
        self.assertEqual(delta, 25.0)

    def test_grade_c(self):
        grade, delta = speedtest.calculate_bufferbloat_grade(20.0, 75.0)
        self.assertEqual(grade, "C")
        self.assertEqual(delta, 55.0)

    def test_grade_d(self):
        grade, delta = speedtest.calculate_bufferbloat_grade(20.0, 110.0)
        self.assertEqual(grade, "D")
        self.assertEqual(delta, 90.0)

    def test_grade_f(self):
        grade, delta = speedtest.calculate_bufferbloat_grade(20.0, 180.0)
        self.assertEqual(grade, "F")
        self.assertEqual(delta, 160.0)


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
    def test_multi_gigabit(self):
        self.assertIn("Multi-Gigabit", speedtest.get_speed_tier(2500))

    def test_gigabit(self):
        self.assertIn("Gigabit", speedtest.get_speed_tier(950))

    def test_ultra_fast(self):
        self.assertIn("Ultra-Fast", speedtest.get_speed_tier(500))

    def test_high_speed(self):
        self.assertIn("High-Speed", speedtest.get_speed_tier(150))

    def test_standard(self):
        self.assertIn("Standard", speedtest.get_speed_tier(50))


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


class TestSparkline(unittest.TestCase):
    def test_sparkline_generation(self):
        values = [10.0, 50.0, 100.0, 25.0, 80.0]
        spark = speedtest.generate_sparkline(values)
        self.assertEqual(len(spark), len(values))
        self.assertEqual(spark[0], " ")
        self.assertEqual(spark[2], "█")


class TestDNSQueryBuilder(unittest.TestCase):
    def test_dns_packet_structure_a(self):
        packet = speedtest.build_dns_query("google.com", "A")
        self.assertTrue(len(packet) > 12)
        # Header ID
        self.assertEqual(packet[:2], b"\xaa\xbb")
        # Contains google and com length bytes
        self.assertIn(b"\x06google\x03com\x00", packet)
        # Type A suffix
        self.assertTrue(packet.endswith(b"\x00\x01\x00\x01"))

    def test_dns_packet_structure_aaaa(self):
        packet = speedtest.build_dns_query("cloudflare.com", "AAAA")
        self.assertTrue(len(packet) > 12)
        self.assertEqual(packet[:2], b"\xaa\xbb")
        # Type AAAA (28 = 0x001c)
        self.assertTrue(packet.endswith(b"\x00\x1c\x00\x01"))


class TestFastestDNSRecommendation(unittest.TestCase):
    def test_recommendation_calculation(self):
        mock_dns = {
            "dns_resolvers": {
                "Cloudflare": {"resolver_ip": "1.1.1.1", "latency_ms": {"avg": 10.0}},
                "Google": {"resolver_ip": "8.8.8.8", "latency_ms": {"avg": 20.0}},
                "SlowDNS": {"resolver_ip": "10.0.0.1", "latency_ms": {"avg": 50.0}}
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


class TestReportsExport(unittest.TestCase):
    def setUp(self):
        self.test_data = {
            "timestamp": "2026-09-13T12:00:00.000000",
            "version": "3.1.0",
            "network": {
                "lan_ip": "192.168.1.50",
                "lan_ipv6": "Unavailable",
                "geo": {"ip": "1.2.3.4", "isp": "Test ISP", "city": "City", "country": "Country"},
                "adapter": {"interface": "eth0", "gateway": "192.168.1.1", "link_speed": "1.0 Gbps", "interface_type": "Ethernet", "wifi_ssid": "N/A", "wifi_signal": "N/A", "mtu": "1500"}
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
                    "upload_grade": "A+"
                }
            },
            "suitability": {
                "overall_score": 98.0,
                "speed_tier": "Ultra-Fast Broadband",
                "gaming": {"status": "Excellent (Competitive)", "score": 98.0},
                "streaming": {"status": "Flawless (4K/8K)", "score": 100.0},
                "video_call": {"status": "Studio Quality", "score": 96.0}
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
                    {"rank": 2, "name": "Google", "ip": "8.8.8.8", "latency_ms": 8.1, "category": "Global Anycast"}
                ],
                "profiles": {
                    "best_speed_privacy": {"name": "Cloudflare", "primary": "1.1.1.1", "secondary": "1.0.0.1", "ipv6_primary": "2606:4700:4700::1111"},
                    "best_security": {"name": "Quad9", "primary": "9.9.9.9", "secondary": "149.112.112.112"},
                    "best_adblocking": {"name": "AdGuard", "primary": "94.140.14.14", "secondary": "94.140.15.15"}
                }
            },
            "dns": {
                "dns_resolvers": {
                    "Cloudflare": {"resolver_ip": "1.1.1.1", "latency_ms": {"avg": 5.2, "min": 4.8, "max": 5.8}},
                    "Google": {"resolver_ip": "8.8.8.8", "latency_ms": {"avg": 8.1, "min": 7.5, "max": 9.0}}
                }
            }
        }

    def test_export_html_report(self):
        with tempfile.NamedTemporaryFile(suffix=".html", delete=False) as tf:
            tf_path = tf.name
        try:
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

    def test_export_html_report_zero_upload(self):
        data = json.loads(json.dumps(self.test_data))
        data["statistics"]["speedtest_upload_mbps"] = {"avg": 0.0, "min": 0.0, "max": 0.0}
        data["statistics"]["cloudflare_upload_mbps"] = {"avg": 0.0}
        with tempfile.NamedTemporaryFile(suffix=".html", delete=False) as tf:
            tf_path = tf.name
        try:
            success = speedtest.export_html_report(tf_path, data)
            self.assertTrue(success)
            with open(tf_path, "r") as f:
                content = f.read()
                self.assertNotIn("1.00 Mbps", content)
                self.assertIn("N/A", content)
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


class TestOoklaNativeMetrics(unittest.TestCase):
    @patch("shutil.which", return_value="/usr/bin/speedtest")
    @patch("subprocess.run")
    def test_ookla_json_iqm_parsing(self, mock_run, mock_which):
        sample_ookla_json = {
            "download": {"bandwidth": 125000000, "latency": {"iqm": 14.5}},
            "upload": {"bandwidth": 62500000, "latency": {"iqm": 22.3}},
            "ping": {"latency": 9.2, "jitter": 1.1}
        }
        mock_proc = MagicMock()
        mock_proc.returncode = 0
        mock_proc.stdout = json.dumps(sample_ookla_json)
        mock_run.return_value = mock_proc

        res = speedtest.get_speedtest(debug=False, retries=0)
        self.assertIsNotNone(res)
        self.assertEqual(res["download"], 1000.0)  # 125M bytes/s * 8 / 1M = 1000 Mbps
        self.assertEqual(res["upload"], 500.0)     # 62.5M bytes/s * 8 / 1M = 500 Mbps
        self.assertEqual(res["ping"], 9.2)
        self.assertEqual(res["jitter"], 1.1)
        self.assertEqual(res["dl_latency"], 14.5)
        self.assertEqual(res["ul_latency"], 22.3)
        self.assertEqual(res["engine_type"], "Ookla Native")


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


class TestDisplayHistory(unittest.TestCase):
    def test_display_history_inline_no_file(self):
        buf = io.StringIO()
        with patch("os.path.exists", return_value=False), patch("sys.stdout", buf):
            speedtest.display_history(inline=True)
        out = buf.getvalue()
        self.assertIn("No prior benchmark history found yet", out)

    def test_display_history_inline_with_data(self):
        sample_history = [{
            "timestamp": "2026-09-25T12:00:00",
            "network": {"geo": {"isp": "TestISP"}, "adapter": {"interface": "eth0"}},
            "statistics": {
                "speedtest_download_mbps": {"avg": 500.0},
                "cloudflare_download_mbps": {"avg": 450.0},
                "ping_ms": {"avg": 10.0},
                "bufferbloat": {"grade": "A+", "delta_ms": 2.0}
            },
            "suitability": {"overall_score": 95.0}
        }]
        buf = io.StringIO()
        with patch("os.path.exists", return_value=True), \
             patch("builtins.open", unittest.mock.mock_open(read_data=json.dumps(sample_history))), \
             patch("sys.stdout", buf):
            speedtest.display_history(inline=True, show_graph=True)
        out = buf.getvalue()
        self.assertIn("PRIOR BENCHMARK HISTORY & TRENDS", out)
        self.assertIn("TestISP", out)
        self.assertIn("500.0 M", out)
        self.assertIn("Overall Historical Averages", out)


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

    def test_json_stdout_disables_open(self):
        with patch("sys.argv", ["speedtest.sh", "--json-stdout"]), \
             patch("speedtest.run_benchmark_cycle", return_value=0) as mock_cycle:
            speedtest.run_benchmark()
            mock_cycle.assert_called_once()
            args = mock_cycle.call_args[0][0]
            self.assertFalse(args.open)
            self.assertTrue(args.quiet)


if __name__ == "__main__":
    unittest.main()


