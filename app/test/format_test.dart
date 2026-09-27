import 'package:flutter_test/flutter_test.dart';
import 'package:rhino_viewer/app/format.dart';

void main() {
  group('unitSymbol', () {
    test('maps rhino3dm unit names to symbols', () {
      expect(unitSymbol('Millimeters'), 'mm');
      expect(unitSymbol('Centimeters'), 'cm');
      expect(unitSymbol('Meters'), 'm');
      expect(unitSymbol('Inches'), 'in');
      expect(unitSymbol('Feet'), 'ft');
      expect(unitSymbol('Kilometers'), 'km');
      expect(unitSymbol('Microns'), 'µm');
      expect(unitSymbol('Mils'), 'mil');
      expect(unitSymbol('Miles'), 'mi');
    });

    test('tolerates the UnitSystem_ prefix, case and whitespace', () {
      expect(unitSymbol('UnitSystem_Millimeters'), 'mm');
      expect(unitSymbol(' inches '), 'in');
    });

    test('is empty for no/unknown/custom units', () {
      for (final name in ['None', 'Unknown', 'Unset', 'CustomUnits', '']) {
        expect(unitSymbol(name), '', reason: name);
      }
    });
  });

  test('withUnit appends the symbol only when there is one', () {
    expect(withUnit('10 × 20', 'Millimeters'), '10 × 20 mm');
    expect(withUnit('10 × 20', 'None'), '10 × 20');
  });

  test('formatLength trims trailing zeros and rounds large values', () {
    expect(formatLength(20), '20');
    expect(formatLength(5.5), '5.5');
    expect(formatLength(0.125), '0.13');
    expect(formatLength(1234.6), '1235');
  });
}
