"""Stage 1c: union of fitted primitives -> silhouette-warped prior F (front) and B (back) depth maps."""
import numpy as np, json, cv2
from scipy import ndimage as ndi
from scipy.interpolate import LinearNDInterpolator
W = 1536
mask = np.load("out/mask.npy"); ear_mask = np.load("out/ear_mask.npy")
r = np.load("out/rows.npz"); al, ar, al_skull = r["al"], r["ar"], r["al_skull"]
lm = np.load("mp_landmarks_px.npy"); M = np.load("mp_matrix.npy"); R = M[:3, :3] / np.linalg.norm(M[:3, :3], axis=0)
s_cm, t_a, t_b, t_d = 52.18, 835.3, 769.9, 204.4
def c2p(c):
    cam = np.atleast_2d(c) @ R.T
    return np.c_[s_cm * cam[:, 0] + t_a, -s_cm * cam[:, 1] + t_b, -1.007 * s_cm * cam[:, 2] + t_d]
def rotx(t):
    t = np.radians(t); return np.array([[1, 0, 0], [0, np.cos(t), -np.sin(t)], [0, np.sin(t), np.cos(t)]])
A_, B_ = np.meshgrid(np.arange(W, dtype=np.float64), np.arange(W, dtype=np.float64))
def ellipsoid_depth(c_cm, ax_cm, tilt=0.0):
    o0 = c2p([0, 0, 0])[0]
    cols = np.array([c2p(rotx(tilt) @ (e * s))[0] - o0 for e, s in zip(np.eye(3), ax_cm)]).T
    center = c2p(c_cm)[0]
    Minv = np.linalg.inv(cols)
    o = np.stack([A_ - center[0], B_ - center[1], np.zeros_like(A_)], -1) @ Minv.T
    dv = Minv @ np.array([0, 0, 1.0]); a = dv @ dv; bq = 2 * (o @ dv); c = np.einsum("...i,...i", o, o) - 1
    disc = bq * bq - 4 * a * c; ok = disc >= 0; sq = np.sqrt(np.where(ok, disc, 0))
    return np.where(ok, center[2] + (-bq - sq) / (2 * a), np.nan), np.where(ok, center[2] + (-bq + sq) / (2 * a), np.nan)
cran = json.load(open("out/cranium.json"))["cranium"]; sb = json.load(open("out/side_beard.json"))
parts = {}
parts["cranium"] = ellipsoid_depth(cran[:3], cran[3:])
sy, sz, sax, say, saz = sb["side"]; parts["side"] = ellipsoid_depth([0, sy, sz], [sax, say, saz])
by, bz, bax, bay, baz, bt = sb["beard"]; parts["beard"] = ellipsoid_depth([0, by, bz], [bax, bay, baz], bt)
ear_c = np.array([-8.5, 0.84, -4.14]); ear_ax = (1.3, 3.25, 1.9)
parts["ear_r"] = ellipsoid_depth(ear_c, ear_ax, -14.0)
parts["ear_l"] = ellipsoid_depth(ear_c * [-1, 1, 1], ear_ax, -14.0)
hc = c2p(cran[:3])[0]
# neck: capsule-like vertical cylinder that starts inside the head
neck_r = 318.0; neck_left = np.nanmedian(al[(np.arange(W) > 880) & (np.arange(W) < 1100)])
nc = np.array([neck_left + neck_r, hc[2] + 60.0])
x = A_ - nc[0]; h = np.sqrt(np.clip(neck_r ** 2 - x ** 2, 0, None))
fade = np.clip((B_ - 700.0) / 120.0, 0, 1)            # grows in from inside the head
nf = np.where((np.abs(x) <= neck_r) & (B_ > 700), nc[1] - h * fade, np.nan)
nb = np.where((np.abs(x) <= neck_r) & (B_ > 700), nc[1] + h * fade, np.nan)
parts["neck"] = (nf, nb)
# torso slices (exact mask span per row, elliptic profile)
tf = np.full((W, W), np.nan); tb = np.full((W, W), np.nan)
d_t = hc[2] + 70.0
for b in range(1060, W):
    if np.isnan(al[b]): continue
    wl, wr = al[b], ar[b]; wc = 0.5 * (wl + wr); hw = 0.5 * (wr - wl)
    rho = np.interp(b, [1060, 1200, 1350, 1536], [0.90, 0.75, 0.64, 0.60])
    xx = A_[b] - wc; ok = np.abs(xx) <= hw
    grow = np.clip((b - 1060) / 140.0, 0, 1) ** 0.5
    hh = rho * hw * np.sqrt(np.clip(1 - (xx / hw) ** 2, 0, None)) * grow
    tf[b] = np.where(ok, d_t - hh, np.nan); tb[b] = np.where(ok, d_t + hh, np.nan)
parts["torso"] = (tf, tb)
# face mesh front
interp = LinearNDInterpolator(lm[:468, :2], lm[:468, 2])
oval = [10, 338, 297, 332, 284, 251, 389, 356, 454, 323, 361, 288, 397, 365, 379, 378, 400, 377, 152, 148, 176, 149, 150, 136, 172, 58, 132, 93, 234, 127, 162, 21, 54, 103, 67, 109]
fm = np.zeros((W, W), np.uint8); cv2.fillPoly(fm, [lm[oval, :2].astype(np.int32)], 1)
yy, xx2 = np.nonzero(fm); ff = np.full((W, W), np.nan); ff[yy, xx2] = interp(np.c_[xx2, yy])
# feather: fade the face mesh into the union near its boundary by pushing it back
dist = ndi.distance_transform_edt(fm)
parts["face"] = (ff + np.clip(1 - dist / 25.0, 0, 1) * 40.0, None)

def smin(stack, tau):
    st = np.stack(stack); valid = ~np.isnan(st)
    m = np.nanmin(st, axis=0)
    e = np.where(valid, np.exp(-(np.nan_to_num(st, nan=1e9) - np.nan_to_num(m, nan=0)) / tau), 0).sum(0)
    return np.where(np.isnan(m), np.nan, m - tau * np.log(np.where(e > 0, e, 1)))
import warnings; warnings.filterwarnings("ignore")
F = smin([v[0] for v in parts.values()], 10.0)
Bk = -smin([-v[1] for v in parts.values() if v[1] is not None], 10.0)
cover = ~np.isnan(F) & ~np.isnan(Bk)
print("raw union IoU %.4f  mask-not-union %d  union-not-mask %d" % ((cover & mask).sum() / (cover | mask).sum(), (mask & ~cover).sum(), (cover & ~mask).sum()))

# ---- per-row silhouette warp: map mask span -> union span with edge-local ramps
Fw = np.full((W, W), np.nan, np.float32); Bw = np.full((W, W), np.nan, np.float32)
ramp = 70.0
for b in range(W):
    if np.isnan(al[b]): continue
    cu = np.nonzero(cover[b])[0]
    if len(cu) < 3: continue
    ul, ur = cu[0], cu[-1]; ml, mr = al[b], ar[b]
    a = np.arange(int(np.floor(ml)), int(np.ceil(mr)) + 1)
    a = a[(a >= 0) & (a < W)]
    t_l = np.clip(1 - (a - ml) / ramp, 0, 1); t_r = np.clip(1 - (mr - a) / ramp, 0, 1)
    src = a + t_l * (ul - ml) + t_r * (ur - mr)
    src = np.clip(src, ul, ur)
    Fw[b, a] = np.interp(src, np.arange(W), np.nan_to_num(F[b], nan=np.nanmax(F[b][cu])))
    Bw[b, a] = np.interp(src, np.arange(W), np.nan_to_num(Bk[b], nan=np.nanmin(Bk[b][cu])))
Fw[~mask] = np.nan; Bw[~mask] = np.nan
# thickness must vanish smoothly at the silhouette (rounded rim): blend toward the mid-depth near the edge
edge = ndi.distance_transform_edt(mask)
mid = 0.5 * (Fw + Bw); half = 0.5 * (Bw - Fw)
k = np.clip(edge / 18.0, 0, 1); half = half * np.sqrt(k)
Fw = mid - half; Bw = mid + half
np.save("out/F_prior.npy", Fw); np.save("out/B_prior.npy", Bw)
print("prior F range %.0f..%.0f  B range %.0f..%.0f" % (np.nanmin(Fw), np.nanmax(Fw), np.nanmin(Bw), np.nanmax(Bw)))
json.dump(dict(neck=[float(nc[0]), float(nc[1]), neck_r], d_t=float(d_t), hc=hc.tolist(), ear_c=ear_c.tolist(), ear_ax=list(ear_ax)),
          open("out/prims2.json", "w"), indent=1)
