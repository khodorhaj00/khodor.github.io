"""B1 = B0 body + MediaPipe face (front view, depth calibrated to the side profile) + ear primitives."""
import json, time, numpy as np, cv2
from scipy import ndimage as ndi
from mv_vol import *
from mv_viz import compare_sheet
A = json.load(open("out/align.json")); cxf = A["cx_f"]
P = dict(np.load("out/b0_params.npz")); YFs = P["YFs"]
mp = np.load("out/mp_front.npy")[:468]; tris = np.load("canon_tris.npy")
# ---- depth calibration on the upper-face midline: Y = Y0 + k * z_px * S
MID = [10, 151, 9, 8, 168, 6, 197, 195, 5, 4, 1, 19]
rr = mp[MID, 1]; zz = mp[MID, 2]; yy = YFs[np.round(rr).astype(int)]
Am = np.c_[zz * S, np.ones(len(MID))]; (k, Y0), *_ = np.linalg.lstsq(Am, yy, rcond=None)
print("face depth calib: k %.3f Y0 %.1f  rms %.2f mm" % (k, Y0, np.sqrt(np.mean((Am @ [k, Y0] - yy) ** 2))))
vc = mp[:, 0] - cxf + 390.0; vr = mp[:, 1]; vY = Y0 + k * S * mp[:, 2]
# ---- rasterise the face mesh into the front common image
F = np.full((NR, 780), np.nan); W = np.zeros((NR, 780))
for t in tris:
    x, y, d = vc[t], vr[t], vY[t]
    x0, x1 = int(np.floor(x.min())), int(np.ceil(x.max())); y0, y1 = int(np.floor(y.min())), int(np.ceil(y.max()))
    gx, gy = np.meshgrid(np.arange(x0, x1 + 1), np.arange(y0, y1 + 1))
    T = np.array([[x[0] - x[2], x[1] - x[2]], [y[0] - y[2], y[1] - y[2]]])
    if abs(np.linalg.det(T)) < 1e-9: continue
    l = np.linalg.solve(T, np.stack([gx.ravel() - x[2], gy.ravel() - y[2]]))
    l3 = 1 - l[0] - l[1]; ins = (l[0] >= -1e-6) & (l[1] >= -1e-6) & (l3 >= -1e-6)
    px, py = gx.ravel()[ins], gy.ravel()[ins]; dv = l[0][ins] * d[0] + l[1][ins] * d[1] + l3[ins] * d[2]
    F[py, px] = dv
m_face = ~np.isnan(F)
def nblur(X, m, s):
    num = ndi.gaussian_filter(np.where(m, X, 0.0), s); den = ndi.gaussian_filter(m.astype(float), s)
    return np.where(m, num / np.maximum(den, 1e-6), np.nan)
F = nblur(F, m_face, 2.5)
# ---- midline residual -> per-row offset with lateral falloff (makes the face midline = side profile)
mid_c = np.interp(np.arange(NR), vr[MID + [2, 0, 13, 17, 18, 200, 152]], vc[MID + [2, 0, 13, 17, 18, 200, 152]])
res = np.full(NR, np.nan)
for r in range(100, 300):
    c = int(round(mid_c[r])); seg = F[r, c - 3:c + 4]
    if np.isnan(seg).all(): continue
    res[r] = YFs[r] - np.nanmin(seg)
ok = ~np.isnan(res); rows_ = np.arange(NR)
res = np.interp(rows_, rows_[ok], res[ok]); res = ndi.gaussian_filter1d(res, 1.5)
Xcols = (np.arange(780) - 390.0) * S; Xmid = (mid_c - 390.0) * S
fall = np.exp(-((Xcols[None, :] - Xmid[:, None]) / 26.0) ** 2)
F = F + res[:, None] * fall
print("midline residual (before) p50 %.2f max %.2f mm" % (np.median(np.abs(res[100:290])), np.abs(res[100:290]).max()))
# ---- face weight: feathered oval, faded out below the mustache and into the hair line
OVAL = [10, 338, 297, 332, 284, 251, 389, 356, 454, 323, 361, 288, 397, 365, 379, 378, 400, 377, 152, 148, 176, 149, 150, 136, 172, 58, 132, 93, 234, 127, 162, 21, 54, 103, 67, 109]
poly = np.stack([vc[OVAL], vr[OVAL]], 1).astype(np.int32)
om = np.zeros((NR, 780), np.uint8); cv2.fillPoly(om, [poly], 1)
dist = ndi.distance_transform_edt(om)
w = np.clip(dist / 55.0, 0, 1); w = w * w * (3 - 2 * w)
# beard line: bare face above, beard lobe below (under the nose at row 266, up to the sideburns at row 200)
dX = np.abs(Xcols[None, :] - Xmid[:, None])
r_line = np.interp(dX, [0, 14, 26, 44, 70, 90], [267, 268, 282, 262, 205, 190])
fade = 1 - np.clip((rows_[:, None] - r_line + 6.0) / 26.0, 0, 1); fade = fade * fade * (3 - 2 * fade)
w = ndi.gaussian_filter(w * fade, 6.0) * m_face
np.savez("out/face.npz", F=np.nan_to_num(F, nan=0.0), w=w, mid_c=mid_c, k=k, Y0=Y0)
# ---- volume: body (B0, blurred) + face slab, cut by the blended front depth
vol = np.load("out/b0_vol.npy")
dm0 = depth_maps(vol)
Fb = dm0["front"]                                            # (NR, NXv) body front Y
wv = w[:, XC]; Fv = np.nan_to_num(F[:, XC], nan=0.0)
F0 = np.where(np.isnan(Fb), Fv, wv * Fv + (1 - wv) * np.nan_to_num(Fb, nan=0.0))
F0 = np.where(np.isnan(Fb) & (wv < 0.01), np.nan, F0)
# front surface displaced from the body front Fb to F0 (no slab: displacement fades out 30 mm behind the surface)
T = 30.0
for r in range(NR):
    f0 = F0[r]; fb = Fb[r]
    okc = (wv[r] > 0.002) & ~np.isnan(fb) & ~np.isnan(f0)
    if not okc.any(): continue
    dlt = np.where(okc, f0 - fb, 0.0)[None, :]
    base = np.where(okc, np.minimum(f0, fb), 0.0)[None, :]
    g = np.clip(1 - (Yv[:, None] - base) / T, 0, 1); g = g * g * (3 - 2 * g)
    vol[r] = vol[r] + (dlt * g).astype(np.float32)
# ---- ears: tilted flat ellipsoid + concha bowl (side = -1 right ear at -X, +1 left ear at +X)
def rot(axis, deg):
    t = np.radians(deg); c, s = np.cos(t), np.sin(t)
    if axis == "z": return np.array([[c, -s, 0], [s, c, 0], [0, 0, 1]])
    if axis == "x": return np.array([[1, 0, 0], [0, c, -s], [0, s, c]])
def ell(Pl, rad):
    k0 = np.linalg.norm(Pl / rad, axis=-1); k1 = np.linalg.norm(Pl / (rad * rad), axis=-1)
    return k0 * (k0 - 1.0) / np.maximum(k1, 1e-9)
EARS = []
for side, x_out, (r0, r1), (y0, y1) in ((-1, -88.0, (159, 263), (5.6, 45.7)), (1, 84.0, (157, 268), (4.3, 39.0))):
    zc = (474.0 - 0.5 * (r0 + r1)) * S; hz = 0.5 * (r1 - r0) * S; yc = 0.5 * (y0 + y1); hy = 0.5 * (y1 - y0)
    yaw = 22.0; th = 5.5
    xc = x_out - side * (th * np.cos(np.radians(yaw)) + hy * np.sin(np.radians(yaw)))
    Rm = rot("z", -side * yaw) @ rot("x", -14.0)               # back edge out, top tilted back
    EARS.append(dict(side=side, c=np.array([xc, yc, zc]), R=Rm, rad=np.array([th, hy, hz])))
    print("ear %+d centre (%.1f, %.1f, %.1f) half-sizes %.1f x %.1f x %.1f" % (side, xc, yc, zc, th, hy, hz))
Xg3, Yg3 = np.meshgrid(Xv, Yv)
for r in range(NR):
    Z = (474.0 - r) * S
    for E in EARS:
        if abs(Z - E["c"][2]) > E["rad"][2] + 4: continue
        Pw = np.stack([Xg3 - E["c"][0], Yg3 - E["c"][1], np.full_like(Xg3, Z - E["c"][2])], -1)
        Pl = Pw @ E["R"]                                       # world -> local
        outer = ell(Pl, E["rad"])
        bowl = ell(Pl - np.array([E["side"] * 4.2, -2.5, -4.0]), np.array([3.6, 0.55 * E["rad"][1], 0.36 * E["rad"][2]]))
        d = np.maximum(outer, -bowl)
        # filler between the ear and the skull (no gap behind the ear: rays from the head centre see one surface)
        Pf = Pl - np.array([-E["side"] * 9.0, 0.0, 0.0])
        fillr = ell(Pf, np.array([9.5, 0.9 * E["rad"][1], 0.92 * E["rad"][2]]))
        d = smin(d, fillr, 2.5)
        vol[r] = smin(vol[r], d.astype(np.float32), 2.0)
np.save("out/b1_vol.npy", vol)
dm = depth_maps(vol); np.savez("out/b1_depth.npz", **dm)
compare_sheet(dm, "out/b1_compare.png")
json.dump([dict(side=E["side"], c=E["c"].tolist(), R=E["R"].tolist(), rad=E["rad"].tolist()) for E in EARS], open("out/ears.json", "w"))
print("done")
# ---- B1s: exact 3D distance, then smooth along Z to remove per-row creases (and lightly in-plane)
vol = np.load("out/b1_vol.npy")
vol = sdf3d(vol)
vol = ndi.gaussian_filter(vol, (5.0, 1.7, 1.7)).astype(np.float32)
np.save("out/b1s_vol.npy", vol)
dm = depth_maps(vol); np.savez("out/b1s_depth.npz", **dm)
compare_sheet(dm, "out/b1s_compare.png")
print("smoothed B1 saved")
