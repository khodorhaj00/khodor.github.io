import { readFileSync } from 'node:fs';
import { createApp } from '../../src/app.js';
import { loadConfig } from '../../src/config.js';

export const FIXTURES = new URL('../fixtures/', import.meta.url);
export const SAMPLES = new URL('../../../samples/', import.meta.url);

export const fixture = (name) => readFileSync(new URL(name, FIXTURES));

/** Starts the app on an ephemeral port and returns helpers to call it; `close()` when done. */
export function startServer({ env = {}, compute = null, logger } = {}) {
  const app = createApp({ config: loadConfig(env), compute, logger });
  const server = app.listen(0);
  const base = `http://127.0.0.1:${server.address().port}`;

  async function post(path, body, { headers = {}, contentType = 'application/octet-stream' } = {}) {
    const response = await fetch(base + path, { method: 'POST', body, headers: { 'content-type': contentType, ...headers } });
    const buffer = Buffer.from(await response.arrayBuffer());
    return { status: response.status, headers: response.headers, buffer, json: () => JSON.parse(buffer.toString('utf8')) };
  }

  async function get(path, { headers = {} } = {}) {
    const response = await fetch(base + path, { headers });
    const buffer = Buffer.from(await response.arrayBuffer());
    return { status: response.status, headers: response.headers, buffer, json: () => JSON.parse(buffer.toString('utf8')) };
  }

  return { base, post, get, close: () => new Promise((resolve) => server.close(resolve)) };
}
