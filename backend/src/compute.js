import RhinoCompute from 'compute-rhino3d';
import { normalizeComputeUrl } from './config.js';

/**
 * Raised by the Compute client. `kind` is one of `unreachable` (network failure), `timeout`
 * or `error` (Compute answered with a non-2xx status; `detail` carries its message).
 */
export class ComputeError extends Error {
  constructor(kind, detail, status = undefined) {
    super(detail);
    this.name = 'ComputeError';
    this.kind = kind;
    this.status = status;
  }
}

async function readBody(response, asJson) {
  try {
    return asJson ? await response.json() : await response.text();
  } catch (err) {
    throw new ComputeError('error', `Compute returned an unreadable body: ${err.message}`, response.status);
  }
}

/**
 * Wraps the `compute-rhino3d` SDK (which supplies endpoint paths and argument zipping) with a
 * transport that has a timeout, sends the API key and surfaces Compute's error text.
 *
 * The SDK is a process-wide singleton (`RhinoCompute.url` / `apiKey` / `computeFetch`), so only
 * one client configuration is active per process; the server creates exactly one.
 */
export function createComputeClient({ url, apiKey = '', timeoutMs = 120000, fetch: fetchImpl = globalThis.fetch }) {
  const baseUrl = normalizeComputeUrl(url);
  if (!baseUrl) throw new Error('createComputeClient: url is required');

  const headers = () => {
    const h = { 'Content-Type': 'application/json', 'User-Agent': `compute.rhino3d.js/${RhinoCompute.version}` };
    if (apiKey) h.RhinoComputeKey = apiKey;
    return h;
  };

  async function request(endpoint, init, limitMs, asJson) {
    const controller = new AbortController();
    const timer = setTimeout(() => controller.abort(), limitMs);
    try {
      let response;
      try {
        response = await fetchImpl(baseUrl + endpoint, { ...init, headers: headers(), signal: controller.signal });
      } catch (err) {
        if (controller.signal.aborted) throw new ComputeError('timeout', `Compute did not answer within ${limitMs} ms`);
        throw new ComputeError('unreachable', `Compute at ${baseUrl} is unreachable: ${err.cause?.message ?? err.message}`);
      }
      if (!response.ok) {
        const text = await readBody(response, false);
        throw new ComputeError('error', `Compute responded ${response.status}: ${text.slice(0, 2000)}`, response.status);
      }
      return readBody(response, asJson);
    } finally {
      clearTimeout(timer);
    }
  }

  RhinoCompute.url = baseUrl;
  RhinoCompute.apiKey = apiKey || null;
  RhinoCompute.computeFetch = (endpoint, args) => request(endpoint, { method: 'POST', body: JSON.stringify(args) }, timeoutMs, true);

  return {
    url: baseUrl,

    /**
     * `Mesh.CreateFromBrep(Brep, MeshingParameters)` for every brep in one Compute call.
     * @param {object[]} brepsJson  encoded Breps (`brep.encode()`)
     * @param {object} mpJson       encoded MeshingParameters
     * @returns {Promise<Array<object[]|null>>} per brep, the encoded meshes Compute produced
     */
    meshBreps(brepsJson, mpJson) {
      if (brepsJson.length === 0) return Promise.resolve([]);
      return RhinoCompute.Mesh.createFromBrep1(brepsJson, brepsJson.map(() => mpJson), true);
    },

    /** `GET <url>version` — true when Compute answers 2xx within `limitMs`. */
    async probe(limitMs = 3000) {
      try {
        await request('version', { method: 'GET' }, limitMs, false);
        return true;
      } catch (err) {
        if (err instanceof ComputeError) return false;
        throw err;
      }
    },
  };
}
