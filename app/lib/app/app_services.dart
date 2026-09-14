import 'dart:io';

import '../core/services/backend_client.dart';
import '../core/services/cache_service.dart';
import '../core/services/file_service.dart';
import '../core/services/intent_service.dart';
import '../core/services/settings_service.dart';

/// Everything the screens need, wired once in `main()` with plain
/// constructors so tests can substitute any piece.
class AppServices {
  const AppServices({
    required this.modelsDir,
    required this.exportsDir,
    required this.files,
    required this.cache,
    required this.backend,
    required this.settings,
    required this.intents,
  });

  /// `<application support>/models/` — served to the viewer as `/files/`.
  final Directory modelsDir;

  /// Scratch directory for exported `.glb` files handed to the share sheet.
  final Directory exportsDir;
  final FileService files;
  final CacheService cache;
  final BackendClient backend;
  final SettingsService settings;
  final IntentService intents;
}
