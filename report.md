# Network Speed Benchmark Report

- **Date / Time:** `2026-10-04 14:21:13`
- **Tool Version:** `v3.2.0`
- **Public IP (WAN):** `24.138.182.29` (EastLink)
- **Speed Tier:** **Standard Broadband**
- **Quality Score:** **76.8/100**

---

## ⚡ Bandwidth Speeds

| Engine | Download (Mbps) | Upload (Mbps) |
| :--- | :--- | :--- |
| **Ookla Speedtest** | 73.92 Mbps | 17.87 Mbps |
| **Fast.com (Netflix)** | 89.13 Mbps | N/A |
| **Cloudflare CDN** | 82.09 Mbps | 9.41 Mbps |


---

## 📶 Latency, Stability & Directional Bufferbloat

| Metric | Result |
| :--- | :--- |
| **Idle Baseline Ping** | `1800000.0 ms` |
| **Download Active Ping** | `87.19 ms` (+0.0 ms, **Grade: A+**) |
| **Upload Active Ping** | `88.49 ms` (+0.0 ms, **Grade: A+**) |
| **Composite Bufferbloat** | **A+** (+0.0 ms loaded spike) |
| **Network Jitter** | `0.0 ms` |
| **Packet Loss** | `0.0%` |

---

## 🖥️ Network Hardware & Diagnostics

- **Interface:** `wlan0` (Wi-Fi)
- **Link Speed:** `432.3 MBit/s`
- **Gateway IP:** `192.168.1.1`
- **Interface MTU:** `1500`
- **Wi-Fi SSID & Signal:** `RCMP_mobile` (-48 dBm)
- **Wi-Fi Frequency:** `5745 MHz (5 GHz)`

---

## 🎮 Real-World Readiness

- **Gaming:** Fair (Occasional Latency Spikes) (60.0/100)
- **4K/8K Streaming:** Flawless (Multi-Device 4K/8K HDR) (95/100)
- **Video Calls:** Good (Reliable HD Group Calls) (75.0/100)

## 🧭 Site Reachability Timing (Traceroute-Style)

| Site | Host | Edge IP | DNS | TCP | TLS | Server | Total | Status |
| :--- | :--- | :--- | ---: | ---: | ---: | ---: | ---: | :--- |
| **YouTube** | `www.youtube.com` | `142.251.151.4` | 1.0 ms | 57.4 ms | 64.6 ms | 141.4 ms | **546.1 ms** | Fair |
| **Google** | `www.google.com` | `142.251.150.119` | 1.5 ms | 38.9 ms | 60.6 ms | 131.5 ms | **419.9 ms** | Fair |
| **Amazon** | `www.amazon.com` | `3.164.99.110` | 1.2 ms | 39.2 ms | 42.5 ms | 36.5 ms | **149.9 ms** | Excellent |
| **Netflix** | `www.netflix.com` | `207.45.73.1` | 0.8 ms | 59.0 ms | 62.6 ms | 138.7 ms | **328.3 ms** | Fair |
| **Cloudflare** | `www.cloudflare.com` | `104.16.124.96` | 1.3 ms | 41.4 ms | 69.4 ms | 32.3 ms | **507.2 ms** | Fair |
| **Microsoft** | `www.microsoft.com` | `23.210.18.103` | 0.9 ms | 115.2 ms | 277.1 ms | 139.6 ms | **1342.6 ms** | Slow |
| **Apple** | `www.apple.com` | `184.26.202.199` | 1.0 ms | 29.7 ms | 37.8 ms | 39.1 ms | **213.2 ms** | Excellent |
| **GitHub** | `github.com` | `140.82.112.3` | 0.8 ms | 54.6 ms | 56.5 ms | 49.6 ms | **621.3 ms** | Fair |

### 🗺️ Hop-by-Hop Path to www.google.com
_via traceroute: 8/8 hops responded_

| Hop | Address | RTT |
| ---: | :--- | ---: |
| 1 | `192.168.1.1` | 61.37 ms |
| 2 | `10.129.128.1` | 60.03 ms |
| 3 | `24.139.3.1` | 60.02 ms |
| 4 | `24.139.15.45` | 60.06 ms |
| 5 | `24.235.60.40` | 60.00 ms |
| 6 | `24.139.20.245` | 59.99 ms |
| 7 | `24.139.20.82` | 59.98 ms |
| 8 | `142.251.155.119` | 59.98 ms |

### 🗺️ Hop-by-Hop Path to www.amazon.com
_via traceroute: 6/20 hops responded_

| Hop | Address | RTT |
| ---: | :--- | ---: |
| 1 | `192.168.1.1` | 61.14 ms |
| 2 | `10.129.128.1` | 59.88 ms |
| 3 | `24.139.3.5` | 59.87 ms |
| 4 | `24.139.7.201` | 59.87 ms |
| 5 | `24.235.60.41` | 59.86 ms |
| 6 | `24.139.20.217` | 59.85 ms |
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
| 🥇 1 | **System DNS (fd8b:88ea:d899:1::1)** | `fd8b:88ea:d899:1::1` | **27.30 ms** | Current System Default |
| 🥈 2 | **Local Gateway (192.168.1.1)** | `192.168.1.1` | **27.34 ms** | Local Router Cache (Fastest) |
| 🥉 3 | **Google** | `8.8.8.8` | **68.24 ms** | Global Anycast Reliability |
| #4 | **Quad9** | `9.9.9.9` | **73.22 ms** | Malware & Phishing Threat Blocking |
| #5 | **Cloudflare** | `1.1.1.1` | **73.24 ms** | Ultra-Fast & Privacy (No Logs) |
| #6 | **OpenDNS** | `208.67.222.222` | **83.04 ms** | Cisco Security & Web Filtering |
| #7 | **AdGuard** | `94.140.14.14` | **251.33 ms** | System-Wide Ad & Tracker Blocking |

### 🏆 Recommended Profiles for Your Network:
- **🚀 Best for Speed & Privacy:** **Cloudflare** (Primary: `1.1.1.1`, Secondary: `1.0.0.1` | IPv6: `2606:4700:4700::1111`)
- **🛡️ Best for Security & Threat Blocking:** **Quad9** (Primary: `9.9.9.9`, Secondary: `149.112.112.112` | IPv6: `2620:fe::fe`)
- **🚫 Best for Ad & Tracker Blocking:** **AdGuard** (Primary: `94.140.14.14`, Secondary: `94.140.15.15` | IPv6: `2a10:50c0::ad1:ff`)
- **🌐 Best for Anycast Reliability:** **Google** (Primary: `8.8.8.8`, Secondary: `8.8.4.4` | IPv6: `2001:4860:4860::8888`)
- **⚡ Status:** Your current System/Gateway DNS (fd8b:88ea:d899:1::1) is already delivering optimal latency (27.3 ms avg)! Fastest public alternative: Google (8.8.8.8).

---
*Report generated by Network Speed Benchmark Tool v3.2.0*
