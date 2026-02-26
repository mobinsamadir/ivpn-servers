import 'package:flutter/material.dart';
import 'package:provider/provider.dart';
import 'package:ivpn_app/logic/vpn_provider.dart';
import 'countdown_screen.dart';

class HomeScreen extends StatelessWidget {
  const HomeScreen({Key? key}) : super(key: key);

  @override
  Widget build(BuildContext context) {
    return Scaffold(
      backgroundColor: const Color(0xFF0F172A),
      body: Consumer<VpnProvider>(
        builder: (context, provider, child) {
          // Check pre-flight issues
          if (provider.preFlightIssues.isNotEmpty) {
            return Center(
              child: Column(
                mainAxisAlignment: MainAxisAlignment.center,
                children: [
                  const Icon(Icons.error_outline, size: 80, color: Colors.red),
                  const SizedBox(height: 20),
                  const Text("Startup Issues Detected", style: TextStyle(color: Colors.white, fontSize: 24)),
                  const SizedBox(height: 10),
                  ...provider.preFlightIssues.map((e) => Text(e, style: const TextStyle(color: Colors.white70))),
                  const SizedBox(height: 30),
                  ElevatedButton(
                    onPressed: () {
                        // Retry logic? For now just exit or manual retry if implemented
                    },
                    child: const Text("Exit"),
                  )
                ],
              ),
            );
          }

          return Center(
            child: Column(
              mainAxisAlignment: MainAxisAlignment.center,
              children: [
                const Text(
                  "iVPN",
                  style: TextStyle(
                    fontSize: 48,
                    fontWeight: FontWeight.bold,
                    color: Color(0xFF00E5FF),
                    letterSpacing: 2.0,
                  ),
                ),
                const SizedBox(height: 10),
                const Text(
                  "SECURE . FAST . ANONYMOUS",
                  style: TextStyle(
                    color: Colors.white54,
                    letterSpacing: 1.5,
                    fontSize: 12,
                  ),
                ),
                const SizedBox(height: 60),
                GestureDetector(
                  onTap: () {
                    if (provider.state == VpnState.disconnected || provider.state == VpnState.error) {
                      provider.connect();
                      Navigator.push(context, MaterialPageRoute(builder: (_) => const CountdownScreen()));
                    }
                  },
                  child: Container(
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
                          color: const Color(0xFF00E5FF).withOpacity(0.3),
                          blurRadius: 20,
                          spreadRadius: 5,
                        ),
                      ],
                    ),
                    child: Center(
                      child: provider.state == VpnState.connecting
                          ? const CircularProgressIndicator(color: Color(0xFF00E5FF))
                          : const Icon(
                              Icons.power_settings_new,
                              size: 80,
                              color: Color(0xFF00E5FF),
                            ),
                    ),
                  ),
                ),
                const SizedBox(height: 40),
                Text(
                  provider.state == VpnState.connecting ? "CONNECTING..." : "TAP TO CONNECT",
                  style: const TextStyle(
                    color: Colors.white70,
                    fontSize: 18,
                    fontWeight: FontWeight.bold,
                    letterSpacing: 1.2,
                  ),
                ),
                if (provider.errorMessage != null)
                    Padding(
                        padding: const EdgeInsets.only(top: 20),
                        child: Text(
                            provider.errorMessage!,
                            style: const TextStyle(color: Colors.red),
                            textAlign: TextAlign.center,
                        ),
                    ),
              ],
            ),
          );
        },
      ),
    );
  }
}
