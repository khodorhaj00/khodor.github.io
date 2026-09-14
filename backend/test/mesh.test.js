import assert from 'node:assert/strict';
import { before, test } from 'node:test';
import { ComputeError } from '../src/compute.js';
import { rhinoReady } from '../src/rhino.js';
import { boxMesh, createFakeCompute } from './helpers/fakeCompute.js';
import { fixture, startServer } from './helpers/client.js';

let rhino;
before(async () => { rhino = await rhinoReady; });

function describeObjects(bytes) {
  const doc = rhino.File3dm.fromByteArray(new Uint8Array(bytes));
  assert.ok(doc, 'response parses as .3dm');
  const objects = doc.objects();
  const result = [];
  for (let i = 0; i < objects.count; i++) {
    const object = objects.get(i);
    const attributes = object.attributes();
    const geometry = object.geometry();
    result.push({
      type: geometry.objectType.constructor.name.replace('ObjectType_', ''),
      name: attributes.name,
      id: attributes.id,
      layerIndex: attributes.layerIndex,
      colorSource: attributes.colorSource.constructor.name.replace('ObjectColorSource_', ''),
      objectColor: { ...attributes.objectColor },
      userStrings: attributes.getUserStrings(),
      isInstanceDefinitionObject: attributes.isInstanceDefinitionObject,
      faces: geometry.objectType === rhino.ObjectType.Mesh ? geometry.faces().count : null,
    });
  }
  const definitions = [];
  for (let i = 0; i < doc.instanceDefinitions().count; i++) {
    const definition = doc.instanceDefinitions().get(i);
    definitions.push({ id: definition.id, name: definition.name, objectIds: definition.getObjectIds() });
  }
  const layers = doc.layers().count;
  const units = doc.settings().modelUnitSystem.constructor.name;
  doc.delete();
  return { objects: result, definitions, layers, units };
}

test('POST /mesh replaces unmeshed Breps with Meshes carrying the original attributes', async () => {
  const compute = await createFakeCompute();
  const server = startServer({ compute });
  try {
    const original = describeObjects(fixture('brep_nomesh.3dm'));
    assert.equal(original.objects.filter((o) => o.type === 'Brep').length, 2);

    const res = await server.post('/mesh?name=brep_nomesh.3dm', fixture('brep_nomesh.3dm'));
    assert.equal(res.status, 200, res.buffer.toString());
    assert.equal(res.headers.get('content-type'), 'application/octet-stream');
    assert.equal(res.headers.get('x-meshed-count'), '2');
    assert.equal(res.headers.get('x-skipped-count'), '0');
    assert.match(res.headers.get('x-compute-ms'), /^\d+$/);
    assert.equal(res.headers.get('content-disposition'), 'attachment; filename="brep_nomesh.3dm"');
    assert.equal(compute.calls.length, 1, 'both breps fit in one batch of 20');
    assert.equal(compute.calls[0].count, 2);

    const meshed = describeObjects(res.buffer);
    assert.equal(meshed.objects.length, 3);
    assert.equal(meshed.objects.filter((o) => o.type === 'Brep').length, 0);
    assert.equal(meshed.objects.filter((o) => o.type === 'Mesh').length, 3);
    assert.equal(meshed.layers, 1);
    assert.equal(meshed.units, 'UnitSystem_Millimeters');
    for (const name of ['box_brep', 'sphere_brep', 'mesh_ok']) {
      const before = original.objects.find((o) => o.name === name);
      const after = meshed.objects.find((o) => o.name === name);
      assert.ok(after, `${name} is present`);
      assert.equal(after.type, 'Mesh');
      assert.equal(after.id, before.id, 'object id preserved');
      assert.equal(after.layerIndex, before.layerIndex, 'layer preserved');
      assert.ok(after.faces > 0);
    }
    assert.equal(meshed.objects.find((o) => o.name === 'box_brep').faces, 12, 'two 6-quad box meshes appended into one');
  } finally {
    await server.close();
  }
});

test('POST /mesh batches Compute calls by COMPUTE_BATCH and honours the quality parameter', async () => {
  const compute = await createFakeCompute();
  const server = startServer({ compute, env: { COMPUTE_BATCH: '1', MESH_QUALITY: 'fine' } });
  try {
    let res = await server.post('/mesh', fixture('brep_nomesh.3dm'));
    assert.equal(res.status, 200);
    assert.equal(compute.calls.length, 2);
    assert.deepEqual(compute.calls.map((c) => c.count), [1, 1]);
    const fine = rhino.MeshingParameters.qualityRenderMesh().encode();
    assert.deepEqual(compute.calls[0].mp, fine, 'MESH_QUALITY env is the default quality');

    res = await server.post('/mesh?quality=draft', fixture('brep_nomesh.3dm'));
    assert.equal(res.status, 200);
    assert.deepEqual(compute.calls[2].mp, rhino.MeshingParameters.fastRenderMesh().encode());

    res = await server.post('/mesh?quality=default', fixture('brep_nomesh.3dm'));
    assert.equal(res.status, 200);
    assert.deepEqual(compute.calls[4].mp, rhino.MeshingParameters.default().encode());

    res = await server.post('/mesh?quality=ultra', fixture('brep_nomesh.3dm'));
    assert.equal(res.status, 400);
    assert.equal(res.json().error, 'bad_request');
  } finally {
    await server.close();
  }
});

test('POST /mesh returns the original bytes untouched when nothing needs meshing', async () => {
  const compute = await createFakeCompute();
  const server = startServer({ compute });
  try {
    const bytes = fixture('meshes.3dm');
    const res = await server.post('/mesh', bytes);
    assert.equal(res.status, 200);
    assert.equal(res.headers.get('x-meshed-count'), '0');
    assert.equal(res.headers.get('x-skipped-count'), '0');
    assert.equal(res.headers.get('x-compute-ms'), '0');
    assert.ok(res.buffer.equals(bytes));
    assert.equal(compute.calls.length, 0);
  } finally {
    await server.close();
  }
});

test('POST /mesh without a configured Compute fails with 502 compute_unreachable', async () => {
  const server = startServer({ compute: null });
  try {
    const res = await server.post('/mesh', fixture('brep_nomesh.3dm'));
    assert.equal(res.status, 502);
    const body = res.json();
    assert.equal(body.error, 'compute_unreachable');
    assert.match(body.detail, /COMPUTE_URL/);
  } finally {
    await server.close();
  }
});

test('POST /mesh handles Extrusions, block definition objects and preserves colors and user strings', async () => {
  const file = new rhino.File3dm();
  file.settings().modelUnitSystem = rhino.UnitSystem.Inches;
  const layer = file.layers().addLayer('WALLS', { r: 10, g: 20, b: 30, a: 255 });

  const extrusionAttributes = new rhino.ObjectAttributes();
  extrusionAttributes.name = 'pipe';
  extrusionAttributes.layerIndex = layer;
  extrusionAttributes.colorSource = rhino.ObjectColorSource.ColorFromObject;
  extrusionAttributes.objectColor = { r: 200, g: 100, b: 50, a: 255 };
  extrusionAttributes.setUserString('PART_ID', 'X1');
  const circle = new rhino.Circle(10);
  const extrusion = rhino.Extrusion.create(circle.toNurbsCurve(), 5, true);
  const extrusionId = file.objects().addExtrusion(extrusion, extrusionAttributes);

  const definitionAttributes = new rhino.ObjectAttributes();
  definitionAttributes.name = 'def_box';
  const brep = rhino.Brep.createFromBoundingBox(new rhino.BoundingBox([0, 0, 0], [10, 10, 10]));
  const definitionIndex = file.instanceDefinitions().add('blk', '', '', '', [0, 0, 0], [brep], [definitionAttributes]);
  const definition = file.instanceDefinitions().get(definitionIndex);
  const [definitionObjectId] = definition.getObjectIds();
  const referenceAttributes = new rhino.ObjectAttributes();
  referenceAttributes.name = 'ref';
  file.objects().addInstanceObject(new rhino.InstanceReference(definition.id, rhino.Transform.translationXYZ(50, 0, 0)), referenceAttributes);

  const meshedAttributes = new rhino.ObjectAttributes();
  meshedAttributes.name = 'already_mesh';
  const mesh = boxMesh(rhino, [0, 0, 0], [1, 1, 1]);
  file.objects().addMesh(mesh, meshedAttributes);
  const bytes = Buffer.from(file.toByteArray());
  file.delete();

  const compute = await createFakeCompute();
  const server = startServer({ compute });
  try {
    const res = await server.post('/mesh', bytes);
    assert.equal(res.status, 200, res.buffer.toString());
    assert.equal(res.headers.get('x-meshed-count'), '2');
    assert.equal(res.headers.get('x-skipped-count'), '0');
    assert.equal(compute.calls[0].count, 2, 'extrusion converted to a Brep and sent along with the definition Brep');

    const result = describeObjects(res.buffer);
    assert.equal(result.units, 'UnitSystem_Inches');
    assert.deepEqual(result.objects.map((o) => o.type).sort(), ['InstanceReference', 'Mesh', 'Mesh', 'Mesh']);

    const pipe = result.objects.find((o) => o.name === 'pipe');
    assert.equal(pipe.type, 'Mesh');
    assert.equal(pipe.id, extrusionId);
    assert.equal(pipe.layerIndex, layer);
    assert.equal(pipe.colorSource, 'ColorFromObject');
    assert.deepEqual(pipe.objectColor, { r: 200, g: 100, b: 50, a: 255 });
    assert.deepEqual(pipe.userStrings, [['PART_ID', 'X1']]);

    const definitionObject = result.objects.find((o) => o.name === 'def_box');
    assert.equal(definitionObject.type, 'Mesh');
    assert.equal(definitionObject.id, definitionObjectId);
    assert.equal(definitionObject.isInstanceDefinitionObject, true);
    assert.deepEqual(result.definitions[0].objectIds, [definitionObjectId], 'block definition still points at the replaced object');
  } finally {
    await server.close();
  }
});

test('POST /mesh counts breps Compute could not mesh as skipped', async () => {
  const compute = await createFakeCompute({ respond: (breps) => breps.map((_, i) => (i === 0 ? null : [])) });
  const server = startServer({ compute });
  try {
    const res = await server.post('/mesh', fixture('brep_nomesh.3dm'));
    assert.equal(res.status, 200);
    assert.equal(res.headers.get('x-meshed-count'), '0');
    assert.equal(res.headers.get('x-skipped-count'), '2');
    assert.ok(res.buffer.equals(fixture('brep_nomesh.3dm')), 'nothing meshed → original bytes');
  } finally {
    await server.close();
  }
});

test('POST /mesh maps Compute failures to 502/504 with the error code and message', async () => {
  const cases = [
    { error: new ComputeError('timeout', 'Compute did not answer within 5 ms'), status: 504, code: 'compute_timeout' },
    { error: new ComputeError('unreachable', 'Compute at http://x/ is unreachable: ECONNREFUSED'), status: 502, code: 'compute_unreachable' },
    { error: new ComputeError('error', 'Compute responded 500: Rhino.Runtime.DocumentCollectedException', 500), status: 502, code: 'compute_error' },
  ];
  for (const { error, status, code } of cases) {
    const compute = await createFakeCompute({ respond: () => { throw error; } });
    const server = startServer({ compute });
    try {
      const res = await server.post('/mesh', fixture('brep_nomesh.3dm'));
      assert.equal(res.status, status);
      assert.deepEqual(res.json(), { error: code, detail: error.message });
    } finally {
      await server.close();
    }
  }
});

test('POST /mesh treats a malformed Compute answer as compute_error', async () => {
  const compute = await createFakeCompute({ respond: () => ({ unexpected: true }) });
  const server = startServer({ compute });
  try {
    const res = await server.post('/mesh', fixture('brep_nomesh.3dm'));
    assert.equal(res.status, 502);
    assert.equal(res.json().error, 'compute_error');
  } finally {
    await server.close();
  }
});
