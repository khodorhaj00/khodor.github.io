import { release } from './rhino.js';

/**
 * Triangulated, GLB-ready copy of a rhino3dm Mesh: quads are split along (0,1,2)/(0,2,3),
 * degenerate faces dropped, vertex normals taken from the mesh when it has one per vertex
 * and otherwise area-weighted from the triangles.
 * @returns {{ positions: Float32Array, normals: Float32Array, indices: Uint32Array, triangleCount: number } | null}
 */
export function meshToTriangles(mesh) {
  const vertexList = mesh.vertices();
  const faceList = mesh.faces();
  const normalList = mesh.normals();
  try {
    const vertexCount = vertexList.count;
    const faceCount = faceList.count;
    if (vertexCount === 0 || faceCount === 0) return null;

    const points = vertexList.toPoint3fArray();
    const positions = new Float32Array(vertexCount * 3);
    for (let i = 0; i < vertexCount; i++) {
      const p = points[i];
      positions[i * 3] = p[0]; positions[i * 3 + 1] = p[1]; positions[i * 3 + 2] = p[2];
    }

    const indices = new Uint32Array(faceCount * 6);
    let n = 0;
    const inRange = (v) => v >= 0 && v < vertexCount;
    for (let f = 0; f < faceCount; f++) {
      const [a, b, c, d] = faceList.get(f);
      if (!inRange(a) || !inRange(b) || !inRange(c) || !inRange(d)) continue;
      if (a !== b && b !== c && a !== c) { indices[n++] = a; indices[n++] = b; indices[n++] = c; }
      if (d !== c && a !== c && c !== d && a !== d) { indices[n++] = a; indices[n++] = c; indices[n++] = d; }
    }
    if (n === 0) return null;
    const trimmed = indices.subarray(0, n).slice();

    const normals = normalList.count === vertexCount
      ? readNormals(normalList, vertexCount)
      : computeVertexNormals(positions, trimmed);

    return { positions, normals, indices: trimmed, triangleCount: n / 3 };
  } finally {
    release(vertexList, faceList, normalList);
  }
}

function readNormals(normalList, vertexCount) {
  const normals = new Float32Array(vertexCount * 3);
  for (let i = 0; i < vertexCount; i++) {
    const v = normalList.get(i);
    normals[i * 3] = v[0]; normals[i * 3 + 1] = v[1]; normals[i * 3 + 2] = v[2];
  }
  return normals;
}

export function computeVertexNormals(positions, indices) {
  const normals = new Float32Array(positions.length);
  for (let t = 0; t < indices.length; t += 3) {
    const ia = indices[t] * 3, ib = indices[t + 1] * 3, ic = indices[t + 2] * 3;
    const abx = positions[ib] - positions[ia], aby = positions[ib + 1] - positions[ia + 1], abz = positions[ib + 2] - positions[ia + 2];
    const acx = positions[ic] - positions[ia], acy = positions[ic + 1] - positions[ia + 1], acz = positions[ic + 2] - positions[ia + 2];
    // Cross product magnitude is twice the triangle area, which weights the accumulation.
    const nx = aby * acz - abz * acy, ny = abz * acx - abx * acz, nz = abx * acy - aby * acx;
    for (const i of [ia, ib, ic]) { normals[i] += nx; normals[i + 1] += ny; normals[i + 2] += nz; }
  }
  for (let i = 0; i < normals.length; i += 3) {
    const len = Math.hypot(normals[i], normals[i + 1], normals[i + 2]);
    if (len > 0) { normals[i] /= len; normals[i + 1] /= len; normals[i + 2] /= len; } else { normals[i + 2] = 1; }
  }
  return normals;
}

/** Concatenates triangle sets, offsetting indices. Returns null when nothing renderable is left. */
export function mergeTriangles(parts) {
  const list = parts.filter(Boolean);
  if (list.length === 0) return null;
  if (list.length === 1) return list[0];
  let vertexTotal = 0, indexTotal = 0;
  for (const p of list) { vertexTotal += p.positions.length; indexTotal += p.indices.length; }
  const positions = new Float32Array(vertexTotal);
  const normals = new Float32Array(vertexTotal);
  const indices = new Uint32Array(indexTotal);
  let vOffset = 0, iOffset = 0;
  for (const p of list) {
    positions.set(p.positions, vOffset);
    normals.set(p.normals, vOffset);
    const base = vOffset / 3;
    for (let i = 0; i < p.indices.length; i++) indices[iOffset + i] = p.indices[i] + base;
    vOffset += p.positions.length;
    iOffset += p.indices.length;
  }
  return { positions, normals, indices, triangleCount: indexTotal / 3 };
}

/** The cached render meshes of a Brep's faces (caller releases). Empty when the file was saved without them. */
export function brepFaceMeshes(rhino, brep) {
  const faces = brep.faces();
  const meshes = [];
  try {
    const count = faces.count;
    for (let i = 0; i < count; i++) {
      const face = faces.get(i);
      const mesh = face.getMesh(rhino.MeshType.Any);
      release(face);
      if (!mesh) continue;
      const faceList = mesh.faces();
      const hasFaces = faceList.count > 0;
      release(faceList);
      if (hasFaces) meshes.push(mesh); else release(mesh);
    }
    return meshes;
  } finally {
    release(faces);
  }
}

/** Extrusion's cached render mesh, or null. */
export function extrusionMesh(rhino, extrusion) {
  const mesh = extrusion.getMesh(rhino.MeshType.Any);
  if (!mesh) return null;
  const faceList = mesh.faces();
  const hasFaces = faceList.count > 0;
  release(faceList);
  if (hasFaces) return mesh;
  release(mesh);
  return null;
}

const SUBD_LEVEL = 2;

/** Meshes a SubD locally by subdividing its control net (mutates the SubD). */
export function subdMesh(rhino, subd) {
  subd.subdivide(SUBD_LEVEL);
  const mesh = rhino.Mesh.createFromSubDControlNet(subd, false);
  if (!mesh) return null;
  const faceList = mesh.faces();
  const hasFaces = faceList.count > 0;
  release(faceList);
  if (hasFaces) return mesh;
  release(mesh);
  return null;
}

/** Combines Compute's per-face mesh JSON into one rhino3dm Mesh (caller releases), or null. */
export function decodeMeshes(rhino, meshJsonList) {
  if (!Array.isArray(meshJsonList) || meshJsonList.length === 0) return null;
  const combined = new rhino.Mesh();
  let appended = 0;
  for (const json of meshJsonList) {
    if (!json) continue;
    const part = rhino.CommonObject.decode(json);
    if (part && part.objectType === rhino.ObjectType.Mesh) {
      const faceList = part.faces();
      if (faceList.count > 0) { combined.append(part); appended++; }
      release(faceList);
    }
    release(part);
  }
  if (appended === 0) { release(combined); return null; }
  combined.compact();
  const vertices = combined.vertices();
  const normals = combined.normals();
  if (normals.count !== vertices.count) normals.computeNormals();
  release(vertices, normals);
  return combined;
}
