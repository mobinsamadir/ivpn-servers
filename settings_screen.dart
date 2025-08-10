import 'package:flutter/material.dart';
import 'package:provider/provider.dart';
import '../main.dart'; // برای دسترسی به ThemeProvider

class SettingsScreen extends StatelessWidget {
  const SettingsScreen({super.key});

  @override
  Widget build(BuildContext context) {
    final themeProvider = Provider.of<ThemeProvider>(context);

    return Scaffold(
      appBar: AppBar(title: const Text('Settings')),
      body: ListView(
        children: [
          const ListTile(
            leading: Icon(Icons.person_outline),
            title: Text('Account'),
            subtitle: Text('mobinsr2001@gmail.com'),
          ),
          const Divider(),
          ListTile(
            leading: const Icon(Icons.palette_outlined),
            title: const Text('Theme'),
            trailing: DropdownButton<ThemeMode>(
              value: themeProvider.themeMode,
              items: const [
                DropdownMenuItem(
                  value: ThemeMode.system,
                  child: Text('System Default'),
                ),
                DropdownMenuItem(value: ThemeMode.light, child: Text('Light')),
                DropdownMenuItem(value: ThemeMode.dark, child: Text('Dark')),
              ],
              onChanged: (mode) {
                if (mode != null) {
                  themeProvider.setThemeMode(mode);
                }
              },
            ),
          ),
          const ListTile(
            leading: Icon(Icons.language_outlined),
            title: Text('Language'),
            trailing: Text('English'),
          ),
          const Divider(),
          const ListTile(
            leading: Icon(Icons.description_outlined),
            title: Text('Terms of Service'),
            trailing: Icon(Icons.arrow_forward_ios, size: 16),
          ),
          const ListTile(
            leading: Icon(Icons.privacy_tip_outlined),
            title: Text('Privacy Policy'),
            trailing: Icon(Icons.arrow_forward_ios, size: 16),
          ),
          const ListTile(
            leading: Icon(Icons.info_outline),
            title: Text('Version'),
            trailing: Text('1.0.0'),
          ),
        ],
      ),
    );
  }
}
