/// Lenient readers for JSON produced by the viewer page. The viewer is
/// JavaScript, so numbers may arrive as `int`, `double` or (rarely) strings,
/// and fields may be missing; every reader falls back instead of throwing.
library;

int readInt(Object? value, {int fallback = 0}) => switch (value) {
  int v => v,
  double v => v.isFinite ? v.round() : fallback,
  String v => int.tryParse(v) ?? fallback,
  _ => fallback,
};

double readDouble(Object? value, {double fallback = 0}) => switch (value) {
  num v => v.toDouble(),
  String v => double.tryParse(v) ?? fallback,
  _ => fallback,
};

bool readBool(Object? value, {bool fallback = false}) => switch (value) {
  bool v => v,
  num v => v != 0,
  String v => v == 'true',
  _ => fallback,
};

String readString(Object? value, {String fallback = ''}) => switch (value) {
  String v => v,
  null => fallback,
  Object v => v.toString(),
};

Map<String, dynamic> readMap(Object? value) =>
    value is Map ? Map<String, dynamic>.from(value) : const <String, dynamic>{};

List<Object?> readList(Object? value) =>
    value is List ? value : const <Object?>[];

/// Reads a 3-component vector, padding missing components with zero.
List<double> readVec3(Object? value) {
  final list = readList(value);
  return List<double>.generate(
    3,
    (i) => i < list.length ? readDouble(list[i]) : 0,
    growable: false,
  );
}
