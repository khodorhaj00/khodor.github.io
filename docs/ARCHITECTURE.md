# Rhino .3dm Viewer — Architecture & Contracts

Two components, one optional. Everything in this document is a contract: builders of one
component must not change an interface here without updating the others.

```
/app                 Flutter Android app (WebView-hosted three.js viewer, rhino3dm WASM)
/backend             Node 22 "appserver" — optional meshing/convert service in front of Rhino.Compute
/.github/workflows   build-apk.yml (signed APK), backend-ci.yml (tests + docker image), viewer tests
/samples             Real Rhino-saved sample file(s)
/backend/test/fixtures  Small synthetic .3dm fixtures (+ generator script)
/docs                This document
/index.html, /index_files   Pre-existing GitHub Pages site — DO NOT TOUCH
```

## 1. Key decision: parse on the phone, mesh on a server only when unavoidable

* Rhino stores **render meshes** inside the `.3dm` for every Brep / Extrusion (and SubD control
  nets) unless the file was saved with *Save small* or produced by a script/exporter.
* `rhino3dm` (McNeel, MIT, WebAssembly, 2.6 MB) reads the whole file on-device and exposes those
  cached meshes. `three.js` ships the official `Rhino3dmLoader` (`3DMLoader.js`) that turns a
  `.3dm` into a scene: meshes, Brep render meshes, Extrusions, SubD, curves, points, point clouds,
  text dots, lights, layers, materials, block instances (`InstanceReference`), nested blocks.
* Therefore a typical Styro3D production file renders **with zero network** — load time is
  parse time (tens to hundreds of ms for a few thousand polys).
* Files **without** render meshes have Brep/Extrusion objects that the loader silently drops. For
  those the app can send the file to `/backend` which calls **Rhino.Compute** to tessellate and
  returns a `.3dm` with meshes; the app caches that result and renders it with the same pipeline.
* Hard fact: Rhino.Compute runs **only on Windows** with a Rhino license (Rhino 8: core-hour
  billing). It cannot run in a Linux Docker container. The Node appserver *is* container-portable
  and talks to Compute over HTTP; document this honestly.

## 2. Viewer page (`app/assets/viewer/`)

Static files bundled as Flutter assets. Vendored, **do not edit** (except the documented patch):

```
vendor/three/three.module.js, three.core.js           three.js r186 (0.186.0)
vendor/three/addons/controls/OrbitControls.js
vendor/three/addons/loaders/3DMLoader.js              PATCHED — see PATCHES.md
vendor/three/addons/loaders/EXRLoader.js, libs/fflate.module.js   (deps of 3DMLoader)
vendor/three/addons/exporters/GLTFExporter.js
vendor/rhino3dm/rhino3dm.js, rhino3dm.wasm             rhino3dm 8.32.2
```

Page files: `index.html`, `viewer.css`, `viewer.js`, `PATCHES.md`.

* `index.html` uses an import map:
  `{"imports":{"three":"./vendor/three/three.module.js","three/addons/":"./vendor/three/addons/"}}`
  and loads `viewer.js` as `type="module"`. No external URLs anywhere (offline app).
* **Start-up guard**: `index.html` opens with an inline ES5 script, first in the document, that
  runs before anything else can fail. It owns the Flutter bridge of §2.2 (so failures before
  `viewer.js` runs are still reported), the ring buffer behind `viewer.diagnostics()`, an opaque
  backdrop, the failure screen (`#viewer-overlay`) and a stand-in `window.viewer`. `viewer.js`
  depends on it: it calls `window.__viewerBoot.starting()` on its first executable line, builds
  the renderer inside `try`/`catch`, and reports whether a model is drawn. Consequences: do not
  load `viewer.js` from any other host page, and do not give it a top-level `await` — the guard
  tells "the module never ran" from "it ran and stopped" by the `DOMContentLoaded` ordering.
* `Rhino3dmLoader.setLibraryPath('./vendor/rhino3dm/')`. The loader fetches `rhino3dm.js` +
  `rhino3dm.wasm` and runs decoding in a Blob Web Worker (needs an http(s) origin — provided by
  the Android `WebViewAssetLoader`, see §3). `setWorkerLimit(1)` (phones), `setSubdivisionLevel(2)`.
* **Patch to 3DMLoader.js** (worker `extractObjectData`): when a `Brep` produces zero meshed faces,
  or an `Extrusion.getMesh()` returns null, post a `warning` message
  `{ type: 'no mesh', objectType: 'Brep'|'Extrusion', guid, message }`. These land in
  `object.userData.warnings`. Document the patch (diff) in `PATCHES.md`.
* Rhino is Z-up. Scene: `camera.up = (0,0,1)`. Views follow Rhino conventions:
  `top` looks down −Z, `front` looks along +Y (camera at −Y), `right` looks along −X (camera at +X),
  `iso` = Rhino Perspective default (camera at (−1,−1,+0.8)·d from the target, roughly).
* Display modes: `shaded` (MeshStandardMaterial, flat lighting: hemisphere + 2 directional, no env
  map), `shaded_edges` (shaded + `EdgesGeometry` at 30°, built in 30 ms slices between frames,
  visible meshes first; a mesh above 100 000 triangles keeps its shading only), `wireframe`,
  `ghosted` (opacity 0.35, depthWrite false). Materials from the file are **replaced** by
  layer/object color materials — production files have unreliable materials; the loader's
  `_createMaterial` is overridden to return one placeholder, so embedded textures are never
  decoded; color = object color if `colorSource` is `ObjectColorSource_ColorFromObject`, else
  layer color. Near-black colours (relative luminance < 0.12 — Rhino's default layer is black)
  are lifted towards `#9AA1AA` **for display only**; `stats.layers[].color` and the GLB export
  keep the file's colour. `side = DoubleSide` (open surfaces).
* Colors on `userData.attributes` from the loader: `attributes.objectColor` is `{r,g,b,a}`
  (0–255), `attributes.colorSource.name`, `attributes.layerIndex`, `attributes.name`,
  `attributes.id`, `attributes.userStrings` (array of `[key, value]` pairs) — verify the exact
  shapes against the loader source (`extractProperties`).
* Layers come from `object.userData.layers` (array in file order: `{name, color:{r,g,b,a},
  visible, fullPath, parentLayerId, id, index?}`) — verify field names in the loader; a layer's
  `objectCount` is computed by walking the scene. Layer visibility toggles every object with that
  `layerIndex`, including objects inside block instances (walk `object.traverse`). Objects hidden
  in Rhino (`attributes.visible === false`, the Hide command) are never drawn, counted in
  `triangles` or exported, but keep their place in `meshes` and `objectCount`.
* Block instances: the stock loader expands one level only, so `viewer.js` overrides
  `_createGeometry` to build definitions recursively (a definition that contains itself stays
  empty). Each `InstanceReference` becomes an `Object3D` wrapper carrying the reference's own
  `userData.attributes` (layer, name, id, user strings), `userData.objectType =
  'InstanceReference'` and `userData.blockName`; its children are clones of the definition
  members. Stats count top-level wrappers as `blocks`; nested members are not counted as `meshes`.
* Background: dark gradient (#1B1F26 top → #0E1013 bottom) drawn with a fullscreen quad or CSS
  behind a transparent renderer (`alpha: true`). Grid: `GridHelper` sized to the model bbox
  (10× the largest dimension, 20 divisions), on the Z=0 plane (rotate −90° about X), subtle
  (#2A3038 / #1F252C), toggleable.
* Picking: pointerdown/pointerup with movement < 6 px and < 300 ms → `Raycaster` against
  visible meshes → emit `objectPicked`. Highlight the picked mesh (emissive #FFB020 × 0.35 plus
  an outline drawn through everything: its hard edges, or its bounding box when it has none or is
  above the edge limit; outline colour #FFB020, or #3DA5FF when the object's own colour is within
  RGB distance 100 of it) until the next pick; tap on empty space clears and emits `null`. A hit
  inside a block instance reports the **top-level instance** (its name, layer, id and user
  strings, the member's user strings filling gaps), as Rhino selects blocks.
* Performance: `renderer.setPixelRatio(min(devicePixelRatio, 2))`; render on demand (only on
  controls `change`, load, resize, mode change) — no continuous RAF loop. Dispose geometry and
  materials on `clear()`.

### 2.1 JS API — `window.viewer` (Flutter → JS via `evaluateJavascript`)

All methods are synchronous or return a Promise; all results are reported through handlers
(§2.2), never through return values, except `getStats()`.

| Method | Behaviour |
|---|---|
| `viewer.load({ url?, base64?, name })` | Clears the scene, loads a `.3dm` from `url` (fetch, preferred) or from `base64` (fallback). Emits `loadProgress` then exactly one `loadResult`. |
| `viewer.clear()` | Removes and disposes the model. |
| `viewer.fit()` | Frames the visible objects' silhouette (every drawn vertex, not a bounding sphere) so it spans 80 % of the limiting viewport axis, in both cameras; also run on every `resize` (phone rotation) so the model is re-framed rather than cropped. |
| `viewer.setView(name)` | `iso` `top` `bottom` `front` `back` `left` `right`; then `fit()`. |
| `viewer.setProjection(p)` | `perspective` (default) or `ortho`. Keeps target and framing. |
| `viewer.setDisplayMode(m)` | `shaded` (default) `shaded_edges` `wireframe` `ghosted`. |
| `viewer.setLayerVisible(index, bool)` / `viewer.setAllLayersVisible(bool)` | Layer index = index into `stats.layers`. |
| `viewer.setCurvesVisible(bool)` / `viewer.setPointsVisible(bool)` | Default both true. |
| `viewer.setGrid(bool)` | Default true. |
| `viewer.setBackground(hexTop, hexBottom)` | Optional; defaults above. |
| `viewer.exportGlb()` | GLTFExporter binary of the visible model, Y-up (rotate −90° about X on a root group copy). Emits `exportResult`. |
| `viewer.getStats()` | Returns the last `Stats` object as a JSON **string** (or `"null"`). |
| `viewer.diagnostics()` | Synchronous, never throws, JSON-serialisable snapshot for a bug report: `{ time, userAgent, devicePixelRatio, viewport:{width,height}, webgl:{webgl1, webgl2, vendor, renderer, unmasked, version, maxTextureSize, contextLost, error}, canvas:{width,height,cssWidth,cssHeight,pixelRatio}\|null, three:'r186'\|null, rhino3dm:{version, worker:'pending'\|'ready'\|'failed'\|'unknown'}, boot:{started, booted, failure:{title,detail}\|null}, model:{name,objects,meshes,triangles,vertices,layers,unmeshed,units,bbox}\|null, logs:[{level,message,t}] }`. `logs` is the last 30 `log` events, `t` in ms since page load. Answered by the stand-in API too, so a page that failed to start still reports why in `boot.failure`. |

### 2.2 Events — JS → Flutter

`viewer.js` calls `window.flutter_inappwebview.callHandler(name, payload)` when it exists.
When it does not (desktop browser, Playwright tests) it pushes `{name, payload}` to
`window.__viewerEvents` (array) and `console.log('[viewer-event] ' + JSON.stringify(...))`.

| Handler | Payload |
|---|---|
| `viewerReady` | `{ three: 'r186', rhino3dm: '8.32.2' }` — emitted once the worker has instantiated `rhino3dm` (the patched loader's `worker._ready`, see `PATCHES.md`), so the first real load only pays for parsing. Never emitted when initialisation fails: that is a `log` error, and every later `load()` answers `loadResult { ok: false }` instead of hanging. |
| `loadProgress` | `{ phase: 'fetch'|'parse'|'build', progress: 0..1 }` |
| `loadResult` | `{ ok: true, name, stats }` or `{ ok: false, name, error }`. A fetch failure carries `error` = `HTTP <status> while fetching <url>` (or Chromium's `Failed to fetch`); the app's base64 fallback (§3.1) keys on those texts, so keep them. Bytes `rhino3dm` cannot read give `Not a valid or complete .3dm file`. |
| `exportResult` | `{ ok: true, filename, base64 }` or `{ ok: false, error }` |
| `objectPicked` | `{ id, name, objectType, blockName, layerIndex, layerName, userStrings: {k: v}, size: [dx,dy,dz], center: [x,y,z] }` or `null`. `blockName` is `''` unless the hit lies inside a block instance; then the payload describes the top-level instance (`objectType: 'InstanceReference'`, `blockName` = definition name, size/center of the whole instance). |
| `log` | `{ level: 'info'|'warn'|'error', message }` |

Every start-up failure (WebGL refused, a script/stylesheet/import-map target that does not load,
`rhino3dm` initialisation), every uncaught error, every unhandled rejection and a lost WebGL
context emit `log` at level `error`. They also paint a full-screen, opaque, readable message in
the page — except while a model is already drawn, which is not a blank page: there the app shows
the `log` error over the working view instead of taking it away. While start-up has failed the
stand-in `window.viewer` answers every call of §2.1, so `load()` emits `loadResult { ok: false,
error }` and `exportGlb()` emits `exportResult { ok: false, error }` instead of staying silent.

`Stats`:
```json
{
  "objects": 237, "meshes": 12, "triangles": 48210, "vertices": 26011,
  "curves": 218, "points": 1, "pointClouds": 1, "blocks": 0, "lights": 2, "other": 4,
  "layers": [ { "index": 0, "name": "Default", "fullPath": "Default", "color": "#RRGGBB",
                "visible": true, "objectCount": 12 } ],
  "unmeshed": { "breps": 0, "extrusions": 0, "total": 0 },
  "bbox": { "min": [x,y,z], "max": [x,y,z] },
  "units": "Millimeters",
  "timings": { "fetchMs": 12, "parseMs": 240, "buildMs": 30, "totalMs": 282 },
  "warnings": [ { "type": "no mesh", "message": "..." } ]
}
```
`warnings` is capped at 50 entries. `units` comes from `userData.settings.modelUnitSystem` (name
without the `UnitSystem_` prefix) — verify against the loader output; fall back to `"Unknown"`.

### 2.3 Viewer test harness (`app/tool/viewer_test/`)

Node + Playwright, no Flutter needed. `package.json` (devDependency `playwright@1.63.0`),
`run.mjs`:
1. Static server (plain `http` module) rooted at the repo root so `/app/assets/viewer/index.html`,
   `/backend/test/fixtures/*.3dm`, `/samples/*.3dm` and the harness-only fixtures
   `/app/tool/viewer_test/fixtures/*.3dm` (generated by the `make_fixtures.py` next to them;
   their expectations live in `run.mjs`) are reachable. Correct MIME for `.wasm`
   (`application/wasm`) and `.js` (`text/javascript`).
2. Chromium via `chromium.launch({ executablePath: process.env.PW_CHROMIUM || undefined })`
   (in this sandbox `PW_CHROMIUM=/opt/pw-browsers/chromium`; in CI Playwright's own download).
3. For each fixture: `page.evaluate(() => viewer.load({url, name}))`, wait for the `loadResult`
   event in `window.__viewerEvents`, assert, screenshot to `out/<fixture>.png`, and assert the
   screenshot is not blank (>2 % of pixels differ from the background — read pixels with a
   canvas in-page or decode PNG in node without extra deps: use `page.evaluate` on the WebGL
   canvas `toDataURL` + count pixels in-page).
4. Expected results:
   * `meshes.3dm`: 50 meshes, 4 layers, layer `HIDDEN` invisible (its box not rendered),
     `curves` 1, `points` 1, `unmeshed.total` 0, units `Millimeters`, triangles 48·12 + sphere.
   * `brep_nomesh.3dm`: `unmeshed.breps` 2, `meshes` 1.
   * `blocks.3dm`: `blocks` 5, rendered triangles 5·12.
   * `Rhino_Logo.3dm`: 6 Breps + 6 SubDs meshed (`meshes` 12), `curves` 218, `unmeshed.total` 0.
   * `exportGlb()` on `meshes.3dm` → base64 decodes to bytes starting with `glTF` magic, JSON
     chunk parses, `meshes.length > 0`.
   * Layer toggle: `setLayerVisible(idx('PARTS'), false)` → screenshot differs from before.
5. Hostile-WebView cases, each on its own page: `getContext` forced to fail, `viewer.js` aborted,
   `three.module.js` aborted (the import-map target), a forced context loss and restore
   (`WEBGL_lose_context`), a zero `window.innerWidth`, the `viewer.diagnostics()` shape, the
   opaque background, and an uncaught error / unhandled rejection both with and without a model
   on screen. Each asserts what the user would see: the painted screen covers the page, is on top
   (`elementFromPoint`), is opaque dark with readable text, names the failure, emits the `log`
   error, does not emit `viewerReady`, and answers `load()` — while a model on screen is left
   drawn and uncovered.
6. Exit non-zero on any failure; print a compact table of timings per fixture.

## 3. Flutter app (`/app`)

Flutter 3.47.4 / Dart 3.13, `minSdk 24`, package `com.styro3d.rhino_viewer`, app name
"Rhino Viewer". Lints: `flutter_lints` (analyzer must be clean with `--fatal-infos`).
Dependencies already in `pubspec.yaml` — do not add more unless strictly needed:
`flutter_inappwebview ^6.1.5, file_picker ^13, path_provider, share_plus ^13, crypto, http,
shared_preferences`; dev: `mocktail`.

### 3.1 WebView hosting

```dart
InAppWebView(
  initialUrlRequest: URLRequest(url: WebUri('https://appassets.androidplatform.net/assets/flutter_assets/assets/viewer/index.html')),
  initialSettings: InAppWebViewSettings(
    webViewAssetLoader: WebViewAssetLoader(pathHandlers: [
      AssetsPathHandler(path: '/assets/'),                       // APK assets
      InternalStoragePathHandler(path: '/files/', directory: modelsDir.path), // our model files
    ]),
    allowFileAccess: false, allowContentAccess: false, javaScriptEnabled: true,
    mediaPlaybackRequiresUserGesture: false,
    transparentBackground: false,          // opaque: see below
    hardwareAcceleration: true,            // LAYER_TYPE_HARDWARE; WebGL draws nothing without it
    forceDark: ForceDark.OFF, algorithmicDarkeningAllowed: false,
    safeBrowsingEnabled: false,            // every byte the page loads is local
    useOnRenderProcessGone: true,
    supportZoom: false, overScrollMode: OverScrollMode.NEVER,
    verticalScrollBarEnabled: false, horizontalScrollBarEnabled: false,
    useHybridComposition: settings.hybridWebViewComposition,   // default true; see below
  ),
  initialUserScripts: [ /* AT_DOCUMENT_START: documentElement.style.backgroundColor = '#0E1013' */ ],
  onWebViewCreated: (c) { register handlers of §2.2 with c.addJavaScriptHandler(...) },
)
```
The WebView is **opaque**. `transparentBackground: true` is the plugin's only background lever
(native: `setBackgroundColor(TRANSPARENT)`), and a transparent WebView composited into the Flutter
view tree is a known source of flat grey frames on Android. flutter_inappwebview 6.1.5 exposes no
Android background colour, so the dark colour is painted by the document itself through the
document-start user script, before `viewer.css` is even fetched. Android's two darkening levers
are pinned off so the app's dark theme cannot wash the page out; both are already the plugin
defaults, pinned so they cannot drift. The Android window is dark in every configuration
(`values/colors.xml`, `LaunchTheme`/`NormalTheme` on `Theme.Black.NoTitleBar` with
`android:isLightTheme=false`, which is also what the WebView reads for the page's
`prefers-color-scheme`), so there is no `values-night/` variant and no white flash.
Never set `disableVerticalScroll` / `disableHorizontalScroll`: on Android the plugin implements them
by swallowing every touch-move event before Chromium sees it, which kills orbit, pan and pinch-zoom;
the page blocks scrolling itself (`viewer.css`: `overflow: hidden`, `touch-action: none`).

**Composition mode** is the one WebView setting the user can change, because it is the one whose
failure mode is a viewer that never appears at all. `useHybridComposition: true` (the default)
routes to `PlatformViewsService.initExpensiveAndroidView` and keeps the real WebView in the Android
view tree; `false` routes to `initSurfaceAndroidView`, which draws it into a Flutter texture — the
path with the known WebGL artefacts, and the reason hybrid is the default. The two reach the engine
through different native code with different requirements, so a device that cannot create the view
one way may manage the other. The page reads
`AppSettings.hybridWebViewComposition` **once, in `initState`**, so the mode can never change under
a live WebView; *Other rendering mode* on the error panel flips it, persists it and recreates the
view through `_retry()`. The button is offered only when the WebView never came up
(`_bridge == null` and still at *Creating the view*) — every later failure is the page's or the
file's, and compositing cannot change it. Settings › Viewer › *Hybrid rendering* is the same flag,
for setting it back. The diagnostics dump names the mode in use (`Composite`); a report that does
not say which path drew the WebView cannot be read.

The manifest must never declare `io.flutter.embedding.android.EnableHcpp`. It turns on Hybrid
Composition++, which is mutually exclusive with hybrid composition: `PlatformViewsChannel` silently
reroutes a hybrid create request to the HCPP controller and `createForPlatformViewLayer` throws. It
is off by default (`settings.h:239`) and there is no other way to enable it, so adding it would
break every WebView in the app with no visible error. There is a comment to that effect in
`AndroidManifest.xml`.

Model URL passed to JS: `https://appassets.androidplatform.net/files/<fileName>` where
`<fileName>` is a file inside `modelsDir`. Fallback if the URL fetch fails (`loadResult.error`
matching the fetch texts of §2.2 — never for parse/build failures, which would only fail again):
`base64`, tried once per file and only for files up to 25 MB, since the inline path holds several
copies of the bytes in memory.

Readiness is tracked as stages (`lib/features/viewer/viewer_status.dart`), each with its own
budget: *Creating the view* 10 s · *Loading the viewer page* 15 s · *Viewer page loaded* 20 s
(the `viewerReady` handshake) · *Viewer ready* 15 s · *Reading the file* 30 s · *Parsing the
model* 120 s · *Building the scene* 60 s. The watchdog is armed when the platform view is
created, not at `onLoadStop`, and re-armed by every stage change and every progress update, so a
slow-but-live parse is never killed while a silent page is caught in seconds. On expiry the page
says which stage stalled and offers *Retry* and *Diagnostics*. `onReceivedError`,
`onReceivedHttpError`, `onConsoleMessage` at error level and `onRenderProcessGone` all reach the
user as readable text (main-frame failures as the error panel, the rest as the overlay's problem
line or a SnackBar once the model is up). *Retry* recreates the platform WebView (new widget key)
instead of reloading it, because a crashed render process cannot be reloaded; callbacks from the
outgoing WebView are ignored so they cannot fail the new attempt.

**Overlay invariant**: exactly one opaque cover is on screen whenever the model is not
(`ViewerOverlay.resolve`: error > busy > progress), and the *none* case is only reachable with
`stats != null`. A blank, grey or otherwise dead WebView can therefore never pass for a working
app, whatever the cause.

### 3.1a Errors nobody catches (`lib/core/services/platform_error_monitor.dart`)

An Android platform view is created by a `Future` **nobody awaits**: flutter_inappwebview calls
`AndroidViewController.create()` from `PlatformViewLink`'s `onCreatePlatformView` and drops the
result, and the framework's own call site in `_PlatformViewLinkState.build` drops it too.
`create()` awaits the native `create` method call and only then runs the
`onPlatformViewCreated` listeners — the listeners that build the controller and fire
`onWebViewCreated`. So when the Android side refuses (an unregistered view type because the
plugin is not registered; an Android System WebView that is missing or disabled, so the `WebView`
constructor throws and the method channel returns a `PlatformException`) **no InAppWebView
callback fires, no `FlutterError` is reported, and nothing in Dart can catch it**: the rejected
future becomes an unhandled asynchronous error in the root zone, which Flutter offers to
`PlatformDispatcher.instance.onError` and otherwise only prints to logcat. That is the one failure
the viewer could not explain — the app knew only that the view was never created.

`PlatformErrorMonitor` closes it. `main()` constructs one as its **first** statement and calls
`install()`; it is passed to the screens through `AppServices.errors`.

* `PlatformDispatcher.instance.onError` → record, then **return `false`**, so the error stays
  unhandled and Flutter logs it exactly as before. `FlutterError.onError` → record, then call the
  handler that was there. The monitor observes; it never absorbs, and it never duplicates an error
  the app already catches (a caught error never reaches either hook).
* `install()` is called from `main()` and nowhere else. `flutter_test` installs its own
  `FlutterError.onError` around every test, so a widget that installed the monitor would swallow
  the failures of the test that built it. The hooks are `@visibleForTesting` methods so the
  behaviour is tested without the globals.
* `runZonedGuarded` is deliberately **not** used: it would move the same errors to the zone
  handler and away from `PlatformDispatcher.onError`, and it requires every binding call and
  `runApp` to sit in the one zone, for no extra coverage.

The viewer page listens from `initState` — before its first build, so no platform-view failure can
beat it. An uncaught error that is from the platform side (`PlatformException`,
`MissingPluginException`) or names the platform-view machinery, arriving while the page is still
at *Creating the view* with no controller, fails the page immediately with Android's own text
instead of waiting out the 10 s watchdog. Anything else is recorded: at error level while no model
is on screen (so it shows under the stage and in the watchdog's message), at warning level once
the model is up, so a stray error elsewhere in the app cannot tear down a working viewer.

**WebView provider probe** (`lib/core/services/webview_provider.dart`). `InAppWebViewController.
getCurrentWebViewPackage()` is a *static* call on the plugin's manager channel
(`WebViewCompat.getCurrentWebViewPackage`), so it needs neither a WebView nor a platform view and
answers when the view was never built. The viewer runs it once per page and reports the answer in
the overlay's problem line and the diagnostics `WebView` field:

| Answer | Means | Page does |
|---|---|---|
| package + version | provider present, plugin registered | records it, nothing else |
| `null` | Android has no enabled WebView implementation | error-level event; named in the watchdog message (the query itself can fail on older Android, so it is not fatal on its own) |
| `MissingPluginException` | the plugin is not registered in this build, so its view factory is not either | fails the page at once — no retry in this process can fix it |

The diagnostics report gains `WebView <provider>` in `STATE` and an `UNCAUGHT ERRORS` section
listing every record the monitor kept, in full.

### 3.1b Contingency: replacing flutter_inappwebview (NOT done, do not start without cause)

If a build with minification off (§3.6b), both composition modes (§3.1) and the diagnostics of §3.1a
still shows a WebView that is never created, the remaining suspect is the plugin itself:
flutter_inappwebview 6.1.5 / flutter_inappwebview_android 1.1.3 were published in 2024 and predate
Flutter 3.47. A source-level check found **no** incompatibility — every framework API the plugin
calls still exists with the same signature, none is deprecated, and the `create` message it sends
matches what the 3.47 engine reads — so this is a contingency, not a plan. Record what the phone
says first; do not start on a hunch.

The replacement is `webview_flutter` + `webview_flutter_android` (4.14.x), which resolves cleanly
against this pubspec. Its structural advantage is the reason to consider it at all: the native
`android.webkit.WebView` is created eagerly by the controller over Pigeon and the platform view only
*looks it up*, so `loadRequest`, `runJavaScript`, `onPageStarted` and `onWebResourceError` all work
independently of the platform view. The exact failure being chased — total Dart-side silence because
the view never came up — is structurally impossible there.

Concrete steps, in order:

1. **Local HTTP server first, on the current plugin.** `webview_flutter_android` has no
   `WebViewAssetLoader` binding and does not expose `shouldInterceptRequest`; its `loadFlutterAsset`
   resolves to a `file://` origin, which kills the blob Web Worker, `fetch`, the import map and WASM
   streaming that §2 depends on. So a `dart:io` `HttpServer` on `InternetAddress.loopbackIPv4` port 0
   is not a workaround, it is the design: serve `/<token>/viewer/<path>` from `rootBundle` (asset
   keys via `AssetManifest.loadFromAssetBundle`) and `/<token>/files/<name>` from `modelsDir`, with
   the MIME table copied from `tool/viewer_test/run.mjs` (`.wasm` → `application/wasm`, `.js` →
   `text/javascript; charset=utf-8`). Reject non-loopback peers, reject a `Host` that is not
   `127.0.0.1:<port>`, and reject any name containing `/` or `..`; the random path token is part of
   the design, because any app on the phone can reach loopback. This is unit-testable under
   `flutter test` with a real `HttpClient`, and it retires the asset origin as a variable while the
   old plugin is still in place. `http://127.0.0.1` is a potentially-trustworthy origin in Chromium
   and is the same origin shape the CI harness already proves green.
2. **Swap the widget and the runner.** Only two files import the plugin: `viewer_page.dart` and
   `webview_js_runner.dart`. `ViewerBridge` sits behind `JsRunner` and does not change, nor does its
   test. Build a `WebViewController` in `initState` and
   `WebViewWidget.fromPlatformCreationParams(AndroidWebViewWidgetCreationParams(controller:,
   displayWithHybridComposition:, gestureRecognizers:))` so the §3.1 mode toggle survives the swap.
3. **Bridge shim, no page change.** `index.html` reads `window.flutter_inappwebview` at call time and
   queues to `window.__viewerEvents` otherwise, so injecting at `onPageStarted` a
   `flutter_inappwebview.callHandler` that forwards `JSON.stringify({name, payload})` to one
   `addJavaScriptChannel` and then drains `__viewerEvents` is lossless. `runJavaScriptReturningResult`
   returns the raw JSON string where `evaluateJavascript` returned a decoded value, so the adapter
   must `jsonDecode` — contain that in `webview_js_runner.dart` and nothing else moves.
4. **Accept the losses, in writing.** `webview_flutter_android` has **no `onRenderProcessGone`**, and
   Android's default for an unhandled dead renderer is to kill the app process: a 5.6 MB model that
   OOMs the renderer would take the app down instead of offering *Retry*, which is a real regression
   against §3.1. `forceDark`, `algorithmicDarkeningAllowed` and `safeBrowsingEnabled` are not exposed
   and can no longer be pinned. `WebResourceRequest` carries only `uri`, so main-frame detection for
   HTTP errors becomes a URL comparison.

Dropping the plugin would also remove the stated reason for the AGP 8.x pin in §3.6a. Do **not**
move to flutter_inappwebview `1.2.0-beta` instead: it rewrites 75 files of the component the whole
app runs on.

### 3.2 Storage & cache

* `modelsDir = <getApplicationSupportDirectory()>/models/`
* Picked/received file → copied to `modelsDir/<sha256>.3dm` (sha256 of content; skip copy if exists).
* Server-meshed result → `modelsDir/<sha256>.meshed.3dm`, written to a temp file next to it and
  renamed into place (a kill mid-write cannot leave a truncated copy). Opening a file prefers the
  `.meshed` variant when present. This is the "cache so re-opening skips the round-trip". If the
  `.meshed` copy fails to load it is deleted, the recents `meshed` flag cleared and the original
  loaded instead. LRU eviction deletes both variants.
* Recents in `SharedPreferences` key `recents_v1` (JSON list of
  `{sha, name, size, addedAt, lastOpenedAt, meshed}`), most recent first, max 40 entries. LRU
  eviction also deletes the files. Total size cap 1 GB (settings).
* Magic check before accepting a file: first bytes ASCII `3D Geometry File Format`.

### 3.3 Android intents (open `.3dm` from file manager / WhatsApp / email / Drive)

`MainActivity.kt` (Kotlin) handles `ACTION_VIEW` and `ACTION_SEND` in `onCreate`/`onNewIntent`:
copy the `content://`/`file://` stream to `cacheDir/incoming/<random uuid>/<displayName or
received.3dm>` (one directory per intent, written as `.partial` and renamed, so a second share of
a same-named file cannot clobber a copy Dart is still importing and a failed copy leaves nothing
behind), then deliver the path to Dart over `MethodChannel('com.styro3d.rhino_viewer/intent')`:
Dart calls `getInitialFile()` → `String?` once at startup; later intents arrive as
`onFile(String path)` invocations from Kotlin. Dart then imports it like a picked file and
deletes that per-intent directory (`IntentService.discardIncoming`). An `ACTION_SEND` without
`EXTRA_STREAM` (text or link shares — the `*/*` filter lists the app in every share sheet) gets a
toast and is ignored.
Manifest intent filters (all with `android:exported="true"` on MainActivity):
* `VIEW` + `DEFAULT` + `BROWSABLE`, `scheme=file`, `host=*`, `mimeType=*/*`,
  `pathPattern=.*\\.3dm` (plus the `.*\\..*\\.3dm`, `.*\\..*\\..*\\.3dm` variants)
* `VIEW` + `DEFAULT`, `scheme=content`, `mimeType=application/octet-stream`
* `VIEW` + `DEFAULT`, `scheme=content`, `mimeType=application/x-rhino`, `model/3dm`, `application/3dm`
* `SEND` + `DEFAULT`, `mimeType=application/octet-stream` and `*/*`
Kotlin rejects anything whose bytes do not start with the `.3dm` magic (toast + ignore).

### 3.4 Screens

* **Home**: app bar "Rhino Viewer" + settings icon; large "Open .3dm" button (file_picker,
  `type: FileType.any`, then extension/magic check — Android often reports no MIME for .3dm);
  recents list (name, size, relative date, `MESHED` badge, tap to open, swipe to delete).
  Drop hint text: "Also opens from Files, WhatsApp, Drive via *Open with*".
* **Viewer**: full-screen WebView; top overlay bar: back, file name, chips `objects` `tris`,
  overflow menu (Export GLB, Share original, Info, Diagnostics — the last always enabled, since
  the report matters most when there is no model and nothing else to look at: it shows
  `viewer.diagnostics()` next to the asset and model URLs, recorded vs on-disk file size, the
  stage timeline with timings, engine versions and the recent event log, with one-tap Copy).
  Bottom toolbar: Fit · Views (popup) ·
  Display mode (popup) · Layers (bottom sheet: checkbox + color swatch + count; all/none) ·
  Grid toggle · Ortho toggle. Loading overlay with phase + progress bar. Banner when
  `unmeshed.total > 0`: "N objects have no render mesh" + `Mesh on server` (if backend URL
  configured; runs `/mesh`, saves `.meshed.3dm`, reloads) or `Set up server` (→ settings) and a
  hint "or re-save in Rhino with Save small unchecked". The loading overlay names the stage
  reached, the file, a determinate bar where a fraction exists and the last error reported.
  While `/mesh` runs the banner is replaced
  by a meshing banner (upload progress, then "waiting for Rhino.Compute", `Cancel` aborts the
  request) and the model stays usable underneath. When the `.meshed` copy is what is on screen
  and still reports unmeshed objects, the banner says the server could not mesh them and offers
  no retry. Picked-object card (name, block name for instances, type, layer, size in model units
  with a unit symbol, user strings; scrolls when long) anchored bottom-left above the toolbar.
* **Settings**: backend URL, API key (obscured), mesh quality (`draft/default/fine`), cache size
  cap, "Clear cache", "Test connection" (`GET /health`; green when Compute is reachable, amber
  when the appserver answers but Compute is not configured or unreachable — `/mesh` fails in
  that state — red with the error code otherwise), *Hybrid rendering* (the composition mode of
  §3.1; on by default, and the only reason to turn it off is a viewer that never appears), about
  (versions of three/rhino3dm).

Visual language (user preference): dark, industrial, no decoration. Tokens: bg `#0E1013`,
surface `#161A1F`, border `#262B33`, text `#E6E8EB`, muted `#8B93A1`, accent `#FFB020`,
danger `#FF4D4F`; numbers in monospace (`fontFeatures: [tabularFigures]`); 8 px grid;
Material 3 with `ColorScheme.dark` seeded from the accent; no elevation shadows, 1 px borders.

### 3.5 Code layout & testability

```
lib/main.dart                      runApp, DI wiring (plain constructors, no DI package)
lib/app/theme.dart
lib/core/models/model_stats.dart   Stats/LayerInfo/PickedObject (fromJson) — pure Dart, unit tested
lib/core/models/recent_file.dart
lib/core/bridge/viewer_bridge.dart Typed wrapper: JS calls out, handler registration in. Testable
                                   through an abstract `JsRunner` (evaluateJavascript) interface.
lib/core/services/file_service.dart     pick, magic check, sha256 (streamed), copy to modelsDir
lib/core/services/cache_service.dart    recents + LRU + size cap (takes a Directory + prefs)
lib/core/services/backend_client.dart   health/mesh/convert over an injectable http.Client
lib/core/services/settings_service.dart
lib/core/services/intent_service.dart   MethodChannel wrapper
lib/core/services/platform_error_monitor.dart  the uncaught-error hooks of 3.1a - pure Dart, unit tested
lib/core/services/webview_provider.dart        one-shot "which WebView does Android have?" probe
lib/features/home/home_page.dart
lib/features/viewer/viewer_page.dart (+ widgets/: toolbar, layers_sheet, stats_sheet, picked_card, unmeshed_banner, meshing_banner, loading_overlay, error_panel, diagnostics_sheet)
lib/features/viewer/viewer_status.dart  stages, watchdog, event log, overlay invariant — pure Dart, unit tested
lib/features/viewer/diagnostics_report.dart  the copyable report — pure Dart, unit tested
lib/features/settings/settings_page.dart
lib/app/format.dart                counts, bytes, lengths, unit symbols, relative dates (no intl)
test/                             unit tests for models, viewer events, format, file_service and
                                  cache_service (temp dir), backend_client (http MockClient),
                                  intent_service, viewer_bridge (fake JsRunner),
                                  platform_error_monitor; widget tests for HomePage, SettingsPage
                                  and the viewer widgets.
```

### 3.6a Android build toolchain (pinned)

`app/android/settings.gradle.kts` pins AGP to **8.11.1** and the wrapper to **Gradle 8.14.3**, below
the AGP 9.1 / Gradle 9.3 the Flutter 3.47 template generates. AGP 9 removed
`getDefaultProguardFile('proguard-android.txt')`; `flutter_inappwebview_android` 1.1.3 still calls it
in its own `android/build.gradle`, so Gradle fails while *evaluating* that project and no release APK
can be produced, regardless of this app's own minify settings. Only the plugin's `1.2.0-beta` line
fixes it, and that beta changes 75 files of the Android WebView implementation plus the platform
interface, which is too much untested churn in the component the whole app runs on.

Flutter 3.47 errors below AGP 8.11.1 and Gradle 8.14.0, so these are the newest versions that both
satisfy Flutter and keep the stable plugin. `android.newDsl` is removed from `gradle.properties`
because it only exists in AGP 9. Do not bump AGP back to 9 until `flutter_inappwebview` ships a
stable release with the fix; the build breaks immediately if you do.

### 3.6b Minification is OFF for release, on purpose

`buildTypes.release` sets `isMinifyEnabled = false` and `isShrinkResources = false`, and **those two
lines are what turns R8 off** — they are not the Flutter default restated. Flutter enables both by
itself: `FlutterPlugin.apply()` assigns `isMinifyEnabled = true` / `isShrinkResources = true` to the
`release` build type and appends `proguard-android-optimize.txt`, its own `flutter_proguard_rules.pro`
and the module's `proguard-rules.pro`, guarded only by `FlutterPluginUtils.shouldShrinkResources()`,
which returns `true` unless the `-Pshrink` Gradle property is set
(`FlutterPlugin.kt:216-228`, `FlutterPluginUtils.kt:226-233`, Flutter 3.47.4). The `--shrink` CLI
flag is documented as having no effect (`flutter_command.dart:986-990`) and CI passes a plain
`flutter build apk --release`. Because the `plugins {}` block applies `FlutterPlugin` before the
script body runs, the app's assignments come last and win.

Why off: the viewer failed on the user's device before `onWebViewCreated` ever fired — the Android
platform view was never constructed, and nothing surfaced in Dart (§3.1a explains why nothing could).
Every release APK this project has produced was minified, so R8 was the only variable on that path
never observed switched off. Shipping an app that cannot be opened is a worse trade than shipping a
larger one. Multidex is not a concern: `minSdk = 24`, where Android loads multiple DEX files
natively.

**Do not use `-Pshrink=false` to test this.** It makes Flutter skip its whole block, so R8 would run
with none of those rule files — strictly more broken than the minified build, and a misleading
result. The only correct switch is the two `false`s in `build.gradle.kts`.

Before turning minification back on, all three must hold:

1. the phone renders a model from a minified build;
2. `build/app/outputs/mapping/release/mapping.txt` still contains `InAppWebViewFlutterPlugin` and
   `FlutterWebViewFactory`, unrenamed;
3. `-printconfiguration` shows that the plugin's own consumer rule
   (`-keep class com.pichillilorenzo.flutter_inappwebview_android.** { *; }`, declared via
   `consumerProguardFiles` in `flutter_inappwebview_android` 1.1.3's `android/build.gradle:36`)
   actually reached R8.

`android/app/proguard-rules.pro` already holds the keeps that day needs — the plugin package, plus
`*JavascriptInterface*` and the `@android.webkit.JavascriptInterface` members the page calls by name.
It is inert while minification is off, and `FlutterPlugin.kt:224-227` picks it up with no wiring once
minification returns. The registration path is worth keeping in mind either way:
`GeneratedPluginRegistrant.registerWith` wraps every `getPlugins().add(...)` in
`catch (Exception e) { Log.e(...) }`, so anything thrown while a plugin registers its view factory
becomes one logcat line and the app continues with the view type unregistered.

### 3.6 Signing (`android/app/build.gradle.kts`)

Read `android/key.properties` if present (`storeFile`, `storePassword`, `keyAlias`,
`keyPassword`) → `signingConfigs.create("release")` and use it for `buildTypes.release`;
otherwise fall back to the debug signing config and print a Gradle `logger.warn`. Add
`android/key.properties`, `android/app/*.jks`, `android/app/*.keystore` to `app/.gitignore`.
`android:label="Rhino Viewer"`, `android:usesCleartextTraffic` NOT enabled globally — the
backend URL must be https, or the user enables `http` per-URL via a `network_security_config`
that allows cleartext only for user-added domains? Simpler: allow cleartext (LAN Compute
servers are the norm in a workshop) with `android:usesCleartextTraffic="true"` and say so in
README. INTERNET permission required.

## 4. Backend (`/backend`) — Node 22, ESM, Express 5

Runs anywhere Docker runs. Talks to a Rhino.Compute instance (`COMPUTE_URL`) only when a
request needs tessellation.

### 4.1 Environment
| Var | Default | Meaning |
|---|---|---|
| `PORT` | `8080` | listen port |
| `APP_API_KEY` | (empty) | if set, every non-health request must carry `X-Api-Key` equal to it (constant-time compare) |
| `COMPUTE_URL` | `http://localhost:5000/` | Rhino.Compute base URL (the `rhino.compute` front end, port 5000 by default) |
| `COMPUTE_API_KEY` | (empty) | sent as `RhinoComputeKey` header |
| `COMPUTE_TIMEOUT_MS` | `120000` | per Compute call |
| `COMPUTE_BATCH` | `20` | breps per Compute call |
| `MAX_UPLOAD_MB` | `200` | request body limit → 413 |
| `MESH_QUALITY` | `default` | `draft` / `default` / `fine` default when query param absent |
| `LOG_LEVEL` | `info` | |

### 4.2 Endpoints
Request body for `/mesh` and `/convert`: raw `.3dm` bytes, `Content-Type: application/octet-stream`.
Optional query `quality=draft|default|fine`, optional `name=<original filename>` (for logs and
glTF asset name). Responses on error are JSON `{ "error": "<code>", "detail": "<text>" }`.

| Route | Response |
|---|---|
| `GET /health` | `200 { ok: true, version, uptimeSec, compute: { url, configured: bool, reachable: bool|null } }` — reachability probed with a 3 s timeout on `GET <COMPUTE_URL>version`; `null` if not configured. Never requires the API key. |
| `POST /mesh` | `200 application/octet-stream` — the same `.3dm` where every Brep / Extrusion / SubD **without** a cached render mesh is replaced by a Mesh object carrying the original `ObjectAttributes` (layer, name, color source, user strings, id preserved where the API allows). Headers `X-Meshed-Count`, `X-Skipped-Count`, `X-Compute-Ms`. If nothing needs meshing → original bytes, `X-Meshed-Count: 0`. |
| `POST /convert` | `200 model/gltf-binary` (`.glb`) — all renderable geometry: Mesh objects, cached render meshes of Breps/Extrusions, SubD (control net subdivided ×2 locally via rhino3dm), instance references expanded (nested transforms), Compute-meshed unmeshed Breps when Compute is configured (else skipped, counted in `X-Skipped-Count`). One glTF node per object, `name` = object name or id, `extras` `{ id, layer, layerIndex, userStrings }`, one material per distinct color (object color or layer color), root node matrix rotating Z-up → Y-up. Headers `X-Object-Count`, `X-Triangle-Count`, `X-Skipped-Count`, `Content-Disposition: attachment; filename="<name>.glb"`. |

Errors: `400 invalid_file` (magic bytes / rhino3dm parse failure), `400 bad_request` (bad
`quality`, or a body cut short / aborted — body-parser's own 4xx keep their status, e.g. 415 for
an unsupported `Content-Encoding`), `401 unauthorized`, `404 not_found`, `413 too_large`
(answered from the `Content-Length` header before the body is read, with `Connection: close` so
the client stops uploading; chunked bodies are still capped by body-parser — a client still
sending the body usually sees the dropped connection rather than this response, which
`BackendClient` reports as `upload_rejected` with a message naming `MAX_UPLOAD_MB`),
`502 compute_unreachable` / `compute_error` (with Compute's message), `504 compute_timeout`,
`500 internal`.

### 4.3 Implementation notes
* `rhino3dm` npm 8.32.2 (`await rhino3dm()` once at startup, exported as a promise).
* Compute calls: `compute-rhino3d` npm 0.13.0-beta — set `RhinoCompute.url`, `RhinoCompute.apiKey`;
  use `RhinoCompute.Mesh.createFromBrep(brepsArray, mpArray, /*multiple*/ true)` in batches of
  `COMPUTE_BATCH`; wrap with `AbortController` timeout. Extrusions → `extrusion.toBrep(true)`
  locally, then treated as Breps. SubD → mesh locally (no Compute). Make the Compute transport
  injectable (`createApp({ compute })`) so tests run with a fake that returns locally built
  meshes (encoded with `mesh.encode()`).
* Meshing parameters: `rhino3dm.MeshingParameters.default` / `.fastRenderMesh` (draft) /
  `.qualityRenderMesh` (fine) — verify names in `rhino3dm.d.ts`; encode with `.encode()`.
* Output `.3dm`: mutate the parsed `File3dm` in place — `objects.delete(id)` + `objects.addMesh(mesh, attributes)`;
  serialize with `file.toByteArray()`. If in-place mutation proves unreliable, rebuild a new
  `File3dm` copying settings, layers, materials, instance definitions and all objects.
* GLB writer (`src/glb.js`, hand-written, no three.js): binary glTF 2.0, one buffer, accessors
  for `POSITION` (float32, min/max), `NORMAL` (float32), indices (uint32), 4-byte alignment,
  `asset.generator = "styro3d-rhino-appserver"`. Unit test validates structure.
* Logging: one JSON line per request to stdout `{ts, method, path, status, ms, bytesIn, bytesOut, meshed, skipped, aborted}`
  (`aborted: true` when the client dropped the connection before the response was delivered —
  the line is written on the response's `close`, not `finish`, so aborted uploads are logged too).
* Every rhino3dm handle a request creates — the parsed `File3dm` first of all — is freed in a
  `finally` (`release()` in `rhino.js`, which takes embind's destructor from the shared
  `ClassHandle` prototype because the table classes shadow `delete` with `delete(id)`); otherwise
  each request leaks the whole model in WASM memory.
* `Dockerfile`: `node:22-alpine`, non-root `node` user, `npm ci --omit=dev`, `HEALTHCHECK` via
  `node -e "fetch('http://127.0.0.1:'+(process.env.PORT||8080)+'/health').then(r=>process.exit(r.ok?0:1)).catch(()=>process.exit(1))"`,
  `EXPOSE 8080`. `docker-compose.yml` with the env vars (`${VAR-default}`, so an empty
  `COMPUTE_URL=` in `.env` disables Compute; the compose default is
  `http://host.docker.internal:5000/`, since `localhost` inside the container is the appserver
  itself) and a comment block explaining the Windows Compute host. `.env.example`. `README.md`
  inside `/backend` for API + deploy.
* Tests (`node --test test/`): GLB structure; `/mesh` on `test/fixtures/brep_nomesh.3dm` with
  fake Compute → 0 Breps, 3 meshes, names/layers preserved, `X-Meshed-Count: 2`; `/convert` on
  `meshes.3dm` and `blocks.3dm` (no Compute) → valid GLB, node count, `X-Skipped-Count: 0`;
  auth 401; magic 400; 413; health.

## 5. CI (`/.github/workflows`)

**`build-apk.yml`** — `on: push (branches: [main, master], paths: app/**,
backend/test/fixtures/**, samples/**, workflow)`, `pull_request` (same paths), `workflow_dispatch`,
`push tags v*`. `main` or `master` is whichever is the repository's default branch (this
repository: `master`).
Job `apk` (ubuntu-latest): checkout → `actions/setup-java@v4` temurin 21 → `subosito/flutter-action@v2`
(`flutter-version: 3.47.4`, `channel: stable`, `cache: true`) → `flutter pub get` →
`flutter analyze --fatal-infos` → `flutter test` → keystore step guarded by
`env.HAS_KEYSTORE == 'true'` where the job sets `env: HAS_KEYSTORE: ${{ secrets.KEYSTORE_BASE64 != '' }}`:
decode `KEYSTORE_BASE64` → `app/android/app/upload-keystore.jks`, write `app/android/key.properties`
from `KEYSTORE_PASSWORD`, `KEY_ALIAS`, `KEY_PASSWORD` (each rejected unless printable ASCII and
backslash-escaped, because `java.util.Properties` reads the file as ISO-8859-1 with `\` as the
escape character) → `flutter build apk --release --split-per-abi` and `flutter build apk --release`
→ upload artifacts `rhino-viewer-apk-<short sha>` (retention 30 days, `overwrite: true` so a
re-run replaces the earlier attempt's artifact). Unsigned builds are still produced (debug-signed)
with an explicit warning annotation.
Job `viewer` (ubuntu-latest, node 22): `npm ci` in `app/tool/viewer_test`,
`npx playwright install --with-deps chromium`, `node run.mjs`, upload `out/*.png` as artifact
`viewer-screenshots-<sha>` (`overwrite: true`).
Job `release` (tags `v*` only, `needs: [apk, viewer]`): `softprops/action-gh-release@v2` attaching
the APKs and `SHA256SUMS.txt`; a failed viewer harness blocks the release.

**`backend-ci.yml`** — `on: push (branches: [main, master]) / pull_request, paths backend/**,
samples/** (the tests read samples/Rhino_Logo.3dm), workflow`: `npm ci`, `npm test`, `docker build`;
on the default branch (`main` or `master`, resolved from `github.event.repository.default_branch`)
also push `ghcr.io/<owner>/rhino-appserver:<sha>` and `:latest` (`permissions: packages: write`,
`docker/login-action@v3` with `GITHUB_TOKEN`).

## 6. Root README

Sections in order: What this is (3 lines) · Why not "convert to glTF on a server" (the
render-mesh insight, Compute = Windows) · Install the APK (Actions artifact / Releases) ·
Open files (picker, *Open with*, WhatsApp) · Build locally · Signing keystore for CI
(`keytool -genkeypair -v -keystore upload-keystore.jks -keyalg RSA -keysize 2048 -validity 10000 -alias upload`,
`base64 -w0 upload-keystore.jks`, secrets `KEYSTORE_BASE64`, `KEYSTORE_PASSWORD`, `KEY_ALIAS`,
`KEY_PASSWORD`) · Trigger a build (push to the default branch / workflow_dispatch / tag) · Optional backend:
deploy appserver with Docker (any host) + set up Rhino.Compute on a Windows VM (link
https://developer.rhino3d.com/guides/compute/deploy-to-iis/ and
https://developer.rhino3d.com/guides/compute/configure-compute-for-production/ ; core-hour
billing note) · API reference (short, link to backend/README.md) · Troubleshooting ·
Repository layout (mention the untouched GitHub Pages site at the root).
