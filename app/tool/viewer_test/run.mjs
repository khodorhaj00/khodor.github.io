// Playwright harness for app/assets/viewer (see docs/ARCHITECTURE.md §2.3).
// Serves the repo root over plain http, drives the viewer page through window.viewer,
// and checks the events it emits plus the pixels it draws.
//
//   npm ci && node run.mjs            (PW_CHROMIUM=/path/to/chrome to use a local binary)

import http from 'node:http';
import fs from 'node:fs';
import fsp from 'node:fs/promises';
import path from 'node:path';
import { fileURLToPath } from 'node:url';
import { chromium } from 'playwright';

const here = path.dirname(fileURLToPath(import.meta.url));
const repoRoot = path.resolve(here, '../../..');
const outDir = path.join(here, 'out');
const VIEWER_PATH = '/app/assets/viewer/index.html';
const BLANK_THRESHOLD = 0.02;
// Mean luminance (0-255) of the drawn model pixels that a black-layer model must reach;
// the background gradient sits at 17-31, unlifted black meshes measured ~19.
const MIN_MODEL_LUMINANCE = 60;
const BOX_TRIANGLES = 12;
const SPHERE_TRIANGLES = 24 * 12 * 2; // sphere_mesh(nu=24, nv=12) quads, two triangles each

const FIXTURES = [
  { name: 'meshes.3dm', url: '/backend/test/fixtures/meshes.3dm' },
  { name: 'brep_nomesh.3dm', url: '/backend/test/fixtures/brep_nomesh.3dm' },
  { name: 'blocks.3dm', url: '/backend/test/fixtures/blocks.3dm' },
  { name: 'Rhino_Logo.3dm', url: '/samples/Rhino_Logo.3dm' },
  { name: 'nested_blocks.3dm', url: '/app/tool/viewer_test/fixtures/nested_blocks.3dm' },
  { name: 'hidden_objects.3dm', url: '/app/tool/viewer_test/fixtures/hidden_objects.3dm' },
  { name: 'black_layer.3dm', url: '/app/tool/viewer_test/fixtures/black_layer.3dm' },
  { name: 'textured.3dm', url: '/app/tool/viewer_test/fixtures/textured.3dm' },
];

const MIME = {
  '.html': 'text/html; charset=utf-8',
  '.js': 'text/javascript; charset=utf-8',
  '.mjs': 'text/javascript; charset=utf-8',
  '.css': 'text/css; charset=utf-8',
  '.wasm': 'application/wasm',
  '.3dm': 'application/octet-stream',
  '.json': 'application/json',
  '.png': 'image/png',
};

// ---------------------------------------------------------------------------------------
// Static server
// ---------------------------------------------------------------------------------------

function startServer() {
  const server = http.createServer(async (req, res) => {
    const urlPath = decodeURIComponent(new URL(req.url, 'http://localhost').pathname);
    const filePath = path.normalize(path.join(repoRoot, urlPath));
    if (!filePath.startsWith(repoRoot + path.sep)) {
      res.writeHead(403).end();
      return;
    }
    let stat;
    try {
      stat = await fsp.stat(filePath);
    } catch {
      console.log(`  http 404 ${urlPath}`);
      res.writeHead(404).end();
      return;
    }
    if (!stat.isFile()) {
      res.writeHead(404).end();
      return;
    }
    res.writeHead(200, {
      'Content-Type': MIME[path.extname(filePath)] || 'application/octet-stream',
      'Content-Length': stat.size,
      'Cache-Control': 'no-store',
    });
    fs.createReadStream(filePath).pipe(res);
  });
  return new Promise((resolve) => {
    server.listen(0, '127.0.0.1', () => resolve({ server, port: server.address().port }));
  });
}

// ---------------------------------------------------------------------------------------
// Assertions
// ---------------------------------------------------------------------------------------

const failures = [];
let checks = 0;
// Set while a test deliberately requests a missing file; Chromium logs the 404 as a console error.
let expectResourceError = false;

function check(condition, message) {
  checks += 1;
  if (condition) {
    console.log(`  ok   ${message}`);
  } else {
    failures.push(message);
    console.log(`  FAIL ${message}`);
  }
}

function checkEqual(actual, expected, label) {
  check(actual === expected, `${label} = ${JSON.stringify(actual)} (expected ${JSON.stringify(expected)})`);
}

// ---------------------------------------------------------------------------------------
// Page helpers
// ---------------------------------------------------------------------------------------

async function eventCount(page) {
  return page.evaluate(() => (window.__viewerEvents || []).length);
}

async function eventsSince(page, from) {
  return page.evaluate((start) => window.__viewerEvents.slice(start), from);
}

async function settle(page) {
  // The viewer renders on demand through a single requestAnimationFrame; two frames
  // guarantee the last request has been drawn.
  await page.evaluate(() => new Promise((resolve) => requestAnimationFrame(() => requestAnimationFrame(resolve))));
}

// Reads the WebGL canvas back through a 2D canvas: counts pixels that were drawn
// (the renderer clears to transparent, so anything with alpha is model or grid), averages
// their luminance and hashes the whole frame so two renders can be compared.
async function frameSignature(page) {
  return page.evaluate(() => {
    const source = document.querySelector('canvas');
    const copy = document.createElement('canvas');
    copy.width = source.width;
    copy.height = source.height;
    const ctx = copy.getContext('2d');
    ctx.drawImage(source, 0, 0);
    const data = ctx.getImageData(0, 0, copy.width, copy.height).data;
    let drawn = 0;
    let luminance = 0;
    let hash = 2166136261;
    for (let i = 0; i < data.length; i += 4) {
      if (data[i + 3] !== 0) {
        drawn += 1;
        luminance += 0.2126 * data[i] + 0.7152 * data[i + 1] + 0.0722 * data[i + 2];
      }
      hash = Math.imul(hash ^ data[i], 16777619);
      hash = Math.imul(hash ^ data[i + 1], 16777619);
      hash = Math.imul(hash ^ data[i + 2], 16777619);
      hash = Math.imul(hash ^ data[i + 3], 16777619);
    }
    return { drawn, total: data.length / 4, meanLuminance: drawn ? luminance / drawn : 0, hash: hash >>> 0 };
  });
}

// Counts every <img> decode the page starts (the stock loader decodes embedded textures
// through <img> data URIs, once per object); installed before the page loads.
async function installImageLoadCounter(page) {
  await page.addInitScript(() => {
    const descriptor = Object.getOwnPropertyDescriptor(HTMLImageElement.prototype, 'src');
    window.__imageLoads = 0;
    Object.defineProperty(HTMLImageElement.prototype, 'src', {
      configurable: true,
      get() {
        return descriptor.get.call(this);
      },
      set(value) {
        window.__imageLoads += 1;
        descriptor.set.call(this, value);
      },
    });
  });
}

// Runs exportGlb() and returns the decoded GLB (header checks included), or null.
async function exportGlb(page, label) {
  const from = await eventCount(page);
  await page.evaluate(() => window.viewer.exportGlb());
  const event = (await eventsSince(page, from)).find((e) => e.name === 'exportResult');
  check(event && event.payload.ok === true, `${label}: exportGlb ok (${event ? event.payload.error || event.payload.filename : 'no event'})`);
  if (!event || !event.payload.ok) return null;
  const bytes = Buffer.from(event.payload.base64, 'base64');
  checkEqual(bytes.toString('latin1', 0, 4), 'glTF', `${label}: exportGlb magic`);
  checkEqual(bytes.readUInt32LE(4), 2, `${label}: glTF version`);
  checkEqual(bytes.readUInt32LE(8), bytes.length, `${label}: declared length matches`);
  const jsonLength = bytes.readUInt32LE(12);
  checkEqual(bytes.readUInt32LE(16), 0x4e4f534a, `${label}: first chunk is JSON`);
  try {
    return { payload: event.payload, bytes, json: JSON.parse(bytes.toString('utf8', 20, 20 + jsonLength)) };
  } catch (error) {
    check(false, `${label}: JSON chunk parses (${error.message})`);
    return null;
  }
}

async function modelSignature(page) {
  await page.evaluate(() => window.viewer.setGrid(false));
  await settle(page);
  const signature = await frameSignature(page);
  await page.evaluate(() => window.viewer.setGrid(true));
  await settle(page);
  return signature;
}

async function loadModel(page, options, expectOk = true) {
  const from = await eventCount(page);
  await page.evaluate((opts) => window.viewer.load(opts), options);
  const events = await eventsSince(page, from);
  const results = events.filter((e) => e.name === 'loadResult');
  checkEqual(results.length, 1, `${options.name}: loadResult events`);
  const result = results[0] ? results[0].payload : { ok: false, error: 'no loadResult' };
  checkEqual(result.name, options.name, `${options.name}: result name`);
  if (expectOk) {
    const phases = [...new Set(events.filter((e) => e.name === 'loadProgress').map((e) => e.payload.phase))];
    check(
      ['fetch', 'parse', 'build'].every((phase) => phases.includes(phase)),
      `${options.name}: loadProgress phases ${JSON.stringify(phases)}`,
    );
    check(result.ok === true, `${options.name}: ok (${result.ok ? 'loaded' : result.error})`);
  }
  return result;
}

async function checkNotBlank(page, label) {
  const signature = await modelSignature(page);
  const ratio = signature.drawn / signature.total;
  check(ratio > BLANK_THRESHOLD, `${label}: ${(ratio * 100).toFixed(1)}% of pixels drawn (> ${BLANK_THRESHOLD * 100}%)`);
  return signature;
}

function layerIndex(stats, name) {
  const layer = stats.layers.find((l) => l.name === name);
  return layer ? layer.index : -1;
}

// ---------------------------------------------------------------------------------------
// Fixture-specific expectations
// ---------------------------------------------------------------------------------------

function checkMeshes(stats) {
  checkEqual(stats.meshes, 50, 'meshes.3dm: meshes');
  checkEqual(stats.layers.length, 4, 'meshes.3dm: layers');
  const hidden = stats.layers.find((l) => l.name === 'HIDDEN');
  check(hidden && hidden.visible === false, 'meshes.3dm: layer HIDDEN is invisible');
  checkEqual(stats.curves, 1, 'meshes.3dm: curves');
  checkEqual(stats.points, 1, 'meshes.3dm: points');
  checkEqual(stats.unmeshed.total, 0, 'meshes.3dm: unmeshed.total');
  checkEqual(stats.units, 'Millimeters', 'meshes.3dm: units');
  checkEqual(stats.triangles, 48 * BOX_TRIANGLES + SPHERE_TRIANGLES, 'meshes.3dm: rendered triangles (48 boxes + sphere)');
  // The hidden box sits at x = -340..-260; the visible model starts at x = -50.
  checkEqual(stats.bbox.min[0], -50, 'meshes.3dm: bbox excludes the hidden box');
  checkEqual(stats.objects, 52, 'meshes.3dm: objects');
  checkEqual(stats.layers.find((l) => l.name === 'PARTS').objectCount, 24, 'meshes.3dm: PARTS objectCount');
  checkEqual(stats.layers.find((l) => l.name === 'PARTS').color, '#C83C28', 'meshes.3dm: PARTS color');
  checkEqual(stats.layers[0].fullPath, 'PARTS', 'meshes.3dm: layer fullPath');
  checkEqual(stats.bbox.max[2], 600, 'meshes.3dm: bbox.max.z is the point at z=600');
}

function checkBrepNoMesh(stats) {
  checkEqual(stats.unmeshed.breps, 2, 'brep_nomesh.3dm: unmeshed.breps');
  checkEqual(stats.unmeshed.total, 2, 'brep_nomesh.3dm: unmeshed.total');
  checkEqual(stats.meshes, 1, 'brep_nomesh.3dm: meshes');
  checkEqual(stats.warnings.filter((w) => w.type === 'no mesh').length, 2, 'brep_nomesh.3dm: "no mesh" warnings');
}

function checkBlocks(stats) {
  checkEqual(stats.blocks, 5, 'blocks.3dm: blocks');
  checkEqual(stats.triangles, 5 * BOX_TRIANGLES, 'blocks.3dm: rendered triangles');
  checkEqual(stats.meshes, 0, 'blocks.3dm: top-level meshes (block content is not counted twice)');
  // 5 instance references + the box inside each instance, all on layer BLOCKS.
  checkEqual(stats.layers[0].objectCount, 10, 'blocks.3dm: BLOCKS objectCount (references + instance content)');
}

function checkRhinoLogo(stats) {
  checkEqual(stats.meshes, 12, 'Rhino_Logo.3dm: meshes (6 Breps + 6 SubDs)');
  checkEqual(stats.curves, 218, 'Rhino_Logo.3dm: curves');
  checkEqual(stats.unmeshed.total, 0, 'Rhino_Logo.3dm: unmeshed.total');
  checkEqual(stats.pointClouds, 1, 'Rhino_Logo.3dm: pointClouds');
  checkEqual(stats.lights, 2, 'Rhino_Logo.3dm: lights');
  checkEqual(stats.other, 4, 'Rhino_Logo.3dm: other (text dots)');
  checkEqual(stats.objects, 237, 'Rhino_Logo.3dm: objects');
  checkEqual(stats.layers.length, 6, 'Rhino_Logo.3dm: layers');
  check(stats.layers.find((l) => l.name === 'subd').visible === false, 'Rhino_Logo.3dm: layer subd hidden in file');
  console.log(`  info Rhino_Logo.3dm: ${stats.triangles} triangles, ${stats.vertices} vertices, warnings ${JSON.stringify(stats.warnings.map((w) => w.type))}`);
}

function checkNestedBlocks(stats) {
  // Two references to 'outer' (each = 'inner' moved by (100,0,0)) and one to 'inner'.
  checkEqual(stats.blocks, 3, 'nested_blocks.3dm: blocks (top-level references only)');
  checkEqual(stats.meshes, 0, 'nested_blocks.3dm: top-level meshes');
  checkEqual(stats.triangles, 3 * BOX_TRIANGLES, 'nested_blocks.3dm: rendered triangles (one box per instance, nested one included)');
  checkEqual(JSON.stringify(stats.bbox), JSON.stringify({ min: [-25, -225, -25], max: [125, 325, 25] }), 'nested_blocks.3dm: bbox applies the nested (100,0,0) offset under the (0,y,0) placements');
  // 3 references + 2 nested references + 3 box members, all on layer 0.
  checkEqual(stats.layers[0].objectCount, 8, 'nested_blocks.3dm: BLOCKS objectCount');
}

function checkHiddenObjects(stats) {
  checkEqual(stats.meshes, 3, 'hidden_objects.3dm: meshes (counted like layer-hidden ones)');
  checkEqual(stats.triangles, 2 * BOX_TRIANGLES, 'hidden_objects.3dm: rendered triangles exclude the Rhino-hidden box');
  checkEqual(stats.bbox.max[0], 550, 'hidden_objects.3dm: bbox stops at the locked box (hidden box at x=1000 excluded)');
}

function checkBlackLayer(stats) {
  checkEqual(stats.layers[0].color, '#000000', 'black_layer.3dm: stats keep the file colour of the black layer');
  checkEqual(stats.layers[1].color, '#400000', 'black_layer.3dm: stats keep the file colour of the dark-red layer');
  checkEqual(stats.meshes, 2, 'black_layer.3dm: meshes');
  checkEqual(stats.curves, 1, 'black_layer.3dm: curves');
  checkEqual(stats.points, 1, 'black_layer.3dm: points');
}

function checkTextured(stats) {
  checkEqual(stats.meshes, 40, 'textured.3dm: meshes');
  checkEqual(stats.triangles, 40 * BOX_TRIANGLES, 'textured.3dm: rendered triangles');
}

const FIXTURE_CHECKS = {
  'meshes.3dm': checkMeshes,
  'brep_nomesh.3dm': checkBrepNoMesh,
  'blocks.3dm': checkBlocks,
  'Rhino_Logo.3dm': checkRhinoLogo,
  'nested_blocks.3dm': checkNestedBlocks,
  'hidden_objects.3dm': checkHiddenObjects,
  'black_layer.3dm': checkBlackLayer,
  'textured.3dm': checkTextured,
};

// Checks that need the page after the fixture is loaded and drawn (grid off).
async function pageCheckHiddenObjects(page) {
  const glb = await exportGlb(page, 'hidden_objects.3dm');
  if (!glb) return;
  const names = glb.json.nodes.map((n) => n.name);
  check(names.includes('visible_box') && names.includes('locked_box') && !names.includes('hidden_box'), `hidden_objects.3dm: exported nodes ${JSON.stringify(names)}`);
}

async function pageCheckBlackLayer(page, stats, signature) {
  check(signature.meanLuminance > MIN_MODEL_LUMINANCE, `black_layer.3dm: drawn pixels mean luminance ${signature.meanLuminance.toFixed(1)} (> ${MIN_MODEL_LUMINANCE})`);
  const glb = await exportGlb(page, 'black_layer.3dm');
  if (!glb) return;
  // Expected: black (mesh and curve), linear dark red (#400000 -> r 0.0513) and the white
  // vertex-coloured point material; a lifted colour would show up as a grey ~[0.32,0.35,0.40].
  const factors = glb.json.materials.map((m) => (m.pbrMetallicRoughness.baseColorFactor || [1, 1, 1, 1]).slice(0, 3));
  const isBlack = (f) => f.every((v) => v === 0);
  const isDarkRed = (f) => f[0] > 0.04 && f[0] < 0.06 && f[1] === 0 && f[2] === 0;
  const isWhite = (f) => f.every((v) => v === 1);
  check(factors.some(isBlack) && factors.some(isDarkRed), `black_layer.3dm: export keeps the file colours ${JSON.stringify(factors)}`);
  check(factors.every((f) => isBlack(f) || isDarkRed(f) || isWhite(f)), `black_layer.3dm: no export material is lifted ${JSON.stringify(factors)}`);
}

async function pageCheckTextured(page) {
  checkEqual(await page.evaluate(() => window.__imageLoads), 0, 'textured.3dm: <img> decodes of the embedded texture (materials are replaced, none expected)');
}

const FIXTURE_PAGE_CHECKS = {
  'hidden_objects.3dm': pageCheckHiddenObjects,
  'black_layer.3dm': pageCheckBlackLayer,
  'textured.3dm': pageCheckTextured,
};

// ---------------------------------------------------------------------------------------
// Interaction tests (run on meshes.3dm)
// ---------------------------------------------------------------------------------------

async function testExport(page) {
  const glb = await exportGlb(page, 'exportGlb');
  if (!glb) return;
  const { payload, bytes, json } = glb;
  check(Array.isArray(json.meshes) && json.meshes.length > 0, `exportGlb: meshes.length = ${json.meshes ? json.meshes.length : 0}`);
  checkEqual(payload.filename, 'meshes.glb', 'exportGlb: filename');
  await fsp.writeFile(path.join(outDir, 'meshes.glb'), bytes);
  console.log(`  info exportGlb: ${bytes.length} bytes, ${json.nodes.length} nodes, ${json.materials.length} materials`);
}

async function testLayerToggle(page, stats) {
  const idx = layerIndex(stats, 'PARTS');
  check(idx >= 0, `layer toggle: PARTS index = ${idx}`);
  const before = await modelSignature(page);
  await page.evaluate((i) => window.viewer.setLayerVisible(i, false), idx);
  const after = await modelSignature(page);
  check(after.hash !== before.hash && after.drawn < before.drawn, `layer toggle: frame changed (${before.drawn} → ${after.drawn} drawn pixels)`);
  await page.evaluate((i) => window.viewer.setLayerVisible(i, true), idx);
  const restored = await modelSignature(page);
  checkEqual(restored.hash, before.hash, 'layer toggle: restored frame matches');

  await page.evaluate(() => window.viewer.setAllLayersVisible(false));
  const none = await modelSignature(page);
  checkEqual(none.drawn, 0, 'setAllLayersVisible(false): nothing drawn');
  await page.evaluate(() => window.viewer.setAllLayersVisible(true));
  await page.evaluate((i) => window.viewer.setLayerVisible(i, false), layerIndex(stats, 'HIDDEN'));
  const back = await modelSignature(page);
  checkEqual(back.hash, before.hash, 'setAllLayersVisible(true) + re-hide HIDDEN: frame matches');
}

async function testCurvesAndPoints(page) {
  const all = await modelSignature(page);
  await page.evaluate(() => window.viewer.setCurvesVisible(false));
  const noCurves = await modelSignature(page);
  check(noCurves.drawn < all.drawn, `setCurvesVisible(false): fewer pixels (${all.drawn} → ${noCurves.drawn})`);
  await page.evaluate(() => window.viewer.setCurvesVisible(true));
  await page.evaluate(() => window.viewer.setPointsVisible(false));
  const noPoints = await modelSignature(page);
  check(noPoints.drawn < all.drawn, `setPointsVisible(false): fewer pixels (${all.drawn} → ${noPoints.drawn})`);
  await page.evaluate(() => window.viewer.setPointsVisible(true));
}

async function testDisplayModes(page) {
  const seen = new Set();
  for (const mode of ['shaded_edges', 'wireframe', 'ghosted', 'shaded']) {
    await page.evaluate((m) => window.viewer.setDisplayMode(m), mode);
    const signature = await modelSignature(page);
    check(signature.drawn / signature.total > BLANK_THRESHOLD, `display mode ${mode}: ${signature.drawn} pixels drawn`);
    seen.add(signature.hash);
    await page.screenshot({ path: path.join(outDir, `meshes_${mode}.png`) });
  }
  checkEqual(seen.size, 4, 'display modes: four distinct frames');
}

async function testViewsAndProjection(page) {
  const hashes = new Set();
  for (const view of ['top', 'front', 'right', 'bottom', 'back', 'left', 'iso']) {
    await page.evaluate((v) => window.viewer.setView(v), view);
    const signature = await modelSignature(page);
    check(signature.drawn / signature.total > BLANK_THRESHOLD, `view ${view}: ${signature.drawn} pixels drawn`);
    hashes.add(signature.hash);
    if (view === 'top') await page.screenshot({ path: path.join(outDir, 'meshes_top.png') });
  }
  checkEqual(hashes.size, 7, 'views: seven distinct frames');
  const perspective = await modelSignature(page);
  await page.evaluate(() => window.viewer.setProjection('ortho'));
  const ortho = await modelSignature(page);
  check(ortho.drawn / ortho.total > BLANK_THRESHOLD && ortho.hash !== perspective.hash, `projection ortho: ${ortho.drawn} pixels drawn, differs from perspective`);
  await page.evaluate(() => window.viewer.setProjection('perspective'));
  const back = await modelSignature(page);
  check(Math.abs(back.drawn - perspective.drawn) / perspective.drawn < 0.05, `projection perspective restored: ${perspective.drawn} → ${back.drawn} pixels`);
  await page.evaluate(() => window.viewer.fit());
}

async function testPicking(page) {
  const viewport = page.viewportSize();
  const from = await eventCount(page);
  await page.mouse.click(viewport.width / 2, viewport.height / 2);
  const events = (await eventsSince(page, from)).filter((e) => e.name === 'objectPicked');
  checkEqual(events.length, 1, 'pick centre: one objectPicked event');
  const hit = events[0] && events[0].payload;
  check(hit !== null && typeof hit === 'object', `pick centre: hit ${hit ? `${hit.objectType} "${hit.name}" on ${hit.layerName}` : 'nothing'}`);
  if (hit) {
    check(typeof hit.id === 'string' && hit.id.length > 0, 'pick: id is a guid string');
    check(Array.isArray(hit.size) && hit.size.length === 3 && hit.size.every((v) => v > 0), `pick: size ${JSON.stringify(hit.size)}`);
    check(Array.isArray(hit.center) && hit.center.length === 3, `pick: center ${JSON.stringify(hit.center)}`);
    check(typeof hit.userStrings === 'object' && hit.userStrings !== null, `pick: userStrings ${JSON.stringify(hit.userStrings)}`);
    check(typeof hit.layerIndex === 'number', `pick: layerIndex ${hit.layerIndex}`);
  }
  const highlighted = await modelSignature(page);
  await page.screenshot({ path: path.join(outDir, 'meshes_picked.png') });

  // Lower-left box of the grid in the fitted iso view (fixed 1280x800 viewport).
  const from1 = await eventCount(page);
  await page.mouse.click(430, 600);
  const box = (await eventsSince(page, from1)).find((e) => e.name === 'objectPicked');
  const boxHit = box && box.payload;
  check(boxHit && /^block_\d_\d$/.test(boxHit.name), `pick box: hit ${boxHit ? `"${boxHit.name}" on ${boxHit.layerName}` : 'nothing'}`);
  if (boxHit) {
    check(boxHit.userStrings.PART_ID === boxHit.name.replace('block_', 'P').replace('_', ''), `pick box: userStrings ${JSON.stringify(boxHit.userStrings)}`);
    check(boxHit.size.every((v) => Math.abs(v - 100) < 1e-6), `pick box: size ${JSON.stringify(boxHit.size)}`);
  }

  const from2 = await eventCount(page);
  await page.mouse.click(4, 4);
  const cleared = (await eventsSince(page, from2)).filter((e) => e.name === 'objectPicked');
  check(cleared.length === 1 && cleared[0].payload === null, 'pick empty corner: objectPicked null');
  const plain = await modelSignature(page);
  check(plain.hash !== highlighted.hash, 'pick: highlight cleared changes the frame');
}

// Tapping block content reports the top-level instance (name, layer, user strings), not
// the anonymous definition member.
async function testPickingBlocks(page) {
  const viewport = page.viewportSize();
  await loadModel(page, { url: '/backend/test/fixtures/blocks.3dm', name: 'blocks.3dm' });
  const from = await eventCount(page);
  await page.mouse.click(viewport.width / 2, viewport.height / 2);
  const hit = ((await eventsSince(page, from)).find((e) => e.name === 'objectPicked') || {}).payload;
  check(hit && /^ref_\d$/.test(hit.name), `pick block: hit ${hit ? `${hit.objectType} "${hit.name}" on ${hit.layerName}` : 'nothing'}`);
  if (hit) {
    checkEqual(hit.objectType, 'InstanceReference', 'pick block: objectType');
    checkEqual(hit.blockName, 'unit_box', 'pick block: blockName');
    checkEqual(hit.layerName, 'BLOCKS', 'pick block: layerName');
    check(hit.size.every((v) => Math.abs(v - 50) < 1e-6), `pick block: size ${JSON.stringify(hit.size)}`);
  }

  await loadModel(page, { url: '/app/tool/viewer_test/fixtures/nested_blocks.3dm', name: 'nested_blocks.3dm' });
  const from1 = await eventCount(page);
  await page.mouse.click(viewport.width / 2, viewport.height / 2);
  const nested = ((await eventsSince(page, from1)).find((e) => e.name === 'objectPicked') || {}).payload;
  check(nested && /^(outer_ref_\d|inner_ref)$/.test(nested.name), `pick nested block: hit ${nested ? `${nested.objectType} "${nested.name}" (block ${nested.blockName})` : 'nothing'}`);
  if (nested && nested.name.startsWith('outer_ref_')) {
    checkEqual(nested.blockName, 'outer', 'pick nested block: top-level instance, not the nested one');
    checkEqual(nested.userStrings.PART_ID, nested.name.replace('outer_ref_', 'OUTER'), `pick nested block: userStrings ${JSON.stringify(nested.userStrings)}`);
  }
}

async function testGetStats(page, expected) {
  const raw = await page.evaluate(() => window.viewer.getStats());
  check(typeof raw === 'string', 'getStats: returns a string');
  let parsed = null;
  try {
    parsed = JSON.parse(raw);
  } catch {
    parsed = null;
  }
  check(parsed && parsed.objects === expected.objects && parsed.triangles === expected.triangles, 'getStats: matches loadResult stats');
}

async function testBase64Load(page) {
  const base64 = (await fsp.readFile(path.join(repoRoot, 'backend/test/fixtures/meshes.3dm'))).toString('base64');
  const result = await loadModel(page, { base64, name: 'meshes-base64.3dm' });
  if (result.ok) checkEqual(result.stats.meshes, 50, 'base64 load: meshes');
}

async function testClear(page) {
  await page.evaluate(() => window.viewer.clear());
  checkEqual(await page.evaluate(() => window.viewer.getStats()), 'null', 'clear: getStats() is "null"');
  await settle(page);
  const signature = await frameSignature(page);
  checkEqual(signature.drawn, 0, 'clear: nothing drawn');
}

async function testBadLoad(page) {
  expectResourceError = true;
  const result = await loadModel(page, { url: '/backend/test/fixtures/does_not_exist.3dm', name: 'missing.3dm' }, false);
  expectResourceError = false;
  check(result.ok === false && typeof result.error === 'string' && result.error.includes('404'), `bad url: ok=false, error "${result.error}"`);
}

// A truncated or garbage file (rhino3dm returns no document) fails with a readable
// message, and the worker keeps working afterwards.
async function testCorruptLoad(page) {
  const meshes = await fsp.readFile(path.join(repoRoot, 'backend/test/fixtures/meshes.3dm'));
  const garbage = Buffer.concat([Buffer.from('3D Geometry File Format '), Buffer.alloc(4000, 0x5a)]);
  for (const [name, bytes] of [['truncated.3dm', meshes.subarray(0, 20000)], ['garbage.3dm', garbage]]) {
    const result = await loadModel(page, { base64: bytes.toString('base64'), name }, false);
    check(result.ok === false && /valid or complete \.3dm/.test(result.error), `${name}: ok=false, error "${result.error}"`);
  }
  const result = await loadModel(page, { url: '/backend/test/fixtures/meshes.3dm', name: 'meshes.3dm' });
  if (result.ok) checkEqual(result.stats.meshes, 50, 'after corrupt loads: meshes.3dm still loads');
}

// rhino3dm failing to instantiate inside the worker (simulated by making
// WebAssembly.instantiate reject in the served rhino3dm.js, which is inlined into the Blob
// worker) must surface as a log error, never emit viewerReady, and fail load() instead of
// hanging it.
async function testInitFailure(browser, port) {
  const context = await browser.newContext({ viewport: { width: 640, height: 480 }, deviceScaleFactor: 1 });
  const page = await context.newPage();
  page.setDefaultTimeout(120000);
  const pageErrors = [];
  page.on('pageerror', (error) => pageErrors.push(error.message));
  const rhino3dmJs = await fsp.readFile(path.join(repoRoot, 'app/assets/viewer/vendor/rhino3dm/rhino3dm.js'), 'utf8');
  await page.route('**/vendor/rhino3dm/rhino3dm.js', (route) => route.fulfill({
    status: 200,
    contentType: 'text/javascript',
    body: `WebAssembly.instantiate = () => Promise.reject(new RangeError('WebAssembly.instantiate(): Out of memory (simulated)'));\n${rhino3dmJs}`,
  }));
  await page.goto(`http://127.0.0.1:${port}${VIEWER_PATH}`);
  await page.waitForFunction(() => (window.__viewerEvents || []).some((e) => e.name === 'log' && e.payload.level === 'error'));
  const events = await page.evaluate(() => window.__viewerEvents);
  const logged = events.find((e) => e.name === 'log' && e.payload.level === 'error').payload.message;
  check(/rhino3dm initialisation failed/.test(logged) && /Out of memory/.test(logged), `init failure: log error "${logged}"`);
  check(!events.some((e) => e.name === 'viewerReady'), 'init failure: viewerReady not emitted');
  const result = await loadModel(page, { url: '/backend/test/fixtures/meshes.3dm', name: 'meshes.3dm' }, false);
  check(result.ok === false && /rhino3dm failed to initialise/.test(result.error), `init failure: load() fails instead of hanging (${result.error})`);
  checkEqual(pageErrors.length, 0, `init failure: uncaught page errors ${JSON.stringify(pageErrors)}`);
  await context.close();
}

// ---------------------------------------------------------------------------------------
// Main
// ---------------------------------------------------------------------------------------

async function main() {
  await fsp.mkdir(outDir, { recursive: true });
  const { server, port } = await startServer();
  const browser = await chromium.launch({
    executablePath: process.env.PW_CHROMIUM || undefined,
    args: ['--use-angle=swiftshader', '--enable-unsafe-swiftshader', '--ignore-gpu-blocklist'],
  });
  const timings = [];
  try {
    const context = await browser.newContext({ viewport: { width: 1280, height: 800 }, deviceScaleFactor: 1 });
    const page = await context.newPage();
    page.setDefaultTimeout(120000);
    await installImageLoadCounter(page);
    page.on('pageerror', (error) => check(false, `page error: ${error.message}`));
    page.on('console', (message) => {
      const text = message.text();
      if (text.startsWith('[viewer-event]')) {
        if (process.env.VERBOSE) console.log('  ' + text);
      } else if (message.type() === 'error' && !(expectResourceError && text.startsWith('Failed to load resource'))) {
        check(false, `console error: ${text}`);
      } else if (message.type() === 'warning' && process.env.VERBOSE) {
        console.log('  console.warn: ' + text);
      }
    });

    console.log(`viewer: http://127.0.0.1:${port}${VIEWER_PATH}`);
    await page.goto(`http://127.0.0.1:${port}${VIEWER_PATH}`);
    await page.waitForFunction(() => (window.__viewerEvents || []).some((e) => e.name === 'viewerReady'));
    const ready = await page.evaluate(() => window.__viewerEvents.find((e) => e.name === 'viewerReady').payload);
    checkEqual(ready.three, 'r186', 'viewerReady: three');
    checkEqual(ready.rhino3dm, '8.32.2', 'viewerReady: rhino3dm');

    let meshesStats = null;
    for (const fixture of FIXTURES) {
      console.log(`\n== ${fixture.name}`);
      const result = await loadModel(page, { url: fixture.url, name: fixture.name });
      if (!result.ok) continue;
      FIXTURE_CHECKS[fixture.name](result.stats);
      const signature = await checkNotBlank(page, fixture.name);
      if (FIXTURE_PAGE_CHECKS[fixture.name]) await FIXTURE_PAGE_CHECKS[fixture.name](page, result.stats, signature);
      await page.screenshot({ path: path.join(outDir, fixture.name.replace(/\.3dm$/, '.png')) });
      timings.push({ fixture: fixture.name, ...result.stats.timings, triangles: result.stats.triangles });
      if (fixture.name === 'meshes.3dm') meshesStats = result.stats;
    }

    if (meshesStats) {
      console.log('\n== interaction (meshes.3dm)');
      await loadModel(page, { url: '/backend/test/fixtures/meshes.3dm', name: 'meshes.3dm' });
      await testGetStats(page, meshesStats);
      await testExport(page);
      await testLayerToggle(page, meshesStats);
      await testCurvesAndPoints(page);
      await testDisplayModes(page);
      await testViewsAndProjection(page);
      await testPicking(page);
      console.log('\n== picking (blocks.3dm, nested_blocks.3dm)');
      await testPickingBlocks(page);
      console.log('\n== base64 / errors / clear');
      await testBase64Load(page);
      await testBadLoad(page);
      await testCorruptLoad(page);
      await testClear(page);
    }
    console.log('\n== worker initialisation failure');
    await testInitFailure(browser, port);
  } finally {
    await browser.close();
    server.close();
  }

  console.log('\nTimings (ms):');
  console.log('  fixture             fetch   parse   build   total   triangles');
  for (const t of timings) {
    console.log(
      `  ${t.fixture.padEnd(18)}${String(t.fetchMs).padStart(8)}${String(t.parseMs).padStart(8)}` +
        `${String(t.buildMs).padStart(8)}${String(t.totalMs).padStart(8)}${String(t.triangles).padStart(12)}`,
    );
  }
  console.log(`\n${checks - failures.length}/${checks} checks passed`);
  if (failures.length) {
    console.log('Failures:');
    for (const f of failures) console.log(`  - ${f}`);
    process.exitCode = 1;
  }
}

main().catch((error) => {
  console.error(error);
  process.exitCode = 1;
});
