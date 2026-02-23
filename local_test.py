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
from itertools import count
from collections import Counter
import datetime

# Configuration
# TCP Concurrency: High because it's just handshake
TCP_CONCURRENCY = int(os.environ.get('TCP_CONCURRENCY', 1500))
# Real Delay Concurrency: 4 instances * 100 requests (Safe for local)
REAL_DELAY_BATCH_SIZE = 100
REAL_DELAY_INSTANCES = 4

TCP_TIMEOUT = float(os.environ.get('TCP_TIMEOUT', 1.5))
REAL_DELAY_TIMEOUT = float(os.environ.get('REAL_DELAY_TIMEOUT', 3.0))

# Latency Guard: Max allowed latency in ms
MAX_ALLOWED_LATENCY = 1200

TEST_URLS = [
    'http://cp.cloudflare.com/generate_204',
    'http://clients3.google.com/generate_204',
    'http://www.gstatic.com/generate_204',
    'http://www.apple.com/library/test/success.html'
]

INPUT_FILE = 'all_configs.txt'
TCP_OUTPUT_FILE = 'tcp_passed.txt'
REAL_DELAY_OUTPUT_FILE = 'real_delay_passed.txt'

# Base port for local testing
START_PORT = 10000

# Max recursion depth for batch splitting
MAX_RECURSION_DEPTH = 8

class XrayBatchCrash(Exception):
    """Raised when Xray crashes on startup."""
    def __init__(self, message="Xray startup failed", is_config_error=False):
        self.message = message
        self.is_config_error = is_config_error
        super().__init__(self.message)

def find_free_port_block(count, min_port=10000, max_port=60000):
    """
    Finds a contiguous block of `count` free ports.
    Tries random start ports within the range.
    """
    MAX_ATTEMPTS = 100
    for _ in range(MAX_ATTEMPTS):
        # Ensure we don't go out of bounds
        if min_port + count > max_port:
             return min_port

        start_port = random.randint(min_port, max_port - count)
        is_block_free = True

        # Verify the entire block
        for port in range(start_port, start_port + count):
            s = None
            try:
                # Try to bind to 127.0.0.1 (where Xray listens)
                s = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
                # Ensure we can reuse address quickly if we just closed it
                s.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
                s.bind(('127.0.0.1', port))
            except OSError:
                is_block_free = False
                break
            finally:
                if s:
                    s.close()

        if not is_block_free:
            continue

        return start_port

    # Fallback to random if we fail to find a guaranteed block
    print(f"⚠️ Could not find guaranteed free port block of size {count} after {MAX_ATTEMPTS} attempts. Using random.")
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
            if self.current % 100 == 0 or self.current >= self.total:
                elapsed = time.time() - self.start_time
                rate = self.current / elapsed if elapsed > 0 else 0
                print(f"[{self.name}] Progress: {min(self.current, self.total)}/{self.total} ({rate:.1f} cfg/s)...")

async def check_tcp_task(sem, config_line, resolver, counter):
    """
    Checks if the host is reachable via TCP.
    1. Resolves DNS (cached/async).
    2. Tries TCP connect to IP.
    """
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
            # 1. DNS Resolution (Non-blocking)
            ip_addr = host
            try:
                # Check if it's already an IP
                import ipaddress
                ipaddress.ip_address(host)
            except ValueError:
                # Resolve
                try:
                    result = await resolver.query(host, 'A')
                    if result:
                        ip_addr = result[0].host
                except Exception:
                     # DNS Failed
                     await counter.increment()
                     return None

            # 2. TCP Connect (to IP, avoiding re-resolution)
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

    # Initialize aiodns resolver
    loop = asyncio.get_running_loop()
    resolver = aiodns.DNSResolver(loop=loop)

    sem = asyncio.Semaphore(TCP_CONCURRENCY)
    counter = ProgressCounter(total, "TCP Test")

    tasks = [check_tcp_task(sem, c, resolver, counter) for c in configs]
    results = await asyncio.gather(*tasks, return_exceptions=True)

    # Filter None and Exceptions
    passed = [r for r in results if r is not None and not isinstance(r, Exception)]
    print(f"✅ TCP tests complete. {len(passed)}/{total} passed.")
    return passed

async def test_batch_real_delay(batch_configs, start_port_base, session, failure_reasons, batch_index=0):
    """
    Tests a batch of configs using a single Xray process.
    Handles 'address already in use' by retrying with different ports.
    Raises XrayBatchCrash if Xray fails to start (other than port conflict).
    """
    # 1. Generate Parsed Configs
    parsed_batch = []
    valid_indices = [] # Map index in parsed_batch to index in batch_configs

    for i, line in enumerate(batch_configs):
        parsed, _ = v2ray_utils.parse_config_line(line)
        if parsed:
            parsed_batch.append(parsed)
            valid_indices.append(i)
        else:
            failure_reasons['ParseError'] += 1

    if not parsed_batch:
        return [None] * len(batch_configs)

    # Retry Logic for Port Conflicts
    MAX_RETRIES = 3

    # Set asset location
    xray_assets_path = os.path.dirname(os.path.abspath(v2ray_utils.XRAY_PATH))
    env = os.environ.copy()
    env["XRAY_LOCATION_ASSET"] = xray_assets_path

    for attempt in range(MAX_RETRIES):
        # INTELLIGENT PORT HUNTING
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

            # Write config to stdin
            process.stdin.write(config_json.encode('utf-8'))
            await process.stdin.drain()
            process.stdin.close()
            await process.stdin.wait_closed()

            # Startup wait
            await asyncio.sleep(0.8)

            # Check if crashed immediately
            try:
                await asyncio.wait_for(process.wait(), timeout=0.1)
                # It crashed
                stdout_data, stderr_data = await process.communicate()
                stdout_str = stdout_data.decode(errors='replace').strip() if stdout_data else ""
                stderr_str = stderr_data.decode(errors='replace').strip() if stderr_data else ""
                combined_log = (stdout_str + "\n" + stderr_str).lower()

                # SYSTEM ERRORS: Do NOT split, just retry with new port
                if "address already in use" in combined_log or "too many open files" in combined_log:
                    print(f"⚠️ [PORT RETRY] Port {current_start_port} busy. Retrying ({attempt+1}/{MAX_RETRIES})...")
                    await asyncio.sleep(0.5)
                    continue # Retry loop

                # CONFIG ERRORS: Proceed with Recursive Splitting
                if "failed to load config files" in combined_log or "invalid uuid" in combined_log or "unknown protocol" in combined_log:
                    raise XrayBatchCrash(f"Config Error: {stderr_str[:100]}", is_config_error=True)

                raise XrayBatchCrash(f"Unknown Crash: {stderr_str[:100]}", is_config_error=True)

            except asyncio.TimeoutError:
                # Process is running
                pass

            # 3. Concurrent Requests (using shared session)
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

                tasks.append(
                    measure_request(target_url, proxy_url, REAL_DELAY_TIMEOUT)
                )

            # Run all requests
            responses = await asyncio.gather(*tasks, return_exceptions=True)

            # 4. Process Results
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
                    if isinstance(res, asyncio.TimeoutError):
                         error_type = "Timeout"
                    elif isinstance(res, aiohttp.ClientProxyConnectionError):
                         error_type = "ProxyConnectionError"
                         should_read_stderr = True
                    elif isinstance(res, aiohttp.ClientConnectorError):
                         error_type = "ConnectorError"

                    failure_reasons[error_type] += 1
                elif hasattr(res, 'status'):
                    if res.status in (200, 204, 301, 302):
                        # LATENCY GUARD: Discard if too slow
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
            raise # Re-raise to be handled by recursive splitter
        except Exception as e:
            # Unexpected python error
            print(f"⚠️ Unexpected Batch Error: {e}")
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
                    except:
                        pass
                except Exception:
                    pass

    # If we exhausted retries
    print(f"❌ Failed to start Xray batch after {MAX_RETRIES} attempts (Ports blocked?)")
    failure_reasons['PortExhaustion'] += 1
    return [None] * len(batch_configs)

async def recursive_test_batch(batch, start_port_base, session, failure_reasons, batch_index, depth=0):
    """
    Recursively splits the batch if Xray crashes on startup.
    """
    try:
        return await test_batch_real_delay(batch, start_port_base, session, failure_reasons, batch_index)
    except XrayBatchCrash:
        # Base case 1: Single item batch means we found the poison config
        if len(batch) <= 1:
            failure_reasons['PoisonConfig'] += 1
            with open("debug_poison_configs.txt", "a", encoding="utf-8") as f:
                f.write(f"[POISON] {batch[0]}\n")
            return [None]

        # Base case 2: Max recursion depth reached
        if depth >= MAX_RECURSION_DEPTH:
            print(f"⚠️ [RECURSION] Max depth {depth} reached. Discarding batch of {len(batch)}.")
            failure_reasons['MaxRecursionDiscard'] += 1
            with open("debug_poison_configs.txt", "a", encoding="utf-8") as f:
                f.write(f"[DISCARDED_BATCH] Size: {len(batch)}\n")
                for c in batch:
                    f.write(f"{c}\n")
            return [None] * len(batch)

        # Split
        mid = len(batch) // 2
        left = batch[:mid]
        right = batch[mid:]

        print(f"⚠️ [RECURSION] Splitting batch of size {len(batch)} due to config error (Depth {depth})...")

        res_left = await recursive_test_batch(left, start_port_base, session, failure_reasons, batch_index, depth + 1)

        # Add offset for right batch to minimize TIME_WAIT issues
        right_port_base = start_port_base + len(left) + 300
        res_right = await recursive_test_batch(right, right_port_base, session, failure_reasons, batch_index, depth + 1)

        return res_left + res_right

async def run_real_delay_tests(configs):
    total = len(configs)
    if total == 0:
        return []

    print(f"🚀 Starting Real Delay tests for {total} configs...")
    print(f"ℹ️  Instances: {REAL_DELAY_INSTANCES}, Batch Size: {REAL_DELAY_BATCH_SIZE}, Max Latency: {MAX_ALLOWED_LATENCY}ms")

    # Ensure Xray is ready
    if not v2ray_utils.check_and_install_xray():
        print("❌ Xray setup failed. Skipping real delay tests.")
        return []

    passed_results = []
    counter = ProgressCounter(total, "Real Delay")
    failure_reasons = Counter()

    # Create Batches
    batches = [configs[i:i + REAL_DELAY_BATCH_SIZE] for i in range(0, total, REAL_DELAY_BATCH_SIZE)]

    sem = asyncio.Semaphore(REAL_DELAY_INSTANCES)

    connector = aiohttp.TCPConnector(limit=0)
    async with aiohttp.ClientSession(connector=connector) as session:
        async def run_batch_with_sem(batch_index, batch):
            async with sem:
                # Use random start port always
                batch_start_port = START_PORT

                # Reduced stagger
                await asyncio.sleep(0.1)

                results = await recursive_test_batch(batch, batch_start_port, session, failure_reasons, batch_index, depth=0)
                await counter.increment(len(batch))
                return results

        tasks = [run_batch_with_sem(i, b) for i, b in enumerate(batches)]

        # Run all batches
        batch_results = await asyncio.gather(*tasks, return_exceptions=True)

    # Flatten results
    latencies = []
    final_configs = []

    for res in batch_results:
        if isinstance(res, list):
            for item in res:
                if item:
                    # Item is (config, latency)
                    config, latency = item
                    final_configs.append(config)
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

async def main():
    print("🚀 Starting Local Engine...")

    # Cleanup previous debug logs
    if os.path.exists("debug_poison_configs.txt"):
        try:
            os.remove("debug_poison_configs.txt")
        except OSError:
            pass

    # Optimize environment
    v2ray_utils.increase_file_limit()

    # Auto-Dependency Management
    v2ray_utils.check_and_download_geoip_db()
    v2ray_utils.check_and_install_xray()

    if not os.path.exists(INPUT_FILE):
        print(f"⚠️ {INPUT_FILE} not found.")
        return

    with open(INPUT_FILE, 'r', encoding='utf-8') as f:
        configs = [line.strip() for line in f if line.strip()]

    # 1. TCP Test
    tcp_passed = await run_tcp_tests(configs)

    with open(TCP_OUTPUT_FILE, 'w', encoding='utf-8') as f:
        for c in tcp_passed:
            f.write(c + '\n')

    # 2. Real Delay Test
    real_delay_passed, avg_latency = await run_real_delay_tests(tcp_passed)

    with open(REAL_DELAY_OUTPUT_FILE, 'w', encoding='utf-8') as f:
        for c in real_delay_passed:
            f.write(c + '\n')

    # 3. Cleanup
    for f in glob.glob("crashed_batch_*.json"):
        try:
            os.remove(f)
        except:
            pass

    if len(real_delay_passed) > 0:
        print("✅ Process Finished Successfully")
    else:
        print("⚠️ No valid configs passed the tests.")

if __name__ == "__main__":
    if sys.platform == 'win32':
        asyncio.set_event_loop_policy(asyncio.WindowsSelectorEventLoopPolicy())
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        print("\n⚠️ Interrupted.")
    finally:
        print("👋 Shutdown complete.")
