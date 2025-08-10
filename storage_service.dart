import 'package:shared_preferences/shared_preferences.dart';
import '../models/server_model.dart';

class StorageService {
  static const _serversKey = 'saved_servers';
  static const _lastUpdateKey = 'last_update_timestamp';
  static const _recentServersKey =
      'recent_servers'; // <-- کلید جدید برای لیست اخیر

  // --- متد جدید برای ذخیره سرورهای اخیر ---
  Future<void> saveRecentServers(List<Server> servers) async {
    final prefs = await SharedPreferences.getInstance();
    final List<String> serverConfigs = servers.map((s) => s.rawConfig).toList();
    await prefs.setStringList(_recentServersKey, serverConfigs);
  }

  // --- متد جدید برای خواندن سرورهای اخیر ---
  Future<List<Server>> loadRecentServers() async {
    final prefs = await SharedPreferences.getInstance();
    final List<String> serverConfigs =
        prefs.getStringList(_recentServersKey) ?? [];
    return serverConfigs
        .map((config) => Server.fromConfigString(config))
        .where((server) => server != null)
        .cast<Server>()
        .toList();
  }

  // --- متدهای قبلی شما بدون تغییر ---
  Future<void> saveServers(List<Server> servers) async {
    final prefs = await SharedPreferences.getInstance();
    final List<String> serverConfigs = servers.map((s) => s.rawConfig).toList();
    await prefs.setStringList(_serversKey, serverConfigs);
  }

  Future<List<Server>> loadServers() async {
    final prefs = await SharedPreferences.getInstance();
    final List<String> serverConfigs = prefs.getStringList(_serversKey) ?? [];
    return serverConfigs
        .map((config) => Server.fromConfigString(config))
        .where((server) => server != null)
        .cast<Server>()
        .toList();
  }

  Future<void> saveLastUpdateTimestamp() async {
    final prefs = await SharedPreferences.getInstance();
    await prefs.setString(_lastUpdateKey, DateTime.now().toIso8601String());
  }

  Future<DateTime?> getLastUpdateTimestamp() async {
    final prefs = await SharedPreferences.getInstance();
    final timestampStr = prefs.getString(_lastUpdateKey);
    if (timestampStr == null) return null;
    return DateTime.parse(timestampStr);
  }
}
