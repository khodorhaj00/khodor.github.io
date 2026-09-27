import rhino3dm from 'rhino3dm';

/** The rhino3dm WASM module, initialised once per process. */
export const rhinoReady = rhino3dm();

export const MAGIC = '3D Geometry File Format';

export function hasMagic(bytes) {
  return bytes.length >= MAGIC.length && bytes.toString('latin1', 0, MAGIC.length) === MAGIC;
}

/**
 * Frees rhino3dm (embind) handles, ignoring null/undefined. The destructor is taken from embind's
 * shared ClassHandle prototype rather than from the handle: the table classes (`objects()`,
 * `layers()`, `materials()`) shadow `delete` with `delete(id)`, which removes an entry, and every
 * table keeps the whole parsed model alive in WASM memory until it is destroyed.
 */
export function release(...handles) {
  for (const handle of handles) {
    if (handle) destructorOf(handle).call(handle);
  }
}

function destructorOf(handle) {
  let proto = Object.getPrototypeOf(handle);
  while (proto !== null && !Object.hasOwn(proto, 'isDeleted')) proto = Object.getPrototypeOf(proto);
  if (proto === null) throw new TypeError('release(): not a rhino3dm handle');
  return proto.delete;
}

export function meshingParameters(rhino, quality) {
  switch (quality) {
    case 'draft': return rhino.MeshingParameters.fastRenderMesh();
    case 'fine': return rhino.MeshingParameters.qualityRenderMesh();
    default: return rhino.MeshingParameters.default();
  }
}

/** Maps the rhino3dm UnitSystem enum to its plain name (`UnitSystem_Millimeters` → `Millimeters`). */
export function unitName(unitSystem) {
  const name = unitSystem?.constructor?.name ?? '';
  return name.startsWith('UnitSystem_') ? name.slice('UnitSystem_'.length) : 'Unknown';
}

/** `getUserStrings()` returns `[key, value]` pairs; callers want a plain object. */
export function userStringsObject(attributes) {
  const result = {};
  if (attributes.userStringCount > 0) {
    for (const [key, value] of attributes.getUserStrings()) result[key] = value;
  }
  return result;
}
