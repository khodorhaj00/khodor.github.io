"""Calibrate all 8 views into one model frame and resample them into canonical images.
model: X right (front view), Y away from the front camera, Z up; rotation axis = vertical through the face centroid.
canonical image of a view: column = u = X cos(az) - Y sin(az) (+CU0), row = -Z (+CR0), in front-view pixels."""
import json, numpy as np, cv2
from scipy.optimize import least_squares, minimize
from scipy import ndimage as ndi
names = ["v000", "v045", "v090", "v135", "v180", "v225", "v270", "v315"]
cf = json.load(open("out/cams_face.json"))
P3 = np.load("out/face3d.npy"); okp = ~np.isnan(P3).any(1)
cams = {}
for v in ["v000", "v045", "v315"]:
    cams[v] = dict(az=float(cf["azimuth"][v]), s=float(cf["scale"][v]), roll=float(cf["roll"][v]), tx=float(cf["tx"][v]), ty=float(cf["ty"][v]))
def proj(P, c):
    t = np.radians(c["az"]); u = P[:, 0] * np.cos(t) - P[:, 1] * np.sin(t); w = P[:, 2]
    r = np.radians(c["roll"]); uu = np.cos(r) * u - np.sin(r) * w; ww = np.sin(r) * u + np.cos(r) * w
    return np.c_[c["s"] * uu + c["tx"], -c["s"] * ww + c["ty"]]
# ---- profile view: azimuth fixed 90, fit similarity to its visible landmarks
p90 = np.load("out/mp_v090.npy")[:468]
tris = np.load("canon_tris.npy")
Q = np.c_[p90[:, 0], -p90[:, 1], -p90[:, 2]]
n = np.zeros_like(Q); a, b, c = Q[tris[:, 0]], Q[tris[:, 1]], Q[tris[:, 2]]; fn = np.cross(b - a, c - a)
for k in range(3): np.add.at(n, tris[:, k], fn)
n /= np.maximum(np.linalg.norm(n, axis=1, keepdims=True), 1e-9)
if np.median(n[:, 2]) < 0: n = -n
vis90 = (n[:, 2] > 0.45) & okp
pan = json.load(open("out/panels.json"))
s90 = cams["v000"]["s"] * (pan["v090"]["bot"] - pan["v090"]["top"]) / float(pan["v000"]["bot"] - pan["v000"]["top"])
c90 = dict(az=90.0, s=s90, roll=0.0, tx=0.0, ty=0.0)
pr = proj(P3[vis90], c90)
tx90 = float(np.median(p90[vis90, 0] - pr[:, 0]))
# vertical: map the front view's head top / base Z to this view's top / base rows
c0 = cams["v000"]; Zt = (c0["ty"] - pan["v000"]["top"]) / c0["s"]; Zb = (c0["ty"] - pan["v000"]["bot"]) / c0["s"]
ty90 = float(0.5 * ((pan["v090"]["top"] + s90 * Zt) + (pan["v090"]["bot"] + s90 * Zb)))
cams["v090"] = dict(az=90.0, s=float(s90), roll=0.0, tx=tx90, ty=ty90)
print("v090: s %.3f tx %.1f ty %.1f (landmark x-offset spread %.1f px)" % (s90, tx90, ty90, np.std(p90[vis90, 0] - pr[:, 0])))
# ---- back views: 2D similarity aligning the view's silhouette to the mirrored partner's silhouette
PART = {"v180": "v000", "v225": "v045", "v135": "v315", "v270": "v090"}
M = {v: np.load("out/%s_mask.npy" % v).astype(np.float32) for v in names}
Wd = M["v000"].shape[1]
def sim_mat(p):  # p = (log scale, angle deg, tx, ty) about the image centre
    s = np.exp(p[0]); a = np.radians(p[1]); c0 = np.array([Wd / 2.0, Wd / 2.0])
    R = s * np.array([[np.cos(a), -np.sin(a)], [np.sin(a), np.cos(a)]])
    t = c0 - R @ c0 + np.array([p[2], p[3]])
    return np.c_[R, t]
# back views: own scale/vertical offset from the head top + base rows (like the profile), azimuth = partner + 180,
# horizontal offset = best head-region overlap with the mirrored partner (solved after the canonical resampling)
for v, pv in PART.items():
    sv = cams["v000"]["s"] * (pan[v]["bot"] - pan[v]["top"]) / float(pan["v000"]["bot"] - pan["v000"]["top"])
    tyv = float(0.5 * ((pan[v]["top"] + sv * Zt) + (pan[v]["bot"] + sv * Zb)))
    cams[v] = dict(az=float((cams[pv]["az"] + 180.0) % 360.0), s=float(sv), roll=0.0, tx=0.0, ty=tyv, partner=pv)
# ---- canonical images
c0 = cams["v000"]; CU0, CR0 = c0["tx"], c0["ty"]
HC, WC = 448, 700; CU0c = 350.0
pf = np.load("out/mp_v000.npy")
Zbrow = (c0["ty"] - pf[9, 1]) / c0["s"]; Zchin = (c0["ty"] - pf[152, 1]) / c0["s"]
Ztop = (c0["ty"] - pan["v000"]["top"]) / c0["s"]; Zbase = (c0["ty"] - pan["v000"]["bot"]) / c0["s"]
def corr_params(v):
    """vertical/horizontal stretch outside the face band so this view's head top and base land on its own silhouette"""
    c = cams[v]
    t = np.radians(c["az"]); rows = lambda Z: proj(np.c_[np.zeros(len(Z)), np.zeros(len(Z)), Z], c)[:, 1]
    rt, rb, rbr, rch = rows(np.array([Ztop, Zbase, Zbrow, Zchin]))
    kt = (rbr - pan[v]["top"]) / max(rbr - rt, 1e-6); kb = (pan[v]["bot"] - rch) / max(rb - rch, 1e-6)
    return kt, kb
KS = {}
for v in ["v000", "v045", "v315", "v090"]:
    KS[v] = (1.0, 1.0) if v == "v000" else corr_params(v)
    print("%s stretch above brow %.3f  below chin %.3f" % (v, KS[v][0], KS[v][1]))
def warpZ(v, Z):
    """remap model Z so the head top / base of view v line up (face band unchanged)"""
    kt, kb = KS[v]
    Zw = Z.copy()
    up = Z > Zbrow; dn = Z < Zchin
    Zw[up] = Zbrow + (Z[up] - Zbrow) * kt
    Zw[dn] = Zchin - (Zchin - Z[dn]) * kb
    k = np.ones_like(Z); k[up] = kt; k[dn] = kb
    return Zw, k
def view_coords(v, U, Zr):
    """canonical grid (u, Z in front-view px) -> pixel coords in view v"""
    c = cams[v]
    Zw, k = warpZ(v, Zr.ravel()) if v in KS else (Zr.ravel(), np.ones(Zr.size))
    uu = U.ravel() * k
    t = np.radians(c["az"]); P2 = np.c_[uu * np.cos(t), -uu * np.sin(t), Zw]
    xy = proj(P2, c)
    return xy[:, 0].reshape(U.shape), xy[:, 1].reshape(U.shape)
cc, rr = np.meshgrid(np.arange(WC, dtype=float), np.arange(HC, dtype=float))
U = cc - CU0c; Zr = CR0 - rr
def resample(v):
    im = cv2.imread("out/%s.png" % v).astype(np.float32) / 255.0
    mx, my = view_coords(v, U, Zr)
    ci = cv2.remap(im, mx.astype(np.float32), my.astype(np.float32), cv2.INTER_LINEAR, borderMode=cv2.BORDER_CONSTANT, borderValue=0)
    ca = cv2.remap(M[v], mx.astype(np.float32), my.astype(np.float32), cv2.INTER_LINEAR, borderMode=cv2.BORDER_CONSTANT, borderValue=0)
    return ci, ca
head_rows = slice(0, int(CR0 - Zchin) + 10)
for v, pv in PART.items():
    _, ap = resample(pv); apm = ap[:, ::-1]                                  # mirror about the canonical axis column
    shift_axis = int(round(2 * CU0c - (WC - 1)))                             # flip maps column c -> WC-1-c ; axis must map to itself
    apm = np.roll(apm, shift_axis, axis=1)
    best = None
    for tx in np.arange(100.0, 360.0, 1.0):
        cams[v]["tx"] = float(tx); _, av = resample(v)
        a_, b_ = av[head_rows] > 0.5, apm[head_rows] > 0.5
        iou = (a_ & b_).sum() / float((a_ | b_).sum() + 1)
        if best is None or iou > best[0]: best = (iou, tx)
    cams[v]["tx"] = float(best[1])
    print("%s: tx %.0f  head IoU with mirrored %s %.3f" % (v, best[1], pv, best[0]))
for v in names:
    im = cv2.imread("out/%s.png" % v).astype(np.float32) / 255.0
    mx, my = view_coords(v, U, Zr)
    ci = cv2.remap(im, mx.astype(np.float32), my.astype(np.float32), cv2.INTER_LINEAR, borderMode=cv2.BORDER_CONSTANT, borderValue=0)
    ca = cv2.remap(M[v], mx.astype(np.float32), my.astype(np.float32), cv2.INTER_LINEAR, borderMode=cv2.BORDER_CONSTANT, borderValue=0)
    np.save("out/c8_%s_img.npy" % v, ci); np.save("out/c8_%s_alpha.npy" % v, ca)
json.dump(cams, open("out/cams8.json", "w"), indent=1)
json.dump(dict(CU0=CU0c, CR0=CR0, HC=HC, WC=WC, KS=KS, Zbrow=Zbrow, Zchin=Zchin, az={v: cams[v]["az"] for v in names}), open("out/canon8.json", "w"), indent=1)
# check sheet with feature lines (front-view rows of brow, nose tip, mouth, chin)
pf = np.load("out/mp_v000.npy")
lines = [pf[i, 1] for i in (9, 4, 13, 152)]
tiles = []
for v in names:
    t = (np.load("out/c8_%s_img.npy" % v) * 255).astype(np.uint8)
    for y in lines: cv2.line(t, (0, int(y)), (WC, int(y)), (0, 140, 255), 1)
    cv2.putText(t, "%s az %.0f" % (v, cams[v]["az"]), (8, 24), cv2.FONT_HERSHEY_SIMPLEX, 0.6, (255, 255, 255), 1)
    tiles.append(t[:, 40:660])
cv2.imwrite("out/canon8_check.png", np.vstack([np.hstack(tiles[:4]), np.hstack(tiles[4:])]))
