import * as THREE from 'three';

import {
  ANNOTATION_COLORS,
  ANNOTATION_FONTS,
  ANNOTATION_SIZES,
  DEFAULT_FONT_STACK,
  DEFAULT_QUALITY,
  DIMENSION_KINDS,
  FONT_ALIASES,
  MIN_ARROW_PX,
  MIN_TEXT_PX,
  MM_PER_MODEL_UNIT,
  QUALITY,
  UNITS,
} from './config.js';

// ---------------------------------------------------------------------------------------
// Annotations (dimensions, text, leaders) and hatches
// ---------------------------------------------------------------------------------------
//
// The patched loader worker (PATCHES.md, `annotations`) hands over world-space lines,
// arrowheads, one text placement and the measured value per annotation, and the 2D boundary
// loops of each hatch. This module turns them into three.js objects: a Group per Rhino
// object carrying the object's attributes and the worker's payload, so a change of options
// (size, colour, font, unit, quality) rebuilds it without re-reading the file.
//
// Sizes, fonts and justification are the file's (PATCHES.md), each multiplied by the chosen
// annotation size. A label or an arrowhead is never drawn smaller than a few pixels
// (updateAnnotationScale()), and labels whose style says "draw forward" turn to read left to
// right from the camera, as Rhino draws them.

const CAP_HEIGHT = 0.716; // Arial / Liberation Sans cap height as a fraction of the em
const LINE_HEIGHT = 1.3; // em
const PAD_PX = 8;
const MAX_TEXTURE_PX = 2048;
const MAX_LABELS = 3000;
const HATCH_SOLID_OPACITY = 0.85;
const HATCH_PATTERN_OPACITY = 0.35;

const textures = new Map();
const templates = new Map();
const arrowGeometries = new Map();
// Parts are coloured by viewer.js; until then they share these.
const placeholderMesh = new THREE.MeshBasicMaterial();
const placeholderLine = new THREE.LineBasicMaterial();
let labelCount = 0;

export const ANNOTATION_TYPES = new Set(['Annotation', 'Hatch']);

/** What annotations are built with; viewer.js owns the live copy (see config.js). */
export const annotationOptions = {
  quality: DEFAULT_QUALITY,
  size: 'medium',
  dimColor: 'file',
  dimFont: 'file',
  textColor: 'file',
  textFont: 'file',
  unit: 'cm',
  unitFactor: 1,
  modelUnits: 'Millimeters',
};

const v3 = (a) => new THREE.Vector3(a[0], a[1], a[2]);

function fontPx() {
  return (QUALITY[annotationOptions.quality] || QUALITY[DEFAULT_QUALITY]).fontPx;
}

function sizeFactor() {
  return ANNOTATION_SIZES[annotationOptions.size] ?? 1;
}

export function isDimension(kind) {
  return DIMENSION_KINDS.has(kind);
}

/** The colour chosen for this kind of annotation, or null to keep the object's own. */
export function colorChoiceFor(kind) {
  const choice = isDimension(kind) ? annotationOptions.dimColor : annotationOptions.textColor;
  return ANNOTATION_COLORS[choice] ?? null;
}

function fontStackFor(g) {
  const choice = isDimension(g.kind) ? annotationOptions.dimFont : annotationOptions.textFont;
  const chosen = ANNOTATION_FONTS[choice];
  if (chosen) return chosen;
  // 'file': the Rhino font first, then the bundled face with the same metrics.
  const family = (g.font || '').replace(/["\\]/g, '');
  const alias = FONT_ALIASES.find((entry) => entry.match.test(family));
  const fallback = alias ? alias.stack : DEFAULT_FONT_STACK;
  return family ? `"${family}", ${fallback}` : fallback;
}

// ---------------------------------------------------------------------------------------
// Text: the number a dimension shows, and the texture it is drawn into
// ---------------------------------------------------------------------------------------

function formatLength(value, unit) {
  const text = value.toFixed(unit.decimals);
  return unit.label ? `${text} ${unit.label}` : text;
}

/** Millimetres per unit of the model, or null when the file does not say. */
export function mmPerModelUnit() {
  return MM_PER_MODEL_UNIT[annotationOptions.modelUnits] ?? null;
}

/**
 * What a label reads: the file's own text in `file` units, otherwise the measurement the
 * worker took, converted. An annotation with no measurement (angles, ordinates, text and
 * leaders) keeps its text either way.
 */
export function labelText(g) {
  const unit = UNITS[annotationOptions.unit];
  if (!unit || !g.measure || annotationOptions.unit === 'file') return g.text || '';
  const prefix = g.measure.prefix || '';
  if (annotationOptions.unit === 'custom') {
    return prefix + formatLength(g.measure.value * (annotationOptions.unitFactor || 1), unit);
  }
  const mm = mmPerModelUnit();
  if (mm === null) return g.text || '';
  return prefix + formatLength((g.measure.value * mm) / unit.mmPerUnit, unit);
}

// The bundled Liberation faces match Arial, Times and Courier metrics, so text keeps
// Rhino's spacing whichever font the file asks for.
function textTexture(stack, bold, italic, text, align) {
  const px = fontPx();
  const key = `${stack}|${bold}|${italic}|${px}\n${align}\n${text}`;
  let entry = textures.get(key);
  if (entry) return entry;
  const lines = text.split(/\r\n|\r|\n/);
  const ctx = document.createElement('canvas').getContext('2d');
  let usedPx = px;
  const weight = `${italic ? 'italic ' : ''}${bold ? 'bold ' : ''}`;
  const fontSpec = (size) => `${weight}${size}px ${stack}`;
  ctx.font = fontSpec(usedPx);
  let textWidth = Math.max(1, ...lines.map((line) => ctx.measureText(line).width));
  // Very long text is drawn with a smaller font so the texture stays within limits.
  if (textWidth + PAD_PX * 2 > MAX_TEXTURE_PX) {
    usedPx = Math.max(8, Math.floor((usedPx * (MAX_TEXTURE_PX - PAD_PX * 2)) / textWidth));
    ctx.font = fontSpec(usedPx);
    textWidth = Math.max(1, ...lines.map((line) => ctx.measureText(line).width));
  }
  const lineHeight = usedPx * LINE_HEIGHT;
  const width = Math.ceil(textWidth) + PAD_PX * 2;
  const height = Math.min(MAX_TEXTURE_PX, Math.ceil(PAD_PX * 2 + (lines.length - 1) * lineHeight + usedPx));
  ctx.canvas.width = width;
  ctx.canvas.height = height;
  ctx.font = fontSpec(usedPx);
  ctx.fillStyle = '#ffffff';
  ctx.textBaseline = 'alphabetic';
  ctx.textAlign = align === 'center' ? 'center' : align === 'right' ? 'right' : 'left';
  const x = align === 'center' ? width / 2 : align === 'right' ? width - PAD_PX : PAD_PX;
  lines.forEach((line, i) => ctx.fillText(line, x, PAD_PX + i * lineHeight + usedPx * CAP_HEIGHT));

  const texture = new THREE.CanvasTexture(ctx.canvas);
  texture.colorSpace = THREE.SRGBColorSpace;
  texture.anisotropy = 4;
  entry = { key, texture, width, height, fontPx: usedPx, lineHeight, lines: lines.length };
  textures.set(key, entry);
  return entry;
}

function templateMaterial(texture) {
  let material = templates.get(texture);
  if (!material) {
    material = new THREE.MeshBasicMaterial({ map: texture, transparent: true, depthWrite: false, side: THREE.DoubleSide });
    templates.set(texture, material);
  }
  return material;
}

// A label is an anchor (the annotation's text point, oriented +x reading direction, +y up)
// holding the text quad, laid out in that frame and centred on the text so turning it to
// read forward keeps it in place. `valign` says which part of the text sits on the anchor
// ('above' = the last baseline one text gap above it, as Rhino draws dimension text).
function buildLabel(g) {
  const text = labelText(g);
  if (!text || labelCount >= MAX_LABELS) return null;
  const label = g.label;
  const scale = sizeFactor();
  const tex = textTexture(fontStackFor(g), Boolean(g.bold), Boolean(g.italic), text, label.align);
  labelCount += 1;
  const textHeight = g.textHeight * scale;
  const gap = g.textGap * scale;
  // World size of one texture pixel, from the cap height.
  const k = textHeight / (CAP_HEIGHT * tex.fontPx);
  const w = tex.width * k;
  const h = tex.height * k;
  const capPx = tex.fontPx * CAP_HEIGHT;
  const lastLinePx = (tex.lines - 1) * tex.lineHeight;

  let left;
  if (label.align === 'center') left = -w / 2;
  else if (label.align === 'right') left = -w + PAD_PX * k;
  else left = -PAD_PX * k;
  // Distance from the quad's top edge down to the anchor, in texture pixels; the text block
  // runs from the first line's cap top to the last line's baseline.
  const anchorPx = {
    top: PAD_PX,
    middleOfTop: PAD_PX + capPx / 2,
    bottomOfTop: PAD_PX + capPx,
    middle: PAD_PX + (lastLinePx + capPx) / 2,
    middleOfBottom: PAD_PX + lastLinePx + capPx / 2,
    bottom: PAD_PX + lastLinePx + capPx,
    bottomOfBox: PAD_PX + lastLinePx + capPx + tex.fontPx * 0.21,
  };
  const top = label.valign in anchorPx ? anchorPx[label.valign] * k : anchorPx.bottom * k + gap; // 'above'
  const shift = label.gap ? (label.align === 'right' ? -gap : gap) : 0;

  const normal = v3(g.normal);
  const dir = v3(label.dir).normalize();
  const up = new THREE.Vector3().crossVectors(normal, dir).normalize();

  // The texture travels on the material: clones (block instances) share it, while their
  // userData is a JSON copy.
  const quad = new THREE.Mesh(new THREE.PlaneGeometry(w, h), templateMaterial(tex.texture));
  quad.position.set(left + w / 2 + shift, top - h / 2, 0);
  quad.renderOrder = 2;
  quad.userData.annotationPart = 'label';

  const anchor = new THREE.Object3D();
  anchor.quaternion.setFromRotationMatrix(new THREE.Matrix4().makeBasis(dir, up, new THREE.Vector3().crossVectors(dir, up)));
  anchor.position.copy(v3(label.point));
  anchor.userData.annotationPart = 'text';
  anchor.userData.worldSize = textHeight;
  anchor.userData.minPx = MIN_TEXT_PX;
  anchor.userData.drawForward = g.drawForward !== false;
  anchor.add(quad);
  return anchor;
}

// ---------------------------------------------------------------------------------------
// Arrowheads: unit shapes with the tip at the origin, pointing along +x
// ---------------------------------------------------------------------------------------

function triangle(length, halfWidth) {
  const geometry = new THREE.BufferGeometry();
  geometry.setAttribute('position', new THREE.Float32BufferAttribute([0, 0, 0, -length, halfWidth, 0, -length, -halfWidth, 0], 3));
  return geometry;
}

function arrowGeometry(type) {
  let entry = arrowGeometries.get(type);
  if (entry) return entry;
  switch (type) {
    case 'Dot':
      entry = { geometry: new THREE.CircleGeometry(0.25, 16), lines: false };
      break;
    case 'Tick': {
      const geometry = new THREE.BufferGeometry();
      geometry.setAttribute('position', new THREE.Float32BufferAttribute([-0.35, -0.35, 0, 0.35, 0.35, 0], 3));
      entry = { geometry, lines: true };
      break;
    }
    case 'OpenArrow': {
      const geometry = new THREE.BufferGeometry();
      geometry.setAttribute('position', new THREE.Float32BufferAttribute([0, 0, 0, -1, 0.2, 0, 0, 0, 0, -1, -0.2, 0], 3));
      entry = { geometry, lines: true };
      break;
    }
    case 'Rectangle': {
      const geometry = new THREE.PlaneGeometry(1, 0.33);
      geometry.translate(-0.5, 0, 0);
      entry = { geometry, lines: false };
      break;
    }
    case 'ShortTriangle':
      entry = { geometry: triangle(0.5, 0.2), lines: false };
      break;
    case 'LongTriangle':
      entry = { geometry: triangle(1, 0.125), lines: false };
      break;
    case 'LongerTriangle':
      entry = { geometry: triangle(1, 0.1), lines: false };
      break;
    default: // SolidTriangle, user blocks
      entry = { geometry: triangle(1, 0.1667), lines: false };
      break;
  }
  entry.geometry.userData.shared = true;
  arrowGeometries.set(type, entry);
  return entry;
}

function buildArrow(arrow, normalArray) {
  const { geometry, lines } = arrowGeometry(arrow.type);
  const dir = v3(arrow.dir).normalize();
  const normal = v3(normalArray);
  const side = new THREE.Vector3().crossVectors(normal, dir);
  if (side.lengthSq() < 1e-12) side.set(0, 0, 1).cross(dir);
  side.normalize();
  const size = arrow.size * sizeFactor();
  const object = lines ? new THREE.LineSegments(geometry, placeholderLine) : new THREE.Mesh(geometry, placeholderMesh);
  object.quaternion.setFromRotationMatrix(new THREE.Matrix4().makeBasis(dir, side, new THREE.Vector3().crossVectors(dir, side)));
  object.position.copy(v3(arrow.tip));
  object.scale.setScalar(size);
  object.userData.annotationPart = 'arrow';
  object.userData.worldSize = size;
  object.userData.minPx = MIN_ARROW_PX;
  return object;
}

// ---------------------------------------------------------------------------------------
// Builders
// ---------------------------------------------------------------------------------------

function tagObject(group, obj, type) {
  const attributes = obj.attributes;
  group.userData.attributes = attributes;
  group.userData.objectType = type;
  if (attributes.name) group.name = attributes.name;
}

/** One annotation's parts, from the worker's payload; rebuilt when options change. */
function annotationParts(group) {
  const g = group.userData.annotationData;
  if (!g) return;
  const positions = g.lines.slice();
  if (g.dimensionLine) positions.push(...g.dimensionLine);
  if (positions.length) {
    const geometry = new THREE.BufferGeometry();
    geometry.setAttribute('position', new THREE.Float32BufferAttribute(positions, 3));
    const segments = new THREE.LineSegments(geometry, placeholderLine);
    segments.userData.annotationPart = 'lines';
    group.add(segments);
  }
  for (const arrow of g.arrows) group.add(buildArrow(arrow, g.normal));
  if (g.label) {
    const label = buildLabel(g);
    if (label) group.add(label);
  }
  group.userData.text = labelText(g);
}

export function buildAnnotation(obj) {
  const group = new THREE.Group();
  tagObject(group, obj, 'Annotation');
  group.userData.annotationKind = obj.geometry.kind;
  group.userData.annotationData = obj.geometry;
  annotationParts(group);
  return group.children.length ? group : undefined;
}

/** Throws an annotation's parts away and builds them again with the current options. */
export function rebuildAnnotation(group) {
  for (const child of [...group.children]) {
    group.remove(child);
    disposePart(child);
  }
  annotationParts(group);
}

function disposePart(part) {
  part.traverse((node) => {
    if (node.userData.annotationPart === 'text') labelCount = Math.max(0, labelCount - 1);
    if (node.geometry && !node.geometry.userData.shared) node.geometry.dispose();
    if (node.material && node.material.userData && node.material.userData.perObject) node.material.dispose();
  });
}

function pointInPolygon(x, y, pts) {
  let inside = false;
  for (let i = 0, j = pts.length - 1; i < pts.length; j = i++) {
    const a = pts[i];
    const b = pts[j];
    if ((a.y > y) !== (b.y > y) && x < ((b.x - a.x) * (y - a.y)) / (b.y - a.y) + a.x) inside = !inside;
  }
  return inside;
}

function toVectors(flat) {
  const pts = [];
  for (let i = 0; i + 1 < flat.length; i += 2) pts.push(new THREE.Vector2(flat[i], flat[i + 1]));
  if (pts.length > 1 && pts[0].distanceToSquared(pts[pts.length - 1]) < 1e-18) pts.pop();
  return pts;
}

export function buildHatch(obj) {
  const g = obj.geometry;
  const origin = v3(g.plane.origin);
  const xAxis = v3(g.plane.xAxis);
  const yAxis = v3(g.plane.yAxis);
  const loops = g.loops.map((loop) => ({ outer: loop.outer, pts: toVectors(loop.points) })).filter((loop) => loop.pts.length >= 3);
  if (!loops.length) return undefined;

  let outers = loops.filter((loop) => loop.outer);
  const holes = loops.filter((loop) => !loop.outer);
  if (!outers.length) outers = loops;
  const shapes = outers.map((loop) => ({ contour: loop.pts, holes: [] }));
  for (const hole of holes) {
    if (outers === loops) break;
    const p = hole.pts[0];
    const owner = shapes.find((shape) => pointInPolygon(p.x, p.y, shape.contour)) || shapes[0];
    owner.holes.push(hole.pts);
  }

  const to3d = (p, out) => {
    out.push(
      origin.x + p.x * xAxis.x + p.y * yAxis.x,
      origin.y + p.x * xAxis.y + p.y * yAxis.y,
      origin.z + p.x * xAxis.z + p.y * yAxis.z,
    );
  };

  const positions = [];
  const indices = [];
  for (const shape of shapes) {
    const base = positions.length / 3;
    const faces = THREE.ShapeUtils.triangulateShape(shape.contour, shape.holes);
    for (const p of shape.contour) to3d(p, positions);
    for (const hole of shape.holes) for (const p of hole) to3d(p, positions);
    for (const face of faces) indices.push(base + face[0], base + face[1], base + face[2]);
  }

  const group = new THREE.Group();
  tagObject(group, obj, 'Hatch');
  group.userData.hatchSolid = g.patternIndex === 0;

  if (indices.length) {
    const geometry = new THREE.BufferGeometry();
    geometry.setAttribute('position', new THREE.Float32BufferAttribute(positions, 3));
    geometry.setIndex(indices);
    const fill = new THREE.Mesh(geometry, placeholderMesh);
    fill.userData.annotationPart = 'fill';
    fill.userData.opacity = group.userData.hatchSolid ? HATCH_SOLID_OPACITY : HATCH_PATTERN_OPACITY;
    group.add(fill);
  }

  const outline = [];
  const a = [];
  const b = [];
  for (const loop of loops) {
    for (let i = 0; i < loop.pts.length; i++) {
      a.length = 0;
      b.length = 0;
      to3d(loop.pts[i], a);
      to3d(loop.pts[(i + 1) % loop.pts.length], b);
      outline.push(...a, ...b);
    }
  }
  const outlineGeometry = new THREE.BufferGeometry();
  outlineGeometry.setAttribute('position', new THREE.Float32BufferAttribute(outline, 3));
  const segments = new THREE.LineSegments(outlineGeometry, placeholderLine);
  segments.userData.annotationPart = 'lines';
  group.add(segments);
  return group;
}

// ---------------------------------------------------------------------------------------
// Per-frame scaling and orientation, disposal
// ---------------------------------------------------------------------------------------

const _position = new THREE.Vector3();
const _right = new THREE.Vector3();
const _up = new THREE.Vector3();
const _normal = new THREE.Vector3();
const _camRight = new THREE.Vector3();
const _camUp = new THREE.Vector3();
const _toCamera = new THREE.Vector3();

// Rhino's "draw forward": mirror a label seen from behind its plane, and turn it half way
// round when it would read right to left (or top to bottom when vertical).
function orientLabel(anchor, camera) {
  const quad = anchor.children[0];
  if (!quad) return;
  anchor.updateWorldMatrix(true, false);
  anchor.matrixWorld.extractBasis(_right, _up, _normal);
  _position.setFromMatrixPosition(anchor.matrixWorld);
  camera.matrixWorld.extractBasis(_camRight, _camUp, _toCamera);
  if (camera.isPerspectiveCamera) _toCamera.setFromMatrixPosition(camera.matrixWorld).sub(_position);
  let sx = _normal.dot(_toCamera) >= 0 ? 1 : -1;
  let sy = 1;
  const across = _right.dot(_camRight) * sx;
  const upward = _right.dot(_camUp) * sx;
  if (across < -1e-3 || (Math.abs(across) <= 1e-3 && upward < 0)) {
    sx = -sx;
    sy = -1;
  }
  if (quad.scale.x !== sx || quad.scale.y !== sy) quad.scale.set(sx, sy, 1);
}

// Keeps labels and arrowheads at least a few pixels tall. `parts` is the list collected by
// collectScaledParts(); only visible parts are touched.
export function updateAnnotationScale(parts, camera, viewportHeight) {
  if (!parts.length) return;
  // The controls move the camera without refreshing its world matrix; the renderer only
  // does that inside render(), after this runs.
  camera.updateMatrixWorld();
  const orthoUnits = camera.isOrthographicCamera ? (camera.top - camera.bottom) / camera.zoom / viewportHeight : 0;
  const perspUnits = camera.isPerspectiveCamera ? (2 * Math.tan(THREE.MathUtils.degToRad(camera.fov) / 2)) / viewportHeight : 0;
  for (const part of parts) {
    if (!isShown(part)) continue;
    let unitsPerPx = orthoUnits;
    if (!orthoUnits) {
      part.getWorldPosition(_position);
      unitsPerPx = perspUnits * Math.max(_position.distanceTo(camera.position), 1e-9);
    }
    const size = Math.max(part.userData.worldSize, part.userData.minPx * unitsPerPx);
    const isText = part.userData.annotationPart === 'text';
    const scale = isText ? size / part.userData.worldSize : size;
    if (Math.abs(part.scale.x - scale) > scale * 1e-3) {
      part.scale.setScalar(scale);
      part.updateMatrixWorld();
    }
    if (isText && part.userData.drawForward) orientLabel(part, camera);
  }
}

function isShown(obj) {
  for (let o = obj; o; o = o.parent) if (!o.visible) return false;
  return true;
}

export function collectScaledParts(root) {
  const parts = [];
  root.traverse((obj) => {
    const part = obj.userData.annotationPart;
    if ((part === 'text' || part === 'arrow') && obj.userData.worldSize > 0) parts.push(obj);
  });
  return parts;
}

// True for parts whose drawn size follows the zoom, which framing must ignore.
export function isScaledPart(obj) {
  const part = obj.userData.annotationPart;
  return part === 'text' || part === 'label' || part === 'arrow';
}

// The annotation or hatch group a drawn part belongs to.
export function annotationOwner(obj) {
  for (let o = obj.parent; o; o = o.parent) {
    if (ANNOTATION_TYPES.has(o.userData.objectType)) return o;
  }
  return null;
}

// Frees every label texture; called when the model is cleared.
export function disposeAnnotationResources() {
  for (const material of templates.values()) material.dispose();
  templates.clear();
  for (const entry of textures.values()) entry.texture.dispose();
  textures.clear();
  labelCount = 0;
}

export function annotationStats() {
  return { labels: labelCount, textures: textures.size };
}
