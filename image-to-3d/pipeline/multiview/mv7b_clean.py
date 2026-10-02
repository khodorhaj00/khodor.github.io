"""Remove row-to-row radius spikes (rays grazing thin folds pick different surfaces in adjacent rows)."""
import numpy as np, json
from scipy import ndimage as ndi
R = np.load("out/mv_mesh_R.npy").astype(np.float64)
for it in range(3):
    Rp = np.concatenate([R[:, -2:], R, R[:, :2]], 1)                 # periodic in u
    Rm = ndi.median_filter(Rp, size=(5, 3), mode="nearest")[:, 2:-2]
    j = np.zeros_like(R); j[1:-1] = np.abs(R[2:] - 2 * R[1:-1] + R[:-2])
    bad = (np.abs(R - Rm) > 1.2) & (ndi.maximum_filter(j, size=(3, 1), mode="nearest") > 1.5)
    bad = ndi.binary_dilation(bad, structure=np.ones((3, 1), bool))
    R = np.where(bad, Rm, R)
    print("pass %d: replaced %d cells" % (it, bad.sum()))
j = np.abs(R[2:] - 2 * R[1:-1] + R[:-2]); print("2nd-diff p99 %.3f max %.1f cells>2mm %d" % (np.percentile(j, 99), j.max(), (j > 2).sum()))
# anti-alias sharp steps (fold edges / overhang outlines crossing the grid diagonally render as staircases)
Rp = np.concatenate([R[:, -3:], R, R[:, :3]], 1)
gr = np.abs(np.gradient(Rp, axis=0)); gu = np.abs(np.gradient(Rp, axis=1))
step = np.maximum(gr, gu)
wst = np.clip((ndi.maximum_filter(step, size=3) - 2.0) / 2.0, 0, 1)
wst = ndi.gaussian_filter(wst, 1.0)
Rb = ndi.gaussian_filter(Rp, 1.3, mode="nearest")
R = ((1 - wst) * Rp + wst * Rb)[:, 3:-3]
print("anti-aliased %.2f%% of cells" % (100 * (wst[:, 3:-3] > 0.3).mean()))
np.save("out/mv_mesh_Rc.npy", R.astype(np.float32))
