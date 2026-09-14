import 'package:flutter/services.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:rhino_viewer/core/services/intent_service.dart';

void main() {
  TestWidgetsFlutterBinding.ensureInitialized();
  const channel = MethodChannel('test/intent');
  final messenger =
      TestDefaultBinaryMessengerBinding.instance.defaultBinaryMessenger;

  tearDown(() => messenger.setMockMethodCallHandler(channel, null));

  test('getInitialFile asks Kotlin over the channel', () async {
    final calls = <MethodCall>[];
    messenger.setMockMethodCallHandler(channel, (call) async {
      calls.add(call);
      return '/cache/incoming/part.3dm';
    });
    final service = IntentService(channel: channel);
    expect(await service.getInitialFile(), '/cache/incoming/part.3dm');
    expect(calls.single.method, 'getInitialFile');
    service.dispose();
  });

  test('onFile calls from Kotlin are surfaced on incomingFiles', () async {
    final service = IntentService(channel: channel);
    final received = <String>[];
    final sub = service.incomingFiles.listen(received.add);
    await messenger.handlePlatformMessage(
      channel.name,
      channel.codec.encodeMethodCall(
        const MethodCall('onFile', '/cache/incoming/a.3dm'),
      ),
      (_) {},
    );
    await messenger.handlePlatformMessage(
      channel.name,
      channel.codec.encodeMethodCall(const MethodCall('onFile', 42)),
      (_) {},
    );
    await Future<void>.delayed(Duration.zero);
    await sub.cancel();
    service.dispose();
    expect(received, ['/cache/incoming/a.3dm']);
  });
}
