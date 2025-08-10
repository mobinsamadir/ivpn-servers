import 'dart:async';
import 'package:http/http.dart' as http;
import '../models/server_model.dart';

class PingService {
  final Map<String, Timer> _pingTimers = {};
  final Function(Server) onUpdate;

  PingService({required this.onUpdate});

  void startPingingAllServers(List<Server> servers) {
    stopAllPinging();
    for (int i = 0; i < servers.length; i++) {
      _schedulePing(servers[i], isInitial: true, index: i);
    }
  }

  void pingServerGroup(List<Server> group) {
    for (final server in group) {
      _schedulePing(server, isInitial: false, index: 0);
    }
  }

  void stopAllPinging() {
    _pingTimers.forEach((key, timer) => timer.cancel());
    _pingTimers.clear();
  }

  void dispose() {
    stopAllPinging();
  }

  void _schedulePing(Server server, {bool isInitial = false, int index = 0}) {
    _pingTimers[server.id]?.cancel();
    Duration initialDelay = isInitial
        ? Duration(milliseconds: index * 150)
        : Duration.zero;
    Timer(initialDelay, () => _httpPingServer(server));
  }

  Future<void> _httpPingServer(Server server) async {
    print("DEBUG: [HTTP Pinging...] - Probing ${server.name}");
    final stopwatch = Stopwatch()..start();

    // We try both https and http
    Uri httpsUri = Uri.parse('https://[${server.ip}]:${server.port}');
    Uri httpUri = Uri.parse('http://[${server.ip}]:${server.port}');

    try {
      // First, try with https
      await http.head(httpsUri).timeout(const Duration(milliseconds: 2500));
      stopwatch.stop();
      _updateServerStatus(server, stopwatch.elapsedMilliseconds);
      print(
        "DEBUG: [SUCCESS ✔️] - ${server.name} responded via HTTPS in ${stopwatch.elapsedMilliseconds} ms.",
      );
    } catch (e) {
      // If https fails, try with http
      stopwatch.reset();
      try {
        await http.head(httpUri).timeout(const Duration(milliseconds: 2500));
        stopwatch.stop();
        _updateServerStatus(server, stopwatch.elapsedMilliseconds);
        print(
          "DEBUG: [SUCCESS ✔️] - ${server.name} responded via HTTP in ${stopwatch.elapsedMilliseconds} ms.",
        );
      } catch (e2) {
        // If both fail
        stopwatch.stop();
        _updateServerStatus(server, 2301); // Failed ping value
        print(
          "DEBUG: [FAILURE ❌] - ${server.name} did not respond to HTTP/S probes.",
        );
      }
    }

    onUpdate(server);

    Duration nextPingDelay = const Duration(seconds: 30);
    if (server.isConnected) nextPingDelay = const Duration(seconds: 5);
    if (server.status == PingStatus.good)
      nextPingDelay = const Duration(seconds: 15);
    _pingTimers[server.id] = Timer(
      nextPingDelay,
      () => _httpPingServer(server),
    );
  }

  void _updateServerStatus(Server server, int pingTime) {
    server.ping = pingTime;
    if (server.ping < 700) {
      server.status = PingStatus.good;
    } else if (server.ping <= 2300) {
      server.status = PingStatus.medium;
    } else {
      server.status = PingStatus.bad;
    }
  }

  void pingSingleServer(Server server) {
    _schedulePing(server);
  }
}
