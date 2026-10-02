"""Filter stereo points with the 8-view hull, add the triangulated face points, render point-cloud views."""
import numpy as np, cv2
from scipy import ndimage as ndi
from v_common import *
hull = np.load("out/hull_vol.npy")
pts = np.load("out/stereo_pts.npy").astype(np.float64)
X, Y, Z = pts[:, 0], pts[:, 1], pts[:, 2]
ci = [CR0 - Z, Y - YV[0], X - XV[0]]
hs = ndi.map_coordinates(hull, ci, order=1, mode="constant", cval=50.0)
keep = (hs < 2.0) & (hs > -14.0)
print("stereo points %d -> near hull surface %d (%.0f%%); hull sdf p50 %.1f" % (len(pts), keep.sum(), 100 * keep.mean(), np.median(hs)))
P = pts[keep]
# statistical outlier removal on a coarse grid: drop points far from the local median depth of their neighbours
from scipy.spatial import cKDTree
tr = cKDTree(P[:, :3]); dd, ii = tr.query(P[:, :3], k=12)
md = dd[:, 1:].mean(1); good = md < np.percentile(md, 95)
P = P[good]
face = np.load("out/face3d.npy"); face = face[~np.isnan(face).any(1)]
print("kept stereo points %d + %d triangulated face points" % (len(P), len(face)))
np.save("out/points_all.npy", np.vstack([P[:, :3], face]).astype(np.float32)); np.save("out/points_stereo_clean.npy", P.astype(np.float32))
# render: 4 views of the point cloud (front, 3/4, side, back), colour = image colour
def render(az, W=520, H=480):
    img = np.full((H, W, 3), 24, np.uint8)
    t = np.radians(az); u = P[:, 0] * np.cos(t) - P[:, 1] * np.sin(t); w = P[:, 0] * np.sin(t) + P[:, 1] * np.cos(t)
    o = np.argsort(-w)                                              # far first
    x = (u[o] * 1.0 + W / 2).astype(int); y = (CR0 - P[o, 2] + 20).astype(int)
    c = (np.clip(P[o, 3:6], 0, 1) * 255).astype(np.uint8)
    okk = (x >= 0) & (x < W) & (y >= 0) & (y < H)
    img[y[okk], x[okk]] = c[okk]
    fu = face[:, 0] * np.cos(t) - face[:, 1] * np.sin(t); fw = face[:, 0] * np.sin(t) + face[:, 1] * np.cos(t)
    for k in range(len(face)):
        if fw[k] < np.percentile(w, 60):
            cv2.circle(img, (int(fu[k] + W / 2), int(CR0 - face[k, 2] + 20)), 1, (60, 255, 90), -1)
    return img
tiles = [render(a) for a in (0, 35, 90, 180)]
for tl, txt in zip(tiles, ["front", "3/4", "side", "back"]):
    cv2.putText(tl, txt, (10, 24), cv2.FONT_HERSHEY_SIMPLEX, 0.6, (220, 220, 220), 1)
cv2.imwrite("out/points_views.png", np.hstack(tiles))
