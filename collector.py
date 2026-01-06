import requests
import base64
import os
import re
from requests.adapters import HTTPAdapter
from urllib3.util.retry import Retry

# --- تنظیمات ---
SOURCES_FILE = 'sources.txt'
OUTPUT_FILE = 'live_servers.txt'
TIMEOUT = 15
USER_AGENT = 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36'

def get_session():
    """ایجاد نشست با قابلیت تلاش مجدد برای جلوگیری از قطعی‌های لحظه‌ای"""
    session = requests.Session()
    retry = Retry(connect=3, backoff_factor=0.5)
    adapter = HTTPAdapter(max_retries=retry)
    session.mount('http://', adapter)
    session.mount('https://', adapter)
    session.headers.update({'User-Agent': USER_AGENT})
    return session

def safe_decode(data):
    """دکود قدرتمند برای انواع فرمت‌های Base64 (استاندارد و URL-Safe)"""
    data = data.strip()
    # تبدیل کاراکترهای URL-Safe به استاندارد
    data = data.replace('-', '+').replace('_', '/')
    
    # اصلاح پدینگ (Padding)
    missing_padding = len(data) % 4
    if missing_padding:
        data += '=' * (4 - missing_padding)
        
    try:
        return base64.b64decode(data).decode('utf-8')
    except Exception:
        # اگر دکود نشد، شاید اصلا بیس۶۴ نیست، خود متن را برگردان
        return data

def collect_configs():
    unique_configs = set()
    session = get_session()
    
    print("🚀 Starting Advanced Collection...")

    if not os.path.exists(SOURCES_FILE):
        with open(SOURCES_FILE, 'w') as f: f.write("")
        print("⚠️ Sources file created.")
        return

    with open(SOURCES_FILE, 'r') as f:
        urls = [line.strip() for line in f if line.strip() and not line.startswith('#')]

    for url in urls:
        try:
            print(f"📥 Fetching: {url}")
            response = session.get(url, timeout=TIMEOUT)
            
            if response.status_code == 200:
                content = response.text.strip()
                
                # تشخیص هوشمند محتوای Base64
                # اگر در متن vmess/vless دیده نشد، احتمالا کد شده است
                if not any(proto in content for proto in ["vmess://", "vless://", "trojan://", "ss://", "hysteria2://"]):
                    content = safe_decode(content)
                
                for line in content.splitlines():
                    line = line.strip()
                    # حذف کاراکترهای غیرقابل چاپ و فاصله‌های عجیب
                    line = re.sub(r'[\x00-\x1f\x7f-\x9f]', '', line)
                    
                    if line.startswith(('vmess://', 'vless://', 'trojan://', 'ss://', 'hysteria2://')):
                        unique_configs.add(line)
            else:
                print(f"⚠️ Failed: {response.status_code}")
                
        except Exception as e:
            print(f"❌ Error: {str(e)[:100]}...") # نمایش خلاصه خطا

    # ذخیره فایل
    with open(OUTPUT_FILE, 'w', encoding='utf-8') as f:
        if unique_configs:
            # مرتب‌سازی برای زیبایی و نظم فایل
            sorted_configs = sorted(list(unique_configs))
            for config in sorted_configs:
                f.write(config + '\n')
            print(f"✅ Success! Saved {len(unique_configs)} unique configs.")
        else:
            f.write("")
            print("⚠️ No configs found.")

if __name__ == "__main__":
    collect_configs()
