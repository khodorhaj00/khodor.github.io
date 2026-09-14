import 'dart:convert';

import 'package:flutter_test/flutter_test.dart';
import 'package:rhino_viewer/core/models/model_stats.dart';

import 'support/fixtures.dart';

void main() {
  group('ModelStats.fromJson', () {
    test('parses the contract sample', () {
      final stats = ModelStats.fromJson(sampleStatsJson);
      expect(stats.objects, 237);
      expect(stats.meshes, 12);
      expect(stats.triangles, 48210);
      expect(stats.vertices, 26011);
      expect(stats.curves, 218);
      expect(stats.points, 1);
      expect(stats.pointClouds, 1);
      expect(stats.blocks, 0);
      expect(stats.lights, 2);
      expect(stats.other, 4);
      expect(stats.units, 'Millimeters');
      expect(stats.layers, hasLength(2));
      expect(stats.layers[1].name, 'HIDDEN');
      expect(stats.layers[1].fullPath, 'Parts::HIDDEN');
      expect(stats.layers[1].visible, isFalse);
      expect(stats.layers[1].objectCount, 3);
      expect(stats.layers[0].rgb, 0xFF8800);
      expect(stats.unmeshed.breps, 2);
      expect(stats.unmeshed.extrusions, 1);
      expect(stats.unmeshed.total, 3);
      expect(stats.hasUnmeshed, isTrue);
      expect(stats.bbox.min, [-10, -20, 0]);
      expect(stats.bbox.max, [10, 20, 5.5]);
      expect(stats.bbox.size, [20, 40, 5.5]);
      expect(stats.timings.parseMs, 240);
      expect(stats.timings.totalMs, 282);
      expect(stats.warnings.single.type, 'no mesh');
      expect(stats.warnings.single.message, contains('abc'));
    });

    test('tolerates missing and oddly typed fields', () {
      final stats = ModelStats.fromJson({
        'objects': '7',
        'triangles': 12.0,
        'layers': [
          {'name': 'A'},
          'garbage',
        ],
        'unmeshed': {'breps': 1, 'extrusions': 2},
        'timings': {'fetchMs': 1, 'parseMs': 2, 'buildMs': 3},
      });
      expect(stats.objects, 7);
      expect(stats.triangles, 12);
      expect(stats.meshes, 0);
      expect(stats.units, 'Unknown');
      expect(stats.layers, hasLength(1));
      expect(stats.layers.single.index, 0);
      expect(stats.layers.single.fullPath, 'A');
      expect(stats.layers.single.visible, isTrue);
      expect(stats.unmeshed.total, 3);
      expect(stats.timings.totalMs, 6);
      expect(stats.bbox.size, [0, 0, 0]);
      expect(stats.warnings, isEmpty);
      expect(stats.hasUnmeshed, isTrue);
    });
  });

  group('ModelStats.fromJsonString', () {
    test('parses the getStats() string', () {
      final stats = ModelStats.fromJsonString(jsonEncode(sampleStatsJson));
      expect(stats?.objects, 237);
    });

    test('returns null for "null", empty, invalid and non-object input', () {
      expect(ModelStats.fromJsonString('null'), isNull);
      expect(ModelStats.fromJsonString(null), isNull);
      expect(ModelStats.fromJsonString(''), isNull);
      expect(ModelStats.fromJsonString('{not json'), isNull);
      expect(ModelStats.fromJsonString('[1,2]'), isNull);
    });
  });

  group('LayerInfo', () {
    test('rgb handles missing hash and invalid colours', () {
      LayerInfo layer(String color) =>
          LayerInfo.fromJson({'name': 'x', 'color': color});
      expect(layer('#0A0B0C').rgb, 0x0A0B0C);
      expect(layer('0A0B0C').rgb, 0x0A0B0C);
      expect(layer('red').rgb, isNull);
      expect(layer('#FFF').rgb, isNull);
    });

    test('copyWith only changes visibility', () {
      final layer = LayerInfo.fromJson(
        sampleStatsJson['layers'][0] as Map<String, dynamic>,
      );
      final hidden = layer.copyWith(visible: false);
      expect(hidden.visible, isFalse);
      expect(hidden.index, layer.index);
      expect(hidden.name, layer.name);
      expect(hidden.color, layer.color);
      expect(hidden.objectCount, layer.objectCount);
    });
  });

  group('PickedObject.fromJson', () {
    test('parses the contract payload', () {
      final picked = PickedObject.fromJson({
        'id': 'guid-1',
        'name': 'Bracket',
        'objectType': 'Brep',
        'layerIndex': 2,
        'layerName': 'PARTS',
        'userStrings': {'material': 'EPS', 'density': '30'},
        'size': [10, 20, 30],
        'center': [1, 2, 3],
      });
      expect(picked.id, 'guid-1');
      expect(picked.displayName, 'Bracket');
      expect(picked.objectType, 'Brep');
      expect(picked.layerIndex, 2);
      expect(picked.layerName, 'PARTS');
      expect(picked.userStrings, {'material': 'EPS', 'density': '30'});
      expect(picked.size, [10, 20, 30]);
      expect(picked.center, [1, 2, 3]);
    });

    test('accepts [key, value] pair lists and pads short vectors', () {
      final picked = PickedObject.fromJson({
        'objectType': 'Mesh',
        'userStrings': [
          ['a', '1'],
          ['b'],
          'junk',
        ],
        'size': [4],
      });
      expect(picked.userStrings, {'a': '1'});
      expect(picked.size, [4, 0, 0]);
      expect(picked.center, [0, 0, 0]);
      expect(picked.layerIndex, -1);
      expect(picked.displayName, 'Mesh');
    });
  });
}
