import asyncio
import os
import sys
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
# Real Delay Concurrency: 4 instances * 200 requests = 800 concurrent connections
REAL_DELAY_BATCH_SIZE = int(os.environ.get('REAL_DELAY_BATCH_SIZE', 200))
REAL_DELAY_INSTANCES = int(os.environ.get('REAL_DELAY_INSTANCES', 1))

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
             # Should not happen with current constants
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
        # INTELLIGENT PORT HUNTING (Global Override)
        # We override start_port_base with a guaranteed free block for EVERY attempt
        current_start_port = find_free_port_block(len(parsed_batch))

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
            await asyncio.sleep(0.8) # Increased to 0.8s for stability

            # Check if crashed immediately
            try:
                await asyncio.wait_for(process.wait(), timeout=0.1)
                # It crashed
                stdout_data, stderr_data = await process.communicate()
                # Use errors='replace' to avoid crashes on non-UTF-8 output
                stdout_str = stdout_data.decode(errors='replace').strip() if stdout_data else ""
                stderr_str = stderr_data.decode(errors='replace').strip() if stderr_data else ""
                combined_log = (stdout_str + "\n" + stderr_str).lower()

                # SYSTEM ERRORS: Do NOT split, just retry with new port
                if "address already in use" in combined_log or "too many open files" in combined_log:
                    print(f"⚠️ [PORT RETRY] Port {current_start_port} busy/system error. Retrying with new block ({attempt+1}/{MAX_RETRIES})...")
                    # No need to manually pick port, next loop iteration calls find_free_port_block again
                    await asyncio.sleep(0.5)
                    continue # Retry loop

                # CONFIG ERRORS: Proceed with Recursive Splitting
                if "failed to load config files" in combined_log or "invalid uuid" in combined_log or "unknown protocol" in combined_log:
                    raise XrayBatchCrash(f"Config Error: {stderr_str[:100]}", is_config_error=True)

                # If not explicitly identified, treat as crash (likely config error)
                # print(f"FATAL: Xray crashed on startup! STDERR: {stderr_str[:200]}")
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

            return batch_results

        except XrayBatchCrash:
            raise # Re-raise to be handled by recursive splitter
        except Exception as e:
            # Unexpected python error
            print(f"⚠️ Unexpected Batch Error: {e}")
            failure_reasons['BatchCrash'] += 1
            return [None] * len(batch_configs)
        finally:
            if process:
                try:
                    process.terminate()
                    try:
                        await asyncio.wait_for(process.wait(), timeout=2.0)
                    except asyncio.TimeoutError:
                        process.kill()
                        await process.wait()

                    if should_read_stderr and process.returncode != 0:
                         # Just consume stderr to avoid pipe deadlock if not read yet
                         await process.stderr.read()
                except:
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
            # Poison config found
            failure_reasons['PoisonConfig'] += 1
            # Log to debug file
            with open("debug_poison_configs.txt", "a", encoding="utf-8") as f:
                f.write(f"[POISON] {batch[0]}\n")
            return [None]

        # Base case 2: Max recursion depth reached
        if depth >= MAX_RECURSION_DEPTH:
            print(f"⚠️ [RECURSION] Max depth {depth} reached. Discarding batch of {len(batch)}.")
            failure_reasons['MaxRecursionDiscard'] += 1
            # Log discarded batch
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

        # We execute sequentially to respect the semaphore (1 slot per batch)
        # Use random port jumps or simple offset. Since we are sequential, we can just bump ports.

        res_left = await recursive_test_batch(left, start_port_base, session, failure_reasons, batch_index, depth + 1)

        # Add offset for right batch to minimize TIME_WAIT issues, or use random
        right_port_base = start_port_base + len(left) + 50
        res_right = await recursive_test_batch(right, right_port_base, session, failure_reasons, batch_index, depth + 1)

        return res_left + res_right

async def run_real_delay_tests(configs):
    total = len(configs)
    if total == 0:
        return []

    print(f"🚀 Starting Real Delay tests for {total} configs...")
    print(f"ℹ️  Instances: {REAL_DELAY_INSTANCES}, Batch Size: {REAL_DELAY_BATCH_SIZE}")

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
                port_offset = (batch_index * REAL_DELAY_BATCH_SIZE) % 20000
                batch_start_port = START_PORT + port_offset

                # Reduced stagger
                await asyncio.sleep(0.1)

                results = await recursive_test_batch(batch, batch_start_port, session, failure_reasons, batch_index, depth=0)
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

def update_readme(tcp_passed_count, real_delay_passed_count, country_stats):
    """Updates README.md with the latest statistics."""
    if not os.path.exists("README.md"):
        return

    try:
        with open("README.md", "r", encoding="utf-8") as f:
            content = f.read()

        # Generate Stats Section
        now = datetime.datetime.utcnow().strftime("%Y-%m-%d %H:%M:%S UTC")

        # Calculate System Health
        success_rate = (real_delay_passed_count / tcp_passed_count * 100) if tcp_passed_count > 0 else 0

        if success_rate >= 50:
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
| **Success Rate** | `{success_rate:.1f}%` |
| **System Health** | {health} |

### 🌍 Server Distribution

| Country | Count |
| :--- | :--- |
"""
        # Sort by count desc
        sorted_stats = sorted(country_stats.items(), key=lambda item: item[1], reverse=True)
        for country, count in sorted_stats:
            flag = v2ray_utils.get_country_flag(country)
            stats_md += f"| {flag} {country} | {count} |\n"

        # Regex replace or append
        # We look for a marker or just replace the section if we can find it.
        # Ideally, we put this inside a specific block in README.
        # For now, let's append it to the top or replace an existing "Statistics" section.

        # Simple approach: Replace the whole Statistics section if it exists, or append after Architecture.
        # But doing regex replacement on markdown is tricky.
        # Let's just create a header "## 📊 Statistics" and replace everything until next header?

        pattern = r"## 📊 Statistics.*?(?=## |\Z)"
        import re
        if re.search(pattern, content, re.DOTALL):
            new_content = re.sub(pattern, stats_md, content, flags=re.DOTALL)
        else:
            # Insert after title
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

async def main():
    # Optimize environment
    v2ray_utils.increase_file_limit()
    v2ray_utils.check_and_download_geoip_db() # Ensure DB for stats

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

    # 3. Cleanup
    for f in glob.glob("crashed_batch_*.json"):
        try:
            os.remove(f)
        except:
            pass

    # 4. Generate Stats
    country_stats = Counter()
    for config in real_delay_passed:
        # Extract country code from ps "[🇩🇪 DE] ..."
        parsed, _ = v2ray_utils.parse_config_line(config)
        if parsed:
            ps = parsed.get('ps', '')
            # Regex to find [XX] or [Flag XX]
            match = re.search(r'\[.*? ([A-Z]{2})\]', ps)
            if match:
                country_stats[match.group(1)] += 1
            else:
                country_stats['Unknown'] += 1

    update_readme(len(tcp_passed), len(real_delay_passed), country_stats)

    print("🎉 All tests finished.")

if __name__ == "__main__":
    if sys.platform == 'win32':
        asyncio.set_event_loop_policy(asyncio.WindowsSelectorEventLoopPolicy())
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        print("\n⚠️ Interrupted.")
