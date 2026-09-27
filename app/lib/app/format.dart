/// Number/date formatting without an intl dependency.
library;

String formatCount(int value) {
  final digits = value.abs().toString();
  final buffer = StringBuffer();
  for (var i = 0; i < digits.length; i++) {
    if (i > 0 && (digits.length - i) % 3 == 0) buffer.write(',');
    buffer.write(digits[i]);
  }
  return value < 0 ? '-$buffer' : buffer.toString();
}

String formatBytes(int bytes) {
  if (bytes < 1024) return '$bytes B';
  const units = ['KB', 'MB', 'GB'];
  var value = bytes / 1024;
  var unit = 0;
  while (value >= 1024 && unit < units.length - 1) {
    value /= 1024;
    unit++;
  }
  return '${value < 10 ? value.toStringAsFixed(1) : value.round()} ${units[unit]}';
}

/// A model-unit length with at most two decimals, trailing zeros trimmed.
String formatLength(double value) {
  if (value.abs() >= 1000) return value.round().toString();
  final text = value.toStringAsFixed(2);
  return text.contains('.') ? text.replaceFirst(RegExp(r'\.?0+$'), '') : text;
}

const Map<String, String> _unitSymbols = {
  'angstroms': 'Å',
  'nanometers': 'nm',
  'microns': 'µm',
  'millimeters': 'mm',
  'centimeters': 'cm',
  'decimeters': 'dm',
  'meters': 'm',
  'dekameters': 'dam',
  'hectometers': 'hm',
  'kilometers': 'km',
  'megameters': 'Mm',
  'gigameters': 'Gm',
  'microinches': 'µin',
  'mils': 'mil',
  'inches': 'in',
  'feet': 'ft',
  'yards': 'yd',
  'miles': 'mi',
  'nauticalmiles': 'nmi',
};

/// Short symbol for a rhino3dm `UnitSystem` name as the viewer reports it
/// (`Millimeters` → `mm`, `Inches` → `in`); a `UnitSystem_` prefix is
/// tolerated. Empty for `None`, `Unknown`, custom and unrecognised units, so
/// callers print bare numbers instead of "100 Unknown".
String unitSymbol(String rhinoName) {
  final key = rhinoName.trim().toLowerCase().replaceFirst('unitsystem_', '');
  return _unitSymbols[key] ?? '';
}

/// `<value> <symbol>`, or just the value when the unit has no symbol.
String withUnit(String value, String rhinoName) {
  final symbol = unitSymbol(rhinoName);
  return symbol.isEmpty ? value : '$value $symbol';
}

String formatMs(int ms) =>
    ms >= 1000 ? '${(ms / 1000).toStringAsFixed(2)} s' : '$ms ms';

const List<String> _months = [
  'Jan',
  'Feb',
  'Mar',
  'Apr',
  'May',
  'Jun',
  'Jul',
  'Aug',
  'Sep',
  'Oct',
  'Nov',
  'Dec',
];

String formatRelative(DateTime when, {DateTime? now}) {
  final reference = now ?? DateTime.now();
  final diff = reference.difference(when);
  if (diff.inSeconds < 60) return 'just now';
  if (diff.inMinutes < 60) return '${diff.inMinutes} min ago';
  if (diff.inHours < 24) return '${diff.inHours} h ago';
  if (diff.inDays < 2) return 'yesterday';
  if (diff.inDays < 30) return '${diff.inDays} d ago';
  final local = when.toLocal();
  return '${local.day} ${_months[local.month - 1]} ${local.year}';
}
