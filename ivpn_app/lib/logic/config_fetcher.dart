import 'package:http/http.dart' as http;

class ConfigFetcher {
  static const String _repoOwner = 'mobinsamadir';
  static const String _repoName = 'ivpn-servers';
  static const String _branch = 'main';

  static const String _ultraFastUrl = 'https://raw.githubusercontent.com/$_repoOwner/$_repoName/$_branch/tested_configs/ultra_fast.txt';
  static const String _realDelayUrl = 'https://raw.githubusercontent.com/$_repoOwner/$_repoName/$_branch/real_delay_passed.txt';

  Future<List<String>> fetchUltraFast() async {
    try {
      final response = await http.get(Uri.parse(_ultraFastUrl));
      if (response.statusCode == 200) {
        return _parseContent(response.body);
      } else {
        print('Failed to fetch Ultra Fast: ${response.statusCode}');
      }
    } catch (e) {
      print('Error fetching Ultra Fast configs: $e');
    }
    return [];
  }

  Future<List<String>> fetchRealDelay() async {
    try {
      final response = await http.get(Uri.parse(_realDelayUrl));
      if (response.statusCode == 200) {
        return _parseContent(response.body);
      } else {
         print('Failed to fetch Real Delay: ${response.statusCode}');
      }
    } catch (e) {
      print('Error fetching Real Delay configs: $e');
    }
    return [];
  }

  List<String> _parseContent(String body) {
    return body
        .split('\n')
        .map((e) => e.trim())
        .where((e) => e.isNotEmpty && !e.startsWith('#'))
        .toList();
  }
}
