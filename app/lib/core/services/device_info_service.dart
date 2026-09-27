import 'package:flutter/services.dart';

import '../models/json_helpers.dart';

/// What the phone reports about itself, for the home screen's telemetry boxes.
class DeviceInfo {
  const DeviceInfo({
    required this.ramTotal,
    required this.ramAvailable,
    required this.storageTotal,
    required this.storageFree,
    required this.glEs,
    required this.versionName,
    required this.versionCode,
    required this.model,
    required this.android,
  });

  factory DeviceInfo.fromMap(Map<String, dynamic> map) => DeviceInfo(
    ramTotal: readInt(map['ramTotal']),
    ramAvailable: readInt(map['ramAvailable']),
    storageTotal: readInt(map['storageTotal']),
    storageFree: readInt(map['storageFree']),
    glEs: readString(map['glEs']),
    versionName: readString(map['versionName']),
    versionCode: readInt(map['versionCode']),
    model: readString(map['model']),
    android: readString(map['android']),
  );

  /// Bytes.
  final int ramTotal;
  final int ramAvailable;
  final int storageTotal;
  final int storageFree;

  /// The OpenGL ES version the GPU offers, e.g. `3.2`.
  final String glEs;
  final String versionName;
  final int versionCode;
  final String model;
  final String android;

  int get ramUsed => ramTotal - ramAvailable;
}

/// Reads [DeviceInfo] over `MainActivity`'s device channel. Answers null when
/// there is no Android side (tests, other platforms) or it fails.
class DeviceInfoService {
  const DeviceInfoService({this.channel = const MethodChannel(channelName)});

  static const String channelName = 'com.styro3d.rhino_viewer/device';

  final MethodChannel channel;

  Future<DeviceInfo?> read() async {
    try {
      final result = await channel.invokeMapMethod<String, dynamic>(
        'getDeviceInfo',
      );
      return result == null ? null : DeviceInfo.fromMap(result);
    } on MissingPluginException {
      return null;
    } on PlatformException {
      return null;
    }
  }
}
