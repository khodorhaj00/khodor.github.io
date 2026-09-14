import 'dart:convert';
import 'dart:typed_data';

import 'package:flutter_test/flutter_test.dart';
import 'package:http/http.dart' as http;
import 'package:http/testing.dart';
import 'package:rhino_viewer/core/services/backend_client.dart';

void main() {
  group('endpoint', () {
    test('adds a scheme, strips trailing slashes, appends query', () {
      expect(
        BackendClient.endpoint('192.168.1.5:8080', 'health').toString(),
        'http://192.168.1.5:8080/health',
      );
      expect(
        BackendClient.endpoint('https://srv.example.com/', 'mesh').toString(),
        'https://srv.example.com/mesh',
      );
      expect(
        BackendClient.endpoint(' http://h/api// ', 'convert').toString(),
        'http://h/api/convert',
      );
      final withQuery = BackendClient.endpoint(
        'http://h',
        'mesh',
        query: {'quality': 'fine', 'name': 'a b.3dm'},
      );
      expect(withQuery.queryParameters, {'quality': 'fine', 'name': 'a b.3dm'});
    });
  });

  group('health', () {
    test('parses the response and sends the api key', () async {
      late http.Request seen;
      final client = MockClient((request) async {
        seen = request;
        return http.Response(
          jsonEncode({
            'ok': true,
            'version': '1.2.3',
            'uptimeSec': 42.7,
            'compute': {
              'url': 'http://win:5000/',
              'configured': true,
              'reachable': false,
            },
          }),
          200,
        );
      });
      final info = await BackendClient(client: client)
          .health('http://h', apiKey: 'k');
      expect(seen.url.toString(), 'http://h/health');
      expect(seen.headers['X-Api-Key'], 'k');
      expect(info.ok, isTrue);
      expect(info.version, '1.2.3');
      expect(info.uptimeSec, 43);
      expect(info.computeUrl, 'http://win:5000/');
      expect(info.computeConfigured, isTrue);
      expect(info.computeReachable, isFalse);
    });

    test(
      'compute.reachable null when not configured; no key header when empty',
      () async {
        late http.Request seen;
        final client = MockClient((request) async {
          seen = request;
          return http.Response(
            jsonEncode({
              'ok': true,
              'version': '1',
              'uptimeSec': 1,
              'compute': {'configured': false, 'reachable': null},
            }),
            200,
          );
        });
        final info = await BackendClient(client: client)
            .health('http://h', apiKey: '');
        expect(seen.headers.containsKey('X-Api-Key'), isFalse);
        expect(info.computeReachable, isNull);
      },
    );

    test('maps JSON error bodies to BackendException', () async {
      final client = MockClient(
        (_) async => http.Response(
          jsonEncode({'error': 'unauthorized', 'detail': 'bad key'}),
          401,
        ),
      );
      expect(
        () => BackendClient(client: client).health('http://h'),
        throwsA(
          isA<BackendException>()
              .having((e) => e.statusCode, 'status', 401)
              .having((e) => e.code, 'code', 'unauthorized')
              .having((e) => e.detail, 'detail', 'bad key'),
        ),
      );
    });

    test('non-JSON error body keeps the HTTP code', () async {
      final client = MockClient(
        (_) async => http.Response('<html>', 502, reasonPhrase: 'Bad Gateway'),
      );
      expect(
        () => BackendClient(client: client).health('http://h'),
        throwsA(
          isA<BackendException>()
              .having((e) => e.code, 'code', 'http_502')
              .having((e) => e.detail, 'detail', 'Bad Gateway'),
        ),
      );
    });

    test('network failures become statusCode 0', () async {
      final client = MockClient(
        (_) async => throw http.ClientException('refused'),
      );
      expect(
        () => BackendClient(client: client).health('http://h'),
        throwsA(
          isA<BackendException>()
              .having((e) => e.statusCode, 'status', 0)
              .having((e) => e.code, 'code', 'network'),
        ),
      );
    });

    test('timeouts become statusCode 0 / timeout', () async {
      final client = MockClient((_) async {
        await Future<void>.delayed(const Duration(milliseconds: 200));
        return http.Response('{}', 200);
      });
      final backend = BackendClient(
        client: client,
        healthTimeout: const Duration(milliseconds: 20),
      );
      expect(
        () => backend.health('http://h'),
        throwsA(
          isA<BackendException>().having((e) => e.code, 'code', 'timeout'),
        ),
      );
    });
  });

  group('mesh / convert', () {
    final body = Uint8List.fromList(List.generate(64, (i) => i));

    test(
      'posts octet-stream with quality/name and reads the count headers',
      () async {
        late http.Request seen;
        final client = MockClient((request) async {
          seen = request;
          return http.Response.bytes(
            [1, 2, 3],
            200,
            headers: {
              'x-meshed-count': '2',
              'x-skipped-count': '1',
              'x-compute-ms': '350',
            },
          );
        });
        final result = await BackendClient(client: client).mesh(
          'http://h/',
          bytes: body,
          name: 'part.3dm',
          quality: MeshQuality.fine,
          apiKey: 'k',
        );
        expect(seen.method, 'POST');
        expect(seen.url.path, '/mesh');
        expect(seen.url.queryParameters, {
          'quality': 'fine',
          'name': 'part.3dm',
        });
        expect(seen.headers['content-type'], 'application/octet-stream');
        expect(seen.headers['X-Api-Key'], 'k');
        expect(seen.bodyBytes, body);
        expect(result.bytes, [1, 2, 3]);
        expect(result.meshedCount, 2);
        expect(result.skippedCount, 1);
        expect(result.computeMs, 350);
      },
    );

    test(
      'convert reads object/triangle headers and defaults missing ones to 0',
      () async {
        final client = MockClient(
          (_) async => http.Response.bytes(
            [9],
            200,
            headers: {'x-object-count': '5', 'x-triangle-count': '60'},
          ),
        );
        final result = await BackendClient(client: client)
            .convert('http://h', bytes: body, name: 'n');
        expect(result.objectCount, 5);
        expect(result.triangleCount, 60);
        expect(result.skippedCount, 0);
        expect(result.bytes, [9]);
      },
    );

    test('502 compute_unreachable surfaces code and detail', () async {
      final client = MockClient(
        (_) async => http.Response(
          jsonEncode({
            'error': 'compute_unreachable',
            'detail': 'ECONNREFUSED',
          }),
          502,
        ),
      );
      expect(
        () =>
            BackendClient(client: client)
                .mesh('http://h', bytes: body, name: 'n'),
        throwsA(
          isA<BackendException>()
              .having((e) => e.code, 'code', 'compute_unreachable')
              .having((e) => e.toString(), 'text', contains('ECONNREFUSED')),
        ),
      );
    });
  });

  test('MeshQuality wire names', () {
    expect(MeshQuality.standard.wireName, 'default');
    expect(MeshQuality.fromWire('draft'), MeshQuality.draft);
    expect(MeshQuality.fromWire('bogus'), MeshQuality.standard);
  });
}
