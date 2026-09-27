# Rhino Viewer APK — everything in one file

Styro3D's Android app for checking Rhino `.3dm` files on the shop floor. Works **fully
offline**. Last updated 2026-09-27 (version 0.4.0, Build 2 — Stitch look).

---

## 1. Where things are

| What | Where |
|---|---|
| Code (GitHub) | https://github.com/khodorhaj00/khodor.github.io — branch `claude/flutter-rhino-3d-viewer-uin8ik` (PR #1). `master` is only the old GitHub Pages site. |
| Code (this PC) | `C:\Users\khodor\Downloads\claude\khodor.github.io` |
| Flutter SDK (this PC) | `C:\Users\khodor\dev\flutter` (3.47.4) |
| APK downloads | GitHub → **Actions → Build APK** → newest green run → **Artifacts** → `rhino-viewer-apk-<code>` |
| Docs in the repo | `README.md` (users), `docs/ARCHITECTURE.md` (how it works), `docs/CUSTOMISING.md` (what to edit), `docs/BUILD_PLAYBOOK.md` (how to build, pitfalls), `app/assets/viewer/PATCHES.md` (changes to three.js) |

## 2. Install on the phone

1. Download the artifact zip from GitHub, unzip it.
2. Install `rhino-viewer-<version>-<code>-arm64-v8a.apk`.
3. **Uninstall the old app first** — builds are not signed with a fixed key yet, so Android
   refuses to update over an older one. (Fix: add the 4 signing secrets, §9.)

## 3. What the app does

**Home (FILE BROWSER):** amber *OPEN .3DM FILE* button; *SYS TELEMETRY* boxes with the phone's real
memory, free storage and OpenGL ES version; *RECENT .3DM FILES* cards (swipe to delete).
Round amber button top-right = Settings.

**Open files:** big *Open .3dm* button, or *Share / Open with* from WhatsApp, Drive, Files.
Rhino 3–8 files. Recent files list (up to 40, 1 GB cache by default).

**Viewer header:** file name + *CAD INSPECT* (*LIVE CALIPER SESSION* while measuring), object
and triangle counts. **View cube** top-right: tap TOP/FRONT/RIGHT/… or ISO.

**Viewer toolbar:** Fit · Views · Display · Layers · Objects · Caliper
- **Views:** Perspective, Top, Bottom, Front, Back, Left, Right + *Orthographic* and *Grid* switches.
- **Display:** Shaded, Shaded + edges, Wireframe, Ghosted, **Rendered** (file materials) +
  *Lighting* switch + *Textures & shadows* switch.
- **Layers:** show/hide, search, ALL VIS · HIDE ALL · INVERT · ISOLATE (isolate = show only the searched layers), N of M visible.
- **Objects:** per type (surfaces, meshes, curves, points, annotations, hatches, blocks) a
  **Show** and a **Select** checkbox.
- **Caliper:** tap 2 points (snaps to corners and curve ends) → distance + ΔX ΔY ΔZ.
- **Tap an object (part card):** name, type badge, X / Y / Z size boxes, layer, annotation text, user strings.
- **⋮ menu:** Export GLB, Share original, Info (counts, timings), Settings, Diagnostics.

**Annotations:** dimensions (linear, aligned, radius, diameter), text, leaders, hatches —
at Rhino's size, font (bold/italic) and alignment, always readable from any side.

**Settings:**
| Setting | Choices (default in bold) |
|---|---|
| Quality | Draft · **Normal** · Fine · Ultra — curves, SubD, text and screen sharpness |
| Units | From file · mm (0 dec) · **cm (1 dec)** · m (2) · inch (2) · Custom ×number |
| Annotation size | Small · **Medium** · Large |
| Dimensions colour / font | **From file** · White · Amber · Cyan · Red / **From file** · Sans · Serif · Mono · Phone default |
| Text colour / font | same five each |
| Meshing server | optional, empty = fully offline (only feature that uses the network) |
| Cache size, Hybrid rendering | 1 GB, on |

## 4. Limits (honest)

- **Surfaces/polysurfaces/extrusions** show the mesh Rhino saved. Quality can't refine them on
  the phone. For smoother parts: in Rhino set render mesh to *Smooth & slower*, then save
  (not *Save small*).
- Files saved with *Save small* show a banner "N objects have no render mesh" → re-save in Rhino.
- Fonts: Arial/Times/Courier are replaced by Liberation Sans/Serif/Mono (same spacing).
  Arabic text uses the phone's own font.
- Section plane: not yet (planned later). Python scripts: not supported.
- 100 MB+ files are at the limit of a mid-range phone.

## 5. Build history

| Build | Date | Version | Main changes | GitHub run |
|---|---|---|---|---|
| Original | 2026-09-15 | 0.1.0 | Viewer, layers, picking, GLB export | run #11 |
| 1 | 2026-09-17 | 0.2.0 | Annotations + hatches, Objects sheet, caliper, rendered mode, curve accuracy, arm64-only test builds | 35240085747 |
| 1.1 | 2026-09-17 | 0.2.0 | rhino3dm 8.35, real text size/font/alignment, readable text, Lighting switch, server button hidden | 35250215862 |
| 1.2 | 2026-09-18 | 0.3.0 | Quality switch, units, annotation size/colour/font, Liberation fonts, long-dimension-line fix | 35285120031 |
| 2 | 2026-09-27 | 0.4.0 | Stitch look, bust icon (see-through), real phone data in telemetry boxes, Settings button, view cube, layers Invert/Isolate | see PR #1 Actions |

## 6. How it is built (short)

- **App shell:** Flutter (Dart) — screens, settings, files, toolbar. `app/lib/`
- **3D viewer:** a web page inside the app: three.js r186 + rhino3dm 8.35 (reads `.3dm`
  on the phone). `app/assets/viewer/`
- **Optional server:** Node + Rhino.Compute for files without meshes. `backend/` (not used now).
- **GitHub Actions** compiles the APK (~4 min) on every push to the branch.

## 7. Change something later

All choices live in **two files** that must use the same short names:
- `app/assets/viewer/config.js` — quality levels, sizes, colours, fonts, units
- `app/lib/core/models/viewer_options.dart` — the same lists for the Settings screen

Look (Build 2): `app/lib/app/theme.dart` (colours), `app/lib/app/stitch.dart` (headers, panels,
chips), `app/assets/viewer/viewcube.js` (view cube), icon: `app/tool/icon/` scripts.

`docs/CUSTOMISING.md` gives the exact steps for: new quality level, colours, fonts
(bundle a new font), units, sizes, minimum text size, app colours, toolbar buttons, version.

## 8. Build and test commands (this PC, Git Bash)

```bash
export PATH=/c/Users/khodor/dev/flutter/bin:$PATH
cd /c/Users/khodor/Downloads/claude/khodor.github.io/app
flutter analyze --fatal-infos && flutter test
cd tool/viewer_test && node run.mjs      # viewer page, 398 checks
```
4 file tests fail only on Windows (path `\` vs `/`); they pass on GitHub (Linux).

Upload (starts the GitHub build):
```bash
cd /c/Users/khodor/Downloads/claude/khodor.github.io
git -c credential.helper= -c credential.helper=manager push origin claude/flutter-rhino-3d-viewer-uin8ik
```
Version: `app/pubspec.yaml` → `version: X.Y.Z+N` (N must go up).

## 9. Signing (so updates install without uninstalling)

Run `scripts/gen-keystore.sh`, then add 4 GitHub secrets (Settings → Secrets → Actions):
`KEYSTORE_BASE64`, `KEYSTORE_PASSWORD`, `KEY_ALIAS`, `KEY_PASSWORD`. Keep the `.jks` file
safe — lose it and phones must uninstall again.

## 10. Test file for annotations

`app/tool/viewer_test/fixtures/make_annotations.py` — run in Rhino 8 to recreate
`annotations.3dm` (dimensions, text, leader, hatches) used by the automatic tests.
