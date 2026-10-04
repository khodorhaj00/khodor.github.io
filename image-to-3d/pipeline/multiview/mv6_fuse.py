"""TSDF fusion of the 4 refined depth maps (+ weak base prior), hard-carved by the front and side silhouettes.
Views are first made consistent with the other views' silhouettes (smooth push-back), then pulled toward the
fused consensus at low frequency (keeps each view's fine detail, removes cracks between views)."""
import sys, time, numpy as np
from scipy import ndimage as ndi
from mv_vol import *
from mv_viz import compare_sheet
from mv_common import row_extents
TAU = float(sys.argv[1]) if len(sys.argv) > 1 else 8.0
ITERS = int(sys.argv[2]) if len(sys.argv) > 2 else 2
W0 = 0.02
d = dict(np.load("out/sfs_all.npz")); prior = np.load("out/b1s_vol.npy")
def ext_mm(v):
    L, R = row_extents(np.load("out/c_%s_alpha.npy" % v)); return (L - 390.0) * S, (R - 390.0) * S
fL, fR = ext_mm("front"); rL, rR = ext_mm("right"); lL, lR = ext_mm("left")
Yant = 0.5 * (rL + lL); Ypost = 0.5 * (rR + lR)
def push(D, m, lim, sign):
    viol = np.nan_to_num(np.where(m, np.maximum(0.0, sign * (lim[:, None] - D)), 0.0))
    c = ndi.gaussian_filter(ndi.maximum_filter(viol, size=7), 3.0); c = np.maximum(c, viol)
    return D + sign * c, float((viol > 0.5).mean())
d["front"], vf = push(d["front"], d["front_mask"], np.nan_to_num(Yant, nan=-1e3), +1)
d["back"], vb = push(d["back"], d["back_mask"], np.nan_to_num(Ypost, nan=1e3), -1)
d["right"], vr = push(d["right"], d["right_mask"], np.nan_to_num(fL, nan=-1e3), +1)
d["left"], vl = push(d["left"], d["left_mask"], np.nan_to_num(fR, nan=1e3), -1)
print("silhouette push-back: front %.1f%% back %.1f%% right %.1f%% left %.1f%%" % (100 * vf, 100 * vb, 100 * vr, 100 * vl))
def wmap(v):
    D = d[v]; m = d[v + "_mask"]
    Dz = np.where(m, D, 0.0)
    g = np.hypot(np.gradient(Dz, axis=1), np.gradient(Dz, axis=0)) / S
    fac = 1.0 / np.sqrt(1.0 + g ** 2)
    fac = ndi.gaussian_filter(ndi.minimum_filter(fac, 3), 1.5)
    edge = np.clip(ndi.distance_transform_edt(m) / 8.0, 0, 1)
    return np.where(m, fac ** 3 * edge, 0.0)
def sil_sdf(v):
    mm = np.load("out/c_%s_alpha.npy" % v) > 0.5
    return (ndi.distance_transform_edt(~mm) - ndi.distance_transform_edt(mm)) * S
sil_f = sil_sdf("front"); sil_s = 0.5 * (sil_sdf("right") + sil_sdf("left"))
Xg, Yg = np.meshgrid(Xv, Yv)
def fuse(d, W):
    vol = np.empty_like(prior)
    for r in range(NR):
        num = W0 * np.clip(prior[r], -TAU, TAU); den = np.full(Xg.shape, W0)
        for v, cols, along in (("front", XC, "x"), ("back", XC, "x"), ("right", YC, "y"), ("left", YC, "y")):
            F = d[v][r, cols]; w = W[v][r, cols]; m = d[v + "_mask"][r, cols]
            if along == "x":
                Fb, wb, mb = F[None, :], w[None, :], m[None, :]
                sd = (Fb - Yg) if v == "front" else (Yg - Fb)
            else:
                Fb, wb, mb = F[:, None], w[:, None], m[:, None]
                sd = (Fb - Xg) if v == "right" else (Xg - Fb)
            sd = np.where(mb, sd, TAU); ww = np.where(mb, wb, 0.0) * np.ones_like(Xg)
            use = sd >= -TAU
            num += np.where(use, ww * np.clip(sd, -TAU, TAU), 0); den += np.where(use, ww, 0)
        ph = num / den
        vol[r] = np.maximum(ph, np.maximum(sil_f[r, XC][None, :], sil_s[r, YC][:, None]))
    vol[np.arange(NR) > 474] = TAU
    return vol
def nblur(X, m, s):
    num = ndi.gaussian_filter(np.where(m, X, 0.0), s); den = ndi.gaussian_filter(m.astype(np.float64), s)
    return np.where(m, num / np.maximum(den, 1e-6), 0.0)
W = {v: wmap(v) for v in ["front", "right", "back", "left"]}
t0 = time.time()
for it in range(ITERS + 1):
    vol = fuse(d, W)
    if it == ITERS: break
    dm = depth_maps(vol)
    for v in ["front", "right", "back", "left"]:
        cols = XC if v in ("front", "back") else YC
        Dv = np.full(d[v].shape, np.nan); Dv[:, cols] = dm[v]
        m = d[v + "_mask"] & ~np.isnan(Dv)
        diff = np.where(m, d[v] - Dv, 0.0)
        diff = np.clip(diff, -12, 12)
        corr = nblur(diff, m, 10.0)
        d[v] = np.where(d[v + "_mask"], d[v] - 0.7 * corr, d[v])
        print("  iter %d %-5s consensus |diff| p50 %.2f p90 %.2f mm" % (it, v, np.median(np.abs(diff[m])), np.percentile(np.abs(diff[m]), 90)))
print("fused in %.0fs" % (time.time() - t0))
vol = ndi.gaussian_filter(vol, 0.6)
lab, n = ndi.label(vol < 0); sizes = ndi.sum(np.ones(vol.shape, np.float32), lab, np.arange(1, n + 1))
keep = 1 + int(np.argmax(sizes)); solid = lab == keep
outside = ndi.binary_fill_holes(solid)
vol = np.where(solid, vol, np.where(outside, -np.abs(vol) - 0.05, np.maximum(vol, 0.05))).astype(np.float32)
print("inside components %d (kept largest)" % n)
np.save("out/fused_vol.npy", vol)
np.savez("out/sfs_push.npz", **d)
dm = depth_maps(vol); np.savez("out/fused_depth.npz", **dm)
compare_sheet(dm, "out/fused_compare.png")
