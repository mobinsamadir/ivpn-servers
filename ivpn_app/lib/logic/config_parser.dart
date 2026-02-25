import 'dart:convert';

class ConfigParser {
  static Map<String, dynamic> generateXrayConfig(String link, {int localPort = 10808}) {
    final outbound = parseOutbound(link);
    return {
      "log": {
        "loglevel": "warning"
      },
      "inbounds": [
        {
          "port": localPort,
          "protocol": "socks",
          "settings": {
            "auth": "noauth",
            "udp": true
          },
          "sniffing": {
            "enabled": true,
            "destOverride": ["http", "tls"]
          }
        },
        {
          "port": localPort + 1,
          "protocol": "http",
          "settings": {
            "allowTransparent": false
          }
        }
      ],
      "outbounds": [
        outbound,
        {
          "protocol": "freedom",
          "tag": "direct",
          "settings": {}
        },
        {
          "protocol": "blackhole",
          "tag": "block",
          "settings": {}
        }
      ],
      "routing": {
        "domainStrategy": "IPIfNonMatch",
        "rules": [
          {
            "type": "field",
            "outboundTag": "block",
            "ip": ["geoip:private"]
          },
          {
            "type": "field",
            "outboundTag": "block",
            "domain": ["geosite:category-ads-all"]
          },
           {
            "type": "field",
            "outboundTag": "direct",
            "domain": ["geosite:cn"]
          },
          {
            "type": "field",
            "outboundTag": "direct",
            "ip": ["geoip:cn"]
          }
        ]
      }
    };
  }

  static Map<String, dynamic> parseOutbound(String link) {
    if (link.startsWith("vless://")) {
      return _parseVless(link);
    } else if (link.startsWith("vmess://")) {
      return _parseVmess(link);
    } else if (link.startsWith("ss://")) {
      return _parseShadowsocks(link);
    } else if (link.startsWith("trojan://")) {
      return _parseTrojan(link);
    }
    throw Exception("Unsupported protocol: $link");
  }

  static Map<String, dynamic> _parseVless(String link) {
    // vless://uuid@host:port?query#remark
    final uri = Uri.parse(link);
    final uuid = uri.userInfo;
    final host = uri.host;
    final port = uri.port;
    final query = uri.queryParameters;

    final encryption = query['encryption'] ?? 'none';
    final security = query['security'] ?? 'none'; // tls, reality, etc.
    final type = query['type'] ?? 'tcp';
    final sni = query['sni'] ?? '';
    final flow = query['flow'] ?? '';
    final pbk = query['pbk'] ?? '';
    final sid = query['sid'] ?? '';
    final fp = query['fp'] ?? '';
    final path = query['path'] ?? '';
    final hostHeader = query['host'] ?? '';
    final serviceName = query['serviceName'] ?? '';
    final mode = query['mode'] ?? ''; // grpc mode

    final streamSettings = <String, dynamic>{
      "network": type,
      "security": security,
    };

    if (security == 'tls') {
      streamSettings['tlsSettings'] = {
        "serverName": sni,
        "allowInsecure": false,
        "fingerprint": fp.isNotEmpty ? fp : "chrome",
        "alpn": query['alpn'] != null ? query['alpn']!.split(',') : []
      };
    } else if (security == 'reality') {
      streamSettings['realitySettings'] = {
        "show": false,
        "dest": "$sni:443", // Usually dest is sni:443 or fallback
        "xver": 0,
        "serverName": sni,
        "privateKey": "", // Client doesn't have private key? Wait. Client needs public key (pbk) and shortId (sid).
                          // Xray config for client usually uses `realitySettings` inside `streamSettings`.
                          // Wait, checking Xray client config structure for Reality.
                          // It is: streamSettings -> realitySettings -> publicKey, shortId, serverName, fingerprint, spiderX.
        "publicKey": pbk,
        "shortId": sid,
        "fingerprint": fp.isNotEmpty ? fp : "chrome",
        "spiderX": query['spx'] ?? ""
      };
    }

    if (type == 'tcp') {
        if (query['headerType'] == 'http') {
             streamSettings['tcpSettings'] = {
                "header": {
                    "type": "http",
                    "request": {
                        "headers": {
                            "Host": [hostHeader.isNotEmpty ? hostHeader : host]
                        }
                    }
                }
             };
        }
    } else if (type == 'ws') {
      streamSettings['wsSettings'] = {
        "path": path,
        "headers": {
          "Host": hostHeader.isNotEmpty ? hostHeader : host
        }
      };
    } else if (type == 'grpc') {
       streamSettings['grpcSettings'] = {
         "serviceName": serviceName,
         "multiMode": mode == 'multi'
       };
    }

    return {
      "protocol": "vless",
      "settings": {
        "vnext": [
          {
            "address": host,
            "port": port,
            "users": [
              {
                "id": uuid,
                "encryption": encryption,
                "flow": flow // xtls-rprx-vision
              }
            ]
          }
        ]
      },
      "streamSettings": streamSettings,
      "tag": "proxy"
    };
  }

  static Map<String, dynamic> _parseVmess(String link) {
    // vmess://base64_json
    final base64Str = link.substring(8);
    String decoded;
    try {
        decoded = utf8.decode(base64.decode(base64Str));
    } catch(e) {
        // Handle URL safe base64 or other padding
        decoded = utf8.decode(base64.decode(base64Str.padRight(base64Str.length + (4 - base64Str.length % 4) % 4, '=')));
    }

    final Map<String, dynamic> config = json.decode(decoded);

    // Config fields: v (version), ps (remark), add, port, id, aid, net, type, host, path, tls, sni, alpn, fp
    final streamSettings = <String, dynamic>{
      "network": config['net'] ?? 'tcp',
      "security": config['tls'] ?? 'none'
    };

    if (config['tls'] == 'tls') {
        streamSettings['tlsSettings'] = {
            "serverName": config['sni'] ?? config['host'] ?? '',
             "allowInsecure": false,
             "fingerprint": config['fp'] ?? 'chrome',
             "alpn": config['alpn'] != null ? (config['alpn'] as String).split(',') : []
        };
    }

    if (config['net'] == 'ws') {
        streamSettings['wsSettings'] = {
            "path": config['path'] ?? '',
            "headers": {
                "Host": config['host'] ?? ''
            }
        };
    } else if (config['net'] == 'grpc') {
         streamSettings['grpcSettings'] = {
             "serviceName": config['path'] ?? '',
             "multiMode": config['type'] == 'multi'
         };
    }

    return {
      "protocol": "vmess",
      "settings": {
        "vnext": [
          {
            "address": config['add'],
            "port": int.tryParse(config['port'].toString()) ?? 443,
            "users": [
              {
                "id": config['id'],
                "alterId": int.tryParse(config['aid'].toString()) ?? 0,
                "security": "auto"
              }
            ]
          }
        ]
      },
      "streamSettings": streamSettings,
      "tag": "proxy"
    };
  }

  static Map<String, dynamic> _parseShadowsocks(String link) {
    // ss://base64#remark or ss://method:password@host:port#remark
    // Handling simplified common case for now
    Uri uri;
    try {
       uri = Uri.parse(link);
    } catch(e) {
       // Manual parsing for ss if needed, usually uri parse works if standard
       throw Exception("Invalid SS link");
    }

    String userInfo = uri.userInfo;
    if (userInfo.isEmpty && uri.host.isEmpty) {
        // Try base64 decoding the host part if it's ss://BASE64
        // Logic for legacy ss links omitted for brevity, assuming standard ss://user:pass@host:port
        // or ss://BASE64@host:port
        String base64Part = link.substring(5).split('#')[0].split('@')[0];
         try {
            userInfo = utf8.decode(base64.decode(base64Part));
        } catch(e) {
             userInfo = utf8.decode(base64.decode(base64Part.padRight(base64Part.length + (4 - base64Part.length % 4) % 4, '=')));
        }
    }

    // userInfo is method:password
    final parts = userInfo.split(':');
    final method = parts[0];
    final password = parts.sublist(1).join(':');

    return {
      "protocol": "shadowsocks",
      "settings": {
        "servers": [
          {
            "address": uri.host,
            "port": uri.port,
            "method": method,
            "password": password,
            "ota": false
          }
        ]
      },
      "tag": "proxy"
    };
  }

  static Map<String, dynamic> _parseTrojan(String link) {
      final uri = Uri.parse(link);
      final password = uri.userInfo;
      final query = uri.queryParameters;

      final streamSettings = <String, dynamic>{
          "network": "tcp",
          "security": "tls",
          "tlsSettings": {
              "serverName": query['sni'] ?? uri.host,
              "allowInsecure": false,
               "fingerprint": query['fp'] ?? 'chrome',
               "alpn": query['alpn'] != null ? query['alpn']!.split(',') : []
          }
      };

      if (query['type'] == 'ws') {
          streamSettings['network'] = 'ws';
          streamSettings['wsSettings'] = {
              "path": query['path'] ?? '',
              "headers": {
                  "Host": query['host'] ?? ''
              }
          };
      }
       if (query['type'] == 'grpc') {
          streamSettings['network'] = 'grpc';
          streamSettings['grpcSettings'] = {
              "serviceName": query['serviceName'] ?? '',
              "multiMode": query['mode'] == 'multi'
          };
      }

      return {
          "protocol": "trojan",
          "settings": {
              "servers": [
                  {
                      "address": uri.host,
                      "port": uri.port,
                      "password": password
                  }
              ]
          },
          "streamSettings": streamSettings,
          "tag": "proxy"
      };
  }
}
