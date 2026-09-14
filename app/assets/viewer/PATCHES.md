# Patches to vendored code

Everything under `vendor/` is upstream code (three.js r186, rhino3dm 8.32.2) and must stay
byte-identical to upstream **except** the single patch documented here. When upgrading
three.js, re-apply this patch to `vendor/three/addons/loaders/3DMLoader.js`.

## 1. `3DMLoader.js` — report Breps / Extrusions that carry no render mesh

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

### Diff (`diff -u` against upstream r186)

```diff
--- a/app/assets/viewer/vendor/three/addons/loaders/3DMLoader.js
+++ b/app/assets/viewer/vendor/three/addons/loaders/3DMLoader.js
@@ -1634,11 +1634,20 @@
 
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
 
@@ -1655,6 +1664,12 @@
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
@@ -1781,6 +1796,22 @@
 
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
