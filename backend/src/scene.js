import { GlbWriter, Z_UP_TO_Y_UP } from './glb.js';
import { brepFaceMeshes, decodeMeshes, extrusionMesh, mergeTriangles, meshToTriangles, subdMesh } from './geometry.js';
import { meshBrepsBatched } from './meshing.js';
import { meshingParameters, release, unitName, userStringsObject } from './rhino.js';

const FALLBACK_COLOR = { r: 128, g: 128, b: 128, a: 255 };

function readLayers(doc) {
  const table = doc.layers();
  const layers = [];
  try {
    const count = table.count;
    for (let i = 0; i < count; i++) {
      const layer = table.get(i);
      layers.push({ index: i, name: layer.name, fullPath: layer.fullPath, color: { ...layer.color }, visible: layer.visible });
      release(layer);
    }
    return layers;
  } finally {
    release(table);
  }
}

function readDefinitions(doc) {
  const table = doc.instanceDefinitions();
  const definitions = new Map();
  try {
    const count = table.count;
    for (let i = 0; i < count; i++) {
      const definition = table.get(i);
      definitions.set(definition.id, definition.getObjectIds());
      release(definition);
    }
    return definitions;
  } finally {
    release(table);
  }
}

/**
 * Plain-data view of every object: everything the glTF assembly needs, plus the geometry
 * handle for tessellation. `handles` collects what the caller must release.
 */
function readObjects(rhino, doc, layers, handles) {
  const objects = doc.objects();
  handles.push(objects);
  const entries = new Map();
  const topLevel = [];
  const count = objects.count;
  for (let i = 0; i < count; i++) {
    const object = objects.get(i);
    const attributes = object.attributes();
    const geometry = object.geometry();
    handles.push(object, attributes, geometry);
    const layer = layers[attributes.layerIndex];
    const isReference = geometry.objectType === rhino.ObjectType.InstanceReference;
    let reference = null;
    if (isReference) {
      const xform = geometry.xform;
      reference = { definitionId: geometry.parentIdefId, matrix: xform.toFloatArray(false) };
      release(xform);
    }
    let colorSource = 'layer';
    if (attributes.colorSource === rhino.ObjectColorSource.ColorFromObject) colorSource = 'object';
    else if (attributes.colorSource === rhino.ObjectColorSource.ColorFromParent) colorSource = 'parent';
    const entry = {
      id: attributes.id,
      name: attributes.name || attributes.id,
      layerIndex: attributes.layerIndex,
      layer: layer?.fullPath ?? '',
      visible: attributes.visible && (layer?.visible ?? true),
      colorSource,
      objectColor: { ...attributes.objectColor },
      layerColor: layer?.color ?? FALLBACK_COLOR,
      userStrings: userStringsObject(attributes),
      reference,
      geometry,
    };
    entries.set(entry.id, entry);
    if (!attributes.isInstanceDefinitionObject) topLevel.push(entry);
  }
  return { entries, topLevel };
}

/**
 * Follows references from the top-level objects. Returns the ids of objects that will render
 * and the ids of definitions that (directly or through nesting) contain themselves; those
 * nested occurrences are dropped rather than recursed into.
 */
export function collectReachable(topLevel, entries, definitions) {
  const reachable = new Set();
  const cycles = new Set();
  const visit = (entry, path) => {
    if (!entry.visible) return;
    if (!entry.reference) { reachable.add(entry.id); return; }
    const { definitionId } = entry.reference;
    const childIds = definitions.get(definitionId);
    if (!childIds) return;
    if (path.has(definitionId)) { cycles.add(definitionId); return; }
    const nested = new Set(path).add(definitionId);
    for (const childId of childIds) {
      const child = entries.get(childId);
      if (child) visit(child, nested);
    }
  };
  for (const entry of topLevel) visit(entry, new Set());
  return { reachable, cycles };
}

async function resolveTriangles(rhino, entries, reachable, { compute, quality, batchSize }) {
  const triangles = new Map();
  const computeTargets = [];
  let skippedCount = 0;
  const timing = { computeMs: 0 };
  const rhinoMeshes = [];
  try {
    for (const id of reachable) {
      const { geometry } = entries.get(id);
      const type = geometry.objectType;
      if (type === rhino.ObjectType.Mesh) {
        triangles.set(id, meshToTriangles(geometry));
      } else if (type === rhino.ObjectType.Brep) {
        const meshes = brepFaceMeshes(rhino, geometry);
        if (meshes.length > 0) {
          rhinoMeshes.push(...meshes);
          triangles.set(id, mergeTriangles(meshes.map(meshToTriangles)));
        } else if (compute) {
          computeTargets.push({ id, brepJson: geometry.encode() });
        } else {
          skippedCount++;
        }
      } else if (type === rhino.ObjectType.Extrusion) {
        const cached = extrusionMesh(rhino, geometry);
        if (cached) {
          rhinoMeshes.push(cached);
          triangles.set(id, meshToTriangles(cached));
        } else {
          const brep = compute ? geometry.toBrep(true) : null;
          if (brep) { computeTargets.push({ id, brepJson: brep.encode() }); release(brep); } else skippedCount++;
        }
      } else if (type === rhino.ObjectType.SubD) {
        const mesh = subdMesh(rhino, geometry);
        if (mesh) { rhinoMeshes.push(mesh); triangles.set(id, meshToTriangles(mesh)); }
      }
    }

    if (computeTargets.length > 0) {
      const mp = meshingParameters(rhino, quality);
      const mpJson = mp.encode();
      release(mp);
      const brepsJson = computeTargets.map((t) => t.brepJson);
      for await (const [index, meshJsonList] of meshBrepsBatched(compute, brepsJson, mpJson, batchSize, timing)) {
        const mesh = decodeMeshes(rhino, meshJsonList);
        if (mesh) { rhinoMeshes.push(mesh); triangles.set(computeTargets[index].id, meshToTriangles(mesh)); } else skippedCount++;
      }
    }
  } finally {
    release(...rhinoMeshes);
  }
  return { triangles, skippedCount, computeMs: Math.round(timing.computeMs) };
}

/**
 * Builds the GLB from plain entries: one node per object, block references as a node with the
 * instance matrix and one child per definition object (nested recursively, cycles dropped), one
 * glTF mesh per (object, color) shared across instances, one material per color, root node Z-up → Y-up.
 * @param {{ topLevel: object[], entries: Map, definitions: Map<string,string[]>, triangles: Map, name: string, units: string }} scene
 * @returns {{ glb: Buffer, objectCount: number, triangleCount: number }}
 */
export function assembleGlb({ topLevel, entries, definitions, triangles, name, units }) {
  const writer = new GlbWriter({ assetExtras: { name, units } });
  const meshIndexByKey = new Map();
  let triangleCount = 0;

  const resolveColor = (entry, inherited) => {
    if (entry.colorSource === 'object') return entry.objectColor;
    if (entry.colorSource === 'parent' && inherited) return inherited;
    return entry.layerColor;
  };
  const extrasOf = (entry) => ({ id: entry.id, layer: entry.layer, layerIndex: entry.layerIndex, userStrings: entry.userStrings });

  const buildNode = (entry, inheritedColor, path) => {
    if (!entry.visible) return null;
    if (entry.reference) {
      const { definitionId, matrix } = entry.reference;
      const childIds = definitions.get(definitionId);
      if (!childIds || path.has(definitionId)) return null;
      const color = resolveColor(entry, inheritedColor);
      const nested = new Set(path).add(definitionId);
      const children = [];
      for (const childId of childIds) {
        const child = entries.get(childId);
        const node = child ? buildNode(child, color, nested) : null;
        if (node !== null) children.push(node);
      }
      if (children.length === 0) return null;
      return writer.addNode({ name: entry.name, matrix, children, extras: extrasOf(entry) });
    }
    const tris = triangles.get(entry.id);
    if (!tris) return null;
    const material = writer.addColorMaterial(resolveColor(entry, inheritedColor));
    const key = `${entry.id}|${material}`;
    let mesh = meshIndexByKey.get(key);
    if (mesh === undefined) {
      mesh = writer.addMesh({ name: entry.name, ...tris, material });
      meshIndexByKey.set(key, mesh);
    }
    triangleCount += tris.triangleCount;
    return writer.addNode({ name: entry.name, mesh, extras: extrasOf(entry) });
  };

  const rootChildren = [];
  for (const entry of topLevel) {
    const node = buildNode(entry, null, new Set());
    if (node !== null) rootChildren.push(node);
  }
  const root = writer.addNode({ name, matrix: Z_UP_TO_Y_UP, children: rootChildren, extras: { units, upAxis: 'Y', sourceUpAxis: 'Z' } });
  return { glb: writer.finish([root]), objectCount: rootChildren.length, triangleCount };
}

/**
 * Renders a File3dm to a GLB. Objects that are hidden or on hidden layers are left out.
 * Unmeshed Breps/Extrusions are sent to Compute when a client is given, otherwise counted as skipped.
 * @returns {Promise<{ glb: Buffer, objectCount: number, triangleCount: number, skippedCount: number, computeMs: number }>}
 */
export async function buildScene(rhino, doc, { compute = null, quality = 'default', batchSize = 20, name = 'model', logger }) {
  const settings = doc.settings();
  const units = unitName(settings.modelUnitSystem);
  release(settings);
  const layers = readLayers(doc);
  const definitions = readDefinitions(doc);
  const handles = [];
  try {
    const { entries, topLevel } = readObjects(rhino, doc, layers, handles);
    const { reachable, cycles } = collectReachable(topLevel, entries, definitions);
    for (const definitionId of cycles) logger.warn({ msg: 'block definition references itself; nested occurrence skipped', definitionId });
    const { triangles, skippedCount, computeMs } = await resolveTriangles(rhino, entries, reachable, { compute, quality, batchSize });
    const { glb, objectCount, triangleCount } = assembleGlb({ topLevel, entries, definitions, triangles, name, units });
    return { glb, objectCount, triangleCount, skippedCount, computeMs };
  } finally {
    release(...handles);
  }
}
