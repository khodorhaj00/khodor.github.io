import 'package:flutter_test/flutter_test.dart';
import 'package:rhino_viewer/app/units.dart';
import 'package:rhino_viewer/core/models/viewer_options.dart';

void main() {
  group('LengthFormat', () {
    const millimetres = 'Millimeters';

    test('keeps the file unit and the app formatting for DisplayUnit.file', () {
      const format = LengthFormat(
        unit: DisplayUnit.file,
        modelUnits: millimetres,
      );
      expect(format.followsFile, isTrue);
      expect(format.format(200), '200 mm');
      expect(format.format(20.456), '20.46 mm');
      expect(format.bare(200), '200');
      expect(format.formatTriple([10, 20.5, 30]), '10 × 20.5 × 30 mm');
      expect(format.formatPoint([0, 0, 0]), '0, 0, 0 mm');
    });

    test('converts to mm, cm, m and inch with their decimals', () {
      String show(DisplayUnit unit, double value) =>
          LengthFormat(unit: unit, modelUnits: millimetres).format(value);
      expect(show(DisplayUnit.mm, 200), '200 mm');
      expect(show(DisplayUnit.cm, 200), '20.0 cm');
      expect(show(DisplayUnit.m, 200), '0.20 m');
      expect(show(DisplayUnit.inch, 200), '7.87 "');
      // A model in centimetres: the same 200 units are 2 m.
      expect(
        const LengthFormat(
          unit: DisplayUnit.m,
          modelUnits: 'Centimeters',
        ).format(200),
        '2.00 m',
      );
    });

    test('custom multiplies the model units, whatever they are', () {
      const format = LengthFormat(
        unit: DisplayUnit.custom,
        modelUnits: millimetres,
        customFactor: 0.1,
      );
      expect(format.followsFile, isFalse);
      expect(format.format(200), '20.00');
      expect(format.bare(200), '20.00');
    });

    test('a size and a point carry the unit once', () {
      const format = LengthFormat(
        unit: DisplayUnit.cm,
        modelUnits: millimetres,
      );
      expect(format.formatTriple([10, 20, 30]), '1.0 × 2.0 × 3.0 cm');
      expect(format.formatPoint([10, 20, 30]), '1.0, 2.0, 3.0 cm');
      expect(format.bare(10), '1.0');
    });

    test('falls back to the file when the model unit is unknown', () {
      const format = LengthFormat(unit: DisplayUnit.cm, modelUnits: 'Unknown');
      expect(format.followsFile, isTrue);
      expect(format.format(12.5), '12.5');
      // A UnitSystem_ prefix, as older payloads carry it, still converts.
      expect(
        const LengthFormat(
          unit: DisplayUnit.cm,
          modelUnits: 'UnitSystem_Millimeters',
        ).format(200),
        '20.0 cm',
      );
    });
  });
}
