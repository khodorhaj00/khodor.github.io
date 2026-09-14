import { createHash, timingSafeEqual } from 'node:crypto';
import { readFileSync } from 'node:fs';
import express from 'express';
import { ComputeError } from './compute.js';
import { loadConfig, QUALITIES } from './config.js';
import { badRequest, HttpError, invalidFile, tooLarge, unauthorized } from './errors.js';
import { silentLogger } from './logger.js';
import { meshFile } from './meshing.js';
import { hasMagic, release, rhinoReady } from './rhino.js';
import { buildScene } from './scene.js';

const pkg = JSON.parse(readFileSync(new URL('../package.json', import.meta.url), 'utf8'));
export const VERSION = pkg.version;

const HEALTH_PROBE_MS = 3000;

function keysMatch(expected, provided) {
  if (typeof provided !== 'string') return false;
  // Hashing both sides gives equal-length buffers so the comparison is constant time.
  const a = createHash('sha256').update(expected).digest();
  const b = createHash('sha256').update(provided).digest();
  return timingSafeEqual(a, b);
}

function safeFilename(name) {
  const base = String(name ?? '').split(/[\\/]/).pop().replace(/\.3dm$/i, '').replace(/[^\w.-]+/g, '_').replace(/^_+|_+$/g, '');
  return base || 'model';
}

function parseQuality(query, fallback) {
  const q = query.quality;
  if (q === undefined || q === '') return fallback;
  if (typeof q !== 'string' || !QUALITIES.includes(q)) throw badRequest(`quality must be one of ${QUALITIES.join(', ')}`);
  return q;
}

function parseDocument(rhino, body) {
  if (!Buffer.isBuffer(body) || body.length === 0) throw invalidFile('request body is empty; send the raw .3dm bytes');
  if (!hasMagic(body)) throw invalidFile('not a .3dm file (magic bytes missing)');
  const doc = rhino.File3dm.fromByteArray(new Uint8Array(body.buffer, body.byteOffset, body.byteLength));
  if (!doc) throw invalidFile('rhino3dm could not parse the file');
  return doc;
}

function mapError(err, maxUploadMb) {
  if (err instanceof HttpError) return { status: err.status, code: err.code, detail: err.message };
  if (err instanceof ComputeError) {
    if (err.kind === 'timeout') return { status: 504, code: 'compute_timeout', detail: err.message };
    if (err.kind === 'unreachable') return { status: 502, code: 'compute_unreachable', detail: err.message };
    return { status: 502, code: 'compute_error', detail: err.message };
  }
  if (err?.type === 'entity.too.large') return mapError(tooLarge(maxUploadMb));
  // body-parser's own 4xx (aborted request, bad encoding, ...)
  if (typeof err?.status === 'number' && err.status >= 400 && err.status < 500) {
    return { status: err.status, code: 'invalid_file', detail: err.message };
  }
  return { status: 500, code: 'internal', detail: 'internal error' };
}

/**
 * @param {object} options
 * @param {object} [options.config]   see loadConfig()
 * @param {object|null} [options.compute]  Compute client `{ url, meshBreps(brepsJson, mpJson), probe(ms) }`; null = not configured
 * @param {object} [options.logger]
 */
export function createApp({ config = loadConfig({}), compute = null, logger = silentLogger } = {}) {
  const app = express();
  app.disable('x-powered-by');
  app.set('etag', false);
  const startedAt = Date.now();

  app.use((req, res, next) => {
    const t0 = performance.now();
    res.on('finish', () => {
      logger.info({
        method: req.method,
        path: req.path,
        status: res.statusCode,
        ms: Math.round(performance.now() - t0),
        bytesIn: Number(req.headers['content-length'] ?? 0),
        bytesOut: Number(res.getHeader('content-length') ?? 0),
        meshed: res.locals.meshed ?? 0,
        skipped: res.locals.skipped ?? 0,
      });
    });
    next();
  });

  app.get('/health', async (req, res) => {
    const reachable = compute ? await compute.probe(HEALTH_PROBE_MS) : null;
    res.json({
      ok: true,
      version: VERSION,
      uptimeSec: Math.round((Date.now() - startedAt) / 1000),
      compute: { url: compute ? compute.url : config.computeUrl, configured: Boolean(compute), reachable },
    });
  });

  app.use((req, res, next) => {
    if (config.appApiKey && !keysMatch(config.appApiKey, req.get('x-api-key'))) return next(unauthorized());
    next();
  });

  const rawBody = express.raw({ type: () => true, limit: `${config.maxUploadMb}mb` });

  app.post('/mesh', rawBody, async (req, res) => {
    const quality = parseQuality(req.query, config.meshQuality);
    const rhino = await rhinoReady;
    const doc = parseDocument(rhino, req.body);
    try {
      const result = await meshFile(rhino, doc, { compute, quality, batchSize: config.computeBatch, logger });
      const bytes = result.meshedCount > 0 ? Buffer.from(doc.toByteArray()) : req.body;
      res.locals.meshed = result.meshedCount;
      res.locals.skipped = result.skippedCount;
      res.set({
        'Content-Type': 'application/octet-stream',
        'X-Meshed-Count': String(result.meshedCount),
        'X-Skipped-Count': String(result.skippedCount),
        'X-Compute-Ms': String(result.computeMs),
        'Content-Disposition': `attachment; filename="${safeFilename(req.query.name)}.3dm"`,
      });
      res.send(bytes);
    } finally {
      release(doc);
    }
  });

  app.post('/convert', rawBody, async (req, res) => {
    const quality = parseQuality(req.query, config.meshQuality);
    const rhino = await rhinoReady;
    const doc = parseDocument(rhino, req.body);
    const name = safeFilename(req.query.name);
    try {
      const result = await buildScene(rhino, doc, { compute, quality, batchSize: config.computeBatch, name, logger });
      res.locals.skipped = result.skippedCount;
      res.set({
        'Content-Type': 'model/gltf-binary',
        'X-Object-Count': String(result.objectCount),
        'X-Triangle-Count': String(result.triangleCount),
        'X-Skipped-Count': String(result.skippedCount),
        'X-Compute-Ms': String(result.computeMs),
        'Content-Disposition': `attachment; filename="${name}.glb"`,
      });
      res.send(result.glb);
    } finally {
      release(doc);
    }
  });

  app.use((req, res) => {
    res.status(404).json({ error: 'not_found', detail: `${req.method} ${req.path} is not a route` });
  });

  app.use((err, req, res, next) => {
    if (res.headersSent) return next(err);
    const mapped = mapError(err, config.maxUploadMb);
    if (mapped.code === 'internal') {
      logger.error({ msg: 'request failed', method: req.method, path: req.path, error: err?.message, stack: err?.stack });
    } else if (mapped.status >= 500) {
      logger.warn({ msg: 'upstream failure', method: req.method, path: req.path, error: mapped.code, detail: mapped.detail });
    }
    // The body may be unread on 413; closing avoids a stalled keep-alive connection.
    if (mapped.status === 413) res.set('Connection', 'close');
    res.status(mapped.status).json({ error: mapped.code, detail: mapped.detail });
  });

  return app;
}
