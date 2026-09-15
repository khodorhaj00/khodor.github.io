# Build Playbook

How to rebuild this APK, and how to build another Flutter app like it without
re-living the five broken builds it took to get this one working.

Everything here is a fact that was paid for. Versions are pinned for reasons,
and the reasons are written next to them. Do not "modernise" a pin without
reading why it is there.

---

## 1. The stack that works

| Piece | Version | Notes |
|---|---|---|
| Flutter | 3.47.4 stable | Dart SDK `^3.13.3` |
| Android Gradle Plugin | **8.11.1** | **NOT 9.x.** See §4.1 |
| Gradle wrapper | **8.14.3** | AGP 8.11 needs ≥ 8.13; Flutter errors below 8.14.0 |
| Kotlin Gradle Plugin | 2.4.0 | |
| JDK | 17 or 21 | CI uses Temurin 21 |
| compileSdk / targetSdk | 36 | from `flutter.compileSdkVersion` |
| minSdk | 24 | Android 7.0 |
| Application ID | `com.styro3d.rhino_viewer` | |

App dependencies, all pinned in `app/pubspec.yaml`:

```
flutter_inappwebview ^6.1.5      file_picker ^13.0.0
path_provider ^2.1.6             share_plus ^13.3.0
crypto ^3.0.7                    http ^1.6.0
shared_preferences ^2.5.5
```

Vendored into `app/assets/viewer/vendor/`, no CDN at runtime:

- three.js r186 (0.186.0), MIT
- rhino3dm 8.32.2, MIT (2.6 MB WebAssembly)

---

## 2. Get an APK

The build runs on GitHub Actions. There is no Android SDK in the Claude Code
container, so CI is the only compiler.

**Triggers:** pull request, push to the default branch, tag `v*`, or
*Actions → Build APK → Run workflow*.

Then: *Actions* → newest green *Build APK* run → *Artifacts* →
`rhino-viewer-apk-<sha>` → unzip → install
`rhino-viewer-<version>-<sha>-arm64-v8a.apk`.

`arm64-v8a` is the right file for any phone since about 2017. `universal`
works everywhere but is roughly triple the size.

### Locally, if you have the Android SDK

```sh
cd app
flutter pub get
flutter analyze --fatal-infos
flutter test
flutter build apk --release --split-per-abi
```

### Release signing

Unsigned builds are debug-signed: they install, but cannot update a
release-signed install without uninstalling first.

```sh
scripts/gen-keystore.sh          # writes the keystore + key.properties, prints the secrets
```

Add four repository secrets under *Settings → Secrets and variables →
Actions*: `KEYSTORE_BASE64`, `KEYSTORE_PASSWORD`, `KEY_ALIAS`, `KEY_PASSWORD`.
All four or none; `KEYSTORE_BASE64` alone fails the build on purpose. Back the
`.jks` up somewhere safe: it cannot be regenerated, and a different key can
never update an installed app.

---

## 3. What the app actually is

Worth understanding before cloning it for something else.

**There is no conversion step.** Rhino writes render meshes into the `.3dm`
for every Brep, Extrusion and SubD control net: the tessellation the shaded
viewport draws is in the file. `rhino3dm` reads them on the phone and three.js
draws them. A normal production file opens with no network at all.

The architecture is three parts:

1. **A static web page** (`app/assets/viewer/`) that does all the 3D work, with
   a documented JavaScript API on `window.viewer` and events back out.
2. **A Flutter shell** that hosts that page in a WebView, owns files, storage,
   settings and the toolbar, and talks to the page through a typed bridge
   (`app/lib/core/bridge/viewer_bridge.dart`).
3. **An optional Node server** (`backend/`) that meshes the rare file saved
   without render meshes, through Rhino.Compute.

The contract between them is `docs/ARCHITECTURE.md`. Read it before changing
either side.

**Why this shape is worth copying:** the 3D page is testable in a browser with
no Android at all. `app/tool/viewer_test/run.mjs` drives it under Playwright,
306 checks against 8 Rhino files, and catches geometry and rendering
regressions in seconds. Only the thin shell needs a device.

---

## 4. The landmines

Five APKs failed before one worked. Every failure is below, with its cause and
its fix. If you build another Flutter app with a WebView, you will meet some of
these again.

### 4.1 AGP 9 breaks the WebView plugin

**Symptom:** release build fails while evaluating
`:flutter_inappwebview_android`, complaining about
`getDefaultProguardFile('proguard-android.txt')`.

**Cause:** AGP 9 removed that helper. `flutter_inappwebview_android` 1.1.3
still calls it in its own build file, so Gradle dies before compiling
anything. The Flutter 3.47 template generates AGP 9.1.

**Fix:** pin AGP to 8.11.1 and Gradle to 8.14.3, in
`app/android/settings.gradle.kts` and the wrapper properties. Flutter 3.47
supports AGP down to 8.11.1, so this stays inside the supported range. Remove
`android.newDsl` from `gradle.properties`, which only exists in AGP 9.

Revisit only when `flutter_inappwebview` ships a **stable** release with the
fix. The `1.2.0-beta` line has it but rewrites ~75 files of the Android
implementation.

### 4.2 The WebView plugin has a recursive `toMap()`

**Symptom:** the WebView is never created. `onWebViewCreated` never fires, the
viewer shows a flat grey rectangle, and nothing is logged.

**Cause:** `flutter_inappwebview_android` 1.1.3,
`lib/src/webview_asset_loader.dart:197`:

```dart
@override
Map<String, dynamic> toMap() {
  return {...toMap(), 'directory': directory};   // calls itself
}
```

Serialising the WebView settings recurses until the stack overflows, so the
platform view is never built. Upstream issue #2451, fixed only in the beta.

**Fix:** `app/lib/core/bridge/internal_storage_path_handler_fix.dart` — a
subclass that emits the map itself. The native side reads only `type`, `path`
and `directory` for this handler, never the channel id. Three tests cover it,
including one that runs the stock handler and asserts it still overflows, so
the workaround is deleted the day upstream is adopted.

### 4.3 A Stack with only positioned children collapses to nothing

**This one cost the most time.** Symptom: the viewer screen shows one flat
colour, no toolbar, no error, no exception, while every other screen renders
perfectly.

**Cause:** a `Stack` takes its size from its children that are **not**
positioned, and only fills the space it is given when it has none of them
(`RenderStack._computeSize`). Every child of the viewer's Stack is positioned.
While loading, the overlay contributed a `Positioned.fill`, so the Stack filled
the screen. The moment the model arrived the overlay became a bare
`SizedBox.shrink()` — then the only unpositioned child — and the Stack sized
itself to zero by zero. Everything inside was clipped away, leaving only the
Scaffold's background colour, which happened to match the web page's own.

**Fix:** `Stack(fit: StackFit.expand, …)` so the size comes from the
constraints, plus keeping every branch positioned.
`app/test/viewer_stack_sizing_test.dart` reproduces the collapse.

**Rule for any Flutter screen:** if a Stack's children are all `Positioned`,
set `fit: StackFit.expand`. Otherwise one empty child silently deletes the
screen.

### 4.4 Failures were invisible, which cost more than the bugs

Three separate blind spots, all now fixed, all worth copying into any app:

- **A widget that throws** is replaced by a featureless box in release builds.
  `app/lib/app/build_failure_screen.dart` shows the error instead.
- **A platform view that fails to be created** rejects a future nobody awaits.
  It never becomes a `FlutterError`; it lands only on
  `PlatformDispatcher.instance.onError`, which nothing installs by default.
  `app/lib/core/services/platform_error_monitor.dart` hooks both.
- **Diagnostics lived inside the screen that broke.** It is now also on the
  home screen, where a broken viewer cannot hide it.

Build the reporting before you need it. Each round trip to a phone you cannot
debug costs twenty minutes.

### 4.5 Smaller ones

- **Touch died on Android** because `disableVerticalScroll` /
  `disableHorizontalScroll` swallow every move event before Chromium sees it.
  Let the page handle it with CSS `touch-action: none` instead.
- **Black geometry is invisible** on a dark background, and black is Rhino's
  default layer colour. The viewer lifts near-black display colours toward a
  light grey, while keeping the real colour in the stats and the GLB export.
- **R8 is on by default** in Flutter release builds. It is not something you
  add. `-Pshrink=false` is the wrong way to turn it off: it makes Flutter skip
  its whole block, so R8 runs with no keep rules at all. Set
  `isMinifyEnabled = false` and `isShrinkResources = false` in the app module.

---

## 5. Building something similar

The fastest honest path, given what this cost:

1. **Start from this repository.** Copy `app/`, drop `lib/features/`, keep
   `lib/core/`, `android/`, the pinned versions and the whole of §4. The
   scaffolding is where the pain was, not the features.
2. **Put the hard work in a web page,** not in Flutter, whenever the domain has
   a good JavaScript library. It is testable without a device, and the same
   page runs in a browser when the app misbehaves.
3. **Write the Playwright harness first.** `app/tool/viewer_test/run.mjs` is
   the reason the 3D side was never in doubt: every time the app failed, the
   page was already proven.
4. **Wire the error reporting before the first device build** (§4.4).
5. **Expect the WebView plugin to be the problem.** Two of the five failures
   were bugs inside it.

### Commands you will actually use

```sh
# everything that can be verified without a device
export PATH=/opt/flutter/bin:$PATH
cd app && flutter analyze --fatal-infos && flutter test
cd app/tool/viewer_test && node run.mjs      # 3D page, 306 checks
cd backend && npm test                        # meshing server, offline
```

---

## 6. Where things live

```
app/assets/viewer/      the 3D page: three.js + rhino3dm, vendored, offline
  PATCHES.md            the three documented patches to the 3DM loader
app/lib/core/           models, the JS bridge, files, cache, settings, errors
app/lib/features/       home, viewer, settings screens
app/android/            Gradle, signing, intent filters, MainActivity.kt
app/tool/viewer_test/   Playwright harness for the page
backend/                Node meshing server, Dockerfile, compose
scripts/                gen-keystore.sh, set-github-secrets.sh
docs/ARCHITECTURE.md    the contracts between all of the above
.github/workflows/      build-apk.yml, backend-ci.yml
index.html, index_files/   pre-existing GitHub Pages site, unrelated
```
