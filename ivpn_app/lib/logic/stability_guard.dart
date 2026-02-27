import 'dart:io';
import 'dart:async';
import 'package:http/http.dart' as http; // For simple requests if needed, but HttpClient is better for proxy
import 'config_fetcher.dart';
import 'vpn_service.dart';

class StabilityGuard {
  final VpnService _vpnService;
  final ConfigFetcher _configFetcher;

  StabilityGuard(this._vpnService, this._configFetcher);

  Future<void> smartConnect() async {
    // 1. Fetch configs
    List<String> ultraFast = await _configFetcher.fetchUltraFast();
    List<String> realDelay = await _configFetcher.fetchRealDelay();

    // 2. Combine list for fallback strategy
    // Assuming backend sorts them by latency/priority.
    // Try top 3 ultra fast
    List<String> candidates = ultraFast.take(3).toList();
    // Then top 5 real delay
    candidates.addAll(realDelay.take(5));

    if (candidates.isEmpty) {
        throw Exception("No servers available.");
    }

    // 3. Iterate and Connect
    for (String config in candidates) {
      print("Trying config...");
      bool success = await _tryConnect(config);
      if (success) {
          print("Connected successfully!");
          return;
      }
      print("Config failed, retrying next...");
    }

    throw Exception("All servers failed.");
  }

  Future<bool> _tryConnect(String config) async {
    try {
      await _vpnService.connect(config);
      // Give it a moment to stabilize
      await Future.delayed(const Duration(seconds: 1));

      // verify
      bool works = await _verifyConnection();
      if (works) return true;

      await _vpnService.disconnect();
    } catch (e) {
      print("Connection failed for config: $e");
      try {
          await _vpnService.disconnect();
      } catch(e) {} // ignore disconnect error
    }
    return false;
  }

  Future<bool> _verifyConnection() async {
    if (Platform.isWindows) {
        return _checkWithProxy("127.0.0.1", 10809);
    } else {
        // Android: VPN is system-wide.
        return _checkDirect();
    }
  }

  Future<bool> _checkWithProxy(String host, int port) async {
    // Dual-Check: Cloudflare (204) -> Google (204)
    if (await _checkUrlWithProxy('http://cp.cloudflare.com/generate_204', host, port)) {
      return true;
    }
    return await _checkUrlWithProxy('https://www.google.com/generate_204', host, port);
  }

  Future<bool> _checkDirect() async {
    // Dual-Check: Cloudflare (204) -> Google (204)
    if (await _checkUrlDirect('http://cp.cloudflare.com/generate_204')) {
        return true;
    }
    return await _checkUrlDirect('https://www.google.com/generate_204');
  }

  Future<bool> _checkUrlWithProxy(String url, String host, int port) async {
    try {
      final client = HttpClient();
      client.findProxy = (uri) {
        return "PROXY $host:$port";
      };
      client.connectionTimeout = const Duration(seconds: 2);

      final request = await client.getUrl(Uri.parse(url));
      final response = await request.close();
      return response.statusCode == 204 || response.statusCode == 200;
    } catch (e) {
      print("Verification failed for $url: $e");
      return false;
    }
  }

  Future<bool> _checkUrlDirect(String url) async {
     try {
      final client = HttpClient();
      client.connectionTimeout = const Duration(seconds: 2);

      final request = await client.getUrl(Uri.parse(url));
      final response = await request.close();
      return response.statusCode == 204 || response.statusCode == 200;
    } catch (e) {
      print("Verification failed for $url: $e");
      return false;
    }
  }
}
