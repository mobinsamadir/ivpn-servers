# V2Ray Config Aggregator & Tester





## 📊 Statistics (Last Updated: 2026-10-15 03:44:56 UTC)

| Metric | Count |
| :--- | :--- |
| **TCP Passed** | `1856` |
| **Real Delay Passed** | `1417` |
| **Average Latency** | `635 ms` |
| **Success Rate** | `76.3%` |
| **System Health** | 🟢 Excellent |

### 🌍 Server Distribution

| Country | Count |
| :--- | :--- |
| 🚩 Unknown | 1318 |
| 🇺🇸 US | 24 |
| 🇰🇷 KR | 9 |
| 🇭🇰 HK | 9 |
| 🇩🇪 DE | 7 |
| 🇳🇱 NL | 6 |
| 🇷🇺 RU | 6 |
| 🇯🇵 JP | 5 |
| 🇸🇬 SG | 5 |
| 🇦🇪 AE | 3 |
| 🇲🇽 MX | 2 |
| 🇹🇼 TW | 2 |
| 🇵🇱 PL | 2 |
| 🇬🇧 GB | 2 |
| 🇫🇷 FR | 2 |
| 🇸🇪 SE | 2 |
| 🇰🇿 KZ | 2 |
| 🇮🇲 IM | 1 |
| 🇸🇨 SC | 1 |
| 🇨🇦 CA | 1 |
| 🇳🇴 NO | 1 |
| 🇮🇱 IL | 1 |
| 🇨🇭 CH | 1 |
| 🇮🇹 IT | 1 |
| 🇦🇱 AL | 1 |
| 🇨🇳 CN | 1 |
| 🇮🇩 ID | 1 |
| 🇱🇻 LV | 1 |

## Architecture

1. **Aggregator (`aggregator.py`)**: Fetches subscriptions from `sources.txt`, parses configs, deduplicates them, and saves to `all_configs.txt`.
2. **Tester (`tester.py`)**:
    * Reads `all_configs.txt`.
    * Performs mass TCP connectivity tests -> `tcp_passed.txt`.
    * Performs Real Delay tests (using Xray core) on TCP-passed configs -> `real_delay_passed.txt`.
3. **Local Auditor & Cache (`local_test.py`)**:
    * Reads `real_delay_passed.txt`.
    * Applies SSID-based priority whitelist, blacklists invalid configs, and updates `data/local_cache.json`.
    * Outputs ultra-fast configs to `tested_configs/ultra_fast.txt`.

## Output Files

* `real_delay_passed.txt`: Configs that passed full Xray connection test.
* `servers.json`: Full metadata of passed servers.
* `tested_configs/ultra_fast.txt`: Ultra-fast servers (< 500ms latency).

## Local Testing

You can run a local test to verify the configurations from your own network environment. This is useful because a config working on GitHub Actions (US/Europe) might not work from your specific location.

### Prerequisites

* Python 3.9+
* Install dependencies:
    ```bash
    pip install -r requirements.txt
    ```

### Running the Test

**Windows:**
Double-click `fast_update.bat` or `run_local.bat`.

**Linux/macOS:**
Run `./run_local.sh`.

The script will:
1. Read `real_delay_passed.txt` (which contains configs that already passed server-side tests).
2. Download Xray core if missing.
3. Test each config by attempting to connect through it to a test URL.
4. Save results to `local_reports/` and update `tested_configs/fast_servers.txt`.

## GitHub Workflow

The workflow runs daily (UTC) and commits the updated lists back to the repository.