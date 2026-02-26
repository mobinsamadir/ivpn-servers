import 'dart:async';
import 'package:flutter/material.dart';
import 'package:provider/provider.dart';
import 'package:ivpn_app/logic/vpn_provider.dart';
import 'connected_screen.dart';

class CountdownScreen extends StatefulWidget {
  const CountdownScreen({Key? key}) : super(key: key);

  @override
  State<CountdownScreen> createState() => _CountdownScreenState();
}

class _CountdownScreenState extends State<CountdownScreen> {
  int _seconds = 10;
  Timer? _timer;

  @override
  void initState() {
    super.initState();
    _startTimer();
  }

  void _startTimer() {
    _timer = Timer.periodic(const Duration(seconds: 1), (timer) {
      if (_seconds > 0) {
        setState(() {
          _seconds--;
        });
      } else {
        _timer?.cancel();
        _transitionIfReady();
      }
    });
  }

  void _transitionIfReady() {
    final provider = Provider.of<VpnProvider>(context, listen: false);
    if (provider.state == VpnState.connected) {
      Navigator.pushReplacement(context, MaterialPageRoute(builder: (_) => const ConnectedScreen()));
    } else if (provider.state == VpnState.error) {
       Navigator.pop(context);
       ScaffoldMessenger.of(context).showSnackBar(SnackBar(content: Text(provider.errorMessage ?? "Error")));
    } else {
       // Still connecting, wait a bit
       Future.delayed(const Duration(seconds: 1), _transitionIfReady);
    }
  }

  @override
  void dispose() {
    _timer?.cancel();
    super.dispose();
  }

  @override
  Widget build(BuildContext context) {
    // Listen to provider state to handle early errors
    final provider = context.watch<VpnProvider>();

    if (provider.state == VpnState.error) {
       // Stop timer and go back
       _timer?.cancel();
       // Use addPostFrameCallback to pop safely during build
       WidgetsBinding.instance.addPostFrameCallback((_) {
         if (mounted) {
            Navigator.pop(context);
            ScaffoldMessenger.of(context).showSnackBar(SnackBar(content: Text(provider.errorMessage ?? "Error")));
         }
       });
    }

    return Scaffold(
      backgroundColor: Theme.of(context).scaffoldBackgroundColor,
      body: Center(
        child: Column(
          mainAxisAlignment: MainAxisAlignment.center,
          children: [
            const Text(
              "iVPN",
              style: TextStyle(
                fontSize: 48,
                fontWeight: FontWeight.bold,
                color: Colors.white,
                letterSpacing: 2.0,
              ),
            ),
            const SizedBox(height: 40),
            Stack(
              alignment: Alignment.center,
              children: [
                SizedBox(
                  width: 150,
                  height: 150,
                  child: CircularProgressIndicator(
                    value: 1 - (_seconds / 10),
                    strokeWidth: 8,
                    valueColor: AlwaysStoppedAnimation<Color>(Theme.of(context).primaryColor),
                    backgroundColor: Colors.white10,
                  ),
                ),
                Text(
                  "$_seconds",
                  style: TextStyle(
                    fontSize: 48,
                    fontWeight: FontWeight.bold,
                    color: Theme.of(context).primaryColor,
                  ),
                ),
              ],
            ),
            const SizedBox(height: 20),
            const Text(
              "Securing your connection...",
              style: TextStyle(color: Colors.white60),
            ),
          ],
        ),
      ),
    );
  }
}
