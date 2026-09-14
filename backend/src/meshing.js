import { HttpError } from './errors.js';
import { brepFaceMeshes, decodeMeshes, extrusionMesh, subdMesh } from './geometry.js';
import { meshingParameters, release } from './rhino.js';

/**
 * Sends encoded Breps to Compute in batches and yields `[index, meshJsonList]` per brep.
 * A non-array answer is treated as a Compute error (protocol violation) rather than a skip.
 */
export async function* meshBrepsBatched(compute, brepsJson, mpJson, batchSize, timing) {
  for (let start = 0; start < brepsJson.length; start += batchSize) {
    const batch = brepsJson.slice(start, start + batchSize);
    const t0 = performance.now();
    const results = await compute.meshBreps(batch, mpJson);
    timing.computeMs += performance.now() - t0;
    if (!Array.isArray(results) || results.length !== batch.length) {
      throw new HttpError(502, 'compute_error', `Compute returned ${Array.isArray(results) ? results.length : typeof results} results for ${batch.length} breps`);
    }
    for (let i = 0; i < results.length; i++) yield [start + i, results[i]];
  }
}

/**
 * Replaces every Brep / Extrusion without a cached render mesh (via Compute) and every SubD
 * (locally, subdivided control net) in `doc` with a Mesh object carrying the original attributes.
 * @returns {Promise<{ meshedCount: number, skippedCount: number, computeMs: number }>}
 */
export async function meshFile(rhino, doc, { compute, quality, batchSize, logger }) {
  const objects = doc.objects();
  const handles = [];
  const computeTargets = [];
  const replacements = [];
  let skippedCount = 0;

  const count = objects.count;
  for (let i = 0; i < count; i++) {
    const object = objects.get(i);
    const geometry = object.geometry();
    const attributes = object.attributes();
    handles.push(object, geometry, attributes);
    const type = geometry.objectType;

    if (type === rhino.ObjectType.Brep) {
      const meshes = brepFaceMeshes(rhino, geometry);
      const hasMesh = meshes.length > 0;
      release(...meshes);
      if (!hasMesh) computeTargets.push({ attributes, brepJson: geometry.encode() });
    } else if (type === rhino.ObjectType.Extrusion) {
      const cached = extrusionMesh(rhino, geometry);
      if (cached) { release(cached); continue; }
      const brep = geometry.toBrep(true);
      if (brep) {
        computeTargets.push({ attributes, brepJson: brep.encode() });
        release(brep);
      } else {
        skippedCount++;
        logger.warn({ msg: 'extrusion could not be converted to a Brep', id: attributes.id });
      }
    } else if (type === rhino.ObjectType.SubD) {
      const mesh = subdMesh(rhino, geometry);
      if (mesh) replacements.push({ attributes, mesh }); else skippedCount++;
    }
  }

  const timing = { computeMs: 0 };
  try {
    if (computeTargets.length > 0) {
      if (!compute) {
        throw new HttpError(502, 'compute_unreachable', `${computeTargets.length} object(s) need tessellation but COMPUTE_URL is not configured`);
      }
      const mp = meshingParameters(rhino, quality);
      const mpJson = mp.encode();
      release(mp);
      const brepsJson = computeTargets.map((t) => t.brepJson);
      for await (const [index, meshJsonList] of meshBrepsBatched(compute, brepsJson, mpJson, batchSize, timing)) {
        const mesh = decodeMeshes(rhino, meshJsonList);
        if (mesh) replacements.push({ attributes: computeTargets[index].attributes, mesh });
        else { skippedCount++; logger.warn({ msg: 'Compute produced no mesh', id: computeTargets[index].attributes.id }); }
      }
    }

    for (const { attributes, mesh } of replacements) {
      objects.delete(attributes.id);
      objects.addMesh(mesh, attributes);
    }
    return { meshedCount: replacements.length, skippedCount, computeMs: Math.round(timing.computeMs) };
  } finally {
    release(...replacements.map((r) => r.mesh), ...handles);
  }
}
