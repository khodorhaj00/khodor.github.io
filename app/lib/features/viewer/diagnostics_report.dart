import '../../app/format.dart';
import '../../app/versions.dart';
import '../../core/models/model_stats.dart';
import '../../core/models/viewer_events.dart';
import '../../core/services/platform_error_monitor.dart';
import 'viewer_status.dart';

/// Everything support needs in one copyable block: what the app tried to
/// load, how far it got, what the page itself reports, and every error the
/// WebView raised on the way.
String buildDiagnosticsReport({
  required DateTime at,
  required String fileName,
  required int recordedSize,
  required String storedName,
  required int? sizeOnDisk,
  required String pageUrl,
  required String modelUrl,
  required ViewerStatus status,
  required String pageDiagnostics,
  required String webViewProvider,
  required String composition,
  required List<UncaughtAppError> uncaught,
  ModelStats? stats,
  ViewerReadyInfo? ready,
  String? error,
}) {
  final out = StringBuffer('Rhino Viewer diagnostics\n')
    ..writeln('Taken: ${at.toUtc().toIso8601String()}')
    ..writeln()
    ..writeln('FILE')
    ..writeln('Name      $fileName')
    ..writeln('Stored    $storedName')
    ..writeln(
      'Size      ${formatBytes(recordedSize)} recorded, '
      '${sizeOnDisk == null ? 'not on disk' : '${formatBytes(sizeOnDisk)} on disk'}',
    )
    ..writeln('Page      $pageUrl')
    ..writeln('Model     $modelUrl')
    ..writeln()
    ..writeln('STATE')
    ..writeln('Stage     ${status.stage.label}')
    ..writeln('Elapsed   ${formatMs(status.elapsed.inMilliseconds)}')
    ..writeln('Error     ${error ?? 'none'}')
    ..writeln('WebView   $webViewProvider')
    // Which of the two Android platform-view paths drew this WebView; a
    // report is unreadable without it once the mode can be switched.
    ..writeln('Composite $composition')
    ..writeln(
      'Engine    three ${ready?.three ?? VendoredVersions.three} · '
      'rhino3dm ${ready?.rhino3dm ?? VendoredVersions.rhino3dm}'
      '${ready == null ? ' (bundled versions; the page never reported)' : ''}',
    )
    ..writeln()
    ..writeln('STAGES');
  for (final mark in status.marks) {
    out.writeln(
      '${formatMs(mark.at.inMilliseconds).padRight(10)}${mark.stage.label}',
    );
  }
  out
    ..writeln()
    ..writeln('MODEL');
  if (stats == null) {
    out.writeln('no model loaded');
  } else {
    final size = stats.bbox.size.map(formatLength).join(' × ');
    out
      ..writeln(
        'Objects   ${formatCount(stats.objects)} · meshes '
        '${formatCount(stats.meshes)} · triangles '
        '${formatCount(stats.triangles)} · layers ${stats.layers.length}',
      )
      ..writeln('Units     ${stats.units}')
      ..writeln('Extents   ${withUnit(size, stats.units)}')
      ..writeln('Unmeshed  ${stats.unmeshed.total}')
      ..writeln(
        'Timings   fetch ${formatMs(stats.timings.fetchMs)} · parse '
        '${formatMs(stats.timings.parseMs)} · build '
        '${formatMs(stats.timings.buildMs)} · total '
        '${formatMs(stats.timings.totalMs)}',
      );
  }
  out
    ..writeln()
    ..writeln('PAGE DIAGNOSTICS')
    ..writeln(pageDiagnostics)
    ..writeln()
    // The one failure with no other symptom: a platform view that was never
    // created reports nothing to the WebView callbacks, so this is where a
    // viewer that never started says why.
    ..writeln('UNCAUGHT ERRORS');
  if (uncaught.isEmpty) {
    out.writeln('none');
  } else {
    for (final error in uncaught) {
      out.writeln(error.detail);
    }
  }
  out
    ..writeln()
    ..writeln('EVENTS');
  if (status.events.isEmpty) {
    out.writeln('none');
  } else {
    for (final event in status.events) {
      out.writeln(
        '${formatMs(event.at.inMilliseconds).padRight(10)}'
        '${event.level.name.padRight(6)}${event.message}',
      );
    }
  }
  return out.toString();
}
