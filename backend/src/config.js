export const QUALITIES = ['draft', 'default', 'fine'];
export const LOG_LEVELS = ['error', 'warn', 'info', 'debug'];

function intVar(env, name, fallback, { min = 1 } = {}) {
  const raw = env[name];
  if (raw === undefined || raw === '') return fallback;
  const value = Number(raw);
  if (!Number.isInteger(value) || value < min) {
    throw new Error(`${name} must be an integer >= ${min}, got "${raw}"`);
  }
  return value;
}

function enumVar(env, name, allowed, fallback) {
  const raw = env[name];
  if (raw === undefined || raw === '') return fallback;
  if (!allowed.includes(raw)) {
    throw new Error(`${name} must be one of ${allowed.join(', ')}, got "${raw}"`);
  }
  return raw;
}

export function normalizeComputeUrl(url) {
  const trimmed = (url ?? '').trim();
  if (trimmed === '') return '';
  return trimmed.endsWith('/') ? trimmed : `${trimmed}/`;
}

/**
 * Reads the service configuration from an environment map (see backend/README.md §Environment).
 * An empty COMPUTE_URL disables Rhino.Compute entirely; an unset one falls back to localhost:5000.
 */
export function loadConfig(env = process.env) {
  return {
    port: intVar(env, 'PORT', 8080, { min: 0 }),
    appApiKey: env.APP_API_KEY ?? '',
    computeUrl: normalizeComputeUrl(env.COMPUTE_URL === undefined ? 'http://localhost:5000/' : env.COMPUTE_URL),
    computeApiKey: env.COMPUTE_API_KEY ?? '',
    computeTimeoutMs: intVar(env, 'COMPUTE_TIMEOUT_MS', 120000),
    computeBatch: intVar(env, 'COMPUTE_BATCH', 20),
    maxUploadMb: intVar(env, 'MAX_UPLOAD_MB', 200),
    meshQuality: enumVar(env, 'MESH_QUALITY', QUALITIES, 'default'),
    logLevel: enumVar(env, 'LOG_LEVEL', LOG_LEVELS, 'info'),
  };
}
