import asyncio
import os
import sys
import v2ray_utils
import aiohttp
from itertools import count

# Configuration
TCP_CONCURRENCY = int(os.environ.get('TCP_CONCURRENCY', 800))
REAL_DELAY_CONCURRENCY = int(os.environ.get('REAL_DELAY_CONCURRENCY', 150))
TCP_TIMEOUT = float(os.environ.get('TCP_TIMEOUT', 3.0))
REAL_DELAY_TIMEOUT = float(os.environ.get('REAL_DELAY_TIMEOUT', 5.0))
TEST_URL = os.environ.get('TEST_URL', 'http://cp.cloudflare.com/generate_204')

INPUT_FILE = 'all_configs.txt'
TCP_OUTPUT_FILE = 'tcp_passed.txt'
REAL_DELAY_OUTPUT_FILE = 'real_delay_passed.txt'

# Port range for local testing
START_PORT = 10000

class ProgressCounter:
    def __init__(self, total, name):
        self.total = total
        self.name = name
        self.current = 0
        self.lock = asyncio.Lock()

    async def increment(self):
        async with self.lock:
            self.current += 1
            if self.current % 500 == 0 or self.current == self.total:
                print(f"[{self.name}] Progress: {self.current}/{self.total}...")

async def check_tcp_task(sem, config_line, counter):
    parsed = v2ray_utils.parse_config_line(config_line)
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
            success = await v2ray_utils.test_tcp_connection(host, port, TCP_TIMEOUT)
            await counter.increment()
            if success:
                return config_line
    except Exception:
        await counter.increment()
        return None
    return None

async def check_real_delay_task(config_line, ports_queue, session, counter):
    # Acquire a port (acts as semaphore)
    local_port = await ports_queue.get()
    try:
        delay, error = await v2ray_utils.test_real_delay(config_line, local_port, REAL_DELAY_TIMEOUT, TEST_URL, session)
        await counter.increment()
        if delay is not None:
            return config_line
    except Exception:
        await counter.increment()
    finally:
        ports_queue.put_nowait(local_port)
    return None

async def run_tcp_tests(configs):
    total = len(configs)
    print(f"🚀 Starting TCP tests for {total} configs with concurrency {TCP_CONCURRENCY}...")

    sem = asyncio.Semaphore(TCP_CONCURRENCY)
    counter = ProgressCounter(total, "TCP Test")

    tasks = [check_tcp_task(sem, c, counter) for c in configs]
    results = await asyncio.gather(*tasks)

    # Filter None
    passed = [r for r in results if r is not None]
    print(f"✅ TCP tests complete. {len(passed)}/{total} passed.")
    return passed

async def run_real_delay_tests(configs):
    total = len(configs)
    if total == 0:
        return []

    print(f"🚀 Starting Real Delay tests for {total} configs with concurrency {REAL_DELAY_CONCURRENCY}...")

    # Ensure Xray is ready
    if not v2ray_utils.check_and_install_xray():
        print("❌ Xray setup failed. Skipping real delay tests.")
        return []

    # Create ports queue
    ports_queue = asyncio.Queue()
    for i in range(REAL_DELAY_CONCURRENCY):
        ports_queue.put_nowait(START_PORT + i)

    counter = ProgressCounter(total, "Real Delay Test")

    # Shared session
    async with aiohttp.ClientSession() as session:
        tasks = [check_real_delay_task(c, ports_queue, session, counter) for c in configs]
        results = await asyncio.gather(*tasks)

    passed = [r for r in results if r is not None]
    print(f"✅ Real Delay tests complete. {len(passed)}/{total} passed.")
    return passed

async def main():
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
