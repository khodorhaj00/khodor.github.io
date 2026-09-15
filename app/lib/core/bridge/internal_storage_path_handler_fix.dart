import 'package:flutter_inappwebview/flutter_inappwebview.dart';

/// A working [InternalStoragePathHandler].
///
/// `flutter_inappwebview_android` 1.1.3 ships a `toMap()` that spreads itself
/// instead of its superclass (lib/src/webview_asset_loader.dart:197):
///
/// ```dart
/// @override
/// Map<String, dynamic> toMap() {
///   return {...toMap(), 'directory': directory};   // calls itself
/// }
/// ```
///
/// Serialising the WebView settings therefore recurses until the stack
/// overflows, the platform view is never created, `onWebViewCreated` never
/// fires, and the app shows an empty rectangle. The thrown `StackOverflowError`
/// reaches neither an InAppWebView callback nor `FlutterError.onError`, which
/// is why the failure looked like a hang rather than a crash.
///
/// Upstream fixed it by writing `super.toMap()` (issue #2451, released in
/// `flutter_inappwebview_android` 1.2.0-beta.1). That line lives in a beta that
/// also rewrites most of the Android WebView implementation this app runs on,
/// so instead of taking the beta this class emits the map itself.
///
/// The map is complete for this handler: the native side reads only `type`,
/// `path` and `directory` for it, and never the channel `id` that the broken
/// method would have supplied, because an internal-storage handler is served
/// entirely in Java with no callback into Dart
/// (`types/WebViewAssetLoaderExt.java:64-73`).
///
/// Remove this class once the app moves to a plugin release that carries the
/// upstream fix, and confirm the viewer still opens on a device before doing so.
class SafeInternalStoragePathHandler extends InternalStoragePathHandler {
  SafeInternalStoragePathHandler({
    required super.path,
    required super.directory,
  });

  @override
  Map<String, dynamic> toMap() => {
    'path': path,
    'type': type,
    'directory': directory,
  };

  @override
  Map<String, dynamic> toJson() => toMap();
}
