import 'dart:async';
import 'dart:convert';
import 'dart:io';
import 'dart:typed_data';

import 'package:crypto/crypto.dart';
import 'package:file_picker/file_picker.dart';

class InvalidModelFileException implements Exception {
  const InvalidModelFileException(this.message);

  final String message;

  @override
  String toString() => message;
}

/// A file the user picked, before it is validated and copied into the cache.
class ModelSource {
  const ModelSource({required this.name, required this.open, this.cleanup});

  final String name;
  final Stream<List<int>> Function() open;

  /// Releases any temporary copy the picker made; called after import.
  final Future<void> Function()? cleanup;
}

typedef ModelPicker = Future<ModelSource?> Function();

class ImportedModel {
  const ImportedModel({
    required this.sha,
    required this.name,
    required this.size,
    required this.file,
  });

  final String sha;
  final String name;
  final int size;
  final File file;
}

/// Validates, hashes and stores `.3dm` files in [modelsDir]
/// (ARCHITECTURE.md §3.2): `<sha256>.3dm`, plus `<sha256>.meshed.3dm` for
/// server-meshed results.
class FileService {
  FileService({required this.modelsDir, ModelPicker? picker})
    : _pick = picker ?? _pickWithFilePicker;

  static const String magic = '3D Geometry File Format';
  static final Uint8List magicBytes = Uint8List.fromList(ascii.encode(magic));

  final Directory modelsDir;
  final ModelPicker _pick;

  static bool hasMagic(List<int> head) {
    if (head.length < magicBytes.length) return false;
    for (var i = 0; i < magicBytes.length; i++) {
      if (head[i] != magicBytes[i]) return false;
    }
    return true;
  }

  File originalFile(String sha) => File('${modelsDir.path}/$sha.3dm');

  File meshedFile(String sha) => File('${modelsDir.path}/$sha.meshed.3dm');

  /// The file name (inside [modelsDir]) the viewer should load: the
  /// server-meshed variant when it exists, else the original.
  Future<String> preferredFileName(String sha) async =>
      await meshedFile(sha).exists() ? '$sha.meshed.3dm' : '$sha.3dm';

  /// Opens the system picker and imports the chosen file. Returns null when
  /// the user cancels; throws [InvalidModelFileException] for non-.3dm data.
  Future<ImportedModel?> pickAndImport() async {
    final source = await _pick();
    if (source == null) return null;
    try {
      return await importStream(source.open(), name: source.name);
    } finally {
      await source.cleanup?.call();
    }
  }

  Future<ImportedModel> importFile(File file, {String? name}) =>
      importStream(file.openRead(), name: name ?? _baseName(file.path));

  /// Streams [source] into `modelsDir/<sha256>.3dm`, checking the magic on
  /// the first bytes and hashing while copying so the file is read once.
  Future<ImportedModel> importStream(
    Stream<List<int>> source, {
    required String name,
  }) async {
    await modelsDir.create(recursive: true);
    final temp = File(
      '${modelsDir.path}/.import-${DateTime.now().microsecondsSinceEpoch}.tmp',
    );
    final sink = temp.openWrite();
    final digest = _DigestSink();
    final hasher = sha256.startChunkedConversion(digest);
    final head = BytesBuilder(copy: false);
    var magicChecked = false;
    var size = 0;
    try {
      await for (final chunk in source) {
        if (!magicChecked) {
          head.add(chunk);
          if (head.length >= magicBytes.length) {
            if (!hasMagic(head.toBytes())) throw _notRhino(name);
            magicChecked = true;
          }
        }
        hasher.add(chunk);
        sink.add(chunk);
        size += chunk.length;
      }
      if (!magicChecked) throw _notRhino(name);
      hasher.close();
      await sink.close();
      final sha = digest.value.toString();
      final target = originalFile(sha);
      if (await target.exists()) {
        await temp.delete();
      } else {
        await temp.rename(target.path);
      }
      return ImportedModel(sha: sha, name: name, size: size, file: target);
    } catch (_) {
      await sink.close();
      if (await temp.exists()) await temp.delete();
      rethrow;
    }
  }

  Future<File> writeMeshed(String sha, List<int> bytes) async {
    if (!hasMagic(bytes)) {
      throw const InvalidModelFileException(
        'Server response is not a .3dm file',
      );
    }
    final file = meshedFile(sha);
    await file.writeAsBytes(bytes, flush: true);
    return file;
  }

  static InvalidModelFileException _notRhino(String name) =>
      InvalidModelFileException('$name is not a Rhino .3dm file');

  static String _baseName(String path) {
    final cut = path.lastIndexOf(Platform.pathSeparator);
    return cut < 0 ? path : path.substring(cut + 1);
  }

  // Android reports no MIME type for .3dm, so the picker accepts any file and
  // the magic check above decides.
  static Future<ModelSource?> _pickWithFilePicker() async {
    final picked = await FilePicker.pickFile(type: FileType.any);
    if (picked == null) return null;
    return ModelSource(
      name: picked.name,
      open: picked.readAsByteStream,
      cleanup: FilePicker.clearTemporaryFiles,
    );
  }
}

class _DigestSink implements Sink<Digest> {
  late Digest value;

  @override
  void add(Digest data) => value = data;

  @override
  void close() {}
}
