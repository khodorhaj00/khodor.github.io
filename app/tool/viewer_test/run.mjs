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
// Fraction of the viewport width or height the drawn model must span after a fit (the
// viewer aims at 80% of the limiting axis for the model's silhouette).
const MIN_FIT_FILL = 0.55;
// A pixel counts as visibly changed by a pick highlight when |dR|+|dG|+|dB| exceeds this,
// and a highlight must change at least PICK_MIN_CHANGED pixels around the picked object.
const PICK_MIN_DIFF = 60;
const PICK_MIN_CHANGED = 200;
const LANDSCAPE = { width: 1280, height: 800 };
const PORTRAIT = { width: 412, height: 915 };

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
// Set while a test deliberately throws on the page: console and page errors matching it are
// the point of the test, not a failure of it.
let expectedErrorPattern = null;

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
// (the renderer clears to transparent, so anything with alpha is model or grid), their
// bounding box and mean luminance, and hashes the whole frame so two renders can be
// compared.
async function frameSignature(page) {
  return page.evaluate(() => {
    const source = document.querySelector('canvas');
    const copy = document.createElement('canvas');
    copy.width = source.width;
    copy.height = source.height;
    const ctx = copy.getContext('2d');
    ctx.drawImage(source, 0, 0);
    const data = ctx.getImageData(0, 0, copy.width, copy.height).data;
    const bounds = { minX: Infinity, minY: Infinity, maxX: -Infinity, maxY: -Infinity };
    let drawn = 0;
    let luminance = 0;
    let hash = 2166136261;
    for (let i = 0; i < data.length; i += 4) {
      if (data[i + 3] !== 0) {
        drawn += 1;
        luminance += 0.2126 * data[i] + 0.7152 * data[i + 1] + 0.0722 * data[i + 2];
        const x = (i / 4) % copy.width;
        const y = Math.floor(i / 4 / copy.width);
        bounds.minX = Math.min(bounds.minX, x);
        bounds.maxX = Math.max(bounds.maxX, x);
        bounds.minY = Math.min(bounds.minY, y);
        bounds.maxY = Math.max(bounds.maxY, y);
      }
      hash = Math.imul(hash ^ data[i], 16777619);
      hash = Math.imul(hash ^ data[i + 1], 16777619);
      hash = Math.imul(hash ^ data[i + 2], 16777619);
      hash = Math.imul(hash ^ data[i + 3], 16777619);
    }
    return {
      drawn,
      total: data.length / 4,
      width: copy.width,
      height: copy.height,
      bounds,
      meanLuminance: drawn ? luminance / drawn : 0,
      hash: hash >>> 0,
    };
  });
}

// Keeps a copy of the current canvas in the page (window.__frames[key]) so two frames can
// be compared pixel by pixel without shipping megabytes over the protocol.
async function captureFrame(page, key) {
  await settle(page);
  await page.evaluate((k) => {
    const source = document.querySelector('canvas');
    const copy = document.createElement('canvas');
    copy.width = source.width;
    copy.height = source.height;
    const ctx = copy.getContext('2d');
    ctx.drawImage(source, 0, 0);
    (window.__frames ||= {})[k] = ctx.getImageData(0, 0, copy.width, copy.height);
  }, key);
}

// Pixels whose colour differs between two captured frames by more than minDiff
// (|dR|+|dG|+|dB|, alpha changes count as a full difference), with their bounding box.
async function frameDiff(page, keyA, keyB, minDiff) {
  return page.evaluate(([a, b, min]) => {
    const A = window.__frames[a];
    const B = window.__frames[b];
    const bounds = { minX: Infinity, minY: Infinity, maxX: -Infinity, maxY: -Infinity };
    let changed = 0;
    for (let i = 0; i < A.data.length; i += 4) {
      const diff = A.data[i + 3] !== B.data[i + 3]
        ? 765
        : Math.abs(A.data[i] - B.data[i]) + Math.abs(A.data[i + 1] - B.data[i + 1]) + Math.abs(A.data[i + 2] - B.data[i + 2]);
      if (diff <= min) continue;
      changed += 1;
      const x = (i / 4) % A.width;
      const y = Math.floor(i / 4 / A.width);
      bounds.minX = Math.min(bounds.minX, x);
      bounds.maxX = Math.max(bounds.maxX, x);
      bounds.minY = Math.min(bounds.minY, y);
      bounds.maxY = Math.max(bounds.maxY, y);
    }
    return { changed, bounds };
  }, [keyA, keyB, minDiff]);
}

// First pixel in raster order that matches a named colour class, or null.
async function findPixel(page, colorClass) {
  return page.evaluate((cls) => {
    const classes = {
      white: (r, g, b) => r >= 240 && g >= 240 && b >= 240,
      grey: (r, g, b) => Math.abs(r - g) < 25 && Math.abs(g - b) < 25 && g > 100,
      purple: (r, g, b) => r > 140 && b > 140 && g < 120,
    };
    const source = document.querySelector('canvas');
    const copy = document.createElement('canvas');
    copy.width = source.width;
    copy.height = source.height;
    const ctx = copy.getContext('2d');
    ctx.drawImage(source, 0, 0);
    const data = ctx.getImageData(0, 0, copy.width, copy.height).data;
    for (let i = 0; i < data.length; i += 4) {
      if (data[i + 3] !== 0 && classes[cls](data[i], data[i + 1], data[i + 2])) {
        return { x: (i / 4) % copy.width, y: Math.floor(i / 4 / copy.width) };
      }
    }
    return null;
  }, colorClass);
}

// The drawn model (grid off) spans at least MIN_FIT_FILL of the viewport width or height
// and touches no edge.
function checkFramed(signature, label) {
  const { bounds, width, height } = signature;
  const fillX = (bounds.maxX - bounds.minX + 1) / width;
  const fillY = (bounds.maxY - bounds.minY + 1) / height;
  const inside = bounds.minX > 0 && bounds.minY > 0 && bounds.maxX < width - 1 && bounds.maxY < height - 1;
  check(
    inside && Math.max(fillX, fillY) >= MIN_FIT_FILL,
    `${label}: drawn ${(fillX * 100).toFixed(0)}% x ${(fillY * 100).toFixed(0)}% of ${width}x${height}, x[${bounds.minX},${bounds.maxX}] y[${bounds.minY},${bounds.maxY}] (>= ${(MIN_FIT_FILL * 100).toFixed(0)}% on one axis, no edge touched)`,
  );
}

// The failure screen index.html paints: whether it is up, how much of the viewport it
// covers, what it says, whether it really is on top (not hidden behind the canvas) and
// whether it is legible — light text on an opaque dark background at a readable size.
async function overlayState(page) {
  return page.evaluate(() => {
    const element = document.getElementById('viewer-overlay');
    if (!element) return null;
    const style = getComputedStyle(element);
    const rect = element.getBoundingClientRect();
    const rgba = (color) => {
      const parts = (String(color).match(/[\d.]+/g) || []).map(Number);
      return {
        luminance: 0.2126 * parts[0] + 0.7152 * parts[1] + 0.0722 * parts[2],
        alpha: parts.length > 3 ? parts[3] : 1,
      };
    };
    const centre = document.elementFromPoint(Math.round(window.innerWidth / 2), Math.round(window.innerHeight / 2));
    return {
      visible: style.display !== 'none' && style.visibility !== 'hidden' && rect.width > 0 && rect.height > 0,
      coverage: (rect.width * rect.height) / (window.innerWidth * window.innerHeight),
      text: element.innerText.replace(/\s+/g, ' ').trim(),
      background: rgba(style.backgroundColor),
      foreground: rgba(style.color),
      fontSize: parseFloat(style.fontSize),
      onTop: Boolean(centre && (centre === element || element.contains(centre))),
    };
  });
}

async function checkFailureScreen(page, label, pattern) {
  const overlay = await overlayState(page);
  if (!overlay) {
    check(false, `${label}: a message is painted on the page`);
    return;
  }
  check(
    overlay.visible && overlay.onTop && overlay.coverage > 0.99,
    `${label}: message covers the page (${(overlay.coverage * 100).toFixed(0)}%, on top: ${overlay.onTop})`,
  );
  check(pattern.test(overlay.text), `${label}: message names the failure "${overlay.text.slice(0, 120)}"`);
  check(
    overlay.background.alpha === 1 && overlay.background.luminance < 60 && overlay.foreground.luminance > 120 && overlay.fontSize >= 12,
    `${label}: message is readable (opaque background ${overlay.background.luminance.toFixed(0)}, text ${overlay.foreground.luminance.toFixed(0)}, ${overlay.fontSize}px)`,
  );
}

// Resizes the viewport (a phone rotation) and waits for the viewer's resize handling.
async function setViewport(page, size) {
  await page.setViewportSize(size);
  await page.waitForFunction(
    ({ width, height }) => window.innerWidth === width && window.innerHeight === height && document.querySelector('canvas').width === width,
    size,
  );
  await settle(page);
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
  checkFramed(signature, label);
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

  // Picking the (lifted) black box highlights it visibly. Top view with the curve and the
  // point hidden: the first grey pixel in raster order is the black box's top face.
  await page.evaluate(() => {
    window.viewer.setCurvesVisible(false);
    window.viewer.setPointsVisible(false);
    window.viewer.setView('top');
    window.viewer.setGrid(false);
  });
  await captureFrame(page, 'plain');
  const corner = await findPixel(page, 'grey');
  check(corner !== null, `black_layer.3dm: grey pixel found at ${JSON.stringify(corner)}`);
  if (corner) {
    const tap = { x: corner.x + 12, y: corner.y + 12 };
    const hit = await pickAt(page, tap.x, tap.y, 'black_layer.3dm: pick');
    checkEqual(hit && hit.name, 'black_box', 'black_layer.3dm: picked object');
    // Two 100-unit boxes fill the width here, so the box is ~250px wide.
    await checkHighlight(page, 'black', tap.x, tap.y, 320, 'black_layer.3dm: pick black box: highlight visible');
    await page.screenshot({ path: path.join(outDir, 'black_layer_picked.png') });
    await pickAt(page, 4, 4, 'black_layer.3dm: clear pick');
  }
  await page.evaluate(() => {
    window.viewer.setGrid(true);
    window.viewer.setCurvesVisible(true);
    window.viewer.setPointsVisible(true);
    window.viewer.setView('iso');
  });
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
    checkFramed(signature, `view ${view}`);
    hashes.add(signature.hash);
    if (view === 'top') await page.screenshot({ path: path.join(outDir, 'meshes_top.png') });
  }
  checkEqual(hashes.size, 7, 'views: seven distinct frames');
  const perspective = await modelSignature(page);
  await page.evaluate(() => window.viewer.setProjection('ortho'));
  const ortho = await modelSignature(page);
  check(ortho.drawn / ortho.total > BLANK_THRESHOLD && ortho.hash !== perspective.hash, `projection ortho: ${ortho.drawn} pixels drawn, differs from perspective`);
  checkFramed(ortho, 'projection ortho (framing kept)');
  await page.evaluate(() => window.viewer.setProjection('perspective'));
  const back = await modelSignature(page);
  check(Math.abs(back.drawn - perspective.drawn) / perspective.drawn < 0.05, `projection perspective restored: ${perspective.drawn} → ${back.drawn} pixels`);

  // fit() frames the ortho camera too.
  await page.evaluate(() => window.viewer.setProjection('ortho'));
  for (const view of ['top', 'iso']) {
    await page.evaluate((v) => window.viewer.setView(v), view);
    checkFramed(await modelSignature(page), `ortho fit (${view} view)`);
    if (view === 'top') await page.screenshot({ path: path.join(outDir, 'meshes_top_ortho.png') });
  }
  await page.evaluate(() => window.viewer.setProjection('perspective'));
  await page.evaluate(() => window.viewer.fit());
}

// A phone rotation resizes the page: the fitted model must be re-framed for the new
// aspect (not cropped at the sides) in both projections, and rotating back restores the
// original framing.
async function testResize(page) {
  await page.evaluate(() => window.viewer.setView('top'));
  const landscape = await modelSignature(page);
  checkFramed(landscape, 'resize: landscape top view');
  await setViewport(page, PORTRAIT);
  checkFramed(await modelSignature(page), 'resize: portrait after rotation');
  await page.screenshot({ path: path.join(outDir, 'meshes_top_portrait.png') });
  await setViewport(page, LANDSCAPE);
  const back = await modelSignature(page);
  const b = back.bounds;
  const l = landscape.bounds;
  check(
    [b.minX - l.minX, b.maxX - l.maxX, b.minY - l.minY, b.maxY - l.maxY].every((d) => Math.abs(d) <= 2),
    `resize: landscape framing restored x[${b.minX},${b.maxX}] y[${b.minY},${b.maxY}] (was x[${l.minX},${l.maxX}] y[${l.minY},${l.maxY}])`,
  );

  await page.evaluate(() => window.viewer.setProjection('ortho'));
  await setViewport(page, PORTRAIT);
  checkFramed(await modelSignature(page), 'resize: portrait ortho after rotation');
  await setViewport(page, LANDSCAPE);
  checkFramed(await modelSignature(page), 'resize: landscape ortho after rotating back');
  await page.evaluate(() => window.viewer.setProjection('perspective'));
}

// Taps at a page position and returns the single objectPicked payload (or undefined).
async function pickAt(page, x, y, label) {
  const from = await eventCount(page);
  await page.mouse.click(x, y);
  const events = (await eventsSince(page, from)).filter((e) => e.name === 'objectPicked');
  checkEqual(events.length, 1, `${label}: one objectPicked event`);
  return events[0] ? events[0].payload : undefined;
}

// A highlight must be unmistakable whatever the object's colour: compared with the
// 'plain' frame, at least PICK_MIN_CHANGED pixels change visibly, all within `reach`
// pixels of the tap (so a previous highlight elsewhere must be gone).
async function checkHighlight(page, key, x, y, reach, label) {
  await captureFrame(page, key);
  const diff = await frameDiff(page, 'plain', key, PICK_MIN_DIFF);
  const b = diff.bounds;
  const local = diff.changed > 0 && b.minX >= x - reach && b.maxX <= x + reach && b.minY >= y - reach && b.maxY <= y + reach;
  check(
    diff.changed >= PICK_MIN_CHANGED && local,
    `${label}: ${diff.changed} pixels changed by > ${PICK_MIN_DIFF}/765 (>= ${PICK_MIN_CHANGED}), within ${reach}px of the tap (x[${b.minX},${b.maxX}] y[${b.minY},${b.maxY}] around ${x},${y})`,
  );
}

async function testPicking(page) {
  const viewport = page.viewportSize();
  // Top view, grid off: the centre ray goes straight down through the yellow sphere
  // (its footprint covers the model centre), and the first white pixel in raster order is
  // the top face of the top-left FOAM box.
  await page.evaluate(() => window.viewer.setView('top'));
  await page.evaluate(() => window.viewer.setGrid(false));
  await captureFrame(page, 'plain');

  const centre = { x: viewport.width / 2, y: viewport.height / 2 };
  const hit = await pickAt(page, centre.x, centre.y, 'pick centre');
  check(hit && hit.name === 'sphere_ref', `pick centre: hit ${hit ? `${hit.objectType} "${hit.name}" on ${hit.layerName}` : 'nothing'}`);
  if (hit) {
    check(typeof hit.id === 'string' && hit.id.length > 0, 'pick: id is a guid string');
    check(Array.isArray(hit.size) && hit.size.length === 3 && hit.size.every((v) => v > 0), `pick: size ${JSON.stringify(hit.size)}`);
    check(Array.isArray(hit.center) && hit.center.length === 3, `pick: center ${JSON.stringify(hit.center)}`);
    check(typeof hit.userStrings === 'object' && hit.userStrings !== null, `pick: userStrings ${JSON.stringify(hit.userStrings)}`);
    check(typeof hit.layerIndex === 'number', `pick: layerIndex ${hit.layerIndex}`);
  }
  // The sphere (300 units) is drawn ~250px wide here; its highlight cage sits around it.
  await checkHighlight(page, 'sphere', centre.x, centre.y, 320, 'pick yellow sphere: highlight visible');
  await page.screenshot({ path: path.join(outDir, 'meshes_picked_sphere.png') });

  const corner = await findPixel(page, 'white');
  check(corner !== null, `pick box: white pixel found at ${JSON.stringify(corner)}`);
  const tap = corner ? { x: corner.x + 12, y: corner.y + 12 } : centre;
  const boxHit = await pickAt(page, tap.x, tap.y, 'pick box');
  check(boxHit && /^block_\d_\d$/.test(boxHit.name) && boxHit.layerName === 'FOAM', `pick box: hit ${boxHit ? `"${boxHit.name}" on ${boxHit.layerName}` : 'nothing'}`);
  if (boxHit) {
    check(boxHit.userStrings.PART_ID === boxHit.name.replace('block_', 'P').replace('_', ''), `pick box: userStrings ${JSON.stringify(boxHit.userStrings)}`);
    check(boxHit.size.every((v) => Math.abs(v - 100) < 1e-6), `pick box: size ${JSON.stringify(boxHit.size)}`);
  }
  // Only the ~85px box may differ from the plain frame: the sphere's highlight is gone.
  await checkHighlight(page, 'box', tap.x, tap.y, 140, 'pick white box: highlight visible, sphere highlight cleared');
  await page.screenshot({ path: path.join(outDir, 'meshes_picked.png') });

  const cleared = await pickAt(page, 4, 4, 'pick empty corner');
  check(cleared === null, 'pick empty corner: objectPicked null');
  await captureFrame(page, 'cleared');
  const restored = await frameDiff(page, 'plain', 'cleared', 0);
  checkEqual(restored.changed, 0, 'pick cleared: frame restored (changed pixels)');
  await page.evaluate(() => window.viewer.setGrid(true));
}

// Taps just inside the top-left corner of the first box drawn in the layer colour
// (top view, grid off) and returns the objectPicked payload.
async function pickFirstBox(page, colorClass, label) {
  await page.evaluate(() => {
    window.viewer.setView('top');
    window.viewer.setGrid(false);
  });
  await settle(page);
  const corner = await findPixel(page, colorClass);
  check(corner !== null, `${label}: ${colorClass} pixel found at ${JSON.stringify(corner)}`);
  if (!corner) return undefined;
  return pickAt(page, corner.x + 10, corner.y + 10, label);
}

// Tapping block content reports the top-level instance (name, layer, user strings), not
// the anonymous definition member.
async function testPickingBlocks(page) {
  await loadModel(page, { url: '/backend/test/fixtures/blocks.3dm', name: 'blocks.3dm' });
  const hit = await pickFirstBox(page, 'purple', 'pick block');
  check(hit && /^ref_\d$/.test(hit.name), `pick block: hit ${hit ? `${hit.objectType} "${hit.name}" on ${hit.layerName}` : 'nothing'}`);
  if (hit) {
    checkEqual(hit.objectType, 'InstanceReference', 'pick block: objectType');
    checkEqual(hit.blockName, 'unit_box', 'pick block: blockName');
    checkEqual(hit.layerName, 'BLOCKS', 'pick block: layerName');
    check(hit.size.every((v) => Math.abs(v - 50) < 1e-6), `pick block: size ${JSON.stringify(hit.size)}`);
  }

  await loadModel(page, { url: '/app/tool/viewer_test/fixtures/nested_blocks.3dm', name: 'nested_blocks.3dm' });
  const nested = await pickFirstBox(page, 'purple', 'pick nested block');
  check(nested && /^(outer_ref_\d|inner_ref)$/.test(nested.name), `pick nested block: hit ${nested ? `${nested.objectType} "${nested.name}" (block ${nested.blockName})` : 'nothing'}`);
  if (nested && nested.name.startsWith('outer_ref_')) {
    checkEqual(nested.blockName, 'outer', 'pick nested block: top-level instance, not the nested one');
    checkEqual(nested.userStrings.PART_ID, nested.name.replace('outer_ref_', 'OUTER'), `pick nested block: userStrings ${JSON.stringify(nested.userStrings)}`);
  }
  await page.evaluate(() => window.viewer.setGrid(true));
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
  checkEqual(await page.evaluate(() => window.viewer.diagnostics().model), null, 'clear: diagnostics model is null');
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
  await checkFailureScreen(page, 'init failure', /rhino3dm/i);
  const result = await loadModel(page, { url: '/backend/test/fixtures/meshes.3dm', name: 'meshes.3dm' }, false);
  check(result.ok === false && /rhino3dm failed to initialise/.test(result.error), `init failure: load() fails instead of hanging (${result.error})`);
  checkEqual(pageErrors.length, 0, `init failure: uncaught page errors ${JSON.stringify(pageErrors)}`);
  await context.close();
}


// ---------------------------------------------------------------------------------------
// Hostile WebView: nothing may fail silently
// ---------------------------------------------------------------------------------------

const STARTUP_FAILURES = [
  {
    label: 'no WebGL',
    file: 'fail_no_webgl.png',
    // Every WebGL context request refused, as on a WebView with no usable GPU path.
    install: (page) => page.addInitScript(() => {
      const getContext = HTMLCanvasElement.prototype.getContext;
      HTMLCanvasElement.prototype.getContext = function (type, attributes) {
        return /^(webgl|experimental-webgl)/.test(String(type)) ? null : getContext.call(this, type, attributes);
      };
    }),
    pattern: /WebGL/i,
    extra: (diagnostics) => check(
      diagnostics.webgl.webgl1 === false && diagnostics.webgl.webgl2 === false,
      `no WebGL: diagnostics report no WebGL (webgl1 ${diagnostics.webgl.webgl1}, webgl2 ${diagnostics.webgl.webgl2})`,
    ),
  },
  {
    label: 'module script missing',
    file: 'fail_no_module.png',
    install: (page) => page.route('**/viewer.js', (route) => route.abort()),
    pattern: /viewer\.js|could not (start|load)/i,
  },
  {
    label: 'import map target missing',
    file: 'fail_no_three.png',
    install: (page) => page.route('**/vendor/three/three.module.js', (route) => route.abort()),
    pattern: /three\.module\.js|could not (start|load)/i,
  },
];

// A page that cannot start must say so on screen and to the app, and must still answer
// viewer calls instead of leaving the app waiting for an event that can never arrive.
async function testStartupFailure(browser, port, scenario) {
  const context = await browser.newContext({ viewport: PORTRAIT, deviceScaleFactor: 1 });
  const page = await context.newPage();
  page.setDefaultTimeout(120000);
  const pageErrors = [];
  page.on('pageerror', (error) => pageErrors.push(error.message));
  await scenario.install(page);
  await page.goto(`http://127.0.0.1:${port}${VIEWER_PATH}`);
  await page.waitForFunction(() => (window.__viewerEvents || []).some((e) => e.name === 'log' && e.payload.level === 'error'));
  const events = await page.evaluate(() => window.__viewerEvents);
  const logged = events.find((e) => e.name === 'log' && e.payload.level === 'error').payload.message;
  check(scenario.pattern.test(logged), `${scenario.label}: log error "${logged}"`);
  check(!events.some((e) => e.name === 'viewerReady'), `${scenario.label}: viewerReady not emitted`);
  await checkFailureScreen(page, scenario.label, scenario.pattern);

  const from = await eventCount(page);
  await page.evaluate(() => window.viewer.load({ url: '/backend/test/fixtures/meshes.3dm', name: 'meshes.3dm' }));
  const result = (await eventsSince(page, from)).find((e) => e.name === 'loadResult');
  check(
    result && result.payload.ok === false && typeof result.payload.error === 'string' && result.payload.error.length > 10,
    `${scenario.label}: load() answers (${result ? JSON.stringify(result.payload.error) : 'no loadResult'})`,
  );
  const diagnostics = await page.evaluate(() => window.viewer.diagnostics());
  check(
    diagnostics.boot.booted === false && diagnostics.boot.failure !== null,
    `${scenario.label}: diagnostics carry the failure (${JSON.stringify(diagnostics.boot.failure && diagnostics.boot.failure.title)})`,
  );
  if (scenario.extra) scenario.extra(diagnostics);
  checkEqual(pageErrors.length, 0, `${scenario.label}: uncaught page errors ${JSON.stringify(pageErrors)}`);
  await page.screenshot({ path: path.join(outDir, scenario.file) });
  await context.close();
}

// A lost context is exactly the phone symptom that started this: a frozen canvas that
// still looks like a working app. It must be announced, and the page must come back.
async function testContextLoss(browser, port) {
  const context = await browser.newContext({ viewport: LANDSCAPE, deviceScaleFactor: 1 });
  const page = await context.newPage();
  page.setDefaultTimeout(120000);
  const pageErrors = [];
  page.on('pageerror', (error) => pageErrors.push(error.message));
  await page.goto(`http://127.0.0.1:${port}${VIEWER_PATH}`);
  await page.waitForFunction(() => (window.__viewerEvents || []).some((e) => e.name === 'viewerReady'));
  await loadModel(page, { url: '/backend/test/fixtures/meshes.3dm', name: 'meshes.3dm' });
  const before = await frameSignature(page);

  const from = await eventCount(page);
  const lost = await page.evaluate(() => {
    const gl = document.querySelector('canvas').getContext('webgl2');
    const extension = gl && gl.getExtension('WEBGL_lose_context');
    if (!extension) return false;
    window.__loseContext = extension;
    extension.loseContext();
    return true;
  });
  check(lost, 'context loss: WEBGL_lose_context available');
  if (!lost) {
    await context.close();
    return;
  }
  await page.waitForFunction(
    (start) => window.__viewerEvents.slice(start).some((e) => e.name === 'log' && e.payload.level === 'error' && /context lost/i.test(e.payload.message)),
    from,
  );
  const logged = (await eventsSince(page, from)).find((e) => e.name === 'log' && e.payload.level === 'error');
  check(Boolean(logged), `context loss: log error "${logged ? logged.payload.message : 'none'}"`);
  await checkFailureScreen(page, 'context loss', /interrupted|graphics context/i);
  await page.screenshot({ path: path.join(outDir, 'fail_context_lost.png') });

  // Switching the view while the context is lost draws nothing (three.js skips rendering);
  // if the frame after the restore shows the new view, it really was drawn again rather
  // than left over in the preserved drawing buffer.
  const restoredFrom = await eventCount(page);
  await page.evaluate(() => window.viewer.setView('top'));
  await page.evaluate(() => window.__loseContext.restoreContext());
  await page.waitForFunction(
    (start) => window.__viewerEvents.slice(start).some((e) => e.name === 'log' && /context restored/i.test(e.payload.message)),
    restoredFrom,
  );
  await settle(page);
  const after = await frameSignature(page);
  check(
    after.drawn / after.total > BLANK_THRESHOLD && after.hash !== before.hash,
    `context restored: ${after.drawn} pixels drawn again in the new view (was ${before.drawn} in the old one)`,
  );
  const overlay = await overlayState(page);
  check(overlay !== null && !overlay.visible, `context restored: message cleared (${overlay ? 'hidden' : 'no message element'})`);
  checkEqual(pageErrors.length, 0, `context loss: uncaught page errors ${JSON.stringify(pageErrors)}`);
  await context.close();
}

// A WebView that reports window.innerWidth/innerHeight as 0 (the platform view is measured
// after the page loads) must still size its canvas and draw, not sit at 0x0 forever.
async function testZeroViewport(browser, port) {
  const context = await browser.newContext({ viewport: PORTRAIT, deviceScaleFactor: 1 });
  const page = await context.newPage();
  page.setDefaultTimeout(120000);
  const pageErrors = [];
  page.on('pageerror', (error) => pageErrors.push(error.message));
  await page.addInitScript(() => {
    Object.defineProperty(window, 'innerWidth', { configurable: true, get: () => 0 });
    Object.defineProperty(window, 'innerHeight', { configurable: true, get: () => 0 });
  });
  await page.goto(`http://127.0.0.1:${port}${VIEWER_PATH}`);
  await page.waitForFunction(() => (window.__viewerEvents || []).some((e) => e.name === 'viewerReady'));
  await loadModel(page, { url: '/backend/test/fixtures/meshes.3dm', name: 'meshes.3dm' });
  const signature = await modelSignature(page);
  check(
    signature.width === PORTRAIT.width && signature.height === PORTRAIT.height,
    `zero innerWidth: canvas is ${signature.width}x${signature.height} (expected ${PORTRAIT.width}x${PORTRAIT.height})`,
  );
  check(signature.drawn / signature.total > BLANK_THRESHOLD, `zero innerWidth: ${signature.drawn} pixels drawn`);
  checkFramed(signature, 'zero innerWidth');
  checkEqual(pageErrors.length, 0, `zero innerWidth: uncaught page errors ${JSON.stringify(pageErrors)}`);
  await context.close();
}

// viewer.diagnostics(): the documented shape, JSON-serialisable, cheap and never throwing.
async function testDiagnostics(page, expected) {
  const diagnostics = await page.evaluate(() => window.viewer.diagnostics());
  check(typeof diagnostics.userAgent === 'string' && /Chrome/.test(diagnostics.userAgent), `diagnostics: userAgent ${JSON.stringify(diagnostics.userAgent)}`);
  checkEqual(diagnostics.three, 'r186', 'diagnostics: three');
  checkEqual(diagnostics.rhino3dm.version, '8.32.2', 'diagnostics: rhino3dm version');
  checkEqual(diagnostics.rhino3dm.worker, 'ready', 'diagnostics: rhino3dm worker');
  check(diagnostics.webgl.webgl1 === true && diagnostics.webgl.webgl2 === true, `diagnostics: webgl1 ${diagnostics.webgl.webgl1}, webgl2 ${diagnostics.webgl.webgl2}`);
  check(
    typeof diagnostics.webgl.renderer === 'string' && diagnostics.webgl.renderer.length > 0,
    `diagnostics: renderer ${JSON.stringify(diagnostics.webgl.renderer)} (unmasked ${diagnostics.webgl.unmasked})`,
  );
  check(typeof diagnostics.webgl.maxTextureSize === 'number' && diagnostics.webgl.maxTextureSize > 0, `diagnostics: maxTextureSize ${diagnostics.webgl.maxTextureSize}`);
  checkEqual(diagnostics.webgl.contextLost, false, 'diagnostics: contextLost');
  checkEqual(diagnostics.devicePixelRatio, 1, 'diagnostics: devicePixelRatio');
  check(
    diagnostics.canvas.width === LANDSCAPE.width && diagnostics.canvas.height === LANDSCAPE.height && diagnostics.canvas.pixelRatio === 1,
    `diagnostics: canvas ${JSON.stringify(diagnostics.canvas)}`,
  );
  check(
    diagnostics.boot.started === true && diagnostics.boot.booted === true && diagnostics.boot.failure === null,
    `diagnostics: boot ${JSON.stringify(diagnostics.boot)}`,
  );
  check(
    Array.isArray(diagnostics.logs) && diagnostics.logs.length <= 30
      && diagnostics.logs.every((e) => typeof e.level === 'string' && typeof e.message === 'string' && typeof e.t === 'number'),
    `diagnostics: logs ${JSON.stringify(diagnostics.logs.length)} entries (<= 30)`,
  );
  check(
    diagnostics.model && diagnostics.model.objects === expected.objects && diagnostics.model.triangles === expected.triangles
      && diagnostics.model.units === expected.units && diagnostics.model.layers === expected.layers.length,
    `diagnostics: model ${JSON.stringify(diagnostics.model)}`,
  );
  check(JSON.stringify(diagnostics).length > 200, 'diagnostics: JSON-serialisable');
  // Cheap: repeated calls must not pile up canvases or leak WebGL contexts.
  const canvases = await page.evaluate(() => {
    for (let i = 0; i < 5; i++) window.viewer.diagnostics();
    return document.querySelectorAll('canvas').length;
  });
  checkEqual(canvases, 1, 'diagnostics: no canvas left behind');
}

// The page paints its own opaque dark background: when the canvas draws nothing the user
// must still see the viewer's background, never the bare host view behind it.
async function testOpaqueBackground(page) {
  const background = await page.evaluate(() => {
    const parse = (color) => (String(color).match(/[\d.]+/g) || []).map(Number);
    const backdrop = document.getElementById('viewer-backdrop');
    const canvas = document.querySelector('canvas');
    const rect = backdrop.getBoundingClientRect();
    return {
      covers: rect.width >= window.innerWidth && rect.height >= window.innerHeight,
      backdrop: parse(getComputedStyle(backdrop).backgroundColor),
      body: parse(getComputedStyle(document.body).backgroundColor),
      canvasOnTop: document.elementFromPoint(Math.round(window.innerWidth / 2), Math.round(window.innerHeight / 2)) === canvas,
      canvasAfterBackdrop: (backdrop.compareDocumentPosition(canvas) & Node.DOCUMENT_POSITION_FOLLOWING) !== 0,
    };
  });
  const opaqueDark = (color) => color.length >= 3 && (color.length < 4 || color[3] === 1)
    && 0.2126 * color[0] + 0.7152 * color[1] + 0.0722 * color[2] < 60;
  check(background.covers && opaqueDark(background.backdrop), `background: backdrop ${JSON.stringify(background.backdrop)} covers the page`);
  check(opaqueDark(background.body), `background: body ${JSON.stringify(background.body)}`);
  check(background.canvasOnTop && background.canvasAfterBackdrop, 'background: the canvas draws over the backdrop');
}

// A drawn model is not a blank page: an error while one is on screen is reported, but the
// failure screen must not take the working view away from the user (the app shows the `log`
// error over it instead). Leaves the page with nothing loaded, as it found it.
async function testErrorOverModel(page) {
  await loadModel(page, { url: '/backend/test/fixtures/meshes.3dm', name: 'meshes.3dm' });
  await settle(page);
  const before = await frameSignature(page);
  const from = await eventCount(page);
  await page.evaluate(() => { setTimeout(() => { throw new Error('synthetic error over a model'); }, 0); });
  await page.waitForFunction(
    (start) => window.__viewerEvents.slice(start).some(
      (e) => e.name === 'log' && e.payload.level === 'error' && e.payload.message.includes('synthetic error over a model'),
    ),
    from,
  );
  await settle(page);
  const overlay = await overlayState(page);
  check(!overlay || !overlay.visible, `error over a model: not painted over (${overlay ? overlay.text.slice(0, 40) : 'no overlay'})`);
  const after = await frameSignature(page);
  check(after.drawn === before.drawn && after.hash === before.hash, `error over a model: model still drawn (${after.drawn} px)`);
  check(
    (await page.evaluate(() => window.viewer.diagnostics().boot.failure)) !== null,
    'error over a model: diagnostics still carry the failure',
  );
  await page.evaluate(() => window.viewer.clear());
}

// An uncaught error or an unhandled rejection anywhere on the page must paint and report,
// instead of leaving a viewer that looks fine while it is broken. Runs last on this page:
// it leaves the failure screen up.
async function testRuntimeErrors(page) {
  expectedErrorPattern = /synthetic/;
  await testErrorOverModel(page);
  const cases = [
    ['uncaught error', () => { setTimeout(() => { throw new Error('synthetic uncaught failure'); }, 0); }, 'synthetic uncaught failure'],
    ['unhandled rejection', () => { Promise.reject(new Error('synthetic rejected promise')); }, 'synthetic rejected promise'],
  ];
  for (const [label, trigger, needle] of cases) {
    const from = await eventCount(page);
    await page.evaluate(trigger);
    await page.waitForFunction(
      ([start, text]) => window.__viewerEvents.slice(start).some(
        (e) => e.name === 'log' && e.payload.level === 'error' && e.payload.message.includes(text),
      ),
      [from, needle],
    );
    const overlay = await overlayState(page);
    check(
      overlay && overlay.visible && overlay.text.includes(needle),
      `${label}: reported and painted "${overlay ? overlay.text.slice(0, 90) : 'nothing'}"`,
    );
  }
  expectedErrorPattern = null;
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
    const context = await browser.newContext({ viewport: LANDSCAPE, deviceScaleFactor: 1 });
    const page = await context.newPage();
    page.setDefaultTimeout(120000);
    await installImageLoadCounter(page);
    page.on('pageerror', (error) => {
      if (expectedErrorPattern && expectedErrorPattern.test(error.message)) return;
      check(false, `page error: ${error.message}`);
    });
    page.on('console', (message) => {
      const text = message.text();
      if (text.startsWith('[viewer-event]')) {
        if (process.env.VERBOSE) console.log('  ' + text);
      } else if (message.type() === 'error'
        && !(expectResourceError && text.startsWith('Failed to load resource'))
        && !(expectedErrorPattern && expectedErrorPattern.test(text))) {
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
      await testDiagnostics(page, meshesStats);
      await testOpaqueBackground(page);
      await testExport(page);
      await testLayerToggle(page, meshesStats);
      await testCurvesAndPoints(page);
      await testDisplayModes(page);
      await testViewsAndProjection(page);
      await testResize(page);
      await testPicking(page);
      console.log('\n== picking (blocks.3dm, nested_blocks.3dm)');
      await testPickingBlocks(page);
      console.log('\n== base64 / errors / clear');
      await testBase64Load(page);
      await testBadLoad(page);
      await testCorruptLoad(page);
      await testClear(page);
      console.log('\n== runtime errors');
      await testRuntimeErrors(page);
    }
    console.log('\n== worker initialisation failure');
    await testInitFailure(browser, port);
    console.log('\n== hostile WebView');
    for (const scenario of STARTUP_FAILURES) await testStartupFailure(browser, port, scenario);
    await testContextLoss(browser, port);
    await testZeroViewport(browser, port);
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
