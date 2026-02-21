import requests
import os
import re
import v2ray_utils
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

def collect_configs():
    unique_configs = {} # Map hash -> config_line
    session = get_session()

    total_fetched = 0

    print("🚀 Starting Aggregator...")

    if not os.path.exists(SOURCES_FILE):
        print(f"⚠️ {SOURCES_FILE} not found.")
        return

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

                    # Parse just to verify it's valid, but we count everything that *looks* like a config
                    # Actually user said "X configs extracted"
                    # We should probably only count valid ones.
                    parsed = v2ray_utils.parse_config_line(line)
                    if parsed:
                        extracted_count += 1
                        total_fetched += 1
                        config_hash = v2ray_utils.get_config_hash(parsed)
                        if config_hash not in unique_configs:
                            unique_configs[config_hash] = line

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

    # Write output
    print(f"Writing {final_unique} configs to {OUTPUT_FILE}...")
    with open(OUTPUT_FILE, 'w', encoding='utf-8') as f:
        for config in unique_configs.values():
            f.write(config + '\n')

    print(f"✅ Aggregation complete.")

if __name__ == "__main__":
    collect_configs()
