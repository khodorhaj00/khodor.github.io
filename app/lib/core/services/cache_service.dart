import 'dart:convert';
import 'dart:io';

import 'package:flutter/foundation.dart';

import '../models/recent_file.dart';
import 'key_value_store.dart';

/// Recents list + LRU eviction of model files (ARCHITECTURE.md §3.2).
/// Notifies listeners whenever the recents list changes.
class CacheService extends ChangeNotifier {
  CacheService({
    required this.modelsDir,
    required this._store,
    this.maxEntries = 40,
    this.sizeCapBytes = defaultSizeCapBytes,
  });

  static const String recentsKey = 'recents_v1';
  static const int defaultSizeCapBytes = 1 << 30;

  final Directory modelsDir;
  final KeyValueStore _store;
  final int maxEntries;

  /// Upper bound for the bytes kept in [modelsDir]; the most recently opened
  /// file is never evicted even when it alone exceeds the cap.
  int sizeCapBytes;

  Future<List<RecentFile>> recents() async {
    final raw = await _store.getString(recentsKey);
    if (raw == null || raw.isEmpty) return const [];
    final Object? decoded;
    try {
      decoded = jsonDecode(raw);
    } on FormatException {
      return const [];
    }
    if (decoded is! List) return const [];
    return [
      for (final item in decoded)
        if (item is Map) RecentFile.fromJson(Map<String, dynamic>.from(item)),
    ];
  }

  /// Moves (or inserts) the entry for [sha] to the front, then applies the
  /// entry and size limits. Returns the stored entry.
  Future<RecentFile> recordOpen({
    required String sha,
    required String name,
    required int size,
    DateTime? now,
  }) async {
    final at = now ?? DateTime.now().toUtc();
    final entries = await recents();
    final existing = entries.where((e) => e.sha == sha).firstOrNull;
    final entry =
        existing?.copyWith(lastOpenedAt: at) ??
        RecentFile(
          sha: sha,
          name: name,
          size: size,
          addedAt: at,
          lastOpenedAt: at,
        );
    final reordered = [entry, ...entries.where((e) => e.sha != sha)];
    await _save(await _enforceLimits(reordered));
    return entry;
  }

  Future<void> markMeshed(String sha, {bool meshed = true}) async {
    final entries = await recents();
    if (!entries.any((e) => e.sha == sha)) return;
    await _save([
      for (final e in entries) e.sha == sha ? e.copyWith(meshed: meshed) : e,
    ]);
  }

  Future<void> remove(String sha) async {
    final entries = await recents();
    await _deleteFiles(sha);
    await _save(entries.where((e) => e.sha != sha).toList());
  }

  /// Deletes every cached model file and the recents list.
  Future<void> clear() async {
    if (await modelsDir.exists()) {
      await for (final entity in modelsDir.list()) {
        if (entity is File) await entity.delete();
      }
    }
    await _store.remove(recentsKey);
    notifyListeners();
  }

  /// Bytes currently used by [modelsDir].
  Future<int> diskUsage() async {
    if (!await modelsDir.exists()) return 0;
    var total = 0;
    await for (final entity in modelsDir.list()) {
      if (entity is File) total += await entity.length();
    }
    return total;
  }

  /// Re-applies the limits (e.g. after the size cap was lowered in settings).
  Future<void> enforceLimits() async =>
      _save(await _enforceLimits(await recents()));

  Future<List<RecentFile>> _enforceLimits(List<RecentFile> ordered) async {
    final kept = <RecentFile>[];
    var used = 0;
    for (final entry in ordered) {
      final bytes = await _bytesOnDisk(entry.sha);
      final overCount = kept.length >= maxEntries;
      final overSize = kept.isNotEmpty && used + bytes > sizeCapBytes;
      if (overCount || overSize) {
        await _deleteFiles(entry.sha);
        continue;
      }
      kept.add(entry);
      used += bytes;
    }
    return kept;
  }

  Future<int> _bytesOnDisk(String sha) async {
    var total = 0;
    for (final file in _filesOf(sha)) {
      if (await file.exists()) total += await file.length();
    }
    return total;
  }

  Future<void> _deleteFiles(String sha) async {
    for (final file in _filesOf(sha)) {
      if (await file.exists()) await file.delete();
    }
  }

  List<File> _filesOf(String sha) => [
    File('${modelsDir.path}/$sha.3dm'),
    File('${modelsDir.path}/$sha.meshed.3dm'),
  ];

  Future<void> _save(List<RecentFile> entries) async {
    await _store.setString(
      recentsKey,
      jsonEncode([for (final e in entries) e.toJson()]),
    );
    notifyListeners();
  }
}
