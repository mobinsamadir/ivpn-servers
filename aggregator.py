import asyncio
import aiohttp
import os
import sys
import zipfile
import stat
import json
import base64
import re
import hashlib
import urllib.parse
from typing import Set, List, Optional

# Constants
XRAY_REPO = "XTLS/Xray-core"
XRAY_BIN = "xray"
SOURCES_FILE = "sources.txt"
OUTPUT_FILE = "all_configs.txt"
LEGACY_FILES = ["live_servers.txt", "servers.txt"]

def safe_base64_decode(s: str) -> str:
    """Helper to decode base64 strings with padding handling."""
    s = s.strip()
    # Url safe replacements
    s = s.replace('-', '+').replace('_', '/')
    padding = len(s) % 4
    if padding:
        s += '=' * (4 - padding)
    try:
        return base64.b64decode(s).decode('utf-8', errors='ignore')
    except Exception as e:
        # print(f"Decode error for {s}: {e}")
        return ""

async def check_and_install_xray():
    """Checks if Xray-core is present; if not, downloads and installs it."""
    if os.path.exists(XRAY_BIN) and os.access(XRAY_BIN, os.X_OK):
        print(f"✅ {XRAY_BIN} is already installed.")
        return

    print("⬇️ Xray-core not found. Fetching latest release...")
    async with aiohttp.ClientSession() as session:
        try:
            async with session.get(f"https://api.github.com/repos/{XRAY_REPO}/releases/latest") as resp:
                if resp.status != 200:
                    print(f"❌ Failed to fetch release info: {resp.status}")
                    return
                release_data = await resp.json()

            assets = release_data.get("assets", [])
            download_url = None
            for asset in assets:
                if asset["name"].endswith("linux-64.zip"):
                    download_url = asset["browser_download_url"]
                    break

            if not download_url:
                print("❌ Could not find linux-64.zip asset.")
                return

            print(f"📥 Downloading {download_url}...")
            async with session.get(download_url) as resp:
                if resp.status != 200:
                    print(f"❌ Failed to download binary: {resp.status}")
                    return
                content = await resp.read()

            with open("xray.zip", "wb") as f:
                f.write(content)

            print("📦 Extracting xray.zip...")
            with zipfile.ZipFile("xray.zip", "r") as zip_ref:
                zip_ref.extractall(".")

            if os.path.exists(XRAY_BIN):
                st = os.stat(XRAY_BIN)
                os.chmod(XRAY_BIN, st.st_mode | stat.S_IEXEC)
                print(f"✅ {XRAY_BIN} installed and executable.")
            else:
                print(f"❌ {XRAY_BIN} not found after extraction.")

            # Cleanup
            if os.path.exists("xray.zip"):
                os.remove("xray.zip")

        except Exception as e:
            print(f"❌ Error installing Xray: {e}")

async def fetch_url(session: aiohttp.ClientSession, url: str) -> str:
    """Fetches content from a URL."""
    try:
        async with session.get(url, timeout=10) as resp:
            if resp.status == 200:
                return await resp.text()
    except Exception as e:
        print(f"⚠️ Failed to fetch {url}: {e}")
    return ""

def parse_vmess(config_str: str) -> Optional[dict]:
    """Parses a vmess config."""
    try:
        # vmess://base64_json
        b64 = config_str[8:]
        json_str = safe_base64_decode(b64)
        if not json_str:
            return None
        data = json.loads(json_str)
        return {
            "protocol": "vmess",
            "add": data.get("add", ""),
            "port": data.get("port", ""),
            "id": data.get("id", ""),
            "net": data.get("net", ""),
            "host": data.get("host", ""),
            "path": data.get("path", ""),
            "tls": data.get("tls", ""),
            "scy": data.get("scy", "auto"),
            "sni": data.get("sni", ""),
            "raw": config_str
        }
    except Exception:
        return None

def parse_vless_trojan(config_str: str, protocol: str) -> Optional[dict]:
    """Parses vless and trojan configs."""
    try:
        # protocol://uuid@host:port?params#name
        # OR protocol://password@host:port?params#name
        # Updated regex to support IPv6 (e.g. [2001:db8::1])
        pattern = r'^(?P<protocol>vless|trojan)://(?P<uuid>[^@]+)@(?P<host>\[[^\]]+\]|[^:]+):(?P<port>\d+)(\?(?P<params>.*))?(#(?P<name>.*))?$'
        match = re.match(pattern, config_str)
        if not match:
            return None

        groups = match.groupdict()
        params = {}
        if groups["params"]:
            params = dict(urllib.parse.parse_qsl(groups["params"]))

        return {
            "protocol": protocol,
            "add": groups["host"],
            "port": groups["port"],
            "id": groups["uuid"], # or password for trojan
            "net": params.get("type", "tcp"), # defaults to tcp
            "host": params.get("host", ""),
            "path": params.get("path", ""),
            "tls": params.get("security", ""),
            "sni": params.get("sni", ""),
            "raw": config_str
        }
    except Exception:
        return None

def parse_ss(config_str: str) -> Optional[dict]:
    """Parses shadowsocks configs."""
    try:
        # ss://base64(method:password)@host:port#name
        # or ss://base64(method:password@host:port)#name
        # This is a simplified parser, SS parsing can be complex due to variants

        # Strip ss://
        rest = config_str[5:]

        # Handle #name
        name = ""
        if '#' in rest:
            rest, name = rest.split('#', 1)

        # Check if user info is base64 encoded separately or whole link
        if '@' in rest:
            # format: base64(method:password)@host:port
            user_info_b64, host_port = rest.split('@', 1)
            user_info = safe_base64_decode(user_info_b64)
            if ':' in user_info:
                method, password = user_info.split(':', 1)
            else:
                return None

            if ':' in host_port:
                host, port = host_port.rsplit(':', 1)
            else:
                return None
        else:
            # format: base64(method:password@host:port)
            decoded = safe_base64_decode(rest)
            if not decoded:
                return None

            # defined as method:password@host:port
            # find last @ for host:port
            if '@' not in decoded:
                return None
            user_info, host_port = decoded.rsplit('@', 1)
            if ':' in user_info:
                method, password = user_info.split(':', 1)
            else:
                return None
            if ':' in host_port:
                host, port = host_port.rsplit(':', 1)
            else:
                return None

        return {
            "protocol": "ss",
            "add": host,
            "port": port,
            "id": password, # Using password as ID for SS
            "net": "tcp", # SS uses TCP/UDP usually
            "host": "",
            "path": "",
            "tls": "",
            "sni": "",
            "method": method,
            "raw": config_str
        }

    except Exception:
        return None

def get_config_hash(details: dict) -> str:
    """Generates a SHA256 hash based on config details."""
    # Protocol + IP + Port + UUID/Password + NetType + SNI + Path
    # For some fields, we fallback to empty string

    # Normalize data
    proto = (details.get("protocol") or "").lower()
    ip = (details.get("add") or "").lower()
    port = str(details.get("port") or "")
    uuid = details.get("id") or ""
    net = (details.get("net") or "").lower()
    sni = (details.get("sni") or "").lower()
    if not sni:
        sni = (details.get("host") or "").lower() # Fallback to host if sni missing
    path = details.get("path") or ""

    fingerprint = f"{proto}|{ip}|{port}|{uuid}|{net}|{sni}|{path}"
    return hashlib.sha256(fingerprint.encode()).hexdigest()

def parse_config_line(line: str) -> Optional[dict]:
    """Parses a single config line and returns details."""
    line = line.strip()
    if line.startswith("vmess://"):
        return parse_vmess(line)
    elif line.startswith("vless://"):
        return parse_vless_trojan(line, "vless")
    elif line.startswith("trojan://"):
        return parse_vless_trojan(line, "trojan")
    elif line.startswith("ss://"):
        return parse_ss(line)
    return None

def process_content(content: str) -> List[str]:
    """Processes fetched content and returns a list of raw config lines."""
    lines = []
    # If content looks like base64, try to decode it
    # We look for common protocol prefixes. If none found, maybe it's a b64 blob
    if not any(p in content for p in ["vmess://", "vless://", "trojan://", "ss://"]):
        decoded = safe_base64_decode(content)
        if decoded:
            content = decoded

    for line in content.splitlines():
        line = line.strip()
        if not line: continue
        if line.startswith(("vmess://", "vless://", "trojan://", "ss://")):
             lines.append(line)
    return lines

async def main():
    # 1. Check/Install Xray
    await check_and_install_xray()

    # 2. Clean legacy files
    for f in LEGACY_FILES:
        if os.path.exists(f):
            try:
                os.remove(f)
                print(f"🗑️ Removed legacy file: {f}")
            except OSError as e:
                print(f"⚠️ Could not remove {f}: {e}")

    # 3. Read Sources
    if not os.path.exists(SOURCES_FILE):
        print(f"❌ {SOURCES_FILE} not found.")
        return

    with open(SOURCES_FILE, 'r') as f:
        urls = [line.strip() for line in f if line.strip() and not line.startswith('#')]

    seen_hashes = set()
    count = 0

    # 4. Fetch and Process
    print("🚀 Starting Aggregation...")
    async with aiohttp.ClientSession() as session:
        # Fetch all URLs concurrently?
        # Or fetch one by one to save memory if sources are huge?
        # User said "aiohttp for concurrent fetching".

        tasks = [fetch_url(session, url) for url in urls]
        results = await asyncio.gather(*tasks)

        with open(OUTPUT_FILE, 'w') as out_f:
            for content in results:
                if not content: continue

                raw_configs = process_content(content)
                for raw in raw_configs:
                    details = None
                    if raw.startswith("vmess://"):
                        details = parse_vmess(raw)
                    elif raw.startswith("vless://"):
                        details = parse_vless_trojan(raw, "vless")
                    elif raw.startswith("trojan://"):
                        details = parse_vless_trojan(raw, "trojan")
                    elif raw.startswith("ss://"):
                        details = parse_ss(raw)

                    if details:
                        h = get_config_hash(details)
                        if h not in seen_hashes:
                            seen_hashes.add(h)
                            out_f.write(raw + "\n")
                            count += 1

    print(f"✅ Aggregation complete. Saved {count} unique configs to {OUTPUT_FILE}.")

if __name__ == "__main__":
    if sys.platform == 'win32':
        asyncio.set_event_loop_policy(asyncio.WindowsSelectorEventLoopPolicy())
    asyncio.run(main())
