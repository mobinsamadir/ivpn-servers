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
import stat
import time
import requests
import resource
from urllib.parse import urlparse, parse_qs, unquote

# Constants
# Using a stable version. Update this as needed.
XRAY_VERSION = "v24.11.21"
BIN_DIR = "bin"
XRAY_EXECUTABLE = "xray.exe" if platform.system() == "Windows" else "xray"
XRAY_PATH = os.path.join(BIN_DIR, XRAY_EXECUTABLE)

def increase_file_limit():
    """Increases the maximum number of open file descriptors."""
    if platform.system() == "Windows":
        return

    try:
        soft, hard = resource.getrlimit(resource.RLIMIT_NOFILE)
        target = hard
        resource.setrlimit(resource.RLIMIT_NOFILE, (target, hard))
        print(f"✅ File limit increased from {soft} to {target}")
    except Exception as e:
        print(f"⚠️ Failed to increase file limit: {e}")

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

def sanitize_host(host):
    """
    Sanitizes and validates a hostname/IP.
    Returns None if invalid.
    """
    if not host:
        return None

    host = host.strip()

    # Remove protocol prefixes
    host = re.sub(r'^https?://', '', host)

    # Remove paths, query params, fragments
    if '/' in host:
        host = host.split('/')[0]
    if '?' in host:
        host = host.split('?')[0]
    if '#' in host:
        host = host.split('#')[0]

    # Remove port if included (e.g. example.com:443)
    if ':' in host:
        # Check if it's IPv6 (contains multiple colons)
        if host.count(':') > 1 and '[' in host:
            # IPv6 literal [::1]:80
            match = re.match(r'^\[(.*?)\](?::\d+)?$', host)
            if match:
                host = match.group(1)
        elif host.count(':') == 1:
            # IPv4 or hostname with port
            host = host.split(':')[0]

    # Basic validation: allowed chars are alphanumeric, dots, hyphens, colons (IPv6)
    # If it contains anything else, it's garbage
    if re.search(r'[^a-zA-Z0-9.\-:]', host):
        return None

    if not host:
        return None

    return host

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

        add = sanitize_host(data.get("add", ""))
        if not add: return None, "VMess_InvalidHost"

        # Normalize fields
        return {
            "protocol": "vmess",
            "add": add,
            "port": int(data.get("port", 0)),
            "id": data.get("id", ""),
            "aid": int(data.get("aid", "0")),
            "net": data.get("net", "tcp"),
            "type": data.get("type", "none"),
            "host": data.get("host", ""),
            "path": data.get("path", ""),
            "tls": data.get("tls", ""),
            "sni": data.get("sni", ""), # vmess json sometimes has sni
            "ps": data.get("ps", "")
        }, None
    except Exception:
        return None, "VMess_ParseError"

def parse_vless_trojan(url, protocol):
    """Parses vless:// and trojan:// URLs."""
    try:
        # vless://uuid@host:port?params#name
        parsed = urlparse(url)
        params = parse_qs(parsed.query)

        add = sanitize_host(parsed.hostname)
        if not add: return None, f"{protocol}_InvalidHost"

        try:
            port = int(parsed.port)
        except (ValueError, TypeError):
            return None, f"{protocol}_InvalidPort"

        config = {
            "protocol": protocol,
            "add": add,
            "port": port,
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
        return config, None
    except Exception:
        return None, f"{protocol}_ParseError"

def parse_ss(url):
    """Parses ss:// URLs."""
    try:
        parsed = urlparse(url)
        user_info = parsed.username
        host = parsed.hostname
        port = parsed.port

        # Check if the whole authority is base64 encoded (old style)
        if not user_info and not port and parsed.netloc:
             decoded = safe_decode(parsed.netloc)
             if '@' in decoded:
                 parts = decoded.split('@')
                 auth = parts[0]
                 addr = parts[1]
                 if ':' in auth:
                     method, password = auth.split(':', 1)
                 else:
                     method, password = "", auth

                 if ':' in addr:
                     host, port = addr.split(':', 1)
                     port = int(port)
                 else:
                     host = addr
                     port = 80

                 host = sanitize_host(host)
                 if not host: return None, "SS_InvalidHost"

                 if not password:
                     return None, "SS_MissingPassword"

                 return {
                     "protocol": "shadowsocks",
                     "add": host,
                     "port": int(port),
                     "id": password,
                     "method": method,
                     "net": "tcp",
                     "ps": unquote(parsed.fragment)
                 }, None

        # New style: user_info is base64(method:password) or just method:password
        if user_info:
             try:
                 decoded_auth = safe_decode(user_info)
                 if ':' in decoded_auth:
                     method, password = decoded_auth.split(':', 1)
                 else:
                     method, password = user_info.split(':', 1)
             except:
                 if ':' in user_info:
                     method, password = user_info.split(':', 1)
                 else:
                     return None, "SS_AuthParseError"

             host = sanitize_host(host)
             if not host: return None, "SS_InvalidHost"

             try:
                 port = int(port)
             except (ValueError, TypeError):
                 return None, "SS_InvalidPort"

             if not password:
                 return None, "SS_MissingPassword"

             return {
                 "protocol": "shadowsocks",
                 "add": host,
                 "port": int(port),
                 "id": password,
                 "method": method,
                 "net": "tcp",
                 "ps": unquote(parsed.fragment)
             }, None

        return None, "SS_InvalidFormat"
    except Exception:
        return None, "SS_ParseError"

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
    return None, "Unsupported_Protocol"

def get_xray_download_url():
    """Returns the download URL for Xray based on OS."""
    system = platform.system()
    machine = platform.machine()

    if machine.lower() in ['x86_64', 'amd64']:
        arch = "64"
    elif machine.lower() in ['arm64', 'aarch64']:
        arch = "arm64-v8a"
    else:
        arch = "32"

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
    geoip_path = os.path.join(BIN_DIR, "geoip.dat")
    geosite_path = os.path.join(BIN_DIR, "geosite.dat")

    if os.path.exists(XRAY_PATH) and os.path.exists(geoip_path) and os.path.exists(geosite_path):
        if platform.system() != "Windows" and not os.access(XRAY_PATH, os.X_OK):
            os.chmod(XRAY_PATH, stat.S_IEXEC | stat.S_IRUSR | stat.S_IWUSR)
        return True

    print(f"⚠️ Xray or assets (geoip/geosite) not found. Downloading {XRAY_VERSION}...")

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

        if platform.system() != "Windows":
            if os.path.exists(XRAY_PATH):
                os.chmod(XRAY_PATH, 0o755)
            else:
                pass

        # Verify assets
        if not os.path.exists(os.path.join(BIN_DIR, "geoip.dat")) or not os.path.exists(os.path.join(BIN_DIR, "geosite.dat")):
             print("⚠️ Warning: geoip.dat or geosite.dat missing after extraction. Xray may crash.")

        print("✅ Xray installed successfully.")
        return True
    except Exception as e:
        print(f"❌ Failed to install Xray: {e}")
        return False

def _create_outbound_object(outbound_config, tag):
    """Helper to create a single Xray outbound object."""
    # --- Schema Validation ---
    protocol = outbound_config.get('protocol')
    net = outbound_config.get('net', 'tcp')
    cipher = outbound_config.get('method', '')

    # 1. Check for missing password in Shadowsocks
    if protocol == 'shadowsocks' and not outbound_config.get('id'):
        return None

    # 2. Check for deprecated ciphers
    if cipher in ['aes-256-cfb', 'rc4-md5']:
        return None

    # 3. Check for supported transport protocols
    valid_nets = {'tcp', 'ws', 'grpc', 'http', 'quic', 'httpupgrade'}
    if net not in valid_nets:
        return None
    # -------------------------

    outbound = {
        "tag": tag,
        "protocol": protocol,
        "settings": {},
        "streamSettings": {
            "network": net,
            "security": outbound_config.get('tls', 'none') or 'none',
        }
    }

    if protocol == 'vmess':
        outbound['settings'] = {
            "vnext": [{
                "address": outbound_config['add'],
                "port": int(outbound_config['port']),
                "users": [{
                    "id": outbound_config['id'],
                    "alterId": int(outbound_config.get('aid', 0)),
                    "security": "auto"
                }]
            }]
        }
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
                 "serviceName": outbound_config.get('path', '')
            }

        if outbound_config.get('tls') == 'tls':
            outbound['streamSettings']['tlsSettings'] = {
                "serverName": outbound_config.get('sni') or outbound_config.get('host') or outbound_config.get('add'),
                "allowInsecure": True
            }

    elif protocol == 'vless':
        outbound['settings'] = {
            "vnext": [{
                "address": outbound_config['add'],
                "port": int(outbound_config['port']),
                "users": [{
                    "id": outbound_config['id'],
                    "encryption": "none",
                    "flow": outbound_config.get('flow', '')
                }]
            }]
        }
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
                "port": int(outbound_config['port']),
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
                "port": int(outbound_config['port']),
                "method": outbound_config.get('method', 'aes-256-gcm'),
                "password": outbound_config['id']
            }]
        }

    return outbound

def generate_xray_batch_config(batch_configs, start_port):
    """
    Generates a single Xray config for a batch of proxies.
    Maps multiple inbounds (http) to multiple outbounds (proxy) via routing rules.
    """
    inbounds = []
    outbounds = []
    routing_rules = []

    for i, config_data in enumerate(batch_configs):
        if not config_data:
            continue

        local_port = start_port + i
        inbound_tag = f"inbound-{local_port}"
        outbound_tag = f"outbound-{local_port}"

        # Create Inbound
        inbounds.append({
            "port": int(local_port),
            "protocol": "http",
            "settings": {},
            "tag": inbound_tag,
            "listen": "127.0.0.1" # Secure to localhost
        })

        # Create Outbound
        outbound = _create_outbound_object(config_data, outbound_tag)
        if not outbound:
            continue

        outbounds.append(outbound)

        # Create Routing Rule
        routing_rules.append({
            "type": "field",
            "inboundTag": [inbound_tag],
            "outboundTag": outbound_tag
        })

    config = {
        "log": {"loglevel": "debug"},
        "inbounds": inbounds,
        "outbounds": outbounds,
        "routing": {
            "domainStrategy": "AsIs",
            "rules": routing_rules
        }
    }

    return json.dumps(config)

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
