import 'package:flutter_inappwebview/flutter_inappwebview.dart';

import '../../core/bridge/viewer_bridge.dart';

/// [JsRunner] backed by a live `InAppWebViewController`.
class InAppWebViewJsRunner implements JsRunner {
  const InAppWebViewJsRunner(this._controller);

  final InAppWebViewController _controller;

  @override
  Future<dynamic> evaluateJavascript(String source) =>
      _controller.evaluateJavascript(source: source);

  @override
  void addJavaScriptHandler(String handlerName, JsHandler callback) =>
      _controller.addJavaScriptHandler(
        handlerName: handlerName,
        callback: callback,
      );
}
