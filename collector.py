import requests
import base64
import os

# تنظیمات
SOURCES_FILE = 'sources.txt'
OUTPUT_FILE = 'servers.txt'

def decode_base64(data):
    """تلاش برای دیکد کردن محتوای بیس۶۴"""
    try:
        # اضافه کردن پدینگ در صورت نیاز
        missing_padding = len(data) % 4
        if missing_padding:
            data += '=' * (4 - missing_padding)
        return base64.b64decode(data).decode('utf-8')
    except:
        return data

def collect_configs():
    unique_configs = set()
    print("🚀 Starting Config Collection...")

    if not os.path.exists(SOURCES_FILE):
        print(f"❌ {SOURCES_FILE} not found!")
        return

    with open(SOURCES_FILE, 'r') as f:
        urls = [line.strip() for line in f if line.strip() and not line.startswith('#')]

    for url in urls:
        try:
            print(f"📥 Fetching: {url}")
            response = requests.get(url, timeout=15)
            if response.status_code == 200:
                content = response.text.strip()
                
                # تشخیص اینکه آیا کل فایل بیس۶۴ است یا خیر
                if "vmess://" not in content and "vless://" not in content and "ss://" not in content:
                    decoded_content = decode_base64(content)
                else:
                    decoded_content = content

                # پردازش خط به خط
                for line in decoded_content.splitlines():
                    line = line.strip()
                    if not line: continue
                    
                    # فیلتر کردن پروتکل‌های معتبر
                    if line.startswith(('vmess://', 'vless://', 'trojan://', 'ss://', 'hysteria2://')):
                        unique_configs.add(line)
            else:
                print(f"⚠️ Failed to fetch {url}: Status {response.status_code}")
        except Exception as e:
            print(f"❌ Error processing {url}: {e}")

    # ذخیره نتیجه
    if unique_configs:
        print(f"✅ Found {len(unique_configs)} unique configs.")
        with open(OUTPUT_FILE, 'w', encoding='utf-8') as f:
            for config in unique_configs:
                f.write(config + '\n')
        print(f"💾 Saved to {OUTPUT_FILE}")
    else:
        print("⚠️ No configs found!")

if __name__ == "__main__":
    collect_configs()
