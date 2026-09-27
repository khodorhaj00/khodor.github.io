/// Turning model-unit lengths into what the user chose to see
/// (ARCHITECTURE.md §2.1, `viewer.setAnnotationOptions({ unit })`). The viewer
/// page does the same for dimension labels; this is the app's side, for the
/// caliper, the picked object and the model extents.
library;

import '../core/models/viewer_options.dart';
import 'format.dart';

/// Millimetres per unit of a rhino3dm `UnitSystem` name, as the viewer reports
/// it (`Millimeters`, `Inches`, ...). Mirrors MM_PER_MODEL_UNIT in
/// `assets/viewer/config.js`.
const Map<String, double> mmPerModelUnit = {
  'Microns': 0.001,
  'Millimeters': 1,
  'Centimeters': 10,
  'Decimeters': 100,
  'Meters': 1000,
  'Dekameters': 10000,
  'Hectometers': 100000,
  'Kilometers': 1000000,
  'Mils': 0.0254,
  'Inches': 25.4,
  'Feet': 304.8,
  'Yards': 914.4,
  'Miles': 1609344,
};

/// Formats lengths that come from the viewer in model units.
class LengthFormat {
  const LengthFormat({
    required this.unit,
    required this.modelUnits,
    this.customFactor = 1,
  });

  /// Keeps the model's own unit and the app's default formatting.
  static const LengthFormat asInFile = LengthFormat(
    unit: DisplayUnit.file,
    modelUnits: '',
  );

  final DisplayUnit unit;

  /// rhino3dm unit name of the model, from `stats.units`.
  final String modelUnits;
  final double customFactor;

  /// Null when the model's unit is unknown, so no conversion is possible.
  double? get _mmPerUnit =>
      mmPerModelUnit[modelUnits.replaceFirst('UnitSystem_', '')];

  /// True when lengths are shown in the file's own unit (no conversion).
  bool get followsFile =>
      unit == DisplayUnit.file ||
      (unit != DisplayUnit.custom && _mmPerUnit == null);

  /// `20.0 cm`, `7.87 "`, `200` — a length given in model units.
  String call(double value) => format(value);

  String format(double value) {
    if (followsFile) return withUnit(formatLength(value), modelUnits);
    if (unit == DisplayUnit.custom) {
      return (value * customFactor).toStringAsFixed(unit.decimals);
    }
    final converted = value * _mmPerUnit! / unit.mmPerUnit!;
    final text = converted.toStringAsFixed(unit.decimals);
    return unit.symbol.isEmpty ? text : '$text ${unit.symbol}';
  }

  /// The number alone, for a column that carries its own label (ΔX, ΔY, ΔZ).
  String bare(double value) {
    final text = format(value);
    final symbol = followsFile ? unitSymbol(modelUnits) : unit.symbol;
    return symbol.isEmpty || !text.endsWith(symbol)
        ? text
        : text.substring(0, text.length - symbol.length - 1);
  }

  /// `10 × 20 × 30 mm`: a size with one unit at the end.
  String formatTriple(List<double> values) => _join(values, ' × ');

  /// `10, 20, 30 mm`: a point with one unit at the end.
  String formatPoint(List<double> values) => _join(values, ', ');

  String _join(List<double> values, String separator) {
    if (followsFile) {
      return withUnit(values.map(formatLength).join(separator), modelUnits);
    }
    // Every number in the chosen unit, with the symbol only after the last.
    final suffix = unit.symbol.isEmpty ? 0 : unit.symbol.length + 1;
    final parts = values.map((value) {
      final text = format(value);
      return suffix == 0 ? text : text.substring(0, text.length - suffix);
    });
    final joined = parts.join(separator);
    return suffix == 0 ? joined : '$joined ${unit.symbol}';
  }
}
