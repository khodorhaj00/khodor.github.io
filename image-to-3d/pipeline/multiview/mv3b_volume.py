import numpy as np, time, sys
from mv_vol import *
from mv_viz import compare_sheet
P = dict(np.load("out/b0_params.npz"))
t0 = time.time()
vol = np.empty((NR, len(Yv), len(Xv)), np.float32)
for r in range(NR): vol[r] = slice_phi(P, r)
from scipy import ndimage as ndi
def cap_top(vol):
    r0 = int(np.argmax((vol < 0).reshape(vol.shape[0], -1).any(1)))
    for r in range(r0): vol[r] = np.maximum(vol[r0], 0) + (r0 - r) * S   # vertical distance above the crown, not a 1e3 wall
    return np.minimum(vol, 30.0)
vol = sdf3d(vol)
vol = ndi.gaussian_filter(vol, (2.0, 1.2, 1.2))
print("volume %s built in %.0fs" % (vol.shape, time.time() - t0))
dm = depth_maps(vol)
np.savez("out/b0_depth.npz", **dm)
compare_sheet(dm, "out/b0_compare.png")
np.save("out/b0_vol.npy", vol)
