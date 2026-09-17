/// Options understood by the viewer page (ARCHITECTURE.md §2.1), shared by
/// the bridge, the settings and the viewer screen.
library;

/// Rhino object categories behind the Objects sheet: each can be hidden
/// (`viewer.setCategoryVisible`) and excluded from selection
/// (`viewer.setCategoryPickable`). Everything inside a block instance also
/// follows [blocks].
enum ObjectCategory {
  surfaces('surfaces', 'Surfaces & solids'),
  meshes('meshes', 'Meshes'),
  curves('curves', 'Curves'),
  points('points', 'Points'),
  annotations('annotations', 'Annotations'),
  hatches('hatches', 'Hatches'),
  blocks('blocks', 'Blocks');

  const ObjectCategory(this.wireName, this.label);

  final String wireName;
  final String label;

  static ObjectCategory? fromWire(String value) {
    for (final category in values) {
      if (category.wireName == value) return category;
    }
    return null;
  }
}

/// How finely curves are sampled while a file is parsed
/// (`viewer.setCurveQuality`, applies to the next load).
enum CurveQuality {
  standard('standard', 'Standard'),
  high('high', 'High'),
  max('max', 'Max');

  const CurveQuality(this.wireName, this.label);

  final String wireName;
  final String label;

  static CurveQuality fromWire(String value) => values.firstWhere(
    (quality) => quality.wireName == value,
    orElse: () => CurveQuality.high,
  );
}

/// The rendered display mode with the file's materials only ([basic]), or
/// with their textures and cast shadows as well ([full]).
enum RenderQuality {
  basic('basic'),
  full('full');

  const RenderQuality(this.wireName);

  final String wireName;
}
