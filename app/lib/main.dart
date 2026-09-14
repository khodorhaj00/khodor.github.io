import 'dart:async';
import 'dart:io';

import 'package:flutter/material.dart';
import 'package:flutter/services.dart';
import 'package:http/http.dart' as http;
import 'package:path_provider/path_provider.dart';
import 'package:shared_preferences/shared_preferences.dart';

import 'app/app_services.dart';
import 'app/theme.dart';
import 'core/models/recent_file.dart';
import 'core/services/backend_client.dart';
import 'core/services/cache_service.dart';
import 'core/services/file_service.dart';
import 'core/services/intent_service.dart';
import 'core/services/key_value_store.dart';
import 'core/services/settings_service.dart';
import 'features/home/home_page.dart';
import 'features/viewer/viewer_page.dart';

Future<void> main() async {
  WidgetsFlutterBinding.ensureInitialized();
  final support = await getApplicationSupportDirectory();
  final temp = await getTemporaryDirectory();
  final modelsDir = Directory('${support.path}/models');
  await modelsDir.create(recursive: true);
  final store = SharedPreferencesStore(SharedPreferencesAsync());
  final settings = SettingsService(store);
  await settings.load();
  runApp(
    RhinoViewerApp(
      services: AppServices(
        modelsDir: modelsDir,
        exportsDir: Directory('${temp.path}/exports'),
        files: FileService(modelsDir: modelsDir),
        cache: CacheService(
          modelsDir: modelsDir,
          store: store,
          sizeCapBytes: settings.value.cacheCapBytes,
        ),
        backend: BackendClient(client: http.Client()),
        settings: settings,
        intents: IntentService(),
      ),
    ),
  );
}

class RhinoViewerApp extends StatefulWidget {
  const RhinoViewerApp({super.key, required this.services});

  final AppServices services;

  @override
  State<RhinoViewerApp> createState() => _RhinoViewerAppState();
}

class _RhinoViewerAppState extends State<RhinoViewerApp> {
  final GlobalKey<NavigatorState> _navigator = GlobalKey();
  final GlobalKey<ScaffoldMessengerState> _messenger = GlobalKey();
  StreamSubscription<String>? _intentSubscription;

  @override
  void initState() {
    super.initState();
    _intentSubscription = widget.services.intents.incomingFiles.listen(
      _openIncoming,
    );
    _openInitialFile();
  }

  @override
  void dispose() {
    _intentSubscription?.cancel();
    super.dispose();
  }

  Future<void> _openInitialFile() async {
    try {
      final path = await widget.services.intents.getInitialFile();
      if (path != null) await _openIncoming(path);
    } on MissingPluginException {
      // Not running inside the Android host (e.g. tests): no intents.
    }
  }

  /// Imports a file Kotlin copied to the cache dir, then removes that copy.
  Future<void> _openIncoming(String path) async {
    final file = File(path);
    try {
      final imported = await widget.services.files.importFile(file);
      final entry = await widget.services.cache.recordOpen(
        sha: imported.sha,
        name: imported.name,
        size: imported.size,
      );
      _navigator.currentState?.pushAndRemoveUntil(
        _viewerRoute(entry),
        (route) => route.isFirst,
      );
    } on InvalidModelFileException catch (e) {
      _snack(e.message);
    } on IOException catch (e) {
      _snack('Could not open file: $e');
    } finally {
      await IntentService.discardIncoming(path);
    }
  }

  Future<void> _openEntry(BuildContext context, RecentFile entry) =>
      Navigator.of(context).push(_viewerRoute(entry));

  MaterialPageRoute<void> _viewerRoute(RecentFile entry) => MaterialPageRoute(
    builder: (_) => ViewerPage(services: widget.services, entry: entry),
  );

  void _snack(String message) =>
      _messenger.currentState?.showSnackBar(SnackBar(content: Text(message)));

  @override
  Widget build(BuildContext context) {
    return MaterialApp(
      title: 'Rhino Viewer',
      theme: buildAppTheme(),
      navigatorKey: _navigator,
      scaffoldMessengerKey: _messenger,
      home: HomePage(services: widget.services, onOpen: _openEntry),
    );
  }
}
