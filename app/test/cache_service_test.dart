import 'dart:convert';
import 'dart:io';

import 'package:flutter_test/flutter_test.dart';
import 'package:rhino_viewer/core/services/cache_service.dart';

import 'support/memory_store.dart';

void main() {
  late Directory dir;
  late MemoryStore store;

  setUp(() async {
    dir = await Directory.systemTemp.createTemp('cache_test');
    store = MemoryStore();
  });

  tearDown(() async {
    if (await dir.exists()) await dir.delete(recursive: true);
  });

  Future<void> writeModel(String sha, int bytes, {bool meshed = false}) =>
      File('${dir.path}/$sha${meshed ? '.meshed' : ''}.3dm')
          .writeAsBytes(List.filled(bytes, 1));

  CacheService service({
    int maxEntries = 40,
    int cap = CacheService.defaultSizeCapBytes,
  }) => CacheService(
    modelsDir: dir,
    store: store,
    maxEntries: maxEntries,
    sizeCapBytes: cap,
  );

  test(
    'recordOpen inserts at the front and re-opening keeps addedAt',
    () async {
      final cache = service();
      final t1 = DateTime.utc(2026, 1, 1);
      final t2 = DateTime.utc(2026, 1, 2);
      final t3 = DateTime.utc(2026, 1, 3);
      await writeModel('a', 10);
      await writeModel('b', 10);
      await cache.recordOpen(sha: 'a', name: 'a.3dm', size: 10, now: t1);
      await cache.recordOpen(sha: 'b', name: 'b.3dm', size: 10, now: t2);
      expect((await cache.recents()).map((e) => e.sha), ['b', 'a']);

      await cache.recordOpen(sha: 'a', name: 'renamed.3dm', size: 10, now: t3);
      final recents = await cache.recents();
      expect(recents.map((e) => e.sha), ['a', 'b']);
      expect(recents.first.addedAt, t1);
      expect(recents.first.lastOpenedAt, t3);
      expect(
        recents.first.name,
        'a.3dm',
        reason: 'the first-seen name is kept',
      );
    },
  );

  test('evicts beyond maxEntries and deletes the evicted files', () async {
    final cache = service(maxEntries: 2);
    for (final sha in ['a', 'b', 'c']) {
      await writeModel(sha, 10);
      await writeModel(sha, 10, meshed: true);
      await cache.recordOpen(sha: sha, name: '$sha.3dm', size: 10);
    }
    expect((await cache.recents()).map((e) => e.sha), ['c', 'b']);
    expect(File('${dir.path}/a.3dm').existsSync(), isFalse);
    expect(File('${dir.path}/a.meshed.3dm').existsSync(), isFalse);
    expect(File('${dir.path}/b.3dm').existsSync(), isTrue);
  });

  test('size cap evicts least recently opened but never the newest', () async {
    final cache = service(cap: 250);
    await writeModel('a', 100);
    await writeModel('b', 100);
    await writeModel('c', 100);
    await cache.recordOpen(sha: 'a', name: 'a', size: 100);
    await cache.recordOpen(sha: 'b', name: 'b', size: 100);
    await cache.recordOpen(sha: 'c', name: 'c', size: 100);
    expect((await cache.recents()).map((e) => e.sha), ['c', 'b']);
    expect(File('${dir.path}/a.3dm').existsSync(), isFalse);

    await writeModel('huge', 1000);
    await cache.recordOpen(sha: 'huge', name: 'huge', size: 1000);
    expect((await cache.recents()).map((e) => e.sha), ['huge']);
    expect(File('${dir.path}/huge.3dm').existsSync(), isTrue);
  });

  test('lowering the cap and calling enforceLimits trims', () async {
    final cache = service();
    await writeModel('a', 100);
    await writeModel('b', 100);
    await cache.recordOpen(sha: 'a', name: 'a', size: 100);
    await cache.recordOpen(sha: 'b', name: 'b', size: 100);
    cache.sizeCapBytes = 150;
    await cache.enforceLimits();
    expect((await cache.recents()).map((e) => e.sha), ['b']);
  });

  test('markMeshed, remove, clear, diskUsage', () async {
    final cache = service();
    await writeModel('a', 40);
    await writeModel('a', 60, meshed: true);
    await cache.recordOpen(sha: 'a', name: 'a', size: 40);
    await cache.markMeshed('a');
    expect((await cache.recents()).single.meshed, isTrue);
    await cache.markMeshed('missing');
    expect(await cache.diskUsage(), 100);

    await cache.remove('a');
    expect(await cache.recents(), isEmpty);
    expect(dir.listSync(), isEmpty);

    await writeModel('z', 5);
    await cache.recordOpen(sha: 'z', name: 'z', size: 5);
    await cache.clear();
    expect(await cache.recents(), isEmpty);
    expect(dir.listSync(), isEmpty);
    expect(store.data.containsKey(CacheService.recentsKey), isFalse);
  });

  test('corrupt or foreign prefs content yields an empty list', () async {
    final cache = service();
    store.data[CacheService.recentsKey] = '{not json';
    expect(await cache.recents(), isEmpty);
    store.data[CacheService.recentsKey] = jsonEncode({'a': 1});
    expect(await cache.recents(), isEmpty);
    store.data[CacheService.recentsKey] = jsonEncode([
      {'sha': 'ok', 'name': 'n', 'size': 1, 'addedAt': 0, 'lastOpenedAt': 0},
      42,
    ]);
    expect((await cache.recents()).single.sha, 'ok');
  });

  test('notifies listeners on every change', () async {
    final cache = service();
    var notifications = 0;
    cache.addListener(() => notifications++);
    await writeModel('a', 1);
    await cache.recordOpen(sha: 'a', name: 'a', size: 1);
    await cache.markMeshed('a');
    await cache.remove('a');
    await cache.clear();
    expect(notifications, 4);
  });
}
