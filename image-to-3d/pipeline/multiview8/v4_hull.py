"""8-view visual hull (robust: the single most-violating view is ignored), as a signed distance volume."""
import time, numpy as np
from scipy import ndimage as ndi
from v_common import *
t0 = time.time()
SD = {v: sil_sdf(load_view(v)[2]) for v in NAMES}
UW = {v: uw(AZ[v]) for v in NAMES}
vol = np.empty((HC, len(YV), len(XV)), np.float32)
for r in range(HC):
    stack = []
    for v in NAMES:
        u, _ = UW[v]
        stack.append(np.interp(u + CU0, np.arange(WC), SD[v][r], left=50.0, right=50.0))
    st = np.sort(np.stack(stack), axis=0)
    # head: strict intersection (silhouettes dilated 2 px); drapery: tolerate the single most-violating view
    # head: strict intersection (silhouettes dilated 2 px); drapery: tolerate the single most-violating view
    t = np.clip((r - 250.0) / 60.0, 0, 1)
    vol[r] = (1 - t) * (st[-1] - 2.0) + t * st[-2]
vol[:4] = np.maximum(vol[:4], 1.0)
print("hull built %.0fs, inside voxels %d" % (time.time() - t0, (vol < 0).sum()))
np.save("out/hull_vol.npy", vol)
dms = {v: depth_map(vol, AZ[v]) for v in NAMES}
np.savez("out/hull_depth.npz", **dms)
compare_sheet(dms, "out/hull_compare.png")
print("done %.0fs" % (time.time() - t0))
