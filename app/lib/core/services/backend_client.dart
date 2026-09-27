import 'dart:async';
import 'dart:convert';
import 'dart:io';
import 'dart:math' as math;
import 'dart:typed_data';

import 'package:http/http.dart' as http;

enum MeshQuality {
  draft('draft'),
  standard('default'),
  fine('fine');

  const MeshQuality(this.wireName);

  /// Value of the `quality` query parameter (ARCHITECTURE.md §4.2).
  final String wireName;

  static MeshQuality fromWire(String value) => MeshQuality.values.firstWhere(
    (q) => q.wireName == value,
    orElse: () => MeshQuality.standard,
  );
}

/// Reports upload progress of [BackendClient.mesh] / [BackendClient.convert]
/// as bytes handed to the socket out of the request body size.
typedef UploadProgressCallback = void Function(int sent, int total);

/// Cancels an in-flight [BackendClient.mesh] / [BackendClient.convert] call:
/// the request is aborted and the call fails with code `cancelled`.
class CancelToken {
  final Completer<void> _completer = Completer<void>();

  bool get isCancelled => _completer.isCompleted;

  /// Completes when [cancel] is called; never completes with an error.
  Future<void> get whenCancelled => _completer.future;

  void cancel() {
    if (!_completer.isCompleted) _completer.complete();
  }
}

/// Raised for any failed backend call. [statusCode] is 0 when the request
/// never produced an HTTP response (network error, timeout, cancellation).
class BackendException implements Exception {
  const BackendException({
    required this.statusCode,
    required this.code,
    required this.detail,
  });

  final int statusCode;
  final String code;
  final String detail;

  @override
  String toString() =>
      statusCode == 0 ? '$code: $detail' : 'HTTP $statusCode $code: $detail';
}

class HealthInfo {
  const HealthInfo({
    required this.ok,
    required this.version,
    required this.uptimeSec,
    required this.computeUrl,
    required this.computeConfigured,
    required this.computeReachable,
  });

  factory HealthInfo.fromJson(Map<String, dynamic> json) {
    final compute = json['compute'];
    final computeMap = compute is Map
        ? Map<String, dynamic>.from(compute)
        : const <String, dynamic>{};
    return HealthInfo(
      ok: json['ok'] == true,
      version: '${json['version'] ?? '?'}',
      uptimeSec: (json['uptimeSec'] is num)
          ? (json['uptimeSec'] as num).round()
          : 0,
      computeUrl: '${computeMap['url'] ?? ''}',
      computeConfigured: computeMap['configured'] == true,
      computeReachable: computeMap['reachable'] is bool
          ? computeMap['reachable'] as bool
          : null,
    );
  }

  final bool ok;
  final String version;
  final int uptimeSec;
  final String computeUrl;
  final bool computeConfigured;

  /// null when the server has no Compute configured.
  final bool? computeReachable;
}

class MeshResult {
  const MeshResult({
    required this.bytes,
    required this.meshedCount,
    required this.skippedCount,
    required this.computeMs,
  });

  final Uint8List bytes;
  final int meshedCount;
  final int skippedCount;
  final int computeMs;
}

class ConvertResult {
  const ConvertResult({
    required this.bytes,
    required this.objectCount,
    required this.triangleCount,
    required this.skippedCount,
  });

  final Uint8List bytes;
  final int objectCount;
  final int triangleCount;
  final int skippedCount;
}

/// Client for the optional appserver (ARCHITECTURE.md §4.2).
class BackendClient {
  BackendClient({
    required this._client,
    this.healthTimeout = const Duration(seconds: 8),
    this.meshTimeout = const Duration(minutes: 10),
  });

  final http.Client _client;
  final Duration healthTimeout;
  final Duration meshTimeout;

  /// Builds `<base>/<path>` tolerating a missing scheme and trailing slashes.
  /// Throws a `bad_url` [BackendException] for input `dart:io` would reject.
  static Uri endpoint(
    String baseUrl,
    String path, {
    Map<String, String> query = const {},
  }) {
    var base = baseUrl.trim();
    if (!base.contains('://')) base = 'http://$base';
    base = base.replaceAll(RegExp(r'/+$'), '');
    final Uri uri;
    try {
      uri = Uri.parse('$base/$path');
    } on FormatException catch (e) {
      throw _badUrl(e.message);
    }
    if (uri.scheme != 'http' && uri.scheme != 'https') {
      throw _badUrl('Unsupported scheme "${uri.scheme}"');
    }
    if (uri.host.isEmpty) throw _badUrl('Missing host');
    if (uri.hasPort && (uri.port < 1 || uri.port > 65535)) {
      throw _badUrl('Invalid port ${uri.port}');
    }
    return query.isEmpty ? uri : uri.replace(queryParameters: query);
  }

  Future<HealthInfo> health(String baseUrl, {String? apiKey}) async {
    final response = await _guard(
      () => _client
          .get(endpoint(baseUrl, 'health'), headers: _headers(apiKey))
          .timeout(healthTimeout),
    );
    _throwIfError(response);
    final Object? decoded;
    try {
      decoded = jsonDecode(utf8.decode(response.bodyBytes));
    } on FormatException {
      throw BackendException(
        statusCode: response.statusCode,
        code: 'bad_response',
        detail: 'Health response is not JSON (not the appserver?)',
      );
    }
    if (decoded is! Map) {
      throw BackendException(
        statusCode: response.statusCode,
        code: 'bad_response',
        detail: 'Health response is not a JSON object',
      );
    }
    return HealthInfo.fromJson(Map<String, dynamic>.from(decoded));
  }

  Future<MeshResult> mesh(
    String baseUrl, {
    required Uint8List bytes,
    required String name,
    MeshQuality quality = MeshQuality.standard,
    String? apiKey,
    CancelToken? cancel,
    UploadProgressCallback? onUploadProgress,
  }) async {
    final response = await _post(
      endpoint(
        baseUrl,
        'mesh',
        query: {'quality': quality.wireName, 'name': name},
      ),
      bytes,
      apiKey,
      cancel: cancel,
      onUploadProgress: onUploadProgress,
    );
    return MeshResult(
      bytes: response.bodyBytes,
      meshedCount: _headerInt(response, 'x-meshed-count'),
      skippedCount: _headerInt(response, 'x-skipped-count'),
      computeMs: _headerInt(response, 'x-compute-ms'),
    );
  }

  Future<ConvertResult> convert(
    String baseUrl, {
    required Uint8List bytes,
    required String name,
    MeshQuality quality = MeshQuality.standard,
    String? apiKey,
    CancelToken? cancel,
    UploadProgressCallback? onUploadProgress,
  }) async {
    final response = await _post(
      endpoint(
        baseUrl,
        'convert',
        query: {'quality': quality.wireName, 'name': name},
      ),
      bytes,
      apiKey,
      cancel: cancel,
      onUploadProgress: onUploadProgress,
    );
    return ConvertResult(
      bytes: response.bodyBytes,
      objectCount: _headerInt(response, 'x-object-count'),
      triangleCount: _headerInt(response, 'x-triangle-count'),
      skippedCount: _headerInt(response, 'x-skipped-count'),
    );
  }

  Future<http.Response> _post(
    Uri uri,
    Uint8List body,
    String? apiKey, {
    CancelToken? cancel,
    UploadProgressCallback? onUploadProgress,
  }) async {
    final request =
        _UploadRequest(
            uri,
            body,
            abortTrigger: cancel?.whenCancelled,
            onProgress: onUploadProgress,
          )
          ..headers.addAll({
            ..._headers(apiKey),
            HttpHeaders.contentTypeHeader: 'application/octet-stream',
          });
    final http.Response response;
    try {
      response = await _guard(
        () => _client
            .send(request)
            .then(http.Response.fromStream)
            .timeout(meshTimeout),
        cancel: cancel,
      );
    } on BackendException catch (e) {
      // The appserver refuses an oversize body from its Content-Length with
      // 413 + `Connection: close` and drops the socket while the phone is
      // still sending. dart:io then reports the failed write rather than the
      // response already in its buffer (HttpClientRequest.done waits on both
      // with eagerError), so the 413 itself never reaches this code.
      if (e.code == 'network' && _uploadCutPattern.hasMatch(e.detail)) {
        final mb = (body.length / (1 << 20)).toStringAsFixed(1);
        throw BackendException(
          statusCode: 0,
          code: 'upload_rejected',
          detail:
              'The server closed the connection while the file ($mb MB) was '
              'being uploaded; this is how it refuses a file above its '
              'MAX_UPLOAD_MB limit',
        );
      }
      rethrow;
    }
    _throwIfError(response);
    return response;
  }

  // dart:io / package:http texts for a socket the peer closed mid-write.
  static final RegExp _uploadCutPattern = RegExp(
    r'Write failed|Broken pipe|Connection reset|closed while sending',
    caseSensitive: false,
  );

  Map<String, String> _headers(String? apiKey) => {
    if (apiKey != null && apiKey.isNotEmpty) 'X-Api-Key': apiKey,
  };

  static int _headerInt(http.Response response, String name) =>
      int.tryParse(response.headers[name] ?? '') ?? 0;

  static BackendException _badUrl(String detail) =>
      BackendException(statusCode: 0, code: 'bad_url', detail: detail);

  static Future<http.Response> _guard(
    Future<http.Response> Function() request, {
    CancelToken? cancel,
  }) async {
    try {
      return await _cancellable(request(), cancel);
    } on BackendException {
      rethrow;
    } on TimeoutException {
      throw const BackendException(
        statusCode: 0,
        code: 'timeout',
        detail: 'The server did not respond in time',
      );
    } on http.ClientException catch (e) {
      throw BackendException(statusCode: 0, code: 'network', detail: e.message);
    } on SocketException catch (e) {
      throw BackendException(statusCode: 0, code: 'network', detail: e.message);
    } on IOException catch (e) {
      // TLS handshake / certificate failures are not wrapped by package:http.
      throw BackendException(statusCode: 0, code: 'network', detail: '$e');
    } on FormatException catch (e) {
      // dart:io rejects some host spellings only when connecting.
      throw _badUrl(e.message);
    }
  }

  // The abort trigger makes clients that support it fail the request right
  // away; racing the token as well keeps the caller from waiting out the
  // timeout with clients that ignore it, and turns whatever error the abort
  // produced into `cancelled`.
  static Future<http.Response> _cancellable(
    Future<http.Response> pending,
    CancelToken? cancel,
  ) async {
    if (cancel == null) return pending;
    try {
      return await Future.any([
        pending,
        cancel.whenCancelled.then((_) => throw _cancelled()),
      ]);
    } catch (_) {
      if (cancel.isCancelled) throw _cancelled();
      rethrow;
    }
  }

  static BackendException _cancelled() => const BackendException(
    statusCode: 0,
    code: 'cancelled',
    detail: 'Cancelled',
  );

  static void _throwIfError(http.Response response) {
    if (response.statusCode >= 200 && response.statusCode < 300) return;
    var code = 'http_${response.statusCode}';
    var detail = response.reasonPhrase ?? '';
    try {
      final decoded = jsonDecode(utf8.decode(response.bodyBytes));
      if (decoded is Map) {
        code = '${decoded['error'] ?? code}';
        detail = '${decoded['detail'] ?? detail}';
      }
    } on FormatException {
      // Non-JSON error body: keep the HTTP reason phrase.
    }
    throw BackendException(
      statusCode: response.statusCode,
      code: code,
      detail: detail,
    );
  }
}

/// Octet-stream POST whose body is pulled chunk by chunk, so the progress
/// callback tracks what the socket has accepted rather than what was
/// buffered up front (dart:io propagates the socket's backpressure to the
/// body stream).
class _UploadRequest extends http.BaseRequest with http.Abortable {
  _UploadRequest(
    Uri url,
    this._body, {
    required this.abortTrigger,
    required this.onProgress,
  }) : super('POST', url) {
    contentLength = _body.length;
  }

  static const int chunkSize = 256 << 10;

  final Uint8List _body;
  final UploadProgressCallback? onProgress;

  @override
  final Future<void>? abortTrigger;

  @override
  http.ByteStream finalize() {
    super.finalize();
    return http.ByteStream(_chunks());
  }

  Stream<List<int>> _chunks() async* {
    onProgress?.call(0, _body.length);
    for (var offset = 0; offset < _body.length; offset += chunkSize) {
      final end = math.min(offset + chunkSize, _body.length);
      // yield resumes only once the consumer has taken the chunk.
      yield Uint8List.sublistView(_body, offset, end);
      onProgress?.call(end, _body.length);
    }
  }
}
