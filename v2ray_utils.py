import os
import sys
import json
import base64
import re
import hashlib
import platform
import subprocess
import asyncio
import aiohttp
import zipfile
import shutil
import stat
import time
import requests
from urllib.parse import urlparse, parse_qs, unquote
from datetime import datetime

# Constants
# Using a stable version. Update this as needed.
XRAY_VERSION = "v1.8.4"
BIN_DIR = "bin"
XRAY_EXECUTABLE = "xray.exe" if platform.system() == "Windows" else "xray"
XRAY_PATH = os.path.join(BIN_DIR, XRAY_EXECUTABLE)

def safe_decode(data):
    """Robust Base64 decoding (standard and URL-safe)."""
    data = data.strip()
    data = data.replace('-', '+').replace('_', '/')
    missing_padding = len(data) % 4
    if missing_padding:
        data += '=' * (4 - missing_padding)
    try:
        return base64.b64decode(data).decode('utf-8')
    except Exception:
        return data

def get_config_hash(config_data):
    """
    Generates a unique hash for a config dict to identify duplicates.
    Fields used: protocol, add (ip), port, id (uuid/password), path, sni, type/net.
    """
    # Create a string representation of key fields
    key_parts = [
        str(config_data.get('protocol') or ''),
        str(config_data.get('add') or ''),
        str(config_data.get('port') or ''),
        str(config_data.get('id') or ''),
        str(config_data.get('net') or ''),
        str(config_data.get('type') or ''),
        str(config_data.get('host') or ''),
        str(config_data.get('path') or ''),
        str(config_data.get('tls') or ''),
        str(config_data.get('sni') or '')
    ]
    key_string = "|".join(key_parts)
    return hashlib.md5(key_string.encode('utf-8')).hexdigest()

def parse_vmess(vmess_url):
    """Parses a vmess:// URL."""
    try:
        b64_part = vmess_url.replace("vmess://", "")
        json_str = safe_decode(b64_part)
        data = json.loads(json_str)

        # Normalize fields
        return {
            "protocol": "vmess",
            "add": data.get("add", ""),
            "port": int(data.get("port", 0)),
            "id": data.get("id", ""),
            "aid": data.get("aid", "0"),
            "net": data.get("net", "tcp"),
            "type": data.get("type", "none"),
            "host": data.get("host", ""),
            "path": data.get("path", ""),
            "tls": data.get("tls", ""),
            "sni": data.get("sni", ""), # vmess json sometimes has sni
            "ps": data.get("ps", "")
        }
    except Exception:
        return None

def parse_vless_trojan(url, protocol):
    """Parses vless:// and trojan:// URLs."""
    try:
        # vless://uuid@host:port?params#name
        parsed = urlparse(url)
        params = parse_qs(parsed.query)

        config = {
            "protocol": protocol,
            "add": parsed.hostname,
            "port": parsed.port,
            "id": parsed.username,
            "net": params.get("type", ["tcp"])[0],
            "type": params.get("headerType", ["none"])[0], # for tcp
            "host": params.get("host", [""])[0],
            "path": params.get("path", [""])[0],
            "tls": "tls" if params.get("security", [""])[0] == "tls" else "",
            "sni": params.get("sni", [""])[0],
            "flow": params.get("flow", [""])[0],
            "ps": unquote(parsed.fragment)
        }

        # Fix for some vless formats where net is in 'security' or other places?
        # Actually standard vless/trojan params are usually 'type' (transport), 'security' (tls/xtls)
        # 'serviceName' for grpc, etc.
        # We try to map to a common structure.

        return config
    except Exception:
        return None

def parse_ss(url):
    """Parses ss:// URLs."""
    try:
        # ss://base64(method:password)@host:port#name
        # or ss://base64(method:password@host:port)#name

        parsed = urlparse(url)
        user_info = parsed.username
        host = parsed.hostname
        port = parsed.port

        # Check if the whole authority is base64 encoded (old style)
        if not host and not port and parsed.netloc:
             # Try decoding the whole netloc (excluding @ if present, though standard urlparse might handle it weirdly if no @)
             # Often ss://BASE64
             decoded = safe_decode(parsed.netloc)
             # Expected: method:password@host:port
             if '@' in decoded:
                 parts = decoded.split('@')
                 auth = parts[0]
                 addr = parts[1]
                 if ':' in auth:
                     method, password = auth.split(':', 1)
                 else:
                     method, password = "", auth # Fallback

                 if ':' in addr:
                     host, port = addr.split(':', 1)
                     port = int(port)
                 else:
                     host = addr
                     port = 80 # Default?

                 return {
                     "protocol": "shadowsocks",
                     "add": host,
                     "port": port,
                     "id": password, # Password as ID
                     "method": method,
                     "net": "tcp",
                     "ps": unquote(parsed.fragment)
                 }

        # New style: user_info is base64(method:password) or just method:password
        if user_info:
             # Try decode
             try:
                 decoded_auth = safe_decode(user_info)
                 if ':' in decoded_auth:
                     method, password = decoded_auth.split(':', 1)
                 else:
                     method, password = user_info.split(':', 1) # Maybe it wasn't base64
             except:
                 if ':' in user_info:
                     method, password = user_info.split(':', 1)
                 else:
                     return None

             return {
                 "protocol": "shadowsocks",
                 "add": host,
                 "port": port,
                 "id": password,
                 "method": method,
                 "net": "tcp",
                 "ps": unquote(parsed.fragment)
             }

        return None
    except Exception:
        return None

def parse_config_line(line):
    """Parses a config line and returns a dict."""
    line = line.strip()
    if line.startswith("vmess://"):
        return parse_vmess(line)
    elif line.startswith("vless://"):
        return parse_vless_trojan(line, "vless")
    elif line.startswith("trojan://"):
        return parse_vless_trojan(line, "trojan")
    elif line.startswith("ss://"):
        return parse_ss(line)
    # hysterial2:// is mentioned in collector.py but I'll skip complex parsing for now unless needed.
    # Just return basic info if possible or None.
    return None

def get_xray_download_url():
    """Returns the download URL for Xray based on OS."""
    system = platform.system()
    machine = platform.machine()

    # Map machine to Xray arch
    if machine.lower() in ['x86_64', 'amd64']:
        arch = "64"
    elif machine.lower() in ['arm64', 'aarch64']:
        arch = "arm64-v8a"
    else:
        arch = "32" # Fallback

    base_url = f"https://github.com/XTLS/Xray-core/releases/download/{XRAY_VERSION}"

    if system == "Linux":
        return f"{base_url}/Xray-linux-{arch}.zip"
    elif system == "Windows":
        return f"{base_url}/Xray-windows-{arch}.zip"
    elif system == "Darwin": # macOS
        return f"{base_url}/Xray-macos-{arch}.zip"
    else:
        raise Exception(f"Unsupported OS: {system}")

def check_and_install_xray():
    """Checks if Xray is installed, downloads if not."""
    if os.path.exists(XRAY_PATH):
        # Check if executable
        if platform.system() != "Windows" and not os.access(XRAY_PATH, os.X_OK):
            os.chmod(XRAY_PATH, stat.S_IEXEC | stat.S_IRUSR | stat.S_IWUSR)
        return True

    print(f"⚠️ Xray not found at {XRAY_PATH}. Downloading {XRAY_VERSION}...")

    if not os.path.exists(BIN_DIR):
        os.makedirs(BIN_DIR)

    try:
        url = get_xray_download_url()
        print(f"Downloading from {url}...")
        response = requests.get(url, stream=True)
        response.raise_for_status()

        zip_path = os.path.join(BIN_DIR, "xray.zip")
        with open(zip_path, 'wb') as f:
            for chunk in response.iter_content(chunk_size=8192):
                f.write(chunk)

        print("Extracting...")
        with zipfile.ZipFile(zip_path, 'r') as zip_ref:
            zip_ref.extractall(BIN_DIR)

        os.remove(zip_path)

        # Ensure executable permission on Linux/Mac
        if platform.system() != "Windows":
            # Find the binary just in case it's in a subfolder (usually it's flat)
            if os.path.exists(XRAY_PATH):
                os.chmod(XRAY_PATH, 0o755)
            else:
                # Sometimes the zip structure varies, but for Xray releases it's usually flat
                pass

        print("✅ Xray installed successfully.")
        return True
    except Exception as e:
        print(f"❌ Failed to install Xray: {e}")
        return False

def generate_xray_config(inbound_port, outbound_config):
    """Generates a minimal Xray config for testing."""
    # This constructs the JSON config for Xray
    # inbound: http or socks, listening on inbound_port
    # outbound: the config to test

    # We need to convert the parsed config dict back to Xray JSON outbound
    # This is TRICKY because we parsed it into a flat dict, but Xray needs structured JSON.
    # Alternatively, we can assume the input 'outbound_config' IS the full config line
    # and we use Xray's ability to parse it? No, Xray core expects JSON config.
    # OR, we can use the 'outbound' block from the parsed data if we map it correctly.

    # Actually, simpler approach for `tester.py`:
    # If we have the original link, maybe we can use a tool or library to convert link -> json?
    # Writing a robust link->json converter is hard.
    # BUT, wait. Most Xray clients do this.

    # Let's try to map our parsed dict to a basic Xray outbound structure.

    protocol = outbound_config['protocol']
    outbound = {
        "tag": "proxy",
        "protocol": protocol,
        "settings": {},
        "streamSettings": {
            "network": outbound_config.get('net', 'tcp'),
            "security": outbound_config.get('tls', 'none') or 'none',
        }
    }

    # Populate settings based on protocol
    if protocol == 'vmess':
        outbound['settings'] = {
            "vnext": [{
                "address": outbound_config['add'],
                "port": outbound_config['port'],
                "users": [{
                    "id": outbound_config['id'],
                    "alterId": int(outbound_config.get('aid', 0)),
                    "security": "auto"
                }]
            }]
        }
        # Stream Settings
        net = outbound_config.get('net', 'tcp')
        outbound['streamSettings']['network'] = net

        if net == 'ws':
            outbound['streamSettings']['wsSettings'] = {
                "path": outbound_config.get('path', '/'),
                "headers": {
                    "Host": outbound_config.get('host', '')
                }
            }
        elif net == 'grpc':
            outbound['streamSettings']['grpcSettings'] = {
                 "serviceName": outbound_config.get('path', '') # path is usually serviceName for grpc
            }

        if outbound_config.get('tls') == 'tls':
            outbound['streamSettings']['tlsSettings'] = {
                "serverName": outbound_config.get('sni') or outbound_config.get('host') or outbound_config.get('add'),
                "allowInsecure": True # For testing, we might want to allow insecure
            }

    elif protocol == 'vless':
        outbound['settings'] = {
            "vnext": [{
                "address": outbound_config['add'],
                "port": outbound_config['port'],
                "users": [{
                    "id": outbound_config['id'],
                    "encryption": "none",
                    "flow": outbound_config.get('flow', '')
                }]
            }]
        }
        # Stream settings similar to vmess
        net = outbound_config.get('net', 'tcp')
        outbound['streamSettings']['network'] = net
        if net == 'ws':
             outbound['streamSettings']['wsSettings'] = {
                "path": outbound_config.get('path', '/'),
                "headers": {"Host": outbound_config.get('host', '')}
            }
        if outbound_config.get('tls') == 'tls':
            outbound['streamSettings']['tlsSettings'] = {
                "serverName": outbound_config.get('sni') or outbound_config.get('host') or outbound_config.get('add'),
                "allowInsecure": True
            }

    elif protocol == 'trojan':
        outbound['settings'] = {
            "servers": [{
                "address": outbound_config['add'],
                "port": outbound_config['port'],
                "password": outbound_config['id']
            }]
        }
        if outbound_config.get('tls') == 'tls':
             outbound['streamSettings']['tlsSettings'] = {
                "serverName": outbound_config.get('sni') or outbound_config.get('host') or outbound_config.get('add'),
                "allowInsecure": True
            }

    elif protocol == 'shadowsocks':
        outbound['settings'] = {
            "servers": [{
                "address": outbound_config['add'],
                "port": outbound_config['port'],
                "method": outbound_config.get('method', 'aes-256-gcm'),
                "password": outbound_config['id']
            }]
        }

    # Full config
    config = {
        "log": {"loglevel": "none"},
        "inbounds": [{
            "port": inbound_port,
            "protocol": "http", # Use HTTP proxy for testing
            "settings": {},
            "tag": "http_in"
        }],
        "outbounds": [outbound]
    }

    return json.dumps(config, indent=2)

async def test_tcp_connection(host, port, timeout=3):
    """Tests TCP connection to host:port."""
    try:
        fut = asyncio.open_connection(host, port)
        reader, writer = await asyncio.wait_for(fut, timeout=timeout)
        writer.close()
        await writer.wait_closed()
        return True
    except:
        return False

async def test_real_delay(config_line, local_port, timeout=5, test_url="http://cp.cloudflare.com/generate_204"):
    """
    Tests real delay by starting an Xray instance and proxying a request.
    Returns delay in ms, or None if failed.
    """
    parsed = parse_config_line(config_line)
    if not parsed:
        return None, "Parse failed"

    config_json = generate_xray_config(local_port, parsed)

    # Create temp config file
    config_path = f"config_{local_port}.json"
    with open(config_path, 'w') as f:
        f.write(config_json)

    # Start Xray
    process = None
    try:
        # Check if Xray executable exists
        if not os.path.exists(XRAY_PATH):
             return None, "Xray not found"

        process = subprocess.Popen(
            [XRAY_PATH, "-c", config_path],
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL
        )

        # Give it a moment to start
        await asyncio.sleep(0.5)

        # Test connection
        start_time = time.time()
        proxies = f"http://127.0.0.1:{local_port}"

        async with aiohttp.ClientSession() as session:
            try:
                async with session.get(test_url, proxy=proxies, timeout=timeout) as response:
                    if response.status == 204 or response.status == 200:
                        delay = (time.time() - start_time) * 1000
                        return delay, None
                    else:
                        return None, f"Status {response.status}"
            except asyncio.TimeoutError:
                return None, "Timeout"
            except Exception as e:
                return None, str(e)

    except Exception as e:
        return None, f"Process error: {e}"
    finally:
        if process:
            process.terminate()
            try:
                process.wait(timeout=1)
            except:
                process.kill()

        # Clean up config file
        if os.path.exists(config_path):
            os.remove(config_path)
