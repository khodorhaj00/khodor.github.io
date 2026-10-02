"""Stage 1: silhouette + landmarks -> per-row slice template, face displacement, ear, prior depth maps.
Working units: full-res image px (a = x right, b = y down, d = depth, smaller = closer to camera)."""
import numpy as np, cv2, json
from scipy import ndimage as ndi
from scipy.interpolate import UnivariateSpline, LinearNDInterpolator, RBFInterpolator
np.set_printoptions(suppress=True, precision=2)
W = 1536
img = cv2.imread("photo.jpg")[:, :, ::-1].astype(np.float32) / 255.0
L = img @ np.array([0.2126, 0.7152, 0.0722], np.float32)
alpha = np.clip((L - 0.03) / 0.12, 0, 1)
mask = alpha > 0.5
mask = ndi.binary_opening(mask, iterations=2)
lab, n = ndi.label(mask); mask = ndi.binary_fill_holes(lab == 1 + int(np.argmax(ndi.sum(mask, lab, range(1, n + 1)))))
np.save("out/mask.npy", mask); np.save("out/lum.npy", L)

# ---- subpixel row spans
rows = np.arange(W)
al = np.full(W, np.nan); ar = np.full(W, np.nan)
for b in rows:
    idx = np.nonzero(mask[b])[0]
    if len(idx) < 3: continue
    i0, i1 = idx[0], idx[-1]
    # refine with alpha crossing 0.5
    def cross(i, step):
        j = i - step
        if 0 <= j < W:
            a0, a1 = alpha[b, j], alpha[b, i]
            if a1 != a0: return j + (0.5 - a0) / (a1 - a0) * step
        return float(i)
    al[b] = cross(i0, 1); ar[b] = cross(i1, -1)
top_row = int(np.nanargmin(np.where(np.isnan(al), np.inf, rows)))
print("top row", top_row)

# ---- landmarks & head frame
lm = np.load("mp_landmarks_px.npy")            # (478,3) a, b, z (z ~ px, smaller = closer)
canon = np.load("canon_xyz.npy"); tris = np.load("canon_tris.npy")
M = np.load("mp_matrix.npy"); R = M[:3, :3] / np.linalg.norm(M[:3, :3], axis=0)
s_cm = 52.18; t_a, t_b, t_d = 835.3, 769.9, 204.4
def canon_to_px(c):           # canonical cm -> (a, b, d) px
    cam = np.atleast_2d(c) @ R.T
    return np.c_[s_cm * cam[:, 0] + t_a, -s_cm * cam[:, 1] + t_b, -1.007 * s_cm * cam[:, 2] + t_d]
head_center = canon_to_px([0.0, 3.0, -4.6])[0]
fwd = canon_to_px([0, 0, 1])[0] - canon_to_px([0, 0, 0])[0]; fwd /= np.linalg.norm(fwd)
up = canon_to_px([0, 1, 0])[0] - canon_to_px([0, 0, 0])[0]; up /= np.linalg.norm(up)
print("head center px", head_center, " fwd", fwd, " up", up)
yaw = np.arctan2(fwd[0], -fwd[2])     # angle of face direction in (a, d) plane from -d toward +a
print("yaw deg %.1f" % np.degrees(yaw))

# ---- skull left edge without the ear (ear rows ~470..850 on the left)
ear_b0, ear_b1 = 455, 870
good = (~np.isnan(al)) & ((rows < ear_b0) | (rows > ear_b1)) & (rows > top_row + 5) & (rows < 1000)
spl = UnivariateSpline(rows[good], al[good], s=len(rows[good]) * 2.0, k=3)
al_skull = al.copy()
er = (rows >= ear_b0) & (rows <= ear_b1)
al_skull[er] = np.maximum(al[er], spl(rows[er]))
ear_mask = np.zeros_like(mask)
for b in rows[er]:
    ear_mask[b, :] = mask[b, :] & (np.arange(W) < al_skull[b] - 0.5)
print("ear pixels", int(ear_mask.sum()))

# ---- per-row slice parameters (theta, rho, d_c) blended head -> neck -> torso
def smooth01(x): x = np.clip(x, 0, 1); return x * x * (3 - 2 * x)
b_head_end, b_neck_end = 960.0, 1180.0      # head rows -> neck/beard rows -> torso rows
t_ht = smooth01((rows - b_head_end) / (b_neck_end - b_head_end))        # 0 head ... 1 torso
theta = (1 - t_ht) * yaw
rho = (1 - t_ht) * 1.22 + t_ht * np.interp(rows, [1180, 1300, 1536], [0.95, 0.72, 0.62])
d_c = np.full(W, head_center[2])
# torso depth centre slightly behind the head centre
d_c = (1 - t_ht) * head_center[2] + t_ht * (head_center[2] + 40.0)
left = np.where(er, al_skull, al)
w = 0.5 * (ar - left); a_c = 0.5 * (ar + left)
p = w / np.sqrt(np.cos(theta) ** 2 + (rho * np.sin(theta)) ** 2); q = rho * p

def slice_front_back(b, a):
    """front/back depth of row-b slice ellipse at columns a (nan outside)."""
    th, pp, qq, ac, dc = theta[b], p[b], q[b], a_c[b], d_c[b]
    # ellipse: ((x cos+ y sin)/pp)^2 + ((-x sin + y cos)/qq)^2 = 1, x = a - ac, y = d - dc, axes: width along rotated a', depth along rotated d'
    x = a - ac
    c, s = np.cos(th), np.sin(th)
    # solve for y: A y^2 + B y + C = 0
    A = (s / pp) ** 2 + (c / qq) ** 2
    B = 2 * x * (c * s / pp ** 2 - s * c / qq ** 2)
    C = (x * c / pp) ** 2 + (x * s / qq) ** 2 - 1
    disc = B * B - 4 * A * C
    ok = disc >= 0
    sq = np.sqrt(np.where(ok, disc, 0))
    y1 = (-B - sq) / (2 * A); y2 = (-B + sq) / (2 * A)
    return np.where(ok, dc + y1, np.nan), np.where(ok, dc + y2, np.nan)

Fp = np.full((W, W), np.nan, np.float32); Bp = np.full((W, W), np.nan, np.float32)
A_ = np.arange(W, dtype=np.float64)
for b in rows:
    if np.isnan(w[b]): continue
    f, bk = slice_front_back(b, A_)
    Fp[b] = f; Bp[b] = bk

# ---- face displacement from MediaPipe landmarks (inside face oval)
face_oval = [10, 338, 297, 332, 284, 251, 389, 356, 454, 323, 361, 288, 397, 365, 379, 378, 400, 377, 152, 148, 176, 149, 150, 136, 172, 58, 132, 93, 234, 127, 162, 21, 54, 103, 67, 109]
poly = lm[face_oval, :2].astype(np.int32)
face_mask = np.zeros((W, W), np.uint8); cv2.fillPoly(face_mask, [poly], 1); face_mask = face_mask.astype(bool)
# rasterize face mesh depth via linear interpolation over landmark triangulation
interp = LinearNDInterpolator(lm[:468, :2], lm[:468, 2])
yy, xx = np.nonzero(face_mask)
fd = interp(np.c_[xx, yy]).astype(np.float32)
Fface = np.full((W, W), np.nan, np.float32); Fface[yy, xx] = fd
delta = Fface - Fp
ok = ~np.isnan(delta)
print("face delta (face depth - slice front) px: median %.1f  p5 %.1f  p95 %.1f" % tuple(np.nanpercentile(delta, [50, 5, 95])))
# boundary statistics (oval landmarks)
db = []
for i in face_oval:
    a, b = lm[i, :2]; bi = int(round(b))
    if 0 <= bi < W and not np.isnan(Fp[bi, int(round(a))]): db.append(lm[i, 2] - Fp[bi, int(round(a))])
print("oval landmark z - slice front (px): ", np.round(np.array(db), 0))
np.save("out/Fp.npy", Fp); np.save("out/Bp.npy", Bp); np.save("out/Fface.npy", Fface); np.save("out/face_mask.npy", face_mask)
np.save("out/ear_mask.npy", ear_mask)
json.dump(dict(head_center=head_center.tolist(), yaw=float(yaw), fwd=fwd.tolist(), up=up.tolist(), top_row=top_row),
          open("out/stage1.json", "w"), indent=1)
np.savez("out/rows.npz", al=al, ar=ar, al_skull=al_skull, theta=theta, rho=rho, d_c=d_c, p=p, q=q, a_c=a_c)
# quick viz
def norm(x):
    v = x[~np.isnan(x)]; lo, hi = np.percentile(v, [1, 99]); return np.clip((x - lo) / (hi - lo), 0, 1)
viz = np.nan_to_num(norm(np.where(np.isnan(Fface), Fp, Fface)), nan=0)
cv2.imwrite("out/prior_depth.png", (255 * (1 - viz)).astype(np.uint8))
