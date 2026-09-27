import 'package:rhino_viewer/core/services/key_value_store.dart';

class MemoryStore implements KeyValueStore {
  final Map<String, String> data = {};

  @override
  Future<String?> getString(String key) async => data[key];

  @override
  Future<void> setString(String key, String value) async => data[key] = value;

  @override
  Future<void> remove(String key) async => data.remove(key);
}
