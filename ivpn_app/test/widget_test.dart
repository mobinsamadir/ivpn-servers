import 'package:flutter/material.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:provider/provider.dart';
import 'package:ivpn_app/logic/vpn_provider.dart';
import 'package:ivpn_app/logic/vpn_service.dart';
import 'package:ivpn_app/logic/config_fetcher.dart';
import 'package:ivpn_app/screens/home_screen.dart';
import 'package:ivpn_app/screens/countdown_screen.dart';

class MockVpnService extends VpnService {
  @override
  Future<void> initialize() async {}

  @override
  Future<void> connect(String config) async {}

  @override
  Future<void> disconnect() async {}
}

class MockConfigFetcher extends ConfigFetcher {
  @override
  Future<List<String>> fetchUltraFast() async {
    return ["vless://mock"];
  }

  @override
  Future<List<String>> fetchRealDelay() async {
    return [];
  }
}

void main() {
  testWidgets('App starts and shows connect button', (WidgetTester tester) async {
    final mockService = MockVpnService();
    final mockFetcher = MockConfigFetcher();

    await tester.pumpWidget(
      ChangeNotifierProvider(
        create: (_) => VpnProvider(vpnService: mockService, configFetcher: mockFetcher),
        child: MaterialApp(
          home: const HomeScreen(),
        ),
      ),
    );

    await tester.pumpAndSettle();

    expect(find.text('iVPN'), findsOneWidget);
    expect(find.text('TAP TO CONNECT'), findsOneWidget);
  });

  testWidgets('Connect button triggers Countdown', (WidgetTester tester) async {
    final mockService = MockVpnService();
    final mockFetcher = MockConfigFetcher();

    await tester.pumpWidget(
      ChangeNotifierProvider(
        create: (_) => VpnProvider(vpnService: mockService, configFetcher: mockFetcher),
        child: MaterialApp(
          home: const HomeScreen(),
        ),
      ),
    );

    await tester.pumpAndSettle();

    await tester.tap(find.byType(GestureDetector));
    await tester.pump();
    await tester.pump(const Duration(milliseconds: 100));

    expect(find.byType(CountdownScreen), findsOneWidget);
    // expect(find.text('10'), findsOneWidget);

    // Pump enough time for StabilityGuard to fail/timeout and clear timers
    await tester.pump(const Duration(seconds: 5));
  });
}
