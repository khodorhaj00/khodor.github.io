"""TSDF fusion of the 8 refined depth maps (+ weak point-based prior), carved by the 8-view hull,
with two rounds of low-frequency consensus between views."""
import time, numpy as np
from scipy import ndimage as ndi
from v_common import *
TAU = 7.0; W0 = 0.03; ITERS = 2
d = dict(np.load("out/sfs8.npz")); prior = np.load("out/b1_vol.npy"); hull = np.load("out/hull_vol.npy")
def nblur(X, m, s):
    num = ndi.gaussian_filter(np.where(m, X, 0.0), s); den = ndi.gaussian_filter(m.astype(np.float64), s)
    return np.where(m, num / np.maximum(den, 1e-6), 0.0)
def wmap(v):
    D = d[v]; m = d[v + "_mask"]; Dz = np.where(m, D, 0.0)
    g = np.hypot(np.gradient(Dz, axis=1), np.gradient(Dz, axis=0))
    fac = ndi.gaussian_filter(ndi.minimum_filter(1.0 / np.sqrt(1.0 + g ** 2), 3), 1.5)
    edge = np.clip(ndi.distance_transform_edt(m) / 8.0, 0, 1)
    return np.where(m, fac ** 3 * edge, 0.0)
W = {v: wmap(v) for v in NAMES}
UW = {v: uw(AZ[v]) for v in NAMES}
cols = np.arange(WC, dtype=float)
def fuse(d):
    vol = np.empty_like(prior)
    for r in range(HC):
        num = W0 * np.clip(prior[r], -TAU, TAU); den = np.full(prior[r].shape, W0)
        for v in NAMES:
            u, w = UW[v]; c = u + CU0
            mrow = d[v + "_mask"][r]
            if not mrow.any(): continue
            Drow = np.where(mrow, d[v][r], np.nan)
            okc = ~np.isnan(Drow)
            Dv = np.interp(c, cols[okc], Drow[okc]) if okc.sum() > 1 else np.full(c.shape, np.nan)
            mv = np.interp(c, cols, mrow.astype(float)) > 0.5
            wv = np.interp(c, cols, W[v][r]) * mv
            sd = np.where(mv, Dv - w, TAU)
            use = sd >= -TAU
            num += np.where(use, wv * np.clip(sd, -TAU, TAU), 0.0); den += np.where(use, wv, 0.0)
        vol[r] = np.maximum(num / den, hull[r])                       # carve with the 8-view hull
    return vol
t0 = time.time()
for it in range(ITERS + 1):
    vol = fuse(d)
    if it == ITERS: break
    for v in NAMES:
        Dv = depth_map(vol, AZ[v]); m = d[v + "_mask"] & ~np.isnan(Dv)
        diff = np.clip(np.where(m, d[v] - Dv, 0.0), -12, 12)
        corr = nblur(diff, m, 10.0)
        d[v] = np.where(d[v + "_mask"], d[v] - 0.7 * corr, d[v])
        print("  iter %d %s consensus |diff| p50 %.2f p90 %.2f px" % (it, v, np.median(np.abs(diff[m])), np.percentile(np.abs(diff[m]), 90)))
print("fused in %.0fs" % (time.time() - t0))
vol = ndi.gaussian_filter(vol, 0.6)
lab, n = ndi.label(vol < 0); sizes = ndi.sum(np.ones(vol.shape, np.float32), lab, np.arange(1, n + 1))
solid = lab == (1 + int(np.argmax(sizes))); filled = ndi.binary_fill_holes(solid)
vol = np.where(solid, vol, np.where(filled, -np.abs(vol) - 0.05, np.maximum(vol, 0.05))).astype(np.float32)
np.save("out/fused8_vol.npy", vol)
dms = {v: depth_map(vol, AZ[v]) for v in NAMES}
np.savez("out/fused8_depth.npz", **dms)
compare_sheet(dms, "out/fused8_compare.png")
print("done %.0fs" % (time.time() - t0))
