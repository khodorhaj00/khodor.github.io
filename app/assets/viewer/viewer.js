import * as THREE from 'three';
import { OrbitControls } from 'three/addons/controls/OrbitControls.js';
import { Rhino3dmLoader } from 'three/addons/loaders/3DMLoader.js';
import { GLTFExporter } from 'three/addons/exporters/GLTFExporter.js';
import { RoomEnvironment } from 'three/addons/environments/RoomEnvironment.js';
import {
  ANNOTATION_TYPES,
  buildAnnotation,
  buildHatch,
  collectScaledParts,
  disposeAnnotationResources,
  isScaledPart,
  updateAnnotationScale,
} from './annotations.js';

// ---------------------------------------------------------------------------------------
// Start-up guard (installed by index.html before this module loads)
// ---------------------------------------------------------------------------------------

// It owns the Flutter bridge, the ring buffer of log events and the failure screen, so
// anything that goes wrong before, during or after start-up is both visible on screen and
// reported to the app. Signal that this module body is running before anything that can
// throw, so the guard can tell "never ran" from "ran and stopped".
const bootstrap = window.__viewerBoot;
bootstrap.starting();
const { emit, log } = bootstrap;

const RHINO3DM_VERSION = '8.32.2';
const HIGHLIGHT_COLOR = 0xFFB020;
const HIGHLIGHT_INTENSITY = 0.35;
// Outline colour for objects too close to HIGHLIGHT_COLOR (8-bit RGB distance) for it to show.
const HIGHLIGHT_ALT_COLOR = 0x3DA5FF;
const HIGHLIGHT_MIN_CONTRAST = 100;
// Fraction of the limiting viewport axis the fitted model's silhouette spans.
const FIT_FILL = 0.8;
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
const DISPLAY_MODES = ['shaded', 'shaded_edges', 'wireframe', 'ghosted', 'rendered'];
const RENDER_QUALITIES = ['basic', 'full'];
const CURVE_QUALITIES = ['standard', 'high', 'max'];
const MESH_TYPES = new Set(['Mesh', 'Brep', 'Extrusion', 'SubD']);
// Object categories for the "Show" and selection-filter switches. Everything inside a
// block instance also follows the `blocks` switch.
const CATEGORY_OF = {
  Brep: 'surfaces',
  Extrusion: 'surfaces',
  SubD: 'surfaces',
  Mesh: 'meshes',
  Curve: 'curves',
  Point: 'points',
  PointSet: 'points',
  Annotation: 'annotations',
  TextDot: 'annotations',
  Hatch: 'hatches',
  InstanceReference: 'blocks',
};
const CATEGORIES = ['surfaces', 'meshes', 'curves', 'points', 'annotations', 'hatches', 'blocks'];
const PICK_LINE_PX = 12;
const SNAP_PX = 16;
const MEASURE_COLOR = 0xFFB020;
const MEASURE_LEG_COLOR = 0x8B93A1;
const LABEL_PX = 22;
const SHADOW_MAP_SIZE = 2048;

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

  // Annotations and hatches arrive from the patched worker (PATCHES.md) and are built by
  // annotations.js; everything else is the stock conversion.
  _createObject(obj, mat) {
    if (obj.objectType === 'Annotation') return buildAnnotation(obj);
    if (obj.objectType === 'Hatch') return buildHatch(obj);
    return super._createObject(obj, mat);
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
    // The file's own materials, for the rendered display mode (built on demand).
    root.userData.renderMaterials = data.materials || [];

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

let renderer = null;
let canvas = null;

// The canvas is created here rather than inside WebGLRenderer so that the browser's own
// `webglcontextcreationerror` reason — the useful half of the message on a phone — can be
// captured and shown when the context is refused.
function createRenderer() {
  const element = document.createElement('canvas');
  let reason = '';
  element.addEventListener('webglcontextcreationerror', (event) => {
    reason = event.statusMessage || '';
  }, false);
  try {
    const created = new THREE.WebGLRenderer({ canvas: element, antialias: true, alpha: true, preserveDrawingBuffer: true });
    created.setPixelRatio(Math.min(window.devicePixelRatio || 1, 2));
    created.setClearColor(0x000000, 0);
    return created;
  } catch (error) {
    throw new Error(`WebGL is unavailable in this browser: ${errorMessage(error)}${reason ? ` (${reason})` : ''}`);
  }
}

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

// A WebView can hand the page a zero-sized or late-sized viewport (hybrid composition
// measures the platform view after the page has loaded), which would leave a 0x0 canvas
// drawing nothing at all; every size is clamped to at least 1 px and re-applied from a
// ResizeObserver as well as from `resize`.
function viewportWidth() {
  return Math.max(1, Math.round(window.innerWidth || document.documentElement.clientWidth || 0));
}

function viewportHeight() {
  return Math.max(1, Math.round(window.innerHeight || document.documentElement.clientHeight || 0));
}

function aspect() {
  return viewportWidth() / viewportHeight();
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
  updateAnnotationScale(scaledParts, camera, appliedHeight || viewportHeight());
  updateMeasureLabel();
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

let appliedWidth = 0;
let appliedHeight = 0;

function applyViewportSize() {
  const width = viewportWidth();
  const height = viewportHeight();
  if (width === appliedWidth && height === appliedHeight) return;
  appliedWidth = width;
  appliedHeight = height;
  renderer.setSize(width, height);
  persp.aspect = aspect();
  persp.updateProjectionMatrix();
  setOrthoFrustum(ortho.top);
  // The new aspect limits the frustum by the other axis (a phone rotation), so re-frame
  // rather than crop: the whole model stays in view at the price of the current zoom.
  fit();
  requestRender();
}

// A lost context leaves a frozen canvas that looks exactly like a working app, so it is
// said on screen and in the log. three.js rebuilds its GL state on restore by itself; the
// page only has to draw again.
function onContextLost(event) {
  // Without preventDefault the browser never restores the context.
  event.preventDefault();
  log('error', 'WebGL context lost');
  bootstrap.notice('The 3D view was interrupted', 'The device took the graphics context (WebGL) away from this page.');
}

function onContextRestored() {
  log('info', 'WebGL context restored');
  bootstrap.clearNotice();
  requestRender();
}

function attachCanvasListeners() {
  canvas.addEventListener('webglcontextlost', onContextLost, false);
  canvas.addEventListener('webglcontextrestored', onContextRestored, false);
}

function observeViewport() {
  window.addEventListener('resize', applyViewportSize);
  // `resize` alone can miss a platform view that is measured after the page loaded.
  if (typeof ResizeObserver === 'function') new ResizeObserver(applyViewportSize).observe(document.documentElement);
}

// ---------------------------------------------------------------------------------------
// Materials (per colour, shared) and display modes
// ---------------------------------------------------------------------------------------

const meshMaterials = new Map();
const lineMaterials = new Map();
const pointMaterials = new Map();
const flatMaterials = new Map();
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

// Unlit, for arrowheads and hatch fills; `opacity` < 1 is drawn behind coplanar geometry.
function flatMaterialFor(hex, opacity = 1) {
  const key = `${hex}:${opacity}`;
  let material = flatMaterials.get(key);
  if (!material) {
    const translucent = opacity < 1;
    material = new THREE.MeshBasicMaterial({
      color: hex,
      side: THREE.DoubleSide,
      transparent: translucent,
      opacity,
      depthWrite: !translucent,
      polygonOffset: true,
      polygonOffsetFactor: 1,
      polygonOffsetUnits: 1,
    });
    material.toneMapped = false;
    flatMaterials.set(key, material);
  }
  return material;
}

// One per label: the texture is the label's own (white text, tinted by the colour).
function textMaterialFor(texture, hex) {
  const material = new THREE.MeshBasicMaterial({
    map: texture,
    color: hex,
    transparent: true,
    depthWrite: false,
    side: THREE.DoubleSide,
  });
  material.toneMapped = false;
  material.userData.perObject = true;
  return material;
}

// Colours the parts of an annotation or hatch group in the group's colour.
function colorAnnotationParts(group, hex) {
  for (const part of group.children) {
    switch (part.userData.annotationPart) {
      case 'lines':
        part.material = lineMaterialFor(hex);
        break;
      case 'arrow':
        part.material = part.isLineSegments ? lineMaterialFor(hex) : flatMaterialFor(hex);
        break;
      case 'fill':
        part.material = flatMaterialFor(hex, part.userData.opacity);
        break;
      case 'text':
        part.material = textMaterialFor(part.material.map, hex);
        break;
      default:
        break;
    }
  }
}

// ---------------------------------------------------------------------------------------
// Rendered display mode: the file's own materials, image-based light, optional textures
// and shadows ('full')
// ---------------------------------------------------------------------------------------

let renderQuality = 'basic';
let roomEnvironment = null;
let sunLight = null;
let shadowGround = null;
const renderMaterials = new Map();
// Each mesh's per-colour display material while it wears a render material. Not in
// userData: Object3D.clone() JSON-copies userData (the GLB export clones the model).
const shadedMaterialOf = new WeakMap();
const textureLoader = new THREE.TextureLoader();

function environmentTexture() {
  if (!roomEnvironment) {
    const generator = new THREE.PMREMGenerator(renderer);
    const room = new RoomEnvironment();
    roomEnvironment = generator.fromScene(room, 0.04).texture;
    room.dispose();
    generator.dispose();
  }
  return roomEnvironment;
}

// The render material index Rhino would use for an object, or -1.
function renderMaterialIndex(attributes, layers) {
  const source = attributes.materialSource && attributes.materialSource.name;
  if (source === 'ObjectMaterialSource_MaterialFromObject') return attributes.materialIndex ?? -1;
  if (source === 'ObjectMaterialSource_MaterialFromLayer') {
    const layer = layers[attributes.layerIndex];
    return layer && layer.renderMaterialIndex >= 0 ? layer.renderMaterialIndex : -1;
  }
  return -1;
}

const unit = (value, fallback) => (Number.isFinite(value) ? THREE.MathUtils.clamp(value, 0, 1) : fallback);

function loadTexture(texture, colour) {
  const map = textureLoader.load(texture.image, () => requestRender());
  map.wrapS = texture.wrapU === 0 ? THREE.RepeatWrapping : THREE.ClampToEdgeWrapping;
  map.wrapT = texture.wrapV === 0 ? THREE.RepeatWrapping : THREE.ClampToEdgeWrapping;
  if (texture.repeat) map.repeat.set(texture.repeat[0], texture.repeat[1]);
  if (colour) map.colorSpace = THREE.SRGBColorSpace;
  return map;
}

function buildRenderMaterial(data, fallbackHex, withTextures) {
  const material = new THREE.MeshStandardMaterial({ side: THREE.DoubleSide, roughness: 0.45, metalness: 0 });
  if (!data) {
    material.color.setHex(fallbackHex);
    return material;
  }
  if (data.pbrSupported && data.pbr) {
    const pbr = data.pbr;
    const base = pbr.baseColor || {};
    material.color.setRGB(unit(base.r, 1), unit(base.g, 1), unit(base.b, 1), THREE.SRGBColorSpace);
    material.roughness = unit(pbr.roughness, 0.5);
    material.metalness = unit(pbr.metallic, 0);
    material.opacity = unit(pbr.opacity, 1);
  } else {
    const diffuse = data.diffuseColor || { r: 255, g: 255, b: 255 };
    material.color.setRGB(diffuse.r / 255, diffuse.g / 255, diffuse.b / 255, THREE.SRGBColorSpace);
    // Rhino's legacy shine runs 0..255 (glossier is higher).
    material.roughness = THREE.MathUtils.clamp(1 - (Number(data.shine) || 0) / 255, 0.08, 1);
    material.metalness = THREE.MathUtils.clamp(Number(data.reflectivity) || 0, 0, 1) * 0.5;
    material.opacity = 1 - unit(data.transparency, 0);
  }
  const emission = data.emissionColor;
  if (emission) material.emissive.setRGB(emission.r / 255, emission.g / 255, emission.b / 255, THREE.SRGBColorSpace);
  material.transparent = material.opacity < 1;
  material.depthWrite = !material.transparent;
  material.name = data.name || '';

  if (withTextures) {
    for (const texture of data.textures || []) {
      if (!texture.image) continue;
      switch (texture.type) {
        case 'Diffuse':
        case 'PBR_BaseColor':
          material.map = loadTexture(texture, true);
          material.color.setRGB(1, 1, 1);
          break;
        case 'Bump':
          material.bumpMap = loadTexture(texture, false);
          break;
        case 'PBR_Roughness':
          material.roughnessMap = loadTexture(texture, false);
          break;
        case 'PBR_Metallic':
          material.metalnessMap = loadTexture(texture, false);
          break;
        case 'PBR_AmbientOcclusion':
          material.aoMap = loadTexture(texture, false);
          break;
        case 'PBR_Emission':
          material.emissiveMap = loadTexture(texture, true);
          break;
        case 'Transparency':
        case 'PBR_Alpha':
          material.alphaMap = loadTexture(texture, false);
          material.transparent = true;
          break;
        default:
          break;
      }
    }
  }
  return material;
}

function renderMaterialFor(mesh) {
  const layers = currentLayers();
  const attributes = mesh.userData.attributes || {};
  const index = renderMaterialIndex(attributes, layers);
  const materials = modelRoot ? modelRoot.userData.renderMaterials || [] : [];
  const data = index >= 0 ? materials[index] : null;
  const hex = mesh.userData.displayHex ?? 0xffffff;
  const key = data ? `m${index}:${renderQuality}` : `c${hex}`;
  let material = renderMaterials.get(key);
  if (!material) {
    material = buildRenderMaterial(data, hex, renderQuality === 'full');
    renderMaterials.set(key, material);
  }
  return material;
}

function disposeRenderMaterials() {
  for (const material of renderMaterials.values()) {
    for (const slot of ['map', 'bumpMap', 'roughnessMap', 'metalnessMap', 'aoMap', 'emissiveMap', 'alphaMap']) {
      if (material[slot]) material[slot].dispose();
    }
    material.dispose();
  }
  renderMaterials.clear();
}

function updateShadowRig() {
  const wantShadows = displayMode === 'rendered' && renderQuality === 'full' && !modelBounds.isEmpty();
  if (renderer.shadowMap.enabled !== wantShadows) {
    renderer.shadowMap.enabled = wantShadows;
    renderer.shadowMap.type = THREE.PCFShadowMap;
    for (const material of renderMaterials.values()) material.needsUpdate = true;
  }
  if (!wantShadows) {
    if (sunLight) sunLight.visible = false;
    if (shadowGround) shadowGround.visible = false;
    return;
  }
  const size = modelBounds.getSize(new THREE.Vector3());
  const center = modelBounds.getCenter(new THREE.Vector3());
  const radius = Math.max(size.length() / 2, 1e-3);
  if (!sunLight) {
    sunLight = new THREE.DirectionalLight(0xffffff, 1.6);
    sunLight.castShadow = true;
    sunLight.shadow.mapSize.set(SHADOW_MAP_SIZE, SHADOW_MAP_SIZE);
    scene.add(sunLight, sunLight.target);
  }
  sunLight.visible = true;
  sunLight.target.position.copy(center);
  sunLight.position.copy(center).addScaledVector(new THREE.Vector3(-0.6, -0.9, 1.4).normalize(), radius * 3);
  const shadowCamera = sunLight.shadow.camera;
  shadowCamera.left = -radius * 1.5;
  shadowCamera.right = radius * 1.5;
  shadowCamera.top = radius * 1.5;
  shadowCamera.bottom = -radius * 1.5;
  shadowCamera.near = radius * 0.5;
  shadowCamera.far = radius * 6;
  shadowCamera.updateProjectionMatrix();
  sunLight.shadow.bias = -0.0005;
  sunLight.shadow.normalBias = radius * 0.002;

  if (!shadowGround) {
    shadowGround = new THREE.Mesh(new THREE.PlaneGeometry(1, 1), new THREE.ShadowMaterial({ opacity: 0.35 }));
    shadowGround.receiveShadow = true;
    shadowGround.raycast = () => {};
    shadowGround.userData.viewerHelper = true;
    scene.add(shadowGround);
  }
  shadowGround.visible = true;
  shadowGround.scale.set(radius * 8, radius * 8, 1);
  shadowGround.position.set(center.x, center.y, modelBounds.min.z - radius * 1e-3);
}

// Swaps every surface/mesh between its per-colour display material and its render
// material. Called on every display-mode or render-quality change.
function applyRenderedMaterials() {
  const rendered = displayMode === 'rendered';
  const full = rendered && renderQuality === 'full';
  scene.environment = rendered ? environmentTexture() : null;
  scene.environmentIntensity = 0.9;
  renderer.toneMapping = rendered ? THREE.NeutralToneMapping : THREE.NoToneMapping;
  hemi.intensity = rendered ? 0.35 : 1.6;
  keyLight.intensity = rendered ? (full ? 0.6 : 1.1) : 2.2;
  fillLight.intensity = rendered ? 0.3 : 0.9;
  forEachMesh((mesh) => {
    if (!shadedMaterialOf.has(mesh)) shadedMaterialOf.set(mesh, mesh.material);
    mesh.material = rendered ? renderMaterialFor(mesh) : shadedMaterialOf.get(mesh);
    mesh.castShadow = full;
    mesh.receiveShadow = full;
  });
  if (!rendered) disposeRenderMaterials();
  updateShadowRig();
  for (const cache of [meshMaterials, lineMaterials, pointMaterials, flatMaterials]) {
    for (const material of cache.values()) material.needsUpdate = true;
  }
}

function applyModeToMaterial(material, mode) {
  if (mode === 'rendered') mode = 'shaded';
  const ghosted = mode === 'ghosted';
  material.wireframe = mode === 'wireframe';
  material.transparent = ghosted;
  material.opacity = ghosted ? GHOSTED_OPACITY : 1;
  material.depthWrite = !ghosted;
  material.needsUpdate = true;
}

function edgeGeometryFor(geometry) {
  let edges = edgeGeometries.get(geometry);
  if (!edges) {
    edges = new THREE.EdgesGeometry(geometry, EDGE_ANGLE_DEG);
    edgeGeometries.set(geometry, edges);
  }
  return edges;
}

function edgesFor(mesh) {
  let edges = mesh.children.find((child) => child.userData.viewerEdges);
  if (edges) return edges;
  edges = new THREE.LineSegments(edgeGeometryFor(mesh.geometry), edgeMaterial);
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
  // The highlight holds copies of the materials being swapped; take it off and put it back.
  const previous = picked;
  unpick();
  for (const material of meshMaterials.values()) applyModeToMaterial(material, displayMode);
  applyRenderedMaterials();
  if (previous) highlight(previous.target, previous.hit);
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
// Visibility (layers, object categories) and the selection filter
// ---------------------------------------------------------------------------------------

let layerVisible = [];
const categoryVisible = Object.fromEntries(CATEGORIES.map((c) => [c, true]));
const categoryPickable = Object.fromEntries(CATEGORIES.map((c) => [c, true]));
let scaledParts = [];

function categoryOf(obj) {
  return CATEGORY_OF[obj.userData.objectType] || null;
}

function applyVisibility() {
  model.traverse((obj) => {
    const attributes = obj.userData.attributes;
    if (!attributes) return;
    const layerOk = layerVisible[attributes.layerIndex] !== false;
    // Objects hidden in Rhino (Hide command) stay hidden, as in the backend's /convert.
    const objectOk = attributes.visible !== false;
    const category = categoryOf(obj);
    const typeOk = !category || categoryVisible[category] !== false;
    obj.visible = layerOk && objectOk && typeOk;
  });
  if (picked && !isShownInModel(picked.target)) setPicked(null);
  requestRender();
}

function isShownInModel(obj) {
  for (let o = obj; o && o !== model; o = o.parent) if (!o.visible) return false;
  return true;
}

function setCategoryVisible(category, visible) {
  if (!(category in categoryVisible)) {
    log('warn', `Unknown object category "${category}"`);
    return;
  }
  categoryVisible[category] = Boolean(visible);
  applyVisibility();
}

function setCategoryPickable(category, pickable) {
  if (!(category in categoryPickable)) {
    log('warn', `Unknown object category "${category}"`);
    return;
  }
  categoryPickable[category] = Boolean(pickable);
  if (picked && !pickableTarget(picked.target)) setPicked(null);
}

function pickableTarget(target) {
  const category = categoryOf(target);
  return !category || categoryPickable[category] !== false;
}

// ---------------------------------------------------------------------------------------
// Bounds, grid, camera framing
// ---------------------------------------------------------------------------------------

const _box = new THREE.Box3();

function drawableBounds(visibleOnly) {
  const box = new THREE.Box3();
  model.updateMatrixWorld(true);
  const visit = (obj) => {
    if (!obj.geometry || obj.userData.viewerEdges || obj.userData.viewerHighlight || obj.isSprite || isScaledPart(obj)) return;
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

// Calls fn(corner) for the eight corners of a box; bit 0/1/2 of the index selects max
// over min on x/y/z.
function boxCorners(box, fn) {
  const corner = new THREE.Vector3();
  for (let i = 0; i < 8; i++) {
    fn(corner.set(i & 1 ? box.max.x : box.min.x, i & 2 ? box.max.y : box.min.y, i & 4 ? box.max.z : box.min.z));
  }
}

// Calls fn(point) for every drawn vertex of the visible model, in world space.
function forEachVisibleVertex(fn) {
  const point = new THREE.Vector3();
  model.updateMatrixWorld(true);
  model.traverseVisible((obj) => {
    if (!obj.geometry || obj.userData.viewerEdges || obj.userData.viewerHighlight || obj.isSprite || isScaledPart(obj)) return;
    const position = obj.geometry.getAttribute('position');
    if (!position) return;
    for (let i = 0; i < position.count; i++) fn(point.fromBufferAttribute(position, i).applyMatrix4(obj.matrixWorld));
  });
}

// Frames a set of points (eachPoint(fn) visits them) from the current view direction, in
// both cameras so switching projection afterwards keeps the framing. The target is
// `center` shifted across the view so the points' silhouette is centred, and the
// perspective distance and ortho half-height are the smallest that keep every point
// inside FIT_FILL of the frustum: the drawn silhouette, not a bounding sphere, fills the
// viewport.
function framePoints(center, radius, eachPoint) {
  const dir = viewDirection();
  // The basis the camera gets from lookAt() once it sits along `dir` (same handling of a
  // direction parallel to `up`).
  const basis = new THREE.Matrix4().lookAt(dir, new THREE.Vector3(), persp.up);
  const right = new THREE.Vector3().setFromMatrixColumn(basis, 0);
  const up = new THREE.Vector3().setFromMatrixColumn(basis, 1);
  const tanV = Math.tan(THREE.MathUtils.degToRad(persp.fov) / 2) * FIT_FILL;
  const tanH = tanV * aspect();
  // A point is inside the frustum of a camera `dist` behind a target shifted by (cx, cy)
  // when (x - cx) <= (dist - z) * tanH, i.e. dist * tanH >= (x + z * tanH) - cx, and
  // likewise for the other three planes; per plane only the largest reach matters.
  const reach = { right: -Infinity, left: -Infinity, top: -Infinity, bottom: -Infinity };
  const min = new THREE.Vector2(Infinity, Infinity);
  const max = new THREE.Vector2(-Infinity, -Infinity);
  const v = new THREE.Vector3();
  const xy = new THREE.Vector2();
  eachPoint((point) => {
    v.subVectors(point, center);
    const x = v.dot(right);
    const y = v.dot(up);
    const z = v.dot(dir);
    reach.right = Math.max(reach.right, x + z * tanH);
    reach.left = Math.max(reach.left, -x + z * tanH);
    reach.top = Math.max(reach.top, y + z * tanV);
    reach.bottom = Math.max(reach.bottom, -y + z * tanV);
    min.min(xy.set(x, y));
    max.max(xy);
  });
  if (min.x === Infinity) {
    reach.right = reach.left = reach.top = reach.bottom = 0;
    min.set(0, 0);
    max.set(0, 0);
  }
  // Balancing opposite planes centres the silhouette and minimises the distance; a
  // degenerate (point-like) model still gets a usable, non-zero framing.
  const cx = (reach.right - reach.left) / 2;
  const cy = (reach.top - reach.bottom) / 2;
  const dist = Math.max((reach.right + reach.left) / (2 * tanH), (reach.top + reach.bottom) / (2 * tanV), radius * 0.05);
  const halfHeight = Math.max(
    (max.y - cy) / FIT_FILL,
    (cy - min.y) / FIT_FILL,
    (max.x - cx) / (FIT_FILL * aspect()),
    (cx - min.x) / (FIT_FILL * aspect()),
    radius * 0.05,
  );
  const target = center.clone().addScaledVector(right, cx).addScaledVector(up, cy);

  persp.position.copy(target).addScaledVector(dir, dist);
  ortho.position.copy(persp.position);
  ortho.zoom = 1;
  setOrthoFrustum(halfHeight);

  controls.target.copy(target);
  applyControlLimits(radius);
  controls.update();
  requestRender();
}

function fit() {
  const box = drawableBounds(true);
  if (box.isEmpty()) return;
  const radius = Math.max(box.getSize(new THREE.Vector3()).length() / 2, 1e-6);
  framePoints(box.getCenter(new THREE.Vector3()), radius, forEachVisibleVertex);
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

function onPointerDown(event) {
  activePointers += 1;
  if (activePointers > 1) multiTouch = true;
  else {
    multiTouch = false;
    pointerDown = { x: event.clientX, y: event.clientY, t: performance.now() };
  }
}

function endPointer(event, allowPick) {
  activePointers = Math.max(0, activePointers - 1);
  const down = pointerDown;
  pointerDown = null;
  if (!allowPick || !down || multiTouch) return;
  const moved = Math.hypot(event.clientX - down.x, event.clientY - down.y);
  if (moved < TAP_MAX_MOVE_PX && performance.now() - down.t < TAP_MAX_MS) onTap(event.clientX, event.clientY);
}

function attachPointerListeners() {
  canvas.addEventListener('pointerdown', onPointerDown);
  canvas.addEventListener('pointerup', (event) => endPointer(event, true));
  canvas.addEventListener('pointercancel', (event) => endPointer(event, false));
}

function onTap(clientX, clientY) {
  if (measure.active) measureAt(clientX, clientY);
  else pickAt(clientX, clientY);
}

// World units covered by one screen pixel at `point`.
function unitsPerPixel(point) {
  const height = appliedHeight || viewportHeight();
  if (camera.isOrthographicCamera) return (camera.top - camera.bottom) / camera.zoom / height;
  const distance = Math.max(point.distanceTo(camera.position), 1e-9);
  return (2 * distance * Math.tan(THREE.MathUtils.degToRad(camera.fov) / 2)) / height;
}

function setRay(clientX, clientY) {
  const rect = canvas.getBoundingClientRect();
  const ndc = new THREE.Vector2(
    ((clientX - rect.left) / rect.width) * 2 - 1,
    -((clientY - rect.top) / rect.height) * 2 + 1,
  );
  raycaster.setFromCamera(ndc, camera);
  raycaster.camera = camera;
  const tolerance = unitsPerPixel(controls.target) * PICK_LINE_PX;
  raycaster.params.Line.threshold = tolerance;
  raycaster.params.Points.threshold = tolerance;
}

// The top-level block instance containing an object, if any.
function instanceOf(obj) {
  let instance = null;
  for (let o = obj.parent; o && o !== modelRoot; o = o.parent) {
    if (o.userData.objectType === 'InstanceReference' && o.userData.attributes) instance = o;
  }
  return instance;
}

// The Rhino object a drawn node belongs to: its annotation/hatch group, or the node.
function ownerOf(node) {
  if (node.userData.annotationPart && node.parent && ANNOTATION_TYPES.has(node.parent.userData.objectType)) return node.parent;
  return node.userData.attributes ? node : null;
}

// Every visible node that may be hit, honouring the selection filter. `forMeasure` takes
// every visible surface, mesh, curve and point instead.
function pickCandidates(forMeasure) {
  const candidates = [];
  if (!modelRoot) return candidates;
  modelRoot.traverseVisible((node) => {
    if (node.userData.viewerEdges || node.userData.viewerHighlight) return;
    const owner = ownerOf(node);
    if (!owner) return;
    const type = owner.userData.objectType;
    if (forMeasure) {
      if ((node.isMesh && MESH_TYPES.has(type)) || (node.isLine && type === 'Curve') || (node.isPoints && CATEGORY_OF[type] === 'points')) {
        candidates.push(node);
      }
      return;
    }
    if (node.isSprite && type !== 'TextDot') return;
    const inBlock = instanceOf(node);
    const category = inBlock ? 'blocks' : CATEGORY_OF[type];
    if (!category || categoryPickable[category] === false) return;
    if (node.isMesh || node.isLine || node.isPoints || node.isSprite) candidates.push(node);
  });
  return candidates;
}

// Nearest hit, preferring a curve, point or annotation that lies on (or just in front of)
// the surface under the finger: those are what a tap near an edge is meant for.
function bestHit(hits) {
  if (!hits.length) return null;
  const surface = hits.find((h) => h.object.isMesh && !h.object.userData.annotationPart);
  const thin = hits.find((h) => !(h.object.isMesh && !h.object.userData.annotationPart));
  if (!surface) return thin;
  if (!thin) return surface;
  const slack = unitsPerPixel(surface.point) * PICK_LINE_PX;
  return thin.distance <= surface.distance + slack ? thin : surface;
}

function pickAt(clientX, clientY) {
  setRay(clientX, clientY);
  const hit = bestHit(raycaster.intersectObjects(pickCandidates(false), false));
  if (!hit) {
    setPicked(null);
    return;
  }
  const owner = ownerOf(hit.object);
  setPicked(instanceOf(hit.object) || owner, hit.object);
}

function colorDistance(a, b) {
  return Math.hypot((a >> 16) - (b >> 16), ((a >> 8) & 255) - ((b >> 8) & 255), (a & 255) - (b & 255));
}

function boxOutlineGeometry(box) {
  const positions = [];
  boxCorners(box, (corner) => positions.push(corner.x, corner.y, corner.z));
  const geometry = new THREE.BufferGeometry();
  geometry.setIndex([0, 1, 1, 3, 3, 2, 2, 0, 4, 5, 5, 7, 7, 6, 6, 4, 0, 4, 1, 5, 2, 6, 3, 7]);
  geometry.setAttribute('position', new THREE.Float32BufferAttribute(positions, 3));
  return geometry;
}

function outlineMaterial(hex) {
  return new THREE.LineBasicMaterial({
    color: colorDistance(hex, HIGHLIGHT_COLOR) < HIGHLIGHT_MIN_CONTRAST ? HIGHLIGHT_ALT_COLOR : HIGHLIGHT_COLOR,
    depthTest: false,
    depthWrite: false,
    toneMapped: false,
  });
}

// A single mesh's outline, drawn through everything: its hard edges (the geometry is shared
// with shaded_edges mode) or, for a smooth closed mesh that has none or a mesh too large to
// edge, its own bounding box. The emissive tint alone vanishes on light colours, and an
// accent-coloured line on an accent-coloured object, so such objects get the alternative
// colour.
function meshOutline(mesh, hex) {
  const edges = meshTriangles(mesh) <= EDGE_MAX_TRIANGLES ? edgeGeometryFor(mesh.geometry) : null;
  const shared = Boolean(edges && edges.getAttribute('position').count > 0);
  if (!shared && !mesh.geometry.boundingBox) mesh.geometry.computeBoundingBox();
  const outline = new THREE.LineSegments(shared ? edges : boxOutlineGeometry(mesh.geometry.boundingBox), outlineMaterial(hex));
  outline.userData.ownsGeometry = !shared;
  return outline;
}

// World-space bounds of an object without the zoom-dependent parts of annotations.
function objectBounds(target) {
  const box = new THREE.Box3();
  const part = new THREE.Box3();
  target.updateWorldMatrix(true, true);
  target.traverse((node) => {
    if (!node.geometry || node.userData.viewerEdges || node.userData.viewerHighlight || isScaledPart(node)) return;
    if (node.isSprite) {
      box.expandByPoint(node.getWorldPosition(new THREE.Vector3()));
      return;
    }
    if (!node.geometry.boundingBox) node.geometry.computeBoundingBox();
    if (node.geometry.boundingBox.isEmpty()) return;
    box.union(part.copy(node.geometry.boundingBox).applyMatrix4(node.matrixWorld));
  });
  if (box.isEmpty()) box.setFromObject(target, true);
  return box;
}

function highlightMaterial(node) {
  const material = node.material.clone();
  if (node.isMesh && !node.userData.annotationPart && material.emissive) {
    material.emissive.setHex(HIGHLIGHT_COLOR);
    material.emissiveIntensity = HIGHLIGHT_INTENSITY;
  } else if (material.color) {
    material.color.setHex(HIGHLIGHT_COLOR);
  }
  return material;
}

// Tints every drawn node of the target and outlines it: a lone surface or mesh by its
// edges (following its transform), anything else by its bounding box.
function highlight(target, hit) {
  const swapped = [];
  let outline;
  target.traverse((node) => {
    if (node.userData.viewerEdges || node.isSprite) return;
    if (!(node.isMesh || node.isLine || node.isPoints) || !node.material) return;
    swapped.push([node, node.material]);
    node.material = highlightMaterial(node);
  });
  if (target.isMesh && MESH_TYPES.has(target.userData.objectType)) {
    outline = meshOutline(target, swapped.length ? swapped[0][1].color.getHex() : HIGHLIGHT_COLOR);
    target.add(outline);
  } else {
    const box = objectBounds(target);
    outline = new THREE.LineSegments(boxOutlineGeometry(box), outlineMaterial(0));
    outline.userData.ownsGeometry = true;
    scene.add(outline);
  }
  outline.renderOrder = 3;
  outline.userData.viewerHighlight = true;
  outline.raycast = () => {};
  picked = { target, hit, swapped, outline };
}

function unpick() {
  if (!picked) return;
  const { swapped, outline } = picked;
  for (const [node, material] of swapped) {
    node.material.dispose();
    node.material = material;
  }
  if (outline.parent) outline.parent.remove(outline);
  outline.material.dispose();
  if (outline.userData.ownsGeometry) outline.geometry.dispose();
  picked = null;
}

function setPicked(target, hit = null) {
  unpick();
  if (target) highlight(target, hit);
  requestRender();
  emit('objectPicked', target ? describeObject(target, hit) : null);
}

const ANNOTATION_LABELS = {
  Aligned: 'Aligned dimension',
  Rotated: 'Linear dimension',
  Angular: 'Angular dimension',
  Angular3pt: 'Angular dimension',
  ArcLen: 'Arc length dimension',
  Radius: 'Radius dimension',
  Diameter: 'Diameter dimension',
  Ordinate: 'Ordinate dimension',
  CenterMark: 'Center mark',
  Text: 'Text',
  Leader: 'Leader',
};

// Block content is reported as its top-level instance, as Rhino selects it: the reference
// carries the meaningful name, layer and user strings; the hit member's user strings fill
// gaps.
function describeObject(target, hit) {
  const attributes = target.userData.attributes || {};
  const layers = currentLayers();
  const layer = layers[attributes.layerIndex];
  const box = objectBounds(target);
  const size = box.getSize(new THREE.Vector3());
  const center = box.getCenter(new THREE.Vector3());
  const member = hit ? ownerOf(hit) : null;
  const userStrings = Object.fromEntries(((member && member.userData.attributes) || {}).userStrings || []);
  Object.assign(userStrings, Object.fromEntries(attributes.userStrings || []));
  const type = target.userData.objectType;
  let subtype = '';
  if (type === 'Annotation') subtype = ANNOTATION_LABELS[target.userData.annotationKind] || target.userData.annotationKind || '';
  else if (type === 'Hatch') subtype = target.userData.hatchSolid ? 'Solid hatch' : 'Pattern hatch';
  else if (type === 'TextDot') subtype = 'Text dot';
  let text = type === 'Annotation' ? target.userData.text || '' : '';
  if (type === 'TextDot') text = (attributes.geometry && attributes.geometry.text) || '';
  return {
    id: attributes.id ?? null,
    name: attributes.name || '',
    objectType: type,
    subtype,
    text,
    blockName: type === 'InstanceReference' ? target.userData.blockName || '' : '',
    layerIndex: attributes.layerIndex ?? -1,
    layerName: layer ? layer.name : '',
    userStrings,
    size: [size.x, size.y, size.z],
    center: [center.x, center.y, center.z],
  };
}

// ---------------------------------------------------------------------------------------
// Caliper (measure mode)
// ---------------------------------------------------------------------------------------

const measure = {
  active: false,
  points: [],
  snaps: [],
  group: null,
  label: null,
  labelEntry: null,
};

function toScreen(point) {
  const v = point.clone().project(camera);
  const rect = canvas.getBoundingClientRect();
  return new THREE.Vector2(rect.left + ((v.x + 1) / 2) * rect.width, rect.top + ((1 - v.y) / 2) * rect.height);
}

// The point a tap measures to: the nearest vertex of the hit triangle, curve segment or
// point when it is within SNAP_PX of the finger, otherwise the hit point itself.
function measureHitAt(clientX, clientY) {
  setRay(clientX, clientY);
  const hit = bestHit(raycaster.intersectObjects(pickCandidates(true), false));
  if (!hit) return null;
  const node = hit.object;
  const finger = new THREE.Vector2(clientX, clientY);
  const position = node.geometry.getAttribute('position');
  const world = (index) => new THREE.Vector3().fromBufferAttribute(position, index).applyMatrix4(node.matrixWorld);

  if (node.isPoints) return { point: world(hit.index), snap: 'point' };

  const candidates = [];
  if (node.isMesh && hit.face) {
    candidates.push([world(hit.face.a), 'vertex'], [world(hit.face.b), 'vertex'], [world(hit.face.c), 'vertex']);
  } else if (node.isLine && hit.index !== undefined) {
    const last = position.count - 1;
    for (const index of [hit.index, hit.index + 1]) {
      if (index < 0 || index > last) continue;
      candidates.push([world(index), index === 0 || index === last ? 'end' : 'vertex']);
    }
  }
  let best = null;
  let bestDistance = SNAP_PX;
  for (const [point, snap] of candidates) {
    const distance = toScreen(point).distanceTo(finger);
    if (distance <= bestDistance) {
      best = { point, snap };
      bestDistance = distance;
    }
  }
  if (best) return best;
  const point = node.isLine ? (hit.pointOnLine || hit.point).clone() : hit.point.clone();
  return { point, snap: node.isLine ? 'curve' : 'surface' };
}

function measureAt(clientX, clientY) {
  const found = measureHitAt(clientX, clientY);
  if (!found) return;
  if (measure.points.length >= 2) {
    measure.points = [];
    measure.snaps = [];
  }
  measure.points.push(found.point);
  measure.snaps.push(found.snap);
  rebuildMeasureOverlay();
  emitMeasure();
}

function disposeMeasureOverlay() {
  if (!measure.group) return;
  scene.remove(measure.group);
  measure.group.traverse((node) => {
    if (node.geometry) node.geometry.dispose();
    if (node.material) {
      if (node.material.map) node.material.map.dispose();
      node.material.dispose();
    }
  });
  measure.group = null;
  measure.label = null;
}

function overlayMaterial(Type, options) {
  const material = new Type({ depthTest: false, depthWrite: false, transparent: true, ...options });
  material.toneMapped = false;
  return material;
}

function labelSprite(text) {
  const ctx = document.createElement('canvas').getContext('2d');
  const fontPx = 44;
  const font = `600 ${fontPx}px ui-monospace, "Roboto Mono", Menlo, Consolas, monospace`;
  ctx.font = font;
  const width = Math.ceil(ctx.measureText(text).width) + 32;
  const height = fontPx + 24;
  ctx.canvas.width = width;
  ctx.canvas.height = height;
  ctx.fillStyle = 'rgba(14,16,19,0.92)';
  ctx.fillRect(0, 0, width, height);
  ctx.strokeStyle = '#FFB020';
  ctx.lineWidth = 3;
  ctx.strokeRect(1.5, 1.5, width - 3, height - 3);
  ctx.font = font;
  ctx.fillStyle = '#FFB020';
  ctx.textBaseline = 'middle';
  ctx.textAlign = 'center';
  ctx.fillText(text, width / 2, height / 2 + 2);
  const texture = new THREE.CanvasTexture(ctx.canvas);
  texture.colorSpace = THREE.SRGBColorSpace;
  const sprite = new THREE.Sprite(overlayMaterial(THREE.SpriteMaterial, { map: texture }));
  sprite.userData.aspect = width / height;
  sprite.renderOrder = 6;
  return sprite;
}

function formatLength(value) {
  const abs = Math.abs(value);
  const digits = abs >= 1000 ? 1 : abs >= 1 ? 2 : 4;
  return value.toFixed(digits);
}

function rebuildMeasureOverlay() {
  disposeMeasureOverlay();
  if (!measure.points.length) {
    requestRender();
    return;
  }
  const group = new THREE.Group();
  group.userData.viewerHelper = true;
  const [a, b] = measure.points;

  const markers = new THREE.BufferGeometry().setFromPoints(measure.points);
  const dots = new THREE.Points(markers, overlayMaterial(THREE.PointsMaterial, { color: MEASURE_COLOR, size: 12, sizeAttenuation: false }));
  dots.renderOrder = 5;
  group.add(dots);

  if (b) {
    const line = new THREE.Line(new THREE.BufferGeometry().setFromPoints([a, b]), overlayMaterial(THREE.LineBasicMaterial, { color: MEASURE_COLOR }));
    line.renderOrder = 5;
    group.add(line);
    // Axis legs: X, then Y, then Z, from the first point.
    const legs = [a, new THREE.Vector3(b.x, a.y, a.z), new THREE.Vector3(b.x, b.y, a.z), b];
    const legLine = new THREE.Line(
      new THREE.BufferGeometry().setFromPoints(legs),
      overlayMaterial(THREE.LineDashedMaterial, { color: MEASURE_LEG_COLOR, dashSize: 1, gapSize: 1, opacity: 0.8 }),
    );
    legLine.computeLineDistances();
    legLine.userData.dashed = true;
    legLine.renderOrder = 4;
    group.add(legLine);
    const label = labelSprite(formatLength(a.distanceTo(b)));
    label.position.copy(a).add(b).multiplyScalar(0.5);
    group.add(label);
    measure.label = label;
  }
  scene.add(group);
  measure.group = group;
  requestRender();
}

// Keeps the distance label and the leg dashes a constant size on screen.
function updateMeasureLabel() {
  if (!measure.group) return;
  if (measure.label) {
    const upp = unitsPerPixel(measure.label.position);
    measure.label.scale.set(LABEL_PX * measure.label.userData.aspect * upp, LABEL_PX * upp, 1);
  }
  for (const node of measure.group.children) {
    if (!node.userData.dashed) continue;
    const upp = unitsPerPixel(measure.points[0]);
    node.material.dashSize = 8 * upp;
    node.material.gapSize = 6 * upp;
  }
}

function emitMeasure() {
  const [a, b] = measure.points;
  emit('measure', {
    points: measure.points.map((p) => [p.x, p.y, p.z]),
    snaps: measure.snaps.slice(),
    distance: b ? a.distanceTo(b) : null,
    delta: b ? [b.x - a.x, b.y - a.y, b.z - a.z] : null,
  });
}

function clearMeasure() {
  measure.points = [];
  measure.snaps = [];
  rebuildMeasureOverlay();
  emitMeasure();
}

function setMeasureMode(active) {
  measure.active = Boolean(active);
  if (measure.active) setPicked(null);
  clearMeasure();
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
    // There is now something on screen, so a later error is reported without covering it.
    bootstrap.contentShown(true);
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
    if (!attributes) return;
    if (ANNOTATION_TYPES.has(obj.userData.objectType)) {
      colorAnnotationParts(obj, displayColorHex(objectColorHex(attributes, layers)));
      return;
    }
    if (!(obj.isMesh || obj.isLine || obj.isPoints)) return;
    loaderMaterials.add(obj.material);
    const hex = displayColorHex(objectColorHex(attributes, layers));
    obj.userData.displayHex = hex;
    if (obj.isMesh) obj.material = meshMaterialFor(hex);
    else if (obj.isLine) obj.material = lineMaterialFor(hex);
    else obj.material = pointMaterialFor(hex, obj.geometry.hasAttribute('color'));
  });
  for (const material of loaderMaterials) material.dispose();
  loader.materials = [];

  model.add(root);
  scaledParts = collectScaledParts(root);
  layerVisible = layers.map((layer) => layer.visible !== false);
  for (const category of CATEGORIES) {
    categoryVisible[category] = true;
    categoryPickable[category] = true;
  }
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
  const counts = { meshes: 0, curves: 0, points: 0, pointClouds: 0, blocks: 0, lights: lightCount, annotations: 0, hatches: 0, other: 0 };
  const categories = Object.fromEntries(CATEGORIES.map((category) => [category, 0]));
  let triangles = 0;
  let vertices = 0;
  let curvePoints = 0;
  const layerCounts = new Array(layers.length).fill(0);

  for (const child of root.children) {
    const type = child.userData.objectType;
    if (MESH_TYPES.has(type)) counts.meshes += 1;
    else if (type === 'Curve') counts.curves += 1;
    else if (type === 'Point') counts.points += 1;
    else if (type === 'PointSet') counts.pointClouds += 1;
    else if (type === 'InstanceReference') counts.blocks += 1;
    else if (type === 'Annotation') counts.annotations += 1;
    else if (type === 'Hatch') counts.hatches += 1;
    else counts.other += 1;
    if (CATEGORY_OF[type]) categories[CATEGORY_OF[type]] += 1;
  }
  root.traverse((obj) => {
    const attributes = obj.userData.attributes;
    if (attributes && attributes.layerIndex >= 0 && attributes.layerIndex < layerCounts.length) {
      layerCounts[attributes.layerIndex] += 1;
    }
  });
  root.traverseVisible((obj) => {
    if (obj.isLine && obj.userData.objectType === 'Curve') {
      const curve = obj.geometry.getAttribute('position');
      if (curve) curvePoints += curve.count;
      return;
    }
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
    curvePoints,
    layers: layers.map((layer, index) => ({
      index,
      name: layer.name || '',
      fullPath: layer.fullPath || layer.name || '',
      color: hexString(layer.color ? colorToHex(layer.color) : 0),
      visible: layer.visible !== false,
      objectCount: layerCounts[index],
    })),
    categories,
    unmeshed,
    bbox,
    units,
    curveQuality: loader.curveQuality,
    timings,
    warnings,
  };
}

function disposeObject(root) {
  root.traverse((obj) => {
    if (obj.geometry && !obj.geometry.userData.shared) obj.geometry.dispose();
    if (obj.material && obj.material.userData && obj.material.userData.perObject) obj.material.dispose();
    if (obj.isSprite && obj.material) {
      if (obj.material.map) obj.material.map.dispose();
      obj.material.dispose();
    }
  });
}

function clear() {
  unpick();
  if (measure.points.length) clearMeasure();
  if (modelRoot) {
    model.remove(modelRoot);
    disposeObject(modelRoot);
    modelRoot = null;
  }
  scaledParts = [];
  disposeAnnotationResources();
  disposeRenderMaterials();
  edgeJob = null;
  for (const geometry of edgeGeometries.values()) geometry.dispose();
  edgeGeometries.clear();
  for (const cache of [meshMaterials, lineMaterials, pointMaterials, flatMaterials]) {
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
  updateShadowRig();
  bootstrap.contentShown(false);
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
  // Annotation and hatch parts take their group's colour.
  const attributesOf = (obj) => obj.userData.attributes || (obj.parent && obj.parent.userData.attributes) || {};
  const materialFor = (obj) => {
    const hex = objectColorHex(attributesOf(obj), layers);
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
      // Labels and arrowheads are screen-sized textures and glyphs, not model geometry.
      if (child.userData.viewerEdges || child.userData.viewerHighlight || isScaledPart(child)) obj.remove(child);
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
// Diagnostics
// ---------------------------------------------------------------------------------------

// A cheap, never-throwing snapshot for a bug report: what the WebView really handed the
// page (WebGL support, the driver's own renderer string, the canvas being drawn into),
// how far start-up got, the last log events and what is loaded. Shape in ARCHITECTURE.md.
function diagnostics() {
  const info = bootstrap.diagnostics();
  try {
    info.three = 'r' + THREE.REVISION;
    info.rhino3dm = { version: RHINO3DM_VERSION, worker: workerState };
    if (renderer) {
      info.webgl = bootstrap.webglInfo(renderer.getContext());
      if (info.canvas) info.canvas.pixelRatio = renderer.getPixelRatio();
    }
    info.model = stats && {
      name: modelName,
      objects: stats.objects,
      meshes: stats.meshes,
      triangles: stats.triangles,
      vertices: stats.vertices,
      layers: stats.layers.length,
      unmeshed: stats.unmeshed.total,
      units: stats.units,
      bbox: stats.bbox,
    };
  } catch (error) {
    info.error = errorMessage(error);
  }
  return info;
}

// ---------------------------------------------------------------------------------------
// Public API
// ---------------------------------------------------------------------------------------

function installApi() {
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
      setCategoryVisible('curves', visible);
    },
    setPointsVisible(visible) {
      setCategoryVisible('points', visible);
    },
    setCategoryVisible,
    setCategoryPickable,
    // Applies to the next load(): curves are sampled while the file is parsed.
    setCurveQuality(quality) {
      if (!CURVE_QUALITIES.includes(quality)) {
        log('warn', `Unknown curve quality "${quality}"`);
        return;
      }
      loader.curveQuality = quality;
    },
    setRenderQuality(quality) {
      if (!RENDER_QUALITIES.includes(quality)) {
        log('warn', `Unknown render quality "${quality}"`);
        return;
      }
      if (quality === renderQuality) return;
      renderQuality = quality;
      if (displayMode === 'rendered') {
        // Rebuild the render materials with or without textures.
        const previous = picked;
        unpick();
        forEachMesh((mesh) => {
          if (shadedMaterialOf.has(mesh)) mesh.material = shadedMaterialOf.get(mesh);
        });
        disposeRenderMaterials();
        applyRenderedMaterials();
        if (previous) highlight(previous.target, previous.hit);
      }
      requestRender();
    },
    setMeasureMode,
    clearMeasure,
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
    diagnostics,
  });
}

// ---------------------------------------------------------------------------------------
// Start-up
// ---------------------------------------------------------------------------------------

let workerReady = null;
let workerState = 'pending';

// Fetches rhino3dm and spawns the decode worker. The worker's `_ready` (patched loader,
// see PATCHES.md) settles once rhino3dm is instantiated inside it, so viewerReady means
// the first load only pays for parsing, and an initialisation failure fails every load()
// instead of hanging it.
function startRhino3dm() {
  workerReady = loader._initLibrary()
    .then(() => loader._getWorker(0))
    .then((worker) => worker._ready);
  workerReady
    .then(() => {
      workerState = 'ready';
      emit('viewerReady', { three: 'r' + THREE.REVISION, rhino3dm: RHINO3DM_VERSION });
    })
    .catch((error) => {
      workerState = 'failed';
      bootstrap.fail('3D files cannot be opened on this device', `rhino3dm initialisation failed: ${errorMessage(error)}`);
    });
}

// Everything that needs a GPU context. Nothing above this point touches WebGL, so any
// failure here is painted and reported instead of leaving a blank document behind.
function startViewer() {
  renderer = createRenderer();
  canvas = renderer.domElement;
  document.body.appendChild(canvas);
  attachCanvasListeners();
  attachPointerListeners();
  observeViewport();
  createControls();
  applyViewportSize();
  if (appliedWidth <= 1 || appliedHeight <= 1) {
    log('warn', `The page has no size yet (${appliedWidth}x${appliedHeight} px); waiting for a resize`);
  }
  // Frame an empty unit scene, so an empty viewer still has a usable camera.
  const unitBox = new THREE.Box3(new THREE.Vector3(-1, -1, -1), new THREE.Vector3(1, 1, 1));
  framePoints(new THREE.Vector3(), modelRadius, (fn) => boxCorners(unitBox, fn));
  installApi();
  bootstrap.booted();
  startRhino3dm();
}

try {
  startViewer();
} catch (error) {
  bootstrap.fail('The 3D viewer could not start', errorMessage(error));
}
