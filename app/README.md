# Rhino Viewer (Android)

Flutter app that opens Rhino `.3dm` files on the phone: `rhino3dm` (WebAssembly) parses the
file inside a WebView and three.js renders the cached render meshes, so a normal Rhino-saved
file needs no network. Files saved without render meshes can be meshed by the optional
appserver in `/backend` (which talks to Rhino.Compute on Windows).

## Run / build

```sh
cd app
flutter pub get
flutter analyze --fatal-infos
flutter test
flutter run                         # debug on a connected device
flutter build apk --release         # single APK, build/app/outputs/flutter-apk/
flutter build apk --release --split-per-abi
```

Requires Flutter 3.47.x, Android SDK 36, JDK 17+. `minSdk` is 24.

## Signing

`flutter build apk --release` signs with the **debug** key and prints a Gradle warning unless
`android/key.properties` exists:

```properties
storeFile=upload-keystore.jks       # relative to android/app/
storePassword=...
keyAlias=upload
keyPassword=...
```

`key.properties`, `*.jks` and `*.keystore` under `android/` are git-ignored. CI writes them
from repository secrets (see the root README).

## Opening files

* **Open .3dm** on the home screen uses the system picker (any file type; the app checks the
  `3D Geometry File Format` magic bytes itself because Android reports no MIME type for `.3dm`).
* *Open with* / *Share to* from Files, Drive, WhatsApp, mail: `MainActivity.kt` validates the
  magic, copies the stream to its own `cacheDir/incoming/<id>/` directory, and hands the path
  to Dart over `MethodChannel('com.styro3d.rhino_viewer/intent')`; Dart deletes that
  directory after importing.
* Imported files are stored as `<sha256>.3dm` under the app-support `models/` directory and
  listed under *Recent* (max 40 entries, size cap configurable in Settings). Server-meshed
  results are cached as `<sha256>.meshed.3dm` and preferred on the next open.

## When the viewer does not come up

The WebView is never allowed to be silently blank. While no model is on screen an opaque
overlay covers it, naming the stage reached — *Creating the view · Loading the viewer page ·
Viewer page loaded · Viewer ready · Reading the file · Parsing the model · Building the scene* —
with a progress bar and the last error the page or the WebView reported. Each stage has its own
watchdog, armed from the moment the platform view is created (not at `onLoadStop`) and re-armed
by every progress update; when one runs out the page says which stage stalled and offers *Retry*
(a fresh platform WebView) and *Diagnostics*.

Resource failures, main-frame HTTP errors, JavaScript console errors and a dead render process
all reach the same place: the overlay's error line while nothing is on screen, a SnackBar once
the model is up, and always the diagnostics log.

One failure has no callback of its own: when Android refuses to create the platform view at all,
no WebView callback ever fires and the rejected request is an uncaught asynchronous error that
would otherwise only reach logcat. The app installs a handler for those in `main()` and the viewer
listens, so *Creating the view* failing now shows Android's own sentence instead of a blank
timeout. The page also asks Android once which WebView package backs the app, because a WebView
provider that is disabled or missing stops the view being created and has no other symptom — a
working browser does not prove it, since Chrome and the system WebView are separate packages.

If the viewer never appears, the error panel also offers **Other rendering mode**. Android can
composite a WebView two ways and they reach the system through different code, so a device that
cannot create the view one way sometimes manages the other. The choice is remembered, and
Settings → *Viewer* → *Hybrid rendering* sets it back. Hybrid (the default) puts the real WebView
in the Android view tree; the alternative draws it through Flutter and can show artefacts, so only
turn it off if the viewer does not come up.

*Diagnostics* in the viewer's overflow menu shows `viewer.diagnostics()` from the page (absent,
slow or throwing is fine — it is reported as such) next to the app-side facts: the asset URL, the
model URL, the file name and its size on disk, the Android WebView package and version, which
compositing mode drew the view, every uncaught error in full, every stage with timings, and the
recent log.
*Copy* puts the whole block on the clipboard for a support mail.

WebView settings worth knowing (`lib/features/viewer/viewer_page.dart`, all justified against the
flutter_inappwebview 6.1.5 sources): the WebView is **opaque** — `transparentBackground: true` is
a known source of flat grey frames on Android and the page paints its own dark background, which
a document-start user script also applies before `viewer.css` loads, since the plugin exposes no
background-colour setting on Android. Android's two darkening levers (`forceDark`,
`algorithmicDarkeningAllowed`) are pinned off so the phone's dark theme cannot wash the page out,
hardware acceleration is pinned on (WebGL draws nothing without it), Safe Browsing is off (every
byte the page loads is local), and hybrid composition is the default so the real WebView is in
the Android view tree (switchable, above).

Release APKs are built **without** R8: minification and resource shrinking are turned off in
`android/app/build.gradle.kts`, which is a deliberate override of the Flutter SDK default rather
than the default restated. The reasoning and the three things that must be proven before turning
it back on are in `docs/ARCHITECTURE.md` §3.6b.

## Meshing server

Settings → *Backend URL* (+ optional API key). The manifest enables cleartext HTTP because
workshop Compute servers usually live on the LAN without TLS; use `https://` where possible.
*Mesh on server* uploads in the background of the viewer with upload progress and a Cancel
button (the HTTP request is aborted); *Test connection* warns in amber when the appserver is
up but Rhino.Compute is missing or unreachable, since `/mesh` fails in that state.

## Layout

```
lib/main.dart                       runApp + wiring (plain constructors)
lib/app/                            theme tokens, formatting helpers, AppServices
lib/core/models/                    Stats / LayerInfo / PickedObject / RecentFile (pure Dart)
lib/core/bridge/viewer_bridge.dart  window.viewer calls + callHandler events (JsRunner interface)
lib/core/services/                  files, cache/recents, backend client, settings, intents
lib/features/{home,viewer,settings} screens; viewer/widgets holds toolbar, sheets, overlays
assets/viewer/                      the three.js page (see ../docs/ARCHITECTURE.md §2)
test/                               unit tests (models, services, bridge, formatting) + widget tests
                                    (home, settings, viewer widgets)
```
