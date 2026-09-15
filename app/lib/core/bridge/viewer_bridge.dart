import 'dart:async';
import 'dart:convert';

import '../models/model_stats.dart';
import '../models/viewer_events.dart';

typedef JsHandler = dynamic Function(List<dynamic> arguments);

/// The two WebView primitives the bridge needs, so it can be tested with a
/// fake instead of an `InAppWebViewController`.
abstract interface class JsRunner {
  Future<dynamic> evaluateJavascript(String source);

  void addJavaScriptHandler(String handlerName, JsHandler callback);
}

enum ViewerView { iso, top, bottom, front, back, left, right }

enum Projection { perspective, ortho }

enum DisplayMode {
  shaded('shaded', 'Shaded'),
  shadedEdges('shaded_edges', 'Shaded + edges'),
  wireframe('wireframe', 'Wireframe'),
  ghosted('ghosted', 'Ghosted');

  const DisplayMode(this.wireName, this.label);

  final String wireName;
  final String label;
}

/// Typed wrapper over `window.viewer` (ARCHITECTURE.md §2.1) and the
/// `callHandler` events (§2.2).
class ViewerBridge {
  ViewerBridge(this._runner);

  final JsRunner _runner;

  final _ready = StreamController<ViewerReadyInfo>.broadcast();
  final _progress = StreamController<LoadProgress>.broadcast();
  final _loadResult = StreamController<LoadResult>.broadcast();
  final _exportResult = StreamController<ExportResult>.broadcast();
  final _picked = StreamController<PickedObject?>.broadcast();
  final _log = StreamController<ViewerLog>.broadcast();

  Stream<ViewerReadyInfo> get onReady => _ready.stream;

  Stream<LoadProgress> get onLoadProgress => _progress.stream;

  Stream<LoadResult> get onLoadResult => _loadResult.stream;

  Stream<ExportResult> get onExportResult => _exportResult.stream;

  /// null when the user tapped empty space.
  Stream<PickedObject?> get onObjectPicked => _picked.stream;

  Stream<ViewerLog> get onLog => _log.stream;

  /// Must be called before the page loads (i.e. in `onWebViewCreated`).
  void registerHandlers() {
    _runner.addJavaScriptHandler('viewerReady', (args) {
      _emit(_ready, ViewerReadyInfo.fromJson(_payload(args)));
    });
    _runner.addJavaScriptHandler('loadProgress', (args) {
      _emit(_progress, LoadProgress.fromJson(_payload(args)));
    });
    _runner.addJavaScriptHandler('loadResult', (args) {
      _emit(_loadResult, LoadResult.fromJson(_payload(args)));
    });
    _runner.addJavaScriptHandler('exportResult', (args) {
      _emit(_exportResult, ExportResult.fromJson(_payload(args)));
    });
    _runner.addJavaScriptHandler('objectPicked', (args) {
      final first = args.isEmpty ? null : args[0];
      _emit(
        _picked,
        first is Map
            ? PickedObject.fromJson(Map<String, dynamic>.from(first))
            : null,
      );
    });
    _runner.addJavaScriptHandler('log', (args) {
      _emit(_log, ViewerLog.fromJson(_payload(args)));
    });
  }

  /// The handlers outlive [dispose]: the page keeps running until the platform
  /// WebView is actually gone and can emit in between. Throwing there would
  /// reject the page's `callHandler` promise instead of being reported.
  static void _emit<T>(StreamController<T> controller, T event) {
    if (!controller.isClosed) controller.add(event);
  }

  Future<void> load({String? url, String? base64, required String name}) =>
      _call('load', [
        {'url': ?url, 'base64': ?base64, 'name': name},
      ]);

  Future<void> clear() => _call('clear');

  Future<void> fit() => _call('fit');

  Future<void> setView(ViewerView view) => _call('setView', [view.name]);

  Future<void> setProjection(Projection projection) =>
      _call('setProjection', [projection.name]);

  Future<void> setDisplayMode(DisplayMode mode) =>
      _call('setDisplayMode', [mode.wireName]);

  Future<void> setLayerVisible(int index, bool visible) =>
      _call('setLayerVisible', [index, visible]);

  Future<void> setAllLayersVisible(bool visible) =>
      _call('setAllLayersVisible', [visible]);

  Future<void> setCurvesVisible(bool visible) =>
      _call('setCurvesVisible', [visible]);

  Future<void> setPointsVisible(bool visible) =>
      _call('setPointsVisible', [visible]);

  Future<void> setGrid(bool visible) => _call('setGrid', [visible]);

  Future<void> setBackground(String hexTop, String hexBottom) =>
      _call('setBackground', [hexTop, hexBottom]);

  Future<void> exportGlb() => _call('exportGlb');

  /// The page's own diagnostics as text, or null when the loaded page does
  /// not offer them. Wrapped in JavaScript rather than called directly: a
  /// page that never finished loading, an older page without
  /// `viewer.diagnostics()` and one whose call throws must all answer instead
  /// of breaking the caller.
  static const String diagnosticsSource =
      '(function () {'
      ' try {'
      ' var v = window.viewer;'
      ' if (!v || typeof v.diagnostics !== "function") return null;'
      ' var d = v.diagnostics();'
      ' if (d && typeof d.then === "function")'
      ' return "viewer.diagnostics() is asynchronous; not read";'
      ' return typeof d === "string" ? d : JSON.stringify(d);'
      ' } catch (e) { return "viewer.diagnostics() threw: " + e; }'
      '})()';

  Future<String?> diagnostics() async {
    final result = await _runner.evaluateJavascript(diagnosticsSource);
    if (result == null) return null;
    return result is String ? result : jsonEncode(result);
  }

  /// The last `Stats` the viewer produced, or null when nothing is loaded.
  Future<ModelStats?> getStats() async {
    final result = await _runner.evaluateJavascript(source('getStats'));
    return ModelStats.fromJsonString(
      result is String ? result : (result == null ? null : jsonEncode(result)),
    );
  }

  /// JavaScript for `window.viewer.<method>(...)`; every argument is
  /// JSON-encoded so strings and objects are quoted safely.
  static String source(String method, [List<Object?> args = const []]) =>
      'window.viewer.$method(${args.map(jsonEncode).join(', ')})';

  Future<void> _call(String method, [List<Object?> args = const []]) =>
      _runner.evaluateJavascript(source(method, args));

  static Map<String, dynamic> _payload(List<dynamic> args) {
    final first = args.isEmpty ? null : args[0];
    return first is Map
        ? Map<String, dynamic>.from(first)
        : const <String, dynamic>{};
  }

  void dispose() {
    _ready.close();
    _progress.close();
    _loadResult.close();
    _exportResult.close();
    _picked.close();
    _log.close();
  }
}
