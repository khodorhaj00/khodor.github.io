import 'json_helpers.dart';

/// One entry of the `recents_v1` list (ARCHITECTURE.md §3.2).
class RecentFile {
  const RecentFile({
    required this.sha,
    required this.name,
    required this.size,
    required this.addedAt,
    required this.lastOpenedAt,
    this.meshed = false,
  });

  factory RecentFile.fromJson(Map<String, dynamic> json) => RecentFile(
    sha: readString(json['sha']),
    name: readString(json['name'], fallback: 'untitled.3dm'),
    size: readInt(json['size']),
    addedAt: _readDate(json['addedAt']),
    lastOpenedAt: _readDate(json['lastOpenedAt']),
    meshed: readBool(json['meshed']),
  );

  static DateTime _readDate(Object? value) => switch (value) {
    int ms => DateTime.fromMillisecondsSinceEpoch(ms, isUtc: true),
    String s =>
      DateTime.tryParse(s) ??
          DateTime.fromMillisecondsSinceEpoch(0, isUtc: true),
    _ => DateTime.fromMillisecondsSinceEpoch(0, isUtc: true),
  };

  /// sha256 of the original file content; also the on-disk file stem.
  final String sha;

  /// Original display name (e.g. `bracket_v3.3dm`).
  final String name;

  /// Size in bytes of the original file.
  final int size;
  final DateTime addedAt;
  final DateTime lastOpenedAt;

  /// True when a server-meshed `<sha>.meshed.3dm` exists next to the original.
  final bool meshed;

  Map<String, dynamic> toJson() => {
    'sha': sha,
    'name': name,
    'size': size,
    'addedAt': addedAt.toUtc().millisecondsSinceEpoch,
    'lastOpenedAt': lastOpenedAt.toUtc().millisecondsSinceEpoch,
    'meshed': meshed,
  };

  RecentFile copyWith({
    String? name,
    int? size,
    DateTime? addedAt,
    DateTime? lastOpenedAt,
    bool? meshed,
  }) => RecentFile(
    sha: sha,
    name: name ?? this.name,
    size: size ?? this.size,
    addedAt: addedAt ?? this.addedAt,
    lastOpenedAt: lastOpenedAt ?? this.lastOpenedAt,
    meshed: meshed ?? this.meshed,
  );
}
