# Patches to vendored code

Everything under `vendor/` is upstream code (three.js r186, rhino3dm 8.32.2) and must stay
byte-identical to upstream **except** the patches documented here, all of them in
`vendor/three/addons/loaders/3DMLoader.js` and tagged `PATCH(<name>)` in the source. When
upgrading three.js, re-apply every hunk of the combined diff at the end of this file.

| Tag | What |
|---|---|
| `no-mesh` | report Breps / Extrusions that carry no render mesh |
| `init-error` | tell the main thread when rhino3dm is usable in the worker, or when it failed |
| `invalid-file` | fail a decode with a readable message when the bytes are not a `.3dm` |

## 1. `no-mesh` — report Breps / Extrusions that carry no render mesh

### Why

Rhino only stores render meshes in a `.3dm` when the file was saved normally. Files saved
with *Save small*, or written by scripts/exporters (rhino3dm, Grasshopper, …), contain
Breps and Extrusions **without** cached meshes. The stock loader silently drops those
objects (the Brep case appends zero face meshes, the Extrusion case gets `null` from
`getMesh()`), then falls through to a generic `missing mesh` warning that does not say
*why* the object vanished or what kind of object it was.

The app needs to tell the user "N objects have no render mesh" and offer server-side
meshing (see `docs/ARCHITECTURE.md` §1 and §3.4), so the worker now posts a dedicated
warning for exactly these two cases:

```js
{ type: 'no mesh', objectType: 'Brep' | 'Extrusion', guid, message }
```

The loader's existing `warning` channel forwards it to `object.userData.warnings`;
`viewer.js` derives `stats.unmeshed` from the entries whose `type` is `'no mesh'`.

### Where

Inside `function Rhino3dmWorker()`. The worker source is produced at runtime by
`Rhino3dmWorker.toString()` and loaded into a Blob worker, so the helper
`postNoMeshWarning()` **must** live inside that function body — nothing outside it is
visible to the worker.

The Brep hunk also moves `faces.delete()` out of the `count > 0` branch: upstream only
frees the `BrepFaceList` when at least one face was meshed, which leaks a WASM object per
unmeshed Brep. Both cases `return` after posting the warning, so the generic
`missing mesh` warning is not emitted a second time for the same object.

## 2. `init-error` — worker readiness and initialisation failure

### Why

Upstream `_getWorker()` resolves as soon as the `Worker` exists and the `init` message is
posted; the 2.6 MB WASM is compiled later inside the worker. So there was no way to know
when rhino3dm is actually usable (`viewerReady` must mean that, `docs/ARCHITECTURE.md`
§2.2), and the first `load()` paid for the compile.

Worse, the worker's `init` wrapped `rhino3dm(RhinoModule)` in a promise that only
`onRuntimeInitialized` could settle and discarded the factory's own promise. When the WASM
cannot be instantiated (out of memory on a constrained device, a corrupt asset) the factory
rejects, `onRuntimeInitialized` never fires, every `decode` waits on that promise forever,
and `parseAsync()` never settles — `load()` hangs with no `loadResult`.

### What

Worker side (inside `Rhino3dmWorker`):

* `rhino3dm(RhinoModule).catch(reject)` routes the factory rejection into `libraryPending`.
* On success the worker posts `{ type: 'ready' }`; on failure it remembers `initError` and
  posts `{ type: 'error', id: 0, error }` (id 0 = not a task).
* Every `decode` throws `initError` first when it is set, so it answers with a normal
  per-task `error` instead of hanging.

Main-thread side (`_getWorker`):

* `worker._ready` is a promise that `ready` resolves and an `error` with `id === 0`
  rejects; `worker.onerror` (script failed to evaluate) rejects it too and rejects every
  pending task.
* Per-task `error` messages are handled as before.

`viewer.js` waits for `worker._ready` before emitting `viewerReady` and at the start of
every `load()`, so an initialisation failure becomes a `log` error plus a
`loadResult { ok: false }`.

## 3. `invalid-file` — readable error for non-`.3dm` bytes

`rhino.File3dm.fromByteArray()` returns `null` (not an exception) when the bytes are not a
complete `.3dm` (truncated transfer, garbage after a valid magic header). Upstream then
dereferences `doc.objects()` and the user sees
`Cannot read properties of null (reading 'objects')`. The worker now throws
`Not a valid or complete .3dm file`, which reaches `loadResult.error` unchanged.

## Combined diff (`diff -u` against upstream r186)

```diff
--- a/app/assets/viewer/vendor/three/addons/loaders/3DMLoader.js
+++ b/app/assets/viewer/vendor/three/addons/loaders/3DMLoader.js
@@ -1021,6 +1021,23 @@
 				worker._taskCosts = {};
 				worker._taskLoad = 0;
 
+				// PATCH(init-error): settles once the worker has instantiated rhino3dm, or
+				// rejects when it cannot (WASM compile/memory failure, broken script). See PATCHES.md.
+				worker._ready = new Promise( ( resolve, reject ) => {
+
+					worker._readyResolve = resolve;
+					worker._readyReject = reject;
+
+				} );
+
+				worker.onerror = ( event ) => {
+
+					const message = { type: 'error', id: 0, error: { message: 'rhino3dm worker error: ' + ( event.message || 'unknown' ) } };
+					worker._readyReject( message );
+					for ( const id in worker._callbacks ) worker._callbacks[ id ].reject( message );
+
+				};
+
 				worker.postMessage( {
 					type: 'init',
 					libraryConfig: this.libraryConfig
@@ -1037,12 +1054,19 @@
 							console.warn( message.data );
 							break;
 
+						case 'ready':
+							// PATCH(init-error): rhino3dm is usable inside the worker.
+							worker._readyResolve();
+							break;
+
 						case 'decode':
 							worker._callbacks[ message.id ].resolve( message );
 							break;
 
 						case 'error':
-							worker._callbacks[ message.id ].reject( message );
+							// PATCH(init-error): id 0 is the library initialisation itself, not a task.
+							if ( message.id === 0 ) worker._readyReject( message );
+							else worker._callbacks[ message.id ].reject( message );
 							break;
 
 						default:
@@ -1108,6 +1132,7 @@
 	let libraryConfig;
 	let rhino;
 	let taskID;
+	let initError; // PATCH(init-error)
 
 	onmessage = function ( e ) {
 
@@ -1120,16 +1145,25 @@
 				libraryConfig = message.libraryConfig;
 				const wasmBinary = libraryConfig.wasmBinary;
 				let RhinoModule;
-				libraryPending = new Promise( function ( resolve ) {
+				libraryPending = new Promise( function ( resolve, reject ) {
 
 					/* Like Basis Loader */
 					RhinoModule = { wasmBinary, onRuntimeInitialized: resolve };
 
-					rhino3dm( RhinoModule ); // eslint-disable-line no-undef
+					// PATCH(init-error): the factory's promise rejects when the WASM cannot be
+					// instantiated; upstream drops it and every decode then waits forever.
+					rhino3dm( RhinoModule ).catch( reject ); // eslint-disable-line no-undef
 
 				 } ).then( () => {
 
 					rhino = RhinoModule;
+					self.postMessage( { type: 'ready' } ); // PATCH(init-error)
+
+				 }, ( error ) => {
+
+					// PATCH(init-error): report once with id 0 (not a task); decodes fail fast below.
+					initError = new Error( 'rhino3dm failed to initialise: ' + ( error && error.message ? error.message : error ) );
+					self.postMessage( { type: 'error', id: 0, error: { message: initError.message, stack: error && error.stack } } );
 
 				 } );
 
@@ -1144,6 +1178,8 @@
 
 					try {
 
+						if ( initError ) throw initError; // PATCH(init-error)
+
 						const data = decodeObjects( rhino, buffer, subdivisionLevel );
 						// Transfer the mesh typed arrays (fast path) instead of structure-cloning
 						// them across the worker boundary.
@@ -1221,6 +1257,10 @@
 		const arr = new Uint8Array( buffer );
 		const doc = rhino.File3dm.fromByteArray( arr );
 
+		// PATCH(invalid-file): rhino3dm returns null (no exception) when the bytes are not a
+		// complete .3dm; without this the failure surfaces as a TypeError on `doc.objects()`.
+		if ( ! doc ) throw new Error( 'Not a valid or complete .3dm file' );
+
 		const objects = [];
 		const materials = [];
 		const layers = [];
@@ -1634,11 +1674,20 @@
 
 				}
 
+				faces.delete();
+
 				if ( mesh.faces().count > 0 ) {
 
 					mesh.compact();
 					geometry = meshToThreejs( mesh );
-					faces.delete();
+
+				} else {
+
+					// PATCH(no-mesh): the file carries no cached render mesh for this Brep
+					// ("Save small" or script-generated). Report it so the app can offer server meshing.
+					mesh.delete();
+					postNoMeshWarning( 'Brep', _attributes.id );
+					return;
 
 				}
 
@@ -1655,6 +1704,12 @@
 					geometry = meshToThreejs( mesh );
 					mesh.delete();
 
+				} else {
+
+					// PATCH(no-mesh): see Brep case above.
+					postNoMeshWarning( 'Extrusion', _attributes.id );
+					return;
+
 				}
 
 				break;
@@ -1781,6 +1836,22 @@
 
 	}
 
+	// PATCH(no-mesh): a Brep with zero meshed faces or an Extrusion without a mesh is
+	// reported as `{ type: 'no mesh', objectType, guid, message }` (lands in
+	// object.userData.warnings on the main thread). See PATCHES.md.
+	function postNoMeshWarning( objectType, guid ) {
+
+		self.postMessage( { type: 'warning', id: taskID, data: {
+			message: `THREE.3DMLoader: ${objectType} ${guid} has no render mesh (file saved with "Save small" or written by a script).`,
+			type: 'no mesh',
+			objectType: objectType,
+			guid: guid
+		}
+
+		} );
+
+	}
+
 	function extractProperties( object ) {
 
 		const result = {};
```
