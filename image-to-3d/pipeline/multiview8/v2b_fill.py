"""Fill face landmarks that were seen in < 2 views: front-view MediaPipe x,y,z mapped into the triangulated frame
(affine fit on the triangulated points), so the face mesh has no gaps."""
import json, numpy as np
f = np.load("out/face3d.npy"); bad = np.isnan(f).any(1)
p = np.load("out/mp_v000.npy")[:468]
cam = json.load(open("out/cams_face.json"))
ok = ~bad
A = np.c_[p[ok, 0], p[ok, 1], p[ok, 2], np.ones(ok.sum())]
coef, *_ = np.linalg.lstsq(A, f[ok], rcond=None)                     # 4x3 affine: front MP -> model
pred = np.c_[p[:, 0], p[:, 1], p[:, 2], np.ones(468)] @ coef
res = np.linalg.norm(pred[ok] - f[ok], axis=1)
print("affine fit MP(front) -> triangulated: rms %.2f px ; filling %d landmarks" % (np.sqrt(np.mean(res ** 2)), bad.sum()))
# keep the triangulated points, fill the rest; blend the filled ones toward neighbours' residual
from scipy.spatial import cKDTree
tr = cKDTree(p[ok, :2]); d, i = tr.query(p[bad, :2], k=6)
corr = (f[ok] - pred[ok])[i].mean(1)
f[bad] = pred[bad] + corr
np.save("out/face3d_full.npy", f)
print("filled; depth range Y %.1f .. %.1f px" % (f[:, 1].min(), f[:, 1].max()))
