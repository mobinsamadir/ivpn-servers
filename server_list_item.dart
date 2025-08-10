import 'package:flutter/material.dart';
import '../models/server_model.dart';

class ServerListItem extends StatelessWidget {
  final Server server;
  final bool isSelected; // <--- برای تشخیص اینکه آیا این آیتم انتخاب شده
  final VoidCallback onTap; // <--- برای مدیریت تپ کردن روی آیتم
  final VoidCallback onTestSpeed;

  const ServerListItem({
    super.key,
    required this.server,
    required this.isSelected,
    required this.onTap,
    required this.onTestSpeed,
  });

  @override
  Widget build(BuildContext context) {
    return ListTile(
      onTap: onTap, // <--- اتصال تابع تپ
      tileColor: isSelected
          ? Colors.green.withOpacity(0.2)
          : null, // <--- تغییر رنگ پس زمینه در صورت انتخاب
      leading: Icon(Icons.public, color: server.statusColor),
      title: Text(server.name),
      subtitle: server.downloadSpeed > 0
          ? Text(
              "Speed: ${server.downloadSpeed.toStringAsFixed(2)} Mbps",
              style: TextStyle(color: Colors.blue[700]),
            )
          : null,
      trailing: Row(
        mainAxisSize: MainAxisSize.min,
        children: [
          Text(
            server.ping == -1 ? "N/A" : "${server.ping} ms",
            style: TextStyle(color: server.statusColor),
          ),
          const SizedBox(width: 8),
          server.isTestingSpeed
              ? const SizedBox(
                  width: 24,
                  height: 24,
                  child: CircularProgressIndicator(strokeWidth: 2.0),
                )
              : IconButton(
                  icon: const Icon(Icons.speed),
                  onPressed: onTestSpeed,
                  tooltip: 'Test Download Speed',
                ),
        ],
      ),
    );
  }
}
