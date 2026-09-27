import 'dart:async';

import 'package:flutter/foundation.dart';
import 'package:flutter/services.dart';
import 'package:flutter_inappwebview/flutter_inappwebview.dart';

/// What Android says about the WebView implementation this app would run in.
@immutable
class WebViewProviderInfo {
  const WebViewProviderInfo({
    required this.summary,
    this.missing = false,
    this.pluginMissing = false,
  });

  /// One line for the overlay and the diagnostics dump.
  final String summary;

  /// Android reports no enabled WebView implementation at all.
  final bool missing;

  /// The plugin's own manager channel has no receiver, so the plugin is not
  /// registered in this build — and neither, then, is its view factory.
  final bool pluginMissing;

  /// True when nothing here explains a WebView that was never created.
  bool get usable => !missing && !pluginMissing;
}

/// Asks Android which WebView package backs this app.
///
/// [InAppWebViewController.getCurrentWebViewPackage] is a static call on the
/// plugin's manager channel (`InAppWebViewManager`, wrapping
/// `WebViewCompat.getCurrentWebViewPackage`). It needs no WebView instance
/// and no platform view, so it still answers when the view was never built —
/// which is exactly when the answer is worth having:
///
/// * a package and version: Android has a WebView provider and the plugin is
///   registered, so neither of those explains a missing view;
/// * `null`: Android has **no** enabled WebView provider (uninstalled, or
///   disabled under Settings › Apps), which stops every WebView in the app;
/// * [MissingPluginException]: the channel has no receiver, so the plugin is
///   not registered — its platform-view factory is not registered either,
///   and creating the view fails with an unregistered view type.
///
/// Every failure answers with a line of text: this runs while the viewer is
/// already in trouble and must never add a way to fail.
Future<WebViewProviderInfo> probeWebViewProvider({
  Duration timeout = const Duration(seconds: 5),
}) async {
  try {
    final info = await InAppWebViewController.getCurrentWebViewPackage()
        .timeout(timeout);
    if (info == null) {
      return const WebViewProviderInfo(
        summary: 'none — Android reports no WebView implementation',
        missing: true,
      );
    }
    final name = info.packageName ?? 'unnamed package';
    final version = info.versionName ?? 'unknown version';
    return WebViewProviderInfo(summary: '$name $version');
  } on MissingPluginException {
    return const WebViewProviderInfo(
      summary: 'unknown — the WebView plugin is not registered in this build',
      pluginMissing: true,
    );
  } on PlatformException catch (e) {
    return WebViewProviderInfo(summary: 'unknown — ${e.message ?? e.code}');
  } on TimeoutException {
    return WebViewProviderInfo(
      summary: 'unknown — Android did not answer in ${timeout.inSeconds} s',
    );
  } on UnimplementedError {
    return const WebViewProviderInfo(summary: 'unknown — not an Android host');
  } catch (e) {
    // The plugin registers its Dart-side implementation from the generated
    // registrant, inside a `try`. If that never ran, the static accessor
    // throws before any channel is touched — which is itself the answer.
    return WebViewProviderInfo(summary: 'unknown — $e');
  }
}
