import 'dart:async';

import 'package:flutter/foundation.dart';

/// How far the viewer got between creating the platform view and putting the
/// model on screen. Every stage carries the longest it may last: the watchdog
/// is re-armed on every transition (and on every progress update), so a page
/// that never finishes loading trips it just like one that loads but never
/// answers `viewerReady`.
enum ViewerStage {
  creatingView('Creating the view', Duration(seconds: 10)),
  pageLoading('Loading the viewer page', Duration(seconds: 15)),
  pageLoaded('Viewer page loaded', Duration(seconds: 20)),
  viewerReady('Viewer ready', Duration(seconds: 15)),
  readingFile('Reading the file', Duration(seconds: 30)),
  parsing('Parsing the model', Duration(seconds: 120)),
  building('Building the scene', Duration(seconds: 60)),
  shown('Model shown', null);

  const ViewerStage(this.label, this.timeout);

  final String label;

  /// How long this stage may last before [ViewerStatus] gives up; null when
  /// the stage is not waiting for anything.
  final Duration? timeout;
}

enum ViewerEventLevel { info, warn, error }

/// One line of the diagnostics log: what happened and how long after the page
/// was created.
@immutable
class ViewerStatusEvent {
  const ViewerStatusEvent({
    required this.at,
    required this.level,
    required this.message,
  });

  final Duration at;
  final ViewerEventLevel level;
  final String message;
}

/// When a stage was entered, in elapsed time since the page was created.
@immutable
class ViewerStageMark {
  const ViewerStageMark(this.stage, this.at);

  final ViewerStage stage;
  final Duration at;
}

/// Tracks how far the viewer got, everything it and the WebView reported, and
/// gives up when a stage stalls. Kept out of the page widget so the failure
/// paths are unit testable without a platform WebView.
class ViewerStatus {
  ViewerStatus({required this.onChanged, required this.onStuck}) {
    _start();
  }

  /// Log kept for the diagnostics report; older entries are dropped.
  static const int maxEvents = 60;

  /// Stage marks kept; a reload re-enters the load stages, so this is not
  /// bounded by the number of stages.
  static const int maxStageMarks = 32;

  /// Called after every change, so the page can rebuild.
  final VoidCallback onChanged;

  /// Called once when a stage outlasts its [ViewerStage.timeout].
  final void Function(ViewerStage stage) onStuck;

  final Stopwatch _clock = Stopwatch()..start();
  final List<ViewerStatusEvent> _events = [];
  final List<ViewerStageMark> _marks = [];
  Timer? _watchdog;
  ViewerStage _stage = ViewerStage.creatingView;
  double? _progress;
  String? _lastProblem;

  ViewerStage get stage => _stage;

  /// 0..1 for the current stage, null when it cannot be measured.
  double? get progress => _progress;

  /// Most recent error-level message, shown while nothing else is on screen.
  String? get lastProblem => _lastProblem;

  Duration get elapsed => _clock.elapsed;

  List<ViewerStageMark> get marks => List.unmodifiable(_marks);

  List<ViewerStatusEvent> get events => List.unmodifiable(_events);

  /// Enters [stage] (or reports progress within the current one) and re-arms
  /// the watchdog: any news at all is proof the viewer is still alive.
  void enter(ViewerStage stage, {double? progress}) {
    if (stage != _stage) {
      _stage = stage;
      _mark(stage);
    }
    _progress = progress;
    _arm(stage.timeout);
    onChanged();
  }

  void record(ViewerEventLevel level, String message) {
    // A page erroring in a loop must not push the rest of the log out; the
    // repeat says nothing the previous line did not.
    if (_events.isNotEmpty && _events.last.message == message) return;
    if (level == ViewerEventLevel.error) _lastProblem = message;
    _events.add(
      ViewerStatusEvent(at: _clock.elapsed, level: level, message: message),
    );
    if (_events.length > maxEvents) _events.removeAt(0);
    onChanged();
  }

  /// Stops the watchdog: either there is something on screen, or the page has
  /// already failed for a reason of its own that must not be overwritten.
  void settle() {
    _watchdog?.cancel();
    _watchdog = null;
  }

  /// Back to the beginning, for a Retry that recreates the platform WebView.
  void reset() {
    settle();
    _events.clear();
    _marks.clear();
    _lastProblem = null;
    _progress = null;
    _stage = ViewerStage.creatingView;
    _clock
      ..reset()
      ..start();
    _start();
    onChanged();
  }

  void dispose() {
    settle();
    _clock.stop();
  }

  void _start() {
    _mark(ViewerStage.creatingView);
    _arm(ViewerStage.creatingView.timeout);
  }

  void _mark(ViewerStage stage) {
    _marks.add(ViewerStageMark(stage, _clock.elapsed));
    if (_marks.length > maxStageMarks) _marks.removeAt(0);
  }

  void _arm(Duration? timeout) {
    _watchdog?.cancel();
    _watchdog = timeout == null ? null : Timer(timeout, _giveUp);
  }

  void _giveUp() {
    _watchdog = null;
    final stuck = _stage;
    record(ViewerEventLevel.error, 'Timed out at "${stuck.label}"');
    onStuck(stuck);
  }
}

/// Plain-language reason and next step for a stage that never finished.
///
/// [detail] is whatever the app learned about the cause while it was waiting
/// — an error nobody caught, or Android's own answer about its WebView. It is
/// the only text the error panel gets, so a stall with a known cause must
/// carry it here rather than leave it in the log.
String stageTimeoutMessage(ViewerStage stage, {String? detail}) {
  final what = switch (stage) {
    ViewerStage.creatingView =>
      'The viewer never started: Android never built the WebView.',
    ViewerStage.pageLoading =>
      'The viewer page did not finish loading from the app.',
    ViewerStage.pageLoaded =>
      'The 3D engine did not start. This phone may not allow WebGL or '
          'WebAssembly in a WebView.',
    ViewerStage.viewerReady => 'The viewer did not start reading the file.',
    ViewerStage.readingFile => 'The file could not be read.',
    ViewerStage.parsing => 'Reading the model did not finish.',
    ViewerStage.building => 'Drawing the model did not finish.',
    ViewerStage.shown => 'The model stopped responding.',
  };
  final seconds = stage.timeout?.inSeconds ?? 0;
  final also = detail == null ? '' : ' The app also reported: $detail.';
  return '$what Nothing happened for $seconds s at "${stage.label}".$also '
      'Tap Retry, or Diagnostics to copy the details for support.';
}

enum ViewerOverlayKind { none, progress, busy, error }

/// What is drawn over the WebView. While no model is on screen the kind is
/// never [ViewerOverlayKind.none], so a page that painted nothing — or that
/// composited as flat grey — can never pass for a working app.
@immutable
class ViewerOverlay {
  const ViewerOverlay._(
    this.kind, {
    this.label = '',
    this.detail,
    this.problem,
    this.progress,
    this.opaque = true,
  });

  factory ViewerOverlay.resolve({
    required ViewerStatus status,
    required String fileName,
    required bool hasModel,
    String? error,
    String? busyLabel,
  }) {
    if (error != null) {
      return ViewerOverlay._(ViewerOverlayKind.error, label: error);
    }
    if (busyLabel != null) {
      // A model on screen stays visible behind a short task like an export.
      return ViewerOverlay._(
        ViewerOverlayKind.busy,
        label: busyLabel,
        opaque: !hasModel,
      );
    }
    if (hasModel) return const ViewerOverlay._(ViewerOverlayKind.none);
    return ViewerOverlay._(
      ViewerOverlayKind.progress,
      label: status.stage.label,
      detail: fileName,
      problem: status.lastProblem,
      progress: status.progress,
    );
  }

  final ViewerOverlayKind kind;

  /// Stage label, busy label, or the error message.
  final String label;
  final String? detail;

  /// Last error-level event, shown under the stage so a failure that is not
  /// fatal by itself still reaches the user as readable text.
  final String? problem;
  final double? progress;
  final bool opaque;
}
