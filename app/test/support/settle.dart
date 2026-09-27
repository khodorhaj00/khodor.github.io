import 'package:flutter_test/flutter_test.dart';

/// Real file I/O inside a widget test only completes within `runAsync`;
/// this pumps in real time until [done] holds (or fails after 10 s). Callers
/// pump normally afterwards to render the final state.
Future<void> settle(WidgetTester tester, bool Function() done) =>
    tester.runAsync(() async {
      final deadline = DateTime.now().add(const Duration(seconds: 10));
      while (!done() && DateTime.now().isBefore(deadline)) {
        await Future<void>.delayed(const Duration(milliseconds: 20));
        await tester.pump();
      }
      expect(done(), isTrue, reason: 'condition not met within 10 s');
    });
