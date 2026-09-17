import 'dart:convert';

import 'package:flutter/foundation.dart';

import '../models/viewer_options.dart';
import 'backend_client.dart';
import 'key_value_store.dart';

class AppSettings {
  const AppSettings({
    this.backendUrl = '',
    this.apiKey = '',
    this.meshQuality = MeshQuality.standard,
    this.cacheCapMb = 1024,
    this.hybridWebViewComposition = true,
    this.quality = ViewQuality.normal,
    this.annotationSize = AnnotationSize.medium,
    this.dimensionColor = AnnotationColorChoice.file,
    this.dimensionFont = AnnotationFontChoice.file,
    this.textColor = AnnotationColorChoice.file,
    this.textFont = AnnotationFontChoice.file,
    this.unit = DisplayUnit.cm,
    this.customUnitFactor = 1,
  });

  factory AppSettings.fromJson(Map<String, dynamic> json) => AppSettings(
    backendUrl: '${json['backendUrl'] ?? ''}',
    apiKey: '${json['apiKey'] ?? ''}',
    meshQuality: MeshQuality.fromWire('${json['meshQuality'] ?? 'default'}'),
    cacheCapMb: json['cacheCapMb'] is int ? json['cacheCapMb'] as int : 1024,
    hybridWebViewComposition: json['hybridWebViewComposition'] is bool
        ? json['hybridWebViewComposition'] as bool
        : true,
    quality: ViewQuality.fromWire('${json['quality'] ?? 'normal'}'),
    annotationSize: AnnotationSize.fromWire(
      '${json['annotationSize'] ?? 'medium'}',
    ),
    dimensionColor: AnnotationColorChoice.fromWire(
      '${json['dimensionColor'] ?? 'file'}',
    ),
    dimensionFont: AnnotationFontChoice.fromWire(
      '${json['dimensionFont'] ?? 'file'}',
    ),
    textColor: AnnotationColorChoice.fromWire('${json['textColor'] ?? 'file'}'),
    textFont: AnnotationFontChoice.fromWire('${json['textFont'] ?? 'file'}'),
    unit: DisplayUnit.fromWire('${json['unit'] ?? 'cm'}'),
    customUnitFactor: json['customUnitFactor'] is num
        ? (json['customUnitFactor'] as num).toDouble()
        : 1,
  );

  static const List<int> cacheCapChoicesMb = [256, 512, 1024, 2048, 4096];

  final String backendUrl;
  final String apiKey;
  final MeshQuality meshQuality;
  final int cacheCapMb;

  /// How Android composites the viewer's WebView. True (the default) keeps the
  /// real WebView in the Android view tree; false draws it into a Flutter
  /// texture instead. See ARCHITECTURE.md 3.1.
  final bool hybridWebViewComposition;

  /// How finely everything is drawn; curves and SubD apply to the next file
  /// opened, label and canvas resolution at once.
  final ViewQuality quality;

  /// Annotation size, colours and fonts, and the unit lengths are shown in.
  final AnnotationSize annotationSize;
  final AnnotationColorChoice dimensionColor;
  final AnnotationFontChoice dimensionFont;
  final AnnotationColorChoice textColor;
  final AnnotationFontChoice textFont;
  final DisplayUnit unit;

  /// Multiplier for [DisplayUnit.custom].
  final double customUnitFactor;

  /// What the viewer page's `setAnnotationOptions` takes.
  Map<String, Object?> get annotationOptions => {
    'size': annotationSize.wireName,
    'dimColor': dimensionColor.wireName,
    'dimFont': dimensionFont.wireName,
    'textColor': textColor.wireName,
    'textFont': textFont.wireName,
    'unit': unit.wireName,
    'unitFactor': customUnitFactor,
  };

  bool get hasBackend => backendUrl.trim().isNotEmpty;

  int get cacheCapBytes => cacheCapMb * 1024 * 1024;

  Map<String, dynamic> toJson() => {
    'backendUrl': backendUrl,
    'apiKey': apiKey,
    'meshQuality': meshQuality.wireName,
    'cacheCapMb': cacheCapMb,
    'hybridWebViewComposition': hybridWebViewComposition,
    'quality': quality.wireName,
    'annotationSize': annotationSize.wireName,
    'dimensionColor': dimensionColor.wireName,
    'dimensionFont': dimensionFont.wireName,
    'textColor': textColor.wireName,
    'textFont': textFont.wireName,
    'unit': unit.wireName,
    'customUnitFactor': customUnitFactor,
  };

  AppSettings copyWith({
    String? backendUrl,
    String? apiKey,
    MeshQuality? meshQuality,
    int? cacheCapMb,
    bool? hybridWebViewComposition,
    ViewQuality? quality,
    AnnotationSize? annotationSize,
    AnnotationColorChoice? dimensionColor,
    AnnotationFontChoice? dimensionFont,
    AnnotationColorChoice? textColor,
    AnnotationFontChoice? textFont,
    DisplayUnit? unit,
    double? customUnitFactor,
  }) => AppSettings(
    backendUrl: backendUrl ?? this.backendUrl,
    apiKey: apiKey ?? this.apiKey,
    meshQuality: meshQuality ?? this.meshQuality,
    cacheCapMb: cacheCapMb ?? this.cacheCapMb,
    hybridWebViewComposition:
        hybridWebViewComposition ?? this.hybridWebViewComposition,
    quality: quality ?? this.quality,
    annotationSize: annotationSize ?? this.annotationSize,
    dimensionColor: dimensionColor ?? this.dimensionColor,
    dimensionFont: dimensionFont ?? this.dimensionFont,
    textColor: textColor ?? this.textColor,
    textFont: textFont ?? this.textFont,
    unit: unit ?? this.unit,
    customUnitFactor: customUnitFactor ?? this.customUnitFactor,
  );
}

/// Persists [AppSettings] as one JSON document and exposes them as a
/// [ValueListenable] so screens rebuild when they change.
class SettingsService {
  SettingsService(this._store);

  static const String key = 'settings_v1';

  final KeyValueStore _store;
  final ValueNotifier<AppSettings> _notifier = ValueNotifier(
    const AppSettings(),
  );

  ValueListenable<AppSettings> get listenable => _notifier;

  AppSettings get value => _notifier.value;

  Future<void> load() async {
    final raw = await _store.getString(key);
    if (raw == null) return;
    try {
      final decoded = jsonDecode(raw);
      if (decoded is Map) {
        _notifier.value = AppSettings.fromJson(
          Map<String, dynamic>.from(decoded),
        );
      }
    } on FormatException {
      // Corrupt settings: keep defaults; the next save overwrites them.
    }
  }

  Future<void> update(AppSettings settings) async {
    _notifier.value = settings;
    await _store.setString(key, jsonEncode(settings.toJson()));
  }
}
