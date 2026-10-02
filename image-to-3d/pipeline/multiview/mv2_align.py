"""Align the 4 views into one orthographic frame.
Model frame (mm): X = subject's left, Y = back, Z = up (Z=0 at the bust base), face toward -Y.
Common images: front/back on an (X,Z) grid, right/left on a (Y,Z) grid, all at the front-view pixel size S.
Rows of every common image are front-view rows (feature-matched with a piecewise-linear vertical warp)."""
import json, numpy as np, cv2
from mv_common import *
S = 0.6181                     # mm/px from the MediaPipe canonical-face fit on the front view
B_BASE = 474.0                 # front-view row of the base cut  (Z = (B_BASE - row) * S)
NR, NX, NY, CX0, CY0 = 480, 780, 780, 390.0, 390.0
# vertical anchors: (view row, front row)  -- head top, brow, nasion, nose tip, subnasale, stomion, beard tip, base
ANCH = {
    "front": [(0, 0), (480, 480)],
    "right": [(14, 6), (172, 166), (190, 188.5), (252, 247.4), (268, 268.3), (304, 304.6), (391, 405), (474, 474)],
    "left":  [(11, 6), (166, 166), (178, 188.5), (237, 247.4), (256, 268.3), (292, 304.6), (379, 405), (470, 474)],
    "back":  [(8, 6), (160, 166), (250, 262), (334, 350), (470, 474)],
}
def vmap(v, b):
    a = np.array(ANCH[v], float); fr, vr = a[:, 1], a[:, 0]
    out = np.interp(b, fr, vr)
    lo = b < fr[0]; hi = b > fr[-1]
    out[lo] = vr[0] + (b[lo] - fr[0]) * (vr[1] - vr[0]) / (fr[1] - fr[0])
    out[hi] = vr[-1] + (b[hi] - fr[-1]) * (vr[-1] - vr[-2]) / (fr[-1] - fr[-2])
    return out
e = np.load("out/extents.npz")
rows = np.arange(NR, dtype=float)
def ext_at(v, side, b):          # silhouette extent of view v at common rows b (view columns)
    arr = e["%s_%s" % (v, side)]; vb = vmap(v, b); ok = ~np.isnan(arr); idx = np.arange(len(arr))
    out = np.interp(vb, idx[ok], arr[ok]); out[(vb < idx[ok][0]) | (vb > idx[ok][-1])] = np.nan; return out
# --- X: front/back.  cx_f = cranium centre of the front view; cx_b from overlap on cranium rows 40..150
cr = np.arange(40, 151, dtype=float)
cx_f = float(np.nanmean(0.5 * (ext_at("front", "L", cr) + ext_at("front", "R", cr))))
K = np.nanmean(np.r_[ext_at("back", "R", cr) + ext_at("front", "L", cr), ext_at("back", "L", cr) + ext_at("front", "R", cr)])
cx_b = float(K - cx_f)
# --- Y: right/left.  cy_r = depth centre of the right view on cranium rows; cy_l from overlap rows 20..330 (head+neck)
hr = np.arange(20, 331, dtype=float)
cy_r = float(np.nanmean(0.5 * (ext_at("right", "L", cr) + ext_at("right", "R", cr))))
K2 = np.nanmean(np.r_[ext_at("left", "L", hr) + ext_at("right", "R", hr), ext_at("left", "R", hr) + ext_at("right", "L", hr)])
cy_l = float(K2 - cy_r)
print("cx_f %.1f cx_b %.1f | cy_r %.1f cy_l %.1f" % (cx_f, cx_b, cy_r, cy_l))
# column maps: common column c -> view column
col = np.arange(NX, dtype=float)
cmap = {"front": cx_f + (col - CX0),             # X = (c-CX0)*S = (a-cx_f)*S
        "back": cx_b - (col - CX0),              # X = -(a-cx_b)*S
        "right": cy_r - (col - CY0),             # Y = -(a-cy_r)*S
        "left": cy_l + (col - CY0)}              # Y =  (a-cy_l)*S
ALIGN = dict(S=S, B_BASE=B_BASE, NR=NR, NX=NX, NY=NY, CX0=CX0, CY0=CY0, cx_f=cx_f, cx_b=cx_b, cy_r=cy_r, cy_l=cy_l, ANCH=ANCH)
json.dump(ALIGN, open("out/align.json", "w"), indent=1)
for v in VIEWS:
    im, lum, m = load(v); al = np.load("out/%s_alpha.npy" % v)
    my = vmap(v, rows).astype(np.float32); mx = cmap[v].astype(np.float32)
    MX, MY = np.meshgrid(mx, my)
    imc = cv2.remap(im.astype(np.float32), MX, MY, cv2.INTER_LINEAR, borderMode=cv2.BORDER_CONSTANT, borderValue=0)
    alc = cv2.remap(al.astype(np.float32), MX, MY, cv2.INTER_LINEAR, borderMode=cv2.BORDER_CONSTANT, borderValue=0)
    # label text / panel border must not leak in: kill rows below the view's base
    base_c = np.interp(ANCH[v][-1][0] if v != "front" else 474, vmap(v, rows), rows)
    alc[rows > base_c + 0.5] = 0; imc[rows > base_c + 0.5] = 0
    np.save("out/c_%s_img.npy" % v, imc); np.save("out/c_%s_alpha.npy" % v, alc)
    print(v, "base row in common frame %.1f" % base_c)
# ---- check sheet: aligned views + feature lines, and silhouette overlays
tiles = []
for v in VIEWS:
    imc = (np.load("out/c_%s_img.npy" % v) * 255).astype(np.uint8)
    for fr in (6, 166, 188.5, 247.4, 268.3, 304.6, 405, 474):
        cv2.line(imc, (0, int(round(fr))), (NX, int(round(fr))), (0, 140, 255), 1)
    cv2.putText(imc, v, (10, 30), cv2.FONT_HERSHEY_SIMPLEX, 0.8, (255, 255, 255), 2); tiles.append(imc)
cv2.imwrite("out/aligned_views.png", cv2.resize(np.hstack(tiles), None, fx=0.6, fy=0.6))
af, ab, ar, alf = [np.load("out/c_%s_alpha.npy" % v) > 0.5 for v in VIEWS]
ov1 = np.dstack([af * 255, ab * 255, np.zeros_like(af, np.uint8) * 0]).astype(np.uint8)
ov2 = np.dstack([ar * 255, alf * 255, np.zeros_like(ar, np.uint8)]).astype(np.uint8)
cv2.imwrite("out/aligned_sil.png", np.hstack([ov1, ov2]))
