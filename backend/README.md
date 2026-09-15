# Rhino appserver

Node 22 / Express 5 service that sits between the Rhino Viewer app and **Rhino.Compute**:

* `POST /mesh` — tessellates the Breps / Extrusions / SubDs of a `.3dm` that has no cached render
  meshes (files saved with *Save small* or produced by scripts) and returns a `.3dm` the app renders
  offline.
* `POST /convert` — converts a `.3dm` into a binary glTF (`.glb`).

The appserver runs anywhere Docker runs and does all parsing itself with `rhino3dm` (WebAssembly
OpenNURBS). Only tessellation of Breps needs Rhino.Compute, which is **Windows-only** and needs a
licensed Rhino 8 (core-hour billing) — see [Rhino.Compute](#rhinocompute).

## Run

```sh
cp .env.example .env            # edit COMPUTE_URL / keys
docker compose up -d --build
curl http://localhost:8080/health
```

Without Docker: `npm ci && npm start` (Node 22+). Tests: `npm test` (offline, Compute is faked).

Under docker compose `COMPUTE_URL` defaults to `http://host.docker.internal:5000/` (the Docker
host; `localhost` inside the container is the appserver itself) and `COMPUTE_URL=` in `.env`
disables Compute, like an empty value does without Docker.

## Environment

| Var | Default | Meaning |
|---|---|---|
| `PORT` | `8080` | listen port |
| `APP_API_KEY` | (empty) | if set, every request except `GET /health` must send `X-Api-Key` equal to it (constant-time compare) |
| `COMPUTE_URL` | `http://localhost:5000/` (`http://host.docker.internal:5000/` under docker compose) | Rhino.Compute base URL (`rhino.compute` front end, port 5000 by default). **Empty** = Compute disabled |
| `COMPUTE_API_KEY` | (empty) | sent as the `RhinoComputeKey` header |
| `COMPUTE_TIMEOUT_MS` | `120000` | per Compute call |
| `COMPUTE_BATCH` | `20` | Breps per Compute call |
| `MAX_UPLOAD_MB` | `200` | request body limit → `413` |
| `MESH_QUALITY` | `default` | `draft` / `default` / `fine` when the request has no `quality` parameter |
| `LOG_LEVEL` | `info` | `error` / `warn` / `info` / `debug` |

## API

Bodies for `/mesh` and `/convert` are the raw `.3dm` bytes (`Content-Type: application/octet-stream`).
Optional query parameters: `quality=draft|default|fine` and `name=<original filename>` (used in
logs, the glTF asset name and `Content-Disposition`).

Errors are JSON: `{ "error": "<code>", "detail": "<text>" }`.

| Status | `error` | When |
|---|---|---|
| 400 | `invalid_file` | body empty, magic bytes missing, or rhino3dm cannot parse it |
| 400 | `bad_request` | `quality` is not `draft`, `default` or `fine`; the body was cut short or aborted (415 for a `Content-Encoding` other than identity/gzip/deflate/br) |
| 401 | `unauthorized` | `APP_API_KEY` set and `X-Api-Key` missing/wrong |
| 404 | `not_found` | unknown route |
| 413 | `too_large` | body above `MAX_UPLOAD_MB` (answered from the `Content-Length` header before the body is read; the connection is then closed, so a client still sending the body may see a dropped connection instead of this response) |
| 502 | `compute_unreachable` | Compute not configured or not reachable over the network |
| 502 | `compute_error` | Compute answered with a non-2xx status (`detail` carries its message) |
| 504 | `compute_timeout` | Compute did not answer within `COMPUTE_TIMEOUT_MS` |
| 500 | `internal` | anything else (logged with a stack trace) |

### `GET /health`

Never requires the API key.

```json
{ "ok": true, "version": "1.0.0", "uptimeSec": 42,
  "compute": { "url": "http://192.168.1.50:5000/", "configured": true, "reachable": true } }
```

`reachable` is probed with `GET <COMPUTE_URL>version` (3 s timeout, `true` only on a 2xx answer);
`null` when Compute is not configured.

### `POST /mesh`

Returns `200 application/octet-stream`: the same `.3dm` in which every Brep and Extrusion **without**
a cached render mesh, and every SubD, is replaced by a Mesh object carrying the original
`ObjectAttributes` (id, name, layer, color source, object color, user strings; objects inside block
definitions included). Breps go to Compute (`Mesh.CreateFromBrep` with the requested
`MeshingParameters`) in batches of `COMPUTE_BATCH`; Extrusions are converted to Breps locally first;
SubDs are meshed locally by subdividing the control net twice (no Compute).

Headers: `X-Meshed-Count`, `X-Skipped-Count` (objects Compute returned nothing for), `X-Compute-Ms`.
When nothing needs meshing the original bytes come back unchanged with `X-Meshed-Count: 0` and
Compute is never contacted. Replaced objects move to the end of the object table.

```sh
curl -H "X-Api-Key: $KEY" --data-binary @part.3dm -H 'Content-Type: application/octet-stream' \
     "http://localhost:8080/mesh?quality=fine&name=part.3dm" -o part.meshed.3dm -D -
```

### `POST /convert`

Returns `200 model/gltf-binary` with `Content-Disposition: attachment; filename="<name>.glb"`.

* Geometry: Mesh objects, the cached render meshes of Breps and Extrusions, SubDs (control net
  subdivided ×2 locally), block instances expanded with their nested transforms. Breps/Extrusions
  without render meshes are meshed through Compute when it is configured, otherwise counted in
  `X-Skipped-Count`. Curves, points, point clouds, text dots, lights and annotations are not
  renderable and are left out.
* Hidden objects and objects on hidden layers are omitted (the GLB is what Rhino shows).
* One node per object, `name` = object name or id, `extras` = `{ id, layer, layerIndex, userStrings }`.
  A block reference is a node with the instance `matrix` and one child per definition object;
  nested blocks nest further. A definition's glTF mesh is shared by all its instances.
* One material per distinct color: the object color when the color source is *by object*,
  the parent's color for *by parent* inside a block, otherwise the layer color. Materials stored in
  the file are ignored (they are unreliable in production files).
* The root node carries the Z-up → Y-up rotation; vertex data stays in the file's units, which are
  recorded in `asset.extras.units` and the root node's `extras.units`.
* Accessors: `POSITION` float32 with min/max, `NORMAL` float32 (mesh normals, or per-vertex normals
  computed from the triangles when the mesh has none), `indices` uint32. Quads are triangulated.

Headers: `X-Object-Count` (top-level objects in the GLB), `X-Triangle-Count` (as rendered —
instances count each time), `X-Skipped-Count`, `X-Compute-Ms`.

## Rhino.Compute

Rhino.Compute is a Windows process backed by a licensed Rhino 8; it cannot run in a Linux
container. Run it on a Windows VM or workstation reachable from the appserver:

1. Follow [Deploy to IIS](https://developer.rhino3d.com/guides/compute/deploy-to-iis/) and
   [Configure Compute for production](https://developer.rhino3d.com/guides/compute/configure-compute-for-production/).
   Rhino 8 Compute bills by core-hour through your Rhino account.
2. Set an API key on the Compute host and put it in `COMPUTE_API_KEY`; set `COMPUTE_URL` to
   `http://<host>:5000/` (or the IIS binding you chose).
3. `GET /health` on the appserver shows whether Compute answers.

## Operational notes

* `rhino3dm` parses the whole file into WebAssembly memory synchronously; a request blocks the
  event loop for the parse (about 100 ms for a 5 MB file) and needs roughly three times the file
  size in memory. Run several replicas behind a load balancer for throughput rather than expecting
  one process to overlap requests.
* Logging: one JSON line per request on stdout —
  `{ts, level, method, path, status, ms, bytesIn, bytesOut, meshed, skipped, aborted}`; `aborted`
  is `true` when the client dropped the connection before the response was delivered (an upload
  cut short by the phone going to sleep, for example). Compute failures are logged at `warn`,
  unexpected errors at `error` with the stack.
* Only the API-key check protects the endpoints; put the service behind TLS (reverse proxy) when it
  is reachable from outside the workshop network.

## Layout

```
src/server.js    entrypoint: env → config, Compute client, HTTP server, graceful shutdown
src/app.js       Express app (createApp({ config, compute, logger })) — routes, auth, errors, logging
src/config.js    environment parsing
src/compute.js   Compute client on top of compute-rhino3d (timeout, API key, error mapping)
src/meshing.js   /mesh pipeline: find unmeshed objects, batch Compute calls, replace in the File3dm
src/scene.js     /convert pipeline: read objects → triangles → glTF nodes (instances, colors)
src/geometry.js  rhino3dm Mesh → triangles, Brep/Extrusion/SubD mesh access, Compute JSON decoding
src/glb.js       hand-written binary glTF 2.0 writer (+ parser used by tests)
src/rhino.js     rhino3dm initialisation and small helpers
test/            node --test suite; fixtures in test/fixtures (generated by make_fixtures.py)
```
