# Rhino Viewer

Android app that opens Rhino `.3dm` files on the phone — no conversion step, no upload — for checking
production files on the shop floor: open a file from WhatsApp, Drive or the file manager, shaded /
wireframe / ghosted, layer toggles, tap a part for its name, layer, size and user strings, export GLB.
An optional Node "appserver" meshes the rare file that has no render meshes through Rhino.Compute.

The repository root also hosts a pre-existing GitHub Pages site (`index.html`, `index_files/`). It is
unrelated to the app and untouched; everything for the viewer lives in `app/`, `backend/`, `samples/`,
`scripts/`, `docs/` and `.github/`.

## Why not "convert to glTF on a server"

* Rhino stores **render meshes** inside the `.3dm` for every Brep, Extrusion and SubD control net: the
  tessellation the shaded viewport draws is written to the file. The only files without them are those
  saved with *Save small* ticked, or produced by a script/exporter that never displayed the objects.
* `rhino3dm` (McNeel's OpenNURBS, WebAssembly, 2.6 MB, MIT) parses the whole file on the phone and
  three.js' `Rhino3dmLoader` builds the scene from those cached meshes: meshes, Breps, Extrusions, SubDs,
  curves, points, point clouds, text dots, lights, layers, block instances. A normal production file
  therefore renders **with zero network**; load time is parse time (`samples/Rhino_Logo.3dm`, 5.6 MB,
  32 k triangles: ~0.4 s in the desktop test harness, a few times that on a phone).
* Files without render meshes have Brep/Extrusion objects with nothing to draw. The app counts them
  (`unmeshed`), shows a banner, and offers two ways out: re-save in Rhino (see
  [Troubleshooting](#troubleshooting)) or *Mesh on server*.
* *Mesh on server* means **Rhino.Compute**, which runs **only on Windows** with a licensed Rhino 8 and
  cannot be put in a Linux container. A design that converts every file on a server makes every open
  depend on a Windows machine, a licence and a network; this design keeps that path optional and rare.

| | Client-side parse (default) | Rhino.Compute conversion (`POST /mesh`) |
|---|---|---|
| Runs on | the phone: rhino3dm WASM + three.js in a WebView | appserver (Docker, any host) + Rhino.Compute (Windows, Rhino 8) |
| Network | none | upload the file, download the meshed copy |
| Time | parse only; sub-second for a few MB | upload + tessellation + download; seconds to a minute for large files |
| Cost | none | a Windows host; core-hour billing on Windows Server |
| Files without render meshes | not drawn; counted in `unmeshed` and flagged | tessellated (`quality=draft|default|fine`) |
| Geometry shown | Rhino's own render mesh, i.e. what the shaded viewport shows | Compute's mesh at the requested quality |
| Data leaves the phone | never | file sent to your appserver (`X-Api-Key`, https recommended) |
| Result reuse | n/a | cached as `<sha256>.meshed.3dm`; the next open is offline |

## Install the APK

* **Actions artifact** (every push to the default branch, PR, or manual run): *Actions* → *Build APK* →
  newest green run → *Artifacts* → `rhino-viewer-apk-<short sha>`. The zip contains
  `rhino-viewer-<version>-<sha>-arm64-v8a.apk` (any phone from ~2017 on), `-armeabi-v7a` (old 32-bit
  phones), `-x86_64` (emulators), `-universal` (all ABIs, largest) and `SHA256SUMS.txt`.
* **Releases** (tags `v*`): *Releases* → the same files attached to the release.
* On the phone: copy or download the APK, open it, allow *Install unknown apps* for the file manager
  or browser when asked. Updating over an installed version works only when both are signed with the
  same key and the new build has a higher version code. Stay on one variant: per-ABI APKs carry
  version code 1000 × ABI index + N and the universal APK plain N, so Android treats a switch
  (arm64-v8a → universal, or between ABIs) as a downgrade. A debug-signed build (CI without keystore
  secrets) cannot update a release-signed one and vice versa. Uninstall first in both cases.

## Open files

* **Open .3dm** on the home screen: the system picker with *all files* — Android has no MIME type for
  `.3dm`, so the app checks the `3D Geometry File Format` magic bytes itself.
* ***Open with* / *Share to*** from Files, Drive, Gmail, WhatsApp: the app registers `file://*.3dm`,
  `content://` with `application/octet-stream` (what WhatsApp and most providers report),
  `application/x-rhino`, `model/3dm`, `application/3dm`, and `SEND` for any type. Anything that does
  not start with the `.3dm` magic is rejected with a toast. An app that lists viewers strictly by
  MIME may not show Rhino Viewer under *Open with* — use *Share to* or the picker instead.
* Imported files are stored as `<sha256>.3dm` in app storage and listed under *Recent* (max 40,
  size cap in Settings, default 1 GB, LRU eviction). `MESHED` marks files with a server-meshed copy,
  which is preferred on open.
* Viewer: one finger orbits, two fingers pan/zoom. Bottom bar: *Fit* · *Views* (Iso, Top, Bottom,
  Front, Back, Left, Right — Rhino conventions, Z-up) · *Display* (Shaded, Shaded + edges, Wireframe,
  Ghosted) · *Layers* (checkbox, colour, object count, search, all/none) · *Grid* · *Ortho*. Tap an
  object for its name, layer, size in model units and user strings (a part inside a block reports the
  block instance and its block name, as Rhino selects it); objects hidden in Rhino stay hidden. Overflow
  menu: *Export GLB* (Y-up, shares the file), *Share original*, *Info* (stats, timings, warnings).
  Materials from the file are ignored on purpose: colour is the object colour when the colour source is
  *by object*, otherwise the layer colour; near-black colours (Rhino's default layer is black) are
  lightened on screen so parts do not vanish against the dark background — exports keep the file colour.

## Build locally

Flutter 3.47.4 (stable), Android SDK with platform 36 and build-tools, JDK 17 or 21 (Gradle 9.3 /
AGP 9.1). No iOS target.

```sh
cd app
flutter pub get
flutter analyze --fatal-infos
flutter test
flutter build apk --release --split-per-abi   # build/app/outputs/flutter-apk/app-<abi>-release.apk
flutter build apk --release                   # universal app-release.apk
```

Without `app/android/key.properties` the release build is signed with the debug key and Gradle prints a
warning; see [Signing](#signing-keystore-for-ci).

Viewer page without Flutter (Node 22, Playwright Chromium; loads every fixture, checks stats and
pixels, writes `out/*.png`):

```sh
cd app/tool/viewer_test && npm ci && npx playwright install --with-deps chromium && node run.mjs
```

Backend: `cd backend && npm ci && npm test` (offline; Compute is faked), `npm start` to run it.

## Signing keystore for CI

CI signs release APKs with an upload keystore held in repository secrets. Without the secrets it still
builds, debug-signed, and annotates the run with a warning.

```sh
scripts/gen-keystore.sh
```

creates `app/android/app/upload-keystore.jks` and `app/android/key.properties` (both git-ignored, so
local release builds are signed too) and prints the secret values. By hand:

```sh
keytool -genkeypair -v -keystore upload-keystore.jks -keyalg RSA -keysize 2048 -validity 10000 -alias upload
base64 -w0 upload-keystore.jks        # macOS: base64 -i upload-keystore.jks | tr -d '\n'
```

Repository *Settings → Secrets and variables → Actions → New repository secret*:

| Secret | Value |
|---|---|
| `KEYSTORE_BASE64` | output of the `base64` command |
| `KEYSTORE_PASSWORD` | the store password |
| `KEY_ALIAS` | `upload` (or the alias you chose) |
| `KEY_PASSWORD` | the key password — identical to `KEYSTORE_PASSWORD` for the PKCS12 keystores `keytool` creates |

All four must be set and printable ASCII (they are written to `android/key.properties`, a Java
properties file); an empty or non-ASCII value fails the build with an explicit error before Gradle runs.
`scripts/set-github-secrets.sh` (optional, needs the `gh` CLI logged in) verifies the password and alias
against the keystore and uploads the four secrets. Back the `.jks` up: it cannot be regenerated, and a
different key cannot update installed apps.

## Trigger a build

| Event | Jobs | Output |
|---|---|---|
| push to the default branch touching `app/**`, `backend/test/fixtures/**`, `samples/**` or the workflow | `apk`, `viewer` | artifact `rhino-viewer-apk-<sha>`, 30 days; `viewer-screenshots-<sha>` |
| pull request with the same paths | `apk`, `viewer` | artifacts |
| *Actions → Build APK → Run workflow* | `apk`, `viewer` | artifacts |
| tag `v*` | `apk`, `viewer`, then `release` once both are green | GitHub Release with the APKs and `SHA256SUMS.txt` |
| push to the default branch or pull request touching `backend/**` or `samples/**` (the tests read `samples/Rhino_Logo.3dm`) | Backend CI: `test`, `image` | image `ghcr.io/<owner>/rhino-appserver:<sha>` and `:latest`, pushed from the default branch only |

Release: set `version:` in `app/pubspec.yaml` (e.g. `0.2.0+2` — the `+N` build number must increase
for Android to accept the update), commit, then

```sh
git tag v0.2.0 && git push origin v0.2.0
```

The build fails immediately if the tag does not match the pubspec version. Superseded runs on the same
branch are cancelled; tag builds never are. Re-running a job replaces the artifacts of the earlier
attempt. The workflows trigger on `main` and `master` (this repository's default branch is `master`);
the backend image is pushed from whichever is the default.

## Optional backend: appserver + Rhino.Compute

Only needed when files without render meshes turn up regularly and cannot be fixed at the source.

**Fix at the source (Rhino):** *File → Save As* with **Save small unticked** (scripted: `-_SaveAs`,
option `SaveSmall=No`). Render meshes only exist for objects that have been drawn in a shaded viewport,
so switch a viewport to *Shaded* or run `_RefreshShade` on everything before saving. Alternatively run
`_Mesh` on the objects and save the resulting mesh objects. Files written by scripts (`rhino3dm`,
headless exporters) never contain render meshes.

**Deploy the appserver** (any host with Docker; image built by `backend-ci.yml`, tags `latest` and the
full commit sha, linux/amd64):

```sh
docker run -d --name rhino-appserver --restart unless-stopped -p 8080:8080 \
  -e APP_API_KEY=change-me \
  -e COMPUTE_URL=http://192.168.1.50:5000/ -e COMPUTE_API_KEY=your-rhino-compute-key \
  ghcr.io/khodorhaj00/rhino-appserver:latest
curl http://localhost:8080/health
```

or from source: `cd backend && cp .env.example .env && docker compose up -d --build`. The GHCR package is
private by default: make it public in the package settings or `docker login ghcr.io` on the host with a
token that has `read:packages`.

| Var | Default | Meaning |
|---|---|---|
| `PORT` | `8080` | listen port |
| `APP_API_KEY` | (empty) | if set, every request except `GET /health` needs `X-Api-Key` |
| `COMPUTE_URL` | `http://localhost:5000/` | Rhino.Compute base URL; empty disables Compute |
| `COMPUTE_API_KEY` | (empty) | sent as `RhinoComputeKey` |
| `COMPUTE_TIMEOUT_MS` | `120000` | per Compute call |
| `COMPUTE_BATCH` | `20` | Breps per Compute call |
| `MAX_UPLOAD_MB` | `200` | body limit → `413` |
| `MESH_QUALITY` | `default` | `draft` / `default` / `fine` when the request has no `quality` |
| `LOG_LEVEL` | `info` | `error` / `warn` / `info` / `debug` |

**Rhino.Compute on Windows.** Compute is a Windows process backed by Rhino 8; it does not run in a
Linux container. A workshop LAN setup is a Windows VM or workstation with Rhino 8 installed:

1. Follow [Deploy to IIS](https://developer.rhino3d.com/guides/compute/deploy-to-iis/) and
   [Configure Compute for production](https://developer.rhino3d.com/guides/compute/configure-compute-for-production/).
   On Windows Server, Rhino 8 Compute bills **core-hours** to your Rhino account while it runs (the
   guides cover idle shutdown); on a desktop Windows machine it uses the Rhino licence logged in there.
2. Set the `RhinoComputeKey` on the Compute host and put it in `COMPUTE_API_KEY`; point `COMPUTE_URL`
   at `http://<host>:5000/` (or the IIS binding). `GET /health` on the appserver reports
   `compute.reachable`.
3. In the app, *Settings*: *Backend URL* `http://<appserver>:8080`, *API key*, *Mesh quality*, then
   *Test connection* (amber when the appserver answers but Compute is missing or unreachable). The
   banner's *Mesh on server* posts the file to `/mesh` — upload progress and a *Cancel* button in a
   banner, the model stays usable meanwhile — stores the result as `<sha256>.meshed.3dm` and reloads.

The app allows cleartext `http://` because workshop servers rarely have TLS; anything reachable from the
internet belongs behind an https reverse proxy with `APP_API_KEY` set.

## API reference

Bodies are the raw `.3dm` bytes (`Content-Type: application/octet-stream`); optional
`?quality=draft|default|fine&name=<filename>`. Errors are `{ "error": "<code>", "detail": "<text>" }`.

| Route | Response |
|---|---|
| `GET /health` | `{ ok, version, uptimeSec, compute: { url, configured, reachable } }`; never needs the key |
| `POST /mesh` | the same `.3dm` with every unmeshed Brep / Extrusion / SubD replaced by a Mesh object carrying the original attributes; headers `X-Meshed-Count`, `X-Skipped-Count`, `X-Compute-Ms` |
| `POST /convert` | binary glTF (`model/gltf-binary`) of all renderable geometry, one node per object, layer/object colours, Z-up → Y-up; headers `X-Object-Count`, `X-Triangle-Count`, `X-Skipped-Count` |

Error codes: `400 invalid_file` / `bad_request`, `401 unauthorized`, `404 not_found`, `413 too_large`
(refused from `Content-Length` before the body is read), `502 compute_unreachable` / `compute_error`,
`504 compute_timeout`, `500 internal`.

```sh
curl -H "X-Api-Key: $KEY" -H 'Content-Type: application/octet-stream' --data-binary @part.3dm \
     "http://appserver:8080/mesh?quality=fine&name=part.3dm" -o part.meshed.3dm -D -
curl -H "X-Api-Key: $KEY" -H 'Content-Type: application/octet-stream' --data-binary @part.3dm \
     "http://appserver:8080/convert?name=part.3dm" -o part.glb
```

Full details (headers, node layout, error table, operational notes): [backend/README.md](backend/README.md).

## Troubleshooting

| Symptom | Cause / fix |
|---|---|
| Banner "N objects have no render mesh", parts missing | File saved with *Save small*, or by a script. Re-save in Rhino as described above, or *Mesh on server*. |
| Rhino Viewer not offered under *Open with* | The sender reports a MIME type the app does not register. Use *Share to* or *Open .3dm* in the app. |
| "App not installed" / "conflicts with an existing package" | Signature mismatch between a debug-signed and a release-signed build, or a lower version code — which is what a switch from a per-ABI APK to the universal one (or between ABIs) looks like to Android. Uninstall, then install. |
| *Test connection* fails | URL must include the scheme and port (`http://192.168.1.20:8080`); the phone must be on the same network as the server; firewall on port 8080; `APP_API_KEY` set on the server but not in the app. |
| `/health` shows `compute.reachable: false` | Compute not running, wrong `COMPUTE_URL` (port 5000, trailing slash), firewall on the Windows host, or the appserver container cannot reach the host (`host.docker.internal`, see `backend/docker-compose.yml`). |
| *Mesh on server* returns `502 compute_unreachable` | Compute is not configured (`COMPUTE_URL` empty) or down. `compute_error` carries Compute's own message, usually a licence or key problem. |
| `413 too_large`, or *Mesh on server* failing with "the server closed the connection while the file was being uploaded" | The file is above the server's `MAX_UPLOAD_MB`: the appserver refuses it from the `Content-Length` and closes the connection, which the phone often sees as a dropped upload rather than the 413 itself. Raise `MAX_UPLOAD_MB` on the server (memory roughly 3× the file size). |
| Big file is slow to open or the viewer reloads | Parsing is on-device and needs several times the file size in memory; a 100 MB+ file on a mid-range phone is at the limit. Purge unused layers/blocks in Rhino or convert to a mesh file. |
| Colours differ from Rhino's rendered view | By design: materials are ignored, objects are drawn in object/layer colour, and very dark colours are lightened on screen (exports keep the file colour). |
| CI run annotated "Unsigned build" | The four signing secrets are missing; see [Signing](#signing-keystore-for-ci). |
| Tag build fails at "Version and commit metadata" | Tag `vX.Y.Z` must equal `version:` in `app/pubspec.yaml`. Bump, commit, re-tag. |
| `viewer` job fails (on a tag this also holds back the release) | Download `viewer-screenshots-<sha>` from the run for the rendered fixtures; the log lists the failed check. |
| Backend image not on GHCR after a push | Images are pushed only from the default branch and only when `backend/**` or `samples/**` changed. |

## Repository layout

```
app/                      Flutter Android app (package com.styro3d.rhino_viewer)
  assets/viewer/          three.js r186 + rhino3dm 8.32.2 viewer page, vendored, offline (PATCHES.md)
  lib/                    Dart: models, JS bridge, services, home / viewer / settings screens
  android/                Gradle with key.properties release signing, intent filters, MainActivity.kt
  tool/viewer_test/       Playwright harness for the viewer page (node run.mjs)
backend/                  Node 22 / Express 5 appserver: /health, /mesh, /convert; Dockerfile, compose
  test/fixtures/          synthetic .3dm fixtures + make_fixtures.py (see samples/README.md)
samples/Rhino_Logo.3dm    real Rhino-saved sample (three.js repository)
scripts/                  gen-keystore.sh, set-github-secrets.sh
docs/ARCHITECTURE.md      contracts between app, viewer page, backend and CI
.github/workflows/        build-apk.yml (analyze, test, APKs, release, viewer harness), backend-ci.yml
index.html, index_files/  pre-existing GitHub Pages site, not part of the app
```
