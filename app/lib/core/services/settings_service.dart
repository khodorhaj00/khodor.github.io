import 'dart:convert';

import 'package:flutter/foundation.dart';

import 'backend_client.dart';
import 'key_value_store.dart';

class AppSettings {
  const AppSettings({
    this.backendUrl = '',
    this.apiKey = '',
    this.meshQuality = MeshQuality.standard,
    this.cacheCapMb = 1024,
  });

  factory AppSettings.fromJson(Map<String, dynamic> json) => AppSettings(
    backendUrl: '${json['backendUrl'] ?? ''}',
    apiKey: '${json['apiKey'] ?? ''}',
    meshQuality: MeshQuality.fromWire('${json['meshQuality'] ?? 'default'}'),
    cacheCapMb: json['cacheCapMb'] is int ? json['cacheCapMb'] as int : 1024,
  );

  static const List<int> cacheCapChoicesMb = [256, 512, 1024, 2048, 4096];

  final String backendUrl;
  final String apiKey;
  final MeshQuality meshQuality;
  final int cacheCapMb;

  bool get hasBackend => backendUrl.trim().isNotEmpty;

  int get cacheCapBytes => cacheCapMb * 1024 * 1024;

  Map<String, dynamic> toJson() => {
    'backendUrl': backendUrl,
    'apiKey': apiKey,
    'meshQuality': meshQuality.wireName,
    'cacheCapMb': cacheCapMb,
  };

  AppSettings copyWith({
    String? backendUrl,
    String? apiKey,
    MeshQuality? meshQuality,
    int? cacheCapMb,
  }) => AppSettings(
    backendUrl: backendUrl ?? this.backendUrl,
    apiKey: apiKey ?? this.apiKey,
    meshQuality: meshQuality ?? this.meshQuality,
    cacheCapMb: cacheCapMb ?? this.cacheCapMb,
  );
}

/// Persists [AppSettings] as one JSON document and exposes them as a
/// [ValueListenable] so screens rebuild when they change.
class SettingsService {
  SettingsService(this._store);

  static const String key = 'settings_v1';

  final KeyValueStore _store;
  final ValueNotifier<AppSettings> _notifier = ValueNotifier(
    const AppSettings(),
  );

  ValueListenable<AppSettings> get listenable => _notifier;

  AppSettings get value => _notifier.value;

  Future<void> load() async {
    final raw = await _store.getString(key);
    if (raw == null) return;
    try {
      final decoded = jsonDecode(raw);
      if (decoded is Map) {
        _notifier.value = AppSettings.fromJson(
          Map<String, dynamic>.from(decoded),
        );
      }
    } on FormatException {
      // Corrupt settings: keep defaults; the next save overwrites them.
    }
  }

  Future<void> update(AppSettings settings) async {
    _notifier.value = settings;
    await _store.setString(key, jsonEncode(settings.toJson()));
  }
}
