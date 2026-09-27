import assert from 'node:assert/strict';
import { readFileSync } from 'node:fs';
import { before, test } from 'node:test';
import { parseGlb, Z_UP_TO_Y_UP } from '../src/glb.js';
import { rhinoReady } from '../src/rhino.js';
import { assembleGlb, collectReachable } from '../src/scene.js';
import { boxMesh, createFakeCompute } from './helpers/fakeCompute.js';
import { fixture, SAMPLES, startServer } from './helpers/client.js';

let rhino;
before(async () => { rhino = await rhinoReady; });

/** Structural checks every GLB the server emits must pass. */
function checkGlb(buffer) {
  const { json, bin } = parseGlb(buffer);
  assert.equal(json.asset.version, '2.0');
  assert.equal(json.asset.generator, 'styro3d-rhino-appserver');
  assert.equal(json.buffers[0].byteLength, bin.length);
  const root = json.nodes[json.scenes[json.scene].nodes[0]];
  assert.deepEqual(root.matrix, Z_UP_TO_Y_UP, 'root node rotates Z-up to Y-up');
  for (const mesh of json.meshes) {
    for (const primitive of mesh.primitives) {
      const position = json.accessors[primitive.attributes.POSITION];
      const normal = json.accessors[primitive.attributes.NORMAL];
      const index = json.accessors[primitive.indices];
      assert.equal(normal.count, position.count, 'one normal per vertex');
      assert.equal(index.count % 3, 0);
      const view = json.bufferViews[index.bufferView];
      const indices = new Uint32Array(bin.buffer.slice(bin.byteOffset + view.byteOffset, bin.byteOffset + view.byteOffset + view.byteLength));
      for (const i of indices) assert.ok(i < position.count, 'indices stay inside the vertex range');
      assert.ok(typeof json.materials[primitive.material].name === 'string');
    }
  }
  return { json, bin, root };
}

const byName = (json, name) => json.nodes.find((n) => n.name === name);

test('POST /convert on meshes.3dm: one node per visible object, materials by color, extras', async () => {
  const server = startServer();
  try {
    const res = await server.post('/convert?name=meshes.3dm', fixture('meshes.3dm'));
    assert.equal(res.status, 200, res.buffer.toString());
    assert.equal(res.headers.get('content-type'), 'model/gltf-binary');
    assert.equal(res.headers.get('content-disposition'), 'attachment; filename="meshes.glb"');
    assert.equal(res.headers.get('x-object-count'), '49', '48 boxes + sphere; the box on the hidden layer is left out');
    assert.equal(res.headers.get('x-triangle-count'), String(48 * 12 + 24 * 12 * 2));
    assert.equal(res.headers.get('x-skipped-count'), '0');

    const { json, root } = checkGlb(res.buffer);
    assert.equal(root.name, 'meshes');
    assert.deepEqual(json.asset.extras, { name: 'meshes', units: 'Millimeters' });
    assert.equal(root.children.length, 49);
    assert.equal(json.nodes.length, 50);
    assert.equal(json.meshes.length, 49);
    assert.equal(json.materials.length, 3, 'PARTS, FOAM and the sphere object color');
    assert.equal(byName(json, 'hidden_box'), undefined);

    const block = byName(json, 'block_0_0');
    assert.deepEqual(block.extras, { id: block.extras.id, layer: 'PARTS', layerIndex: 0, userStrings: { PART_ID: 'P00' } });
    assert.match(block.extras.id, /^[0-9a-f-]{36}$/);
    assert.equal(json.materials[json.meshes[block.mesh].primitives[0].material].name, '#C83C28');
    const foam = byName(json, 'block_0_1');
    assert.equal(json.materials[json.meshes[foam.mesh].primitives[0].material].name, '#F0F0F0');
    const sphere = byName(json, 'sphere_ref');
    assert.equal(json.materials[json.meshes[sphere.mesh].primitives[0].material].name, '#FFC800', 'ColorFromObject wins over the layer color');
    assert.equal(json.accessors[json.meshes[sphere.mesh].primitives[0].indices].count, 24 * 12 * 2 * 3);
  } finally {
    await server.close();
  }
});

test('POST /convert on blocks.3dm expands instance references and shares the definition mesh', async () => {
  const server = startServer();
  try {
    const res = await server.post('/convert', fixture('blocks.3dm'));
    assert.equal(res.status, 200, res.buffer.toString());
    assert.equal(res.headers.get('x-object-count'), '5');
    assert.equal(res.headers.get('x-triangle-count'), '60');
    assert.equal(res.headers.get('x-skipped-count'), '0');
    assert.equal(res.headers.get('content-disposition'), 'attachment; filename="model.glb"');

    const { json, root } = checkGlb(res.buffer);
    assert.equal(json.nodes.length, 11, 'root + 5 references + 5 definition instances');
    assert.equal(json.meshes.length, 1, 'the definition mesh is shared');
    assert.equal(root.children.length, 5);
    const ref1 = byName(json, 'ref_1');
    assert.equal(ref1.children.length, 1);
    assert.equal(ref1.mesh, undefined);
    assert.deepEqual(ref1.matrix.slice(12, 15), [80, 20, 10], 'instance transform is column-major');
    assert.equal(json.nodes[ref1.children[0]].mesh, 0);
    assert.equal(byName(json, 'ref_0').matrix, undefined, 'identity transform omitted');
    assert.equal(json.materials.length, 1);
  } finally {
    await server.close();
  }
});

test('POST /convert skips unmeshed Breps without Compute and meshes them with Compute', async () => {
  const plain = startServer();
  try {
    const res = await plain.post('/convert', fixture('brep_nomesh.3dm'));
    assert.equal(res.status, 200);
    assert.equal(res.headers.get('x-object-count'), '1');
    assert.equal(res.headers.get('x-skipped-count'), '2');
    assert.equal(res.headers.get('x-triangle-count'), '12');
    checkGlb(res.buffer);
  } finally {
    await plain.close();
  }

  const compute = await createFakeCompute();
  const withCompute = startServer({ compute });
  try {
    const res = await withCompute.post('/convert?quality=draft', fixture('brep_nomesh.3dm'));
    assert.equal(res.status, 200);
    assert.equal(res.headers.get('x-object-count'), '3');
    assert.equal(res.headers.get('x-skipped-count'), '0');
    assert.equal(res.headers.get('x-triangle-count'), String(12 + 2 * 24));
    assert.equal(compute.calls.length, 1);
    assert.deepEqual(compute.calls[0].mp, rhino.MeshingParameters.fastRenderMesh().encode());
    const { json } = checkGlb(res.buffer);
    assert.ok(byName(json, 'box_brep'));
    assert.ok(byName(json, 'sphere_brep'));
  } finally {
    await withCompute.close();
  }
});

/** The sample with its `subd` layer switched on, so SubDs are tessellated as well as Breps. */
function rhinoLogoWithSubd() {
  const doc = rhino.File3dm.fromByteArray(new Uint8Array(readFileSync(new URL('Rhino_Logo.3dm', SAMPLES))));
  const subdLayer = doc.layers().get(4);
  assert.equal(subdLayer.name, 'subd');
  subdLayer.visible = true;
  const bytes = Buffer.from(doc.toByteArray());
  doc.delete();
  return bytes;
}

/** WASM linear memory shows up in `external` but not in `arrayBuffers` (Node's own Buffers). */
const wasmBytes = () => { const m = process.memoryUsage(); return m.external - m.arrayBuffers; };

test('POST /convert on Rhino_Logo.3dm meshes Breps from their render meshes and SubDs locally', async () => {
  const bytes = rhinoLogoWithSubd();
  const server = startServer();
  try {
    const res = await server.post('/convert?name=Rhino_Logo.3dm', bytes);
    assert.equal(res.status, 200, res.buffer.toString());
    assert.equal(res.headers.get('x-object-count'), '12', '6 Breps + 6 SubDs; curves, text dots, lights and point clouds are not renderable');
    assert.equal(res.headers.get('x-skipped-count'), '0');
    assert.ok(Number(res.headers.get('x-triangle-count')) > 32044 + 6 * 2 * 288, 'brep render meshes plus subdivided SubDs');
    const { json } = checkGlb(res.buffer);
    assert.equal(json.meshes.length, 12);
    assert.equal(json.nodes.filter((n) => n.extras?.layer === 'subd').length, 6);
    assert.equal(json.nodes.filter((n) => n.extras?.layer === 'brep').length, 6);
  } finally {
    await server.close();
  }
});

test('POST /convert frees the parsed model between requests (WASM memory stays bounded)', async () => {
  const bytes = rhinoLogoWithSubd();
  const server = startServer();
  try {
    const convert = async () => { const res = await server.post('/convert', bytes); assert.equal(res.status, 200); };
    for (let i = 0; i < 3; i++) await convert();
    const before = wasmBytes();
    for (let i = 0; i < 30; i++) await convert();
    const growth = wasmBytes() - before;
    // A leaked model costs ~10 MB per request on this file; the WASM heap never shrinks, so
    // once the high-water mark is reached further requests must not move it.
    assert.ok(growth < 32 * 1024 * 1024, `WASM memory grew ${(growth / 1048576).toFixed(1)} MB over 30 requests`);
  } finally {
    await server.close();
  }
});

test('POST /convert follows nested block definitions with accumulated transforms', async () => {
  const file = new rhino.File3dm();
  const layer = file.layers().addLayer('L', { r: 255, g: 255, b: 255, a: 255 });
  const attributesFor = (name) => { const a = new rhino.ObjectAttributes(); a.name = name; a.layerIndex = layer; return a; };

  const innerIndex = file.instanceDefinitions().add('inner', '', '', '', [0, 0, 0], [boxMesh(rhino, [0, 0, 0], [1, 1, 1])], [attributesFor('inner_box')]);
  const inner = file.instanceDefinitions().get(innerIndex);
  const outerIndex = file.instanceDefinitions().add('outer', '', '', '', [0, 0, 0], [
    boxMesh(rhino, [5, 5, 5], [6, 6, 6]),
    new rhino.InstanceReference(inner.id, rhino.Transform.translationXYZ(0, 0, 100)),
  ], [attributesFor('outer_box'), attributesFor('inner_ref')]);
  const outer = file.instanceDefinitions().get(outerIndex);
  file.objects().addInstanceObject(new rhino.InstanceReference(outer.id, rhino.Transform.translationXYZ(10, 0, 0)), attributesFor('outer_ref'));
  file.objects().addInstanceObject(new rhino.InstanceReference(outer.id, rhino.Transform.translationXYZ(20, 0, 0)), attributesFor('outer_ref_2'));
  const bytes = Buffer.from(file.toByteArray());
  file.delete();

  const server = startServer();
  try {
    const res = await server.post('/convert', bytes);
    assert.equal(res.status, 200, res.buffer.toString());
    assert.equal(res.headers.get('x-object-count'), '2');
    assert.equal(res.headers.get('x-triangle-count'), String(2 * 2 * 12));
    const { json, root } = checkGlb(res.buffer);
    assert.equal(json.meshes.length, 2, 'both definition meshes shared across the two references');
    assert.equal(root.children.length, 2);
    const outerRef = byName(json, 'outer_ref');
    assert.deepEqual(outerRef.matrix.slice(12, 15), [10, 0, 0]);
    assert.equal(outerRef.children.length, 2);
    const innerRef = json.nodes[outerRef.children[1]];
    assert.equal(innerRef.name, 'inner_ref');
    assert.deepEqual(innerRef.matrix.slice(12, 15), [0, 0, 100]);
    assert.equal(json.nodes[innerRef.children[0]].name, 'inner_box');
    assert.equal(json.nodes[innerRef.children[0]].mesh, json.nodes[byName(json, 'outer_ref_2').children[1] && json.nodes[byName(json, 'outer_ref_2').children[1]].children[0]].mesh);
  } finally {
    await server.close();
  }
});

test('assembleGlb drops nested occurrences of a block definition that contains itself', () => {
  const box = { positions: new Float32Array([0, 0, 0, 1, 0, 0, 0, 1, 0]), normals: new Float32Array([0, 0, 1, 0, 0, 1, 0, 0, 1]), indices: new Uint32Array([0, 1, 2]), triangleCount: 1 };
  const plain = (id, extra = {}) => ({
    id, name: id, layerIndex: 0, layer: 'L', visible: true, colorSource: 'layer', objectColor: { r: 0, g: 0, b: 0, a: 255 },
    layerColor: { r: 255, g: 255, b: 255, a: 255 }, userStrings: {}, reference: null, geometry: null, ...extra,
  });
  const entries = new Map([
    ['loop_box', plain('loop_box')],
    ['self_ref', plain('self_ref', { reference: { definitionId: 'LOOP', matrix: [1, 0, 0, 0, 0, 1, 0, 0, 0, 0, 1, 0, 5, 0, 0, 1] } })],
    ['top', plain('top', { reference: { definitionId: 'LOOP', matrix: [1, 0, 0, 0, 0, 1, 0, 0, 0, 0, 1, 0, 0, 0, 0, 1] } })],
  ]);
  const definitions = new Map([['LOOP', ['loop_box', 'self_ref']]]);
  const topLevel = [entries.get('top')];

  const { reachable, cycles } = collectReachable(topLevel, entries, definitions);
  assert.deepEqual([...reachable], ['loop_box']);
  assert.deepEqual([...cycles], ['LOOP']);

  const triangles = new Map([['loop_box', box]]);
  const { glb, objectCount, triangleCount } = assembleGlb({ topLevel, entries, definitions, triangles, name: 'loop', units: 'Millimeters' });
  assert.equal(objectCount, 1);
  assert.equal(triangleCount, 1);
  const { json } = checkGlb(glb);
  const top = byName(json, 'top');
  assert.equal(top.children.length, 1, 'the self-reference is dropped instead of recursing forever');
  assert.equal(json.nodes[top.children[0]].name, 'loop_box');
});
