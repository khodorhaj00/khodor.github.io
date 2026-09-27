import 'dart:async';

import 'package:flutter/foundation.dart';
import 'package:flutter/services.dart';

/// An error that reached the app with no `catch` in its way.
@immutable
class UncaughtAppError {
  const UncaughtAppError({
    required this.summary,
    required this.detail,
    required this.fromPlatform,
    required this.mentionsPlatformView,
  });

  /// Reads one error and its stack into a record.
  factory UncaughtAppError.from(Object error, StackTrace? stack) =>
      UncaughtAppError(
        summary: _shorten(describeUncaughtError(error), 300),
        detail: _shorten(error.toString(), 2000),
        fromPlatform:
            error is PlatformException || error is MissingPluginException,
        mentionsPlatformView: _mentionsPlatformView(error, stack),
      );

  /// One readable line, fit for the error panel: a [PlatformException]'s own
  /// `message` where there is one, because that is the sentence the platform
  /// wrote about what it refused to do.
  final String summary;

  /// The error's full text, for the diagnostics dump.
  final String detail;

  /// The platform side, not Dart, is what failed: a [PlatformException] from
  /// a channel call, or a [MissingPluginException] from a channel that has no
  /// receiver in this build.
  final bool fromPlatform;

  /// The error or its stack names the framework's platform-view machinery.
  /// Release stack traces are not always symbolic, so this is corroboration,
  /// never the test on its own.
  final bool mentionsPlatformView;

  @override
  String toString() => summary;

  /// The identifier flutter_inappwebview registers its view factory under; it
  /// appears verbatim in the engine's message for an unregistered view type.
  static const String _webViewType = 'com.pichillilorenzo/flutter_inappwebview';

  static bool _mentionsPlatformView(Object error, StackTrace? stack) {
    final haystack = '$error\n${stack ?? ''}';
    return haystack.contains(_webViewType) ||
        haystack.contains('AndroidViewController') ||
        haystack.contains('PlatformViewsService') ||
        haystack.contains('platform_view');
  }

  static String _shorten(String text, int max) {
    final flat = text.trim();
    return flat.length <= max ? flat : '${flat.substring(0, max)}…';
  }
}

/// Catches the errors that no callback in this app can see.
///
/// An Android platform view is created by a future nobody awaits. The plugin
/// calls `AndroidViewController.create()` from `PlatformViewLink`'s
/// `onCreatePlatformView` and drops the result (flutter_inappwebview_android
/// 1.1.3, `in_app_webview.dart`), and the framework's own call site in
/// `_PlatformViewLinkState.build` drops it too (Flutter 3.47,
/// `widgets/platform_view.dart`). `create()` awaits the native `create`
/// method call and only then runs the `onPlatformViewCreated` listeners — the
/// listener that builds the controller and fires `onWebViewCreated`.
///
/// So when the native side refuses — an unregistered view type because the
/// plugin never registered, or an Android System WebView that is missing or
/// disabled so the `WebView` constructor throws, which the method channel
/// turns into a [PlatformException] — no InAppWebView callback fires, no
/// [FlutterError] is reported, and the rejected future becomes an unhandled
/// asynchronous error in the root zone. Flutter offers that to
/// [PlatformDispatcher.onError] and otherwise only prints it to logcat. This
/// class listens there, so the phone can say why the viewer never started.
class PlatformErrorMonitor {
  PlatformErrorMonitor({this.repeatWindow = const Duration(seconds: 1)});

  /// Enough to explain one failed start. The oldest go first, so the cap is
  /// generous: the first error is usually the informative one.
  static const int maxRecords = 20;

  /// How close together two identical errors have to be to count as one
  /// event repeating rather than two occurrences.
  ///
  /// This exists for one hazard: a listener that fails while handling an
  /// error has its own failure land back here, which without a guard feeds
  /// itself forever. Such a loop runs at microtask speed, so a window of a
  /// second stops it. Anything slower is genuinely a second occurrence and
  /// must be reported — a Retry that fails exactly the way the first attempt
  /// did is the case that matters, and swallowing it would leave the error
  /// panel with nothing to say.
  final Duration repeatWindow;

  final StreamController<UncaughtAppError> _controller =
      StreamController<UncaughtAppError>.broadcast();
  final List<UncaughtAppError> _records = [];
  final Stopwatch _sinceLastRecord = Stopwatch();
  FlutterExceptionHandler? _previousOnError;
  bool _installed = false;

  /// Every error caught from now on. Broadcast, so a screen can come and go.
  Stream<UncaughtAppError> get errors => _controller.stream;

  /// Everything caught so far, oldest first — including anything that
  /// arrived before a screen started listening.
  List<UncaughtAppError> get records => List.unmodifiable(_records);

  /// Installs the process-wide hooks.
  ///
  /// Call this once, from `main()`, and from nowhere else: `flutter_test`
  /// installs its own [FlutterError.onError] around every test, and a widget
  /// that replaced it would swallow the failures of the test that built it.
  void install() {
    if (_installed) return;
    _installed = true;
    _previousOnError = FlutterError.onError;
    FlutterError.onError = handleFlutterError;
    PlatformDispatcher.instance.onError = handleUncaughtAsyncError;
  }

  /// Keeps [error] and hands it to the listeners. The seam the tests use, so
  /// they never touch the process-wide hooks.
  void record(Object error, StackTrace? stack) {
    final entry = UncaughtAppError.from(error, stack);
    if (_records.isNotEmpty &&
        _records.last.summary == entry.summary &&
        _sinceLastRecord.elapsed < repeatWindow) {
      return;
    }
    _records.add(entry);
    if (_records.length > maxRecords) _records.removeAt(0);
    _sinceLastRecord
      ..reset()
      ..start();
    _controller.add(entry);
  }

  /// The [FlutterError.onError] hook. Public so a test can prove the two
  /// things that make [install] safe without installing anything.
  @visibleForTesting
  void handleFlutterError(FlutterErrorDetails details) {
    record(details.exception, details.stack);
    // Forward, always. The console dump and the debug error widget are not
    // this class's to take away, and a swallowed framework error is worse
    // than the blind spot this monitor exists to close.
    (_previousOnError ?? FlutterError.presentError)(details);
  }

  /// The [PlatformDispatcher.onError] hook.
  @visibleForTesting
  bool handleUncaughtAsyncError(Object error, StackTrace stack) {
    record(error, stack);
    // False: still unhandled, so Flutter logs it exactly as it did before.
    // This monitor observes, it never absorbs.
    return false;
  }
}

/// The most useful sentence an error carries.
///
/// A [PlatformException] prints as `PlatformException(error, ..., null, null)`,
/// which buries the one part that says what the platform refused to do;
/// `details` is usually a Java stack trace, so it stays out of the line shown
/// to the user and goes to the diagnostics dump instead.
String describeUncaughtError(Object error) {
  if (error is PlatformException) {
    final message = error.message;
    return message == null || message.isEmpty
        ? error.code
        : '$message (${error.code})';
  }
  if (error is MissingPluginException) {
    return error.message ??
        'a platform channel has no receiver in this build of the app';
  }
  return error.toString();
}
