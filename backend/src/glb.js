/**
 * Minimal binary glTF 2.0 writer: one buffer, float32 POSITION (with min/max) + NORMAL
 * accessors, uint32 indices, everything 4-byte aligned. No dependencies.
 */

export const GLB_MAGIC = 0x46546c67; // 'glTF'
const CHUNK_JSON = 0x4e4f534a;
const CHUNK_BIN = 0x004e4942;
const ARRAY_BUFFER = 34962;
const ELEMENT_ARRAY_BUFFER = 34963;
const FLOAT = 5126;
const UNSIGNED_INT = 5125;
const TRIANGLES = 4;

/** Column-major matrix rotating Rhino's Z-up world into glTF's Y-up: (x, y, z) → (x, z, −y). */
export const Z_UP_TO_Y_UP = [1, 0, 0, 0, 0, 0, -1, 0, 0, 1, 0, 0, 0, 0, 0, 1];

const IDENTITY = [1, 0, 0, 0, 0, 1, 0, 0, 0, 0, 1, 0, 0, 0, 0, 1];

const pad4 = (n) => (n + 3) & ~3;

function srgbToLinear(c) {
  const v = c / 255;
  return v <= 0.04045 ? v / 12.92 : ((v + 0.055) / 1.055) ** 2.4;
}

export class GlbWriter {
  constructor({ generator = 'styro3d-rhino-appserver', assetExtras = undefined } = {}) {
    this.asset = { version: '2.0', generator };
    if (assetExtras) this.asset.extras = assetExtras;
    this.chunks = [];
    this.byteLength = 0;
    this.bufferViews = [];
    this.accessors = [];
    this.materials = [];
    this.meshes = [];
    this.nodes = [];
    this.materialByKey = new Map();
  }

  /**
   * One material per distinct RGBA (0–255) color. Returns the material index.
   */
  addColorMaterial({ r, g, b, a = 255 }) {
    const key = `${r},${g},${b},${a}`;
    const existing = this.materialByKey.get(key);
    if (existing !== undefined) return existing;
    const hex = `#${[r, g, b].map((c) => c.toString(16).padStart(2, '0')).join('')}`.toUpperCase();
    const material = {
      name: hex,
      pbrMetallicRoughness: {
        baseColorFactor: [srgbToLinear(r), srgbToLinear(g), srgbToLinear(b), a / 255],
        metallicFactor: 0,
        roughnessFactor: 0.8,
      },
      doubleSided: true,
    };
    if (a < 255) material.alphaMode = 'BLEND';
    const index = this.materials.push(material) - 1;
    this.materialByKey.set(key, index);
    return index;
  }

  /**
   * @param {{ name?: string, positions: Float32Array, normals: Float32Array, indices: Uint32Array, material: number }} mesh
   * @returns {number} mesh index
   */
  addMesh({ name, positions, normals, indices, material }) {
    if (positions.length % 3 !== 0 || normals.length !== positions.length) {
      throw new Error('GlbWriter.addMesh: positions/normals must be matching VEC3 arrays');
    }
    if (indices.length % 3 !== 0) throw new Error('GlbWriter.addMesh: indices must form triangles');
    const vertexCount = positions.length / 3;
    const bounds = { min: [Infinity, Infinity, Infinity], max: [-Infinity, -Infinity, -Infinity] };
    for (let i = 0; i < positions.length; i += 3) {
      for (let k = 0; k < 3; k++) {
        const v = positions[i + k];
        if (v < bounds.min[k]) bounds.min[k] = v;
        if (v > bounds.max[k]) bounds.max[k] = v;
      }
    }
    const positionAccessor = this.#addAccessor(positions, ARRAY_BUFFER, {
      componentType: FLOAT, count: vertexCount, type: 'VEC3', min: bounds.min, max: bounds.max,
    });
    const normalAccessor = this.#addAccessor(normals, ARRAY_BUFFER, { componentType: FLOAT, count: vertexCount, type: 'VEC3' });
    const indexAccessor = this.#addAccessor(indices, ELEMENT_ARRAY_BUFFER, { componentType: UNSIGNED_INT, count: indices.length, type: 'SCALAR' });
    const mesh = {
      primitives: [{ attributes: { POSITION: positionAccessor, NORMAL: normalAccessor }, indices: indexAccessor, material, mode: TRIANGLES }],
    };
    if (name) mesh.name = name;
    return this.meshes.push(mesh) - 1;
  }

  /**
   * @param {{ name?: string, mesh?: number, matrix?: number[], children?: number[], extras?: object }} node
   * @returns {number} node index
   */
  addNode({ name, mesh, matrix, children, extras }) {
    const node = {};
    if (name) node.name = name;
    if (mesh !== undefined) node.mesh = mesh;
    if (matrix && !matrix.every((v, i) => v === IDENTITY[i])) node.matrix = matrix;
    if (children && children.length > 0) node.children = children;
    if (extras) node.extras = extras;
    return this.nodes.push(node) - 1;
  }

  /** Serialises the document with `rootNodes` as the single scene. */
  finish(rootNodes) {
    const json = {
      asset: this.asset,
      scene: 0,
      scenes: [{ nodes: rootNodes }],
      nodes: this.nodes,
      meshes: this.meshes,
      materials: this.materials,
      accessors: this.accessors,
      bufferViews: this.bufferViews,
      buffers: [{ byteLength: this.byteLength }],
    };
    for (const key of ['nodes', 'meshes', 'materials', 'accessors', 'bufferViews']) {
      if (json[key].length === 0) delete json[key];
    }
    if (this.byteLength === 0) delete json.buffers;

    const jsonBytes = Buffer.from(JSON.stringify(json), 'utf8');
    const jsonPadded = pad4(jsonBytes.length);
    const binPadded = pad4(this.byteLength);
    const total = 12 + 8 + jsonPadded + (binPadded > 0 ? 8 + binPadded : 0);

    const out = Buffer.alloc(total);
    let offset = 0;
    out.writeUInt32LE(GLB_MAGIC, 0); out.writeUInt32LE(2, 4); out.writeUInt32LE(total, 8);
    offset = 12;
    out.writeUInt32LE(jsonPadded, offset); out.writeUInt32LE(CHUNK_JSON, offset + 4);
    offset += 8;
    jsonBytes.copy(out, offset);
    out.fill(0x20, offset + jsonBytes.length, offset + jsonPadded);
    offset += jsonPadded;
    if (binPadded > 0) {
      out.writeUInt32LE(binPadded, offset); out.writeUInt32LE(CHUNK_BIN, offset + 4);
      offset += 8;
      for (const chunk of this.chunks) {
        chunk.copy(out, offset);
        offset += pad4(chunk.length);
      }
    }
    return out;
  }

  #addAccessor(typedArray, target, accessor) {
    const bytes = Buffer.from(typedArray.buffer, typedArray.byteOffset, typedArray.byteLength);
    const byteOffset = this.byteLength;
    this.chunks.push(bytes);
    this.byteLength += pad4(bytes.length);
    const bufferView = this.bufferViews.push({ buffer: 0, byteOffset, byteLength: bytes.length, target }) - 1;
    return this.accessors.push({ bufferView, byteOffset: 0, ...accessor }) - 1;
  }
}

/** Parses a GLB back into `{ json, bin }` (used by tests and by callers wanting to inspect output). */
export function parseGlb(buffer) {
  if (buffer.length < 12 || buffer.readUInt32LE(0) !== GLB_MAGIC) throw new Error('not a GLB: bad magic');
  const version = buffer.readUInt32LE(4);
  const total = buffer.readUInt32LE(8);
  if (version !== 2 || total !== buffer.length) throw new Error(`not a valid GLB: version ${version}, length ${total}/${buffer.length}`);
  let offset = 12;
  let json = null;
  let bin = null;
  while (offset < total) {
    const length = buffer.readUInt32LE(offset);
    const type = buffer.readUInt32LE(offset + 4);
    const data = buffer.subarray(offset + 8, offset + 8 + length);
    if (type === CHUNK_JSON) json = JSON.parse(data.toString('utf8'));
    else if (type === CHUNK_BIN) bin = data;
    offset += 8 + length;
  }
  if (!json) throw new Error('GLB has no JSON chunk');
  return { json, bin };
}
