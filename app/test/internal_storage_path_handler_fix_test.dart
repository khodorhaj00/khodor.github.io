import 'package:flutter_inappwebview/flutter_inappwebview.dart';
import 'package:flutter_inappwebview_android/flutter_inappwebview_android.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:rhino_viewer/core/bridge/internal_storage_path_handler_fix.dart';

/// Guards the workaround for flutter_inappwebview_android 1.1.3's recursive
/// `InternalStoragePathHandler.toMap()`. Without it, building the WebView
/// settings overflows the stack and the Android platform view is never created.
void main() {
  // Constructing a handler opens a method channel, so the binding has to exist
  // first, and the Android implementation has to be registered exactly as the
  // app does at run time.
  TestWidgetsFlutterBinding.ensureInitialized();
  setUpAll(AndroidInAppWebViewPlatform.registerWith);

  group('SafeInternalStoragePathHandler', () {
    test('toMap returns what the native side reads, without recursing', () {
      final handler = SafeInternalStoragePathHandler(
        path: '/files/',
        directory: '/data/user/0/com.styro3d.rhino_viewer/files/models',
      );

      // A recursive toMap() throws StackOverflowError instead of returning.
      final map = handler.toMap();

      expect(map['path'], '/files/');
      expect(map['type'], 'InternalStoragePathHandler');
      expect(
        map['directory'],
        '/data/user/0/com.styro3d.rhino_viewer/files/models',
      );
      expect(handler.toJson(), map);
    });

    test('survives being serialised inside the WebView settings', () {
      // This is the call that fails on a device with the stock handler: the
      // settings are serialised to build the platform view's creation params.
      final settings = InAppWebViewSettings(
        webViewAssetLoader: WebViewAssetLoader(
          pathHandlers: [
            AssetsPathHandler(path: '/assets/'),
            SafeInternalStoragePathHandler(
              path: '/files/',
              directory: '/tmp/models',
            ),
          ],
        ),
      );

      final map = settings.toMap();
      final loader = map['webViewAssetLoader'] as Map<String, dynamic>;
      final handlers = (loader['pathHandlers'] as List)
          .cast<Map<String, dynamic>>();

      expect(handlers, hasLength(2));
      expect(handlers.first['type'], 'AssetsPathHandler');
      expect(handlers.last['type'], 'InternalStoragePathHandler');
      expect(handlers.last['directory'], '/tmp/models');
    });

    test('the stock handler still has the bug this class works around', () {
      // If this ever stops throwing, the plugin has been fixed upstream and
      // SafeInternalStoragePathHandler can be deleted.
      final stock = InternalStoragePathHandler(
        path: '/files/',
        directory: '/tmp/models',
      );

      expect(() => stock.toMap(), throwsA(isA<StackOverflowError>()));
    });
  });
}
