import 'dart:io';

class PreFlightCheck {
  static const List<int> _portsToCheck = [10808, 10809];
  static const List<String> _processNames = ['xray.exe', 'v2ray.exe', 'clash.exe', 'nekoray.exe'];

  static Future<List<String>> checkConflicts() async {
    List<String> conflicts = [];

    // check ports
    for (int port in _portsToCheck) {
      if (await _isPortInUse(port)) {
        conflicts.add('Port $port is already in use.');
      }
    }

    // check processes (Windows only)
    if (Platform.isWindows) {
      try {
        final result = await Process.run('tasklist', []);
        final output = result.stdout.toString().toLowerCase();
        for (String process in _processNames) {
          if (output.contains(process.toLowerCase())) {
            conflicts.add('Process $process is running.');
          }
        }
      } catch (e) {
        print('Error checking processes: $e');
      }
    }

    return conflicts;
  }

  static Future<bool> _isPortInUse(int port) async {
    try {
      final server = await ServerSocket.bind(InternetAddress.loopbackIPv4, port);
      await server.close();
      return false;
    } catch (e) {
      return true;
    }
  }
}
