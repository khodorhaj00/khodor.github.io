/// Options understood by the viewer page (ARCHITECTURE.md §2.1), shared by the
/// bridge, the settings and the viewer screen.
///
/// Every list here mirrors one in `app/assets/viewer/config.js`: the wire names
/// must match. docs/CUSTOMISING.md says what to edit to add or change a choice.
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

/// How finely everything is drawn: curve sampling and SubD smoothness (applied
/// when a file is opened), label and canvas resolution (applied at once).
/// Surfaces keep the render mesh Rhino saved in the file.
enum ViewQuality {
  draft('draft', 'Draft'),
  normal('normal', 'Normal'),
  fine('fine', 'Fine'),
  ultra('ultra', 'Ultra');

  const ViewQuality(this.wireName, this.label);

  final String wireName;
  final String label;

  static ViewQuality fromWire(String value) => values.firstWhere(
    (quality) => quality.wireName == value,
    orElse: () => ViewQuality.normal,
  );
}

/// Annotation size, as a multiple of the size Rhino stores.
enum AnnotationSize {
  small('small', 'Small'),
  medium('medium', 'Medium'),
  large('large', 'Large');

  const AnnotationSize(this.wireName, this.label);

  final String wireName;
  final String label;

  static AnnotationSize fromWire(String value) => values.firstWhere(
    (size) => size.wireName == value,
    orElse: () => AnnotationSize.medium,
  );
}

/// One colour for every dimension, or for every text.
enum AnnotationColorChoice {
  file('file', 'From file', null),
  white('white', 'White', 0xFFE6E8EB),
  amber('amber', 'Amber', 0xFFFFB020),
  cyan('cyan', 'Cyan', 0xFF3DA5FF),
  red('red', 'Red', 0xFFFF4D4F);

  const AnnotationColorChoice(this.wireName, this.label, this.argb);

  final String wireName;
  final String label;

  /// Swatch colour, or null for "From file".
  final int? argb;

  static AnnotationColorChoice fromWire(String value) => values.firstWhere(
    (choice) => choice.wireName == value,
    orElse: () => AnnotationColorChoice.file,
  );
}

/// One font for every dimension, or for every text. The bundled Liberation
/// faces match Arial, Times New Roman and Courier New.
enum AnnotationFontChoice {
  file('file', 'From file'),
  sans('sans', 'Sans'),
  serif('serif', 'Serif'),
  mono('mono', 'Mono'),
  system('system', 'Phone default');

  const AnnotationFontChoice(this.wireName, this.label);

  final String wireName;
  final String label;

  static AnnotationFontChoice fromWire(String value) => values.firstWhere(
    (choice) => choice.wireName == value,
    orElse: () => AnnotationFontChoice.file,
  );
}

/// The unit every length is shown in: dimensions, the caliper and the picked
/// object. [file] keeps the model's own unit and the number Rhino wrote;
/// [custom] multiplies the model's own units by a factor.
enum DisplayUnit {
  file('file', 'From file', null, '', 1),
  mm('mm', 'mm', 1, 'mm', 0),
  cm('cm', 'cm', 10, 'cm', 1),
  m('m', 'm', 1000, 'm', 2),
  inch('inch', 'inch', 25.4, '"', 2),
  custom('custom', 'Custom ×', null, '', 2);

  const DisplayUnit(
    this.wireName,
    this.label,
    this.mmPerUnit,
    this.symbol,
    this.decimals,
  );

  final String wireName;
  final String label;

  /// Millimetres in one of these units; null for [file] and [custom].
  final double? mmPerUnit;
  final String symbol;
  final int decimals;

  static DisplayUnit fromWire(String value) => values.firstWhere(
    (unit) => unit.wireName == value,
    orElse: () => DisplayUnit.cm,
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
