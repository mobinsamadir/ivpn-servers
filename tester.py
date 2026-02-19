import asyncio
import aiohttp
import json
import os
import sys
import subprocess
import socket
import time
import random
import uvloop
from typing import List, Optional, Tuple

# Import parsing logic from aggregator
try:
    from aggregator import parse_config_line, XRAY_BIN
except ImportError:
    # Fallback if aggregator not in path or renamed
    sys.path.append('.')
    from aggregator import parse_config_line, XRAY_BIN

# Install uvloop
asyncio.set_event_loop_policy(uvloop.EventLoopPolicy())

# Constants
TCP_TIMEOUT = 2.0 # seconds
REAL_DELAY_TIMEOUT = 5.0 # seconds
TCP_CONCURRENCY = 1000
REAL_DELAY_CONCURRENCY = 50
TEST_URL = "http://cp.cloudflare.com/generate_204"
ALL_CONFIGS_FILE = "all_configs.txt"
TCP_PASSED_FILE = "tcp_passed.txt"
REAL_DELAY_PASSED_FILE = "real_delay_passed.txt"

async def test_tcp_connection(config: str, semaphore: asyncio.Semaphore) -> Tuple[bool, str]:
    """Tests TCP connectivity to the server address and port."""
    details = parse_config_line(config)
    if not details:
        return False, config

    address = details.get("add")
    port = details.get("port")

    if not address or not port:
        return False, config

    async with semaphore:
        try:
            # Validate port is integer
            port = int(port)
            start_time = time.time()
            reader, writer = await asyncio.wait_for(
                asyncio.open_connection(address, port),
                timeout=TCP_TIMEOUT
            )
            writer.close()
            await writer.wait_closed()
            return True, config
        except Exception:
            return False, config

def generate_xray_config(details: dict, local_port: int) -> dict:
    """Generates a minimal Xray config for local testing."""
    proto = details.get("protocol")
    outbound = {
        "protocol": proto,
        "settings": {},
        "streamSettings": {
            "network": details.get("net", "tcp"),
            "security": details.get("tls", "none") or "none",
            "wsSettings": {},
            "tcpSettings": {},
            "tlsSettings": {
                "serverName": details.get("sni", "") or details.get("host", ""),
                "allowInsecure": True
            },
             "grpcSettings": {
                "serviceName": details.get("path", "")
            }
        }
    }

    # Stream Settings Refinement
    if details.get("net") == "ws":
        outbound["streamSettings"]["wsSettings"] = {
            "path": details.get("path", "/"),
            "headers": {
                "Host": details.get("host", "") or details.get("sni", "")
            }
        }
    elif details.get("net") == "tcp":
        outbound["streamSettings"]["tcpSettings"] = {
            "header": {
                "type": details.get("type", "none")
            }
        }
    elif details.get("net") == "grpc":
         outbound["streamSettings"]["grpcSettings"] = {
            "serviceName": details.get("path", "")
         }

    # Protocol Specific Settings
    if proto == "vmess":
        outbound["settings"] = {
            "vnext": [{
                "address": details.get("add"),
                "port": int(details.get("port")),
                "users": [{
                    "id": details.get("id"),
                    "alterId": 0,
                    "security": details.get("scy", "auto")
                }]
            }]
        }
    elif proto == "vless":
        outbound["settings"] = {
            "vnext": [{
                "address": details.get("add"),
                "port": int(details.get("port")),
                "users": [{
                    "id": details.get("id"),
                    "encryption": "none"
                }]
            }]
        }
    elif proto == "trojan":
        outbound["settings"] = {
            "servers": [{
                "address": details.get("add"),
                "port": int(details.get("port")),
                "password": details.get("id")
            }]
        }
    elif proto == "shadowsocks":
        # Check if using simplified SS or full SS
        # Xray uses protocol "shadowsocks"
        # but config requires "servers" list
        outbound["protocol"] = "shadowsocks"
        outbound["settings"] = {
            "servers": [{
                "address": details.get("add"),
                "port": int(details.get("port")),
                "method": details.get("method", "aes-256-gcm"), # Default fallback
                "password": details.get("id")
            }]
        }

    return {
        "log": {"loglevel": "none"},
        "inbounds": [{
            "port": local_port,
            "protocol": "http", # Use HTTP protocol for aiohttp compatibility
            "settings": {"auth": "noauth", "udp": True},
            "sniffing": {"enabled": True, "destOverride": ["http", "tls"]}
        }],
        "outbounds": [outbound]
    }

async def test_real_delay(config: str, semaphore: asyncio.Semaphore, port_pool: asyncio.Queue) -> Tuple[float, str]:
    """Tests real HTTP latency via Xray."""
    details = parse_config_line(config)
    if not details: return -1, config

    # Get a port from the pool
    local_port = await port_pool.get()

    config_json = generate_xray_config(details, local_port)
    config_file = f"config_{local_port}_{random.randint(1000,9999)}.json"

    async with semaphore:
        process = None
        try:
            with open(config_file, 'w') as f:
                json.dump(config_json, f)

            # Start Xray
            # We assume XRAY_BIN is in current dir or path
            if not os.path.exists(XRAY_BIN):
                 # Fallback to system path
                 xray_cmd = "xray"
            else:
                 xray_cmd = f"./{XRAY_BIN}"

            process = await asyncio.create_subprocess_exec(
                xray_cmd, "-c", config_file,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE
            )

            # Wait a bit for Xray to start
            await asyncio.sleep(1.0)

            # Check connection
            proxy_url = f"http://127.0.0.1:{local_port}"
            start_time = time.time()

            async with aiohttp.ClientSession() as session:
                try:
                    async with session.get(
                        TEST_URL,
                        proxy=proxy_url,
                        timeout=REAL_DELAY_TIMEOUT
                    ) as resp:
                        if resp.status == 204 or resp.status == 200:
                            delay = (time.time() - start_time) * 1000 # ms
                        else:
                            print(f"⚠️ Status {resp.status} for {config[:30]}...")
                            delay = -1
                except Exception as e:
                    print(f"❌ HTTP Error for {config[:30]}...: {repr(e)}")
                    delay = -1

            # Cleanup
            if process:
                try:
                    process.terminate()
                    await process.wait()
                except Exception:
                    try:
                        process.kill()
                    except:
                        pass

            return delay, config

        except Exception as e:
            # print(f"Error testing {config[:20]}...: {e}")
            return -1, config
        finally:
            # Return port to pool
            await port_pool.put(local_port)
            if os.path.exists(config_file):
                os.remove(config_file)

async def main():
    if not os.path.exists(ALL_CONFIGS_FILE):
        print(f"❌ {ALL_CONFIGS_FILE} not found. Run aggregator.py first.")
        return

    print("🚀 Starting Tester Engine...")

    # Read configs
    with open(ALL_CONFIGS_FILE, 'r') as f:
        configs = [line.strip() for line in f if line.strip()]

    print(f"📋 Loaded {len(configs)} configs.")

    # Stage 1: TCP Test
    print("📡 Stage 1: Mass TCP Testing...")
    tcp_sem = asyncio.Semaphore(TCP_CONCURRENCY)
    tasks = [test_tcp_connection(c, tcp_sem) for c in configs]

    tcp_passed = []
    # Use tqdm or simple progress? Simple progress to avoid extra deps if possible
    # But for 1000s of configs, simple print is spammy.
    # We'll just wait for gather.
    results = await asyncio.gather(*tasks)

    for success, config in results:
        if success:
            tcp_passed.append(config)

    print(f"✅ TCP Passed: {len(tcp_passed)}/{len(configs)}")

    with open(TCP_PASSED_FILE, 'w') as f:
        for c in tcp_passed:
            f.write(c + '\n')

    if not tcp_passed:
        print("⚠️ No configs passed TCP test. Exiting.")
        return

    # Stage 2: Real Delay Test
    print("⚡ Stage 2: Real Delay Testing...")

    # Initialize Port Pool
    port_pool = asyncio.Queue()
    start_port = 20000
    for i in range(REAL_DELAY_CONCURRENCY):
        port_pool.put_nowait(start_port + i)

    delay_sem = asyncio.Semaphore(REAL_DELAY_CONCURRENCY)

    # We only test TCP passed configs
    tasks = [test_real_delay(c, delay_sem, port_pool) for c in tcp_passed]
    results = await asyncio.gather(*tasks)

    real_passed = []
    for delay, config in results:
        if delay > 0:
            real_passed.append((delay, config))

    # Sort by delay
    real_passed.sort(key=lambda x: x[0])

    print(f"✅ Real Delay Passed: {len(real_passed)}/{len(tcp_passed)}")

    with open(REAL_DELAY_PASSED_FILE, 'w') as f:
        for delay, config in real_passed:
            # Maybe save delay in comment? Or just raw config?
            # User said "Output the deduplicated raw configs... output the requested files".
            # Usually raw config is preferred.
            f.write(config + '\n')

    print("🎉 Testing Complete.")

if __name__ == "__main__":
    asyncio.run(main())
