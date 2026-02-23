import asyncio
import os
import sys
import re
import v2ray_utils
import aiohttp
import aiodns
import time
import random
import glob
import socket
import datetime
import subprocess
import traceback
from collections import Counter
from itertools import count

# Environment Detection
IS_GITHUB_ACTIONS = os.getenv('GITHUB_ACTIONS') == 'true'

# 1. Environment-Aware Configuration
if IS_GITHUB_ACTIONS:
    INPUT_FILE = 'all_configs.txt'
    TCP_CONCURRENCY = 1500
    REAL_DELAY_BATCH_SIZE = 250
    REAL_DELAY_INSTANCES = 8
    print("🌍 Environment: GitHub Actions (High Concurrency)")
else:
    # Local Mode (Windows/Home)
    INPUT_FILE = 'real_delay_passed.txt'
    TCP_CONCURRENCY = 64
    REAL_DELAY_BATCH_SIZE = 100
    REAL_DELAY_INSTANCES = 4
    print("🏠 Environment: Local/Windows (Safe Concurrency)")

TCP_TIMEOUT = float(os.environ.get('TCP_TIMEOUT', 1.5))
REAL_DELAY_TIMEOUT = float(os.environ.get('REAL_DELAY_TIMEOUT', 3.0))
MAX_ALLOWED_LATENCY = 1200
START_PORT = 10000
MAX_RECURSION_DEPTH = 8

TCP_OUTPUT_FILE = 'tcp_passed.txt'
REAL_DELAY_OUTPUT_FILE = 'real_delay_passed.txt'
LOCAL_REPORTS_DIR = 'local_reports'
DEBUG_LOG_FILE = 'local_execution_debug.log'

TEST_URLS = [
    'http://cp.cloudflare.com/generate_204',
    'http://clients3.google.com/generate_204',
    'http://www.gstatic.com/generate_204',
    'http://www.apple.com/library/test/success.html'
]

# --- Logging & SSID Helpers ---

def check_vpn_active():
    """Checks for active VPN/Proxy ports and identifies the process."""
    if IS_GITHUB_ACTIONS:
        return

    vpn_ports = [1080, 2080, 7890, 10808, 10809]
    detected = []

    print("🛡️  Running Pre-Flight VPN Check...")
    for port in vpn_ports:
        with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
            s.settimeout(0.5)
            if s.connect_ex(('127.0.0.1', port)) == 0:
                detected.append(port)

    if detected:
        print(f"\n\033[1;31m[CRITICAL WARNING] VPN/Proxy Detected on port(s): {detected}\033[0m")

        # Smart Process Identification (Windows)
        if sys.platform == 'win32':
            try:
                for port in detected:
                    # Find PID
                    pid_out = subprocess.check_output(f"netstat -ano | findstr :{port}", shell=True).decode('utf-8', errors='ignore')
                    pid = None
                    for line in pid_out.splitlines():
                        if f":{port}" in line and "LISTENING" in line:
                            parts = line.strip().split()
                            if parts:
                                pid = parts[-1]
                                break

                    if pid:
                        # Find Process Name
                        task_out = subprocess.check_output(f"tasklist /FI \"PID eq {pid}\" /FO CSV /NH", shell=True).decode('utf-8', errors='ignore')
                        if task_out:
                            proc_name = task_out.split(',')[0].strip('"')
                            print(f"   ↳ Port {port} is used by: {proc_name} (PID: {pid})")

                            keywords = ['xray', 'v2ray', 'clash', 'nekoray', 'v2rayN', 'sing-box']
                            if any(k.lower() in proc_name.lower() for k in keywords):
                                print(f"   ⚠️  v2rayN/Proxy app is detected as ACTIVE on port {port}.")
                                print(f"       Even if System Proxy is CLEAR, the APP IS STILL RUNNING.")
                                print(f"       Please CLOSE the app completely for best results.")
            except Exception as e:
                print(f"   (Could not identify process details: {e})")

        print("\033[1;31mPLEASE DISABLE ALL VPNs/PROXIES BEFORE CONTINUING!\033[0m")
        try:
            input("Press Enter to acknowledge and continue (or Ctrl+C to exit)...")
        except EOFError:
            pass
    else:
        print("✅ No active VPN detected.")

class DualLogger:
    """Writes to both console and file."""
    def __init__(self, filepath):
        self.terminal = sys.stdout
        self.log = open(filepath, "w", encoding="utf-8")

    def write(self, message):
        self.terminal.write(message)
        self.log.write(message)
        self.log.flush()

    def flush(self):
        self.terminal.flush()
        self.log.flush()

def get_ssid():
    """Detects the current WiFi SSID."""
    try:
        if sys.platform == 'win32':
            # Windows: netsh wlan show interfaces
            output = subprocess.check_output("netsh wlan show interfaces", shell=True).decode('utf-8', errors='ignore')
            for line in output.split('\n'):
                line = line.strip()
                if line.startswith("SSID") and "BSSID" not in line:
                    parts = line.split(":", 1)
                    if len(parts) > 1:
                        return parts[1].strip()
        elif sys.platform == 'linux':
            # Linux: iwgetid -r
            try:
                ssid = subprocess.check_output(["iwgetid", "-r"]).decode('utf-8').strip()
                if ssid:
                    return ssid
            except FileNotFoundError:
                pass
    except Exception:
        pass
    return "Ethernet_or_Unknown"

# --- Core Logic ---

class XrayBatchCrash(Exception):
    def __init__(self, message="Xray startup failed", is_config_error=False):
        self.message = message
        self.is_config_error = is_config_error
        super().__init__(self.message)

def find_free_port_block(count, min_port=10000, max_port=60000):
    MAX_ATTEMPTS = 100
    for _ in range(MAX_ATTEMPTS):
        if min_port + count > max_port:
             return min_port

        start_port = random.randint(min_port, max_port - count)
        is_block_free = True

        for port in range(start_port, start_port + count):
            s = None
            try:
                s = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
                s.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
                s.bind(('127.0.0.1', port))
            except OSError:
                is_block_free = False
                break
            finally:
                if s: s.close()

        if not is_block_free:
            continue
        return start_port

    print(f"⚠️ Could not find guaranteed free port block of size {count}. Using random.")
    return random.randint(min_port, max_port - count)

class ProgressCounter:
    def __init__(self, total, name):
        self.total = total
        self.name = name
        self.current = 0
        self.lock = asyncio.Lock()
        self.start_time = time.time()

    async def increment(self, count=1):
        async with self.lock:
            self.current += count
            if self.current % 50 == 0 or self.current >= self.total:
                elapsed = time.time() - self.start_time
                rate = self.current / elapsed if elapsed > 0 else 0
                print(f"[{self.name}] Progress: {min(self.current, self.total)}/{self.total} ({rate:.1f} cfg/s)...")

async def check_tcp_task(sem, config_line, resolver, counter):
    parsed, _ = v2ray_utils.parse_config_line(config_line)
    if not parsed:
        await counter.increment()
        return None

    host = parsed.get('add')
    port = parsed.get('port')

    if not host or not port:
        await counter.increment()
        return None

    try:
        async with sem:
            # DNS
            ip_addr = host
            try:
                import ipaddress
                ipaddress.ip_address(host)
            except ValueError:
                try:
                    result = await resolver.query_dns(host, 'A')
                    if result:
                        ip_addr = result[0].host
                except Exception:
                     await counter.increment()
                     return None

            # TCP Connect
            success = await v2ray_utils.test_tcp_connection(ip_addr, port, TCP_TIMEOUT)
            await counter.increment()
            if success:
                return config_line
    except Exception:
        await counter.increment()
        return None
    return None

async def run_tcp_tests(configs):
    total = len(configs)
    print(f"🚀 Starting TCP tests for {total} configs with concurrency {TCP_CONCURRENCY}...")

    loop = asyncio.get_running_loop()
    resolver = aiodns.DNSResolver(loop=loop)

    sem = asyncio.Semaphore(TCP_CONCURRENCY)
    counter = ProgressCounter(total, "TCP Test")

    tasks = [check_tcp_task(sem, c, resolver, counter) for c in configs]
    results = await asyncio.gather(*tasks, return_exceptions=True)

    passed = [r for r in results if r is not None and not isinstance(r, Exception)]
    print(f"✅ TCP tests complete. {len(passed)}/{total} passed.")
    return passed

async def test_batch_real_delay(batch_configs, start_port_base, session, failure_reasons, batch_index=0):
    parsed_batch = []
    valid_indices = []

    for i, line in enumerate(batch_configs):
        parsed, _ = v2ray_utils.parse_config_line(line)
        if parsed:
            parsed_batch.append(parsed)
            valid_indices.append(i)
        else:
            failure_reasons['ParseError'] += 1

    if not parsed_batch:
        return [None] * len(batch_configs)

    MAX_RETRIES = 3
    xray_assets_path = os.path.dirname(os.path.abspath(v2ray_utils.XRAY_PATH))
    env = os.environ.copy()
    env["XRAY_LOCATION_ASSET"] = xray_assets_path

    for attempt in range(MAX_RETRIES):
        current_start_port = find_free_port_block(len(parsed_batch), min_port=start_port_base)
        config_json = v2ray_utils.generate_xray_batch_config(parsed_batch, current_start_port)

        process = None
        should_read_stderr = False

        try:
            process = await asyncio.create_subprocess_exec(
                v2ray_utils.XRAY_PATH, "-c", "stdin:",
                stdin=asyncio.subprocess.PIPE,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
                env=env
            )

            process.stdin.write(config_json.encode('utf-8'))
            await process.stdin.drain()
            process.stdin.close()
            await process.stdin.wait_closed()

            await asyncio.sleep(0.8)

            try:
                await asyncio.wait_for(process.wait(), timeout=0.1)
                stdout_data, stderr_data = await process.communicate()
                stdout_str = stdout_data.decode(errors='replace').strip() if stdout_data else ""
                stderr_str = stderr_data.decode(errors='replace').strip() if stderr_data else ""
                combined_log = (stdout_str + "\n" + stderr_str).lower()

                if "address already in use" in combined_log or "too many open files" in combined_log:
                    print(f"⚠️ [PORT RETRY] Port {current_start_port} busy. Retrying ({attempt+1}/{MAX_RETRIES})...")
                    await asyncio.sleep(0.5)
                    continue

                if "failed to load config files" in combined_log or "invalid uuid" in combined_log:
                    raise XrayBatchCrash(f"Config Error: {stderr_str[:100]}", is_config_error=True)

                raise XrayBatchCrash(f"Unknown Crash: {stderr_str[:100]}", is_config_error=True)

            except asyncio.TimeoutError:
                pass

            tasks = []
            for i in range(len(parsed_batch)):
                port = current_start_port + i
                proxy_url = f"http://127.0.0.1:{port}"
                target_url = random.choice(TEST_URLS)

                async def measure_request(url, proxy, timeout):
                    start_t = time.time()
                    try:
                        resp = await session.get(url, proxy=proxy, timeout=timeout)
                        latency = (time.time() - start_t) * 1000
                        return resp, latency
                    except Exception as e:
                        return e, None

                tasks.append(measure_request(target_url, proxy_url, REAL_DELAY_TIMEOUT))

            responses = await asyncio.gather(*tasks, return_exceptions=True)
            batch_results = [None] * len(batch_configs)

            for i, res_tuple in enumerate(responses):
                original_idx = valid_indices[i]
                if isinstance(res_tuple, Exception):
                     res = res_tuple
                     latency = None
                else:
                     res, latency = res_tuple

                if isinstance(res, Exception):
                    error_type = type(res).__name__
                    if isinstance(res, asyncio.TimeoutError): error_type = "Timeout"
                    elif isinstance(res, aiohttp.ClientProxyConnectionError):
                         error_type = "ProxyConnectionError"
                         should_read_stderr = True
                    failure_reasons[error_type] += 1
                elif hasattr(res, 'status'):
                    if res.status in (200, 204, 301, 302):
                        if latency is not None and latency <= MAX_ALLOWED_LATENCY:
                            batch_results[original_idx] = (batch_configs[original_idx], latency)
                        else:
                            failure_reasons['HighLatency'] += 1
                    else:
                        failure_reasons[f"HTTP_{res.status}"] += 1
                else:
                    failure_reasons['UnknownError'] += 1

            return batch_results

        except XrayBatchCrash:
            raise
        except Exception as e:
            print(f"⚠️ Unexpected Batch Error: {e}")
            print(traceback.format_exc())
            failure_reasons['BatchCrash'] += 1
            return [None] * len(batch_configs)
        finally:
            if process and process.returncode is None:
                try:
                    process.terminate()
                    await asyncio.wait_for(process.communicate(), timeout=2.0)
                except asyncio.TimeoutError:
                    try:
                        process.kill()
                        await process.communicate()
                    except: pass
                except Exception: pass

    print(f"❌ Failed to start Xray batch after {MAX_RETRIES} attempts.")
    failure_reasons['PortExhaustion'] += 1
    return [None] * len(batch_configs)

async def recursive_test_batch(batch, start_port_base, session, failure_reasons, batch_index, depth=0):
    try:
        return await test_batch_real_delay(batch, start_port_base, session, failure_reasons, batch_index)
    except XrayBatchCrash:
        if len(batch) <= 1:
            failure_reasons['PoisonConfig'] += 1
            with open("debug_poison_configs.txt", "a", encoding="utf-8") as f:
                f.write(f"[POISON] {batch[0]}\n")
            return [None]

        if depth >= MAX_RECURSION_DEPTH:
            failure_reasons['MaxRecursionDiscard'] += 1
            with open("debug_poison_configs.txt", "a", encoding="utf-8") as f:
                f.write(f"[DISCARDED_BATCH] Size: {len(batch)}\n")
            return [None] * len(batch)

        mid = len(batch) // 2
        left = batch[:mid]
        right = batch[mid:]
        print(f"⚠️ [RECURSION] Splitting batch of size {len(batch)} (Depth {depth})...")

        res_left = await recursive_test_batch(left, start_port_base, session, failure_reasons, batch_index, depth + 1)
        right_port_base = start_port_base + len(left) + 300
        res_right = await recursive_test_batch(right, right_port_base, session, failure_reasons, batch_index, depth + 1)

        return res_left + res_right

async def run_real_delay_tests(configs):
    total = len(configs)
    if total == 0: return [], 0

    print(f"🚀 Starting Real Delay tests for {total} configs...")
    print(f"ℹ️  Instances: {REAL_DELAY_INSTANCES}, Batch Size: {REAL_DELAY_BATCH_SIZE}")

    if not v2ray_utils.check_and_install_xray():
        print("❌ Xray setup failed.")
        return [], 0

    counter = ProgressCounter(total, "Real Delay")
    failure_reasons = Counter()
    batches = [configs[i:i + REAL_DELAY_BATCH_SIZE] for i in range(0, total, REAL_DELAY_BATCH_SIZE)]
    sem = asyncio.Semaphore(REAL_DELAY_INSTANCES)

    connector = aiohttp.TCPConnector(limit=0)
    async with aiohttp.ClientSession(connector=connector) as session:
        async def run_batch_with_sem(batch_index, batch):
            async with sem:
                port_offset = (batch_index * REAL_DELAY_BATCH_SIZE) % 20000
                batch_start_port = START_PORT + port_offset
                await asyncio.sleep(0.1)
                results = await recursive_test_batch(batch, batch_start_port, session, failure_reasons, batch_index, depth=0)
                await counter.increment(len(batch))
                return results

        tasks = [run_batch_with_sem(i, b) for i, b in enumerate(batches)]
        batch_results = await asyncio.gather(*tasks, return_exceptions=True)

    latencies = []
    final_configs = [] # List of tuples (config, latency)

    for res in batch_results:
        if isinstance(res, list):
            for item in res:
                if item:
                    config, latency = item
                    final_configs.append((config, latency))
                    if latency is not None:
                        latencies.append(latency)

    avg_latency = sum(latencies) / len(latencies) if latencies else 0
    print(f"✅ Real Delay tests complete. {len(final_configs)}/{total} passed. Avg Latency: {avg_latency:.0f}ms")

    print("\n📊 Failure Summary:")
    if failure_reasons:
        for reason, count in failure_reasons.most_common():
            print(f"  - {reason}: {count}")
    else:
        print("  No failures recorded.")

    return final_configs, avg_latency

def update_readme(tcp_passed_count, real_delay_passed_count, country_stats, avg_latency=0):
    """Updates README.md with the latest statistics."""
    if not os.path.exists("README.md"):
        return

    try:
        with open("README.md", "r", encoding="utf-8") as f:
            content = f.read()

        now = datetime.datetime.now(datetime.UTC).strftime("%Y-%m-%d %H:%M:%S UTC")
        success_rate = (real_delay_passed_count / tcp_passed_count * 100) if tcp_passed_count > 0 else 0

        if tcp_passed_count == 0:
            health = "❓ Unknown"
        elif success_rate >= 50:
            health = "🟢 Excellent"
        elif success_rate >= 20:
            health = "🟡 Degraded"
        else:
            health = "🔴 Critical"

        stats_md = f"""
## 📊 Statistics (Last Updated: {now})

| Metric | Count |
| :--- | :--- |
| **TCP Passed** | `{tcp_passed_count}` |
| **Real Delay Passed** | `{real_delay_passed_count}` |
| **Average Latency** | `{avg_latency:.0f} ms` |
| **Success Rate** | `{success_rate:.1f}%` |
| **System Health** | {health} |

### 🌍 Server Distribution

| Country | Count |
| :--- | :--- |
"""
        sorted_stats = sorted(country_stats.items(), key=lambda item: item[1], reverse=True)
        for country, count in sorted_stats:
            flag = v2ray_utils.get_country_flag(country)
            stats_md += f"| {flag} {country} | {count} |\n"

        pattern = r"## 📊 Statistics.*?(?=## |\Z)"
        if re.search(pattern, content, re.DOTALL):
            new_content = re.sub(pattern, stats_md, content, flags=re.DOTALL)
        else:
            lines = content.splitlines()
            if len(lines) > 2:
                lines.insert(2, "\n" + stats_md)
                new_content = "\n".join(lines)
            else:
                new_content = content + "\n" + stats_md

        with open("README.md", "w", encoding="utf-8") as f:
            f.write(new_content)

        print("✅ README.md updated.")

    except Exception as e:
        print(f"⚠️ Failed to update README: {e}")

def cleanup_old_reports():
    """Deletes local reports older than 7 days."""
    if not os.path.exists(LOCAL_REPORTS_DIR):
        return

    now = time.time()
    cutoff = now - (7 * 86400)

    deleted = 0
    for f in glob.glob(os.path.join(LOCAL_REPORTS_DIR, "*")):
        try:
            if os.path.getmtime(f) < cutoff:
                os.remove(f)
                deleted += 1
        except Exception:
            pass
    if deleted > 0:
        print(f"🧹 Cleaned up {deleted} old reports.")

def save_local_report(results, ssid, avg_latency, total_tcp_count):
    """Saves timestamped report to local_reports/."""
    if not os.path.exists(LOCAL_REPORTS_DIR):
        os.makedirs(LOCAL_REPORTS_DIR)

    timestamp = datetime.datetime.now(datetime.UTC).strftime("%Y-%m-%d_%H-%M")
    # Clean SSID for filename
    safe_ssid = "".join([c for c in ssid if c.isalnum() or c in (' ', '-', '_')]).strip()
    if not safe_ssid: safe_ssid = "Unknown"

    filename = f"Result_{timestamp}_{safe_ssid}.txt"
    filepath = os.path.join(LOCAL_REPORTS_DIR, filename)
    success_rate = (len(results) / total_tcp_count * 100) if total_tcp_count > 0 else 0

    try:
        with open(filepath, "w", encoding="utf-8") as f:
            f.write(f"# Local Audit Report\n")
            f.write(f"# Date: {datetime.datetime.now(datetime.UTC)}\n")
            f.write(f"# Network (SSID): {ssid}\n")
            f.write(f"# Avg Latency: {avg_latency:.0f}ms\n")
            f.write(f"# Success Rate: {success_rate:.1f}%\n")
            f.write(f"# Total Passed: {len(results)}\n\n")

            # Sort by latency
            results.sort(key=lambda x: x[1] if x[1] is not None else 9999)

            for config, latency in results:
                f.write(f"[{latency:.0f}ms] {config}\n")

        print(f"📄 Report saved to: {filepath}")
    except Exception as e:
        print(f"⚠️ Failed to save report: {e}")

async def main():
    # Setup Dual Logging
    sys.stdout = DualLogger(DEBUG_LOG_FILE)
    sys.stderr = sys.stdout # Redirect stderr too

    check_vpn_active()
    print(f"Starting Test on [{get_ssid()}] at [{datetime.datetime.now(datetime.UTC)}]")

    # Cleanup previous debug logs
    if os.path.exists("debug_poison_configs.txt"):
        try: os.remove("debug_poison_configs.txt")
        except OSError: pass

    v2ray_utils.increase_file_limit()
    v2ray_utils.check_and_download_geoip_db()

    if not os.path.exists(INPUT_FILE):
        print(f"⚠️ {INPUT_FILE} not found. Ensure previous steps ran correctly.")
        return

    with open(INPUT_FILE, 'r', encoding='utf-8') as f:
        configs = [line.strip() for line in f if line.strip()]

    # 1. TCP Test
    tcp_passed = await run_tcp_tests(configs)

    if IS_GITHUB_ACTIONS:
        # Save TCP results only on GitHub
        with open(TCP_OUTPUT_FILE, 'w', encoding='utf-8') as f:
            for c in tcp_passed:
                f.write(c + '\n')

    # 2. Real Delay Test
    real_delay_results, avg_latency = await run_real_delay_tests(tcp_passed)

    # Extract just configs for standard output files
    final_configs = [c for c, l in real_delay_results]

    # Always write standard output for compatibility (local tools might expect it)
    with open(REAL_DELAY_OUTPUT_FILE, 'w', encoding='utf-8') as f:
        for c in final_configs:
            f.write(c + '\n')

    # Golden List (<500ms)
    ultra_fast = [c for c, l in real_delay_results if l is not None and l < 500]
    if not os.path.exists('tested_configs'):
        os.makedirs('tested_configs')
    with open('tested_configs/ultra_fast.txt', 'w', encoding='utf-8') as f:
        for c in ultra_fast:
            f.write(c + '\n')
    if ultra_fast:
        print(f"🌟 Saved {len(ultra_fast)} ultra-fast configs (<500ms) to tested_configs/ultra_fast.txt")
    else:
        print("ℹ️  No ultra-fast configs (<500ms) found. Cleared Golden List.")

    if not IS_GITHUB_ACTIONS:
        # Local Mode: Save Detailed Report
        save_local_report(real_delay_results, get_ssid(), avg_latency, len(tcp_passed))
        cleanup_old_reports()

    # 3. Cleanup
    for f in glob.glob("crashed_batch_*.json"):
        try: os.remove(f)
        except: pass

    # 4. Generate Stats (Update README)
    country_stats = Counter()
    for config in final_configs:
        parsed, _ = v2ray_utils.parse_config_line(config)
        if parsed:
            ps = parsed.get('ps', '')
            match = re.search(r'\[.*? ([A-Z]{2})\]', ps)
            if match:
                country_stats[match.group(1)] += 1
            else:
                country_stats['Unknown'] += 1

    update_readme(len(tcp_passed), len(final_configs), country_stats, avg_latency)

    if len(final_configs) > 0:
        print("✅ Process Finished Successfully")
    else:
        print("⚠️ No valid configs passed the tests.")

if __name__ == "__main__":
    if sys.platform == 'win32':
        asyncio.set_event_loop_policy(asyncio.WindowsProactorEventLoopPolicy())
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        print("\n⚠️ Interrupted.")
    finally:
        print("👋 Shutdown complete.")
