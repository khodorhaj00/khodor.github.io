import rhino3dm from 'rhino3dm';

/** The rhino3dm WASM module, initialised once per process. */
export const rhinoReady = rhino3dm();

export const MAGIC = '3D Geometry File Format';

export function hasMagic(bytes) {
  return bytes.length >= MAGIC.length && bytes.toString('latin1', 0, MAGIC.length) === MAGIC;
}

/**
 * Calls `.delete()` on rhino3dm (embind) handles, ignoring null/undefined. Not for table handles
 * (`objects()`, `layers()`, ...): their `delete(id)` is a bound method that removes an entry.
 */
export function release(...handles) {
  for (const handle of handles) {
    if (handle && typeof handle.delete === 'function') handle.delete();
  }
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
