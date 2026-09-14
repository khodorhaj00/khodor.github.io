import assert from 'node:assert/strict';
import { test } from 'node:test';
import { loadConfig } from '../src/config.js';

test('defaults match the documented table', () => {
  assert.deepEqual(loadConfig({}), {
    port: 8080,
    appApiKey: '',
    computeUrl: 'http://localhost:5000/',
    computeApiKey: '',
    computeTimeoutMs: 120000,
    computeBatch: 20,
    maxUploadMb: 200,
    meshQuality: 'default',
    logLevel: 'info',
  });
});

test('values are read from the environment and the Compute URL gets a trailing slash', () => {
  const config = loadConfig({
    PORT: '9000', APP_API_KEY: 'a', COMPUTE_URL: 'http://win-compute:5000', COMPUTE_API_KEY: 'c',
    COMPUTE_TIMEOUT_MS: '5000', COMPUTE_BATCH: '5', MAX_UPLOAD_MB: '10', MESH_QUALITY: 'fine', LOG_LEVEL: 'debug',
  });
  assert.equal(config.port, 9000);
  assert.equal(config.appApiKey, 'a');
  assert.equal(config.computeUrl, 'http://win-compute:5000/');
  assert.equal(config.computeApiKey, 'c');
  assert.equal(config.computeTimeoutMs, 5000);
  assert.equal(config.computeBatch, 5);
  assert.equal(config.maxUploadMb, 10);
  assert.equal(config.meshQuality, 'fine');
  assert.equal(config.logLevel, 'debug');
});

test('an empty COMPUTE_URL disables Compute', () => {
  assert.equal(loadConfig({ COMPUTE_URL: '' }).computeUrl, '');
  assert.equal(loadConfig({ COMPUTE_URL: '   ' }).computeUrl, '');
});

test('invalid values fail fast', () => {
  assert.throws(() => loadConfig({ COMPUTE_BATCH: '0' }), /COMPUTE_BATCH/);
  assert.throws(() => loadConfig({ MAX_UPLOAD_MB: 'lots' }), /MAX_UPLOAD_MB/);
  assert.throws(() => loadConfig({ MESH_QUALITY: 'ultra' }), /MESH_QUALITY/);
  assert.throws(() => loadConfig({ LOG_LEVEL: 'loud' }), /LOG_LEVEL/);
});
