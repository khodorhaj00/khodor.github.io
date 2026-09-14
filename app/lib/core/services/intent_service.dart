import 'dart:async';

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
