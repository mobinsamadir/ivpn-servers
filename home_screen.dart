import 'package:flutter/material.dart';
import 'package:http/http.dart' as http;
import 'dart:convert';
import 'dart:async';

import '../models/server_model.dart';
import '../services/ping_service.dart';
import '../services/storage_service.dart';
import '../services/speed_test_service.dart';
import '../widgets/server_list_item.dart';

class HomeScreen extends StatefulWidget {
  const HomeScreen({super.key});

  @override
  State<HomeScreen> createState() => _HomeScreenState();
}

class _HomeScreenState extends State<HomeScreen> {
  // متغیر جدید برای لیست اخیر
  List<Server> _recentServers = [];

  // بقیه متغیرها و سرویس ها مثل کد شما هستند
  bool _isLoading = true;
  bool _isConnected = false;
  Server? _connectedServer;
  List<Server> _servers = [];
  String _statusMessage = "Initializing...";
  Server? _manualSelectedServer;

  late final PingService _pingService;
  final StorageService _storageService = StorageService();
  final SpeedTestService _speedTestService = SpeedTestService();

  @override
  void initState() {
    super.initState();
    _pingService = PingService(
      onUpdate: (updatedServer) {
        if (mounted) {
          _servers.sort((a, b) => a.ping.compareTo(b.ping));
          setState(() {});
        }
      },
    );
    _initializeApp();
  }

  @override
  void dispose() {
    _pingService.dispose();
    super.dispose();
  }

  // تمام توابع منطقی شما که صحیح بودند، دست نخورده باقی مانده اند
  Future<void> _initializeApp() async {
    final localServers = await _storageService.loadServers();
    final recentServers = await _storageService.loadRecentServers();
    if (mounted) {
      setState(() {
        _servers = localServers;
        _recentServers = recentServers;
        _isLoading = false;
      });
      if (localServers.isNotEmpty) {
        _pingService.startPingingAllServers(localServers);
      }
    }
    final lastUpdate = await _storageService.getLastUpdateTimestamp();
    bool needsUpdate =
        localServers.isEmpty ||
        (lastUpdate == null ||
            DateTime.now().difference(lastUpdate).inHours >= 24);
    if (needsUpdate) {
      await _loadServersFromUrl();
    } else {
      if (mounted) setState(() => _statusMessage = "Servers are up to date.");
    }
  }

  Future<void> _loadServersFromUrl() async {
    if (mounted) setState(() => _isLoading = true);
    final url = Uri.parse(
      'https://raw.githubusercontent.com/mobinsamadir/ivpn-servers/main/servers.txt',
    );
    try {
      final response = await http.get(url).timeout(const Duration(seconds: 15));
      if (response.statusCode == 200) {
        final content = utf8.decode(response.bodyBytes);
        final lines = content.split('\n');
        final networkServers = lines
            .map((line) => Server.fromConfigString(line.trim()))
            .where((server) => server != null)
            .cast<Server>()
            .toList();
        if (networkServers.isNotEmpty) {
          _pingService.stopAllPinging();
          await _storageService.saveServers(networkServers);
          await _storageService.saveLastUpdateTimestamp();
          if (mounted) {
            setState(() {
              _servers = networkServers;
              _statusMessage = "Servers updated successfully!";
            });
            _pingService.startPingingAllServers(networkServers);
          }
        } else {
          if (mounted)
            setState(
              () => _statusMessage = "Network list is empty. Using local list.",
            );
        }
      }
    } catch (e) {
      if (mounted)
        setState(
          () => _statusMessage = "Error updating servers. Using local list.",
        );
      print("Error fetching servers: $e");
    } finally {
      if (mounted) setState(() => _isLoading = false);
    }
  }

  void _handleConnection() {
    setState(() {
      if (_isConnected) {
        _isConnected = false;
        if (_connectedServer != null) {
          _connectedServer!.isConnected = false;
          _pingService.pingSingleServer(_connectedServer!);
        }
        _connectedServer = null;
        _manualSelectedServer = null;
        _statusMessage = "Disconnected";
      } else {
        Server? targetServer;
        if (_manualSelectedServer != null) {
          targetServer = _manualSelectedServer;
        } else {
          final goodServers = _servers
              .where((s) => s.status == PingStatus.good)
              .toList();
          if (goodServers.isNotEmpty) {
            targetServer = goodServers.first;
          } else if (_servers.isNotEmpty) {
            targetServer = _servers.first;
          }
        }
        if (targetServer != null) {
          _isConnected = true;
          _connectedServer = targetServer;
          targetServer.isConnected = true;
          _statusMessage = "Connected to ${targetServer.name}";
          _pingService.pingSingleServer(targetServer);
          _addServerToRecents(targetServer);
        } else {
          _statusMessage = "No server selected or no good servers available.";
        }
      }
    });
  }

  void _addServerToRecents(Server server) {
    _recentServers.removeWhere((s) => s.id == server.id);
    _recentServers.insert(0, server);
    if (_recentServers.length > 5) {
      _recentServers = _recentServers.sublist(0, 5);
    }
    _storageService.saveRecentServers(_recentServers);
  }

  void _showAddServerDialog() {
    final TextEditingController controller = TextEditingController();
    showDialog(
      context: context,
      builder: (context) {
        return AlertDialog(
          title: const Text("Add Server Manually"),
          content: TextField(
            controller: controller,
            decoration: const InputDecoration(
              hintText: "Paste server config (vless://...)",
            ),
          ),
          actions: [
            TextButton(
              onPressed: () => Navigator.of(context).pop(),
              child: const Text("Cancel"),
            ),
            ElevatedButton(
              onPressed: () {
                final String config = controller.text.trim();
                if (config.isNotEmpty) {
                  final newServer = Server.fromConfigString(config);
                  if (newServer != null) {
                    setState(() {
                      _servers.insert(0, newServer);
                    });
                    _pingService.pingSingleServer(newServer);
                    Navigator.of(context).pop();
                  } else {
                    ScaffoldMessenger.of(context).showSnackBar(
                      const SnackBar(
                        content: Text("Invalid server config format!"),
                      ),
                    );
                  }
                }
              },
              child: const Text("Save"),
            ),
          ],
        );
      },
    );
  }

  void _handleSpeedTest(Server server) async {
    if (mounted) setState(() => server.isTestingSpeed = true);
    final speed = await _speedTestService.testDownloadSpeed();
    if (mounted) {
      setState(() {
        server.downloadSpeed = speed;
        server.isTestingSpeed = false;
        _servers.sort((a, b) => b.downloadSpeed.compareTo(a.downloadSpeed));
      });
    }
  }

  void _showCleanupDialog() {
    showDialog(
      context: context,
      builder: (context) {
        return AlertDialog(
          title: const Text('Cleanup Server List'),
          content: const Text(
            'This will permanently remove servers from your main list.',
          ),
          actions: <Widget>[
            TextButton(
              child: const Text('Remove Offline Servers'),
              onPressed: () {
                setState(
                  () => _servers.removeWhere((s) => s.status == PingStatus.bad),
                );
                _storageService.saveServers(_servers);
                Navigator.of(context).pop();
              },
            ),
            TextButton(
              child: const Text('Remove Slow Servers'),
              onPressed: () {
                setState(
                  () => _servers.removeWhere(
                    (s) =>
                        s.status == PingStatus.medium ||
                        s.status == PingStatus.bad,
                  ),
                );
                _storageService.saveServers(_servers);
                Navigator.of(context).pop();
              },
            ),
            TextButton(
              child: const Text('Cancel'),
              onPressed: () => Navigator.of(context).pop(),
            ),
          ],
        );
      },
    );
  }

  // =========================================================================
  //  THE BUILD METHOD IS NOW FIXED AND CORRECTLY STRUCTURED
  // =========================================================================
  @override
  Widget build(BuildContext context) {
    Server? bestServer;
    final goodServers = _servers
        .where((s) => s.status == PingStatus.good)
        .toList();
    if (goodServers.isNotEmpty) {
      bestServer = goodServers.first;
    } else if (_servers.isNotEmpty) {
      bestServer = _servers.first;
    }

    return Scaffold(
      appBar: AppBar(
        title: const Text("iVPN"),
        actions: [
          IconButton(
            icon: const Icon(Icons.filter_list_off),
            onPressed: _showCleanupDialog,
            tooltip: 'Cleanup Server List',
          ),
          IconButton(
            icon: const Icon(Icons.refresh),
            onPressed: _loadServersFromUrl,
          ),
        ],
      ),
      floatingActionButton: FloatingActionButton(
        onPressed: _showAddServerDialog,
        child: const Icon(Icons.add),
      ),
      body: SingleChildScrollView(
        child: Column(
          children: [
            const SizedBox(height: 40),
            GestureDetector(
              onTap: _handleConnection,
              child: Container(
                width: 150,
                height: 150,
                decoration: BoxDecoration(
                  color: _isConnected ? Colors.redAccent : Colors.green,
                  shape: BoxShape.circle,
                  boxShadow: [
                    BoxShadow(
                      color: _isConnected
                          ? Colors.red.withOpacity(0.4)
                          : Colors.green.withOpacity(0.4),
                      blurRadius: 15,
                      spreadRadius: 5,
                    ),
                  ],
                ),
                child: Center(
                  child: Text(
                    _isConnected ? "DISCONNECT" : "CONNECT",
                    style: const TextStyle(
                      color: Colors.white,
                      fontSize: 20,
                      fontWeight: FontWeight.bold,
                    ),
                  ),
                ),
              ),
            ),
            const SizedBox(height: 20),
            Padding(
              padding: const EdgeInsets.symmetric(horizontal: 16.0),
              child: Text(
                _statusMessage,
                textAlign: TextAlign.center,
                style: const TextStyle(
                  fontSize: 16,
                  fontWeight: FontWeight.w500,
                ),
              ),
            ),
            const SizedBox(height: 30),
            const Divider(indent: 20, endIndent: 20),

            // --- NEW: Recently Connected List ---
            if (_recentServers.isNotEmpty)
              Padding(
                padding: const EdgeInsets.symmetric(horizontal: 8.0),
                child: ExpansionTile(
                  leading: const Icon(Icons.history, color: Colors.blueAccent),
                  title: const Text(
                    "Recently Connected",
                    style: TextStyle(fontWeight: FontWeight.bold),
                  ),
                  initiallyExpanded: true,
                  children: _recentServers.map((server) {
                    return Dismissible(
                      key: Key(server.id),
                      direction: DismissDirection.endToStart,
                      background: Container(
                        color: Colors.red,
                        alignment: Alignment.centerRight,
                        padding: const EdgeInsets.symmetric(horizontal: 20),
                        child: const Icon(
                          Icons.delete_outline,
                          color: Colors.white,
                        ),
                      ),
                      onDismissed: (direction) {
                        setState(() {
                          _recentServers.remove(server);
                        });
                        _storageService.saveRecentServers(_recentServers);
                        ScaffoldMessenger.of(context).showSnackBar(
                          SnackBar(
                            content: Text(
                              '${server.name} removed from recents',
                            ),
                          ),
                        );
                      },
                      child: ServerListItem(
                        server: server,
                        isSelected: _manualSelectedServer == server,
                        onTap: () {
                          setState(() {
                            _manualSelectedServer = server;
                          });
                        },
                        onTestSpeed: () => _handleSpeedTest(server),
                      ),
                    );
                  }).toList(),
                ),
              ),

            // Main "Auto-Location" tile
            ListTile(
              leading: const Icon(Icons.auto_awesome, color: Colors.purple),
              title: const Text(
                "Auto-Location",
                style: TextStyle(fontWeight: FontWeight.bold),
              ),
              subtitle: const Text("Connect to the fastest server"),
              onTap: () {
                setState(() {
                  _manualSelectedServer = null;
                });
                _handleConnection();
              },
            ),

            // Main list of all other servers
            if (_isLoading && _servers.isEmpty)
              const Padding(
                padding: EdgeInsets.all(16.0),
                child: CircularProgressIndicator(),
              )
            else if (bestServer != null)
              Padding(
                padding: const EdgeInsets.symmetric(horizontal: 8.0),
                child: ExpansionTile(
                  leading: Icon(
                    Icons.public,
                    color: (_manualSelectedServer ?? bestServer).statusColor,
                  ),
                  title: Text(
                    _manualSelectedServer?.name ?? bestServer.name,
                    style: const TextStyle(fontWeight: FontWeight.bold),
                  ),
                  subtitle: Text(
                    _manualSelectedServer != null
                        ? "Manually Selected"
                        : "Best available server",
                  ),
                  children: [
                    ListView.builder(
                      shrinkWrap: true,
                      physics: const NeverScrollableScrollPhysics(),
                      itemCount: _servers.length,
                      itemBuilder: (context, index) {
                        final server = _servers[index];
                        return ServerListItem(
                          server: server,
                          isSelected: _manualSelectedServer == server,
                          onTap: () {
                            setState(() {
                              _manualSelectedServer = server;
                            });
                          },
                          onTestSpeed: () => _handleSpeedTest(server),
                        );
                      },
                    ),
                  ],
                ),
              ),
          ],
        ),
      ),
    );
  }
}
