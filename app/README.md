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
* *Open with* / *Share to* from Files, Drive, WhatsApp, mail: `MainActivity.kt` copies the
  stream to `cacheDir/incoming/`, validates the magic, and hands the path to Dart over
  `MethodChannel('com.styro3d.rhino_viewer/intent')`.
* Imported files are stored as `<sha256>.3dm` under the app-support `models/` directory and
  listed under *Recent* (max 40 entries, size cap configurable in Settings). Server-meshed
  results are cached as `<sha256>.meshed.3dm` and preferred on the next open.

## Meshing server

Settings → *Backend URL* (+ optional API key). The manifest enables cleartext HTTP because
workshop Compute servers usually live on the LAN without TLS; use `https://` where possible.

## Layout

```
lib/main.dart                       runApp + wiring (plain constructors)
lib/app/                            theme tokens, formatting helpers, AppServices
lib/core/models/                    Stats / LayerInfo / PickedObject / RecentFile (pure Dart)
lib/core/bridge/viewer_bridge.dart  window.viewer calls + callHandler events (JsRunner interface)
lib/core/services/                  files, cache/recents, backend client, settings, intents
lib/features/{home,viewer,settings} screens; viewer/widgets holds toolbar, sheets, overlays
assets/viewer/                      the three.js page (see ../docs/ARCHITECTURE.md §2)
test/                               unit tests (models, services, bridge) + HomePage widget test
```
