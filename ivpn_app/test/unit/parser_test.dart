import 'package:flutter_test/flutter_test.dart';
import 'package:ivpn_app/logic/config_parser.dart';

void main() {
  group('ConfigParser Tests', () {
    test('Parse VLESS Reality Link', () {
      const link = "vless://uuid@example.com:443?security=reality&encryption=none&pbk=publickey&sid=shortid&fp=chrome&type=tcp&sni=example.com&flow=xtls-rprx-vision#Example";
      final config = ConfigParser.generateXrayConfig(link);

      expect(config['outbounds'][0]['protocol'], 'vless');
      expect(config['outbounds'][0]['streamSettings']['security'], 'reality');
      expect(config['outbounds'][0]['streamSettings']['realitySettings']['publicKey'], 'publickey');
      expect(config['outbounds'][0]['streamSettings']['realitySettings']['shortId'], 'shortid');
      expect(config['outbounds'][0]['settings']['vnext'][0]['users'][0]['flow'], 'xtls-rprx-vision');
    });

    test('Parse VMess Link', () {
      // Mock base64 vmess
      // {"v": "2", "ps": "test", "add": "1.1.1.1", "port": "443", "id": "uuid", "aid": "0", "net": "ws", "type": "none", "host": "host.com", "path": "/path", "tls": "tls"}
      const vmessJson = '{"v": "2", "ps": "test", "add": "1.1.1.1", "port": "443", "id": "uuid", "aid": "0", "net": "ws", "type": "none", "host": "host.com", "path": "/path", "tls": "tls"}';
      // simple base64 encode
      // import 'dart:convert'; final base64Str = base64Encode(utf8.encode(vmessJson));
      // resulting string: eyJ2IjogIjIiLCAicHMiOiAidGVzdCIsICJhZGQiOiAiMS4xLjEuMSIsICJwb3J0IjogIjQ0MyIsICJpZCI6ICJ1dWlkIiwgImFpZCI6ICIwIiwgIm5ldCI6ICJ3cyIsICJ0eXBlIjogIm5vbmUiLCAiaG9zdCI6ICJob3N0LmNvbSIsICJwYXRoIjogIi9wYXRoIiwgInRscyI6ICJ0bHMifQ==
      const link = "vmess://eyJ2IjogIjIiLCAicHMiOiAidGVzdCIsICJhZGQiOiAiMS4xLjEuMSIsICJwb3J0IjogIjQ0MyIsICJpZCI6ICJ1dWlkIiwgImFpZCI6ICIwIiwgIm5ldCI6ICJ3cyIsICJ0eXBlIjogIm5vbmUiLCAiaG9zdCI6ICJob3N0LmNvbSIsICJwYXRoIjogIi9wYXRoIiwgInRscyI6ICJ0bHMifQ==";

      final config = ConfigParser.generateXrayConfig(link);

      expect(config['outbounds'][0]['protocol'], 'vmess');
      expect(config['outbounds'][0]['streamSettings']['network'], 'ws');
      expect(config['outbounds'][0]['streamSettings']['security'], 'tls');
      expect(config['outbounds'][0]['streamSettings']['wsSettings']['path'], '/path');
    });

    test('Parse Shadowsocks Link', () {
      // ss://aes-256-gcm:password@1.1.1.1:8888#Remark
      const link = "ss://aes-256-gcm:password@1.1.1.1:8888#Remark";
      final config = ConfigParser.generateXrayConfig(link);

      expect(config['outbounds'][0]['protocol'], 'shadowsocks');
      expect(config['outbounds'][0]['settings']['servers'][0]['method'], 'aes-256-gcm');
      expect(config['outbounds'][0]['settings']['servers'][0]['password'], 'password');
    });
  });
}
