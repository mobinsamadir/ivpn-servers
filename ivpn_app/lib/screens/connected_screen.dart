import 'package:flutter/material.dart';
import 'package:provider/provider.dart';
import 'package:ivpn_app/logic/vpn_provider.dart';

class ConnectedScreen extends StatelessWidget {
  const ConnectedScreen({Key? key}) : super(key: key);

  @override
  Widget build(BuildContext context) {
    return Scaffold(
      backgroundColor: const Color(0xFF0F172A), // Use theme color
      appBar: AppBar(
        title: const Text("iVPN Protected"),
        backgroundColor: Colors.transparent,
        elevation: 0,
        centerTitle: true,
      ),
      body: Center(
        child: Column(
          mainAxisAlignment: MainAxisAlignment.center,
          children: [
            Container(
              width: 200,
              height: 200,
              decoration: BoxDecoration(
                shape: BoxShape.circle,
                color: const Color(0xFF00E5FF).withOpacity(0.1),
                border: Border.all(
                  color: const Color(0xFF00E5FF),
                  width: 4,
                ),
                boxShadow: [
                  BoxShadow(
                    color: const Color(0xFF00E5FF).withOpacity(0.5),
                    blurRadius: 20,
                    spreadRadius: 5,
                  ),
                ],
              ),
              child: const Icon(
                Icons.shield,
                size: 80,
                color: Color(0xFF00E5FF),
              ),
            ),
            const SizedBox(height: 40),
            const Text(
              "CONNECTED",
              style: TextStyle(
                fontSize: 32,
                fontWeight: FontWeight.bold,
                color: Color(0xFF00E5FF),
                letterSpacing: 1.5,
              ),
            ),
            const SizedBox(height: 10),
            const Text(
              "Your traffic is encrypted and secure.",
              style: TextStyle(color: Colors.white60),
            ),
            const SizedBox(height: 60),
            ElevatedButton(
              onPressed: () {
                final provider = Provider.of<VpnProvider>(context, listen: false);
                provider.disconnect();
                Navigator.pop(context); // Return to Home
              },
              style: ElevatedButton.styleFrom(
                backgroundColor: const Color(0xFFFF5252),
                padding: const EdgeInsets.symmetric(horizontal: 50, vertical: 15),
                shape: RoundedRectangleBorder(
                  borderRadius: BorderRadius.circular(30),
                ),
              ),
              child: const Text(
                "DISCONNECT",
                style: TextStyle(
                  fontSize: 18,
                  fontWeight: FontWeight.bold,
                  color: Colors.white,
                ),
              ),
            ),
          ],
        ),
      ),
    );
  }
}
