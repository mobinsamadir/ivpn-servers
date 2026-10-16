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
if sys.platform != 'win32':
    import resource
import uuid
from urllib.parse import urlparse, parse_qs, unquote, quote
try:
    import geoip2.database
except ImportError:
    geoip2 = None

# Constants
# Using a stable version. Update this as needed.
XRAY_VERSION = "v24.11.21"
BIN_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "bin")
XRAY_EXECUTABLE = "xray.exe" if os.name == 'nt' else "xray"
XRAY_PATH = os.path.join(BIN_DIR, XRAY_EXECUTABLE)

def increase_file_limit():
    """Increases the maximum number of open file descriptors."""
    if os.name == 'nt':
        return

    try:
        soft, hard = resource.getrlimit(resource.RLIMIT_NOFILE)
        target = hard
        resource.setrlimit(resource.RLIMIT_NOFILE, (target, hard))
        print(f"✅ File limit increased from {soft} to {target}")
    except Exception as e:
        print(f"⚠️ Failed to increase file limit: {e}")

def safe_decode(data):
    """Robust Base64 decoding (standard and URL-safe, tolerant to non-utf8 and padding)."""
    if not data:
        return ""
    data = data.strip()
    if '#' in data:
        data = data.split('#')[0]
    if '?' in data:
        data = data.split('?')[0]
    data = unquote(data)
    data = data.replace('-', '+').replace('_', '/')
    cleaned = re.sub(r'[^A-Za-z0-9+/=]', '', data)
    missing_padding = len(cleaned) % 4
    if missing_padding:
        cleaned += '=' * (4 - missing_padding)
    try:
        decoded_bytes = base64.b64decode(cleaned)
        return decoded_bytes.decode('utf-8', errors='ignore')
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

def validate_uuid(uuid_str):
    """
    Validates if the string is a valid UUID using the uuid library.
    """
    if not uuid_str:
        return False
    try:
        uuid.UUID(uuid_str)
        return True
    except ValueError:
        return False

def validate_password(password):
    """
    Validates if the password contains only printable ASCII characters (33-126).
    """
    if not password:
        return False
    return all(33 <= ord(c) <= 126 for c in password)

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
        b64_part = vmess_url.replace("vmess://", "").strip()
        if '#' in b64_part:
            b64_part = b64_part.split('#')[0]
        if '?' in b64_part:
            b64_part = b64_part.split('?')[0]
        json_str = safe_decode(b64_part)
        data = json.loads(json_str)

        add = sanitize_host(data.get("add", ""))
        if not add: return None, "VMess_InvalidHost"

        # Validate & repair UUID
        id_val = unquote(str(data.get("id", ""))).strip()
        if not validate_uuid(id_val):
            return None, "VMess_InvalidUUID"

        try:
            port = int(str(data.get("port", 0)).strip())
            if port < 1 or port > 65535:
                return None, "VMess_InvalidPort"
        except (ValueError, TypeError):
            return None, "VMess_InvalidPort"

        try:
            aid = int(str(data.get("aid", "0")).strip())
        except (ValueError, TypeError):
            aid = 0

        net_val = str(data.get("net", "tcp")).strip().lower() or "tcp"
        tls_val = str(data.get("tls", "")).strip().lower()
        if not tls_val and port in [443, 8443, 2053, 2083, 2087, 2096, 2052]:
            tls_val = "tls"

        path_val = str(data.get("path", "")).strip()
        if net_val == "ws" and path_val and not path_val.startswith("/"):
            path_val = "/" + path_val

        host_val = str(data.get("host", "")).strip()
        sni_val = str(data.get("sni", "")).strip()
        if not sni_val and tls_val == "tls":
            sni_val = host_val or add

        # Normalize fields
        return {
            "protocol": "vmess",
            "add": add,
            "port": port,
            "id": id_val,
            "aid": aid,
            "net": net_val,
            "type": str(data.get("type", "none")).strip() or "none",
            "host": host_val,
            "path": path_val,
            "tls": tls_val,
            "sni": sni_val,
            "ps": str(data.get("ps", "")).strip()
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

        id_val = unquote(parsed.username).strip() if parsed.username else ""
        if protocol == "vless":
             if not validate_uuid(id_val):
                 return None, "VLESS_InvalidUUID"
        elif protocol == "trojan":
             if not validate_password(id_val):
                 return None, "Trojan_InvalidPassword"

        sec = params.get("security", [""])[0].strip().lower()
        # Allow 'reality' to be passed through for proper Flow validation later
        tls_val = sec if sec in ["tls", "reality"] else ""

        # Auto-repair Trojan TLS: Trojan in Xray requires TLS/Reality
        if protocol == "trojan" and not tls_val:
            sni_val = params.get("sni", [""])[0].strip()
            host_val = params.get("host", [""])[0].strip()
            # If standard TLS port or SNI/host exists, repair to TLS
            if port in [443, 8443, 2053, 2083, 2087, 2096, 2052] or sni_val or host_val:
                tls_val = "tls"

        # Validate REALITY pbk length
        pbk_val = params.get("pbk", [""])[0].strip()
        if tls_val == "reality":
            if len(pbk_val) not in [43, 44]:
                return None, f"{protocol}_InvalidRealityKey"

        flow_val = params.get("flow", [""])[0].strip()

        # Auto-repair network transport: support both 'type' and 'net' query params
        net_val = (params.get("type", [""])[0] or params.get("net", ["tcp"])[0] or "tcp").strip().lower()

        # Auto-repair path: ensure leading slash for ws
        path_val = params.get("path", [""])[0].strip()
        if net_val == "ws" and path_val and not path_val.startswith("/"):
            path_val = "/" + path_val

        # Auto-repair SNI fallback
        sni_val = params.get("sni", [""])[0].strip()
        if not sni_val and tls_val in ["tls", "reality"]:
            sni_val = params.get("host", [""])[0].strip() or add

        fp_val = params.get("fp", [""])[0].strip()
        if tls_val == "reality" and not fp_val:
            fp_val = "chrome"

        config = {
            "protocol": protocol,
            "add": add,
            "port": port,
            "id": id_val,
            "net": net_val,
            "type": params.get("headerType", ["none"])[0].strip() or "none",
            "host": params.get("host", [""])[0].strip(),
            "path": path_val,
            "tls": tls_val,
            "sni": sni_val,
            "flow": flow_val,
            "pbk": pbk_val,
            "sid": params.get("sid", [""])[0].strip(),
            "fp": fp_val,
            "spx": params.get("spx", [""])[0].strip(),
            "ps": unquote(parsed.fragment).strip() if parsed.fragment else ""
        }
        return config, None
    except Exception:
        return None, f"{protocol}_ParseError"

def parse_ss(url):
    """Parses ss:// URLs with full support for unencoded user:pass, SIP002 base64, and authority base64."""
    try:
        parsed = urlparse(url)
        user_info = parsed.username
        pass_info = parsed.password
        host = parsed.hostname
        port = parsed.port

        # Case 1: Standard unencoded ss://method:password@host:port#ps
        if user_info and pass_info:
            method = unquote(user_info).strip()
            password = unquote(pass_info).strip()
            host = sanitize_host(host)
            if not host: return None, "SS_InvalidHost"
            try:
                port = int(port)
            except (ValueError, TypeError):
                return None, "SS_InvalidPort"
            if not validate_password(password):
                return None, "SS_InvalidPassword"
            return {
                "protocol": "shadowsocks",
                "add": host,
                "port": port,
                "id": password,
                "method": method,
                "net": "tcp",
                "ps": unquote(parsed.fragment).strip() if parsed.fragment else ""
            }, None

        # Case 2: SIP002 format where user_info is base64(method:password) or method:password
        if user_info and not pass_info:
            method, password = "", ""
            decoded_auth = safe_decode(user_info)
            if ':' in decoded_auth:
                method, password = decoded_auth.split(':', 1)
            elif ':' in user_info:
                method, password = user_info.split(':', 1)
            else:
                return None, "SS_AuthParseError"

            method = unquote(method).strip()
            password = unquote(password).strip()
            host = sanitize_host(host)
            if not host: return None, "SS_InvalidHost"
            try:
                port = int(port)
            except (ValueError, TypeError):
                return None, "SS_InvalidPort"
            if not password:
                return None, "SS_MissingPassword"
            if not validate_password(password):
                return None, "SS_InvalidPassword"
            return {
                "protocol": "shadowsocks",
                "add": host,
                "port": port,
                "id": password,
                "method": method,
                "net": "tcp",
                "ps": unquote(parsed.fragment).strip() if parsed.fragment else ""
            }, None

        # Case 3: Old style: the whole authority is base64 encoded ss://base64(method:password@host:port)#ps
        if not user_info and not port and parsed.netloc:
             decoded = safe_decode(parsed.netloc)
             if '@' in decoded:
                 parts = decoded.split('@', 1)
                 auth = parts[0]
                 addr = parts[1]
                 if ':' in auth:
                     method, password = auth.split(':', 1)
                 else:
                     method, password = "", auth

                 # Clean trailing query or path from addr (e.g. host:port/?plugin=...)
                 if '/' in addr:
                     addr = addr.split('/')[0]
                 if '?' in addr:
                     addr = addr.split('?')[0]

                 if ':' in addr:
                     host, port_str = addr.rsplit(':', 1)
                     try:
                         port = int(port_str.strip())
                     except (ValueError, TypeError):
                         port = 80
                 else:
                     host = addr
                     port = 80

                 host = sanitize_host(host)
                 if not host: return None, "SS_InvalidHost"
                 if not password:
                     return None, "SS_MissingPassword"
                 pwd = unquote(password).strip()
                 if not validate_password(pwd):
                     return None, "SS_InvalidPassword"

                 return {
                     "protocol": "shadowsocks",
                     "add": host,
                     "port": port,
                     "id": pwd,
                     "method": method.strip(),
                     "net": "tcp",
                     "ps": unquote(parsed.fragment).strip() if parsed.fragment else ""
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

def construct_config_line(config):
    """Reconstructs a config string from a parsed dictionary."""
    protocol = config.get("protocol")

    if protocol == "vmess":
        data = {
            "v": "2",
            "ps": config.get("ps", ""),
            "add": config.get("add", ""),
            "port": str(config.get("port", "")),
            "id": config.get("id", ""),
            "aid": str(config.get("aid", 0)),
            "scy": "auto",
            "net": config.get("net", "tcp"),
            "type": config.get("type", "none"),
            "host": config.get("host", ""),
            "path": config.get("path", ""),
            "tls": config.get("tls", ""),
            "sni": config.get("sni", ""),
            "alpn": ""
        }
        json_str = json.dumps(data)
        b64_str = base64.b64encode(json_str.encode("utf-8")).decode("utf-8")
        return f"vmess://{b64_str}"

    elif protocol in ["vless", "trojan"]:
        # protocol://id@add:port?params#ps
        query = []
        if config.get("tls"):
            query.append(f"security={config['tls']}")
        if config.get("net"):
            query.append(f"type={config['net']}")

        # TCP Header type
        if config.get("type") and config.get("type") != "none":
            query.append(f"headerType={config['type']}")

        if config.get("host"):
            query.append(f"host={quote(config['host'])}")
        if config.get("path"):
            query.append(f"path={quote(config['path'])}")
        if config.get("sni"):
            query.append(f"sni={config['sni']}")
        if config.get("flow"):
            query.append(f"flow={config['flow']}")

        # REALITY params
        if config.get("pbk"):
            query.append(f"pbk={config['pbk']}")
        if config.get("fp"):
            query.append(f"fp={config['fp']}")
        if config.get("sid"):
            query.append(f"sid={config['sid']}")
        if config.get("spx"):
            query.append(f"spx={quote(config['spx'])}")

        query_str = "&".join(query)
        ps_encoded = quote(config.get("ps", ""))

        return f"{protocol}://{config['id']}@{config['add']}:{config['port']}?{query_str}#{ps_encoded}"

    elif protocol == "shadowsocks":
        # ss://base64(method:password)@host:port#ps
        user_pass = f"{config.get('method', '')}:{config.get('id', '')}"
        b64_auth = base64.b64encode(user_pass.encode("utf-8")).decode("utf-8")
        ps_encoded = quote(config.get("ps", ""))
        return f"ss://{b64_auth}@{config['add']}:{config['port']}#{ps_encoded}"

    return None

def check_and_download_geoip_db():
    """Downloads GeoLite2-Country.mmdb if missing."""
    mmdb_path = os.path.join(BIN_DIR, "Country.mmdb")
    if os.path.exists(mmdb_path):
        return True

    print("⚠️ Country.mmdb not found. Downloading...")
    if not os.path.exists(BIN_DIR):
        os.makedirs(BIN_DIR)

    url = "https://github.com/P3TERX/GeoLite.mmdb/raw/download/GeoLite2-Country.mmdb"
    try:
        response = requests.get(url, stream=True, timeout=30)
        response.raise_for_status()
        with open(mmdb_path, 'wb') as f:
            for chunk in response.iter_content(chunk_size=8192):
                f.write(chunk)
        print("✅ Country.mmdb downloaded.")
        return True
    except Exception as e:
        print(f"❌ Failed to download Country.mmdb: {e}")
        return False

def get_country_code(ip, db_path=None):
    """
    Returns the ISO country code for an IP address.
    """
    if geoip2 is None:
        return None
    if not db_path:
        db_path = os.path.join(BIN_DIR, "Country.mmdb")

    if not os.path.exists(db_path):
        return None

    try:
        with geoip2.database.Reader(db_path) as reader:
            response = reader.country(ip)
            return response.country.iso_code
    except Exception:
        return None

def get_country_flag(country_code):
    """Returns the flag emoji for a country code."""
    if not country_code:
        return "🚩"

    country_code = country_code.upper()
    if len(country_code) != 2:
        return "🚩"

    # Regional Indicator Symbol Letter A is 127462
    base = 127397
    first = ord(country_code[0]) + base
    second = ord(country_code[1]) + base
    return chr(first) + chr(second)

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
        if os.name != 'nt' and not os.access(XRAY_PATH, os.X_OK):
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

        if os.name != 'nt':
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

    # Generic Whitespace Trimming
    for key, value in outbound_config.items():
        if isinstance(value, str):
            outbound_config[key] = value.strip()

    # --- Schema Validation ---
    protocol = outbound_config.get('protocol')
    net = outbound_config.get('net', 'tcp')
    cipher = outbound_config.get('method', '')

    # 1. Validate Port
    try:
        port_num = int(outbound_config.get('port', 0))
        if port_num < 1 or port_num > 65535:
            return None
    except (ValueError, TypeError):
        return None

    if not outbound_config.get('add'):
        return None

    # 2. Check for missing password in Shadowsocks or Trojan
    if (protocol == 'shadowsocks' or protocol == 'trojan') and not outbound_config.get('id'):
        return None

    tls_mode = outbound_config.get('tls', 'none') or 'none'
    if tls_mode not in ['tls', 'reality', 'none']:
        tls_mode = 'none'

    # Auto-repair Trojan: requires TLS or REALITY in Xray client outbound
    if protocol == 'trojan' and tls_mode not in ['tls', 'reality']:
        if port_num in [443, 8443, 2053, 2083, 2087, 2096, 2052] or outbound_config.get('sni') or outbound_config.get('host'):
            tls_mode = 'tls'
        else:
            return None

    # 3. Check for deprecated ciphers and invalid characters in Shadowsocks
    if cipher in ['aes-128-cfb', 'aes-256-cfb', 'rc4-md5', 'chacha20-ietf', 'ss']:
        return None

    if cipher and re.search(r'[^a-zA-Z0-9\-]', cipher):
        return None

    # 4. Check for supported transport protocols
    valid_nets = {'tcp', 'ws', 'grpc', 'http', 'quic', 'httpupgrade', 'h2'}
    if net not in valid_nets:
        return None

    outbound = {
        "tag": tag,
        "protocol": protocol,
        "settings": {},
        "streamSettings": {
            "network": net,
            "security": tls_mode,
        }
    }

    # Protocol-specific Settings
    if protocol == 'vmess':
        user_id = str(outbound_config.get('id', '')).strip()
        if not validate_uuid(user_id):
            return None

        outbound['settings'] = {
            "vnext": [{
                "address": outbound_config['add'],
                "port": port_num,
                "users": [{
                    "id": user_id,
                    "alterId": int(outbound_config.get('aid', 0)),
                    "security": "aes-128-gcm"
                }]
            }]
        }

    elif protocol == 'vless':
        user_id = str(outbound_config.get('id', '')).strip()
        if not validate_uuid(user_id):
            return None

        if outbound_config.get('flow') == 'xtls-rprx-vision':
            if tls_mode not in ['tls', 'reality']:
                return None

        user_obj = {
            "id": user_id,
            "encryption": "none"
        }
        flow_val = outbound_config.get('flow')
        if flow_val:
            user_obj["flow"] = flow_val

        outbound['settings'] = {
            "vnext": [{
                "address": outbound_config['add'],
                "port": port_num,
                "users": [user_obj]
            }]
        }

    elif protocol == 'trojan':
        outbound['settings'] = {
            "servers": [{
                "address": outbound_config['add'],
                "port": port_num,
                "password": outbound_config['id']
            }]
        }

    elif protocol == 'shadowsocks':
        outbound['settings'] = {
            "servers": [{
                "address": outbound_config['add'],
                "port": port_num,
                "method": outbound_config.get('method', 'aes-256-gcm'),
                "password": outbound_config['id']
            }]
        }

    # Common Transport Settings
    if net == 'ws':
        path_ws = outbound_config.get('path', '/').strip() or '/'
        if not path_ws.startswith('/'):
            path_ws = '/' + path_ws
        outbound['streamSettings']['wsSettings'] = {
            "path": path_ws,
            "headers": {"Host": outbound_config.get('host', '').strip()}
        }
    elif net == 'grpc':
        outbound['streamSettings']['grpcSettings'] = {
            "serviceName": outbound_config.get('path', '').strip()
        }
    elif net in ['http', 'h2']:
        path_http = outbound_config.get('path', '/').strip() or '/'
        if not path_http.startswith('/'):
            path_http = '/' + path_http
        outbound['streamSettings']['httpSettings'] = {
            "path": path_http,
            "host": [outbound_config.get('host', '').strip()] if outbound_config.get('host') else []
        }
    elif net == 'quic':
        outbound['streamSettings']['quicSettings'] = {
            "security": "none",
            "key": "",
            "header": {
                "type": outbound_config.get('type') or "none"
            }
        }
    elif net == 'httpupgrade':
        path_up = outbound_config.get('path', '/').strip() or '/'
        if not path_up.startswith('/'):
            path_up = '/' + path_up
        outbound['streamSettings']['httpupgradeSettings'] = {
            "path": path_up,
            "host": outbound_config.get('host', '').strip()
        }

    # Common Security Settings (TLS / Reality)
    if tls_mode == 'tls':
        sni_clean = (outbound_config.get('sni') or outbound_config.get('host') or outbound_config.get('add') or '').strip()
        sni_clean = re.sub(r'^https?://', '', sni_clean).split(':')[0].split('/')[0].strip()
        outbound['streamSettings']['tlsSettings'] = {
            "serverName": sni_clean,
            "allowInsecure": True
        }
        alpn = outbound_config.get('alpn')
        if alpn:
            outbound['streamSettings']['tlsSettings']['alpn'] = [s.strip() for s in alpn.split(',') if s.strip()]
    elif tls_mode == 'reality':
        pub_key = (outbound_config.get('pbk') or '').strip()
        if not pub_key or len(pub_key) not in [43, 44]:
            return None

        fp = (outbound_config.get('fp') or 'chrome').strip() or 'chrome'
        sid = (outbound_config.get('sid') or '').strip()
        if sid:
            if len(sid) % 2 != 0 or not all(c in '0123456789abcdefABCDEF' for c in sid):
                return None

        sni_clean = (outbound_config.get('sni') or outbound_config.get('add') or '').strip()
        sni_clean = re.sub(r'^https?://', '', sni_clean).split(':')[0].split('/')[0].strip()

        outbound['streamSettings']['realitySettings'] = {
            "show": False,
            "fingerprint": fp,
            "serverName": sni_clean,
            "publicKey": pub_key,
            "shortId": sid,
            "spiderX": outbound_config.get('spx', '')
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
