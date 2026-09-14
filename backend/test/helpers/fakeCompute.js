import { rhinoReady } from '../../src/rhino.js';

/** A closed box mesh (6 quads, per-vertex normals) spanning `min`..`max`. */
export function boxMesh(rhino, min, max) {
  const mesh = new rhino.Mesh();
  const vertices = mesh.vertices();
  const corners = [
    [min[0], min[1], min[2]], [max[0], min[1], min[2]], [max[0], max[1], min[2]], [min[0], max[1], min[2]],
    [min[0], min[1], max[2]], [max[0], min[1], max[2]], [max[0], max[1], max[2]], [min[0], max[1], max[2]],
  ];
  for (const p of corners) vertices.add(p[0], p[1], p[2]);
  const faces = mesh.faces();
  for (const q of [[0, 3, 2, 1], [4, 5, 6, 7], [0, 1, 5, 4], [1, 2, 6, 5], [2, 3, 7, 6], [3, 0, 4, 7]]) faces.addQuadFace(...q);
  mesh.normals().computeNormals();
  vertices.delete(); faces.delete();
  return mesh;
}

/**
 * Stands in for Rhino.Compute: answers `Mesh.CreateFromBrep` with the bounding box of each brep,
 * split in two meshes (like Compute's one-mesh-per-face output). Records every call.
 */
export async function createFakeCompute({ reachable = true, respond } = {}) {
  const rhino = await rhinoReady;
  const calls = [];
  return {
    url: 'http://fake-compute.test/',
    calls,
    async meshBreps(brepsJson, mpJson) {
      calls.push({ count: brepsJson.length, mp: mpJson });
      if (respond) return respond(brepsJson, mpJson);
      return brepsJson.map((json) => {
        const brep = rhino.CommonObject.decode(json);
        const box = brep.getBoundingBox();
        const mid = (box.min[2] + box.max[2]) / 2;
        const lower = boxMesh(rhino, box.min, [box.max[0], box.max[1], mid]);
        const upper = boxMesh(rhino, [box.min[0], box.min[1], mid], box.max);
        const result = [lower.encode(), upper.encode()];
        lower.delete(); upper.delete(); brep.delete();
        return result;
      });
    },
    async probe() { return reachable; },
  };
}
