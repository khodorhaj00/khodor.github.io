import 'package:flutter_test/flutter_test.dart';
import 'package:rhino_viewer/core/models/model_stats.dart';
import 'package:rhino_viewer/core/models/viewer_events.dart';
import 'package:rhino_viewer/features/viewer/diagnostics_report.dart';
import 'package:rhino_viewer/features/viewer/viewer_status.dart';

import 'support/fixtures.dart';

const Duration _oneSecond = Duration(seconds: 1);
const Duration _twoSeconds = Duration(seconds: 2);

/// The watchdog is a real Timer, so these run inside `testWidgets`, where
/// `tester.pump(duration)` drives the test clock. The status must be disposed
/// inside the test body: a timer still pending when the body returns fails
/// the test.
Future<void> withStatus(
  Future<void> Function(ViewerStatus status, List<ViewerStage> stuck) body,
) async {
  final stuck = <ViewerStage>[];
  final status = ViewerStatus(onChanged: () {}, onStuck: stuck.add);
  try {
    await body(status, stuck);
  } finally {
    status.dispose();
  }
}

void main() {
  group('ViewerStatus watchdog', () {
    testWidgets('is armed from the moment the view is created', (tester) async {
      await withStatus((status, stuck) async {
        expect(status.stage, ViewerStage.creatingView);
        await tester.pump(ViewerStage.creatingView.timeout! - _oneSecond);
        expect(stuck, isEmpty, reason: 'nothing has timed out yet');

        await tester.pump(_twoSeconds);
        expect(stuck, [ViewerStage.creatingView]);
        expect(status.lastProblem, contains(ViewerStage.creatingView.label));
      });
    });

    testWidgets('a page that loads but never answers trips at its stage', (
      tester,
    ) async {
      await withStatus((status, stuck) async {
        status.enter(ViewerStage.pageLoading);
        await tester.pump(const Duration(seconds: 9));
        status.enter(ViewerStage.pageLoaded);
        await tester.pump(ViewerStage.pageLoaded.timeout! - _oneSecond);
        expect(stuck, isEmpty, reason: 'each stage gets its own budget');

        await tester.pump(_twoSeconds);
        expect(stuck, [ViewerStage.pageLoaded]);
      });
    });

    testWidgets('progress within a stage re-arms it', (tester) async {
      await withStatus((status, stuck) async {
        status.enter(ViewerStage.readingFile);
        await tester.pump(const Duration(seconds: 20));
        status.enter(ViewerStage.readingFile, progress: 0.5);
        await tester.pump(const Duration(seconds: 20));
        expect(stuck, isEmpty, reason: 'news of any kind means it is alive');
        expect(status.progress, 0.5);

        await tester.pump(const Duration(seconds: 15));
        expect(stuck, [ViewerStage.readingFile]);
      });
    });

    testWidgets('the shown stage waits for nothing and settle stops it', (
      tester,
    ) async {
      await withStatus((status, stuck) async {
        status.enter(ViewerStage.shown);
        await tester.pump(const Duration(minutes: 5));
        expect(stuck, isEmpty);

        status.enter(ViewerStage.parsing);
        status.settle();
        await tester.pump(const Duration(minutes: 5));
        expect(stuck, isEmpty, reason: 'a message is already on screen');
      });
    });

    testWidgets('reset starts a fresh attempt', (tester) async {
      await withStatus((status, stuck) async {
        status.enter(ViewerStage.pageLoaded);
        status.record(ViewerEventLevel.error, 'boom');
        await tester.pump(const Duration(seconds: 5));

        status.reset();
        expect(status.stage, ViewerStage.creatingView);
        expect(status.events, isEmpty);
        expect(status.lastProblem, isNull);
        expect(status.marks.single.stage, ViewerStage.creatingView);
        expect(status.elapsed.inSeconds, 0);

        await tester.pump(ViewerStage.creatingView.timeout! + _oneSecond);
        expect(stuck, [ViewerStage.creatingView]);
      });
    });
  });

  group('ViewerStatus log', () {
    testWidgets('marks every stage it passes through, with timings', (
      tester,
    ) async {
      await withStatus((status, _) async {
        status.enter(ViewerStage.pageLoading);
        // The marks are wall-clock timings, so real time has to pass.
        await tester.runAsync(
          () => Future<void>.delayed(const Duration(milliseconds: 20)),
        );
        status.enter(ViewerStage.pageLoaded);
        status.enter(ViewerStage.pageLoaded, progress: 0.5);
        expect(status.marks.map((m) => m.stage), [
          ViewerStage.creatingView,
          ViewerStage.pageLoading,
          ViewerStage.pageLoaded,
        ], reason: 'staying in a stage does not add a mark');
        expect(status.marks.last.at.inMilliseconds, greaterThanOrEqualTo(10));
      });
    });

    testWidgets('keeps the last errors and drops repeats', (tester) async {
      await withStatus((status, _) async {
        status.record(ViewerEventLevel.info, 'loaded');
        status.record(
          ViewerEventLevel.error,
          'Page error: x is not a function',
        );
        status.record(
          ViewerEventLevel.error,
          'Page error: x is not a function',
        );
        expect(status.events.length, 2);
        expect(status.lastProblem, 'Page error: x is not a function');

        for (var i = 0; i < ViewerStatus.maxEvents * 2; i++) {
          status.record(ViewerEventLevel.info, 'event $i');
        }
        expect(status.events.length, ViewerStatus.maxEvents);
        expect(
          status.events.last.message,
          'event ${ViewerStatus.maxEvents * 2 - 1}',
        );
      });
    });
  });

  group('ViewerOverlay', () {
    testWidgets('always covers the WebView while no model is on screen', (
      tester,
    ) async {
      await withStatus((status, _) async {
        for (final stage in ViewerStage.values) {
          status.enter(stage);
          final overlay = ViewerOverlay.resolve(
            status: status,
            fileName: 'kiosk.3dm',
            hasModel: false,
          );
          expect(
            overlay.kind,
            ViewerOverlayKind.progress,
            reason: 'nothing on screen at $stage',
          );
          expect(overlay.label, stage.label);
          expect(overlay.detail, 'kiosk.3dm');
          expect(overlay.opaque, isTrue, reason: 'hides a blank or grey page');
        }
      });
    });

    testWidgets('shows the last error under the stage', (tester) async {
      await withStatus((status, _) async {
        status.enter(ViewerStage.pageLoaded, progress: 0.25);
        status.record(ViewerEventLevel.error, 'Page error: WebGL unavailable');
        final overlay = ViewerOverlay.resolve(
          status: status,
          fileName: 'kiosk.3dm',
          hasModel: false,
        );
        expect(overlay.problem, 'Page error: WebGL unavailable');
        expect(overlay.progress, 0.25);
      });
    });

    testWidgets('an error wins, and a busy task keeps the model visible', (
      tester,
    ) async {
      await withStatus((status, _) async {
        final failed = ViewerOverlay.resolve(
          status: status,
          fileName: 'kiosk.3dm',
          hasModel: true,
          error: 'The viewer never started.',
          busyLabel: 'Exporting GLB…',
        );
        expect(failed.kind, ViewerOverlayKind.error);
        expect(failed.label, 'The viewer never started.');
        expect(failed.opaque, isTrue);

        final busy = ViewerOverlay.resolve(
          status: status,
          fileName: 'kiosk.3dm',
          hasModel: true,
          busyLabel: 'Exporting GLB…',
        );
        expect(busy.kind, ViewerOverlayKind.busy);
        expect(busy.label, 'Exporting GLB…');
        expect(busy.opaque, isFalse);

        final idle = ViewerOverlay.resolve(
          status: status,
          fileName: 'kiosk.3dm',
          hasModel: true,
        );
        expect(idle.kind, ViewerOverlayKind.none);
      });
    });
  });

  test('every stage has a plain-language timeout message', () {
    for (final stage in ViewerStage.values) {
      final message = stageTimeoutMessage(stage);
      expect(message, contains(stage.label));
      expect(message, contains('Retry'));
      expect(message, contains('Diagnostics'));
    }
  });

  group('buildDiagnosticsReport', () {
    testWidgets('names the file, the URLs, the stages and the events', (
      tester,
    ) async {
      await withStatus((status, _) async {
        status.enter(ViewerStage.pageLoading);
        await tester.pump(const Duration(milliseconds: 120));
        status.enter(ViewerStage.pageLoaded);
        status.record(ViewerEventLevel.error, 'Page error: boom');

        final report = buildDiagnosticsReport(
          at: DateTime.utc(2026, 9, 15, 10, 30),
          fileName: 'KIOSK information-1.3dm',
          recordedSize: 3 << 20,
          storedName: 'ab12.3dm',
          sizeOnDisk: 3 << 20,
          pageUrl: 'https://appassets.androidplatform.net/assets/index.html',
          modelUrl: 'https://appassets.androidplatform.net/files/ab12.3dm',
          status: status,
          pageDiagnostics: 'renderer: WebGL2 (SwiftShader)',
          stats: ModelStats.fromJson(sampleStatsJson),
          ready: const ViewerReadyInfo(three: 'r186', rhino3dm: '8.32.2'),
          error: 'The viewer did not get past "Viewer page loaded".',
        );

        expect(report, contains('KIOSK information-1.3dm'));
        expect(report, contains('ab12.3dm'));
        expect(report, contains('3.0 MB recorded, 3.0 MB on disk'));
        expect(report, contains('/files/ab12.3dm'));
        expect(report, contains('2026-09-15T10:30:00.000Z'));
        expect(report, contains(ViewerStage.creatingView.label));
        expect(report, contains(ViewerStage.pageLoaded.label));
        expect(report, contains('renderer: WebGL2 (SwiftShader)'));
        expect(report, contains('Page error: boom'));
        expect(report, contains('48,210'));
        expect(report, contains('Millimeters'));
        expect(report, contains('r186'));
        expect(report, contains('The viewer did not get past'));
      });
    });

    testWidgets('works with no model, no page answer and no versions', (
      tester,
    ) async {
      await withStatus((status, _) async {
        final report = buildDiagnosticsReport(
          at: DateTime.utc(2026, 9, 15),
          fileName: 'kiosk.3dm',
          recordedSize: 1024,
          storedName: 'ab12.3dm',
          sizeOnDisk: null,
          pageUrl: 'https://appassets.androidplatform.net/assets/index.html',
          modelUrl: 'https://appassets.androidplatform.net/files/ab12.3dm',
          status: status,
          pageDiagnostics: 'not available: no WebView is running',
        );
        expect(report, contains('not on disk'));
        expect(report, contains('no model loaded'));
        expect(report, contains('not available: no WebView is running'));
        expect(report, contains('bundled versions'));
        expect(report, contains('Error     none'));
      });
    });
  });
}
