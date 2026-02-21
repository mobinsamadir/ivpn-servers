import os
import sys
import json
import asyncio
import v2ray_utils
from datetime import datetime

# Configuration
REAL_DELAY_CONCURRENCY = int(os.environ.get('REAL_DELAY_CONCURRENCY', 50))
REAL_DELAY_TIMEOUT = float(os.environ.get('REAL_DELAY_TIMEOUT', 5.0))
TEST_URL = os.environ.get('TEST_URL', 'http://cp.cloudflare.com/generate_204')
INPUT_FILE = 'real_delay_passed.txt'

START_PORT = 20000

async def worker_local_test(config_queue, results, detailed_results, ports_queue):
    while True:
        try:
            config_line = config_queue.get_nowait()
        except asyncio.QueueEmpty:
            return

        local_port = await ports_queue.get()
        try:
            delay, error = await v2ray_utils.test_real_delay(config_line, local_port, REAL_DELAY_TIMEOUT, TEST_URL)

            result_entry = {
                "config": config_line,
                "delay_ms": delay,
                "error": error
            }
            detailed_results.append(result_entry)

            if delay is not None:
                print(f"✅ Delay {delay:.0f}ms")
                results.append(config_line)
            else:
                pass
                # print(f"❌ Error: {error}")
        except Exception as e:
            detailed_results.append({
                "config": config_line,
                "delay_ms": None,
                "error": str(e)
            })
        finally:
            await ports_queue.put(local_port)
            config_queue.task_done()

async def main():
    # Setup Output Directory
    timestamp = datetime.now().strftime("%Y-%m-%d_%H-%M-%S")
    output_dir = os.path.join("local_results", timestamp)
    os.makedirs(output_dir, exist_ok=True)

    # Redirect stdout/stderr to test.log
    log_file = os.path.join(output_dir, "test.log")

    original_stdout = sys.stdout
    original_stderr = sys.stderr
    log_f = open(log_file, 'w', encoding='utf-8')

    class Tee:
        def __init__(self, original_stream):
            self.original_stream = original_stream

        def write(self, message):
            self.original_stream.write(message)
            log_f.write(message)
            # Flush often to keep log updated
            log_f.flush()

        def flush(self):
            self.original_stream.flush()
            log_f.flush()

    sys.stdout = Tee(original_stdout)
    sys.stderr = Tee(original_stderr)

    print(f"📂 Output directory: {output_dir}")

    if not os.path.exists(INPUT_FILE):
        print(f"❌ Error: {INPUT_FILE} not found. Please run the aggregator/tester first or ensure the file exists.")
        return

    # Check Xray
    if not v2ray_utils.check_and_install_xray():
        print("❌ Xray setup failed.")
        return

    with open(INPUT_FILE, 'r', encoding='utf-8') as f:
        configs = [line.strip() for line in f if line.strip()]

    print(f"🚀 Starting Local Test for {len(configs)} configs...")

    queue = asyncio.Queue()
    for c in configs:
        queue.put_nowait(c)

    ports_queue = asyncio.Queue()
    for i in range(REAL_DELAY_CONCURRENCY):
        ports_queue.put_nowait(START_PORT + i)

    results = []
    detailed_results = []
    tasks = []
    num_workers = min(REAL_DELAY_CONCURRENCY, len(configs))

    for _ in range(num_workers):
        task = asyncio.create_task(worker_local_test(queue, results, detailed_results, ports_queue))
        tasks.append(task)

    await queue.join()

    for task in tasks:
        task.cancel()

    # Save Results
    with open(os.path.join(output_dir, "real_delay_passed.txt"), 'w', encoding='utf-8') as f:
        for c in results:
            f.write(c + '\n')

    with open(os.path.join(output_dir, "detailed_results.json"), 'w', encoding='utf-8') as f:
        json.dump(detailed_results, f, indent=2)

    print(f"✅ Local Test Complete. {len(results)}/{len(configs)} passed.")
    print(f"📄 Results saved to {output_dir}")

    # Restore stdout/stderr (good practice, though script ends here)
    sys.stdout = original_stdout
    sys.stderr = original_stderr
    log_f.close()

if __name__ == "__main__":
    if sys.platform == 'win32':
        asyncio.set_event_loop_policy(asyncio.WindowsSelectorEventLoopPolicy())
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        print("\n⚠️ Interrupted.")
