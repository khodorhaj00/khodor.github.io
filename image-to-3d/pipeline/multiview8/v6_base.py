"""Surface from points (v2): smooth 8-view hull + robust offset field from the stereo points (median of their distance
to the hull over 40 neighbours, so single bad matches cannot dig pits) + the triangulated face mesh (splatted, trusted)."""
import time, numpy as np
from scipy import ndimage as ndi
from scipy.spatial import cKDTree
from v_common import *
t0 = time.time()
hull = np.load("out/hull_vol.npy")
hs = ndi.gaussian_filter(np.clip(hull, -30, 30), 3.0).astype(np.float32)
def samp(vol, p):
    return ndi.map_coordinates(vol, [CR0 - p[:, 2], p[:, 1] - YV[0], p[:, 0] - XV[0]], order=1, mode="constant", cval=30.0)
P = np.load("out/points_stereo_clean.npy").astype(np.float64); pts = P[:, :3]
hp = samp(hs, pts)                                                     # signed distance of each point to the smooth hull
tr = cKDTree(pts); dd, nb = tr.query(pts, k=60)
op = np.median(hp[nb], axis=1); spread = np.median(np.abs(hp[nb] - op[:, None]), axis=1)
good = (op > -14) & (op < 3) & (spread < 4.0) & (dd[:, -1] < 16)
print("stereo offsets: %d / %d consistent; median offset %.1f px (inside < 0)" % (good.sum(), len(pts), np.median(op[good])))
# splat the robust offsets to the grid (normalised gaussian), only near the surface
acc = np.zeros(hs.shape, np.float32); wac = np.zeros(hs.shape, np.float32)
ir = np.round(CR0 - pts[good, 2]).astype(int); iy = np.round(pts[good, 1] - YV[0]).astype(int); ix = np.round(pts[good, 0] - XV[0]).astype(int)
inb = (ir >= 0) & (ir < hs.shape[0]) & (iy >= 0) & (iy < hs.shape[1]) & (ix >= 0) & (ix < hs.shape[2])
np.add.at(acc, (ir[inb], iy[inb], ix[inb]), op[good][inb]); np.add.at(wac, (ir[inb], iy[inb], ix[inb]), 1.0)
a8 = ndi.gaussian_filter(acc, 12.0); w8 = ndi.gaussian_filter(wac, 12.0)
a20 = ndi.gaussian_filter(acc, 28.0); w20 = ndi.gaussian_filter(wac, 28.0)
o8 = np.where(w8 > 1e-5, a8 / np.maximum(w8, 1e-9), 0.0); o20 = np.where(w20 > 1e-6, a20 / np.maximum(w20, 1e-9), 0.0)
c8 = np.clip(w8 / 0.0015, 0, 1); c20 = np.clip(w20 / 0.00015, 0, 1)
o = c8 * o8 + (1 - c8) * c20 * o20; conf = np.maximum(c8, c20)
vol = hs - o.astype(np.float32)
print("offset field: %.0f%% of near-surface voxels covered, mean offset %.2f px" % (100 * (conf[np.abs(hs) < 2] > 0.5).mean(), o[np.abs(hs) < 2].mean()))
# ---- triangulated face mesh: dense oriented samples, splatted signed distance (trusted, local)
face = np.load("out/face3d_full.npy"); tris = np.load("canon_tris.npy"); okf = ~np.isnan(face).any(1)
# close the eye and mouth openings (MediaPipe has no triangles there): fan caps, slightly domed eyeballs
RING = {"eyeR": [33, 7, 163, 144, 145, 153, 154, 155, 133, 173, 157, 158, 159, 160, 161, 246],
        "eyeL": [362, 382, 381, 380, 374, 373, 390, 249, 263, 466, 388, 387, 386, 385, 384, 398],
        "mouth": [78, 95, 88, 178, 87, 14, 317, 402, 318, 324, 308, 415, 310, 311, 312, 13, 82, 81, 80, 191]}
extra = []; face = np.vstack([face, np.full((len(RING), 3), np.nan)]); okf = np.r_[okf, np.zeros(len(RING), bool)]
for k, (nm, ring) in enumerate(RING.items()):
    ring = [i for i in ring if okf[i]]
    if len(ring) < 6: continue
    c = face[ring].mean(0)
    if nm.startswith("eye"): c[1] -= 1.5                              # eyeball bulges a little in front of the lid line
    ci = 468 + k; face[ci] = c; okf[ci] = True
    for a, b in zip(ring, ring[1:] + ring[:1]): extra.append([a, b, ci])
tris = np.vstack([tris, np.array(extra, int)])
fs = []
for t in tris:
    if not okf[t].all(): continue
    a, b, c = face[t]; n = np.cross(b - a, c - a); ln = np.linalg.norm(n)
    if ln < 1e-6: continue
    n /= ln
    if n[1] > 0: n = -n
    for i in range(6):
        for j in range(6 - i):
            l1, l2 = (i + 0.5) / 6.0, (j + 0.5) / 6.0
            if l1 + l2 <= 1: fs.append(np.r_[a + l1 * (b - a) + l2 * (c - a), n])
fs = np.array(fs); fp, fn = fs[:, :3], fs[:, 3:]
# fade the face splat toward the mesh border (no step where the face meets the hull surface)
from matplotlib.path import Path
from scipy.spatial import ConvexHull
okp = ~np.isnan(face).any(1); hl = ConvexHull(face[okp][:, [0, 2]]); poly = face[okp][hl.vertices][:, [0, 2]]
def dist_to_poly(q):
    d = np.full(len(q), np.inf)
    for a, b in zip(poly, np.roll(poly, -1, 0)):
        ab = b - a; t = np.clip(((q - a) @ ab) / max(ab @ ab, 1e-9), 0, 1); d = np.minimum(d, np.linalg.norm(q - (a + t[:, None] * ab), axis=1))
    return d
fwgt = np.clip(dist_to_poly(fp[:, [0, 2]]) / 14.0, 0, 1); fwgt = fwgt * fwgt * (3 - 2 * fwgt)
Zsub = face[2, 2]; Zmouth = face[13, 2]                               # subnasale, mouth (model Z, px)
bw = np.clip((fp[:, 2] - Zmouth) / max(Zsub - Zmouth, 1e-3), 0, 1); bw = bw * bw * (3 - 2 * bw)
fwgt = fwgt * (0.08 + 0.92 * bw)
TR = 6.0; Rr = 6
num = np.zeros(hs.shape, np.float64); den = np.zeros(hs.shape, np.float64)
offs = np.array([(dz, dy, dx) for dz in range(-Rr, Rr + 1) for dy in range(-Rr, Rr + 1) for dx in range(-Rr, Rr + 1)])
ir = np.round(CR0 - fp[:, 2]).astype(int); iy = np.round(fp[:, 1] - YV[0]).astype(int); ix = np.round(fp[:, 0] - XV[0]).astype(int)
for c0 in range(0, len(fp), 3000):
    sl = slice(c0, c0 + 3000)
    R_ = ir[sl, None] + offs[None, :, 0]; Yi = iy[sl, None] + offs[None, :, 1]; Xi = ix[sl, None] + offs[None, :, 2]
    ok = (R_ >= 0) & (R_ < hs.shape[0]) & (Yi >= 0) & (Yi < hs.shape[1]) & (Xi >= 0) & (Xi < hs.shape[2])
    vz = CR0 - R_; vy = YV[0] + Yi; vx = XV[0] + Xi
    dx_, dy_, dz_ = vx - fp[sl, 0, None], vy - fp[sl, 1, None], vz - fp[sl, 2, None]
    d = dx_ * fn[sl, 0, None] + dy_ * fn[sl, 1, None] + dz_ * fn[sl, 2, None]
    lat2 = dx_ ** 2 + dy_ ** 2 + dz_ ** 2 - d ** 2
    w = np.where(ok, fwgt[sl, None] * np.exp(-lat2 / (2 * 2.5 ** 2)) * np.exp(-d ** 2 / (2 * 4.0 ** 2)), 0.0)
    fi = np.ravel_multi_index((np.clip(R_, 0, hs.shape[0] - 1), np.clip(Yi, 0, hs.shape[1] - 1), np.clip(Xi, 0, hs.shape[2] - 1)), hs.shape)
    np.add.at(num.reshape(-1), fi.ravel(), (w * np.clip(d, -TR, TR)).ravel()); np.add.at(den.reshape(-1), fi.ravel(), w.ravel())
WB = 0.25
vol = np.where(den > 0.02, (WB * np.clip(vol, -TR, TR) + 3.0 * num) / (WB + 3.0 * den), vol)
vol = np.maximum(vol, ndi.gaussian_filter(np.clip(hull, -30, 30), 1.5) - 1.5)
lab, n = ndi.label(vol < 0); sizes = ndi.sum(np.ones(vol.shape, np.float32), lab, np.arange(1, n + 1))
solid = ndi.binary_fill_holes(lab == (1 + int(np.argmax(sizes))))
dout = ndi.distance_transform_edt(~solid); din = ndi.distance_transform_edt(solid)
vol = np.clip((dout - din).astype(np.float32) + np.where(solid, 0.5, -0.5), -30, 30)
vol = ndi.gaussian_filter(vol, 2.0).astype(np.float32)
np.save("out/b1_vol.npy", vol)
dms = {v: depth_map(vol, AZ[v]) for v in NAMES}
np.savez("out/b1_depth.npz", **dms)
compare_sheet(dms, "out/b1_compare.png")
print("base from points done %.0fs" % (time.time() - t0))
