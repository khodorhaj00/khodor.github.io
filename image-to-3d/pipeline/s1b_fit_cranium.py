"""Fit cranium ellipsoid (head frame from MediaPipe) to upper silhouette + forehead landmarks."""
import numpy as np, json
from scipy.optimize import minimize
r = np.load("out/rows.npz"); al, ar = r["al"], r["ar"]; al_skull = r["al_skull"]
lm = np.load("mp_landmarks_px.npy")
M = np.load("mp_matrix.npy"); R = M[:3, :3] / np.linalg.norm(M[:3, :3], axis=0)
s_cm, t_a, t_b, t_d = 52.18, 835.3, 769.9, 204.4
def canon_to_px(c):
    cam = np.atleast_2d(c) @ R.T
    return np.c_[s_cm * cam[:, 0] + t_a, -s_cm * cam[:, 1] + t_b, -1.007 * s_cm * cam[:, 2] + t_d]
def px_to_canon(p):
    p = np.atleast_2d(p); cam = np.c_[(p[:, 0] - t_a) / s_cm, -(p[:, 1] - t_b) / s_cm, -(p[:, 2] - t_d) / (1.007 * s_cm)]
    return cam @ R          # inverse rotation
U, V = np.meshgrid(np.linspace(0, 2 * np.pi, 220), np.linspace(0, np.pi, 160))
def surf(par):
    cx, cy, cz, ax, ay, az = par
    pts = np.c_[(cx + ax * np.sin(V) * np.cos(U)).ravel(), (cy + ay * np.cos(V)).ravel(), (cz + az * np.sin(V) * np.sin(U)).ravel()]
    return canon_to_px(pts)
rows_fit = np.arange(12, 460, 4)
fore = [10, 109, 67, 103, 54, 338, 297, 332, 284, 151, 108, 69, 104, 337, 299, 333]
lm_fore = px_to_canon(lm[fore])
lm_face = px_to_canon(lm[:468])
def loss(par, verbose=False):
    cx, cy, cz, ax, ay, az = par
    P = surf(par)
    bins = np.round(P[:, 1]).astype(int)
    e = 0.0; n = 0
    for b in rows_fit:
        sel = np.abs(P[:, 1] - b) < 2.5
        if sel.sum() < 3: e += 400.0; n += 1; continue
        e += (P[sel, 0].min() - al[b]) ** 2 + (P[sel, 0].max() - ar[b]) ** 2; n += 2
    e /= max(n, 1)
    top = P[:, 1].min(); e += 0.5 * (top - 9.0) ** 2
    # forehead on surface (radial units cm -> px)
    q = (lm_fore - [cx, cy, cz]) / [ax, ay, az]; rr = np.linalg.norm(q, axis=1)
    e += 40.0 * np.mean(((rr - 1.0) * 8.5 * s_cm) ** 2) / 100.0
    # face points must not be inside the ellipsoid by more than ~0.3 cm (eye sockets slightly allowed)
    qf = (lm_face - [cx, cy, cz]) / [ax, ay, az]; rf = np.linalg.norm(qf, axis=1)
    e += 2.0 * np.sum(np.clip(0.97 - rf, 0, None) ** 2) * 1e3
    if verbose: print("silhouette rms px %.1f  top %.1f  fore radial %s" % (np.sqrt(e), top, np.round(rr, 3)))
    return e
x0 = np.array([0.0, 3.0, -4.5, 7.6, 9.0, 9.8])
res = minimize(loss, x0, method="Powell", options=dict(maxiter=6000, xtol=1e-3, ftol=1e-4))
print(res.x, res.fun); loss(res.x, True)
json.dump(dict(cranium=res.x.tolist()), open("out/cranium.json", "w"))
