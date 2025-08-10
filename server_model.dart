import 'package:flutter/material.dart';

// An enum for better type safety
enum ServerType { personal, free, custom }

enum PingStatus { good, medium, bad, unknown }

class Server {
  final String rawConfig;
  final String id;
  final String name;
  final String ip;
  final int port;
  final ServerType type; // Using the enum now
  int ping;
  PingStatus status;
  bool isConnected;
  double downloadSpeed;
  bool isTestingSpeed;

  Server({
    required this.rawConfig,
    required this.id,
    required this.name,
    required this.ip,
    required this.port,
    required this.type, // Use enum
    this.ping = -1,
    this.status = PingStatus.unknown,
    this.isConnected = false,
    this.downloadSpeed = 0.0,
    this.isTestingSpeed = false,
  });

  static Server? fromConfigString(String config) {
    try {
      final uri = Uri.parse(config);
      String decodedFragment = Uri.decodeComponent(uri.fragment);

      // TODO: You need a way to determine the server type from your source.
      // For this example, we'll assume if the name contains "Personal", it's a personal server.
      ServerType type = ServerType.free; // Default to free
      if (decodedFragment.toLowerCase().contains('personal')) {
        type = ServerType.personal;
      }
      if (decodedFragment.toLowerCase().contains('custom')) {
        type = ServerType.custom;
      }

      return Server(
        rawConfig: config,
        id: uri.host + uri.port.toString(),
        name: decodedFragment.trim(),
        ip: uri.host,
        port: uri.port,
        type: type,
      );
    } catch (e) {
      print("Failed to parse server config: $config, Error: $e");
      return null;
    }
  }

  Color get statusColor {
    switch (status) {
      case PingStatus.good:
        return Colors.green;
      case PingStatus.medium:
        return Colors.orange;
      case PingStatus.bad:
        return Colors.red;
      default:
        return Colors.grey;
    }
  }
}
