import 'dart:io';
import 'dart:ffi';
import 'package:ffi/ffi.dart';

class SystemProxyManager {
  // Constants for InternetSetOption
  static const int INTERNET_OPTION_SETTINGS_CHANGED = 39;
  static const int INTERNET_OPTION_REFRESH = 37;

  static void setSystemProxy(String host, int port) {
    if (!Platform.isWindows) return;

    try {
      // 1. Set Registry Keys via 'reg' command
      _runRegCommand('ProxyEnable', 'REG_DWORD', '1');
      _runRegCommand('ProxyServer', 'REG_SZ', '$host:$port');
      _runRegCommand('ProxyOverride', 'REG_SZ', '<local>');

      // 2. Notify System
      _notifySystem();
    } catch (e) {
      print('Failed to set system proxy: $e');
    }
  }

  static void clearSystemProxy() {
    if (!Platform.isWindows) return;

    try {
      _runRegCommand('ProxyEnable', 'REG_DWORD', '0');
      _notifySystem();
    } catch (e) {
      print('Failed to clear system proxy: $e');
    }
  }

  static void _runRegCommand(String valueName, String type, String data) {
    Process.runSync('reg', [
      'add',
      r'HKCU\Software\Microsoft\Windows\CurrentVersion\Internet Settings',
      '/v', valueName,
      '/t', type,
      '/d', data,
      '/f'
    ]);
  }

  static void _notifySystem() {
    try {
      final wininet = DynamicLibrary.open('wininet.dll');
      final InternetSetOption = wininet.lookupFunction<
          Int32 Function(IntPtr, Int32, Pointer<Void>, Int32),
          int Function(int, int, Pointer<Void>, int)>('InternetSetOptionW');

      InternetSetOption(0, INTERNET_OPTION_SETTINGS_CHANGED, nullptr, 0);
      InternetSetOption(0, INTERNET_OPTION_REFRESH, nullptr, 0);
    } catch (e) {
      print('Failed to notify system: $e');
    }
  }
}
