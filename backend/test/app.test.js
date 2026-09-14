import assert from 'node:assert/strict';
import { test } from 'node:test';
import { Writable } from 'node:stream';
import { VERSION } from '../src/app.js';
import { createLogger } from '../src/logger.js';
import { MAGIC } from '../src/rhino.js';
import { createFakeCompute } from './helpers/fakeCompute.js';
import { fixture, startServer } from './helpers/client.js';

test('GET /health reports version, uptime and Compute state', async () => {
  const unconfigured = startServer({ env: { COMPUTE_URL: '' } });
  try {
    const res = await unconfigured.get('/health');
    assert.equal(res.status, 200);
    const body = res.json();
    assert.equal(body.ok, true);
    assert.equal(body.version, VERSION);
    assert.equal(typeof body.uptimeSec, 'number');
    assert.deepEqual(body.compute, { url: '', configured: false, reachable: null });
  } finally {
    await unconfigured.close();
  }

  for (const reachable of [true, false]) {
    const compute = await createFakeCompute({ reachable });
    const server = startServer({ compute });
    try {
      const body = (await server.get('/health')).json();
      assert.deepEqual(body.compute, { url: 'http://fake-compute.test/', configured: true, reachable });
    } finally {
      await server.close();
    }
  }
});

test('APP_API_KEY guards every route except /health with a constant-time comparison', async () => {
  const server = startServer({ env: { APP_API_KEY: 'secret-key' } });
  try {
    assert.equal((await server.get('/health')).status, 200);

    let res = await server.post('/convert', fixture('meshes.3dm'));
    assert.equal(res.status, 401);
    assert.deepEqual(res.json(), { error: 'unauthorized', detail: 'missing or wrong X-Api-Key' });

    res = await server.post('/convert', fixture('meshes.3dm'), { headers: { 'x-api-key': 'secret-kez' } });
    assert.equal(res.status, 401);

    res = await server.post('/convert', fixture('meshes.3dm'), { headers: { 'x-api-key': 'secret-key-longer' } });
    assert.equal(res.status, 401);

    res = await server.post('/convert', fixture('meshes.3dm'), { headers: { 'X-Api-Key': 'secret-key' } });
    assert.equal(res.status, 200);

    res = await server.get('/nope', { headers: { 'x-api-key': 'secret-key' } });
    assert.equal(res.status, 404);
    assert.equal(res.json().error, 'not_found');
  } finally {
    await server.close();
  }
});

test('bodies that are not .3dm files are rejected with 400 invalid_file', async () => {
  const server = startServer();
  try {
    for (const route of ['/mesh', '/convert']) {
      let res = await server.post(route, Buffer.from('not a rhino file at all'));
      assert.equal(res.status, 400);
      assert.equal(res.json().error, 'invalid_file');

      res = await server.post(route, Buffer.from(`${MAGIC} 7 but the rest is garbage that opennurbs cannot read`));
      assert.equal(res.status, 400);
      assert.equal(res.json().error, 'invalid_file');
      assert.match(res.json().detail, /could not parse/);

      res = await server.post(route, Buffer.alloc(0));
      assert.equal(res.status, 400);
      assert.equal(res.json().error, 'invalid_file');

      res = await server.post(route, fixture('meshes.3dm').subarray(0, 4000));
      assert.equal(res.status, 400, 'truncated file');
    }
  } finally {
    await server.close();
  }
});

test('bodies above MAX_UPLOAD_MB are rejected with 413 too_large', async () => {
  const server = startServer({ env: { MAX_UPLOAD_MB: '1' } });
  try {
    const res = await server.post('/mesh', Buffer.alloc(1024 * 1024 + 1, 0x41));
    assert.equal(res.status, 413);
    assert.deepEqual(res.json(), { error: 'too_large', detail: 'request body exceeds 1 MB' });

    const ok = await server.post('/mesh', fixture('meshes.3dm'));
    assert.equal(ok.status, 200, 'a 78 KB file passes a 1 MB limit');
  } finally {
    await server.close();
  }
});

test('unknown routes answer JSON 404', async () => {
  const server = startServer();
  try {
    const res = await server.get('/nope');
    assert.equal(res.status, 404);
    assert.deepEqual(res.json(), { error: 'not_found', detail: 'GET /nope is not a route' });
  } finally {
    await server.close();
  }
});

test('every request produces one JSON log line with the documented fields', async () => {
  const lines = [];
  const sink = new Writable({ write(chunk, _enc, cb) { lines.push(chunk.toString()); cb(); } });
  const logger = createLogger('info', { stdout: sink, stderr: sink });
  const server = startServer({ logger });
  try {
    await server.post('/convert?name=meshes.3dm', fixture('meshes.3dm'));
    await new Promise((r) => setTimeout(r, 10));
    const records = lines.map((l) => JSON.parse(l));
    const record = records.find((r) => r.path === '/convert');
    assert.ok(record, 'request logged');
    assert.equal(record.method, 'POST');
    assert.equal(record.status, 200);
    assert.equal(typeof record.ms, 'number');
    assert.equal(record.bytesIn, fixture('meshes.3dm').length);
    assert.ok(record.bytesOut > 1000);
    assert.equal(record.meshed, 0);
    assert.equal(record.skipped, 0);
    assert.match(record.ts, /^\d{4}-\d{2}-\d{2}T/);
    assert.ok(lines.every((l) => l.endsWith('\n') && l.indexOf('\n') === l.length - 1), 'one line per record');
  } finally {
    await server.close();
  }
});

test('LOG_LEVEL filters records', () => {
  const lines = [];
  const sink = new Writable({ write(chunk, _enc, cb) { lines.push(chunk.toString()); cb(); } });
  const logger = createLogger('warn', { stdout: sink, stderr: sink });
  logger.info({ msg: 'hidden' });
  logger.debug({ msg: 'hidden' });
  logger.warn({ msg: 'shown' });
  logger.error({ msg: 'shown' });
  assert.equal(lines.length, 2);
  assert.deepEqual(lines.map((l) => JSON.parse(l).level), ['warn', 'error']);
});
