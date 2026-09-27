import 'package:flutter/services.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:rhino_viewer/core/services/device_info_service.dart';

void main() {
  TestWidgetsFlutterBinding.ensureInitialized();
  const service = DeviceInfoService();
  final messenger =
      TestDefaultBinaryMessengerBinding.instance.defaultBinaryMessenger;

  tearDown(() => messenger.setMockMethodCallHandler(service.channel, null));

  test('reads the map MainActivity sends', () async {
    messenger.setMockMethodCallHandler(service.channel, (call) async {
      expect(call.method, 'getDeviceInfo');
      return {
        'ramTotal': 8 << 30,
        'ramAvailable': 3 << 30,
        'storageTotal': 128 << 30,
        'storageFree': 40 << 30,
        'glEs': '3.2',
        'versionName': '0.4.0',
        'versionCode': 4,
        'model': 'Samsung SM-A546',
        'android': '14',
      };
    });
    final info = (await service.read())!;
    expect(info.ramUsed, 5 << 30);
    expect(info.storageFree, 40 << 30);
    expect(info.glEs, '3.2');
    expect(info.versionCode, 4);
    expect(info.model, 'Samsung SM-A546');
  });

  test('null without an Android side or on failure', () async {
    expect(await service.read(), isNull);
    messenger.setMockMethodCallHandler(
      service.channel,
      (_) async => throw PlatformException(code: 'x'),
    );
    expect(await service.read(), isNull);
  });
}
