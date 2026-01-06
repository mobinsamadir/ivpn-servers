import requests
import base64
import os

# تنظیمات
SOURCES_FILE = 'sources.txt'
OUTPUT_FILE = 'live_servers.txt'  # نام جدید فایل

def decode_base64(data):
    try:
        missing_padding = len(data) % 4
        if missing_padding:
            data += '=' * (4 - missing_padding)
        return base64.b64decode(data).decode('utf-8')
    except:
        return data

def collect_configs():
    unique_configs = set()
    print("🚀 Starting Collection...")

    if not os.path.exists(SOURCES_FILE):
        # ساخت فایل نمونه اگر نباشد
        with open(SOURCES_FILE, 'w') as f: f.write("")
        print(f"⚠️ {SOURCES_FILE} created empty.")

    with open(SOURCES_FILE, 'r') as f:
        urls = [line.strip() for line in f if line.strip() and not line.startswith('#')]

    for url in urls:
        try:
            print(f"📥 Fetching: {url}")
            response = requests.get(url, timeout=15)
            if response.status_code == 200:
                content = response.text.strip()
                if "vmess://" not in content and "vless://" not in content:
                    content = decode_base64(content)
                
                for line in content.splitlines():
                    line = line.strip()
                    if line.startswith(('vmess://', 'vless://', 'trojan://', 'ss://')):
                        unique_configs.add(line)
        except Exception as e:
            print(f"❌ Error: {e}")

    # همیشه فایل را بساز، حتی اگر خالی باشد یا تکراری
    with open(OUTPUT_FILE, 'w', encoding='utf-8') as f:
        if unique_configs:
            for config in unique_configs:
                f.write(config + '\n')
            print(f"✅ Saved {len(unique_configs)} configs to {OUTPUT_FILE}")
        else:
            f.write("") # ساخت فایل خالی
            print("⚠️ No configs found, created empty file.")

if __name__ == "__main__":
    collect_configs()
