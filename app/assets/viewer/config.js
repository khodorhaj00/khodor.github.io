// ---------------------------------------------------------------------------------------
// Viewer options — the one file to edit when a choice changes
// ---------------------------------------------------------------------------------------
//
// Every list here is what the app offers in Settings. Adding an entry is a one-line change
// on each side: the id used here must also exist in the Dart enums of
// `app/lib/core/models/viewer_options.dart` (docs/CUSTOMISING.md says where).

/**
 * View quality. `curve` is the chord tolerance as a fraction of a curve's own size, the arc
 * step in degrees and the per-curve point cap; `subdivision` is how often SubD control nets
 * are subdivided; `fontPx` is the height a label's texture is drawn at; `pixelRatio` caps
 * the canvas resolution. Draft and Ultra are the two ends: Ultra costs memory and load time.
 */
export const QUALITY = {
  draft: { curve: { relTol: 2e-3, arcStepDeg: 8, maxPoints: 1000 }, subdivision: 1, fontPx: 24, pixelRatio: 1.5 },
  normal: { curve: { relTol: 5e-4, arcStepDeg: 3, maxPoints: 4000 }, subdivision: 2, fontPx: 40, pixelRatio: 2 },
  fine: { curve: { relTol: 1e-4, arcStepDeg: 1.5, maxPoints: 12000 }, subdivision: 3, fontPx: 64, pixelRatio: 2.5 },
  ultra: { curve: { relTol: 2e-5, arcStepDeg: 0.75, maxPoints: 40000 }, subdivision: 4, fontPx: 96, pixelRatio: 3 },
};

export const DEFAULT_QUALITY = 'normal';

/** Annotation size, as a multiple of the size Rhino stores. */
export const ANNOTATION_SIZES = { small: 0.75, medium: 1, large: 1.5 };

/** Colour for every dimension, or every text: `null` keeps the object's own colour. */
export const ANNOTATION_COLORS = {
  file: null,
  white: 0xE6E8EB,
  amber: 0xFFB020,
  cyan: 0x3DA5FF,
  red: 0xFF4D4F,
};

/**
 * Font for every dimension, or every text. `file` keeps the font named in the .3dm, mapped
 * to its metric-compatible Liberation face; `system` is whatever the phone uses.
 */
export const ANNOTATION_FONTS = {
  file: null,
  sans: '"Liberation Sans", Arial, sans-serif',
  serif: '"Liberation Serif", "Times New Roman", serif',
  mono: '"Liberation Mono", "Courier New", monospace',
  system: 'system-ui, sans-serif',
};

/** Rhino font family → the bundled face with the same metrics. */
export const FONT_ALIASES = [
  { match: /courier|mono|consol/i, stack: ANNOTATION_FONTS.mono },
  { match: /times|georgia|garamond|roman|serif|palatino|cambria|book/i, stack: ANNOTATION_FONTS.serif },
];

export const DEFAULT_FONT_STACK = ANNOTATION_FONTS.sans;

/**
 * How lengths are shown. `mmPerUnit` converts from millimetres; `decimals` is fixed; `file`
 * keeps the number Rhino wrote into the dimension. `custom` multiplies the model's own units
 * by the factor the app sends (viewer.setAnnotationOptions({ unit: 'custom', unitFactor })).
 */
export const UNITS = {
  file: { label: '', decimals: 1, mmPerUnit: null },
  mm: { label: 'mm', decimals: 0, mmPerUnit: 1 },
  cm: { label: 'cm', decimals: 1, mmPerUnit: 10 },
  m: { label: 'm', decimals: 2, mmPerUnit: 1000 },
  inch: { label: '"', decimals: 2, mmPerUnit: 25.4 },
  custom: { label: '', decimals: 2, mmPerUnit: null },
};

export const DEFAULT_UNIT = 'cm';

/** Millimetres per unit of a rhino3dm `UnitSystem` name, for the conversions above. */
export const MM_PER_MODEL_UNIT = {
  Microns: 0.001,
  Millimeters: 1,
  Centimeters: 10,
  Decimeters: 100,
  Meters: 1000,
  Dekameters: 10000,
  Hectometers: 100000,
  Kilometers: 1000000,
  Mils: 0.0254,
  Inches: 25.4,
  Feet: 304.8,
  Yards: 914.4,
  Miles: 1609344,
};

/** Annotation kinds that count as dimensions; everything else follows the text options. */
export const DIMENSION_KINDS = new Set([
  'Aligned',
  'Rotated',
  'Angular',
  'Angular3pt',
  'ArcLen',
  'Radius',
  'Diameter',
  'Ordinate',
  'CenterMark',
]);

/** Smallest a label or an arrowhead is ever drawn, in screen pixels. */
export const MIN_TEXT_PX = 10;
export const MIN_ARROW_PX = 7;
