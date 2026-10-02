"""Step 1e: light direction from silhouette-rim brightness + front-facing brightness (first-order SH)."""
import numpy as np, cv2
from scipy import ndimage as ndi
from viz import normals
L = np.load("out/lum.npy"); m = np.load("out/mask.npy")
c = max(cv2.findContours(m.astype(np.uint8), cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_NONE)[0], key=len)[:, 0, :].astype(float)
cs = np.stack([ndi.uniform_filter1d(c[:, 0], 9, mode="wrap"), ndi.uniform_filter1d(c[:, 1], 9, mode="wrap")], 1)
t = np.gradient(cs, axis=0); t /= np.linalg.norm(t, axis=1, keepdims=True); nrm = np.stack([t[:, 1], -t[:, 0]], 1)
tst = (cs - 6 * nrm).round().astype(int)
if m[np.clip(tst[:, 1], 0, m.shape[0] - 1), np.clip(tst[:, 0], 0, m.shape[1] - 1)].mean() < 0.5: nrm = -nrm
keep = cs[:, 1] < m.shape[0] - 16
vals = [np.median([L[int(round(y - d * uy)), int(round(x - d * ux))] for d in (5, 7, 9)]) for (x, y), (ux, uy) in zip(cs[keep], nrm[keep])]
A = np.c_[np.ones(keep.sum()), nrm[keep, 0], -nrm[keep, 1]]; c0, cx, cy = np.linalg.lstsq(A, np.array(vals), rcond=None)[0]
n = normals(np.load("out/F_prior_s.npy")); sel = ndi.binary_erosion(m, iterations=25) & (n[..., 2] > 0.95) & (L > 0.3)
cz = np.median(L[sel]) - c0
np.save("out/light_rim.npy", np.r_[c0, cx, cy, cz]); print("light", np.round(np.r_[cx, cy, cz] / np.linalg.norm([cx, cy, cz]), 3))
