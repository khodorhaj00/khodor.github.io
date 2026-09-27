import assert from 'node:assert/strict';
import { connect } from 'node:net';
import { test } from 'node:test';
import { Writable } from 'node:stream';
import { VERSION } from '../src/app.js';
import { createLogger } from '../src/logger.js';
import { MAGIC } from '../src/rhino.js';
import { createFakeCompute } from './helpers/fakeCompute.js';
import { fixture, startServer } from './helpers/client.js';

/** Writes raw HTTP/1.1 bytes to the server and resolves with everything it answered once it closes the socket. */
function rawExchange(server, request, { timeoutMs = 2000 } = {}) {
  return new Promise((resolve, reject) => {
    const socket = connect(Number(new URL(server.base).port), '127.0.0.1');
    const chunks = [];
    const timer = setTimeout(() => { socket.destroy(); reject(new Error('server kept the socket open')); }, timeoutMs);
    socket.on('data', (chunk) => chunks.push(chunk));
    socket.on('error', reject);
    socket.on('close', () => { clearTimeout(timer); resolve(Buffer.concat(chunks).toString('latin1')); });
    socket.write(request);
  });
}

const partialUpload = (path, declaredLength) => `POST ${path} HTTP/1.1\r\nHost: test\r\nContent-Type: application/octet-stream\r\nContent-Length: ${declaredLength}\r\n\r\n0123456789`;

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

    // Declared size above the limit: answered before the body arrives and the socket is closed,
    // so a phone does not upload 200 MB just to learn the file is too big.
    const answer = await rawExchange(server, partialUpload('/convert', 5_000_000));
    assert.match(answer, /^HTTP\/1\.1 413 /);
    assert.match(answer, /\r\nConnection: close\r\n/i);
    assert.deepEqual(JSON.parse(answer.slice(answer.indexOf('\r\n\r\n') + 4)), { error: 'too_large', detail: 'request body exceeds 1 MB' });

    // Chunked bodies carry no Content-Length: the streaming limit still applies.
    const chunk = Buffer.alloc(64 * 1024, 0x41);
    let sent = 0;
    const stream = new ReadableStream({
      pull(controller) {
        if (sent > 1024 * 1024) { controller.close(); return; }
        controller.enqueue(chunk); sent += chunk.length;
      },
    });
    const chunked = await fetch(`${server.base}/mesh`, { method: 'POST', body: stream, duplex: 'half', headers: { 'content-type': 'application/octet-stream' } });
    assert.equal(chunked.status, 413);
    assert.deepEqual(await chunked.json(), { error: 'too_large', detail: 'request body exceeds 1 MB' });

    const ok = await server.post('/mesh', fixture('meshes.3dm'));
    assert.equal(ok.status, 200, 'a 78 KB file passes a 1 MB limit');
  } finally {
    await server.close();
  }
});

test('transport problems are reported as bad_request, not invalid_file', async () => {
  const server = startServer();
  try {
    const res = await server.post('/convert', fixture('meshes.3dm'), { headers: { 'content-encoding': 'zstd' } });
    assert.equal(res.status, 415);
    assert.deepEqual(res.json(), { error: 'bad_request', detail: 'unsupported content encoding "zstd"' });
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
    assert.equal(record.aborted, false);
    assert.match(record.ts, /^\d{4}-\d{2}-\d{2}T/);
    assert.ok(lines.every((l) => l.endsWith('\n') && l.indexOf('\n') === l.length - 1), 'one line per record');
  } finally {
    await server.close();
  }
});

test('an upload the client drops mid-body is logged as aborted', async () => {
  const lines = [];
  const sink = new Writable({ write(chunk, _enc, cb) { lines.push(chunk.toString()); cb(); } });
  const logger = createLogger('info', { stdout: sink, stderr: sink });
  const server = startServer({ logger });
  try {
    await new Promise((resolve, reject) => {
      const socket = connect(Number(new URL(server.base).port), '127.0.0.1');
      socket.on('error', reject);
      socket.write(partialUpload('/mesh', 1_000_000), () => setTimeout(() => { socket.destroy(); resolve(); }, 100));
    });
    const deadline = Date.now() + 2000;
    while (lines.length === 0 && Date.now() < deadline) await new Promise((r) => setTimeout(r, 10));
    const records = lines.map((l) => JSON.parse(l)).filter((r) => r.path === '/mesh');
    assert.equal(records.length, 1, 'exactly one line for the aborted request');
    assert.equal(records[0].method, 'POST');
    assert.equal(records[0].status, 400, 'body-parser reports the aborted body');
    assert.equal(records[0].bytesIn, 1_000_000);
    assert.equal(records[0].aborted, true);
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
