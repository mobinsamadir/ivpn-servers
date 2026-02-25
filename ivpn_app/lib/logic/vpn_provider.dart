import 'package:flutter/material.dart';
import 'package:ivpn_app/logic/config_fetcher.dart';
import 'package:ivpn_app/logic/stability_guard.dart';
import 'package:ivpn_app/logic/vpn_service.dart';
import 'package:ivpn_app/logic/pre_flight_check.dart';

enum VpnState { disconnected, connecting, connected, error }

class VpnProvider extends ChangeNotifier {
  final VpnService _vpnService;
  final ConfigFetcher _configFetcher;
  late final StabilityGuard _stabilityGuard;

  VpnState _state = VpnState.disconnected;
  String? _errorMessage;
  List<String> _preFlightIssues = [];

  VpnState get state => _state;
  String? get errorMessage => _errorMessage;
  List<String> get preFlightIssues => _preFlightIssues;

  VpnProvider({VpnService? vpnService, ConfigFetcher? configFetcher})
      : _vpnService = vpnService ?? VpnService(),
        _configFetcher = configFetcher ?? ConfigFetcher() {
    _stabilityGuard = StabilityGuard(_vpnService, _configFetcher);
    _init();
  }

  Future<void> _init() async {
    // 1. Run Pre-flight
    _preFlightIssues = await PreFlightCheck.checkConflicts();
    if (_preFlightIssues.isNotEmpty) {
      _errorMessage = "Port conflicts detected!";
    }

    // 2. Init VPN Service
    try {
        await _vpnService.initialize();
    } catch(e) {
        _errorMessage = "Failed to initialize VPN: $e";
    }
    notifyListeners();
  }

  Future<void> connect() async {
    _state = VpnState.connecting;
    _errorMessage = null;
    notifyListeners();

    try {
      // Run Smart Connect
      await _stabilityGuard.smartConnect();
      _state = VpnState.connected;
    } catch (e) {
      _state = VpnState.error;
      _errorMessage = e.toString();
    }
    notifyListeners();
  }

  Future<void> disconnect() async {
    try {
      await _vpnService.disconnect();
      _state = VpnState.disconnected;
    } catch (e) {
      _errorMessage = "Failed to disconnect: $e";
    }
    notifyListeners();
  }
}
