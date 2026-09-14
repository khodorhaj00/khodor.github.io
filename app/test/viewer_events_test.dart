import 'package:flutter_test/flutter_test.dart';
import 'package:rhino_viewer/core/models/viewer_events.dart';

import 'support/fixtures.dart';

void main() {
  test('ViewerReadyInfo', () {
    final info = ViewerReadyInfo.fromJson({
      'three': 'r186',
      'rhino3dm': '8.32.2',
    });
    expect(info.three, 'r186');
    expect(info.rhino3dm, '8.32.2');
    expect(ViewerReadyInfo.fromJson({}).three, '?');
  });

  test('LoadProgress clamps and maps phases', () {
    final p = LoadProgress.fromJson({'phase': 'parse', 'progress': 1.7});
    expect(p.phase, LoadPhase.parse);
    expect(p.progress, 1);
    expect(
      LoadProgress.fromJson({'phase': 'weird', 'progress': -1}).phase,
      LoadPhase.unknown,
    );
    expect(
      LoadProgress.fromJson({'phase': 'weird', 'progress': -1}).progress,
      0,
    );
    expect(LoadPhase.build.label, 'Building scene');
  });

  test('LoadResult ok carries stats, failure carries error', () {
    final ok = LoadResult.fromJson({
      'ok': true,
      'name': 'a.3dm',
      'stats': sampleStatsJson,
    });
    expect(ok.ok, isTrue);
    expect(ok.name, 'a.3dm');
    expect(ok.stats?.triangles, 48210);
    expect(ok.error, isNull);

    final failed = LoadResult.fromJson({
      'ok': false,
      'name': 'a.3dm',
      'error': 'boom',
    });
    expect(failed.ok, isFalse);
    expect(failed.stats, isNull);
    expect(failed.error, 'boom');
    expect(LoadResult.fromJson({'ok': false}).error, 'Unknown error');
  });

  test('LoadResult.isFetchFailure only flags fetch-phase errors', () {
    LoadResult failed(String error) =>
        LoadResult.fromJson({'ok': false, 'name': 'a.3dm', 'error': error});
    expect(
      failed(
        'HTTP 404 while fetching https://appassets.androidplatform.net/files/x.3dm',
      ).isFetchFailure,
      isTrue,
    );
    expect(failed('Failed to fetch').isFetchFailure, isTrue);
    expect(failed('TypeError: network error').isFetchFailure, isTrue);
    expect(
      failed("Cannot read properties of null (reading 'objects')")
          .isFetchFailure,
      isFalse,
    );
    expect(failed('superseded by a newer load()').isFetchFailure, isFalse);
    expect(LoadResult.fromJson({'ok': false}).isFetchFailure, isFalse);
    expect(
      LoadResult.fromJson({
        'ok': true,
        'name': 'a.3dm',
        'stats': sampleStatsJson,
      }).isFetchFailure,
      isFalse,
    );
  });

  test('ExportResult', () {
    final ok = ExportResult.fromJson({
      'ok': true,
      'filename': 'm.glb',
      'base64': 'Z2xURg==',
    });
    expect(ok.filename, 'm.glb');
    expect(ok.base64, 'Z2xURg==');
    final failed = ExportResult.fromJson({'ok': false, 'error': 'nothing'});
    expect(failed.base64, isNull);
    expect(failed.error, 'nothing');
  });

  test('ViewerLog level mapping', () {
    expect(
      ViewerLog.fromJson({'level': 'error', 'message': 'x'}).level,
      ViewerLogLevel.error,
    );
    expect(
      ViewerLog.fromJson({'level': 'nope', 'message': 'x'}).level,
      ViewerLogLevel.info,
    );
  });
}
