import * as THREE from 'three';
import { OrbitControls } from 'three/addons/controls/OrbitControls.js';
import { Rhino3dmLoader } from 'three/addons/loaders/3DMLoader.js';
import { GLTFExporter } from 'three/addons/exporters/GLTFExporter.js';

const RHINO3DM_VERSION = '8.32.2';
const HIGHLIGHT_COLOR = 0xFFB020;
const HIGHLIGHT_INTENSITY = 0.35;
const GHOSTED_OPACITY = 0.35;
const EDGE_ANGLE_DEG = 30;
const EDGE_BUILD_BUDGET_MS = 30;
const EDGE_MAX_TRIANGLES = 100000;
const DARK_LUMINANCE = 0.12;
const DARK_LIFT_COLOR = 0x9AA1AA;
const GRID_DIVISIONS = 20;
const GRID_SCALE = 10;
const MAX_WARNINGS = 50;
const TAP_MAX_MOVE_PX = 6;
const TAP_MAX_MS = 300;
const VIEW_DIRECTIONS = {
  // Direction from the target towards the camera, Rhino conventions (Z up).
  // Axis views carry a tiny Y offset so "up" stays well defined when looking along Z.
  iso: [-1, -1, 0.8],
  top: [0, -1e-4, 1],
  bottom: [0, -1e-4, -1],
  front: [0, -1, 0],
  back: [0, 1, 0],
  right: [1, 0, 0],
  left: [-1, 0, 0],
};
const DISPLAY_MODES = ['shaded', 'shaded_edges', 'wireframe', 'ghosted'];
const MESH_TYPES = new Set(['Mesh', 'Brep', 'Extrusion', 'SubD']);

// ---------------------------------------------------------------------------------------
// Flutter bridge
// ---------------------------------------------------------------------------------------

function emit(name, payload) {
  const bridge = window.flutter_inappwebview;
  if (bridge && typeof bridge.callHandler === 'function') {
    bridge.callHandler(name, payload);
    return;
  }
  (window.__viewerEvents ||= []).push({ name, payload });
  // Keep the console line readable: a GLB payload can be tens of MB of base64.
  const logged = payload && typeof payload.base64 === 'string'
    ? { ...payload, base64: `<${payload.base64.length} chars>` }
    : payload;
  console.log('[viewer-event] ' + JSON.stringify({ name, payload: logged }));
}

function log(level, message) {
  emit('log', { level, message });
}

// ---------------------------------------------------------------------------------------
// Loader: stock loader minus file materials, plus full (nested) block-instance expansion
// ---------------------------------------------------------------------------------------

// buildScene() replaces every material with shared per-colour ones, so the stock loader's
// materials — and the decode of any embedded texture or render environment they carry,
// which the stock loader repeats for every object on the main thread — would be wasted.
const placeholderMaterial = new THREE.MeshStandardMaterial({ name: 'placeholder' });

class ViewerLoader extends Rhino3dmLoader {
  _createMaterial() {
    return placeholderMaterial;
  }

  // The stock loader expands block instances one level only: a reference that is itself a
  // definition member is dropped from its definition and drawn once, at the top level, with
  // just its local transform. Build definitions recursively instead, and keep each
  // reference's own attributes (layer, name, id, user strings) on its wrapper.
  _createGeometry(data) {
    const definitions = new Map();
    const members = new Map();
    const plain = [];
    for (const obj of data.objects) {
      if (obj.objectType === 'InstanceDefinition') definitions.set(obj.attributes.id, obj);
      else if (obj.attributes.isInstanceDefinitionObject) members.set(obj.attributes.id, obj);
      else if (obj.objectType !== 'InstanceReference') plain.push(obj);
    }
    const root = super._createGeometry({ ...data, objects: plain });

    const templates = new Map();
    const building = new Set();
    const buildDefinition = (id) => {
      if (templates.has(id)) return templates.get(id);
      const template = new THREE.Object3D();
      const definition = definitions.get(id);
      // An unknown definition, or one that (indirectly) contains itself, stays empty.
      if (!definition || building.has(id)) return template;
      building.add(id);
      for (const memberId of definition.attributes.objectIds || []) {
        const member = members.get(memberId);
        if (!member) continue;
        const child = member.objectType === 'InstanceReference' ? instantiate(member) : this._createObject(member, null);
        if (child && !child.isLight) template.add(child);
      }
      building.delete(id);
      templates.set(id, template);
      return template;
    };
    const instantiate = (ref) => {
      const wrapper = new THREE.Object3D();
      wrapper.applyMatrix4(new THREE.Matrix4().set(...ref.geometry.xform.array));
      wrapper.name = ref.attributes.name || '';
      wrapper.userData.objectType = 'InstanceReference';
      wrapper.userData.attributes = ref.attributes;
      const definition = definitions.get(ref.geometry.parentIdefId);
      wrapper.userData.blockName = definition ? definition.attributes.name || '' : '';
      for (const child of buildDefinition(ref.geometry.parentIdefId).children) wrapper.add(child.clone(true));
      return wrapper;
    };
    for (const obj of data.objects) {
      if (obj.objectType === 'InstanceReference' && !obj.attributes.isInstanceDefinitionObject) root.add(instantiate(obj));
    }
    return root;
  }
}

const loader = new ViewerLoader()
  .setLibraryPath('./vendor/rhino3dm/')
  .setWorkerLimit(1)
  .setSubdivisionLevel(2);

// ---------------------------------------------------------------------------------------
// Renderer, scene, cameras, controls
// ---------------------------------------------------------------------------------------

const renderer = new THREE.WebGLRenderer({ antialias: true, alpha: true, preserveDrawingBuffer: true });
renderer.setPixelRatio(Math.min(window.devicePixelRatio || 1, 2));
renderer.setSize(window.innerWidth, window.innerHeight);
renderer.setClearColor(0x000000, 0);
document.body.appendChild(renderer.domElement);
const canvas = renderer.domElement;

const scene = new THREE.Scene();

const persp = new THREE.PerspectiveCamera(40, aspect(), 1, 1000);
const ortho = new THREE.OrthographicCamera(-1, 1, 1, -1, 0, 1000);
persp.up.set(0, 0, 1);
ortho.up.set(0, 0, 1);
let camera = persp;
scene.add(persp, ortho);

const hemi = new THREE.HemisphereLight(0xffffff, 0x3a3f47, 1.6);
hemi.position.set(0, 0, 1);
scene.add(hemi);

// Camera-relative key + fill so surfaces read the same from every view angle.
const lightRig = new THREE.Group();
const keyLight = new THREE.DirectionalLight(0xffffff, 2.2);
keyLight.position.set(1, 1.2, 1.5);
keyLight.target.position.set(0, 0, -1);
const fillLight = new THREE.DirectionalLight(0xffffff, 0.9);
fillLight.position.set(-1.5, -0.5, 0.5);
fillLight.target.position.set(0, 0, -1);
lightRig.add(keyLight, keyLight.target, fillLight, fillLight.target);
camera.add(lightRig);

const model = new THREE.Group();
scene.add(model);

let grid = null;
let gridVisible = true;

let controls = null;
function createControls() {
  const previousTarget = controls ? controls.target.clone() : new THREE.Vector3();
  if (controls) controls.dispose();
  controls = new OrbitControls(camera, canvas);
  controls.enableDamping = false;
  controls.screenSpacePanning = true;
  controls.zoomToCursor = true;
  controls.touches = { ONE: THREE.TOUCH.ROTATE, TWO: THREE.TOUCH.DOLLY_PAN };
  controls.target.copy(previousTarget);
  controls.addEventListener('change', requestRender);
  controls.update();
}

function applyControlLimits(radius) {
  controls.minDistance = radius * 0.01;
  controls.maxDistance = radius * 100;
  controls.minZoom = 0.01;
  controls.maxZoom = 100;
}

function aspect() {
  return window.innerWidth / Math.max(1, window.innerHeight);
}

function setOrthoFrustum(halfHeight) {
  ortho.top = halfHeight;
  ortho.bottom = -halfHeight;
  ortho.right = halfHeight * aspect();
  ortho.left = -ortho.right;
  ortho.updateProjectionMatrix();
}

// ---------------------------------------------------------------------------------------
// Render on demand
// ---------------------------------------------------------------------------------------

let renderQueued = false;
let modelCenter = new THREE.Vector3();
let modelRadius = 1;
let gridRadius = 0;

function requestRender() {
  if (renderQueued) return;
  renderQueued = true;
  requestAnimationFrame(renderFrame);
}

function renderFrame() {
  renderQueued = false;
  updateClipPlanes();
  renderer.render(scene, camera);
}

function updateClipPlanes() {
  // Everything drawable lies inside a sphere around the model centre; the grid may be
  // wider. Fit the planes to that sphere as seen from the orbit target.
  const reach = Math.max(modelRadius, gridRadius) + controls.target.distanceTo(modelCenter);
  const dist = camera.position.distanceTo(controls.target);
  if (camera.isPerspectiveCamera) {
    camera.near = Math.max(dist - reach, modelRadius * 2e-3);
    camera.far = Math.max(dist + reach, camera.near * 10);
  } else {
    camera.near = Math.max(dist - reach, 0);
    camera.far = Math.max(dist + reach, camera.near + modelRadius);
  }
  camera.updateProjectionMatrix();
}

window.addEventListener('resize', () => {
  renderer.setSize(window.innerWidth, window.innerHeight);
  persp.aspect = aspect();
  persp.updateProjectionMatrix();
  setOrthoFrustum(ortho.top);
  requestRender();
});

canvas.addEventListener('webglcontextlost', (event) => {
  event.preventDefault();
  log('error', 'WebGL context lost');
});
canvas.addEventListener('webglcontextrestored', () => {
  log('info', 'WebGL context restored');
  requestRender();
});

// ---------------------------------------------------------------------------------------
// Materials (per colour, shared) and display modes
// ---------------------------------------------------------------------------------------

const meshMaterials = new Map();
const lineMaterials = new Map();
const pointMaterials = new Map();
const edgeMaterial = new THREE.LineBasicMaterial({ color: 0x8B93A1 });
const edgeGeometries = new Map();
const darkLiftHsl = new THREE.Color(DARK_LIFT_COLOR).getHSL({}, THREE.SRGBColorSpace);
let displayMode = 'shaded';
let edgeJob = null;

function colorToHex(color) {
  return ((color.r & 255) << 16) | ((color.g & 255) << 8) | (color.b & 255);
}

function hexString(hex) {
  return '#' + hex.toString(16).padStart(6, '0').toUpperCase();
}

// The colour the file assigns to an object; reported in stats and used for the GLB export.
function objectColorHex(attributes, layers) {
  const source = attributes.colorSource && attributes.colorSource.name;
  if (source === 'ObjectColorSource_ColorFromObject' && attributes.objectColor) {
    return colorToHex(attributes.objectColor);
  }
  const layer = layers[attributes.layerIndex];
  if (layer && layer.color) return colorToHex(layer.color);
  return attributes.drawColor ? colorToHex(attributes.drawColor) : 0xffffff;
}

// The colour actually drawn. Rhino's default layer colour is black, and a black albedo gets
// no diffuse light, so such objects would be silhouettes against the dark background. Lift
// near-black colours towards a light grey, the more the darker they are; a colour that
// carries a hue keeps it (dark red reads as muted red, not grey).
function displayColorHex(hex) {
  const color = new THREE.Color(hex);
  const luminance = 0.2126 * color.r + 0.7152 * color.g + 0.0722 * color.b;
  if (luminance >= DARK_LUMINANCE) return hex;
  const t = 1 - luminance / DARK_LUMINANCE;
  const hsl = color.getHSL({}, THREE.SRGBColorSpace);
  const hued = hsl.s > 0.25;
  return color.setHSL(
    hued ? hsl.h : darkLiftHsl.h,
    THREE.MathUtils.lerp(hsl.s, hued ? hsl.s * 0.5 : darkLiftHsl.s, t),
    THREE.MathUtils.lerp(hsl.l, darkLiftHsl.l, t),
    THREE.SRGBColorSpace,
  ).getHex();
}

function meshMaterialFor(hex) {
  let material = meshMaterials.get(hex);
  if (!material) {
    material = new THREE.MeshStandardMaterial({
      color: hex,
      roughness: 0.65,
      metalness: 0,
      side: THREE.DoubleSide,
    });
    applyModeToMaterial(material, displayMode);
    meshMaterials.set(hex, material);
  }
  return material;
}

function lineMaterialFor(hex) {
  let material = lineMaterials.get(hex);
  if (!material) {
    material = new THREE.LineBasicMaterial({ color: hex });
    lineMaterials.set(hex, material);
  }
  return material;
}

function pointMaterialFor(hex, vertexColors) {
  const key = vertexColors ? 'vc' : hex;
  let material = pointMaterials.get(key);
  if (!material) {
    material = new THREE.PointsMaterial({
      color: vertexColors ? 0xffffff : hex,
      vertexColors,
      size: 6,
      sizeAttenuation: false,
    });
    pointMaterials.set(key, material);
  }
  return material;
}

function applyModeToMaterial(material, mode) {
  const ghosted = mode === 'ghosted';
  material.wireframe = mode === 'wireframe';
  material.transparent = ghosted;
  material.opacity = ghosted ? GHOSTED_OPACITY : 1;
  material.depthWrite = !ghosted;
  material.needsUpdate = true;
}

function edgesFor(mesh) {
  let edges = mesh.children.find((child) => child.userData.viewerEdges);
  if (edges) return edges;
  let geometry = edgeGeometries.get(mesh.geometry);
  if (!geometry) {
    geometry = new THREE.EdgesGeometry(mesh.geometry, EDGE_ANGLE_DEG);
    edgeGeometries.set(mesh.geometry, geometry);
  }
  edges = new THREE.LineSegments(geometry, edgeMaterial);
  edges.userData.viewerEdges = true;
  edges.raycast = () => {};
  mesh.add(edges);
  return edges;
}

function meshTriangles(mesh) {
  const position = mesh.geometry.getAttribute('position');
  if (!position) return 0;
  return Math.floor((mesh.geometry.index ? mesh.geometry.index.count : position.count) / 3);
}

// EdgesGeometry is O(triangles) on the main thread, so edges are built in time-boxed
// slices: the first one now, the rest between frames, visible meshes first. A mesh above
// EDGE_MAX_TRIANGLES keeps its shading only. Cancelled by setting edgeJob to null.
function buildEdges() {
  const pending = [];
  forEachMesh((mesh) => {
    if (mesh.userData.edgesSkipped || mesh.children.some((child) => child.userData.viewerEdges)) return;
    pending.push(mesh);
  });
  pending.sort((a, b) => Number(b.visible) - Number(a.visible));
  const job = { pending, next: 0, skipped: 0 };
  edgeJob = job;
  const step = () => {
    if (edgeJob !== job) return;
    const deadline = performance.now() + EDGE_BUILD_BUDGET_MS;
    while (job.next < job.pending.length && performance.now() < deadline) {
      const mesh = job.pending[job.next++];
      if (meshTriangles(mesh) > EDGE_MAX_TRIANGLES) {
        mesh.userData.edgesSkipped = true;
        job.skipped += 1;
      } else {
        edgesFor(mesh).visible = true;
      }
    }
    requestRender();
    if (job.next < job.pending.length) {
      requestAnimationFrame(step);
      return;
    }
    edgeJob = null;
    if (job.skipped) log('warn', `Edges skipped for ${job.skipped} mesh(es) above ${EDGE_MAX_TRIANGLES} triangles`);
  };
  step();
}

function applyDisplayMode() {
  for (const material of meshMaterials.values()) applyModeToMaterial(material, displayMode);
  if (picked) applyModeToMaterial(picked.mesh.material, displayMode);
  if (displayMode === 'shaded_edges') {
    buildEdges();
    return;
  }
  edgeJob = null;
  forEachMesh((mesh) => {
    const edges = mesh.children.find((child) => child.userData.viewerEdges);
    if (edges) edges.visible = false;
  });
}

function forEachMesh(fn) {
  model.traverse((obj) => {
    if (obj.isMesh && MESH_TYPES.has(obj.userData.objectType)) fn(obj);
  });
}

// ---------------------------------------------------------------------------------------
// Visibility (layers, curves, points)
// ---------------------------------------------------------------------------------------

let layerVisible = [];
let curvesVisible = true;
let pointsVisible = true;

function applyVisibility() {
  model.traverse((obj) => {
    const attributes = obj.userData.attributes;
    if (!attributes) return;
    const layerOk = layerVisible[attributes.layerIndex] !== false;
    // Objects hidden in Rhino (Hide command) stay hidden, as in the backend's /convert.
    const objectOk = attributes.visible !== false;
    let typeOk = true;
    if (obj.isLine) typeOk = curvesVisible;
    else if (obj.isPoints) typeOk = pointsVisible;
    obj.visible = layerOk && objectOk && typeOk;
  });
  requestRender();
}

// ---------------------------------------------------------------------------------------
// Bounds, grid, camera framing
// ---------------------------------------------------------------------------------------

const _box = new THREE.Box3();

function drawableBounds(visibleOnly) {
  const box = new THREE.Box3();
  model.updateMatrixWorld(true);
  const visit = (obj) => {
    if (!obj.geometry || obj.userData.viewerEdges || obj.isSprite) return;
    if (!obj.geometry.boundingBox) obj.geometry.computeBoundingBox();
    if (obj.geometry.boundingBox.isEmpty()) return;
    _box.copy(obj.geometry.boundingBox).applyMatrix4(obj.matrixWorld);
    box.union(_box);
  };
  if (visibleOnly) model.traverseVisible(visit);
  else model.traverse(visit);
  return box;
}

function rebuildGrid(box) {
  if (grid) {
    scene.remove(grid);
    grid.geometry.dispose();
    grid.material.dispose();
    grid = null;
  }
  if (box.isEmpty()) return;
  const size = box.getSize(new THREE.Vector3());
  const extent = Math.max(size.x, size.y, size.z, 1e-3) * GRID_SCALE;
  grid = new THREE.GridHelper(extent, GRID_DIVISIONS, 0x2A3038, 0x1F252C);
  grid.rotation.x = -Math.PI / 2;
  grid.position.set((box.min.x + box.max.x) / 2, (box.min.y + box.max.y) / 2, 0);
  grid.visible = gridVisible;
  gridRadius = extent * Math.SQRT1_2;
  scene.add(grid);
}

function viewDirection() {
  const dir = camera.position.clone().sub(controls.target);
  if (dir.lengthSq() < 1e-12) dir.fromArray(VIEW_DIRECTIONS.iso);
  return dir.normalize();
}

// Frames a sphere from the current view direction in both cameras, so switching
// projection afterwards keeps the same framing.
function frameSphere(center, radius) {
  const dir = viewDirection();
  const vfov = THREE.MathUtils.degToRad(persp.fov);
  const hfov = 2 * Math.atan(Math.tan(vfov / 2) * aspect());
  const dist = (radius / Math.sin(Math.min(vfov, hfov) / 2)) * 1.05;

  persp.position.copy(center).addScaledVector(dir, dist);
  ortho.position.copy(center).addScaledVector(dir, dist);
  ortho.zoom = 1;
  setOrthoFrustum(aspect() >= 1 ? radius * 1.05 : (radius * 1.05) / aspect());

  controls.target.copy(center);
  applyControlLimits(radius);
  controls.update();
  requestRender();
}

function fit() {
  const box = drawableBounds(true);
  if (box.isEmpty()) return;
  frameSphere(box.getCenter(new THREE.Vector3()), Math.max(box.getSize(new THREE.Vector3()).length() / 2, 1e-6));
}

function setView(name) {
  const dir = VIEW_DIRECTIONS[name];
  if (!dir) {
    log('warn', `Unknown view "${name}"`);
    return;
  }
  const dist = Math.max(camera.position.distanceTo(controls.target), modelRadius * 3);
  camera.position.copy(controls.target).addScaledVector(new THREE.Vector3().fromArray(dir).normalize(), dist);
  controls.update();
  fit();
}

function setProjection(projection) {
  if (projection !== 'ortho' && projection !== 'perspective') {
    log('warn', `Unknown projection "${projection}"`);
    return;
  }
  const wantOrtho = projection === 'ortho';
  if (wantOrtho === camera.isOrthographicCamera) return;
  const target = controls.target.clone();
  const dir = viewDirection();
  const halfFov = THREE.MathUtils.degToRad(persp.fov / 2);
  if (wantOrtho) {
    const dist = persp.position.distanceTo(target);
    ortho.position.copy(persp.position);
    ortho.zoom = 1;
    setOrthoFrustum(dist * Math.tan(halfFov));
    camera = ortho;
  } else {
    const halfHeight = ortho.top / ortho.zoom;
    persp.position.copy(target).addScaledVector(dir, halfHeight / Math.tan(halfFov));
    camera = persp;
  }
  camera.add(lightRig);
  createControls();
  applyControlLimits(modelRadius);
  requestRender();
}

// ---------------------------------------------------------------------------------------
// Picking
// ---------------------------------------------------------------------------------------

const raycaster = new THREE.Raycaster();
let picked = null;
let pointerDown = null;
let activePointers = 0;
let multiTouch = false;

canvas.addEventListener('pointerdown', (event) => {
  activePointers += 1;
  if (activePointers > 1) multiTouch = true;
  else {
    multiTouch = false;
    pointerDown = { x: event.clientX, y: event.clientY, t: performance.now() };
  }
});

function endPointer(event, allowPick) {
  activePointers = Math.max(0, activePointers - 1);
  const down = pointerDown;
  pointerDown = null;
  if (!allowPick || !down || multiTouch) return;
  const moved = Math.hypot(event.clientX - down.x, event.clientY - down.y);
  if (moved < TAP_MAX_MOVE_PX && performance.now() - down.t < TAP_MAX_MS) pickAt(event.clientX, event.clientY);
}

canvas.addEventListener('pointerup', (event) => endPointer(event, true));
canvas.addEventListener('pointercancel', (event) => endPointer(event, false));

function pickAt(clientX, clientY) {
  const rect = canvas.getBoundingClientRect();
  const ndc = new THREE.Vector2(
    ((clientX - rect.left) / rect.width) * 2 - 1,
    -((clientY - rect.top) / rect.height) * 2 + 1,
  );
  raycaster.setFromCamera(ndc, camera);
  const candidates = [];
  model.traverseVisible((obj) => {
    if (obj.isMesh && MESH_TYPES.has(obj.userData.objectType)) candidates.push(obj);
  });
  const hit = raycaster.intersectObjects(candidates, false)[0];
  setPicked(hit ? hit.object : null);
}

function setPicked(mesh) {
  if (picked) {
    picked.mesh.material.dispose();
    picked.mesh.material = picked.baseMaterial;
    picked = null;
  }
  if (mesh) {
    const highlight = mesh.material.clone();
    highlight.emissive.setHex(HIGHLIGHT_COLOR);
    highlight.emissiveIntensity = HIGHLIGHT_INTENSITY;
    picked = { mesh, baseMaterial: mesh.material };
    mesh.material = highlight;
  }
  requestRender();
  emit('objectPicked', mesh ? describeObject(mesh) : null);
}

// The top-level block instance containing a mesh, if any.
function instanceOf(mesh) {
  let instance = null;
  for (let obj = mesh.parent; obj && obj !== modelRoot; obj = obj.parent) {
    if (obj.userData.objectType === 'InstanceReference' && obj.userData.attributes) instance = obj;
  }
  return instance;
}

// Block content is reported as its top-level instance, as Rhino selects it: the reference
// carries the meaningful name, layer and user strings; the member's user strings fill gaps.
function describeObject(mesh) {
  const instance = instanceOf(mesh);
  const subject = instance || mesh;
  const attributes = subject.userData.attributes || {};
  const layers = currentLayers();
  const layer = layers[attributes.layerIndex];
  const box = new THREE.Box3().setFromObject(subject, true);
  const size = box.getSize(new THREE.Vector3());
  const center = box.getCenter(new THREE.Vector3());
  const userStrings = Object.fromEntries((mesh.userData.attributes || {}).userStrings || []);
  Object.assign(userStrings, Object.fromEntries(attributes.userStrings || []));
  return {
    id: attributes.id ?? null,
    name: attributes.name || '',
    objectType: instance ? 'InstanceReference' : mesh.userData.objectType,
    blockName: instance ? instance.userData.blockName || '' : '',
    layerIndex: attributes.layerIndex ?? -1,
    layerName: layer ? layer.name : '',
    userStrings,
    size: [size.x, size.y, size.z],
    center: [center.x, center.y, center.z],
  };
}

// ---------------------------------------------------------------------------------------
// Loading
// ---------------------------------------------------------------------------------------

let stats = null;
let loadSerial = 0;
let modelName = '';
let modelRoot = null;
let modelBounds = new THREE.Box3();

function currentLayers() {
  return modelRoot ? modelRoot.userData.layers || [] : [];
}

function emitProgress(phase, progress) {
  emit('loadProgress', { phase, progress: Math.max(0, Math.min(1, progress)) });
}

async function fetchBytes(url) {
  const response = await fetch(url, { cache: 'no-store' });
  if (!response.ok) throw new Error(`HTTP ${response.status} while fetching ${url}`);
  const total = Number(response.headers.get('Content-Length')) || 0;
  emitProgress('fetch', 0);
  if (!response.body || total === 0) {
    const buffer = await response.arrayBuffer();
    emitProgress('fetch', 1);
    return buffer;
  }
  const reader = response.body.getReader();
  const chunks = [];
  let received = 0;
  let lastReported = 0;
  for (;;) {
    const { done, value } = await reader.read();
    if (done) break;
    chunks.push(value);
    received += value.byteLength;
    const progress = received / total;
    if (progress - lastReported >= 0.02) {
      lastReported = progress;
      emitProgress('fetch', progress);
    }
  }
  const bytes = new Uint8Array(received);
  let offset = 0;
  for (const chunk of chunks) {
    bytes.set(chunk, offset);
    offset += chunk.byteLength;
  }
  emitProgress('fetch', 1);
  return bytes.buffer;
}

function decodeBase64(base64) {
  emitProgress('fetch', 0);
  const binary = atob(base64);
  const bytes = new Uint8Array(binary.length);
  for (let i = 0; i < binary.length; i++) bytes[i] = binary.charCodeAt(i);
  emitProgress('fetch', 1);
  return bytes.buffer;
}

function errorMessage(error) {
  if (error && error.error && error.error.message) return error.error.message;
  if (error && error.message) return error.message;
  return String(error);
}

async function load(options) {
  const { url, base64, name } = options || {};
  const displayName = name || (url ? url.split('/').pop() : 'model.3dm');
  const serial = ++loadSerial;
  const t0 = performance.now();
  const timings = {};
  clear();
  modelName = displayName;

  try {
    await workerReady;
    let buffer;
    if (url) buffer = await fetchBytes(url);
    else if (base64) buffer = decodeBase64(base64);
    else throw new Error('load() needs a url or base64');
    timings.fetchMs = Math.round(performance.now() - t0);

    emitProgress('parse', 0);
    const t1 = performance.now();
    loader.warnings = [];
    const root = await loader.parseAsync(buffer);
    timings.parseMs = Math.round(performance.now() - t1);
    emitProgress('parse', 1);

    if (serial !== loadSerial) {
      disposeObject(root);
      throw new Error('superseded by a newer load()');
    }

    emitProgress('build', 0);
    const t2 = performance.now();
    const lightCount = buildScene(root);
    timings.buildMs = Math.round(performance.now() - t2);
    timings.totalMs = Math.round(performance.now() - t0);
    stats = computeStats(root, timings, lightCount);
    emitProgress('build', 1);
    if (stats.unmeshed.total > 0) {
      log('warn', `${stats.unmeshed.total} object(s) have no render mesh and were skipped`);
    }
    emit('loadResult', { ok: true, name: displayName, stats });
  } catch (error) {
    const message = errorMessage(error);
    if (serial === loadSerial) {
      clear();
      log('error', `Load failed: ${message}`);
    }
    emit('loadResult', { ok: false, name: displayName, error: message });
  }
}

// Replaces the loader's materials with shared per-colour ones, drops the file's lights
// (the viewer has its own fixed rig) and frames the model. Returns the number of lights
// removed so the stats can still report them.
function buildScene(root) {
  modelRoot = root;
  const layers = root.userData.layers || [];
  const loaderMaterials = new Set();

  let lightCount = 0;
  for (const child of [...root.children]) {
    if (child.isLight) {
      root.remove(child);
      lightCount += 1;
    }
  }

  root.traverse((obj) => {
    const attributes = obj.userData.attributes;
    if (!attributes || !(obj.isMesh || obj.isLine || obj.isPoints)) return;
    loaderMaterials.add(obj.material);
    const hex = displayColorHex(objectColorHex(attributes, layers));
    if (obj.isMesh) obj.material = meshMaterialFor(hex);
    else if (obj.isLine) obj.material = lineMaterialFor(hex);
    else obj.material = pointMaterialFor(hex, obj.geometry.hasAttribute('color'));
  });
  for (const material of loaderMaterials) material.dispose();
  loader.materials = [];

  model.add(root);
  layerVisible = layers.map((layer) => layer.visible !== false);
  curvesVisible = true;
  pointsVisible = true;
  applyVisibility();

  const visibleBox = drawableBounds(true);
  modelBounds = visibleBox.isEmpty() ? drawableBounds(false) : visibleBox;
  modelCenter = modelBounds.isEmpty() ? new THREE.Vector3() : modelBounds.getCenter(new THREE.Vector3());
  modelRadius = modelBounds.isEmpty() ? 1 : Math.max(modelBounds.getSize(new THREE.Vector3()).length() / 2, 1e-6);
  rebuildGrid(modelBounds);
  applyDisplayMode();
  setView('iso');
  return lightCount;
}

function computeStats(root, timings, lightCount) {
  const layers = root.userData.layers || [];
  const counts = { meshes: 0, curves: 0, points: 0, pointClouds: 0, blocks: 0, lights: lightCount, other: 0 };
  let triangles = 0;
  let vertices = 0;
  const layerCounts = new Array(layers.length).fill(0);

  for (const child of root.children) {
    const type = child.userData.objectType;
    if (MESH_TYPES.has(type)) counts.meshes += 1;
    else if (type === 'Curve') counts.curves += 1;
    else if (type === 'Point') counts.points += 1;
    else if (type === 'PointSet') counts.pointClouds += 1;
    else if (type === 'InstanceReference') counts.blocks += 1;
    else counts.other += 1;
  }
  root.traverse((obj) => {
    const attributes = obj.userData.attributes;
    if (attributes && attributes.layerIndex >= 0 && attributes.layerIndex < layerCounts.length) {
      layerCounts[attributes.layerIndex] += 1;
    }
  });
  root.traverseVisible((obj) => {
    if (!obj.isMesh || !MESH_TYPES.has(obj.userData.objectType)) return;
    const position = obj.geometry.getAttribute('position');
    if (!position) return;
    vertices += position.count;
    triangles += Math.floor((obj.geometry.index ? obj.geometry.index.count : position.count) / 3);
  });

  const unmeshed = { breps: 0, extrusions: 0, total: 0 };
  const warnings = [];
  for (const warning of root.userData.warnings || []) {
    if (warning.type === 'no mesh') {
      if (warning.objectType === 'Brep') unmeshed.breps += 1;
      else if (warning.objectType === 'Extrusion') unmeshed.extrusions += 1;
      unmeshed.total += 1;
    }
    if (warnings.length < MAX_WARNINGS) warnings.push({ type: warning.type, message: warning.message });
  }

  const bbox = modelBounds.isEmpty()
    ? { min: [0, 0, 0], max: [0, 0, 0] }
    : { min: modelBounds.min.toArray(), max: modelBounds.max.toArray() };

  const unitSystem = root.userData.settings && root.userData.settings.modelUnitSystem;
  const units = unitSystem && typeof unitSystem.name === 'string'
    ? unitSystem.name.replace(/^UnitSystem_/, '')
    : 'Unknown';

  return {
    objects: Object.values(counts).reduce((sum, n) => sum + n, 0),
    ...counts,
    triangles,
    vertices,
    layers: layers.map((layer, index) => ({
      index,
      name: layer.name || '',
      fullPath: layer.fullPath || layer.name || '',
      color: hexString(layer.color ? colorToHex(layer.color) : 0),
      visible: layer.visible !== false,
      objectCount: layerCounts[index],
    })),
    unmeshed,
    bbox,
    units,
    timings,
    warnings,
  };
}

function disposeObject(root) {
  root.traverse((obj) => {
    if (obj.geometry) obj.geometry.dispose();
    if (obj.isSprite && obj.material) {
      if (obj.material.map) obj.material.map.dispose();
      obj.material.dispose();
    }
  });
}

function clear() {
  if (picked) {
    picked.mesh.material.dispose();
    picked.mesh.material = picked.baseMaterial;
    picked = null;
  }
  if (modelRoot) {
    model.remove(modelRoot);
    disposeObject(modelRoot);
    modelRoot = null;
  }
  edgeJob = null;
  for (const geometry of edgeGeometries.values()) geometry.dispose();
  edgeGeometries.clear();
  for (const cache of [meshMaterials, lineMaterials, pointMaterials]) {
    for (const material of cache.values()) material.dispose();
    cache.clear();
  }
  rebuildGrid(new THREE.Box3());
  layerVisible = [];
  stats = null;
  modelName = '';
  modelBounds = new THREE.Box3();
  modelCenter = new THREE.Vector3();
  modelRadius = 1;
  gridRadius = 0;
  requestRender();
}

// ---------------------------------------------------------------------------------------
// Export
// ---------------------------------------------------------------------------------------

function bytesToBase64(bytes) {
  const CHUNK = 0x8000;
  let binary = '';
  for (let i = 0; i < bytes.length; i += CHUNK) {
    binary += String.fromCharCode.apply(null, bytes.subarray(i, i + CHUNK));
  }
  return btoa(binary);
}

async function exportGlb() {
  if (!modelRoot) {
    emit('exportResult', { ok: false, error: 'No model loaded' });
    return;
  }
  // Export clean per-colour materials in the file's colours (no legibility lift, no
  // highlight, no display-mode flags) on a Y-up copy.
  const layers = modelRoot.userData.layers || [];
  const exportMaterials = new Map();
  const materialFor = (obj) => {
    const hex = objectColorHex(obj.userData.attributes || {}, layers);
    const vertexColors = Boolean(obj.isPoints && obj.material.vertexColors);
    const key = `${obj.type}:${hex}:${vertexColors}`;
    let clean = exportMaterials.get(key);
    if (!clean) {
      if (obj.isMesh) clean = new THREE.MeshStandardMaterial({ color: hex, roughness: 0.65, metalness: 0, side: THREE.DoubleSide });
      else if (obj.isPoints) clean = new THREE.PointsMaterial({ color: vertexColors ? 0xffffff : hex, vertexColors, size: 6, sizeAttenuation: false });
      else clean = new THREE.LineBasicMaterial({ color: hex });
      exportMaterials.set(key, clean);
    }
    return clean;
  };
  const yUpRoot = new THREE.Group();
  yUpRoot.name = modelName.replace(/\.3dm$/i, '');
  yUpRoot.rotation.x = -Math.PI / 2;
  const copy = modelRoot.clone(true);
  for (const obj of [...copy.children]) {
    if (obj.isSprite) copy.remove(obj);
  }
  copy.traverse((obj) => {
    for (const child of [...obj.children]) {
      if (child.userData.viewerEdges) obj.remove(child);
    }
  });
  copy.traverse((obj) => {
    if (obj.isMesh || obj.isLine || obj.isPoints) obj.material = materialFor(obj);
  });
  yUpRoot.add(copy);

  try {
    const glb = await new GLTFExporter().parseAsync(yUpRoot, { binary: true, onlyVisible: true });
    emit('exportResult', {
      ok: true,
      filename: `${yUpRoot.name || 'model'}.glb`,
      base64: bytesToBase64(new Uint8Array(glb)),
    });
  } catch (error) {
    emit('exportResult', { ok: false, error: errorMessage(error) });
  } finally {
    for (const material of exportMaterials.values()) material.dispose();
  }
}

// ---------------------------------------------------------------------------------------
// Public API
// ---------------------------------------------------------------------------------------

window.viewer = Object.freeze({
  load,
  clear,
  fit,
  setView,
  setProjection,
  setDisplayMode(mode) {
    if (!DISPLAY_MODES.includes(mode)) {
      log('warn', `Unknown display mode "${mode}"`);
      return;
    }
    displayMode = mode;
    applyDisplayMode();
    requestRender();
  },
  setLayerVisible(index, visible) {
    if (index < 0 || index >= layerVisible.length) return;
    layerVisible[index] = Boolean(visible);
    applyVisibility();
  },
  setAllLayersVisible(visible) {
    layerVisible = layerVisible.map(() => Boolean(visible));
    applyVisibility();
  },
  setCurvesVisible(visible) {
    curvesVisible = Boolean(visible);
    applyVisibility();
  },
  setPointsVisible(visible) {
    pointsVisible = Boolean(visible);
    applyVisibility();
  },
  setGrid(visible) {
    gridVisible = Boolean(visible);
    if (grid) grid.visible = gridVisible;
    requestRender();
  },
  setBackground(hexTop, hexBottom) {
    const style = document.documentElement.style;
    if (hexTop) style.setProperty('--bg-top', hexTop);
    if (hexBottom) style.setProperty('--bg-bottom', hexBottom);
  },
  exportGlb,
  getStats() {
    return stats ? JSON.stringify(stats) : 'null';
  },
});

// ---------------------------------------------------------------------------------------
// Start-up: frame an empty unit scene, then fetch rhino3dm and spawn the decode worker.
// The worker's `_ready` (patched loader, see PATCHES.md) settles once rhino3dm is
// instantiated inside it, so viewerReady means the first load only pays for parsing, and
// an initialisation failure fails every load() instead of hanging it.
// ---------------------------------------------------------------------------------------

createControls();
frameSphere(new THREE.Vector3(), modelRadius);
const workerReady = loader._initLibrary()
  .then(() => loader._getWorker(0))
  .then((worker) => worker._ready);
workerReady
  .then(() => emit('viewerReady', { three: 'r' + THREE.REVISION, rhino3dm: RHINO3DM_VERSION }))
  .catch((error) => log('error', `rhino3dm initialisation failed: ${errorMessage(error)}`));
