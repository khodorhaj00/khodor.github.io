import 'dart:async';
import 'dart:collection';
import 'dart:convert';
import 'dart:io';

import 'package:flutter/foundation.dart';
import 'package:flutter/material.dart';
import 'package:flutter/services.dart';
import 'package:flutter_inappwebview/flutter_inappwebview.dart';
import 'package:share_plus/share_plus.dart';

import '../../app/app_services.dart';
import '../../app/format.dart';
import '../../app/theme.dart';
import '../../core/bridge/viewer_bridge.dart';
import '../../core/models/model_stats.dart';
import '../../core/models/recent_file.dart';
import '../../core/models/viewer_events.dart';
import '../../core/services/backend_client.dart';
import '../../core/services/file_service.dart';
import '../../core/services/settings_service.dart';
import '../settings/settings_page.dart';
import 'diagnostics_report.dart';
import 'viewer_status.dart';
import 'webview_js_runner.dart';
import 'widgets/diagnostics_sheet.dart';
import 'widgets/error_panel.dart';
import 'widgets/layers_sheet.dart';
import 'widgets/loading_overlay.dart';
import 'widgets/meshing_banner.dart';
import 'widgets/picked_card.dart';
import 'widgets/stats_sheet.dart';
import 'widgets/toolbar.dart';
import 'widgets/unmeshed_banner.dart';

enum _MenuAction { exportGlb, shareOriginal, info, diagnostics }

/// One `/mesh` round trip; mutated in place so the page can tell a status
/// update for a stale job from one for the job on screen.
class _MeshJob {
  _MeshJob() : cancel = CancelToken();

  final CancelToken cancel;
  String status = 'Reading file…';
}

/// Full-screen WebView hosting the three.js viewer (ARCHITECTURE.md §3.1/§3.4).
class ViewerPage extends StatefulWidget {
  const ViewerPage({super.key, required this.services, required this.entry});

  final AppServices services;
  final RecentFile entry;

  @override
  State<ViewerPage> createState() => _ViewerPageState();
}

class _ViewerPageState extends State<ViewerPage> {
  static const String _origin = 'https://appassets.androidplatform.net';
  static const String _indexUrl =
      '$_origin/assets/flutter_assets/assets/viewer/index.html';

  /// Inline loading keeps several transient copies of the file in memory
  /// (Dart bytes, base64, the JS source string, the decoded buffer), so it
  /// is only attempted for files small enough to survive that.
  static const int _base64FallbackMaxBytes = 25 << 20;

  /// A page that has not answered `viewer.diagnostics()` by then is not
  /// running JavaScript at all; the menu must not hang on it.
  static const Duration _diagnosticsTimeout = Duration(seconds: 3);

  /// flutter_inappwebview 6.1.5 has no background-colour setting for an
  /// Android WebView — `transparentBackground` is the only lever, and it
  /// only chooses between TRANSPARENT and the platform default (white). The
  /// app's dark background is therefore painted by the document itself, from
  /// the first frame, before `viewer.css` has even been fetched.
  static final UnmodifiableListView<UserScript> _userScripts =
      UnmodifiableListView([
        UserScript(
          source:
              'if (document.documentElement) document.documentElement.style'
              ".backgroundColor = '${cssHex(AppColors.bg)}';",
          injectionTime: UserScriptInjectionTime.AT_DOCUMENT_START,
        ),
      ]);

  ViewerBridge? _bridge;
  final List<StreamSubscription<Object?>> _subscriptions = [];
  late final ViewerStatus _status;

  /// Bumped by [_retry]: a new key makes Flutter create a fresh platform
  /// WebView, which is the only way back from a dead render process.
  int _webViewGeneration = 0;

  late RecentFile _entry = widget.entry;
  ViewerReadyInfo? _ready;

  /// Set while GLB export runs; shown as the modal overlay.
  String? _busyLabel;

  /// Set while `/mesh` is in flight; shown as a cancellable banner.
  _MeshJob? _meshJob;
  ModelStats? _stats;
  String? _error;
  List<LayerInfo> _layers = const [];
  PickedObject? _picked;
  DisplayMode _displayMode = DisplayMode.shaded;
  Projection _projection = Projection.perspective;
  bool _grid = true;
  bool _triedBase64 = false;

  /// File name (inside modelsDir) of the load in flight or last completed.
  String? _loadingFileName;

  /// Set once the `.meshed.3dm` copy failed to load: it is discarded and the
  /// original is used for the rest of this page's life.
  bool _meshedRejected = false;

  AppServices get _services => widget.services;

  bool get _showingMeshed =>
      _loadingFileName == FileService.meshedName(_entry.sha);

  String get _storedFileName =>
      _loadingFileName ?? FileService.originalName(_entry.sha);

  @override
  void initState() {
    super.initState();
    _status = ViewerStatus(onChanged: _onStatusChanged, onStuck: _onStuck);
  }

  @override
  void dispose() {
    _status.dispose();
    // Leaving the page must not leave the upload running in the background.
    _meshJob?.cancel.cancel();
    _tearDownWebView();
    super.dispose();
  }

  void _tearDownWebView() {
    for (final s in _subscriptions) {
      s.cancel();
    }
    _subscriptions.clear();
    _bridge?.dispose();
    _bridge = null;
  }

  void _onStatusChanged() {
    if (mounted) setState(() {});
  }

  void _onStuck(ViewerStage stage) {
    if (_error == null) _fail(stageTimeoutMessage(stage));
  }

  void _onWebViewCreated(InAppWebViewController controller) {
    // The platform view exists, which is news: the same budget now covers the
    // wait for the first navigation instead of both at once. On a first-ever
    // run Android still has to bring its WebView provider up.
    _status.enter(ViewerStage.creatingView);
    final bridge = ViewerBridge(InAppWebViewJsRunner(controller))
      ..registerHandlers();
    _bridge = bridge;
    _subscriptions.addAll([
      bridge.onReady.listen(_onReady),
      bridge.onLoadProgress.listen(_onLoadProgress),
      bridge.onLoadResult.listen(_onLoadResult),
      bridge.onExportResult.listen(_onExportResult),
      bridge.onObjectPicked.listen((p) => setState(() => _picked = p)),
      bridge.onLog.listen(_onLog),
    ]);
  }

  void _onLoadStop() {
    if (_ready != null) return;
    _status.enter(ViewerStage.pageLoaded);
  }

  void _onReady(ViewerReadyInfo info) {
    _status.enter(ViewerStage.viewerReady);
    setState(() => _ready = info);
    _startLoad();
  }

  void _onLoadProgress(LoadProgress progress) {
    final stage = switch (progress.phase) {
      LoadPhase.fetch => ViewerStage.readingFile,
      LoadPhase.parse => ViewerStage.parsing,
      LoadPhase.build => ViewerStage.building,
      LoadPhase.unknown => _status.stage,
    };
    // rhino3dm reports no fraction while parsing: a zero there means
    // "started", not "none of it done".
    final done = progress.phase == LoadPhase.parse && progress.progress == 0
        ? null
        : progress.progress;
    _status.enter(stage, progress: done);
  }

  Future<void> _startLoad({bool viaBase64 = false}) async {
    final bridge = _bridge;
    if (bridge == null) return;
    _status.enter(ViewerStage.readingFile);
    setState(() {
      _error = null;
      _picked = null;
    });
    final files = _services.files;
    final sha = _entry.sha;
    try {
      final fileName = _meshedRejected
          ? FileService.originalName(sha)
          : await files.preferredFileName(sha);
      _loadingFileName = fileName;
      final String? base64;
      if (viaBase64) {
        final bytes = await File('${files.modelsDir.path}/$fileName')
            .readAsBytes();
        base64 = base64Encode(bytes);
      } else {
        base64 = null;
      }
      // The page may have been retried or left while reading.
      if (!mounted || !identical(bridge, _bridge)) return;
      await bridge.load(
        url: base64 == null ? '$_origin/files/$fileName' : null,
        base64: base64,
        name: _entry.name,
      );
    } on IOException catch (e) {
      _fail('The cached file could not be read: $e');
    } on PlatformException catch (e) {
      // The call never reached the page, so no loadResult can arrive; say so
      // now instead of letting the watchdog time the stage out.
      _fail('The viewer page could not be reached: ${e.message ?? e.code}');
    }
  }

  void _fail(String message) {
    if (!mounted) return;
    // A message is on screen now; a later watchdog must not replace it.
    _status.settle();
    setState(() {
      _stats = null;
      _layers = const [];
      _error = message;
    });
  }

  void _onLoadResult(LoadResult result) {
    if (result.ok) {
      final stats = result.stats;
      if (stats == null) {
        // The contract (§2.2) always sends stats with ok; without them the
        // page would sit behind an overlay that has nothing left to say.
        _fail(
          'The viewer loaded ${result.name} but reported nothing about '
          'it. Tap Retry.',
        );
        return;
      }
      _status.enter(ViewerStage.shown);
      setState(() {
        _stats = stats;
        _layers = stats.layers;
        _error = null;
      });
      _applyDisplayState();
      return;
    }
    final error = result.error ?? 'Unknown error';
    _status.record(ViewerEventLevel.error, 'Load failed: $error');
    // The asset-loader URL can fail on some WebView builds; the contract's
    // fallback is to hand the bytes over inline, tried once per file. A
    // parse or build failure would only fail again, so it is not retried.
    if (result.isFetchFailure && !_triedBase64) {
      _triedBase64 = true;
      unawaited(_retryInline(error));
      return;
    }
    if (_showingMeshed && !_meshedRejected) {
      _meshedRejected = true;
      unawaited(_discardMeshed(error));
      return;
    }
    _fail(error);
  }

  Future<void> _retryInline(String fetchError) async {
    final fileName = _loadingFileName;
    if (fileName == null) {
      _fail(fetchError);
      return;
    }
    try {
      final length = await File('${_services.files.modelsDir.path}/$fileName')
          .length();
      if (length > _base64FallbackMaxBytes) {
        _fail(
          '$fetchError. The file (${formatBytes(length)}) is too large to '
          'load inline instead.',
        );
        return;
      }
    } on IOException catch (e) {
      _fail('The cached file could not be read: $e');
      return;
    }
    if (mounted) await _startLoad(viaBase64: true);
  }

  // A .meshed.3dm that no longer loads (truncated by a kill mid-write, or a
  // bad server result) must not shadow the original forever.
  Future<void> _discardMeshed(String reason) async {
    try {
      await _services.files.discardMeshed(_entry.sha);
      await _services.cache.markMeshed(_entry.sha, meshed: false);
    } on IOException {
      // _meshedRejected keeps this page on the original regardless.
    } on PlatformException {
      // Same: a stale recents flag only costs one extra fallback later.
    }
    if (!mounted) return;
    _entry = _entry.copyWith(meshed: false);
    _triedBase64 = false;
    _snack(
      'The server-meshed copy is unreadable ($reason); showing the original',
    );
    await _startLoad();
  }

  // After a (re)load the page is back to its defaults; re-apply the user's
  // choices so a server-meshed reload keeps the same look.
  void _applyDisplayState() {
    final bridge = _bridge;
    if (bridge == null) return;
    if (_displayMode != DisplayMode.shaded) {
      bridge.setDisplayMode(_displayMode);
    }
    if (_projection != Projection.perspective) {
      bridge.setProjection(_projection);
    }
    if (!_grid) bridge.setGrid(false);
  }

  /// Every failure the page or the WebView reports ends up here: kept for the
  /// diagnostics report, shown under the stage while nothing is on screen,
  /// and announced once when the model is up and nothing else would show it.
  void _problem(String message) {
    final repeat = _status.lastProblem == message;
    _status.record(ViewerEventLevel.error, message);
    if (_stats != null && !repeat) _snack(message);
  }

  void _onLog(ViewerLog log) {
    switch (log.level) {
      case ViewerLogLevel.error:
        _problem(log.message);
      case ViewerLogLevel.warn:
        _status.record(ViewerEventLevel.warn, log.message);
      case ViewerLogLevel.info:
        _status.record(ViewerEventLevel.info, log.message);
    }
  }

  void _onReceivedError(WebResourceRequest request, WebResourceError error) {
    final mainFrame = request.isForMainFrame ?? true;
    final what = mainFrame ? 'the viewer page' : _lastSegment(request.url);
    _problem('Could not load $what: ${error.description} (${error.type})');
    if (mainFrame) {
      _fail(
        'The viewer page inside the app could not be opened '
        '(${error.description}). Tap Retry; if it keeps failing, '
        'reinstalling the app restores the viewer files.',
      );
    }
  }

  void _onReceivedHttpError(
    WebResourceRequest request,
    WebResourceResponse response,
  ) {
    final status = response.statusCode?.toString() ?? '?';
    final mainFrame = request.isForMainFrame ?? true;
    _problem('HTTP $status for ${_lastSegment(request.url)}');
    if (mainFrame) {
      _fail(
        'The viewer page inside the app answered HTTP $status. Tap Retry; if '
        'it keeps failing, reinstalling the app restores the viewer files.',
      );
    }
  }

  void _onConsoleMessage(ConsoleMessage message) {
    if (message.messageLevel == ConsoleMessageLevel.ERROR) {
      _problem('Page error: ${message.message}');
    } else if (message.messageLevel == ConsoleMessageLevel.WARNING) {
      _status.record(ViewerEventLevel.warn, 'Page warning: ${message.message}');
    } else if (kDebugMode) {
      debugPrint('[webview] ${message.message}');
    }
  }

  void _onRenderProcessGone(RenderProcessGoneDetail detail) {
    _status.record(
      ViewerEventLevel.error,
      'Render process gone (didCrash: ${detail.didCrash})',
    );
    _fail(
      detail.didCrash
          ? 'The viewer ran out of memory and Android stopped it. Tap Retry; '
                'a smaller file or closing other apps helps.'
          : 'Android stopped the viewer to free memory. Tap Retry to load '
                'the file again.',
    );
  }

  /// File name of a request URL, for messages that must stay readable.
  static String _lastSegment(WebUri url) {
    final segments = url.pathSegments;
    return segments.isEmpty || segments.last.isEmpty
        ? url.toString()
        : segments.last;
  }

  Future<void> _meshOnServer() async {
    final settings = _services.settings.value;
    if (!settings.hasBackend || _meshJob != null) return;
    final job = _MeshJob();
    setState(() => _meshJob = job);
    try {
      final bytes = await _services.files
          .originalFile(_entry.sha)
          .readAsBytes();
      final total = formatBytes(bytes.length);
      final result = await _services.backend.mesh(
        settings.backendUrl,
        bytes: bytes,
        name: _entry.name,
        quality: settings.meshQuality,
        apiKey: settings.apiKey,
        cancel: job.cancel,
        onUploadProgress: (sent, length) => _setMeshStatus(
          job,
          sent >= length
              ? 'Uploaded $total · waiting for Rhino.Compute…'
              : 'Uploading $total · ${(sent * 100 / length).floor()} %',
        ),
      );
      // A response that raced the Cancel tap is not what the user asked for.
      if (job.cancel.isCancelled || !mounted) return;
      if (result.meshedCount == 0) {
        final skipped = result.skippedCount;
        _snack(
          skipped > 0
              ? 'The server could not mesh $skipped object${skipped == 1 ? '' : 's'}'
              : 'The server found nothing to mesh',
        );
        return;
      }
      await _services.files.writeMeshed(_entry.sha, result.bytes);
      await _services.cache.markMeshed(_entry.sha);
      _entry = _entry.copyWith(meshed: true);
      _triedBase64 = false;
      _snack(
        'Meshed ${result.meshedCount} objects in ${formatMs(result.computeMs)}',
      );
      await _startLoad();
    } on BackendException catch (e) {
      if (e.code != 'cancelled') _snack('Server meshing failed: $e');
    } on InvalidModelFileException catch (e) {
      _snack(e.message);
    } on IOException catch (e) {
      _snack('Server meshing failed: $e');
    } finally {
      if (mounted) setState(() => _meshJob = null);
    }
  }

  void _setMeshStatus(_MeshJob job, String status) {
    if (!mounted || !identical(_meshJob, job) || job.status == status) return;
    setState(() => job.status = status);
  }

  void _exportGlb() {
    final bridge = _bridge;
    if (bridge == null || _stats == null || _busyLabel != null) return;
    setState(() => _busyLabel = 'Exporting GLB…');
    bridge.exportGlb();
  }

  Future<void> _onExportResult(ExportResult result) async {
    try {
      final base64 = result.base64;
      if (!result.ok || base64 == null) {
        _snack('Export failed: ${result.error}');
        return;
      }
      final dir = _services.exportsDir;
      await dir.create(recursive: true);
      final name = _safeFileName(result.filename ?? 'model.glb');
      final file = File('${dir.path}/$name');
      await file.writeAsBytes(base64Decode(base64), flush: true);
      await SharePlus.instance.share(
        ShareParams(files: [XFile(file.path, mimeType: 'model/gltf-binary')]),
      );
    } on FormatException {
      _snack('Export failed: invalid data from viewer');
    } on IOException catch (e) {
      _snack('Export failed: $e');
    } finally {
      if (mounted) setState(() => _busyLabel = null);
    }
  }

  Future<void> _shareOriginal() async {
    final file = _services.files.originalFile(_entry.sha);
    if (!await file.exists()) {
      _snack('${_entry.name} is no longer cached');
      return;
    }
    try {
      await SharePlus.instance.share(
        ShareParams(
          files: [XFile(file.path, mimeType: 'application/octet-stream')],
          fileNameOverrides: [_entry.name],
        ),
      );
    } on PlatformException catch (e) {
      _snack('Could not share: ${e.message ?? e.code}');
    }
  }

  static String _safeFileName(String name) {
    final base = name.split('/').last.split(r'\').last.trim();
    return base.isEmpty ? 'model.glb' : base;
  }

  void _showDiagnostics() =>
      DiagnosticsSheet.show(context, report: _collectDiagnostics());

  Future<String> _collectDiagnostics() async {
    final page = await _pageDiagnostics();
    final fileName = _storedFileName;
    int? sizeOnDisk;
    try {
      sizeOnDisk = await File('${_services.modelsDir.path}/$fileName').length();
    } on IOException {
      sizeOnDisk = null;
    }
    return buildDiagnosticsReport(
      at: DateTime.now(),
      fileName: _entry.name,
      recordedSize: _entry.size,
      storedName: fileName,
      sizeOnDisk: sizeOnDisk,
      pageUrl: _indexUrl,
      modelUrl: '$_origin/files/$fileName',
      status: _status,
      pageDiagnostics: page,
      stats: _stats,
      ready: _ready,
      error: _error,
    );
  }

  /// `viewer.diagnostics()` is the page's own report. It is optional and the
  /// page may be dead, so every way it can fail answers with a line of text
  /// instead of breaking the menu.
  Future<String> _pageDiagnostics() async {
    final bridge = _bridge;
    if (bridge == null) return 'not available: no WebView is running';
    try {
      final report = await bridge.diagnostics().timeout(_diagnosticsTimeout);
      return report ?? 'not available: this viewer page has no diagnostics()';
    } on TimeoutException {
      return 'no answer in ${_diagnosticsTimeout.inSeconds} s: the page is '
          'not running JavaScript';
    } on PlatformException catch (e) {
      return 'failed: ${e.message ?? e.code}';
    } on MissingPluginException {
      return 'failed: the WebView is gone';
    }
  }

  void _onMenu(_MenuAction action) {
    switch (action) {
      case _MenuAction.exportGlb:
        _exportGlb();
      case _MenuAction.shareOriginal:
        _shareOriginal();
      case _MenuAction.info:
        final stats = _stats;
        if (stats != null) {
          StatsSheet.show(
            context,
            fileName: _entry.name,
            stats: stats,
            ready: _ready,
          );
        }
      case _MenuAction.diagnostics:
        _showDiagnostics();
    }
  }

  void _showLayers() {
    final bridge = _bridge;
    if (bridge == null) return;
    LayersSheet.show(
      context,
      layers: _layers,
      onLayerToggled: (index, visible) {
        bridge.setLayerVisible(index, visible);
        setState(() {
          _layers = [
            for (final l in _layers)
              l.index == index ? l.copyWith(visible: visible) : l,
          ];
        });
      },
      onAllToggled: (visible) {
        bridge.setAllLayersVisible(visible);
        setState(() {
          _layers = [for (final l in _layers) l.copyWith(visible: visible)];
        });
      },
    );
  }

  void _openSettings() => Navigator.of(context).push(
    MaterialPageRoute<void>(builder: (_) => SettingsPage(services: _services)),
  );

  // Always starts a fresh WebView rather than reloading: after a renderer
  // crash the old instance is unusable, and a page stuck in a bad JS state
  // is not worth telling apart from one.
  void _retry() {
    _tearDownWebView();
    _status.reset();
    setState(() {
      _error = null;
      _stats = null;
      _layers = const [];
      _picked = null;
      _ready = null;
      _triedBase64 = false;
      _webViewGeneration++;
    });
  }

  void _snack(String message) {
    if (!mounted) return;
    ScaffoldMessenger.of(context)
      ..hideCurrentSnackBar()
      ..showSnackBar(
        SnackBar(content: Text(message), margin: kViewerSnackBarMargin),
      );
  }

  @override
  Widget build(BuildContext context) {
    final stats = _stats;
    final picked = _picked;
    final meshJob = _meshJob;
    final bottomInset = MediaQuery.paddingOf(context).bottom;
    // A Retry keeps this State and swaps the platform view underneath it. The
    // outgoing WebView can still report an aborted load, a console error or a
    // dead renderer while its replacement is starting, and that must not fail
    // the new attempt.
    final generation = _webViewGeneration;
    bool current() => generation == _webViewGeneration;
    final overlay = ViewerOverlay.resolve(
      status: _status,
      fileName: _entry.name,
      hasModel: stats != null,
      error: _error,
      busyLabel: _busyLabel,
    );
    return Scaffold(
      backgroundColor: AppColors.bg,
      body: Stack(
        children: [
          Positioned.fill(
            child: InAppWebView(
              key: ValueKey(_webViewGeneration),
              initialUrlRequest: URLRequest(url: WebUri(_indexUrl)),
              initialUserScripts: _userScripts,
              initialSettings: InAppWebViewSettings(
                webViewAssetLoader: WebViewAssetLoader(
                  pathHandlers: [
                    AssetsPathHandler(path: '/assets/'),
                    InternalStoragePathHandler(
                      path: '/files/',
                      directory: _services.modelsDir.path,
                    ),
                  ],
                ),
                allowFileAccess: false,
                allowContentAccess: false,
                javaScriptEnabled: true,
                mediaPlaybackRequiresUserGesture: false,
                // Opaque. `transparentBackground: true` is the plugin's only
                // background lever and makes the native side call
                // setBackgroundColor(TRANSPARENT); a transparent WebView
                // composited into the Flutter view tree is a known source of
                // flat grey frames on Android, and the page paints its own
                // dark background anyway (see _userScripts).
                transparentBackground: false,
                // LAYER_TYPE_HARDWARE: WebGL draws nothing on a software
                // layer. This is the plugin default, pinned because the whole
                // viewer depends on it.
                hardwareAcceleration: true,
                // The app's theme is dark, so Android would be free to darken
                // the page for us — which washes real content to flat greys.
                // Both levers are off by default and the plugin's native code
                // applies them unconditionally; pinned so they cannot drift.
                algorithmicDarkeningAllowed: false,
                forceDark: ForceDark.OFF,
                // Everything the page loads is local (APK assets and this
                // app's own storage, through WebViewAssetLoader), so Safe
                // Browsing can only add a network-dependent step to a load
                // that has to work offline.
                safeBrowsingEnabled: false,
                // The plugin forwards onRenderProcessGone only when this is
                // set; it infers it from the callback, but a dead renderer is
                // the one failure this page must never miss.
                useOnRenderProcessGone: true,
                supportZoom: false,
                // The page itself blocks scrolling (viewer.css: overflow
                // hidden, touch-action none). The plugin's disable*Scroll
                // flags must NOT be used: they swallow every ACTION_MOVE
                // before Chromium sees it, killing orbit/pan/pinch.
                overScrollMode: OverScrollMode.NEVER,
                verticalScrollBarEnabled: false,
                horizontalScrollBarEnabled: false,
                // Hybrid composition keeps the real WebView in the Android
                // view tree (ARCHITECTURE.md §3.1); the alternative copies it
                // into a Flutter texture, which is the path with the known
                // WebGL artefacts.
                useHybridComposition: true,
              ),
              onWebViewCreated: _onWebViewCreated,
              onLoadStart: (_, _) {
                if (current()) {
                  _status.enter(ViewerStage.pageLoading, progress: 0);
                }
              },
              onProgressChanged: (_, percent) {
                if (current() && _status.stage == ViewerStage.pageLoading) {
                  _status.enter(
                    ViewerStage.pageLoading,
                    progress: percent / 100,
                  );
                }
              },
              onLoadStop: (_, _) {
                if (current()) _onLoadStop();
              },
              onReceivedError: (_, request, error) {
                if (current()) _onReceivedError(request, error);
              },
              onReceivedHttpError: (_, request, response) {
                if (current()) _onReceivedHttpError(request, response);
              },
              onRenderProcessGone: (_, detail) {
                if (current()) _onRenderProcessGone(detail);
              },
              onConsoleMessage: (_, message) {
                if (current()) _onConsoleMessage(message);
              },
            ),
          ),
          Positioned(
            left: 0,
            right: 0,
            top: 0,
            child: SafeArea(
              bottom: false,
              child: Column(
                children: [
                  _TopBar(
                    name: _entry.name,
                    stats: stats,
                    onBack: () => Navigator.of(context).maybePop(),
                    onMenu: _onMenu,
                  ),
                  if (meshJob != null)
                    Padding(
                      padding: const EdgeInsets.fromLTRB(kGap, kGap, kGap, 0),
                      child: MeshingBanner(
                        status: meshJob.status,
                        onCancel: meshJob.cancel.cancel,
                      ),
                    )
                  else if (stats != null && stats.hasUnmeshed && _error == null)
                    Padding(
                      padding: const EdgeInsets.fromLTRB(kGap, kGap, kGap, 0),
                      child: ValueListenableBuilder<AppSettings>(
                        valueListenable: _services.settings.listenable,
                        builder: (_, settings, _) => UnmeshedBanner(
                          count: stats.unmeshed.total,
                          backendConfigured: settings.hasBackend,
                          serverTried: _showingMeshed,
                          onMeshOnServer: _meshOnServer,
                          onSetupServer: _openSettings,
                        ),
                      ),
                    ),
                ],
              ),
            ),
          ),
          if (picked != null && stats != null)
            Positioned(
              left: kGap,
              right: kGap * 8,
              bottom: kViewerToolbarHeight + bottomInset + kGap,
              child: PickedCard(
                object: picked,
                units: stats.units,
                onClose: () => setState(() => _picked = null),
              ),
            ),
          Positioned(
            left: 0,
            right: 0,
            bottom: 0,
            child: ColoredBox(
              color: AppColors.surface,
              child: SafeArea(
                top: false,
                child: ViewerToolbar(
                  displayMode: _displayMode,
                  projection: _projection,
                  grid: _grid,
                  onFit: () => _bridge?.fit(),
                  onView: (v) => _bridge?.setView(v),
                  onDisplayMode: (m) {
                    setState(() => _displayMode = m);
                    _bridge?.setDisplayMode(m);
                  },
                  onLayers: _showLayers,
                  onGrid: (v) {
                    setState(() => _grid = v);
                    _bridge?.setGrid(v);
                  },
                  onProjection: (p) {
                    setState(() => _projection = p);
                    _bridge?.setProjection(p);
                  },
                ),
              ),
            ),
          ),
          // Exactly one of these covers the WebView whenever the model is not
          // on screen, so a page that painted nothing can never pass for a
          // working app.
          switch (overlay.kind) {
            ViewerOverlayKind.error => ViewerErrorPanel(
              message: overlay.label,
              onRetry: _retry,
              onDiagnostics: _showDiagnostics,
              onBack: () => Navigator.of(context).maybePop(),
            ),
            ViewerOverlayKind.busy ||
            ViewerOverlayKind.progress => LoadingOverlay(
              label: overlay.label,
              detail: overlay.detail,
              problem: overlay.problem,
              progress: overlay.progress,
              opaque: overlay.opaque,
            ),
            ViewerOverlayKind.none => const SizedBox.shrink(),
          },
        ],
      ),
    );
  }
}

class _TopBar extends StatelessWidget {
  const _TopBar({
    required this.name,
    required this.stats,
    required this.onBack,
    required this.onMenu,
  });

  final String name;
  final ModelStats? stats;
  final VoidCallback onBack;
  final ValueChanged<_MenuAction> onMenu;

  @override
  Widget build(BuildContext context) {
    final stats = this.stats;
    return Container(
      height: 56,
      decoration: BoxDecoration(
        color: AppColors.bg.withValues(alpha: 0.85),
        border: const Border(bottom: kBorder),
      ),
      child: Row(
        children: [
          IconButton(
            onPressed: onBack,
            icon: const Icon(Icons.arrow_back),
            tooltip: 'Back',
          ),
          Expanded(
            child: Text(
              name,
              maxLines: 1,
              overflow: TextOverflow.ellipsis,
              style: const TextStyle(color: AppColors.text, fontSize: 15),
            ),
          ),
          if (stats != null) ...[
            _StatChip(label: 'objects', value: formatCount(stats.objects)),
            const SizedBox(width: kGap / 2),
            _StatChip(label: 'tris', value: formatCount(stats.triangles)),
          ],
          PopupMenuButton<_MenuAction>(
            tooltip: 'More',
            onSelected: onMenu,
            itemBuilder: (_) => [
              PopupMenuItem(
                value: _MenuAction.exportGlb,
                enabled: stats != null,
                child: const Text('Export GLB'),
              ),
              const PopupMenuItem(
                value: _MenuAction.shareOriginal,
                child: Text('Share original'),
              ),
              PopupMenuItem(
                value: _MenuAction.info,
                enabled: stats != null,
                child: const Text('Info'),
              ),
              // Always enabled: the report matters most when there is no
              // model and nothing else to look at.
              const PopupMenuItem(
                value: _MenuAction.diagnostics,
                child: Text('Diagnostics'),
              ),
            ],
          ),
        ],
      ),
    );
  }
}

class _StatChip extends StatelessWidget {
  const _StatChip({required this.label, required this.value});

  final String label;
  final String value;

  @override
  Widget build(BuildContext context) {
    return Container(
      padding: const EdgeInsets.symmetric(horizontal: kGap, vertical: 3),
      decoration: const BoxDecoration(
        color: AppColors.surface,
        border: Border.fromBorderSide(kBorder),
        borderRadius: kRadius,
      ),
      child: Row(
        mainAxisSize: MainAxisSize.min,
        children: [
          Text(
            value,
            style: monoNumbers.copyWith(color: AppColors.text, fontSize: 12),
          ),
          const SizedBox(width: 4),
          Text(
            label,
            style: const TextStyle(color: AppColors.muted, fontSize: 11),
          ),
        ],
      ),
    );
  }
}
