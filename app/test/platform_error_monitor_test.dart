import 'package:flutter/foundation.dart';
import 'package:flutter/services.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:rhino_viewer/core/services/platform_error_monitor.dart';

/// What the Android engine sends back when nothing registered the view type
/// the widget asked for — the failure this monitor exists to name.
PlatformException unregisteredViewType() => PlatformException(
  code: 'error',
  message:
      'Trying to create a platform view of unregistered type: '
      'com.pichillilorenzo/flutter_inappwebview',
);

void main() {
  group('describeUncaughtError', () {
    test('lifts the platform message out of the wrapper', () {
      expect(
        describeUncaughtError(unregisteredViewType()),
        'Trying to create a platform view of unregistered type: '
        'com.pichillilorenzo/flutter_inappwebview (error)',
      );
    });

    test('falls back to the code when there is no message', () {
      expect(
        describeUncaughtError(PlatformException(code: 'no_webview')),
        'no_webview',
      );
    });

    test('a channel with no receiver says so', () {
      expect(
        describeUncaughtError(MissingPluginException()),
        contains('no receiver'),
      );
    });

    test('anything else keeps its own text', () {
      expect(
        describeUncaughtError(StateError('bad state')),
        contains('bad state'),
      );
    });
  });

  group('PlatformErrorMonitor', () {
    test('a failed platform view is recognised as one', () {
      final record = UncaughtAppError.from(
        unregisteredViewType(),
        StackTrace.empty,
      );

      expect(record.fromPlatform, isTrue);
      expect(
        record.mentionsPlatformView,
        isTrue,
        reason: 'the message names the WebView view type',
      );
      expect(record.summary, contains('unregistered type'));
      expect(record.detail, contains('PlatformException'));
    });

    test('a platform view named only by the stack is still recognised', () {
      final record = UncaughtAppError.from(
        PlatformException(code: 'error', message: 'No WebView installed'),
        StackTrace.fromString(
          '#0      AndroidViewController.create '
          '(package:flutter/src/services/platform_views.dart:864)',
        ),
      );

      expect(record.mentionsPlatformView, isTrue);
      expect(record.summary, 'No WebView installed (error)');
    });

    test('an unrelated error is neither', () {
      final record = UncaughtAppError.from(
        StateError('unrelated'),
        StackTrace.empty,
      );

      expect(record.fromPlatform, isFalse);
      expect(record.mentionsPlatformView, isFalse);
    });

    test('records reach a listener and the kept log', () async {
      final monitor = PlatformErrorMonitor();
      final seen = <UncaughtAppError>[];
      final subscription = monitor.errors.listen(seen.add);
      addTearDown(subscription.cancel);

      monitor.record(unregisteredViewType(), StackTrace.empty);
      await Future<void>.delayed(Duration.zero);

      expect(seen, hasLength(1));
      expect(monitor.records.single.summary, seen.single.summary);
    });

    test('an error repeating at once is one event, not two', () {
      final monitor = PlatformErrorMonitor();
      monitor.record(unregisteredViewType(), StackTrace.empty);
      monitor.record(unregisteredViewType(), StackTrace.empty);

      expect(monitor.records, hasLength(1));
    });

    test('the same error later is a second occurrence', () async {
      // The case that matters: a Retry that fails exactly the way the first
      // attempt did must reach the error panel again, not be swallowed as a
      // repeat. Zero window isolates that from the loop guard.
      final monitor = PlatformErrorMonitor(repeatWindow: Duration.zero);
      final seen = <UncaughtAppError>[];
      monitor.errors.listen(seen.add);

      monitor.record(unregisteredViewType(), StackTrace.empty);
      monitor.record(unregisteredViewType(), StackTrace.empty);
      await pumpEventQueue();

      expect(monitor.records, hasLength(2));
      expect(seen, hasLength(2));
    });

    test('keeps the newest errors and no more', () {
      final monitor = PlatformErrorMonitor();
      for (var i = 0; i < PlatformErrorMonitor.maxRecords + 5; i++) {
        monitor.record(StateError('boom $i'), StackTrace.empty);
      }

      expect(monitor.records, hasLength(PlatformErrorMonitor.maxRecords));
      expect(monitor.records.last.summary, contains('boom 24'));
    });

    test('a very long platform detail is cut down, not dropped', () {
      final record = UncaughtAppError.from(
        PlatformException(
          code: 'error',
          message: 'x' * 500,
          details: 'y' * 5000,
        ),
        StackTrace.empty,
      );

      expect(record.summary.length, lessThanOrEqualTo(301));
      expect(record.detail.length, lessThanOrEqualTo(2001));
      expect(record.summary, startsWith('xxx'));
    });

    // install() itself cannot run here: flutter_test owns
    // FlutterError.onError for the length of a test, and replacing it would
    // swallow that test's own failures. The hooks are exercised directly.
    test('a framework error is recorded and passed on untouched', () {
      final monitor = PlatformErrorMonitor();
      final forwarded = <FlutterErrorDetails>[];
      final previous = FlutterError.presentError;
      FlutterError.presentError = forwarded.add;
      addTearDown(() => FlutterError.presentError = previous);

      final details = FlutterErrorDetails(exception: unregisteredViewType());
      monitor.handleFlutterError(details);

      expect(monitor.records.single.summary, contains('unregistered type'));
      expect(forwarded.single, same(details), reason: 'never swallowed');
    });

    test('an uncaught asynchronous error is left unhandled', () {
      final monitor = PlatformErrorMonitor();

      expect(
        monitor.handleUncaughtAsyncError(
          unregisteredViewType(),
          StackTrace.empty,
        ),
        isFalse,
        reason: 'false keeps Flutter logging it exactly as it did before',
      );
      expect(monitor.records, hasLength(1));
    });
  });
}
