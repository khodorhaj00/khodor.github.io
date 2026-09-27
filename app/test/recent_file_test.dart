import 'package:flutter_test/flutter_test.dart';
import 'package:rhino_viewer/core/models/recent_file.dart';

void main() {
  test('round-trips through JSON', () {
    final entry = RecentFile(
      sha: 'abc',
      name: 'part.3dm',
      size: 1234,
      addedAt: DateTime.utc(2026, 1, 2, 3, 4, 5),
      lastOpenedAt: DateTime.utc(2026, 1, 3),
      meshed: true,
    );
    final restored = RecentFile.fromJson(entry.toJson());
    expect(restored.sha, 'abc');
    expect(restored.name, 'part.3dm');
    expect(restored.size, 1234);
    expect(restored.addedAt, DateTime.utc(2026, 1, 2, 3, 4, 5));
    expect(restored.lastOpenedAt, DateTime.utc(2026, 1, 3));
    expect(restored.meshed, isTrue);
  });

  test('accepts ISO-8601 dates and defaults missing fields', () {
    final entry = RecentFile.fromJson({
      'sha': 'x',
      'addedAt': '2026-05-06T07:08:09Z',
      'lastOpenedAt': 'not a date',
    });
    expect(entry.name, 'untitled.3dm');
    expect(entry.size, 0);
    expect(entry.meshed, isFalse);
    expect(entry.addedAt, DateTime.utc(2026, 5, 6, 7, 8, 9));
    expect(entry.lastOpenedAt.millisecondsSinceEpoch, 0);
  });
}
