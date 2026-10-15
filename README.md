# V2Ray Config Aggregator & Tester

## 📊 Statistics (Last Updated: 2026-10-15 01:21:36 UTC)

| Metric | Count |
| :--- | :--- |
| **TCP Passed** | `8265` |
| **Real Delay Passed** | `310` |
| **Average Latency** | `633 ms` |
| **Success Rate** | `3.8%` |
| **System Health** | 🔴 Critical |

### 🌍 Server Distribution

| Country | Count |
| :--- | :--- |
| 🇩🇪 DE | 37 |
| 🇫🇷 FR | 33 |
| 🇳🇱 NL | 29 |
| 🚩 Unknown | 28 |
| 🇺🇸 US | 21 |
| 🇷🇺 RU | 14 |
| 🇱🇻 LV | 11 |
| 🇸🇪 SE | 6 |
| 🇲🇾 MY | 5 |
| 🇭🇰 HK | 4 |
| 🇯🇵 JP | 4 |

This tool aggregates V2Ray/Xray subscription URLs, deduplicates configurations, and tests them for TCP connectivity and Real Delay (latency). It automatically updates the list of valid configurations every 24 hours via GitHub Actions.

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