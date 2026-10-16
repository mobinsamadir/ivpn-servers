#!/usr/bin/env python3
"""
ivpn-servers - Iran VPS Auditor
Dedicated, ultra-lightweight tester designed to run inside Iran.
- Safe high port range (45000+) to prevent conflict with web servers (80, 443, 22).
- Low memory & CPU footprint (2 instances, ~35MB RAM, safe for 1 vCPU / 2GB RAM).
- Tests connectivity against strictly filtered endpoints (Google, YouTube, Telegram).
"""

import asyncio
import os
import sys
import time
import random
import aiohttp
import json
import subprocess

# Ensure current dir is in sys.path
BASE_DIR = os.path.dirname(os.path.abspath(__file__))
if BASE_DIR not in sys.path:
    sys.path.insert(0, BASE_DIR)

import v2ray_utils

# --- Configuration (Tuned for Iran Server Safety) ---
INPUT_FILE = os.getenv('INPUT_FILE', 'real_delay_passed.txt')
OUTPUT_DIR = os.path.join(BASE_DIR, 'tested_configs')
PASSED_FILE = os.path.join(OUTPUT_DIR, 'iran_passed.txt')
ULTRA_FILE = os.path.join(OUTPUT_DIR, 'iran_ultra.txt')
JSON_FILE = os.path.join(BASE_DIR, 'servers_iran.json')

# Safe port range: far away from 80, 443, 22, 10808
START_PORT = 45000

# Low concurrency to ensure zero impact on existing websites
REAL_DELAY_BATCH_SIZE = 100
REAL_DELAY_INSTANCES = 2
REAL_DELAY_TIMEOUT = 3.5
MAX_ULTRA_LATENCY = 1000

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

    async def test_batch(self, batch_configs, start_port, session):
        parsed_batch = []
        valid_indices = []
        for idx, cfg in enumerate(batch_configs):
            parsed, _ = v2ray_utils.parse_config_line(cfg)
            if parsed:
                parsed_batch.append(parsed)
                valid_indices.append(idx)

        if not parsed_batch:
            return [None] * len(batch_configs)

        # Generate Xray config for this batch
        xray_json_str = v2ray_utils.generate_xray_batch_config(parsed_batch, start_port=start_port)
        if not xray_json_str:
            return [None] * len(batch_configs)

        proc = None
        try:
            xray_bin = v2ray_utils.XRAY_PATH
            proc = await asyncio.create_subprocess_exec(
                xray_bin, "-c", "stdin:",
                stdin=asyncio.subprocess.PIPE,
                stdout=asyncio.subprocess.DEVNULL,
                stderr=asyncio.subprocess.PIPE
            )

            # Send config to stdin
            proc.stdin.write(xray_json_str.encode('utf-8'))
            await proc.stdin.drain()
            proc.stdin.close()
            await proc.stdin.wait_closed()

            # Wait for startup
            await asyncio.sleep(0.5)
            if proc.returncode is not None:
                _, stderr = await proc.communicate()
                err_msg = stderr.decode(errors='replace').strip() if stderr else "unknown"
                print(f"\n⚠️ Xray batch error: {err_msg[:80]}")
                return [None] * len(batch_configs)

            # Test through local proxy
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
        except Exception as e:
            print(f"\n⚠️ Batch exception: {e}")
            return [None] * len(batch_configs)
        finally:
            if proc and proc.returncode is None:
                try:
                    proc.terminate()
                    await asyncio.wait_for(proc.wait(), timeout=1.0)
                except Exception:
                    try: proc.kill()
                    except Exception: pass

    async def run(self):
        print("🇮🇷 Starting Iran Network Verification Test...")
        print(f"📦 Input Source: {self.input_file}")
        print(f"⚙️  Concurrency: {REAL_DELAY_INSTANCES} instances | Batch: {REAL_DELAY_BATCH_SIZE} | Safe Ports: {START_PORT}+")

        if not v2ray_utils.check_and_install_xray():
            print("❌ Failed to initialize Xray binary.")
            return

        configs = self.load_configs()
        total = len(configs)
        if total == 0:
            print("⚠️ No configs to test.")
            return

        print(f"🚀 Verifying {total} configs against filtered targets (Google/YouTube)...")
        batches = [configs[i:i + REAL_DELAY_BATCH_SIZE] for i in range(0, total, REAL_DELAY_BATCH_SIZE)]
        sem = asyncio.Semaphore(REAL_DELAY_INSTANCES)
        connector = aiohttp.TCPConnector(limit=0)

        passed_results = []
        start_time = time.time()
        self.completed_count = 0

        async with aiohttp.ClientSession(connector=connector, headers=BROWSER_HEADERS) as session:
            async def run_batch_with_sem(batch_idx, batch):
                async with sem:
                    port_offset = (batch_idx * REAL_DELAY_BATCH_SIZE) % 5000
                    current_port = START_PORT + port_offset
                    await asyncio.sleep(0.1)
                    results = await self.test_batch(batch, current_port, session)
                    self.completed_count += len(batch)
                    batch_passed = sum(1 for r in results if r is not None)
                    self.passed_count += batch_passed
                    pct = round((self.completed_count / total) * 100, 1)
                    print(f"[Iran Test] Progress: {self.completed_count}/{total} ({pct}%) | Verified Working: {self.passed_count}")
                    return results

            tasks = [run_batch_with_sem(i, b) for i, b in enumerate(batches)]
            batch_results = await asyncio.gather(*tasks, return_exceptions=True)

            for res_list in batch_results:
                if isinstance(res_list, list):
                    for item in res_list:
                        if item is not None:
                            passed_results.append(item)

        elapsed = round(time.time() - start_time, 2)
        print(f"\n✅ Iran Test Complete in {elapsed}s!")
        print(f"🎯 Passed: {len(passed_results)} / {total} configs successfully bypassed Iran censorship.")

        # Sort by latency
        passed_results.sort(key=lambda x: x[1])

        # Save to output files
        with open(PASSED_FILE, 'w', encoding='utf-8') as f:
            for cfg, lat in passed_results:
                f.write(f"{cfg}\n")

        ultra_results = [item for item in passed_results if item[1] <= MAX_ULTRA_LATENCY]
        with open(ULTRA_FILE, 'w', encoding='utf-8') as f:
            for cfg, lat in ultra_results:
                f.write(f"{cfg}\n")

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

        print(f"\n📁 Results saved:")
        print(f"   - All Passed: {PASSED_FILE} ({len(passed_results)} configs)")
        print(f"   - Ultra Fast (<1s): {ULTRA_FILE} ({len(ultra_results)} configs)")
        print(f"   - JSON Metadata: {JSON_FILE}")

        # Auto-Push if requested
        if '--push' in sys.argv or os.getenv('AUTO_PUSH') == 'true':
            self.git_push_results()

    def git_push_results(self):
        print("\n📤 Pushing Iran-verified results to GitHub...")
        try:
            subprocess.run(["git", "config", "user.name", "Iran-Auditor-Bot"], check=True)
            subprocess.run(["git", "config", "user.email", "iran-bot@ivpn.local"], check=True)
            subprocess.run(["git", "add", PASSED_FILE, ULTRA_FILE, JSON_FILE], check=True)
            subprocess.run(["git", "commit", "-m", f"🇮🇷 Update Iran-verified servers [{time.strftime('%Y-%m-%d %H:%M')}]"], check=True)
            subprocess.run(["git", "pull", "--rebase", "--autostash", "-X", "theirs", "origin", "main"], check=True)
            subprocess.run(["git", "push", "origin", "main"], check=True)
            print("🎉 Successfully pushed Iran-verified servers to GitHub!")
        except Exception as e:
            print(f"⚠️ Git push failed: {e}")

if __name__ == '__main__':
    v2ray_utils.increase_file_limit()
    asyncio.run(IranAuditor().run())
