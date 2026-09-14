import 'dart:convert';
import 'dart:io';

import 'package:flutter/material.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:http/http.dart' as http;
import 'package:http/testing.dart';
import 'package:rhino_viewer/app/app_services.dart';
import 'package:rhino_viewer/app/theme.dart';
import 'package:rhino_viewer/core/services/backend_client.dart';
import 'package:rhino_viewer/core/services/cache_service.dart';
import 'package:rhino_viewer/core/services/file_service.dart';
import 'package:rhino_viewer/core/services/intent_service.dart';
import 'package:rhino_viewer/core/services/settings_service.dart';
import 'package:rhino_viewer/features/settings/settings_page.dart';

import 'support/memory_store.dart';
import 'support/settle.dart';

void main() {
  late Directory dir;
  late MemoryStore store;
  late AppServices services;
  late http.Request? lastRequest;
  late http.Response Function(http.Request) respond;

  setUp(() async {
    dir = await Directory.systemTemp.createTemp('settings_test');
    store = MemoryStore();
    lastRequest = null;
    respond = (_) => http.Response('{}', 200);
    final modelsDir = Directory('${dir.path}/models');
    services = AppServices(
      modelsDir: modelsDir,
      exportsDir: Directory('${dir.path}/exports'),
      files: FileService(modelsDir: modelsDir, picker: () async => null),
      cache: CacheService(modelsDir: modelsDir, store: store),
      backend: BackendClient(
        client: MockClient((request) async {
          lastRequest = request;
          return respond(request);
        }),
      ),
      settings: SettingsService(store),
      intents: IntentService(),
    );
  });

  tearDown(() async {
    services.intents.dispose();
    await dir.delete(recursive: true);
  });

  Widget app() => MaterialApp(
    theme: buildAppTheme(),
    home: SettingsPage(services: services),
  );

  Future<void> pumpPage(WidgetTester tester) async {
    await tester.pumpWidget(app());
    await settle(
      tester,
      () => find.textContaining('used').evaluate().isNotEmpty,
    );
    await tester.pumpAndSettle();
  }

  testWidgets('persists URL, API key and mesh quality', (tester) async {
    await pumpPage(tester);
    await tester.enterText(
      find.widgetWithText(TextField, 'Backend URL'),
      'http://192.168.1.10:8080 ',
    );
    await tester.enterText(find.widgetWithText(TextField, 'API key'), 'secret');
    await tester.tap(find.text('Fine'));
    await tester.pumpAndSettle();

    final settings = services.settings.value;
    expect(settings.backendUrl, 'http://192.168.1.10:8080');
    expect(settings.apiKey, 'secret');
    expect(settings.meshQuality, MeshQuality.fine);
    expect(settings.hasBackend, isTrue);
    final persisted = jsonDecode(store.data[SettingsService.key]!) as Map;
    expect(persisted['meshQuality'], 'fine');
    expect(persisted['backendUrl'], 'http://192.168.1.10:8080');

    final key = tester.widget<TextField>(
      find.widgetWithText(TextField, 'API key'),
    );
    expect(key.obscureText, isTrue);
    await tester.tap(find.byIcon(Icons.visibility_outlined));
    await tester.pump();
    expect(
      tester
          .widget<TextField>(find.widgetWithText(TextField, 'API key'))
          .obscureText,
      isFalse,
    );
  });

  testWidgets('Test connection summarises /health and sends the key', (
    tester,
  ) async {
    await services.settings.update(
      const AppSettings(backendUrl: 'http://srv:8080/', apiKey: 'k1'),
    );
    respond = (_) => http.Response(
      jsonEncode({
        'ok': true,
        'version': '1.2.3',
        'uptimeSec': 5,
        'compute': {
          'url': 'http://win:5000/',
          'configured': true,
          'reachable': true,
        },
      }),
      200,
    );
    await pumpPage(tester);
    await tester.tap(find.text('Test connection'));
    await tester.pumpAndSettle();
    expect(find.text('OK · v1.2.3 · Compute reachable'), findsOneWidget);
    expect(lastRequest!.url.toString(), 'http://srv:8080/health');
    expect(lastRequest!.headers['X-Api-Key'], 'k1');

    respond = (_) => http.Response(
      jsonEncode({'error': 'unauthorized', 'detail': 'bad key'}),
      401,
    );
    await tester.tap(find.text('Test connection'));
    await tester.pumpAndSettle();
    expect(find.text('Failed: HTTP 401 unauthorized: bad key'), findsOneWidget);
  });

  testWidgets(
    'Test connection always shows a result for unclassified failures',
    (tester) async {
      await services.settings.update(
        const AppSettings(backendUrl: 'http://srv:8080'),
      );
      respond = (_) => http.Response('<html>landing page</html>', 200);
      await pumpPage(tester);
      await tester.tap(find.text('Test connection'));
      await tester.pumpAndSettle();
      expect(
        find.text(
          'Failed: HTTP 200 bad_response: Health response is not JSON (not the appserver?)',
        ),
        findsOneWidget,
      );

      await tester.enterText(
        find.widgetWithText(TextField, 'Backend URL'),
        'http://192.168.1.10:abc',
      );
      await tester.tap(find.text('Test connection'));
      await tester.pumpAndSettle();
      expect(
        find.textContaining('Failed: bad_url: Invalid port'),
        findsOneWidget,
      );
      expect(find.text('Test connection'), findsOneWidget);
    },
  );

  testWidgets('Test connection without a URL asks for one', (tester) async {
    await pumpPage(tester);
    await tester.tap(find.text('Test connection'));
    await tester.pumpAndSettle();
    expect(find.text('Enter a server URL first'), findsOneWidget);
    expect(lastRequest, isNull);
  });

  testWidgets('cache cap is persisted and Clear cache empties the models dir', (
    tester,
  ) async {
    await tester.runAsync(() async {
      await File('${services.modelsDir.path}/abc.3dm').create(recursive: true);
      await File('${services.modelsDir.path}/abc.3dm')
          .writeAsBytes(List.filled(2048, 0));
      await services.cache.recordOpen(sha: 'abc', name: 'a.3dm', size: 2048);
    });
    await pumpPage(tester);
    expect(find.text('2.0 KB used'), findsOneWidget);

    await tester.tap(find.text('256 MB'));
    await settle(tester, () => services.settings.value.cacheCapMb == 256);
    await tester.pumpAndSettle();
    expect(services.cache.sizeCapBytes, 256 * 1024 * 1024);

    await tester.tap(find.text('Clear cache'));
    await tester.pumpAndSettle();
    expect(find.text('Clear cache?'), findsOneWidget);
    await tester.tap(find.text('Clear'));
    await settle(tester, () => find.text('0 B used').evaluate().isNotEmpty);
    await tester.pumpAndSettle();
    expect(File('${services.modelsDir.path}/abc.3dm').existsSync(), isFalse);
    expect(store.data.containsKey(CacheService.recentsKey), isFalse);
  });
}
