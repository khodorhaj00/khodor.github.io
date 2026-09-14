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
  map), `shaded_edges` (shaded + `EdgesGeometry` at 30°), `wireframe`, `ghosted` (opacity 0.35,
  depthWrite false). Materials from the file are **replaced** by layer/object color materials —
  production files have unreliable materials; color = object color if `colorSource` is
  `ObjectColorSource_ColorFromObject`, else layer color. `side = DoubleSide` (open surfaces).
* Colors on `userData.attributes` from the loader: `attributes.objectColor` is `{r,g,b,a}`
  (0–255), `attributes.colorSource.name`, `attributes.layerIndex`, `attributes.name`,
  `attributes.id`, `attributes.userStrings` (array of `[key, value]` pairs) — verify the exact
  shapes against the loader source (`extractProperties`).
* Layers come from `object.userData.layers` (array in file order: `{name, color:{r,g,b,a},
  visible, fullPath, parentLayerId, id, index?}`) — verify field names in the loader; a layer's
  `objectCount` is computed by walking the scene. Layer visibility toggles every object with that
  `layerIndex`, including objects inside block instances (walk `object.traverse`).
* Background: dark gradient (#1B1F26 top → #0E1013 bottom) drawn with a fullscreen quad or CSS
  behind a transparent renderer (`alpha: true`). Grid: `GridHelper` sized to the model bbox
  (10× the largest dimension, 20 divisions), on the Z=0 plane (rotate −90° about X), subtle
  (#2A3038 / #1F252C), toggleable.
* Picking: pointerdown/pointerup with movement < 6 px and < 300 ms → `Raycaster` against
  visible meshes → emit `objectPicked`. Highlight the picked mesh (emissive #FFB020 × 0.35)
  until the next pick; tap on empty space clears and emits `null`.
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
| `viewer.fit()` | Frames the bounding box of visible objects (perspective and ortho). |
| `viewer.setView(name)` | `iso` `top` `bottom` `front` `back` `left` `right`; then `fit()`. |
| `viewer.setProjection(p)` | `perspective` (default) or `ortho`. Keeps target and framing. |
| `viewer.setDisplayMode(m)` | `shaded` (default) `shaded_edges` `wireframe` `ghosted`. |
| `viewer.setLayerVisible(index, bool)` / `viewer.setAllLayersVisible(bool)` | Layer index = index into `stats.layers`. |
| `viewer.setCurvesVisible(bool)` / `viewer.setPointsVisible(bool)` | Default both true. |
| `viewer.setGrid(bool)` | Default true. |
| `viewer.setBackground(hexTop, hexBottom)` | Optional; defaults above. |
| `viewer.exportGlb()` | GLTFExporter binary of the visible model, Y-up (rotate −90° about X on a root group copy). Emits `exportResult`. |
| `viewer.getStats()` | Returns the last `Stats` object as a JSON **string** (or `"null"`). |

### 2.2 Events — JS → Flutter

`viewer.js` calls `window.flutter_inappwebview.callHandler(name, payload)` when it exists.
When it does not (desktop browser, Playwright tests) it pushes `{name, payload}` to
`window.__viewerEvents` (array) and `console.log('[viewer-event] ' + JSON.stringify(...))`.

| Handler | Payload |
|---|---|
| `viewerReady` | `{ three: 'r186', rhino3dm: '8.32.2' }` — emitted once after `rhino3dm` is initialised (do a tiny warm-up so the first real load is fast). |
| `loadProgress` | `{ phase: 'fetch'|'parse'|'build', progress: 0..1 }` |
| `loadResult` | `{ ok: true, name, stats }` or `{ ok: false, name, error }` |
| `exportResult` | `{ ok: true, filename, base64 }` or `{ ok: false, error }` |
| `objectPicked` | `{ id, name, objectType, layerIndex, layerName, userStrings: {k: v}, size: [dx,dy,dz], center: [x,y,z] }` or `null` |
| `log` | `{ level: 'info'|'warn'|'error', message }` |

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
5. Exit non-zero on any failure; print a compact table of timings per fixture.

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
    mediaPlaybackRequiresUserGesture: false, transparentBackground: true,
    supportZoom: false, overScrollMode: OverScrollMode.NEVER,
    verticalScrollBarEnabled: false, horizontalScrollBarEnabled: false,
    useHybridComposition: true,
  ),
  onWebViewCreated: (c) { register handlers of §2.2 with c.addJavaScriptHandler(...) },
)
```
Never set `disableVerticalScroll` / `disableHorizontalScroll`: on Android the plugin implements them
by swallowing every touch-move event before Chromium sees it, which kills orbit, pan and pinch-zoom;
the page blocks scrolling itself (`viewer.css`: `overflow: hidden`, `touch-action: none`).

Model URL passed to JS: `https://appassets.androidplatform.net/files/<fileName>` where
`<fileName>` is a file inside `modelsDir`. Fallback if the URL fetch fails: `base64`.

### 3.2 Storage & cache

* `modelsDir = <getApplicationSupportDirectory()>/models/`
* Picked/received file → copied to `modelsDir/<sha256>.3dm` (sha256 of content; skip copy if exists).
* Server-meshed result → `modelsDir/<sha256>.meshed.3dm`. Opening a file prefers the `.meshed`
  variant when present. This is the "cache so re-opening skips the round-trip".
* Recents in `SharedPreferences` key `recents_v1` (JSON list of
  `{sha, name, size, addedAt, lastOpenedAt, meshed}`), most recent first, max 40 entries. LRU
  eviction also deletes the files. Total size cap 1 GB (settings).
* Magic check before accepting a file: first bytes ASCII `3D Geometry File Format`.

### 3.3 Android intents (open `.3dm` from file manager / WhatsApp / email / Drive)

`MainActivity.kt` (Kotlin) handles `ACTION_VIEW` and `ACTION_SEND` in `onCreate`/`onNewIntent`:
copy the `content://`/`file://` stream to `cacheDir/incoming/<displayName or received.3dm>`,
then deliver the path to Dart over `MethodChannel('com.styro3d.rhino_viewer/intent')`:
Dart calls `getInitialFile()` → `String?` once at startup; later intents arrive as
`onFile(String path)` invocations from Kotlin. Dart then imports it like a picked file.
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
  overflow menu (Export GLB, Share original, Info). Bottom toolbar: Fit · Views (popup) ·
  Display mode (popup) · Layers (bottom sheet: checkbox + color swatch + count; all/none) ·
  Grid toggle · Ortho toggle. Loading overlay with phase + progress bar. Banner when
  `unmeshed.total > 0`: "N objects have no render mesh" + `Mesh on server` (if backend URL
  configured; runs `/mesh`, saves `.meshed.3dm`, reloads) or `Set up server` (→ settings) and a
  hint "or re-save in Rhino with Save small unchecked". Picked-object card (name, layer, size
  in model units, user strings) anchored bottom-left above the toolbar.
* **Settings**: backend URL, API key (obscured), mesh quality (`draft/default/fine`), cache size
  cap, "Clear cache", "Test connection" (`GET /health`), about (versions of three/rhino3dm).

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
lib/features/home/home_page.dart
lib/features/viewer/viewer_page.dart (+ widgets/: toolbar, layers_sheet, stats_sheet, picked_card, unmeshed_banner, loading_overlay)
lib/features/settings/settings_page.dart
test/                             unit tests for models, cache_service (temp dir), backend_client
                                  (http MockClient), viewer_bridge (fake JsRunner); widget test for HomePage.
```

### 3.6 Signing (`android/app/build.gradle.kts`)

Read `android/key.properties` if present (`storeFile`, `storePassword`, `keyAlias`,
`keyPassword`) → `signingConfigs.create("release")` and use it for `buildTypes.release`;
otherwise fall back to the debug signing config and print a Gradle `logger.warn`. Add
`android/key.properties`, `android/app/*.jks`, `android/app/*.keystore` to `app/.gitignore`.
Release: `isMinifyEnabled = true`, `isShrinkResources = true`, ProGuard rules file keeping
`com.pichillilorenzo.flutter_inappwebview_android.**` (flutter_inappwebview) if needed.
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

Errors: `400 invalid_file` (magic bytes / rhino3dm parse failure), `401 unauthorized`,
`413 too_large`, `502 compute_unreachable` / `compute_error` (with Compute's message),
`504 compute_timeout`, `500 internal`.

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
* Logging: one JSON line per request to stdout `{ts, method, path, status, ms, bytesIn, bytesOut, meshed, skipped}`.
* `Dockerfile`: `node:22-alpine`, non-root `node` user, `npm ci --omit=dev`, `HEALTHCHECK` via
  `node -e "fetch('http://127.0.0.1:8080/health').then(r=>process.exit(r.ok?0:1)).catch(()=>process.exit(1))"`,
  `EXPOSE 8080`. `docker-compose.yml` with the env vars and a comment block explaining the
  Windows Compute host. `.env.example`. `README.md` inside `/backend` for API + deploy.
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
