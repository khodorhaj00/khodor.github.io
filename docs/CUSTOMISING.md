# Customising

What to edit for the changes that come up most often, and what each change costs. Every
option the app offers lives in **two** files that must agree on the same short names:

| Side | File | Holds |
|---|---|---|
| Viewer page (the 3D part) | `app/assets/viewer/config.js` | quality levels, annotation sizes, colours, fonts, units, which kinds count as dimensions, minimum on-screen sizes |
| App (Flutter) | `app/lib/core/models/viewer_options.dart` | the same lists as Dart enums, with the labels shown in Settings |

The app sends the short name (`ultra`, `amber`, `inch`, …), the viewer page looks it up. A
name that only exists on one side is ignored with a warning in the diagnostics log.

After any change: `cd app && flutter analyze --fatal-infos && flutter test`, and
`cd app/tool/viewer_test && node run.mjs` for the viewer page. Then push; GitHub builds the
APK (see README, *Trigger a build*).

---

## Add or change a quality level

1. `config.js` → `QUALITY`: add an entry, e.g. `insane: { curve: { relTol: 1e-5, arcStepDeg: 0.5, maxPoints: 80000 }, subdivision: 5, fontPx: 128, pixelRatio: 3 }`.
   * `curve.relTol` — how closely curves follow their true shape, as a fraction of each
     curve's own size. Smaller is finer and slower.
   * `subdivision` — SubD smoothness (each step multiplies the triangles by four).
   * `fontPx` — the height annotation text is drawn at before it is put on screen.
   * `pixelRatio` — the canvas resolution cap.
2. `viewer_options.dart` → `enum ViewQuality`: add `insane('insane', 'Insane')`.

Surfaces, polysurfaces and extrusions are **not** affected: they are drawn with the mesh
Rhino saved in the file. Save from Rhino with a finer render mesh, or mesh on a server.

## Change the annotation colours (5) or fonts (5)

1. `config.js` → `ANNOTATION_COLORS` / `ANNOTATION_FONTS`.
2. `viewer_options.dart` → `enum AnnotationColorChoice` / `AnnotationFontChoice` (the colour
   carries the swatch shown in Settings as `0xAARRGGBB`).

A font must exist on the phone or be bundled (below). `file` means "whatever the .3dm asks
for", mapped through `FONT_ALIASES` to the bundled face with the same metrics.

## Bundle another font

1. Put the `.ttf` in `app/assets/viewer/fonts/` (the folder is already in `pubspec.yaml`).
   Keep it free to redistribute — the bundled Liberation faces are SIL OFL, see
   `fonts/VERSION` for the source and the subsetting command that keeps them small.
2. Declare it in `app/assets/viewer/viewer.css` with `@font-face` (one block per weight and
   style), and add the family to `FONT_FAMILIES` in `app/assets/viewer/viewer.js` so labels
   wait for it to load.
3. Name it in `ANNOTATION_FONTS` (above).

Cost: whatever the files weigh, straight onto the APK (the current eight faces are 1.4 MB).

## Add a unit

1. `config.js` → `UNITS`: `{ label: 'ft', decimals: 2, mmPerUnit: 304.8 }`.
2. `viewer_options.dart` → `enum DisplayUnit`: `feet('feet', 'feet', 304.8, 'ft', 2)`.
3. `app/lib/features/settings/settings_page.dart` → `_unitLabel` for the menu text.

`file` keeps the number Rhino wrote into the dimension; `custom` multiplies the model's own
units by the factor from Settings. The app formats the caliper and the picked object through
`app/lib/app/units.dart`, which reads the same enum.

## Annotation sizes

`config.js` → `ANNOTATION_SIZES` (multiples of the size stored in the file) and
`viewer_options.dart` → `enum AnnotationSize`.

## Smallest readable text

`config.js` → `MIN_TEXT_PX` / `MIN_ARROW_PX`: labels and arrowheads are never drawn smaller
than this on screen, however far you zoom out.

## App colours and spacing

`app/lib/app/theme.dart` — the dark tokens (`bg`, `surface`, `accent`, …), the 8 px grid and
every Material override. The viewer page's own background is `--bg-top` / `--bg-bottom` in
`app/assets/viewer/viewer.css`, and the app repeats the colour in `viewer_page.dart`
(`_userScripts`) so the first frame is never white.

## Toolbar buttons

`app/lib/features/viewer/widgets/toolbar.dart` — one `_ToolButton` per entry; the Views and
Display menus hold the switches (Orthographic, Grid, Lighting, Textures & shadows).

## Version and build

* App version: `app/pubspec.yaml` → `version: 0.2.0+2`. The `+N` must increase or Android
  refuses the update.
* A release tag `vX.Y.Z` must match that version; tag builds make every ABI, other builds
  only `arm64-v8a` (`.github/workflows/build-apk.yml`, job env `ALL_ABIS`).

## Where the rest lives

`docs/ARCHITECTURE.md` is the contract between the app, the viewer page and the backend;
`app/assets/viewer/PATCHES.md` documents every change made to the vendored three.js loader
(annotations, hatches, curve sampling) and how to re-apply them after an upgrade.

## The Stitch look (Build 2)

| To change | Edit |
|---|---|
| Colours (amber accent, green "OK", panel shades) | `app/lib/app/theme.dart` → `AppColors` |
| Fonts of titles / technical labels | `theme.dart` → `kTitleFamily`, `kMonoFamily`, `techLabel` |
| Headers, panels, chips, info boxes, Settings button | `app/lib/app/stitch.dart` (every screen uses these) |
| Home screen (Open button, SYS TELEMETRY, recent cards) | `app/lib/features/home/home_page.dart` |
| What the telemetry boxes read from the phone | `MainActivity.kt` → `getDeviceInfo`, and `core/services/device_info_service.dart` |
| View cube labels, size, colours | `app/assets/viewer/viewcube.js` (`FACES`, `HALF`) + `viewer.css` (`.viewcube*`) |
| Logo in the headers | `app/assets/branding/logo.png` (128 px, transparent) |

**App icon.** Source photo `app/tool/icon/bust_source.jpg`. In `app/tool/icon` run
`python icon_cut.py bust_source.jpg bust_cut.png` (cuts the background out; needs Pillow and
numpy), then `python make_icons.py` (writes every `mipmap-*/ic_launcher*.png` and the logo). The adaptive icon's background is transparent
(`res/mipmap-anydpi-v26/ic_launcher.xml`).
