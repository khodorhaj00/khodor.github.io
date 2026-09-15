import '../../core/services/platform_error_monitor.dart';
import '../../core/services/webview_provider.dart';

/// The diagnostics a user can always reach, from the home screen.
///
/// The viewer's own Diagnostics sits behind its overflow menu, so a viewer
/// screen that fails to draw takes the report down with it — exactly when the
/// report is most needed. This is the subset that does not depend on a model
/// being open: what Android says about its WebView, and every error that
/// reached the app uncaught.
Future<String> buildAppReport({
  required DateTime at,
  required List<UncaughtAppError> uncaught,
  required bool hybridComposition,
}) async {
  final provider = await probeWebViewProvider();
  final out = StringBuffer('Rhino Viewer app diagnostics\n')
    ..writeln('Taken: ${at.toUtc().toIso8601String()}')
    ..writeln()
    ..writeln('ANDROID')
    ..writeln('WebView   ${provider.summary}')
    ..writeln(
      'Composite ${hybridComposition ? 'hybrid — the WebView sits in the Android view tree' : 'texture — Flutter draws the WebView itself'}',
    )
    ..writeln()
    ..writeln('UNCAUGHT ERRORS');
  if (uncaught.isEmpty) {
    out.writeln('none');
  } else {
    for (final error in uncaught) {
      out.writeln(error.detail);
    }
  }
  return out.toString();
}
