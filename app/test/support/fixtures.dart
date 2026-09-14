import 'dart:convert';
import 'dart:typed_data';

import 'package:rhino_viewer/core/services/file_service.dart';

/// Bytes that pass the .3dm magic check, padded with [payload].
Uint8List rhinoBytes([String payload = 'body']) =>
    Uint8List.fromList([...FileService.magicBytes, ...utf8.encode(payload)]);

/// Splits [bytes] into a stream of fixed-size chunks.
Stream<List<int>> chunked(List<int> bytes, int chunkSize) async* {
  for (var i = 0; i < bytes.length; i += chunkSize) {
    yield bytes.sublist(
      i,
      i + chunkSize > bytes.length ? bytes.length : i + chunkSize,
    );
  }
}

const Map<String, dynamic> sampleStatsJson = {
  'objects': 237,
  'meshes': 12,
  'triangles': 48210,
  'vertices': 26011,
  'curves': 218,
  'points': 1,
  'pointClouds': 1,
  'blocks': 0,
  'lights': 2,
  'other': 4,
  'layers': [
    {
      'index': 0,
      'name': 'Default',
      'fullPath': 'Default',
      'color': '#FF8800',
      'visible': true,
      'objectCount': 12,
    },
    {
      'index': 1,
      'name': 'HIDDEN',
      'fullPath': 'Parts::HIDDEN',
      'color': '#00FF00',
      'visible': false,
      'objectCount': 3,
    },
  ],
  'unmeshed': {'breps': 2, 'extrusions': 1, 'total': 3},
  'bbox': {
    'min': [-10, -20, 0],
    'max': [10, 20, 5.5],
  },
  'units': 'Millimeters',
  'timings': {'fetchMs': 12, 'parseMs': 240, 'buildMs': 30, 'totalMs': 282},
  'warnings': [
    {'type': 'no mesh', 'message': 'Brep abc has no render mesh'},
  ],
};
