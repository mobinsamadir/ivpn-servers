import 'package:flutter/material.dart';
import '../models/server_model.dart';
import '../services/ping_service.dart';
import '../widgets/server_list_item.dart';

class SelectServerScreen extends StatefulWidget {
  final List<Server> allServers;
  final Server? currentSelectedServer;
  final PingService pingService;
  final Function(Server) onServerSelected;

  const SelectServerScreen({
    super.key,
    required this.allServers,
    required this.pingService,
    required this.onServerSelected,
    this.currentSelectedServer,
  });

  @override
  State<SelectServerScreen> createState() => _SelectServerScreenState();
}

class _SelectServerScreenState extends State<SelectServerScreen>
    with SingleTickerProviderStateMixin {
  late TabController _tabController;

  List<Server> personalGreenServers = [];
  List<Server> freeServers = [];
  List<Server> customServers = [];
  List<Server> obsoletePersonalServers = [];

  @override
  void initState() {
    super.initState();
    _tabController = TabController(length: 3, vsync: this);
    _filterAndGroupServers();
  }

  @override
  void didUpdateWidget(covariant SelectServerScreen oldWidget) {
    super.didUpdateWidget(oldWidget);
    // Re-filter if the server list has changed
    if (widget.allServers != oldWidget.allServers) {
      _filterAndGroupServers();
    }
  }

  void _filterAndGroupServers() {
    personalGreenServers = widget.allServers
        .where(
          (s) => s.type == ServerType.personal && s.status == PingStatus.good,
        )
        .toList();
    freeServers = widget.allServers
        .where((s) => s.type == ServerType.free)
        .toList();
    customServers = widget.allServers
        .where((s) => s.type == ServerType.custom)
        .toList();
    obsoletePersonalServers = widget.allServers
        .where(
          (s) => s.type == ServerType.personal && s.status != PingStatus.good,
        )
        .toList();
  }

  Widget _buildGroupTile(String title, List<Server> servers, IconData icon) {
    if (servers.isEmpty) return const SizedBox.shrink();

    return ExpansionTile(
      leading: Icon(icon),
      title: Text(title, style: const TextStyle(fontWeight: FontWeight.bold)),
      trailing: IconButton(
        icon: const Icon(Icons.refresh, size: 20),
        tooltip: 'Ping this group',
        onPressed: () {
          widget.pingService.pingServerGroup(servers);
          ScaffoldMessenger.of(context).showSnackBar(
            SnackBar(
              content: Text('Pinging $title...'),
              duration: const Duration(seconds: 1),
            ),
          );
        },
      ),
      children: servers.map((server) {
        return ServerListItem(
          server: server,
          isSelected: widget.currentSelectedServer == server,
          onTap: () {
            widget.onServerSelected(server);
            Navigator.of(context).pop();
          },
          onTestSpeed: () {
            /* TODO */
          },
        );
      }).toList(),
    );
  }

  @override
  Widget build(BuildContext context) {
    return Column(
      children: [
        Padding(
          padding: const EdgeInsets.symmetric(vertical: 12.0),
          child: Container(
            width: 40,
            height: 5,
            decoration: BoxDecoration(
              color: Colors.grey[400],
              borderRadius: BorderRadius.circular(10),
            ),
          ),
        ),
        TabBar(
          controller: _tabController,
          tabs: const [
            Tab(text: 'All'),
            Tab(text: 'Favorites'),
            Tab(text: 'Recent'),
          ],
        ),
        Expanded(
          child: TabBarView(
            controller: _tabController,
            children: [
              ListView(
                children: [
                  _buildGroupTile(
                    '⭐ Personal (Online)',
                    personalGreenServers,
                    Icons.person,
                  ),
                  _buildGroupTile('🌐 Free Servers', freeServers, Icons.public),
                  _buildGroupTile(
                    '🔧 Custom Servers',
                    customServers,
                    Icons.build,
                  ),
                  _buildGroupTile(
                    '⚠️ Obsolete Personal',
                    obsoletePersonalServers,
                    Icons.cloud_off,
                  ),
                ],
              ),
              const Center(child: Text('Favorites feature is coming soon!')),
              const Center(
                child: Text('Recent servers feature is coming soon!'),
              ),
            ],
          ),
        ),
      ],
    );
  }
}
