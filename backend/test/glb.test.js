import assert from 'node:assert/strict';
import { test } from 'node:test';
import { GlbWriter, GLB_MAGIC, parseGlb, Z_UP_TO_Y_UP } from '../src/glb.js';
import { computeVertexNormals, mergeTriangles } from '../src/geometry.js';

function triangle() {
  return {
    positions: new Float32Array([0, 0, 0, 1, 0, 0, 0, 1, 0]),
    normals: new Float32Array([0, 0, 1, 0, 0, 1, 0, 0, 1]),
    indices: new Uint32Array([0, 1, 2]),
    material: 0,
  };
}

test('GlbWriter produces a structurally valid binary glTF 2.0 file', () => {
  const writer = new GlbWriter({ assetExtras: { name: 'unit', units: 'Millimeters' } });
  const red = writer.addColorMaterial({ r: 255, g: 0, b: 0, a: 255 });
  const redAgain = writer.addColorMaterial({ r: 255, g: 0, b: 0, a: 255 });
  const glass = writer.addColorMaterial({ r: 0, g: 0, b: 255, a: 128 });
  assert.equal(red, redAgain, 'one material per distinct color');
  assert.equal(glass, 1);

  // 5 vertices: positions 15 floats = 60 bytes (aligned), indices 6 * 4 = 24 bytes.
  const mesh = writer.addMesh({
    name: 'quad',
    positions: new Float32Array([0, 0, 0, 2, 0, 0, 2, 3, 0, 0, 3, 0, 1, 1, -1]),
    normals: new Float32Array(15).fill(0).map((_, i) => (i % 3 === 2 ? 1 : 0)),
    indices: new Uint32Array([0, 1, 2, 0, 2, 3]),
    material: red,
  });
  const child = writer.addNode({ name: 'child', mesh, extras: { id: 'abc', layer: 'L', layerIndex: 0, userStrings: { k: 'v' } } });
  const root = writer.addNode({ name: 'root', matrix: Z_UP_TO_Y_UP, children: [child] });
  const glb = writer.finish([root]);

  assert.equal(glb.readUInt32LE(0), GLB_MAGIC);
  assert.equal(glb.readUInt32LE(4), 2);
  assert.equal(glb.readUInt32LE(8), glb.length);
  assert.equal(glb.length % 4, 0, 'total length is 4-byte aligned');
  const jsonChunkLength = glb.readUInt32LE(12);
  assert.equal(jsonChunkLength % 4, 0);
  assert.equal(glb.readUInt32LE(16), 0x4e4f534a);
  assert.equal(glb.readUInt32LE(20 + jsonChunkLength + 4), 0x004e4942);

  const { json, bin } = parseGlb(glb);
  assert.equal(json.asset.version, '2.0');
  assert.equal(json.asset.generator, 'styro3d-rhino-appserver');
  assert.deepEqual(json.asset.extras, { name: 'unit', units: 'Millimeters' });
  assert.equal(json.scene, 0);
  assert.deepEqual(json.scenes, [{ nodes: [root] }]);
  assert.equal(json.nodes.length, 2);
  assert.deepEqual(json.nodes[root].matrix, Z_UP_TO_Y_UP);
  assert.deepEqual(json.nodes[root].children, [child]);
  assert.equal(json.nodes[child].mesh, mesh);
  assert.equal(json.nodes[child].matrix, undefined, 'identity matrices are omitted');
  assert.deepEqual(json.nodes[child].extras, { id: 'abc', layer: 'L', layerIndex: 0, userStrings: { k: 'v' } });

  const primitive = json.meshes[mesh].primitives[0];
  assert.equal(primitive.mode, 4);
  assert.equal(primitive.material, red);
  const position = json.accessors[primitive.attributes.POSITION];
  assert.equal(position.componentType, 5126);
  assert.equal(position.type, 'VEC3');
  assert.equal(position.count, 5);
  assert.deepEqual(position.min, [0, 0, -1]);
  assert.deepEqual(position.max, [2, 3, 0]);
  const normal = json.accessors[primitive.attributes.NORMAL];
  assert.equal(normal.count, 5);
  assert.equal(normal.type, 'VEC3');
  const index = json.accessors[primitive.indices];
  assert.equal(index.componentType, 5125);
  assert.equal(index.type, 'SCALAR');
  assert.equal(index.count, 6);

  assert.equal(json.buffers.length, 1);
  assert.equal(json.buffers[0].byteLength, bin.length);
  for (const view of json.bufferViews) {
    assert.equal(view.buffer, 0);
    assert.equal(view.byteOffset % 4, 0, 'bufferViews are 4-byte aligned');
    assert.ok(view.byteOffset + view.byteLength <= bin.length);
    assert.ok([34962, 34963].includes(view.target));
  }
  assert.equal(json.bufferViews[json.accessors[primitive.indices].bufferView].target, 34963);

  const positionView = json.bufferViews[position.bufferView];
  const positions = new Float32Array(bin.buffer.slice(bin.byteOffset + positionView.byteOffset, bin.byteOffset + positionView.byteOffset + positionView.byteLength));
  assert.deepEqual(Array.from(positions.subarray(0, 6)), [0, 0, 0, 2, 0, 0]);
  const indexView = json.bufferViews[index.bufferView];
  const indices = new Uint32Array(bin.buffer.slice(bin.byteOffset + indexView.byteOffset, bin.byteOffset + indexView.byteOffset + indexView.byteLength));
  assert.deepEqual(Array.from(indices), [0, 1, 2, 0, 2, 3]);

  assert.equal(json.materials[red].name, '#FF0000');
  assert.deepEqual(json.materials[red].pbrMetallicRoughness.baseColorFactor, [1, 0, 0, 1]);
  assert.equal(json.materials[red].doubleSided, true);
  assert.equal(json.materials[red].alphaMode, undefined);
  assert.equal(json.materials[glass].alphaMode, 'BLEND');
  assert.equal(json.materials[glass].pbrMetallicRoughness.baseColorFactor[3], 128 / 255);
});

test('GlbWriter rejects malformed meshes', () => {
  const writer = new GlbWriter();
  assert.throws(() => writer.addMesh({ ...triangle(), normals: new Float32Array(6) }), /matching VEC3/);
  assert.throws(() => writer.addMesh({ ...triangle(), indices: new Uint32Array([0, 1]) }), /triangles/);
});

test('an empty scene still serialises without buffers', () => {
  const writer = new GlbWriter();
  const root = writer.addNode({ name: 'root', matrix: Z_UP_TO_Y_UP });
  const { json, bin } = parseGlb(writer.finish([root]));
  assert.equal(bin, null);
  assert.equal(json.buffers, undefined);
  assert.equal(json.meshes, undefined);
  assert.equal(json.nodes.length, 1);
});

test('Z-up to Y-up matrix maps +Z to +Y and +Y to -Z', () => {
  const m = Z_UP_TO_Y_UP;
  const apply = ([x, y, z]) => [
    m[0] * x + m[4] * y + m[8] * z,
    m[1] * x + m[5] * y + m[9] * z,
    m[2] * x + m[6] * y + m[10] * z,
  ];
  assert.deepEqual(apply([0, 0, 1]), [0, 1, 0]);
  assert.deepEqual(apply([0, 1, 0]), [0, 0, -1]);
  assert.deepEqual(apply([1, 0, 0]), [1, 0, 0]);
});

test('computeVertexNormals produces unit normals facing the triangle winding', () => {
  const t = triangle();
  const normals = computeVertexNormals(t.positions, t.indices);
  assert.deepEqual(Array.from(normals), [0, 0, 1, 0, 0, 1, 0, 0, 1]);
});

test('mergeTriangles offsets indices and sums triangle counts', () => {
  const a = { ...triangle(), triangleCount: 1 };
  const b = { ...triangle(), triangleCount: 1 };
  const merged = mergeTriangles([a, null, b]);
  assert.equal(merged.positions.length, 18);
  assert.deepEqual(Array.from(merged.indices), [0, 1, 2, 3, 4, 5]);
  assert.equal(merged.triangleCount, 2);
  assert.equal(mergeTriangles([null]), null);
  assert.equal(mergeTriangles([a]), a);
});
