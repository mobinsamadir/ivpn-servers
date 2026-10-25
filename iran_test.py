#!/usr/bin/env python3
"""
ivpn-servers - Iran VPS Dedicated Auditor (Resilient & Safe)
- Gentle on CPU/RAM: batch_size=30, instances=2, ~20MB RAM, safe for 1 vCPU.
- Safe ports: 42000-55000 with socket pre-check (find_free_port_block).
- High Timeout: 5.0s for high-latency / throttled networks in Iran.
- Recursive batch splitting: isolates poison configs without dropping good configs.
- Full debug logging to iran_test_debug.log.
"""

import asyncio
import os
import sys
import time
import random
import socket
import aiohttp
import json
import subprocess
import base64

# Ensure current dir is in sys.path
BASE_DIR = os.path.dirname(os.path.abspath(__file__))
if BASE_DIR not in sys.path:
    sys.path.insert(0, BASE_DIR)

import v2ray_utils

# --- Configuration ---
INPUT_FILE = os.getenv('INPUT_FILE', 'real_delay_passed.txt')
OUTPUT_DIR = os.path.join(BASE_DIR, 'tested_configs')
PASSED_FILE = os.path.join(OUTPUT_DIR, 'iran_passed.txt')
ULTRA_FILE = os.path.join(OUTPUT_DIR, 'iran_ultra.txt')
PASSED_BASE64_FILE = os.path.join(OUTPUT_DIR, 'iran_passed_base64.txt')
ULTRA_BASE64_FILE = os.path.join(OUTPUT_DIR, 'iran_ultra_base64.txt')
JSON_FILE = os.path.join(BASE_DIR, 'servers_iran.json')
DEBUG_LOG_FILE = os.path.join(BASE_DIR, 'iran_test_debug.log')

# Safe port range: far away from 80, 443, 22, 10808
MIN_PORT = 42000
MAX_PORT = 55000

# Tuned for Iran network conditions: small gentle batches, generous timeout
REAL_DELAY_BATCH_SIZE = 30
REAL_DELAY_INSTANCES = 2
REAL_DELAY_TIMEOUT = 5.0
MAX_ULTRA_LATENCY = 1500
MAX_RECURSION_DEPTH = 5

# Targets that are strictly filtered inside Iran
IRAN_FILTERED_TARGETS = [
    'http://www.google.com/generate_204',
    'https://www.youtube.com/generate_204',
    'http://clients3.google.com/generate_204'
]

BROWSER_HEADERS = {
    'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/122.0.0.0 Safari/537.36',
    'Accept': '*/*',
    'Connection': 'keep-alive'
}

class XrayBatchCrash(Exception):
    def __init__(self, message, is_config_error=True):
        self.message = message
        self.is_config_error = is_config_error
        super().__init__(self.message)

def log_debug(msg):
    ts = time.strftime('%Y-%m-%d %H:%M:%S')
    with open(DEBUG_LOG_FILE, 'a', encoding='utf-8') as f:
        f.write(f"[{ts}] {msg}\n")

def find_free_port_block(count, min_port=MIN_PORT, max_port=MAX_PORT):
    """Finds a contiguous block of `count` free ports on 127.0.0.1."""
    for _ in range(50):
        start_port = random.randint(min_port, max_port - count)
        is_free = True
        for port in range(start_port, start_port + count):
            s = None
            try:
                s = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
                s.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
                s.bind(('127.0.0.1', port))
            except OSError:
                is_free = False
                break
            finally:
                if s: s.close()
        if is_free:
            return start_port
    return random.randint(min_port, max_port - count)

class IranAuditor:
    def __init__(self, input_file=INPUT_FILE):
        self.input_file = input_file
        os.makedirs(OUTPUT_DIR, exist_ok=True)
        self.completed_count = 0
        self.passed_count = 0

    def load_configs(self):
        if not os.path.exists(self.input_file):
            print(f"❌ Input file not found: {self.input_file}")
            return []
        with open(self.input_file, 'r', encoding='utf-8') as f:
            configs = [line.strip() for line in f if line.strip() and not line.startswith('#')]
        return configs

    async def execute_xray_batch(self, batch_configs, start_port, session):
        parsed_batch = []
        valid_indices = []
        for idx, cfg in enumerate(batch_configs):
            parsed, _ = v2ray_utils.parse_config_line(cfg)
            if parsed:
                parsed_batch.append(parsed)
                valid_indices.append(idx)

        if not parsed_batch:
            return [None] * len(batch_configs)

        # Set asset environment
        xray_assets_path = os.path.dirname(os.path.abspath(v2ray_utils.XRAY_PATH))
        env = os.environ.copy()
        env["XRAY_LOCATION_ASSET"] = xray_assets_path

        # Generate Xray config
        config_json = v2ray_utils.generate_xray_batch_config(parsed_batch, start_port)
        if not config_json:
            return [None] * len(batch_configs)

        proc = None
        try:
            proc = await asyncio.create_subprocess_exec(
                v2ray_utils.XRAY_PATH, "-c", "stdin:",
                stdin=asyncio.subprocess.PIPE,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
                env=env
            )

            # Write config to stdin
            proc.stdin.write(config_json.encode('utf-8'))
            await proc.stdin.drain()
            proc.stdin.close()
            await proc.stdin.wait_closed()

            # Startup wait
            await asyncio.sleep(0.6)

            # Check if crashed
            if proc.returncode is not None:
                stdout_data, stderr_data = await proc.communicate()
                out_str = stdout_data.decode(errors='replace').strip() if stdout_data else ""
                err_str = stderr_data.decode(errors='replace').strip() if stderr_data else ""
                log_debug(f"Xray Crash on port {start_port}: stdout={out_str[:120]} stderr={err_str[:120]}")
                raise XrayBatchCrash(f"{out_str} {err_str}", is_config_error=True)

            # Run proxy requests
            tasks = []
            for i in range(len(parsed_batch)):
                port = start_port + i
                proxy_url = f"http://127.0.0.1:{port}"

                async def measure(pxy):
                    for target_url in IRAN_FILTERED_TARGETS:
                        t0 = time.time()
                        try:
                            resp = await session.get(target_url, proxy=pxy, timeout=REAL_DELAY_TIMEOUT)
                            if hasattr(resp, 'status') and resp.status in (200, 204):
                                lat = (time.time() - t0) * 1000
                                return resp, lat
                        except Exception:
                            continue
                    return None, None

                tasks.append(measure(proxy_url))

            responses = await asyncio.gather(*tasks, return_exceptions=True)
            batch_results = [None] * len(batch_configs)

            for i, res_tuple in enumerate(responses):
                orig_idx = valid_indices[i]
                if isinstance(res_tuple, tuple) and res_tuple[0] is not None:
                    batch_results[orig_idx] = (batch_configs[orig_idx], res_tuple[1])

            return batch_results
        finally:
            if proc and proc.returncode is None:
                try:
                    proc.terminate()
                    await asyncio.wait_for(proc.wait(), timeout=1.0)
                except Exception:
                    try: proc.kill()
                    except Exception: pass

    async def recursive_test_batch(self, batch, session, depth=0):
        """Recursively splits the batch if Xray crashes, isolating poison configs."""
        start_port = find_free_port_block(len(batch))
        try:
            return await self.execute_xray_batch(batch, start_port, session)
        except XrayBatchCrash:
            if len(batch) <= 1:
                log_debug(f"Isolated Poison Config: {batch[0] if batch else ''}")
                return [None] * len(batch)
            if depth >= MAX_RECURSION_DEPTH:
                log_debug(f"Max recursion depth reached for batch size {len(batch)}")
                return [None] * len(batch)

            mid = len(batch) // 2
            left = batch[:mid]
            right = batch[mid:]
            print(f"⚠️ Splitting batch ({len(batch)} -> {len(left)} + {len(right)}) to isolate bad config...")
            res_left = await self.recursive_test_batch(left, session, depth + 1)
            res_right = await self.recursive_test_batch(right, session, depth + 1)
            return res_left + res_right

    async def run(self):
        print("==========================================")
        print("🇮🇷 Starting Iran Network Verification Test")
        print(f"📦 Input Source: {self.input_file}")
        print(f"⚙️  Gentle Mode: batch={REAL_DELAY_BATCH_SIZE} | timeout={REAL_DELAY_TIMEOUT}s | ports={MIN_PORT}-{MAX_PORT}")
        print(f"📝 Debug log: {DEBUG_LOG_FILE}")
        print("==========================================")

        if not v2ray_utils.check_and_install_xray():
            print("❌ Failed to initialize Xray binary.")
            return

        configs = self.load_configs()
        total = len(configs)
        if total == 0:
            print("⚠️ No configs to test.")
            return

        print(f"🚀 Testing {total} configs against filtered targets (Google/YouTube)...")
        batches = [configs[i:i + REAL_DELAY_BATCH_SIZE] for i in range(0, total, REAL_DELAY_BATCH_SIZE)]
        sem = asyncio.Semaphore(REAL_DELAY_INSTANCES)
        connector = aiohttp.TCPConnector(limit=0)

        passed_results = []
        start_time = time.time()
        self.completed_count = 0
        self.passed_count = 0

        async with aiohttp.ClientSession(connector=connector, headers=BROWSER_HEADERS) as session:
            async def run_batch_with_sem(batch):
                async with sem:
                    # Gentle pause between batches to prevent socket congestion
                    await asyncio.sleep(0.3)
                    results = await self.recursive_test_batch(batch, session)
                    self.completed_count += len(batch)
                    batch_passed = sum(1 for r in results if r is not None)
                    self.passed_count += batch_passed
                    pct = round((self.completed_count / total) * 100, 1)
                    print(f"[Iran Test] Progress: {self.completed_count}/{total} ({pct}%) | Verified Working: {self.passed_count}")
                    return results

            tasks = [run_batch_with_sem(b) for b in batches]
            batch_results = await asyncio.gather(*tasks, return_exceptions=True)

            for res_list in batch_results:
                if isinstance(res_list, list):
                    for item in res_list:
                        if item is not None:
                            passed_results.append(item)

        elapsed = round(time.time() - start_time, 2)
        print("\n==========================================")
        print(f"✅ Iran Test Complete in {elapsed}s!")
        print(f"🎯 Passed: {len(passed_results)} / {total} configs successfully bypassed Iran censorship.")
        print("==========================================")

        # Sort by latency
        passed_results.sort(key=lambda x: x[1])

        # Save to output files
        passed_text = "".join(f"{cfg}\n" for cfg, lat in passed_results)
        with open(PASSED_FILE, 'w', encoding='utf-8') as f:
            f.write(passed_text)
        with open(PASSED_BASE64_FILE, 'w', encoding='utf-8') as f:
            f.write(base64.b64encode(passed_text.encode('utf-8')).decode('utf-8'))

        ultra_results = [item for item in passed_results if item[1] <= MAX_ULTRA_LATENCY]
        ultra_text = "".join(f"{cfg}\n" for cfg, lat in ultra_results)
        with open(ULTRA_FILE, 'w', encoding='utf-8') as f:
            f.write(ultra_text)
        with open(ULTRA_BASE64_FILE, 'w', encoding='utf-8') as f:
            f.write(base64.b64encode(ultra_text.encode('utf-8')).decode('utf-8'))

        # JSON metadata
        json_data = {
            "updated_at": time.strftime("%Y-%m-%d %H:%M:%S UTC", time.gmtime()),
            "total_tested": total,
            "passed_count": len(passed_results),
            "ultra_count": len(ultra_results),
            "test_location": "Iran VPS",
            "servers": [{"config": c, "latency_ms": round(l, 1)} for c, l in passed_results]
        }
        with open(JSON_FILE, 'w', encoding='utf-8') as f:
            json.dump(json_data, f, indent=2, ensure_ascii=False)

        print(f"📁 Results saved:")
        print(f"   - All Passed: {PASSED_FILE} ({len(passed_results)} configs)")
        print(f"   - Ultra Fast (<1.5s): {ULTRA_FILE} ({len(ultra_results)} configs)")
        print(f"   - JSON Metadata: {JSON_FILE}")

        # Auto-Push if requested
        if '--push' in sys.argv or os.getenv('AUTO_PUSH') == 'true':
            self.git_push_results()

    def git_push_results(self):
        print("\n📤 Pushing Iran-verified results to GitHub...")
        try:
            subprocess.run(["git", "config", "user.name", "Iran-Auditor-Bot"], check=True)
            subprocess.run(["git", "config", "user.email", "iran-bot@ivpn.local"], check=True)
            subprocess.run(["git", "add", "tested_configs/iran_passed.txt", "tested_configs/iran_ultra.txt", "tested_configs/iran_passed_base64.txt", "tested_configs/iran_ultra_base64.txt", "servers_iran.json"], check=True)
            diff_check = subprocess.run(["git", "diff", "--cached", "--quiet"])
            if diff_check.returncode == 0:
                print("ℹ️ No changes detected in tested results. Everything is already up to date on GitHub.")
                return
            subprocess.run(["git", "commit", "-m", f"🇮🇷 Update Iran-verified servers [{time.strftime('%Y-%m-%d %H:%M UTC', time.gmtime())}]"], check=True)
            subprocess.run(["git", "pull", "--rebase", "--autostash", "-X", "theirs", "origin", "main"], check=True)
            subprocess.run(["git", "push", "origin", "main"], check=True)
            print("🎉 Successfully pushed Iran-verified servers to GitHub!")
        except Exception as e:
            print(f"⚠️ Git push failed: {e}")

if __name__ == '__main__':
    v2ray_utils.increase_file_limit()
    asyncio.run(IranAuditor().run())
