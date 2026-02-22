import asyncio
import os
import sys
import v2ray_utils
import aiohttp
import aiodns
import time
import random
from itertools import count
from collections import Counter

# Configuration
# TCP Concurrency: High because it's just handshake
TCP_CONCURRENCY = int(os.environ.get('TCP_CONCURRENCY', 1500))
# Real Delay Concurrency: 4 instances * 150 requests = 600 concurrent connections
REAL_DELAY_BATCH_SIZE = int(os.environ.get('REAL_DELAY_BATCH_SIZE', 50))
REAL_DELAY_INSTANCES = int(os.environ.get('REAL_DELAY_INSTANCES', 8))

TCP_TIMEOUT = float(os.environ.get('TCP_TIMEOUT', 1.5))
REAL_DELAY_TIMEOUT = float(os.environ.get('REAL_DELAY_TIMEOUT', 3.0))

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
START_PORT = 20000

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
            if self.current % 1000 == 0 or self.current >= self.total:
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

async def test_batch_real_delay(batch_configs, batch_start_port, session, failure_reasons):
    """
    Tests a batch of configs using a single Xray process.
    """
    # 1. Generate Config
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

    config_json = v2ray_utils.generate_xray_batch_config(parsed_batch, batch_start_port)

    # 2. Start Xray (Async Subprocess)
    process = None
    should_read_stderr = False
    try:
        process = await asyncio.create_subprocess_exec(
            v2ray_utils.XRAY_PATH, "-c", "stdin:",
            stdin=asyncio.subprocess.PIPE,
            stdout=asyncio.subprocess.DEVNULL,
            stderr=asyncio.subprocess.PIPE
        )

        # Write config to stdin
        process.stdin.write(config_json.encode('utf-8'))
        await process.stdin.drain()
        process.stdin.close()

        # Increased startup wait to ensure ports are bound
        await asyncio.sleep(1.0)

        try:
            # If it exits within 0.1s of checking, it crashed!
            await asyncio.wait_for(process.wait(), timeout=0.1)
            # It crashed: capture stderr immediately
            stdout_data, stderr_data = await process.communicate()
            stderr_output = stderr_data if stderr_data else b""
            print(f"FATAL: Xray crashed on startup! Error: {stderr_output.decode()}")

            # CRITICAL: Save the corrupted JSON to disk so we can debug it in the CI/CD artifacts!
            with open(f"crashed_batch_{batch_start_port}.json", "w") as f:
                f.write(config_json)

            return [None] * len(batch_configs)
        except asyncio.TimeoutError:
            # Process is still running normally, proceed with aiohttp requests
            pass

        # 3. Concurrent Requests (using shared session)
        tasks = []
        for i in range(len(parsed_batch)):
            port = batch_start_port + i
            proxy_url = f"http://127.0.0.1:{port}"
            # Rotate URLs
            target_url = random.choice(TEST_URLS)
            tasks.append(
                session.get(target_url, proxy=proxy_url, timeout=REAL_DELAY_TIMEOUT)
            )

        # Run all requests
        responses = await asyncio.gather(*tasks, return_exceptions=True)

        # 4. Process Results
        batch_results = [None] * len(batch_configs)

        for i, res in enumerate(responses):
            original_idx = valid_indices[i]
            if isinstance(res, Exception):
                # Classify Exception
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
                    batch_results[original_idx] = batch_configs[original_idx]
                else:
                    failure_reasons[f"HTTP_{res.status}"] += 1
            else:
                failure_reasons['UnknownError'] += 1

        if process.returncode is not None:
            should_read_stderr = True

        return batch_results

    except Exception as e:
        # print(f"⚠️ Batch Error: {e}")
        failure_reasons['BatchCrash'] += 1
        should_read_stderr = True
        return [None] * len(batch_configs)
    finally:
        if process:
            try:
                process.terminate()
                # Async wait for termination
                await process.wait()

                if should_read_stderr:
                    stderr_output = await process.stderr.read()
                    if stderr_output:
                        print(f"⚠️ Xray Crash/Exit (Code {process.returncode}): {stderr_output.decode().strip()}")
            except ProcessLookupError:
                pass
            except Exception:
                try:
                    process.kill()
                except:
                    pass

async def run_real_delay_tests(configs):
    total = len(configs)
    if total == 0:
        return []

    print(f"🚀 Starting Real Delay tests for {total} configs...")
    print(f"ℹ️  Instances: {REAL_DELAY_INSTANCES}, Batch Size: {REAL_DELAY_BATCH_SIZE}, Total Concurrency: {REAL_DELAY_INSTANCES * REAL_DELAY_BATCH_SIZE}")

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

    # Use TCPConnector with limit=0 (Unlimited)
    connector = aiohttp.TCPConnector(limit=0)
    async with aiohttp.ClientSession(connector=connector) as session:
        async def run_batch_with_sem(batch_index, batch):
            async with sem:
                # Dynamic port allocation: START_PORT + (batch_index * BATCH_SIZE)
                # This ensures unique ports for every batch running in parallel
                # We wrap ports modulo 30000 to stay within safe range 10000-40000
                port_offset = (batch_index * REAL_DELAY_BATCH_SIZE) % 20000
                batch_start_port = START_PORT + port_offset

                results = await test_batch_real_delay(batch, batch_start_port, session, failure_reasons)
                await counter.increment(len(batch))
                return results

        tasks = [run_batch_with_sem(i, b) for i, b in enumerate(batches)]

        # Run all batches
        batch_results = await asyncio.gather(*tasks, return_exceptions=True)

    # Flatten results
    for res in batch_results:
        if isinstance(res, list):
            passed_results.extend([r for r in res if r])

    print(f"✅ Real Delay tests complete. {len(passed_results)}/{total} passed.")

    print("\n📊 Failure Summary:")
    if failure_reasons:
        for reason, count in failure_reasons.most_common():
            print(f"  - {reason}: {count}")
    else:
        print("  No failures recorded.")

    return passed_results

async def main():
    # Optimize environment
    v2ray_utils.increase_file_limit()

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
    real_delay_passed = await run_real_delay_tests(tcp_passed)

    with open(REAL_DELAY_OUTPUT_FILE, 'w', encoding='utf-8') as f:
        for c in real_delay_passed:
            f.write(c + '\n')

    print("🎉 All tests finished.")

if __name__ == "__main__":
    if sys.platform == 'win32':
        asyncio.set_event_loop_policy(asyncio.WindowsSelectorEventLoopPolicy())
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        print("\n⚠️ Interrupted.")
