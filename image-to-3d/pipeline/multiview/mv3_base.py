"""Base shape B0 (no face detail, no ears): per-slice smooth lobes fitted to the 4 aligned silhouettes.
lobes: main (head -> neck, rows 6..474), beard (240..406), torso (338..474)."""
import json, numpy as np
from scipy.ndimage import gaussian_filter1d
A = json.load(open("out/align.json")); S = A["S"]
NR = 480; rows = np.arange(NR, dtype=float)
e = {v: (np.load("out/c_%s_ext.npy" % v) - 390.0) * S for v in ["front", "right", "back", "left"]}
def fill(x):
    ok = ~np.isnan(x); return np.interp(rows, rows[ok], x[ok])
XLf, XRf = fill(e["front"][:, 0]), fill(e["front"][:, 1]); XLb, XRb = fill(e["back"][:, 0]), fill(e["back"][:, 1])
YFs = 0.5 * (fill(e["right"][:, 0]) + fill(e["left"][:, 0])); YBs = 0.5 * (fill(e["right"][:, 1]) + fill(e["left"][:, 1]))
TOP = 6.0
def hermite(arr, r0, r1):
    a = arr.copy(); s0 = (arr[r0] - arr[r0 - 6]) / 6.0; s1 = (arr[r1 + 6] - arr[r1]) / 6.0
    t = (rows[r0:r1 + 1] - r0) / float(r1 - r0); L = float(r1 - r0)
    h00, h10, h01, h11 = 2 * t**3 - 3 * t**2 + 1, t**3 - 2 * t**2 + t, -2 * t**3 + 3 * t**2, t**3 - t**2
    a[r0:r1 + 1] = h00 * arr[r0] + h10 * L * s0 + h01 * arr[r1] + h11 * L * s1
    return a
def sstep(x, a, b):
    t = np.clip((x - a) / (b - a), 0, 1); return t * t * (3 - 2 * t)
def sm(x, s): return gaussian_filter1d(x, s, mode="nearest")
XLf_n, XRf_n, XLb_n, XRb_n = [hermite(x, 163, 266) for x in (XLf, XRf, XLb, XRb)]     # ears removed
line = np.interp(rows, [186, 270], [YFs[186], YFs[270]])
YF_open = YFs.copy(); seg = (rows >= 186) & (rows <= 270); YF_open[seg] = np.maximum(YFs[seg], line[seg])  # nose removed
wf = 0.6
# ---------------- main lobe: head -> neck (the neck continues down inside the torso)
XL_head, XR_head = wf * XLf_n + (1 - wf) * XLb_n, wf * XRf_n + (1 - wf) * XRb_n
neckL = XLb_n.copy(); neckR = XRb_n.copy()
nk = rows > 340; neckL[nk] = neckL[340]; neckR[nk] = neckR[340]                  # neck width frozen under the drapery
t_neck = sstep(rows, 256, 290)
mXL = (1 - t_neck) * XL_head + t_neck * neckL; mXR = (1 - t_neck) * XR_head + t_neck * neckR
mYF = YF_open.copy()
lip = (rows >= 268) & (rows <= 296); mYF[lip] = YFs[lip]
anc_r = [296, 330, 352, 372, 392, 410, 474]; anc_y = [YFs[296] + 3.0, -80.0, -62.0, -44.0, -36.0, -33.0, -28.0]
sel = rows > 296; mYF[sel] = np.interp(rows[sel], anc_r, anc_y)
mYB = YBs.copy(); back = rows > 342; mYB[back] = np.interp(rows[back], [342, 474], [YBs[342], YBs[342] - 6.0])
kap = np.interp(rows, [0, 150, 190, 250, 290, 480], [0.58, 0.58, 0.62, 0.62, 0.5, 0.5])
mN = np.interp(rows, [0, 150, 190, 250, 290, 340, 480], [2.4, 2.4, 2.0, 2.0, 2.15, 2.15, 2.15])
# ---------------- beard lobe
Bt, Bb = 240.0, 406.0
tb = sstep(rows, 240, 272)
bXL = (1 - tb) * mXL + tb * XLf_n; bXR = (1 - tb) * mXR + tb * XRf_n
bXL[rows >= 266] = XLf[rows >= 266]; bXR[rows >= 266] = XRf[rows >= 266]
uc, uh = 3.0, 58.0
uw = uh * np.sqrt(np.clip(1 - ((rows - 345.0) / (Bb - 345.0)) ** 2, 0, 1))
tu = sstep(rows, 336, 350)
bXL = (1 - tu) * bXL + tu * (uc - uw); bXR = (1 - tu) * bXR + tu * (uc + uw)
bYF = YFs.copy(); bYF[rows < 270] = YF_open[rows < 270]
bYB = np.interp(rows, [Bt, 270, 300, 340, Bb], [12.0, 16.0, 8.0, -18.0, -40.0])
bkap = np.interp(rows, [Bt, 290, 360, Bb], [0.72, 0.72, 0.5, 0.5])
# ---------------- torso lobe (shoulders + drapery)
Tt = 338.0
XL_t, XR_t = wf * XLf + (1 - wf) * XLb, wf * XRf + (1 - wf) * XRb
tt = sstep(rows, 340, 358)
tXL = (1 - tt) * neckL + tt * XL_t; tXR = (1 - tt) * neckR + tt * XR_t
tYB = YBs.copy()
tYF = np.interp(rows, [Tt, 360, 390, 418], [8.0, -8.0, -24.0, YFs[418]]); tYF[rows > 418] = YFs[rows > 418]
tYB[rows < 346] = np.interp(rows[rows < 346], [Tt, 346], [YBs[338] - 2.0, YBs[346]])
P = dict(mXL=sm(mXL, 3.0), mXR=sm(mXR, 3.0), mYF=np.where(rows < 186, sm(mYF, 6.0), sm(mYF, 2.0)), mYB=sm(mYB, 3.0),
         kap=sm(kap, 4.0), mN=sm(mN, 4.0),
         bXL=sm(bXL, 2.5), bXR=sm(bXR, 2.5), bYF=sm(bYF, 1.5), bYB=bYB, bkap=sm(bkap, 4.0), Bt=Bt, Bb=Bb, bN=1.8,
         tXL=sm(tXL, 2.5), tXR=sm(tXR, 2.5), tYF=sm(tYF, 2.5), tYB=sm(tYB, 2.5), Tt=Tt, tN=2.3,
         TOP=TOP, S=S, YFs=YFs, YBs=YBs, XLf=XLf, XRf=XRf, XLb=XLb, XRb=XRb, YF_open=YF_open)
np.savez("out/b0_params.npz", **P)
print("saved b0 params; head width (row 120) %.1f mm, depth %.1f mm" % (P["mXR"][120] - P["mXL"][120], P["mYB"][120] - P["mYF"][120]))
