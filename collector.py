import requests
import base64
import json
import socket
import re
from urllib.parse import urlparse
from concurrent.futures import ThreadPoolExecutor

# --- تنظیمات ---
SOURCES_FILE = 'sources.txt'
OUTPUT_FILE = 'live_servers.txt'
TIMEOUT = 1.5  # ثانیه (هر سروری کندتر از این باشد حذف می‌شود)
MAX_WORKERS = 50 # تعداد تست همزمان

def decode_base64(data):
    """دکود کردن لینک‌های سابسکریپشن"""
    try:
        missing_padding = len(data) % 4
        if missing_padding:
            data += '=' * (4 - missing_padding)
        return base64.b64decode(data).decode('utf-8')
    except:
        return ""

def parse_config(config):
    """استخراج IP و Port از انواع کانفیگ‌ها"""
    try:
        ip = ""
        port = 0
        
        # 1. VMESS Parsing
        if config.startswith("vmess://"):
            b64_part = config[8:]
            json_str = decode_base64(b64_part)
            if not json_str: return None, None
            data = json.loads(json_str)
            ip = data.get('add')
            port = int(data.get('port'))

        # 2. VLESS / TROJAN / SS Parsing
        elif config.startswith(("vless://", "trojan://", "ss://")):
            parsed = urlparse(config)
            ip = parsed.hostname
            port = parsed.port
        
        # اگر IP یا Port پیدا نشد
        if not ip or not port:
            return None, None
            
        return ip, port
    except:
        return None, None

def check_connection(config):
    """تست اتصال TCP به سرور"""
    ip, port = parse_config(config)
    if not ip or not port:
        return None # فرمت نامعتبر

    try:
        # ایجاد سوکت برای تست اتصال
        sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        sock.settimeout(TIMEOUT)
        
        # زمان‌گیری شروع
        start_time = socket.gettimeofday() if hasattr(socket, 'gettimeofday') else 0
        
        # تلاش برای اتصال
        result = sock.connect_ex((ip, port))
        sock.close()
        
        # اگر اتصال موفق بود (0 یعنی موفقیت)
        if result == 0:
            # اینجا چون دقیق نمی‌تونیم پینگ بگیریم، صرفا اتصال موفق رو ملاک قرار میدیم
            # اما کانفیگ رو برمی‌گردونیم
            return config
    except:
        pass
    
    return None

def collect_and_test():
    raw_configs = set()
    valid_configs = []
    
    print("🚀 Starting Smart Collection...")

    # 1. دانلود و استخراج لینک‌ها
    with open(SOURCES_FILE, 'r') as f:
        urls = [line.strip() for line in f if line.strip() and not line.startswith('#')]

    for url in urls:
        try:
            print(f"📥 Fetching: {url}")
            response = requests.get(url, timeout=10)
            if response.status_code == 200:
                content = response.text.strip()
                if "vmess://" not in content and "vless://" not in content:
                    content = decode_base64(content)
                
                for line in content.splitlines():
                    line = line.strip()
                    if line.startswith(('vmess://', 'vless://', 'trojan://', 'ss://')):
                        raw_configs.add(line)
        except Exception as e:
            print(f"❌ Error fetching source: {e}")

    print(f"⚡ Testing {len(raw_configs)} configs (Timeout: {TIMEOUT}s)...")

    # 2. تست همزمان کانفیگ‌ها (Multi-threading)
    with ThreadPoolExecutor(max_workers=MAX_WORKERS) as executor:
        results = executor.map(check_connection, raw_configs)
    
    # 3. جمع‌آوری نتایج سالم
    for config in results:
        if config:
            valid_configs.append(config)

    print(f"✅ Healthy configs kept: {len(valid_configs)} / {len(raw_configs)}")

    # 4. ذخیره در فایل
    with open(OUTPUT_FILE, 'w', encoding='utf-8') as f:
        for config in valid_configs:
            f.write(config + '\n')
            
    print(f"💾 Saved to {OUTPUT_FILE}")

if __name__ == "__main__":
    collect_and_test()
