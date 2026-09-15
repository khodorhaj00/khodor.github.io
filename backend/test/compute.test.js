import assert from 'node:assert/strict';
import { test } from 'node:test';
import { ComputeError, createComputeClient } from '../src/compute.js';
import { fixture, startServer } from './helpers/client.js';

function jsonResponse(body, status = 200) {
  return new Response(JSON.stringify(body), { status, headers: { 'content-type': 'application/json' } });
}

test('meshBreps posts zipped [brep, meshingParameters] pairs to the multiple=true endpoint with the API key', async () => {
  const requests = [];
  const fetchImpl = async (url, init) => {
    requests.push({ url, init, body: JSON.parse(init.body) });
    return jsonResponse([[{ data: 'mesh-a' }], [{ data: 'mesh-b' }]]);
  };
  const client = createComputeClient({ url: 'http://compute.local:5000', apiKey: 'k3y', timeoutMs: 1000, fetch: fetchImpl });
  assert.equal(client.url, 'http://compute.local:5000/');

  const result = await client.meshBreps([{ data: 'brep-a' }, { data: 'brep-b' }], { GridMinCount: 16 });
  assert.deepEqual(result, [[{ data: 'mesh-a' }], [{ data: 'mesh-b' }]]);
  assert.equal(requests.length, 1);
  assert.equal(requests[0].url, 'http://compute.local:5000/rhino/geometry/mesh/createfrombrep-brep_meshingparameters?multiple=true');
  assert.equal(requests[0].init.method, 'POST');
  assert.equal(requests[0].init.headers.RhinoComputeKey, 'k3y');
  assert.equal(requests[0].init.headers['Content-Type'], 'application/json');
  assert.match(requests[0].init.headers['User-Agent'], /^compute\.rhino3d\.js\//);
  assert.ok(requests[0].init.signal instanceof AbortSignal);
  assert.deepEqual(requests[0].body, [[{ data: 'brep-a' }, { GridMinCount: 16 }], [{ data: 'brep-b' }, { GridMinCount: 16 }]]);

  assert.deepEqual(await client.meshBreps([], {}), []);
  assert.equal(requests.length, 1, 'an empty batch never hits the network');
});

test('the API key header is omitted when no key is configured', async () => {
  let headers;
  const client = createComputeClient({ url: 'http://c/', fetch: async (_url, init) => { headers = init.headers; return jsonResponse([]); } });
  await client.meshBreps([{}], {});
  assert.equal('RhinoComputeKey' in headers, false);
});

test('a hanging Compute call is aborted after timeoutMs and reported as a timeout', async () => {
  const fetchImpl = (_url, { signal }) => new Promise((_resolve, reject) => {
    signal.addEventListener('abort', () => reject(new DOMException('This operation was aborted', 'AbortError')));
  });
  const client = createComputeClient({ url: 'http://c/', timeoutMs: 20, fetch: fetchImpl });
  const t0 = performance.now();
  await assert.rejects(client.meshBreps([{}], {}), (err) => {
    assert.ok(err instanceof ComputeError);
    assert.equal(err.kind, 'timeout');
    assert.match(err.message, /within 20 ms/);
    return true;
  });
  assert.ok(performance.now() - t0 < 2000);
});

test('network failures are reported as unreachable with the underlying cause', async () => {
  const fetchImpl = async () => { throw new TypeError('fetch failed', { cause: new Error('connect ECONNREFUSED 127.0.0.1:5000') }); };
  const client = createComputeClient({ url: 'http://127.0.0.1:5000/', fetch: fetchImpl });
  await assert.rejects(client.meshBreps([{}], {}), (err) => {
    assert.equal(err.kind, 'unreachable');
    assert.match(err.message, /ECONNREFUSED/);
    return true;
  });
  assert.equal(await client.probe(50), false);
});

test("non-2xx answers become compute_error carrying Compute's message", async () => {
  const fetchImpl = async () => new Response('Rhino.Runtime.DocumentCollectedException: mesh failed', { status: 500 });
  const client = createComputeClient({ url: 'http://c/', fetch: fetchImpl });
  await assert.rejects(client.meshBreps([{}], {}), (err) => {
    assert.equal(err.kind, 'error');
    assert.equal(err.status, 500);
    assert.match(err.message, /Compute responded 500: Rhino\.Runtime\.DocumentCollectedException/);
    return true;
  });
});

test('probe GETs <url>version and reports reachability', async () => {
  const seen = [];
  const client = createComputeClient({ url: 'http://c', apiKey: 'k', fetch: async (url, init) => { seen.push({ url, method: init.method }); return jsonResponse({ rhino: '8.0' }); } });
  assert.equal(await client.probe(100), true);
  assert.deepEqual(seen, [{ url: 'http://c/version', method: 'GET' }]);

  const unauthorized = createComputeClient({ url: 'http://c', fetch: async () => new Response('nope', { status: 401 }) });
  assert.equal(await unauthorized.probe(100), false);
});

test('the real client plugged into the app maps failures to 504/502 responses', async () => {
  const timeoutClient = createComputeClient({
    url: 'http://c/', timeoutMs: 10,
    fetch: (_url, { signal }) => new Promise((_r, reject) => signal.addEventListener('abort', () => reject(new Error('aborted')))),
  });
  const server = startServer({ compute: timeoutClient });
  try {
    const res = await server.post('/mesh', fixture('brep_nomesh.3dm'));
    assert.equal(res.status, 504);
    assert.equal(res.json().error, 'compute_timeout');
  } finally {
    await server.close();
  }

  const failing = createComputeClient({ url: 'http://c/', fetch: async () => new Response('boom', { status: 503 }) });
  const server2 = startServer({ compute: failing });
  try {
    const res = await server2.post('/convert', fixture('brep_nomesh.3dm'));
    assert.equal(res.status, 502);
    assert.deepEqual(res.json(), { error: 'compute_error', detail: 'Compute responded 503: boom' });
  } finally {
    await server2.close();
  }
});
