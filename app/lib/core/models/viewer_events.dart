/// Payloads of the JS → Flutter events in ARCHITECTURE.md §2.2.
library;

import 'json_helpers.dart';
import 'model_stats.dart';

class ViewerReadyInfo {
  const ViewerReadyInfo({required this.three, required this.rhino3dm});

  factory ViewerReadyInfo.fromJson(Map<String, dynamic> json) =>
      ViewerReadyInfo(
        three: readString(json['three'], fallback: '?'),
        rhino3dm: readString(json['rhino3dm'], fallback: '?'),
      );

  final String three;
  final String rhino3dm;
}

enum LoadPhase {
  fetch('Fetching'),
  parse('Parsing'),
  build('Building scene'),
  unknown('Loading');

  const LoadPhase(this.label);

  final String label;

  static LoadPhase fromWire(String value) => LoadPhase.values.firstWhere(
    (phase) => phase.name == value,
    orElse: () => LoadPhase.unknown,
  );
}

class LoadProgress {
  const LoadProgress({required this.phase, required this.progress});

  factory LoadProgress.fromJson(Map<String, dynamic> json) => LoadProgress(
    phase: LoadPhase.fromWire(readString(json['phase'])),
    progress: readDouble(json['progress']).clamp(0, 1).toDouble(),
  );

  final LoadPhase phase;

  /// 0..1
  final double progress;
}

class LoadResult {
  const LoadResult({
    required this.ok,
    required this.name,
    this.stats,
    this.error,
  });

  factory LoadResult.fromJson(Map<String, dynamic> json) {
    final ok = readBool(json['ok']);
    return LoadResult(
      ok: ok,
      name: readString(json['name']),
      stats: ok && json['stats'] is Map
          ? ModelStats.fromJson(readMap(json['stats']))
          : null,
      error: ok ? null : readString(json['error'], fallback: 'Unknown error'),
    );
  }

  final bool ok;
  final String name;
  final ModelStats? stats;
  final String? error;

  // viewer.js reports no failing phase, so a fetch failure is recognised by
  // the messages its fetch path produces: its own `HTTP <status> while
  // fetching <url>` and Chromium's TypeError texts for a failed fetch().
  static final RegExp _fetchErrorPattern = RegExp(
    r'^HTTP \d+ while fetching |Failed to fetch|network error',
  );

  /// True when the file could not be fetched from its URL, as opposed to
  /// failing to parse or build; only then is loading it inline worth a try.
  bool get isFetchFailure => !ok && _fetchErrorPattern.hasMatch(error ?? '');
}

class ExportResult {
  const ExportResult({
    required this.ok,
    this.filename,
    this.base64,
    this.error,
  });

  factory ExportResult.fromJson(Map<String, dynamic> json) {
    final ok = readBool(json['ok']);
    return ExportResult(
      ok: ok,
      filename: ok ? readString(json['filename'], fallback: 'model.glb') : null,
      base64: ok ? readString(json['base64']) : null,
      error: ok ? null : readString(json['error'], fallback: 'Export failed'),
    );
  }

  final bool ok;
  final String? filename;
  final String? base64;
  final String? error;
}

/// What a caliper point snapped to.
enum MeasureSnap {
  vertex('Vertex'),
  end('End'),
  point('Point'),
  curve('On curve'),
  surface('On surface'),
  unknown('Point');

  const MeasureSnap(this.label);

  final String label;

  static MeasureSnap fromWire(String value) => values.firstWhere(
    (snap) => snap.name == value,
    orElse: () => MeasureSnap.unknown,
  );
}

/// Payload of the `measure` event: the caliper's picked points (0, 1 or 2)
/// and, once there are two, the distance and the X/Y/Z deltas in model
/// units.
class MeasureResult {
  const MeasureResult({
    required this.points,
    required this.snaps,
    this.distance,
    this.delta,
  });

  factory MeasureResult.fromJson(Map<String, dynamic> json) {
    final points = [for (final p in readList(json['points'])) readVec3(p)];
    final snaps = [
      for (final s in readList(json['snaps']))
        MeasureSnap.fromWire(readString(s)),
    ];
    final distance = json['distance'];
    return MeasureResult(
      points: points,
      snaps: [
        for (var i = 0; i < points.length; i++)
          i < snaps.length ? snaps[i] : MeasureSnap.unknown,
      ],
      distance: distance is num ? distance.toDouble() : null,
      delta: json['delta'] is List ? readVec3(json['delta']) : null,
    );
  }

  static const MeasureResult empty = MeasureResult(points: [], snaps: []);

  final List<List<double>> points;
  final List<MeasureSnap> snaps;
  final double? distance;
  final List<double>? delta;

  bool get isComplete => distance != null && points.length >= 2;
}

enum ViewerLogLevel {
  info,
  warn,
  error;

  static ViewerLogLevel fromWire(String value) => ViewerLogLevel.values
      .firstWhere((l) => l.name == value, orElse: () => ViewerLogLevel.info);
}

class ViewerLog {
  const ViewerLog({required this.level, required this.message});

  factory ViewerLog.fromJson(Map<String, dynamic> json) => ViewerLog(
    level: ViewerLogLevel.fromWire(readString(json['level'])),
    message: readString(json['message']),
  );

  final ViewerLogLevel level;
  final String message;
}
