import 'dart:async';
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
import 'webview_js_runner.dart';
import 'widgets/layers_sheet.dart';
import 'widgets/loading_overlay.dart';
import 'widgets/meshing_banner.dart';
import 'widgets/picked_card.dart';
import 'widgets/stats_sheet.dart';
import 'widgets/toolbar.dart';
import 'widgets/unmeshed_banner.dart';

enum _MenuAction { exportGlb, shareOriginal, info }

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
  static const Duration _readyTimeout = Duration(seconds: 20);

  /// Inline loading keeps several transient copies of the file in memory
  /// (Dart bytes, base64, the JS source string, the decoded buffer), so it
  /// is only attempted for files small enough to survive that.
  static const int _base64FallbackMaxBytes = 25 << 20;

  ViewerBridge? _bridge;
  final List<StreamSubscription<Object?>> _subscriptions = [];
  Timer? _readyTimer;

  /// Bumped by [_retry]: a new key makes Flutter create a fresh platform
  /// WebView, which is the only way back from a dead render process.
  int _webViewGeneration = 0;

  late RecentFile _entry = widget.entry;
  ViewerReadyInfo? _ready;
  LoadProgress? _progress;

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

  @override
  void dispose() {
    _readyTimer?.cancel();
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

  void _onWebViewCreated(InAppWebViewController controller) {
    final bridge = ViewerBridge(InAppWebViewJsRunner(controller))
      ..registerHandlers();
    _bridge = bridge;
    _subscriptions.addAll([
      bridge.onReady.listen(_onReady),
      bridge.onLoadProgress.listen((p) => setState(() => _progress = p)),
      bridge.onLoadResult.listen(_onLoadResult),
      bridge.onExportResult.listen(_onExportResult),
      bridge.onObjectPicked.listen((p) => setState(() => _picked = p)),
      bridge.onLog.listen(_onLog),
    ]);
  }

  void _onLoadStop() {
    if (_ready != null) return;
    _armReadyTimer();
  }

  void _armReadyTimer() {
    _readyTimer?.cancel();
    _readyTimer = Timer(_readyTimeout, () {
      if (mounted && _ready == null) {
        setState(() {
          _error =
              'The viewer did not start (WebGL or WebAssembly unavailable).';
          _progress = null;
        });
      }
    });
  }

  void _onReady(ViewerReadyInfo info) {
    _readyTimer?.cancel();
    setState(() => _ready = info);
    _startLoad();
  }

  Future<void> _startLoad({bool viaBase64 = false}) async {
    final bridge = _bridge;
    if (bridge == null) return;
    setState(() {
      _progress = const LoadProgress(phase: LoadPhase.fetch, progress: 0);
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
    }
  }

  void _fail(String message) {
    if (!mounted) return;
    setState(() {
      _progress = null;
      _stats = null;
      _layers = const [];
      _error = message;
    });
  }

  void _onLoadResult(LoadResult result) {
    if (result.ok) {
      setState(() {
        _progress = null;
        _stats = result.stats;
        _layers = result.stats?.layers ?? const [];
        _error = null;
      });
      _applyDisplayState();
      return;
    }
    final error = result.error ?? 'Unknown error';
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

  void _onLog(ViewerLog log) {
    // A failing load ends in the error panel or in a silent retry, so its
    // `Load failed` log would only duplicate (or contradict) that.
    if (log.level == ViewerLogLevel.error && _progress == null) {
      _snack(log.message);
    } else if (kDebugMode) {
      debugPrint('[viewer:${log.level.name}] ${log.message}');
    }
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
    setState(() {
      _error = null;
      _stats = null;
      _layers = const [];
      _picked = null;
      _ready = null;
      _triedBase64 = false;
      _progress = const LoadProgress(phase: LoadPhase.fetch, progress: 0);
      _webViewGeneration++;
    });
    _armReadyTimer();
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
    final progress = _progress;
    final meshJob = _meshJob;
    final bottomInset = MediaQuery.paddingOf(context).bottom;
    return Scaffold(
      backgroundColor: AppColors.bg,
      body: Stack(
        children: [
          Positioned.fill(
            child: InAppWebView(
              key: ValueKey(_webViewGeneration),
              initialUrlRequest: URLRequest(url: WebUri(_indexUrl)),
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
                transparentBackground: true,
                supportZoom: false,
                // The page itself blocks scrolling (viewer.css: overflow
                // hidden, touch-action none). The plugin's disable*Scroll
                // flags must NOT be used: they swallow every ACTION_MOVE
                // before Chromium sees it, killing orbit/pan/pinch.
                overScrollMode: OverScrollMode.NEVER,
                verticalScrollBarEnabled: false,
                horizontalScrollBarEnabled: false,
                useHybridComposition: true,
              ),
              onWebViewCreated: _onWebViewCreated,
              onLoadStop: (_, _) => _onLoadStop(),
              onReceivedError: (_, request, error) {
                if (request.isForMainFrame ?? true) {
                  setState(() {
                    _error = 'Viewer page failed to load: ${error.description}';
                    _progress = null;
                  });
                }
              },
              onRenderProcessGone: (_, detail) => setState(() {
                _error = detail.didCrash
                    ? 'The WebView renderer crashed (out of memory?).'
                    : 'The WebView renderer was stopped by the system.';
                _progress = null;
              }),
              onConsoleMessage: (_, message) {
                if (kDebugMode) debugPrint('[webview] ${message.message}');
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
          if (_error != null)
            _ErrorPanel(
              message: _error!,
              onRetry: _retry,
              onBack: () => Navigator.of(context).maybePop(),
            )
          else if (_busyLabel != null)
            LoadingOverlay(label: _busyLabel!)
          else if (progress != null)
            LoadingOverlay(
              label: '${progress.phase.label} ${_entry.name}',
              progress:
                  progress.phase == LoadPhase.parse && progress.progress == 0
                  ? null
                  : progress.progress,
            ),
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

class _ErrorPanel extends StatelessWidget {
  const _ErrorPanel({
    required this.message,
    required this.onRetry,
    required this.onBack,
  });

  final String message;
  final VoidCallback onRetry;
  final VoidCallback onBack;

  @override
  Widget build(BuildContext context) {
    return Positioned.fill(
      child: ColoredBox(
        color: AppColors.bg.withValues(alpha: 0.85),
        child: Center(
          child: Card(
            child: Padding(
              padding: const EdgeInsets.all(kGap * 2),
              child: ConstrainedBox(
                constraints: const BoxConstraints(maxWidth: 360),
                child: Column(
                  mainAxisSize: MainAxisSize.min,
                  crossAxisAlignment: CrossAxisAlignment.start,
                  children: [
                    const Text(
                      'Could not display this file',
                      style: TextStyle(
                        color: AppColors.danger,
                        fontWeight: FontWeight.w600,
                      ),
                    ),
                    const SizedBox(height: kGap),
                    Text(
                      message,
                      style: const TextStyle(
                        color: AppColors.text,
                        fontSize: 13,
                      ),
                    ),
                    const SizedBox(height: kGap * 2),
                    Row(
                      mainAxisAlignment: MainAxisAlignment.end,
                      children: [
                        OutlinedButton(
                          onPressed: onBack,
                          child: const Text('Back'),
                        ),
                        const SizedBox(width: kGap),
                        FilledButton(
                          onPressed: onRetry,
                          style: FilledButton.styleFrom(
                            minimumSize: const Size(0, 40),
                          ),
                          child: const Text('Retry'),
                        ),
                      ],
                    ),
                  ],
                ),
              ),
            ),
          ),
        ),
      ),
    );
  }
}
