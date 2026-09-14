import 'dart:io';

import 'package:crypto/crypto.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:rhino_viewer/core/services/file_service.dart';

import 'support/fixtures.dart';

void main() {
  late Directory dir;

  setUp(() async {
    dir = await Directory.systemTemp.createTemp('file_service_test');
  });

  tearDown(() async {
    if (await dir.exists()) await dir.delete(recursive: true);
  });

  test('hasMagic', () {
    expect(FileService.hasMagic(rhinoBytes()), isTrue);
    expect(FileService.hasMagic(FileService.magicBytes), isTrue);
    expect(FileService.hasMagic(FileService.magicBytes.sublist(0, 5)), isFalse);
    expect(FileService.hasMagic([0x50, 0x4B, 3, 4]), isFalse);
  });

  test('importStream stores <sha256>.3dm, hashes the content and cleans temp files', () async {
    final service = FileService(modelsDir: Directory('${dir.path}/models'));
    final bytes = rhinoBytes('hello');
    final imported = await service.importStream(
      chunked(bytes, 7),
      name: 'hello.3dm',
    );
    expect(imported.sha, sha256.convert(bytes).toString());
    expect(imported.name, 'hello.3dm');
    expect(imported.size, bytes.length);
    expect(imported.file.path, '${dir.path}/models/${imported.sha}.3dm');
    expect(await imported.file.readAsBytes(), bytes);
    expect(service.modelsDir.listSync().map((e) => e.path), [
      imported.file.path,
    ]);
  });

  test('magic spanning several small chunks is still accepted', () async {
    final service = FileService(modelsDir: dir);
    final imported = await service.importStream(
      chunked(rhinoBytes(), 3),
      name: 'n',
    );
    expect(await imported.file.exists(), isTrue);
  });

  test(
    'rejects non-Rhino content and short files, leaving no files behind',
    () async {
      final service = FileService(modelsDir: dir);
      await expectLater(
        service.importStream(
          chunked(List.filled(100, 0x41), 10),
          name: 'x.txt',
        ),
        throwsA(
          isA<InvalidModelFileException>().having(
            (e) => e.message,
            'message',
            contains('x.txt'),
          ),
        ),
      );
      await expectLater(
        service.importStream(chunked([0x33, 0x44], 2), name: 'short'),
        throwsA(isA<InvalidModelFileException>()),
      );
      expect(dir.listSync(), isEmpty);
    },
  );

  test('importing the same content twice is idempotent', () async {
    final service = FileService(modelsDir: dir);
    final a = await service.importStream(
      chunked(rhinoBytes('same'), 5),
      name: 'a',
    );
    final b = await service.importStream(
      chunked(rhinoBytes('same'), 50),
      name: 'b',
    );
    expect(a.sha, b.sha);
    expect(dir.listSync(), hasLength(1));
  });

  test('importFile derives the name from the path', () async {
    final service = FileService(modelsDir: Directory('${dir.path}/m'));
    final incoming = File('${dir.path}/incoming/Bracket v2.3dm');
    await incoming.create(recursive: true);
    await incoming.writeAsBytes(rhinoBytes());
    final imported = await service.importFile(incoming);
    expect(imported.name, 'Bracket v2.3dm');
  });

  test(
    'pickAndImport returns null on cancel and cleans up after a pick',
    () async {
      var cleaned = 0;
      ModelSource? next;
      final service = FileService(modelsDir: dir, picker: () async => next);
      expect(await service.pickAndImport(), isNull);

      next = ModelSource(
        name: 'picked.3dm',
        open: () => chunked(rhinoBytes('p'), 4),
        cleanup: () async => cleaned++,
      );
      final imported = await service.pickAndImport();
      expect(imported?.name, 'picked.3dm');
      expect(cleaned, 1);

      next = ModelSource(
        name: 'bad.bin',
        open: () => chunked(List.filled(40, 7), 8),
        cleanup: () async => cleaned++,
      );
      await expectLater(
        service.pickAndImport(),
        throwsA(isA<InvalidModelFileException>()),
      );
      expect(cleaned, 2, reason: 'cleanup runs even when the import fails');
    },
  );

  test(
    'preferredFileName prefers the meshed variant; writeMeshed validates magic',
    () async {
      final service = FileService(modelsDir: dir);
      expect(await service.preferredFileName('s'), 's.3dm');
      await expectLater(
        service.writeMeshed('s', [1, 2, 3]),
        throwsA(isA<InvalidModelFileException>()),
      );
      final meshed = await service.writeMeshed('s', rhinoBytes('meshed'));
      expect(meshed.path, service.meshedFile('s').path);
      expect(await service.preferredFileName('s'), 's.meshed.3dm');
    },
  );
}
