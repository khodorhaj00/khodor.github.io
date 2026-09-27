// ---------------------------------------------------------------------------------------
// View cube: a small CSS 3D cube in the top-right corner that turns with the camera.
// Tap a face for that view, ISO for the perspective view. Rhino conventions: Z up,
// Front looks from -Y. Sizes and colours are in viewer.css (.viewcube*); the labels are
// FACES below.
// ---------------------------------------------------------------------------------------

// n: outward normal, u: the face's right, v: the face's up (world, Z up); u × v = n.
const FACES = [
  { view: 'top', label: 'TOP', n: [0, 0, 1], u: [1, 0, 0], v: [0, 1, 0] },
  { view: 'bottom', label: 'BTM', n: [0, 0, -1], u: [1, 0, 0], v: [0, -1, 0] },
  { view: 'front', label: 'FRONT', n: [0, -1, 0], u: [1, 0, 0], v: [0, 0, 1] },
  { view: 'back', label: 'BACK', n: [0, 1, 0], u: [-1, 0, 0], v: [0, 0, 1] },
  { view: 'right', label: 'RIGHT', n: [1, 0, 0], u: [0, 1, 0], v: [0, 0, 1] },
  { view: 'left', label: 'LEFT', n: [-1, 0, 0], u: [0, -1, 0], v: [0, 0, 1] },
];
const AXES = [
  { label: 'X', dir: [1, 0, 0], cls: 'x' },
  { label: 'Y', dir: [0, 1, 0], cls: 'y' },
  { label: 'Z', dir: [0, 0, 1], cls: 'z' },
];

/** Half the cube's edge in CSS px; keep in step with .viewcube-face in viewer.css. */
const HALF = 26;

/**
 * Builds the cube into document.body. [onView] gets 'top', 'front', ..., or 'iso'.
 * Returns { update(camera), setTop(px), setVisible(bool) }.
 */
export function createViewCube(onView) {
  const root = document.createElement('div');
  root.className = 'viewcube';
  root.setAttribute('aria-label', 'View cube');

  const stage = document.createElement('div');
  stage.className = 'viewcube-stage';
  root.appendChild(stage);

  const faces = FACES.map((face) => {
    const el = document.createElement('button');
    el.type = 'button';
    el.className = 'viewcube-face';
    el.textContent = face.label;
    el.dataset.view = face.view;
    el.addEventListener('click', (event) => {
      event.stopPropagation();
      onView(face.view);
    });
    stage.appendChild(el);
    return { face, el };
  });

  const axes = AXES.map((axis) => {
    const el = document.createElement('span');
    el.className = `viewcube-axis viewcube-axis-${axis.cls}`;
    el.textContent = axis.label;
    stage.appendChild(el);
    return { axis, el };
  });

  const iso = document.createElement('button');
  iso.type = 'button';
  iso.className = 'viewcube-iso';
  iso.textContent = 'ISO';
  iso.dataset.view = 'iso';
  iso.addEventListener('click', (event) => {
    event.stopPropagation();
    onView('iso');
  });
  root.appendChild(iso);

  // Taps on the cube must not reach the canvas (orbit, pick, caliper).
  for (const type of ['pointerdown', 'pointerup', 'touchstart', 'touchend']) {
    root.addEventListener(type, (event) => event.stopPropagation());
  }

  document.body.appendChild(root);

  // World → CSS: the camera's rotation, then flip Y (CSS y points down).
  const m = new Array(9).fill(0);
  const toCss = (w) => [
    m[0] * w[0] + m[3] * w[1] + m[6] * w[2],
    -(m[1] * w[0] + m[4] * w[1] + m[7] * w[2]),
    m[2] * w[0] + m[5] * w[1] + m[8] * w[2],
  ];

  function update(camera) {
    const e = camera.matrixWorldInverse.elements;
    m[0] = e[0]; m[1] = e[1]; m[2] = e[2];
    m[3] = e[4]; m[4] = e[5]; m[5] = e[6];
    m[6] = e[8]; m[7] = e[9]; m[8] = e[10];
    for (const { face, el } of faces) {
      const a = toCss(face.u);
      const b = toCss(face.v.map((x) => -x));
      const c = toCss(face.n);
      const t = c.map((x) => x * HALF);
      el.style.transform = `matrix3d(${a[0]},${a[1]},${a[2]},0,${b[0]},${b[1]},${b[2]},0,`
        + `${c[0]},${c[1]},${c[2]},0,${t[0]},${t[1]},${t[2]},1)`;
    }
    for (const { axis, el } of axes) {
      const p = toCss(axis.dir);
      const r = HALF * 1.75;
      el.style.transform = `translate(${p[0] * r}px, ${p[1] * r}px) translateZ(${HALF * 3}px)`;
    }
  }

  return {
    update,
    /** Distance from the top of the page, to clear the app's header. */
    setTop(px) {
      const value = Number(px);
      if (Number.isFinite(value) && value >= 0) root.style.top = `${value}px`;
    },
    setVisible(visible) {
      root.hidden = !visible;
    },
  };
}
