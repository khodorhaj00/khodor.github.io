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
