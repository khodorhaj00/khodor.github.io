import 'dart:io';

import 'package:flutter/material.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:http/http.dart' as http;
import 'package:http/testing.dart';
import 'package:rhino_viewer/app/app_services.dart';
import 'package:rhino_viewer/app/theme.dart';
import 'package:rhino_viewer/core/models/recent_file.dart';
import 'package:rhino_viewer/core/services/backend_client.dart';
import 'package:rhino_viewer/core/services/cache_service.dart';
import 'package:rhino_viewer/core/services/file_service.dart';
import 'package:rhino_viewer/core/services/intent_service.dart';
import 'package:rhino_viewer/core/services/platform_error_monitor.dart';
import 'package:rhino_viewer/core/services/settings_service.dart';
import 'package:rhino_viewer/features/home/home_page.dart';

import 'support/fixtures.dart';
import 'support/memory_store.dart';
import 'support/settle.dart';

void main() {
  late Directory dir;
  late MemoryStore store;
  late AppServices services;
  late List<RecentFile> opened;
  ModelSource? nextPick;

  setUp(() async {
    dir = await Directory.systemTemp.createTemp('home_test');
    store = MemoryStore();
    final modelsDir = Directory('${dir.path}/models');
    services = AppServices(
      modelsDir: modelsDir,
      exportsDir: Directory('${dir.path}/exports'),
      files: FileService(modelsDir: modelsDir, picker: () async => nextPick),
      cache: CacheService(modelsDir: modelsDir, store: store),
      backend: BackendClient(
        client: MockClient((_) async => http.Response('{}', 200)),
      ),
      settings: SettingsService(store),
      intents: IntentService(),
      errors: PlatformErrorMonitor(),
    );
    opened = [];
    nextPick = null;
  });

  tearDown(() async {
    services.intents.dispose();
    await dir.delete(recursive: true);
  });

  Widget app() => MaterialApp(
    theme: buildAppTheme(),
    home: HomePage(
      services: services,
      onOpen: (_, entry) async => opened.add(entry),
    ),
  );

  Future<RecentFile> seedRecent(
    String sha,
    String name, {
    bool meshed = false,
  }) async {
    await File('${services.modelsDir.path}/$sha.3dm').create(recursive: true);
    final entry = await services.cache.recordOpen(
      sha: sha,
      name: name,
      size: 2048,
    );
    if (meshed) await services.cache.markMeshed(sha);
    return entry;
  }

  bool noSpinner() => find.byType(CircularProgressIndicator).evaluate().isEmpty;

  testWidgets('shows title, open button, hint and empty state', (tester) async {
    await tester.pumpWidget(app());
    await tester.pumpAndSettle();
    expect(find.text('Rhino Viewer'), findsOneWidget);
    expect(find.text('Open .3dm'), findsOneWidget);
    expect(
      find.textContaining('Also opens from Files, WhatsApp, Drive'),
      findsOneWidget,
    );
    expect(find.text('No recent files'), findsOneWidget);
    expect(find.byIcon(Icons.settings_outlined), findsOneWidget);
  });

  testWidgets('lists recents with size, MESHED badge, and opens on tap', (
    tester,
  ) async {
    await tester.runAsync(() async {
      await seedRecent('aaa', 'plain.3dm');
      await seedRecent('bbb', 'meshed.3dm', meshed: true);
    });
    await tester.pumpWidget(app());
    await tester.pumpAndSettle();

    expect(find.text('plain.3dm'), findsOneWidget);
    expect(find.text('meshed.3dm'), findsOneWidget);
    expect(find.text('MESHED'), findsOneWidget);
    expect(find.textContaining('2.0 KB'), findsNWidgets(2));
    expect(find.text('No recent files'), findsNothing);

    await tester.tap(find.text('plain.3dm'));
    await settle(tester, () => opened.isNotEmpty);
    await tester.pumpAndSettle();
    expect(opened.single.sha, 'aaa');
    final recents = await tester.runAsync(services.cache.recents);
    expect(recents!.first.sha, 'aaa', reason: 'opening moves it to the front');
  });

  testWidgets('a second tap while a recent is opening is ignored', (
    tester,
  ) async {
    await tester.runAsync(() => seedRecent('eee', 'twice.3dm'));
    await tester.pumpWidget(app());
    await tester.pumpAndSettle();
    await tester.tap(find.text('twice.3dm'));
    await tester.tap(find.text('twice.3dm'));
    await settle(tester, () => opened.isNotEmpty && noSpinner());
    await tester.pumpAndSettle();
    expect(opened, hasLength(1));
  });

  testWidgets('swipe hides the entry; the file goes once Undo expires', (
    tester,
  ) async {
    await tester.runAsync(() => seedRecent('ccc', 'gone.3dm'));
    await tester.pumpWidget(app());
    await tester.pumpAndSettle();
    await tester.drag(find.text('gone.3dm'), const Offset(-600, 0));
    await tester.pumpAndSettle();
    expect(find.text('gone.3dm'), findsNothing);
    expect(find.text('Removed gone.3dm'), findsOneWidget);
    expect(find.text('Undo'), findsOneWidget);
    expect(find.text('No recent files'), findsOneWidget);
    expect(
      File('${services.modelsDir.path}/ccc.3dm').existsSync(),
      isTrue,
      reason: 'nothing is deleted while Undo is still offered',
    );
    expect(store.data[CacheService.recentsKey], contains('ccc'));

    // Let the SnackBar time out.
    await tester.pump(const Duration(seconds: 6));
    await tester.pumpAndSettle();
    expect(find.text('Undo'), findsNothing);
    await settle(tester, () => store.data[CacheService.recentsKey] == '[]');
    await tester.pumpAndSettle();
    expect(find.text('No recent files'), findsOneWidget);
    expect(File('${services.modelsDir.path}/ccc.3dm').existsSync(), isFalse);
  });

  testWidgets('Undo after a swipe restores the entry and keeps the file', (
    tester,
  ) async {
    await tester.runAsync(() => seedRecent('fff', 'kept.3dm'));
    await tester.pumpWidget(app());
    await tester.pumpAndSettle();
    await tester.drag(find.text('kept.3dm'), const Offset(-600, 0));
    await tester.pumpAndSettle();
    expect(find.text('kept.3dm'), findsNothing);

    await tester.tap(find.text('Undo'));
    await tester.pumpAndSettle();
    expect(find.text('kept.3dm'), findsOneWidget);
    expect(find.text('No recent files'), findsNothing);
    await tester.pump(const Duration(seconds: 6));
    await tester.pumpAndSettle();
    expect(File('${services.modelsDir.path}/fff.3dm').existsSync(), isTrue);
    expect(store.data[CacheService.recentsKey], contains('fff'));

    await tester.tap(find.text('kept.3dm'));
    await settle(tester, () => opened.isNotEmpty);
    await tester.pumpAndSettle();
    expect(opened.single.sha, 'fff');
  });

  testWidgets('a stale recent whose file vanished is removed with a message', (
    tester,
  ) async {
    await tester.runAsync(() => seedRecent('ddd', 'stale.3dm'));
    File('${services.modelsDir.path}/ddd.3dm').deleteSync();
    await tester.pumpWidget(app());
    await tester.pumpAndSettle();
    await tester.tap(find.text('stale.3dm'));
    await settle(tester, () => find.byType(SnackBar).evaluate().isNotEmpty);
    await tester.pumpAndSettle();
    expect(opened, isEmpty);
    expect(find.text('stale.3dm is no longer cached'), findsOneWidget);
    expect(find.text('No recent files'), findsOneWidget);
  });

  testWidgets('Open .3dm imports a picked file and opens it', (tester) async {
    nextPick = ModelSource(
      name: 'picked.3dm',
      open: () => chunked(rhinoBytes('x'), 8),
    );
    await tester.pumpWidget(app());
    await tester.pumpAndSettle();
    await tester.tap(find.text('Open .3dm'));
    await settle(tester, () => opened.isNotEmpty && noSpinner());
    await tester.pumpAndSettle();
    expect(opened.single.name, 'picked.3dm');
    expect(find.text('picked.3dm'), findsOneWidget);
    expect(
      File('${services.modelsDir.path}/${opened.single.sha}.3dm').existsSync(),
      isTrue,
    );
  });

  testWidgets(
    'Open .3dm with a non-Rhino file shows an error and opens nothing',
    (tester) async {
      nextPick = ModelSource(
        name: 'photo.jpg',
        open: () => chunked(List.filled(64, 0xFF), 8),
      );
      await tester.pumpWidget(app());
      await tester.pumpAndSettle();
      await tester.tap(find.text('Open .3dm'));
      await settle(
        tester,
        () => find.byType(SnackBar).evaluate().isNotEmpty && noSpinner(),
      );
      await tester.pumpAndSettle();
      expect(opened, isEmpty);
      expect(find.text('photo.jpg is not a Rhino .3dm file'), findsOneWidget);
      expect(find.text('No recent files'), findsOneWidget);
    },
  );

  testWidgets('cancelling the picker is a no-op', (tester) async {
    await tester.pumpWidget(app());
    await tester.pumpAndSettle();
    await tester.tap(find.text('Open .3dm'));
    await tester.pumpAndSettle();
    expect(opened, isEmpty);
    expect(find.byType(SnackBar), findsNothing);
  });
}
