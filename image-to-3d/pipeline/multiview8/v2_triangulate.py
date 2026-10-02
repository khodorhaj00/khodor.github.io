"""Multi-view triangulation of the 478 MediaPipe face points (orthographic cameras around the vertical axis).
Unknowns: 3D points, per-view azimuth (front fixed at 0), scale, offset, roll; one common camera elevation.
Visibility per view from MediaPipe's own mesh normals (hidden points are not used)."""
import json, sys, numpy as np, cv2
FIX_E = float(sys.argv[1]) if len(sys.argv) > 1 else None
from scipy.optimize import least_squares
tris = np.load("canon_tris.npy")
VIEWS = {"v000": 0.0, "v045": 45.0, "v315": -45.0}
obs = {}; vis = {}
def vnormals(P):
    n = np.zeros_like(P); a, b, c = P[tris[:, 0]], P[tris[:, 1]], P[tris[:, 2]]
    fn = np.cross(b - a, c - a)
    for k in range(3): np.add.at(n, tris[:, k], fn)
    return n / np.maximum(np.linalg.norm(n, axis=1, keepdims=True), 1e-9)
for v in VIEWS:
    p = np.load("out/mp_%s.npy" % v)[:468]
    Q = np.c_[p[:, 0], -p[:, 1], -p[:, 2]]               # x right, y up, z toward camera
    n = vnormals(Q)
    if np.median(n[:, 2]) < 0: n = -n
    obs[v] = p[:, :2]; vis[v] = n[:, 2] > 0.30
    print("%s: %d / 468 points facing the camera" % (v, vis[v].sum()))
names = list(VIEWS)
nv = len(names)
cnt = sum(vis[v].astype(int) for v in names)
use = cnt >= 2
print("points seen in >= 2 views: %d (in 3+: %d)" % (use.sum(), (cnt >= 3).sum()))
idx = np.nonzero(use)[0]; npnt = len(idx)
# init: front view points, depth from mediapipe z (px), centred
p0 = np.load("out/mp_v000.npy")[:468]
c0 = p0[idx, :2].mean(0)
P0 = np.c_[p0[idx, 0] - c0[0], p0[idx, 2] * 1.05, -(p0[idx, 1] - c0[1])]        # model: X right, Y away from front cam, Z up
def unpack(x):
    k = 0; th = {}; sc = {}; tx = {}; ty = {}; ro = {}
    for v in names:
        if v == "v000": th[v] = 0.0
        else: th[v] = x[k]; k += 1
        sc[v], tx[v], ty[v], ro[v] = x[k], x[k + 1], x[k + 2], x[k + 3]; k += 4
    e = x[k] if FIX_E is None else FIX_E; k += 1
    P = x[k:].reshape(-1, 3)
    return th, sc, tx, ty, ro, e, P
def project(P, th, s, tx, ty, ro, e):
    t = np.radians(th); el = np.radians(e)
    r = np.array([np.cos(t), -np.sin(t), 0.0]); upv = np.array([np.sin(t) * np.sin(el), np.cos(t) * np.sin(el), np.cos(el)])
    u = P @ r; w = P @ upv
    c, s_ = np.cos(np.radians(ro)), np.sin(np.radians(ro))
    uu = c * u - s_ * w; ww = s_ * u + c * w
    return np.c_[s * uu + tx, -s * ww + ty]
def resid(x):
    th, sc, tx, ty, ro, e, P = unpack(x)
    out = []
    for v in names:
        m = vis[v][idx]
        pr = project(P[m], th[v], sc[v], tx[v], ty[v], ro[v], e)
        out.append((pr - obs[v][idx][m]).ravel())
    return np.concatenate(out)
x0 = []
for v in names:
    if v != "v000": x0.append(VIEWS[v])
    pv = obs[v][idx]; x0 += [1.0, pv[:, 0].mean(), pv[:, 1].mean(), 0.0]
x0 += [5.0]
x0 = np.r_[np.array(x0), P0.ravel()]
sol = least_squares(resid, x0, loss="soft_l1", f_scale=1.5, max_nfev=400)
th, sc, tx, ty, ro, e, P = unpack(sol.x)
r = resid(sol.x).reshape(-1, 2); err = np.linalg.norm(r, axis=1)
print("solve: cost %.1f  reprojection px: p50 %.2f p90 %.2f max %.1f" % (sol.cost, np.median(err), np.percentile(err, 90), err.max()))
for v in names: print("  %s: azimuth %6.1f  scale %.3f  roll %5.2f" % (v, th[v], sc[v], ro[v]))
print("  camera elevation %.1f deg (looking down)" % e)
# per-view residual
k = 0
for v in names:
    m = vis[v][idx].sum(); ev = err[k:k + m]; k += m
    print("  %s residual p50 %.2f p90 %.2f px" % (v, np.median(ev), np.percentile(ev, 90)))
# full 468 set: points seen once keep their (front) estimate via the front view + mediapipe depth offset
Pfull = np.full((468, 3), np.nan); Pfull[idx] = P
json.dump(dict(azimuth=th, scale=sc, tx=tx, ty=ty, roll=ro, elevation=e), open("out/cams_face.json", "w"), indent=1)
np.save("out/face3d.npy", Pfull); np.save("out/face3d_idx.npy", idx)
# side view picture of the triangulated points vs the front view mediapipe depth guess
img = np.full((520, 1040, 3), 24, np.uint8)
def plot(Pts, ox, col):
    for p in Pts:
        if np.isnan(p).any(): continue
        y = int(260 - (p[2] - np.nanmean(Pts[:, 2])) * 1.6); x = int(ox + (p[1] - np.nanmean(Pts[:, 1])) * 1.6)
        cv2.circle(img, (x, y), 1, col, -1)
plot(P0 * 1.0, 260, (160, 160, 160)); plot(P, 780, (120, 255, 140))
cv2.putText(img, "1 view (MediaPipe depth guess)", (90, 30), cv2.FONT_HERSHEY_SIMPLEX, 0.6, (200, 200, 200), 1)
cv2.putText(img, "4 views triangulated", (680, 30), cv2.FONT_HERSHEY_SIMPLEX, 0.6, (140, 255, 160), 1)
cv2.imwrite("out/face3d_side.png", img)
