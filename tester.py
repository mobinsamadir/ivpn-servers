import asyncio
import os
import sys
import v2ray_utils
import random
from datetime import datetime

# Configuration
TCP_CONCURRENCY = int(os.environ.get('TCP_CONCURRENCY', 500))
REAL_DELAY_CONCURRENCY = int(os.environ.get('REAL_DELAY_CONCURRENCY', 50))
TCP_TIMEOUT = float(os.environ.get('TCP_TIMEOUT', 3.0))
REAL_DELAY_TIMEOUT = float(os.environ.get('REAL_DELAY_TIMEOUT', 5.0))
TEST_URL = os.environ.get('TEST_URL', 'http://cp.cloudflare.com/generate_204')

INPUT_FILE = 'all_configs.txt'
TCP_OUTPUT_FILE = 'tcp_passed.txt'
REAL_DELAY_OUTPUT_FILE = 'real_delay_passed.txt'

# Port range for local testing
START_PORT = 10000

async def check_tcp_worker(config_queue, results, semaphore):
    while True:
        try:
            config_line = config_queue.get_nowait()
        except asyncio.QueueEmpty:
            return

        parsed = v2ray_utils.parse_config_line(config_line)
        if parsed:
            host = parsed.get('add')
            port = parsed.get('port')
            if host and port:
                try:
                    async with semaphore:
                        success = await v2ray_utils.test_tcp_connection(host, port, TCP_TIMEOUT)
                    if success:
                        results.append(config_line)
                except Exception:
                    pass
        config_queue.task_done()

async def check_real_delay_worker(config_queue, results, ports_queue):
    while True:
        try:
            config_line = config_queue.get_nowait()
        except asyncio.QueueEmpty:
            return

        local_port = await ports_queue.get()
        try:
            delay, error = await v2ray_utils.test_real_delay(config_line, local_port, REAL_DELAY_TIMEOUT, TEST_URL)
            if delay is not None:
                # print(f"✅ Delay {delay:.0f}ms")
                results.append(config_line)
        except Exception:
            pass
        finally:
            await ports_queue.put(local_port)
            config_queue.task_done()

async def run_tcp_tests(configs):
    print(f"🚀 Starting TCP tests for {len(configs)} configs...")
    queue = asyncio.Queue()
    for c in configs:
        queue.put_nowait(c)

    results = []
    semaphore = asyncio.Semaphore(TCP_CONCURRENCY)

    tasks = []
    # Create workers equal to concurrency or queue size
    num_workers = min(TCP_CONCURRENCY, len(configs))
    for _ in range(num_workers):
        task = asyncio.create_task(check_tcp_worker(queue, results, semaphore))
        tasks.append(task)

    await queue.join()

    # Cancel workers (they return on QueueEmpty anyway but just in case)
    for task in tasks:
        task.cancel()

    print(f"✅ TCP tests complete. {len(results)}/{len(configs)} passed.")
    return results

async def run_real_delay_tests(configs):
    if not configs:
        return []

    print(f"🚀 Starting Real Delay tests for {len(configs)} configs...")

    # Ensure Xray is ready
    if not v2ray_utils.check_and_install_xray():
        print("❌ Xray setup failed. Skipping real delay tests.")
        return []

    queue = asyncio.Queue()
    for c in configs:
        queue.put_nowait(c)

    ports_queue = asyncio.Queue()
    for i in range(REAL_DELAY_CONCURRENCY):
        ports_queue.put_nowait(START_PORT + i)

    results = []
    tasks = []
    num_workers = min(REAL_DELAY_CONCURRENCY, len(configs))

    for _ in range(num_workers):
        task = asyncio.create_task(check_real_delay_worker(queue, results, ports_queue))
        tasks.append(task)

    await queue.join()

    for task in tasks:
        task.cancel()

    print(f"✅ Real Delay tests complete. {len(results)}/{len(configs)} passed.")
    return results

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
