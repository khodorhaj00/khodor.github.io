import 'dart:convert';

import 'json_helpers.dart';

/// One entry of `Stats.layers` (ARCHITECTURE.md §2.2). `index` is the
/// position used by `viewer.setLayerVisible(index, ...)`.
class LayerInfo {
  const LayerInfo({
    required this.index,
    required this.name,
    required this.fullPath,
    required this.color,
    required this.visible,
    required this.objectCount,
  });

  factory LayerInfo.fromJson(Map<String, dynamic> json) {
    final name = readString(json['name']);
    return LayerInfo(
      index: readInt(json['index']),
      name: name,
      fullPath: readString(json['fullPath'], fallback: name),
      color: readString(json['color'], fallback: '#808080'),
      visible: readBool(json['visible'], fallback: true),
      objectCount: readInt(json['objectCount']),
    );
  }

  final int index;
  final String name;
  final String fullPath;

  /// `#RRGGBB` as emitted by the viewer.
  final String color;
  final bool visible;
  final int objectCount;

  /// The layer colour as a 24-bit `0xRRGGBB` integer, or null when the
  /// string is not a valid hex colour.
  int? get rgb {
    final hex = color.startsWith('#') ? color.substring(1) : color;
    if (hex.length != 6) return null;
    return int.tryParse(hex, radix: 16);
  }

  LayerInfo copyWith({bool? visible}) => LayerInfo(
    index: index,
    name: name,
    fullPath: fullPath,
    color: color,
    visible: visible ?? this.visible,
    objectCount: objectCount,
  );
}

class UnmeshedCounts {
  const UnmeshedCounts({
    required this.breps,
    required this.extrusions,
    required this.total,
  });

  factory UnmeshedCounts.fromJson(Map<String, dynamic> json) {
    final breps = readInt(json['breps']);
    final extrusions = readInt(json['extrusions']);
    return UnmeshedCounts(
      breps: breps,
      extrusions: extrusions,
      total: readInt(json['total'], fallback: breps + extrusions),
    );
  }

  final int breps;
  final int extrusions;
  final int total;
}

class BoundingBox {
  const BoundingBox({required this.min, required this.max});

  factory BoundingBox.fromJson(Map<String, dynamic> json) =>
      BoundingBox(min: readVec3(json['min']), max: readVec3(json['max']));

  static const BoundingBox empty = BoundingBox(min: [0, 0, 0], max: [0, 0, 0]);

  final List<double> min;
  final List<double> max;

  List<double> get size =>
      List<double>.generate(3, (i) => max[i] - min[i], growable: false);
}

class LoadTimings {
  const LoadTimings({
    required this.fetchMs,
    required this.parseMs,
    required this.buildMs,
    required this.totalMs,
  });

  factory LoadTimings.fromJson(Map<String, dynamic> json) {
    final fetch = readInt(json['fetchMs']);
    final parse = readInt(json['parseMs']);
    final build = readInt(json['buildMs']);
    return LoadTimings(
      fetchMs: fetch,
      parseMs: parse,
      buildMs: build,
      totalMs: readInt(json['totalMs'], fallback: fetch + parse + build),
    );
  }

  final int fetchMs;
  final int parseMs;
  final int buildMs;
  final int totalMs;
}

class ViewerWarning {
  const ViewerWarning({required this.type, required this.message});

  factory ViewerWarning.fromJson(Map<String, dynamic> json) => ViewerWarning(
    type: readString(json['type'], fallback: 'warning'),
    message: readString(json['message']),
  );

  final String type;
  final String message;
}

/// The `Stats` object of ARCHITECTURE.md §2.2.
class ModelStats {
  const ModelStats({
    required this.objects,
    required this.meshes,
    required this.triangles,
    required this.vertices,
    required this.curves,
    required this.points,
    required this.pointClouds,
    required this.blocks,
    required this.lights,
    required this.other,
    required this.layers,
    required this.unmeshed,
    required this.bbox,
    required this.units,
    required this.timings,
    required this.warnings,
  });

  factory ModelStats.fromJson(Map<String, dynamic> json) => ModelStats(
    objects: readInt(json['objects']),
    meshes: readInt(json['meshes']),
    triangles: readInt(json['triangles']),
    vertices: readInt(json['vertices']),
    curves: readInt(json['curves']),
    points: readInt(json['points']),
    pointClouds: readInt(json['pointClouds']),
    blocks: readInt(json['blocks']),
    lights: readInt(json['lights']),
    other: readInt(json['other']),
    layers: [
      for (final layer in readList(json['layers']))
        if (layer is Map) LayerInfo.fromJson(Map<String, dynamic>.from(layer)),
    ],
    unmeshed: UnmeshedCounts.fromJson(readMap(json['unmeshed'])),
    bbox: json['bbox'] is Map
        ? BoundingBox.fromJson(readMap(json['bbox']))
        : BoundingBox.empty,
    units: readString(json['units'], fallback: 'Unknown'),
    timings: LoadTimings.fromJson(readMap(json['timings'])),
    warnings: [
      for (final warning in readList(json['warnings']))
        if (warning is Map)
          ViewerWarning.fromJson(Map<String, dynamic>.from(warning)),
    ],
  );

  /// Parses the string returned by `viewer.getStats()`, which is either a
  /// JSON object or the literal `"null"`. Returns null for anything that is
  /// not a JSON object.
  static ModelStats? fromJsonString(String? source) {
    if (source == null || source.isEmpty || source == 'null') return null;
    final Object? decoded;
    try {
      decoded = jsonDecode(source);
    } on FormatException {
      return null;
    }
    return decoded is Map ? ModelStats.fromJson(readMap(decoded)) : null;
  }

  final int objects;
  final int meshes;
  final int triangles;
  final int vertices;
  final int curves;
  final int points;
  final int pointClouds;
  final int blocks;
  final int lights;
  final int other;
  final List<LayerInfo> layers;
  final UnmeshedCounts unmeshed;
  final BoundingBox bbox;
  final String units;
  final LoadTimings timings;
  final List<ViewerWarning> warnings;

  bool get hasUnmeshed => unmeshed.total > 0;
}

/// Payload of the `objectPicked` event (null payload means "nothing picked").
class PickedObject {
  const PickedObject({
    required this.id,
    required this.name,
    required this.objectType,
    required this.layerIndex,
    required this.layerName,
    required this.userStrings,
    required this.size,
    required this.center,
  });

  factory PickedObject.fromJson(Map<String, dynamic> json) => PickedObject(
    id: readString(json['id']),
    name: readString(json['name']),
    objectType: readString(json['objectType']),
    layerIndex: readInt(json['layerIndex'], fallback: -1),
    layerName: readString(json['layerName']),
    userStrings: _readUserStrings(json['userStrings']),
    size: readVec3(json['size']),
    center: readVec3(json['center']),
  );

  /// The contract specifies a `{k: v}` map; the raw rhino3dm shape is an
  /// array of `[key, value]` pairs, which is accepted too.
  static Map<String, String> _readUserStrings(Object? value) {
    if (value is Map) {
      return {
        for (final entry in value.entries)
          readString(entry.key): readString(entry.value),
      };
    }
    if (value is List) {
      return {
        for (final pair in value)
          if (pair is List && pair.length >= 2)
            readString(pair[0]): readString(pair[1]),
      };
    }
    return const {};
  }

  final String id;
  final String name;
  final String objectType;
  final int layerIndex;
  final String layerName;
  final Map<String, String> userStrings;
  final List<double> size;
  final List<double> center;

  String get displayName => name.isEmpty ? objectType : name;
}
