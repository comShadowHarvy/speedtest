# Network Speed Benchmark Report

- **Date / Time:** `2026-10-04 14:11:17`
- **Tool Version:** `v3.2.0`
- **Public IP (WAN):** `24.138.182.29` (EastLink)
- **Speed Tier:** **High-Speed Broadband**
- **Quality Score:** **93.0/100**

---

## ⚡ Bandwidth Speeds

| Engine | Download (Mbps) | Upload (Mbps) |
| :--- | :--- | :--- |
| **Ookla Speedtest** | 80.00 Mbps | 13.91 Mbps |
| **Fast.com (Netflix)** | 74.60 Mbps | N/A |
| **Cloudflare CDN** | 105.12 Mbps | 12.48 Mbps |


---

## 📶 Latency, Stability & Directional Bufferbloat

| Metric | Result |
| :--- | :--- |
| **Idle Baseline Ping** | `54.74 ms` |
| **Download Active Ping** | `71.6 ms` (+16.86 ms, **Grade: B**) |
| **Upload Active Ping** | `73.3 ms` (+18.56 ms, **Grade: B**) |
| **Composite Bufferbloat** | **B** (+18.56 ms loaded spike) |
| **Network Jitter** | `9.92 ms` |
| **Packet Loss** | `0.0%` |

---

## 🖥️ Network Hardware & Diagnostics

- **Interface:** `wlan0` (Wi-Fi)
- **Link Speed:** `864.8 MBit/s`
- **Gateway IP:** `192.168.1.1`
- **Interface MTU:** `1500`
- **Wi-Fi SSID & Signal:** `RCMP_mobile` (-45 dBm)
- **Wi-Fi Frequency:** `5745 MHz (5 GHz)`

---

## 🎮 Real-World Readiness

- **Gaming:** Good (Smooth Casual Gaming) (80.0/100)
- **4K/8K Streaming:** Flawless (Multi-Device 4K/8K HDR) (100.0/100)
- **Video Calls:** Studio Quality (Flawless HD/4K Calls) (100.0/100)

## 🧭 Site Reachability Timing (Traceroute-Style)

| Site | Host | Edge IP | DNS | TCP | TLS | Server | Total | Status |
| :--- | :--- | :--- | ---: | ---: | ---: | ---: | ---: | :--- |
| **YouTube** | `www.youtube.com` | `142.251.154.4` | 1.2 ms | 41.5 ms | 57.2 ms | 152.3 ms | **503.8 ms** | Fair |
| **Google** | `www.google.com` | `142.251.154.119` | 1.2 ms | 52.7 ms | 142.5 ms | 126.7 ms | **622.9 ms** | Fair |
| **Amazon** | `www.amazon.com` | `54.230.84.180` | 75.7 ms | 49.2 ms | 102.7 ms | 36.8 ms | **254.4 ms** | Excellent |
| **Netflix** | `www.netflix.com` | `207.45.72.1` | 1.3 ms | 40.5 ms | 107.7 ms | 160.4 ms | **356.5 ms** | Fair |
| **Cloudflare** | `www.cloudflare.com` | `104.16.123.96` | 1.2 ms | 92.7 ms | 88.5 ms | 77.7 ms | **929.7 ms** | Slow |
| **Microsoft** | `www.microsoft.com` | `23.192.50.102` | 1.2 ms | 37.3 ms | 82.8 ms | 49.0 ms | **560.2 ms** | Fair |
| **Apple** | `www.apple.com` | `23.14.141.45` | 1.1 ms | 73.2 ms | 147.0 ms | 282.7 ms | **1169.0 ms** | Slow |
| **GitHub** | `github.com` | `140.82.121.3` | 1.1 ms | 184.2 ms | 205.3 ms | 134.2 ms | **1285.3 ms** | Slow |

### 🗺️ Hop-by-Hop Path to www.google.com
_via traceroute: 8/8 hops responded_

| Hop | Address | RTT |
| ---: | :--- | ---: |
| 1 | `192.168.1.1` | 81.46 ms |
| 2 | `10.129.128.1` | 93.06 ms |
| 3 | `24.139.3.1` | 96.04 ms |
| 4 | `24.139.15.45` | 100.96 ms |
| 5 | `24.139.20.217` | 100.95 ms |
| 6 | `24.139.20.245` | 100.94 ms |
| 7 | `24.139.20.82` | 100.94 ms |
| 8 | `142.251.155.119` | 104.14 ms |

### 🗺️ Hop-by-Hop Path to www.amazon.com
_via traceroute: 6/20 hops responded_

| Hop | Address | RTT |
| ---: | :--- | ---: |
| 1 | `192.168.1.1` | 88.73 ms |
| 2 | `10.129.128.1` | 100.95 ms |
| 3 | `24.139.3.5` | 104.15 ms |
| 4 | `24.139.7.201` | 105.69 ms |
| 5 | `24.139.7.233` | 105.69 ms |
| 6 | `24.139.20.244` | 100.92 ms |
| 7 | `*` | no reply |
| 8 | `*` | no reply |
| 9 | `*` | no reply |
| 10 | `*` | no reply |
| 11 | `*` | no reply |
| 12 | `*` | no reply |
| 13 | `*` | no reply |
| 14 | `*` | no reply |
| 15 | `*` | no reply |
| 16 | `*` | no reply |
| 17 | `*` | no reply |
| 18 | `*` | no reply |
| 19 | `*` | no reply |
| 20 | `*` | no reply |

---

## 💡 DNS Resolution Leaderboard & Recommendations

| Rank | Resolver | IP Address | Latency | Category / Best For |
| :---: | :--- | :--- | :---: | :--- |
| 🥇 1 | **System DNS (fd8b:88ea:d899:1::1)** | `fd8b:88ea:d899:1::1` | **48.28 ms** | Current System Default |
| 🥈 2 | **Local Gateway (192.168.1.1)** | `192.168.1.1` | **48.40 ms** | Local Router Cache (Fastest) |
| 🥉 3 | **Google** | `8.8.8.8` | **80.52 ms** | Global Anycast Reliability |
| #4 | **Quad9** | `9.9.9.9` | **102.68 ms** | Malware & Phishing Threat Blocking |
| #5 | **Cloudflare** | `1.1.1.1` | **120.29 ms** | Ultra-Fast & Privacy (No Logs) |
| #6 | **OpenDNS** | `208.67.222.222` | **124.74 ms** | Cisco Security & Web Filtering |
| #7 | **AdGuard** | `94.140.14.14` | **223.97 ms** | System-Wide Ad & Tracker Blocking |

### 🏆 Recommended Profiles for Your Network:
- **🚀 Best for Speed & Privacy:** **Cloudflare** (Primary: `1.1.1.1`, Secondary: `1.0.0.1` | IPv6: `2606:4700:4700::1111`)
- **🛡️ Best for Security & Threat Blocking:** **Quad9** (Primary: `9.9.9.9`, Secondary: `149.112.112.112` | IPv6: `2620:fe::fe`)
- **🚫 Best for Ad & Tracker Blocking:** **AdGuard** (Primary: `94.140.14.14`, Secondary: `94.140.15.15` | IPv6: `2a10:50c0::ad1:ff`)
- **🌐 Best for Anycast Reliability:** **Google** (Primary: `8.8.8.8`, Secondary: `8.8.4.4` | IPv6: `2001:4860:4860::8888`)
- **⚡ Status:** Your current System/Gateway DNS (fd8b:88ea:d899:1::1) is already delivering optimal latency (48.3 ms avg)! Fastest public alternative: Google (8.8.8.8).

---
*Report generated by Network Speed Benchmark Tool v3.2.0*
