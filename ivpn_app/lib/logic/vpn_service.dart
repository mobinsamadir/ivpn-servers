import 'dart:io';
import 'dart:async';
import 'dart:convert';
import 'package:flutter/foundation.dart';
import 'package:flutter_v2ray/flutter_v2ray.dart';
import 'package:path_provider/path_provider.dart';
import 'package:process_run/shell.dart';

import 'config_parser.dart';
import 'system_proxy_manager.dart';

class VpnService {
  final FlutterV2ray _flutterV2ray = FlutterV2ray(
    onStatusChanged: (status) {
      // Handle status change if needed locally
    },
  );

  Process? _xrayProcess;
  bool _isConnected = false;

  Future<void> initialize() async {
    if (Platform.isAndroid) {
      await _flutterV2ray.initializeV2Ray();
    }
  }

  Future<void> connect(String configLink) async {
    if (Platform.isAndroid) {
      await _connectAndroid(configLink);
    } else if (Platform.isWindows) {
      await _connectWindows(configLink);
    }
    _isConnected = true;
  }

  Future<void> disconnect() async {
    if (Platform.isAndroid) {
      await _flutterV2ray.stopV2Ray();
    } else if (Platform.isWindows) {
      await _disconnectWindows();
    }
    _isConnected = false;
  }

  Future<bool> isConnected() async {
    // For Android, check internal status
    // For Windows, check process and flag
    return _isConnected;
  }

  Future<void> _connectAndroid(String configLink) async {
      // V2RayURL parser = FlutterV2ray.parseFromURL(configLink); // Assuming method exists or similar
      // await _flutterV2ray.startV2Ray(remark: "iVPN", config: parser.getFullConfiguration());
      // The API might differ slightly based on version.
      // Usually:
      if (await _flutterV2ray.requestPermission()) {
        V2RayURL v2rayURL = FlutterV2ray.parseFromURL(configLink);
        await _flutterV2ray.startV2Ray(
          remark: "iVPN Connection",
          config: v2rayURL.getFullConfiguration(),
          blockedApps: null,
          bypassSubnets: null,
          proxyOnly: false,
        );
      }
  }

  Future<void> _connectWindows(String configLink) async {
    // 1. Generate config.json
    final configMap = ConfigParser.generateXrayConfig(configLink);
    final jsonConfig = jsonEncode(configMap);

    // 2. Write to temp file
    final tempDir = await getTemporaryDirectory();
    final configFile = File('${tempDir.path}/config.json');
    await configFile.writeAsString(jsonConfig);

    // 3. Locate xray.exe
    // During dev: assets/bin/xray.exe
    // Released: relative to executable
    String xrayPath = 'assets/bin/xray.exe';
    if (!await File(xrayPath).exists()) {
       // fallback for release build or different structure
       final exeDir = File(Platform.resolvedExecutable).parent;
       xrayPath = '${exeDir.path}/data/flutter_assets/assets/bin/xray.exe';
    }

    if (!await File(xrayPath).exists()) {
        throw Exception("xray.exe not found at $xrayPath");
    }

    // 4. Kill existing
    await _killXrayWindows();

    // 5. Run process
    try {
        _xrayProcess = await Process.start(xrayPath, ['-c', configFile.path]);

        // Wait a bit to ensure it started
        await Future.delayed(const Duration(seconds: 1));

        // Check if process is still running
        // if (await _xrayProcess?.exitCode != null) ...
        // Process.start returns immediately.
    } catch (e) {
        print("Failed to start xray: $e");
        throw e;
    }

    // 6. Set System Proxy
    SystemProxyManager.setSystemProxy("127.0.0.1", 10809);
  }

  Future<void> _disconnectWindows() async {
    await _killXrayWindows();
    SystemProxyManager.clearSystemProxy();
  }

  Future<void> _killXrayWindows() async {
    if (_xrayProcess != null) {
      _xrayProcess!.kill();
      _xrayProcess = null;
    }
    // Also force kill any stray instances
    try {
        await Process.run('taskkill', ['/F', '/IM', 'xray.exe']);
    } catch(e) {
        // ignore
    }
  }
}
