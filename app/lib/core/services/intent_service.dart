import 'dart:async';
import 'dart:io';

import 'package:flutter/services.dart';

/// Dart side of `MethodChannel('com.styro3d.rhino_viewer/intent')`
/// (ARCHITECTURE.md §3.3). Kotlin copies incoming files to the cache dir
/// and hands over their path: the launch file via [getInitialFile], later
/// ones as `onFile(path)` calls surfaced on [incomingFiles].
class IntentService {
  IntentService({this._channel = defaultChannel}) {
    _channel.setMethodCallHandler(_onCall);
  }

  static const MethodChannel defaultChannel = MethodChannel(
    'com.styro3d.rhino_viewer/intent',
  );

  final MethodChannel _channel;
  final StreamController<String> _incoming = StreamController.broadcast();

  Stream<String> get incomingFiles => _incoming.stream;

  Future<String?> getInitialFile() =>
      _channel.invokeMethod<String>('getInitialFile');

  /// Removes the copy Kotlin made for one intent once Dart has imported it.
  /// Kotlin gives each intent its own directory under `cacheDir/incoming/`
  /// (so same-named files cannot clobber each other), and that directory
  /// goes with the file. A leftover is harmless: Android purges the cache.
  static Future<void> discardIncoming(String path) async {
    final file = File(path);
    final dir = file.parent;
    final perIntent =
        dir.parent.path.split(Platform.pathSeparator).last == 'incoming';
    try {
      if (perIntent) {
        if (await dir.exists()) await dir.delete(recursive: true);
      } else if (await file.exists()) {
        await file.delete();
      }
    } on IOException {
      // Nothing to do: see above.
    }
  }

  Future<Object?> _onCall(MethodCall call) async {
    if (call.method == 'onFile' && call.arguments is String) {
      _incoming.add(call.arguments as String);
      return null;
    }
    throw MissingPluginException('Unknown method ${call.method}');
  }

  void dispose() {
    _channel.setMethodCallHandler(null);
    _incoming.close();
  }
}
