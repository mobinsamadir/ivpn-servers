import requests
import os
import re
import v2ray_utils
import asyncio
import aiodns
import socket
from requests.adapters import HTTPAdapter
from urllib3.util.retry import Retry

SOURCES_FILE = 'sources.txt'
OUTPUT_FILE = 'all_configs.txt'
TIMEOUT = 15
USER_AGENT = 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36'

def get_session():
    session = requests.Session()
    retry = Retry(connect=3, backoff_factor=0.5)
    adapter = HTTPAdapter(max_retries=retry)
    session.mount('http://', adapter)
    session.mount('https://', adapter)
    session.headers.update({'User-Agent': USER_AGENT})
    return session

async def resolve_hosts(hosts):
    """
    Resolves a list of hosts to IPs using aiodns.
    Returns a dict {host: ip}.
    """
    resolver = aiodns.DNSResolver()
    results = {}

    async def query(host):
        try:
            # Check if it's already an IP (IPv4)
            try:
                socket.inet_aton(host)
                return host, host
            except OSError:
                pass

            # Check if it's already an IP (IPv6)
            if ':' in host:
                try:
                    socket.inet_pton(socket.AF_INET6, host)
                    return host, host
                except OSError:
                    pass

            # Resolve Domain (A record only for now, as GeoIP is mainly IPv4 focused for this use case)
            # aiodns 3.1+ uses query(host, type)
            res = await resolver.query(host, 'A')
            if res:
                return host, res[0].host
        except:
            return host, None
        return host, None

    # Limit concurrency
    sem = asyncio.Semaphore(100)
    async def safe_query(host):
        async with sem:
            return await query(host)

    tasks = [safe_query(h) for h in hosts]
    resolved = await asyncio.gather(*tasks)

    for host, ip in resolved:
        if ip:
            results[host] = ip
    return results

def collect_configs():
    unique_configs = {} # Map hash -> parsed_config
    session = get_session()

    total_fetched = 0

    print("🚀 Starting Aggregator...")

    # Ensure GeoIP DB is ready
    v2ray_utils.check_and_download_geoip_db()

    if not os.path.exists(SOURCES_FILE):
        print(f"⚠️ {SOURCES_FILE} not found.")
        return

    from collections import Counter
    error_counter = Counter()

    with open(SOURCES_FILE, 'r') as f:
        urls = [line.strip() for line in f if line.strip() and not line.startswith('#')]

    for url in urls:
        try:
            # print(f"📥 Fetching: {url}")
            response = session.get(url, timeout=TIMEOUT)

            extracted_count = 0

            if response.status_code == 200:
                content = response.text.strip()

                # Try decoding if it looks like base64 (no protocol prefixes)
                if not any(proto in content for proto in ["vmess://", "vless://", "trojan://", "ss://", "hysteria2://"]):
                    decoded = v2ray_utils.safe_decode(content)
                    if decoded:
                        content = decoded

                lines = content.splitlines()
                for line in lines:
                    line = line.strip()
                    # Basic cleanup
                    line = re.sub(r'[\x00-\x1f\x7f-\x9f]', '', line)

                    if not line:
                        continue

                    parsed, error = v2ray_utils.parse_config_line(line)
                    if parsed:
                        extracted_count += 1
                        total_fetched += 1
                        config_hash = v2ray_utils.get_config_hash(parsed)
                        if config_hash not in unique_configs:
                            unique_configs[config_hash] = parsed
                    elif error:
                        error_counter[error] += 1

                print(f"[{url}] -> {extracted_count} configs extracted")

            else:
                print(f"[{url}] -> Failed: {response.status_code}")

        except Exception as e:
            print(f"[{url}] -> Error: {str(e)[:100]}")

    final_unique = len(unique_configs)
    duplicates_removed = total_fetched - final_unique

    print("-" * 50)
    print(f"Total fetched: {total_fetched} | Duplicates removed: {duplicates_removed} | Final unique configs: {final_unique}")
    print("-" * 50)

    # Parsing Failure Summary
    if error_counter:
        print("\n⚠️ Parsing Failure Summary:")
        for err, count in error_counter.most_common():
             print(f"  - {err}: {count}")
        print("-" * 50)

    # --- GeoIP Tagging ---
    print("🌍 Performing GeoIP Tagging...")
    unique_hosts = set()
    for parsed in unique_configs.values():
        if parsed.get('add'):
            unique_hosts.add(parsed['add'])

    # Run async resolution
    loop = asyncio.new_event_loop()
    asyncio.set_event_loop(loop)
    host_map = loop.run_until_complete(resolve_hosts(list(unique_hosts)))
    loop.close()

    tagged_configs = []
    for parsed in unique_configs.values():
        add = parsed.get('add')
        ip = host_map.get(add)

        country_code = None
        if ip:
            country_code = v2ray_utils.get_country_code(ip)

        flag = v2ray_utils.get_country_flag(country_code)
        cc_str = country_code if country_code else "Unknown"

        original_ps = parsed.get('ps', '')
        # Prepend flag
        new_ps = f"[{flag} {cc_str}] {original_ps}"
        parsed['ps'] = new_ps

        # Reconstruct
        new_line = v2ray_utils.construct_config_line(parsed)
        if new_line:
            tagged_configs.append(new_line)

    # Write output
    print(f"Writing {len(tagged_configs)} tagged configs to {OUTPUT_FILE}...")
    with open(OUTPUT_FILE, 'w', encoding='utf-8') as f:
        for config in tagged_configs:
            f.write(config + '\n')

    print(f"✅ Aggregation complete.")

if __name__ == "__main__":
    collect_configs()
