# Patches to vendored code

Everything under `vendor/` is upstream code (three.js r186, rhino3dm 8.35.0) and must stay
byte-identical to upstream **except** the patches documented here, all of them in
`vendor/three/addons/loaders/3DMLoader.js` and tagged `PATCH(<name>)` in the source. When
upgrading three.js, re-apply every hunk of the combined diff at the end of this file.

| Tag | What |
|---|---|
| `no-mesh` | report Breps / Extrusions that carry no render mesh |
| `init-error` | tell the main thread when rhino3dm is usable in the worker, or when it failed |
| `invalid-file` | fail a decode with a readable message when the bytes are not a `.3dm` |
| `curve-accuracy` | sample curves adaptively to a chord tolerance instead of 100 fixed points |
| `annotations` | convert dimensions, text, leaders and hatches instead of dropping them |

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

## 4. `curve-accuracy` — curves keep their real shape

### Why

Upstream samples every curve at 100 parameter-uniform points (arcs every 5°), whatever
its length or detail: a long traced outline or lettering loses its shape, and dense knot
regions get the same few samples as flat ones. (Its angle filter never runs: it reads
`tan.x` from an array, so every sample is kept.)

### What

`curveToPoints( curve )` walks the curve by knot span and splits each span in half until
the midpoint lies within a chord tolerance of the chord, with a minimum split for curved
spans; line, polyline and degree-1 curves keep their own vertices; arcs are sampled by
angle; anything else goes through `toNurbsCurve()`. The tolerance is relative to each
curve's bounding box and comes from `loader.curveQuality` (sent with every `decode`
message):

| Quality | Chord tolerance | Arc step | Points per curve (cap) |
|---|---|---|---|
| `standard` | 1/1000 of the curve's size | 5° | 2 000 |
| `high` (default) | 1/5000 | 2° | 8 000 |
| `max` | 1/20000 | 1° | 32 000 |

## 5. `annotations` — dimensions, text, leaders and hatches

### Why

Upstream skips `Annotation` and `Hatch` objects ("Conversion not implemented"), so
drawings arrive without their dimensions, notes and fills.

### What

Worker side, in `extractObjectData`:

* `Annotation` → `extractAnnotation()` returns `{ kind, text, plane, normal, textHeight,
  textGap, font, bold, italic, drawForward, lines, dimensionLine?, arrows, label }`.
  Sizes are Rhino's: with rhino3dm ≥ 8.35 the object's effective style
  (`getDimensionStyle(parent)`, its property overrides applied), `getTextHeight(parent)`
  and the model-space scale `getDimensionScale(parent)`, which multiplies the text height
  and every style length (arrows, gaps, extension offsets, landings, centre marks). The font
  is `getFont(parent)` plus the `\b`, `\i` and `\fN` runs of the rich text. Text Rhino has
  not formatted yet (a file written before the dimension was ever drawn) is measured here —
  the definition points along the dimension line, or the radius — times the style's length
  factor, and `<>` in user text stands for that value. A linear dimension whose arrow points
  coincide although its definition points do not is rebuilt from the definition points and
  the dimension line point.
  Text justification is not exposed by rhino3dm, but the style's own record
  (`style.encode()`) ends in a fixed block whose int32 fields 98, 94, 90 and 86 bytes from
  the end read `1`, vertical alignment (0 top … 6 bottom of box), horizontal alignment
  (0 left, 1 centre, 2 right, 3 auto) and `1` — found by diffing Rhino 8 texts written in
  every alignment and checked against Rhino 7 and 8 production files. When the two `1`
  markers are not there the text falls back to Rhino's default, top left. Linear (`Aligned`, `Rotated`)
  dimensions are rebuilt from `points` (`defpt1/2`, `arrowpt1/2`, `dimline`, `textpt`)
  and the dimension style's offsets and arrowheads; radial ones from `centerpt`,
  `radiuspt`, `kneept`, `dimlinept`; leaders from their polyline and
  `getTextPoint2d()`; text from its plane. Other kinds use `getDisplayLines()`.
  rhino3dm's `getDisplayLines()` is not used for linear dimensions: without font metrics
  its text rectangle is uninitialised memory and the dimension line comes back cut short.
  Dimension styles are looked up once per decode (`dimstyleCache`) and freed at its end;
  the style table itself is never `delete()`d, its `delete( id )` shadows the destructor.
* `Hatch` → `extractHatch()`. rhino3dm exposes no hatch loops, but `encode()` returns the
  hatch's opennurbs record, in which every loop is a version byte (`0x11`), an `int` loop
  type (0 outer, 1 inner) and the 2D boundary curve as an embedded class record
  (`TCODE_OPENNURBS_CLASS` = `0x00027FFA`, 8-byte length). Each such record is handed to
  `CommonObject.decode()` on its own and sampled with `curveToPoints()`. Result:
  `{ plane, patternIndex, loops: [{ outer, points: [u, v, ...] }] }`; a hatch whose loops
  cannot be read posts a `no conversion` warning.

Main-thread objects are built by `viewer.js` / `annotations.js` (`_createObject`
override), not by the loader.

## Combined diff (`diff -u` against upstream r186)

```diff
--- a/app/assets/viewer/vendor/three/addons/loaders/3DMLoader.js
+++ b/app/assets/viewer/vendor/three/addons/loaders/3DMLoader.js
@@ -84,6 +84,9 @@
 		// values increase smoothness at the cost of (potentially very large) vertex counts.
 		this.subdivisionLevel = 3;
 
+		// PATCH(curve-accuracy): 'standard' | 'high' | 'max', sent with every decode.
+		this.curveQuality = 'high';
+
 		this.materials = [];
 		this.warnings = [];
 
@@ -212,7 +215,8 @@
 
 					worker._callbacks[ taskID ] = { resolve, reject };
 
-					worker.postMessage( { type: 'decode', id: taskID, buffer, subdivisionLevel: this.subdivisionLevel }, [ buffer ] );
+					// PATCH(curve-accuracy): the worker samples curves to this quality ('standard' | 'high' | 'max').
+					worker.postMessage( { type: 'decode', id: taskID, buffer, subdivisionLevel: this.subdivisionLevel, curveQuality: this.curveQuality }, [ buffer ] );
 
 				} );
 
@@ -1021,6 +1025,23 @@
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
@@ -1037,12 +1058,19 @@
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
@@ -1108,6 +1136,19 @@
 	let libraryConfig;
 	let rhino;
 	let taskID;
+	let initError; // PATCH(init-error)
+
+	// PATCH(curve-accuracy): chord tolerance as a fraction of each curve's own size, arc step,
+	// and the per-curve point cap. See curveToPoints().
+	const CURVE_QUALITY = {
+		standard: { relTol: 1e-3, arcStepDeg: 5, maxPoints: 2000 },
+		high: { relTol: 2e-4, arcStepDeg: 2, maxPoints: 8000 },
+		max: { relTol: 5e-5, arcStepDeg: 1, maxPoints: 32000 }
+	};
+	let curveTolerances = CURVE_QUALITY.high;
+
+	// PATCH(annotations): dimension styles by id, looked up once per decode.
+	let dimstyleCache = null;
 
 	onmessage = function ( e ) {
 
@@ -1120,16 +1161,25 @@
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
 
@@ -1140,10 +1190,13 @@
 				taskID = message.id;
 				const buffer = message.buffer;
 				const subdivisionLevel = message.subdivisionLevel;
+				curveTolerances = CURVE_QUALITY[ message.curveQuality ] || CURVE_QUALITY.high; // PATCH(curve-accuracy)
 				libraryPending.then( () => {
 
 					try {
 
+						if ( initError ) throw initError; // PATCH(init-error)
+
 						const data = decodeObjects( rhino, buffer, subdivisionLevel );
 						// Transfer the mesh typed arrays (fast path) instead of structure-cloning
 						// them across the worker boundary.
@@ -1221,6 +1274,10 @@
 		const arr = new Uint8Array( buffer );
 		const doc = rhino.File3dm.fromByteArray( arr );
 
+		// PATCH(invalid-file): rhino3dm returns null (no exception) when the bytes are not a
+		// complete .3dm; without this the failure surfaces as a TypeError on `doc.objects()`.
+		if ( ! doc ) throw new Error( 'Not a valid or complete .3dm file' );
+
 		const objects = [];
 		const materials = [];
 		const layers = [];
@@ -1234,20 +1291,32 @@
 		const objs = doc.objects();
 		const cnt = objs.count;
 
-		for ( let i = 0; i < cnt; i ++ ) {
+		dimstyleCache = new Map(); // PATCH(annotations)
+
+		try {
 
-			const _object = objs.get( i );
+			for ( let i = 0; i < cnt; i ++ ) {
 
-			const object = extractObjectData( _object, doc, subdivisionLevel );
+				const _object = objs.get( i );
 
-			_object.delete();
+				const object = extractObjectData( _object, doc, subdivisionLevel );
 
-			if ( object ) {
+				_object.delete();
 
-				objects.push( object );
+				if ( object ) {
+
+					objects.push( object );
+
+				}
 
 			}
 
+		} finally {
+
+			// PATCH(annotations): the looked-up styles are copies owned by this decode.
+			for ( const style of dimstyleCache.values() ) if ( style ) style.delete();
+			dimstyleCache = null;
+
 		}
 
 		// Handle instance definitions
@@ -1554,7 +1623,7 @@
 
 			case rhino.ObjectType.Curve:
 
-				const pts = curveToPoints( _geometry, 100 );
+				const pts = curveToPoints( _geometry ); // PATCH(curve-accuracy): was a fixed 100 samples
 
 				position = {};
 				attributes = {};
@@ -1634,11 +1703,20 @@
 
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
 
@@ -1655,6 +1733,12 @@
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
@@ -1705,9 +1789,35 @@
 
 				break;
 
+			// PATCH(annotations): dimensions, text and leaders become lines, arrowheads and a
+			// text placement; hatches become their boundary loops. Built on the main thread.
+			case rhino.ObjectType.Annotation:
+
+				geometry = extractAnnotation( _geometry, doc );
+
+				break;
+
+			case rhino.ObjectType.Hatch:
+
+				geometry = extractHatch( _geometry );
+
+				if ( ! geometry ) {
+
+					self.postMessage( { type: 'warning', id: taskID, data: {
+						message: 'THREE.3DMLoader: Hatch boundary could not be read.',
+						type: 'no conversion',
+						guid: _attributes.id
+					}
+
+					} );
+
+					return;
+
+				}
+
+				break;
+
 				/*
-				case rhino.ObjectType.Annotation:
-				case rhino.ObjectType.Hatch:
 				case rhino.ObjectType.ClipPlane:
 				*/
 
@@ -1781,6 +1891,22 @@
 
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
@@ -1817,118 +1943,704 @@
 
 	}
 
-	function curveToPoints( curve, pointLimit ) {
+	// PATCH(curve-accuracy): curves are sampled adaptively against a chord tolerance relative
+	// to each curve's own size (per knot span, arcs by angle) instead of a fixed 100 uniform
+	// samples, so long or detailed curves keep their real shape. Returns [ [x, y, z], ... ].
+	function curveToPoints( curve ) {
 
-		let pointCount = pointLimit;
-		let rc = [];
-		const ts = [];
+		const out = [];
+		appendCurvePoints( curve, out, curveTolerance( curve ) );
+		return out;
 
-		if ( curve instanceof rhino.LineCurve ) {
+	}
+
+	function curveTolerance( curve ) {
+
+		let diag = 0;
 
-			return [ curve.pointAtStart, curve.pointAtEnd ];
+		try {
+
+			const box = curve.getBoundingBox();
+			diag = Math.hypot( box.max[ 0 ] - box.min[ 0 ], box.max[ 1 ] - box.min[ 1 ], box.max[ 2 ] - box.min[ 2 ] );
+			if ( typeof box.delete === 'function' ) box.delete();
+
+		} catch ( e ) {
+
+			diag = 0;
 
 		}
 
-		if ( curve instanceof rhino.PolylineCurve ) {
+		const tol = diag * curveTolerances.relTol;
+		return tol > 0 && isFinite( tol ) ? tol : 1e-9;
 
-			pointCount = curve.pointCount;
-			for ( let i = 0; i < pointCount; i ++ ) {
+	}
 
-				rc.push( curve.point( i ) );
+	function pushPoint( out, p ) {
 
-			}
+		const last = out[ out.length - 1 ];
+		if ( last && last[ 0 ] === p[ 0 ] && last[ 1 ] === p[ 1 ] && last[ 2 ] === p[ 2 ] ) return;
+		out.push( [ p[ 0 ], p[ 1 ], p[ 2 ] ] );
 
-			return rc;
+	}
+
+	function appendCurvePoints( curve, out, tol ) {
+
+		if ( curve instanceof rhino.LineCurve ) {
+
+			pushPoint( out, curve.pointAtStart );
+			pushPoint( out, curve.pointAtEnd );
+			return;
 
 		}
 
-		if ( curve instanceof rhino.PolyCurve ) {
+		if ( curve instanceof rhino.PolylineCurve ) {
 
-			const segmentCount = curve.segmentCount;
+			for ( let i = 0; i < curve.pointCount; i ++ ) pushPoint( out, curve.point( i ) );
+			return;
 
-			for ( let i = 0; i < segmentCount; i ++ ) {
+		}
+
+		if ( curve instanceof rhino.PolyCurve ) {
+
+			for ( let i = 0; i < curve.segmentCount; i ++ ) {
 
 				const segment = curve.segmentCurve( i );
-				const segmentArray = curveToPoints( segment, pointCount );
-				rc = rc.concat( segmentArray );
+				appendCurvePoints( segment, out, tol );
 				segment.delete();
 
 			}
 
-			return rc;
+			return;
 
 		}
 
 		if ( curve instanceof rhino.ArcCurve ) {
 
-			pointCount = Math.floor( curve.angleDegrees / 5 );
-			pointCount = pointCount < 2 ? 2 : pointCount;
-			// alternative to this hardcoded version: https://stackoverflow.com/a/18499923/2179399
+			const count = Math.max( 2, Math.ceil( Math.abs( curve.angleDegrees ) / curveTolerances.arcStepDeg ) + 1 );
+			const domain = curve.domain;
+			for ( let j = 0; j < count; j ++ ) {
+
+				pushPoint( out, curve.pointAt( domain[ 0 ] + ( j / ( count - 1 ) ) * ( domain[ 1 ] - domain[ 0 ] ) ) );
+
+			}
+
+			return;
 
 		}
 
-		if ( curve instanceof rhino.NurbsCurve && curve.degree === 1 ) {
+		const owned = ! ( curve instanceof rhino.NurbsCurve );
+		const nurbs = owned ? curve.toNurbsCurve() : curve;
+		if ( ! nurbs ) return;
 
-			const pLine = curve.tryGetPolyline();
+		try {
 
-			for ( let i = 0; i < pLine.count; i ++ ) {
+			const params = spanParameters( nurbs );
+			const limit = out.length + curveTolerances.maxPoints;
+			// Straight spans need no subdivision; curved ones are always split a little so a
+			// span whose midpoint happens to sit on the chord is still sampled.
+			const minDepth = nurbs.degree <= 1 ? 0 : ( params.length > 64 ? 1 : 2 );
+			let previous = nurbs.pointAt( params[ 0 ] );
+			pushPoint( out, previous );
 
-				rc.push( pLine.get( i ) );
+			for ( let s = 0; s + 1 < params.length; s ++ ) {
+
+				const next = nurbs.pointAt( params[ s + 1 ] );
+				subdivideSpan( nurbs, params[ s ], previous, params[ s + 1 ], next, tol * tol, 0, minDepth, out, limit );
+				pushPoint( out, next );
+				previous = next;
 
 			}
 
-			pLine.delete();
+		} finally {
 
-			return rc;
+			if ( owned ) nurbs.delete();
 
 		}
 
-		const domain = curve.domain;
-		const divisions = pointCount - 1.0;
+	}
 
-		for ( let j = 0; j < pointCount; j ++ ) {
+	// The increasing, distinct knot values inside the curve's domain, plus both ends.
+	function spanParameters( nurbs ) {
 
-			const t = domain[ 0 ] + ( j / divisions ) * ( domain[ 1 ] - domain[ 0 ] );
+		const domain = nurbs.domain;
+		const eps = Math.abs( domain[ 1 ] - domain[ 0 ] ) * 1e-12;
+		const params = [ domain[ 0 ] ];
+		const knots = typeof nurbs.knots === 'function' ? nurbs.knots() : nurbs.knots;
 
-			if ( t === domain[ 0 ] || t === domain[ 1 ] ) {
+		if ( knots ) {
 
-				ts.push( t );
-				continue;
+			for ( let i = 0; i < knots.count; i ++ ) {
+
+				const k = knots.get( i );
+				if ( k > params[ params.length - 1 ] + eps && k < domain[ 1 ] - eps ) params.push( k );
 
 			}
 
-			const tan = curve.tangentAt( t );
-			const prevTan = curve.tangentAt( ts.slice( - 1 )[ 0 ] );
+			if ( typeof knots.delete === 'function' ) knots.delete();
 
-			// Duplicated from THREE.Vector3
-			// How to pass imports to worker?
+		}
 
-			const tS = tan[ 0 ] * tan[ 0 ] + tan[ 1 ] * tan[ 1 ] + tan[ 2 ] * tan[ 2 ];
-			const ptS = prevTan[ 0 ] * prevTan[ 0 ] + prevTan[ 1 ] * prevTan[ 1 ] + prevTan[ 2 ] * prevTan[ 2 ];
+		params.push( domain[ 1 ] );
+		return params;
 
-			const denominator = Math.sqrt( tS * ptS );
+	}
 
-			let angle;
+	function subdivideSpan( curve, t0, p0, t1, p1, tol2, depth, minDepth, out, limit ) {
 
-			if ( denominator === 0 ) {
+		if ( depth >= 10 || out.length >= limit ) return;
 
-				angle = Math.PI / 2;
+		const tm = ( t0 + t1 ) / 2;
+		const pm = curve.pointAt( tm );
 
-			} else {
+		if ( depth >= minDepth ) {
+
+			const dx = pm[ 0 ] - ( p0[ 0 ] + p1[ 0 ] ) / 2;
+			const dy = pm[ 1 ] - ( p0[ 1 ] + p1[ 1 ] ) / 2;
+			const dz = pm[ 2 ] - ( p0[ 2 ] + p1[ 2 ] ) / 2;
+			if ( dx * dx + dy * dy + dz * dz <= tol2 ) return;
+
+		}
+
+		subdivideSpan( curve, t0, p0, tm, pm, tol2, depth + 1, minDepth, out, limit );
+		pushPoint( out, pm );
+		subdivideSpan( curve, tm, pm, t1, p1, tol2, depth + 1, minDepth, out, limit );
+
+	}
+
+	// PATCH(annotations) ----------------------------------------------------------------
+	// Annotations become { kind, text, plane, textHeight, textGap, font, normal, lines,
+	// arrows, label }: world-space line segments (flat xyz pairs), arrowheads ({ tip, dir,
+	// type, size }) and one text placement ({ point, dir, align, valign }). Built from the
+	// definition points rhino3dm exposes; rhino3dm has no font metrics, so text extents and
+	// the text gap in dimension lines are laid out on the main thread.
+
+	function toXYZ( p ) {
+
+		if ( ! p ) return null;
+		if ( p.X !== undefined ) return [ p.X, p.Y, p.Z ];
+		if ( p.length === 3 || p.length === 2 ) return [ p[ 0 ], p[ 1 ], p[ 2 ] || 0 ];
+		return null;
+
+	}
+
+	function vAdd( a, b ) {
+
+		return [ a[ 0 ] + b[ 0 ], a[ 1 ] + b[ 1 ], a[ 2 ] + b[ 2 ] ];
+
+	}
+
+	function vSub( a, b ) {
+
+		return [ a[ 0 ] - b[ 0 ], a[ 1 ] - b[ 1 ], a[ 2 ] - b[ 2 ] ];
+
+	}
+
+	function vScale( a, s ) {
+
+		return [ a[ 0 ] * s, a[ 1 ] * s, a[ 2 ] * s ];
+
+	}
+
+	function vDot( a, b ) {
+
+		return a[ 0 ] * b[ 0 ] + a[ 1 ] * b[ 1 ] + a[ 2 ] * b[ 2 ];
+
+	}
+
+	function vLength( a ) {
+
+		return Math.hypot( a[ 0 ], a[ 1 ], a[ 2 ] );
+
+	}
+
+	function vNormalize( a ) {
+
+		const length = a ? vLength( a ) : 0;
+		return length > 0 ? vScale( a, 1 / length ) : null;
+
+	}
+
+	function vCross( a, b ) {
+
+		return [ a[ 1 ] * b[ 2 ] - a[ 2 ] * b[ 1 ], a[ 2 ] * b[ 0 ] - a[ 0 ] * b[ 2 ], a[ 0 ] * b[ 1 ] - a[ 1 ] * b[ 0 ] ];
+
+	}
+
+	function enumName( value, prefix ) {
+
+		const name = value && value.constructor ? value.constructor.name : '';
+		return name.startsWith( prefix ) ? name.substring( prefix.length ) : name;
+
+	}
+
+	function tryGet( fn ) {
+
+		try {
+
+			return fn();
+
+		} catch ( e ) {
+
+			return undefined;
+
+		}
+
+	}
+
+	function dimstyleFor( doc, id ) {
+
+		if ( ! dimstyleCache ) return null;
+		if ( dimstyleCache.has( id ) ) return dimstyleCache.get( id );
+
+		const table = doc.dimstyles();
+		let style = tryGet( () => table.findId( id ) ) || null;
+		// An annotation with per-object overrides may name a style that is not in the table.
+		if ( ! style && table.count > 0 ) style = tryGet( () => table.get( 0 ) ) || null;
+		// The table is not freed here: its `delete( id )` shadows the handle destructor.
+
+		dimstyleCache.set( id, style );
+		return style;
+
+	}
+
+	// Bold / italic and the font a Rhino rich-text string asks for. getFont() reports the
+	// annotation's base font only, while the runs carry \b, \i and \fN.
+	function rtfStyle( rtf ) {
+
+		const result = { bold: false, italic: false, family: null };
+		if ( ! rtf || rtf.indexOf( '{\\rtf' ) !== 0 ) return result;
+		const fonts = {};
+		const table = /\{\\fonttbl((?:\{[^{}]*\})*)\}/.exec( rtf );
+		if ( table ) {
 
-				const theta = ( tan.x * prevTan.x + tan.y * prevTan.y + tan.z * prevTan.z ) / denominator;
-				angle = Math.acos( Math.max( - 1, Math.min( 1, theta ) ) );
+			for ( const m of table[ 1 ].matchAll( /\{\\f(\d+)[^ ;{}]*\s*([^;{}]+);?\}/g ) ) fonts[ m[ 1 ] ] = m[ 2 ].trim();
+
+		}
+
+		const body = table ? rtf.replace( table[ 0 ], '' ) : rtf;
+		result.bold = /\\b(?![a-z0-9])/.test( body );
+		result.italic = /\\i(?![a-z0-9])/.test( body );
+		// The last font switch before the first text run wins.
+		const used = [ ...body.matchAll( /\\f(\d+)(?![a-z0-9])/g ) ].map( ( m ) => m[ 1 ] );
+		if ( used.length ) result.family = fonts[ used[ used.length - 1 ] ] || null;
+		return result;
+
+	}
+
+	function fontOf( g, parentStyle, style ) {
+
+		const out = { family: 'Arial', bold: false, italic: false };
+		const f = tryGet( () => ( parentStyle && typeof g.getFont === 'function' ? g.getFont( parentStyle ) : style && style.getFont() ) );
+		if ( f ) {
+
+			if ( f.familyName ) out.family = f.familyName;
+			out.bold = Boolean( tryGet( () => f.bold ) );
+			out.italic = Boolean( tryGet( () => f.italic ) );
+			if ( typeof f.delete === 'function' ) f.delete();
+
+		}
+
+		const rtf = rtfStyle( tryGet( () => g.richText ) );
+		if ( rtf.family ) out.family = rtf.family;
+		out.bold = out.bold || rtf.bold;
+		out.italic = out.italic || rtf.italic;
+		return out;
+
+	}
+
+	// Text justification. rhino3dm exposes none, but a style's own record (encode()) ends
+	// with a fixed block whose int32 fields at 98, 94, 90 and 86 bytes from the end read
+	// 1, vertical alignment, horizontal alignment, 1 - the same in Rhino 7 and 8 files.
+	// Anything else falls back to Rhino's default, top left.
+	const TEXT_VALIGN = [ 'top', 'middleOfTop', 'bottomOfTop', 'middle', 'middleOfBottom', 'bottom', 'bottomOfBox' ];
+	const TEXT_HALIGN = [ 'left', 'center', 'right', 'left' ];
+
+	function textAlignment( style ) {
+
+		const fallback = { h: 'left', v: 'top' };
+		const encoded = style ? tryGet( () => style.encode() ) : null;
+		if ( ! encoded || ! encoded.data ) return fallback;
+		const bytes = base64ToBytes( encoded.data );
+		const n = bytes.length;
+		if ( n < 110 ) return fallback;
+		const view = new DataView( bytes.buffer, bytes.byteOffset, n );
+		const at = ( k ) => view.getInt32( n - k, true );
+		const v = at( 94 );
+		const h = at( 90 );
+		if ( at( 98 ) !== 1 || at( 86 ) !== 1 || ! ( v >= 0 && v < TEXT_VALIGN.length ) || ! ( h >= 0 && h < TEXT_HALIGN.length ) ) return fallback;
+		return { h: TEXT_HALIGN[ h ], v: TEXT_VALIGN[ v ] };
+
+	}
+
+	function formatMeasurement( value, style, prefix ) {
+
+		const factor = style && style.lengthFactor > 0 ? style.lengthFactor : 1;
+		return prefix + ( value * factor ).toFixed( 1 );
+
+	}
+
+	function extractAnnotation( g, doc ) {
+
+		const kind = enumName( g.annotationType, 'AnnotationTypes_' ) || 'Unset';
+		const parentStyle = dimstyleFor( doc, g.dimensionStyleId );
+		// rhino3dm >= 8.35 gives the object's effective style (its property overrides
+		// applied), its text height and the model-space scale Rhino multiplies every
+		// annotation length by; older builds fall back to the parent style.
+		const ownStyle = parentStyle && typeof g.getDimensionStyle === 'function' ? tryGet( () => g.getDimensionStyle( parentStyle ) ) : null;
+
+		try {
+
+			const style = ownStyle || parentStyle;
+			let scale = parentStyle && typeof g.getDimensionScale === 'function' ? tryGet( () => g.getDimensionScale( parentStyle ) ) : undefined;
+			if ( ! ( scale > 0 ) ) scale = style && style.dimensionScale > 0 ? style.dimensionScale : 1;
+			let baseHeight = parentStyle && typeof g.getTextHeight === 'function' ? tryGet( () => g.getTextHeight( parentStyle ) ) : undefined;
+			if ( ! ( baseHeight > 0 ) ) baseHeight = style && style.textHeight > 0 ? style.textHeight : 1;
+			const textHeight = baseHeight * scale;
+			// A style length in model units: scaled, or `fallback` when the style has none.
+			const len = ( value, fallback ) => ( Number.isFinite( value ) && value >= 0 ? value * scale : fallback );
+
+			const plane = g.plane;
+			const origin = toXYZ( plane.origin ) || [ 0, 0, 0 ];
+			const xAxis = vNormalize( toXYZ( plane.xAxis ) ) || [ 1, 0, 0 ];
+			const yAxis = vNormalize( toXYZ( plane.yAxis ) ) || [ 0, 1, 0 ];
+			const font = fontOf( g, parentStyle, style );
+
+			const out = {
+				kind,
+				text: tryGet( () => g.plainTextWithFields ) || tryGet( () => g.plainText ) || '',
+				plane: { origin, xAxis, yAxis },
+				normal: vNormalize( vCross( xAxis, yAxis ) ) || [ 0, 0, 1 ],
+				textHeight,
+				textGap: len( style && style.textGap, textHeight / 4 ),
+				font: font.family,
+				bold: font.bold,
+				italic: font.italic,
+				// Rhino's "draw forward": text turns to read left to right from the view.
+				drawForward: ! ( style && style.drawForward === false ),
+				lines: [],
+				arrows: [],
+				label: null
+			};
+
+			// Text Rhino has not formatted yet (a file written before the annotation was
+			// ever drawn) is measured here; "<>" stands for the measurement.
+			const withMeasurement = ( value, prefix ) => {
+
+				const measured = formatMeasurement( value, style, prefix );
+				if ( ! out.text ) out.text = measured;
+				else if ( out.text.indexOf( '<>' ) >= 0 ) out.text = out.text.split( '<>' ).join( measured );
+
+			};
+
+			const line = ( a, b ) => {
+
+				if ( a && b ) out.lines.push( a[ 0 ], a[ 1 ], a[ 2 ], b[ 0 ], b[ 1 ], b[ 2 ] );
+
+			};
+
+			const arrow = ( tip, from, type, size ) => {
+
+				const dir = tip && from ? vNormalize( vSub( tip, from ) ) : null;
+				if ( dir && type !== 'None' ) out.arrows.push( { tip, dir, type: type || 'SolidTriangle', size: size > 0 ? size : textHeight } );
+
+			};
+
+			const pts = tryGet( () => g.points );
+
+			switch ( kind ) {
+
+				case 'Aligned':
+				case 'Rotated': {
+
+					const d1 = toXYZ( pts && pts.defpt1 );
+					const d2 = toXYZ( pts && pts.defpt2 );
+					let a1 = toXYZ( pts && pts.arrowpt1 );
+					let a2 = toXYZ( pts && pts.arrowpt2 );
+					const dimline = toXYZ( pts && pts.dimline );
+					let textPoint = toXYZ( pts && pts.textpt );
+					if ( ! a1 || ! a2 ) break;
+					// Arrow points that coincide although the definition points do not (an
+					// aligned dimension whose cached layout is stale): rebuild them from the
+					// definition points and the dimension line point.
+					if ( d1 && d2 && dimline && vLength( vSub( a2, a1 ) ) < 1e-9 && vLength( vSub( d2, d1 ) ) > 1e-9 ) {
+
+						const along = vNormalize( vSub( d2, d1 ) );
+						const rel = vSub( dimline, d1 );
+						const off = vSub( rel, vScale( along, vDot( rel, along ) ) );
+						a1 = vAdd( d1, off );
+						a2 = vAdd( d2, off );
+						textPoint = vScale( vAdd( a1, a2 ), 0.5 );
+
+					}
+
+					const offset = len( style && style.extensionLineOffset, 0 );
+					const extension = len( style && style.extensionLineExtension, 0 );
+					const extensionLine = ( from, to, suppressed ) => {
+
+						const v = from ? vSub( to, from ) : null;
+						const length = v ? vLength( v ) : 0;
+						if ( suppressed || length < 1e-9 ) return;
+						const u = vScale( v, 1 / length );
+						line( vAdd( from, vScale( u, Math.min( offset, length ) ) ), vAdd( to, vScale( u, extension ) ) );
+
+					};
+
+					extensionLine( d1, a1, style && style.suppressExtension1 );
+					extensionLine( d2, a2, style && style.suppressExtension2 );
+
+					const axis = vNormalize( vSub( a2, a1 ) );
+					if ( axis ) {
+
+						// The dimension line runs between the arrows and on to the text when the
+						// text sits outside them.
+						let t0 = 0;
+						let t1 = vLength( vSub( a2, a1 ) );
+						for ( const p of [ dimline, textPoint ] ) {
+
+							if ( ! p ) continue;
+							const t = vDot( vSub( p, a1 ), axis );
+							t0 = Math.min( t0, t );
+							t1 = Math.max( t1, t );
+
+						}
+
+						out.dimensionLine = [ ...vAdd( a1, vScale( axis, t0 ) ), ...vAdd( a1, vScale( axis, t1 ) ) ];
+						const arrowSize = len( style && style.arrowLength, textHeight );
+						if ( ! ( style && style.suppressArrow1 ) ) arrow( a1, a2, enumName( style && style.arrowType1, 'ArrowheadTypes_' ), arrowSize );
+						if ( ! ( style && style.suppressArrow2 ) ) arrow( a2, a1, enumName( style && style.arrowType2, 'ArrowheadTypes_' ), arrowSize );
+						if ( d1 && d2 ) withMeasurement( Math.abs( vDot( vSub( d2, d1 ), axis ) ), '' );
+
+					}
+
+					out.label = { point: textPoint || vScale( vAdd( a1, a2 ), 0.5 ), dir: axis || xAxis, align: 'center', valign: 'above' };
+					break;
+
+				}
+
+				case 'Radius':
+				case 'Diameter': {
+
+					const center = toXYZ( pts && pts.centerpt );
+					const radius = toXYZ( pts && pts.radiuspt );
+					const dimline = toXYZ( pts && pts.dimlinept );
+					const knee = toXYZ( pts && pts.kneept ) || dimline;
+					if ( ! radius || ! dimline ) break;
+
+					line( radius, knee );
+					if ( vLength( vSub( dimline, knee ) ) > 1e-9 ) line( knee, dimline );
+					arrow( radius, knee, enumName( style && style.arrowType1, 'ArrowheadTypes_' ), len( style && style.arrowLength, textHeight ) );
+
+					const mark = len( style && style.centermarkSize, 0 );
+					if ( center && mark > 0 ) {
+
+						line( vAdd( center, vScale( xAxis, - mark ) ), vAdd( center, vScale( xAxis, mark ) ) );
+						line( vAdd( center, vScale( yAxis, - mark ) ), vAdd( center, vScale( yAxis, mark ) ) );
+
+					}
+
+					if ( center ) {
+
+						const r = vLength( vSub( radius, center ) );
+						withMeasurement( kind === 'Diameter' ? 2 * r : r, kind === 'Diameter' ? 'Ø' : 'R' );
+
+					}
+
+					const toText = vNormalize( vSub( dimline, knee ) ) || vNormalize( vSub( dimline, radius ) ) || xAxis;
+					out.label = { point: dimline, dir: xAxis, align: vDot( toText, xAxis ) >= 0 ? 'left' : 'right', valign: 'middle', gap: true };
+					break;
+
+				}
+
+				case 'Leader': {
+
+					const points = [];
+					if ( pts && typeof pts.length === 'number' ) {
+
+						for ( let i = 0; i < pts.length; i ++ ) {
+
+							const p = toXYZ( pts[ i ] );
+							if ( p ) points.push( p );
+
+						}
+
+					}
+
+					if ( points.length === 0 ) break;
+					for ( let i = 0; i + 1 < points.length; i ++ ) line( points[ i ], points[ i + 1 ] );
+					if ( points.length >= 2 ) {
+
+						arrow( points[ 0 ], points[ 1 ], enumName( style && style.leaderArrowType, 'ArrowheadTypes_' ), len( style && style.leaderArrowLength, textHeight ) );
+
+					}
+
+					const last = points[ points.length - 1 ];
+					const lastX = vDot( vSub( last, origin ), xAxis );
+					const textPoint2d = parentStyle ? tryGet( () => g.getTextPoint2d( parentStyle, scale ) ) : undefined;
+					let point = last;
+					let align = points.length >= 2 && vDot( vSub( last, points[ points.length - 2 ] ), xAxis ) < 0 ? 'right' : 'left';
+					let gap = true;
+
+					if ( textPoint2d && textPoint2d.length >= 2 && isFinite( textPoint2d[ 0 ] ) ) {
+
+						// Rhino's own text point already includes the landing and the text gap.
+						point = vAdd( origin, vAdd( vScale( xAxis, textPoint2d[ 0 ] ), vScale( yAxis, textPoint2d[ 1 ] ) ) );
+						align = textPoint2d[ 0 ] >= lastX ? 'left' : 'right';
+						gap = false;
+						const landing = len( style && style.leaderLandingLength, 0 );
+						if ( style && style.leaderHasLanding && landing > 0 ) {
+
+							const sign = align === 'left' ? 1 : - 1;
+							line( last, vAdd( last, vScale( xAxis, sign * landing ) ) );
+
+						}
+
+					}
+
+					out.label = { point, dir: xAxis, align, valign: 'middle', gap };
+					break;
+
+				}
+
+				case 'Text': {
+
+					const rotation = tryGet( () => g.textRotationRadians ) || 0;
+					const dir = rotation ? vAdd( vScale( xAxis, Math.cos( rotation ) ), vScale( yAxis, Math.sin( rotation ) ) ) : xAxis;
+					const justify = textAlignment( style );
+					out.label = { point: origin, dir, align: justify.h, valign: justify.v };
+					break;
+
+				}
+
+				default: {
+
+					// Angular, ordinate and centre marks: Rhino's own display lines, when rhino3dm
+					// can compute them for this type.
+					if ( parentStyle && typeof g.getDisplayLines === 'function' ) {
+
+						const result = tryGet( () => g.getDisplayLines( parentStyle, scale ) );
+						if ( result && result.lines ) {
+
+							for ( let i = 0; i < result.lines.size(); i ++ ) {
+
+								const l = result.lines.get( i );
+								line( toXYZ( l.from ), toXYZ( l.to ) );
+								if ( typeof l.delete === 'function' ) l.delete();
+
+							}
+
+							result.lines.delete();
+							if ( result.text_rect ) result.text_rect.delete();
+
+						}
+
+					}
+
+					let point = toXYZ( pts && ( pts.textpt || pts.textPoint || pts.dimlinept ) );
+					if ( ! point ) {
+
+						const box = tryGet( () => g.getTightBoundingBox() );
+						if ( box && box.min[ 0 ] <= box.max[ 0 ] ) point = vScale( vAdd( box.min, box.max ), 0.5 );
+						if ( box && typeof box.delete === 'function' ) box.delete();
+
+					}
+
+					out.label = { point: point || origin, dir: xAxis, align: 'center', valign: 'middle' };
+					break;
+
+				}
 
 			}
 
-			if ( angle < 0.1 ) continue;
+			if ( ! out.text ) out.label = null;
+			return out;
+
+		} finally {
+
+			if ( ownStyle && typeof ownStyle.delete === 'function' ) ownStyle.delete();
+
+		}
+
+	}
+
+	// Hatches: rhino3dm exposes neither the loops nor the pattern, but the hatch's own
+	// opennurbs record does. Each loop is written as a version byte (0x11), an int loop type
+	// (0 outer, 1 inner) and the 2D boundary curve as an embedded class record, which
+	// CommonObject.decode() can read on its own.
+	const TCODE_OPENNURBS_CLASS = 0x00027FFA;
+
+	function base64ToBytes( base64 ) {
+
+		const binary = atob( base64 );
+		const bytes = new Uint8Array( binary.length );
+		for ( let i = 0; i < binary.length; i ++ ) bytes[ i ] = binary.charCodeAt( i );
+		return bytes;
+
+	}
+
+	function bytesToBase64( bytes ) {
+
+		let binary = '';
+		for ( let i = 0; i < bytes.length; i += 0x8000 ) {
 
-			ts.push( t );
+			binary += String.fromCharCode.apply( null, bytes.subarray( i, i + 0x8000 ) );
 
 		}
 
-		rc = ts.map( t => curve.pointAt( t ) );
-		return rc;
+		return btoa( binary );
+
+	}
+
+	function extractHatch( g ) {
+
+		const encoded = tryGet( () => g.encode() );
+		if ( ! encoded || ! encoded.data ) return null;
+
+		const bytes = base64ToBytes( encoded.data );
+		const view = new DataView( bytes.buffer, bytes.byteOffset, bytes.byteLength );
+		const plane = g.plane;
+		const loops = [];
+
+		// Start past the hatch's own class record header.
+		for ( let off = 12; off + 12 <= bytes.length; off ++ ) {
+
+			if ( view.getUint32( off, true ) !== TCODE_OPENNURBS_CLASS ) continue;
+			const length = Number( view.getBigUint64( off + 4, true ) );
+			if ( off + 12 + length > bytes.length ) continue;
+			if ( off < 5 || bytes[ off - 5 ] !== 0x11 ) continue;
+
+			const type = view.getInt32( off - 4, true );
+			const curve = tryGet( () => rhino.CommonObject.decode( {
+				version: encoded.version,
+				archive3dm: encoded.archive3dm,
+				opennurbs: encoded.opennurbs,
+				data: bytesToBase64( bytes.subarray( off, off + 12 + length ) )
+			} ) );
+
+			if ( curve && curve instanceof rhino.Curve ) {
+
+				const points = [];
+				for ( const p of curveToPoints( curve ) ) points.push( p[ 0 ], p[ 1 ] );
+				if ( points.length >= 6 ) loops.push( { outer: type !== 1, points } );
+
+			}
+
+			if ( curve && typeof curve.delete === 'function' ) curve.delete();
+			// Never look inside a record already handled (a polycurve's own segments).
+			off += 11 + length;
+
+		}
+
+		if ( loops.length === 0 ) return null;
+
+		return {
+			plane: {
+				origin: toXYZ( plane.origin ) || [ 0, 0, 0 ],
+				xAxis: vNormalize( toXYZ( plane.xAxis ) ) || [ 1, 0, 0 ],
+				yAxis: vNormalize( toXYZ( plane.yAxis ) ) || [ 0, 1, 0 ]
+			},
+			patternIndex: tryGet( () => g.patternIndex ) || 0,
+			loops
+		};
 
 	}
 
```
