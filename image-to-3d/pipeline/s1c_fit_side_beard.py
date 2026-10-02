"""Joint fit: head-side ellipsoid (temporal/zygomatic level) + beard ellipsoid to the silhouette & landmarks."""
import numpy as np, json
from scipy.optimize import minimize
r = np.load("out/rows.npz"); al, ar, al_skull = r["al"], r["ar"], r["al_skull"]
mask = np.load("out/mask.npy")
lm = np.load("mp_landmarks_px.npy"); M = np.load("mp_matrix.npy"); R = M[:3, :3] / np.linalg.norm(M[:3, :3], axis=0)
s_cm, t_a, t_b, t_d = 52.18, 835.3, 769.9, 204.4
def c2p(c):
    cam = np.atleast_2d(c) @ R.T
    return np.c_[s_cm * cam[:, 0] + t_a, -s_cm * cam[:, 1] + t_b, -1.007 * s_cm * cam[:, 2] + t_d]
def p2c(p):
    p = np.atleast_2d(p); cam = np.c_[(p[:, 0] - t_a) / s_cm, -(p[:, 1] - t_b) / s_cm, -(p[:, 2] - t_d) / (1.007 * s_cm)]
    return cam @ R
TH, PH = np.meshgrid(np.linspace(0, 2 * np.pi, 120), np.linspace(0, np.pi, 80))
UNIT = np.c_[(np.sin(PH) * np.cos(TH)).ravel(), np.cos(PH).ravel(), (np.sin(PH) * np.sin(TH)).ravel()]
def rotx(t):
    t = np.radians(t); return np.array([[1, 0, 0], [0, np.cos(t), -np.sin(t)], [0, np.sin(t), np.cos(t)]])
def ell_pts(c, ax, tilt=0.0):
    return c2p((UNIT * ax) @ rotx(tilt).T + c)
def ell_r(pc, c, ax, tilt=0.0):
    return np.linalg.norm(((pc - c) @ rotx(tilt)) / ax, axis=1)
def extents(P, rows):
    out = {}
    bi = np.round(P[:, 1]).astype(int)
    for b in rows:
        sel = np.abs(P[:, 1] - b) < 3.0
        if sel.sum() >= 2: out[b] = (P[sel, 0].min(), P[sel, 0].max())
    return out
cran = json.load(open("out/cranium.json"))["cranium"]
Pc = ell_pts(cran[:3], cran[3:])
far_ids = [251, 389, 356, 454, 323, 361, 288, 397]
jaw_ids = [132, 58, 172, 136, 150, 149, 176, 148, 152, 377, 400, 378, 379, 365, 397, 288, 361]
face_c = p2c(lm[:468]); far_c = p2c(lm[far_ids]); jaw_c = p2c(lm[jaw_ids])
rows_r = np.arange(470, 1100, 6); rows_l = np.arange(470, 850, 6)
def loss(par, verbose=False):
    sy, sz, sax, say, saz, by, bz, bax, bay, baz, btilt = par
    sc_, sa = np.array([0.0, sy, sz]), np.array([sax, say, saz])
    bc_, ba = np.array([0.0, by, bz]), np.array([bax, bay, baz])
    P = np.vstack([Pc, ell_pts(sc_, sa), ell_pts(bc_, ba, btilt)])
    ex = extents(P, np.unique(np.r_[rows_r, rows_l, np.arange(1100, 1330, 8)]))
    e = 0.0; n = 0
    for b in rows_r:
        if b in ex: e += (ex[b][1] - ar[b]) ** 2; n += 1
        else: e += 1e4; n += 1
    for b in rows_l:
        if b in ex: e += (ex[b][0] - al_skull[b]) ** 2; n += 1
    # do not overshoot the mask below the ear rows (neck covers the left there)
    for b in np.arange(850, 1330, 8):
        if b in ex:
            e += np.clip(al[b] - ex[b][0], 0, None) ** 2 * 0.5 + np.clip(ex[b][1] - ar[b], 0, None) ** 2; n += 1
    e /= max(n, 1)
    # beard lowest point -> beard tip (b 1330, a ~880)
    Pb = ell_pts(bc_, ba, btilt); low = Pb[np.argmax(Pb[:, 1])]
    e += ((low[1] - 1330.0) / 6.0) ** 2 + ((low[0] - 880.0) / 30.0) ** 2
    # far face-oval landmarks on the side ellipsoid, jaw landmarks on the beard ellipsoid
    e += 300.0 * np.mean((ell_r(far_c, sc_, sa) - 1.0) ** 2)
    e += 300.0 * np.mean((ell_r(jaw_c, bc_, ba, btilt) - 1.0) ** 2)
    # face points should not sit deep inside the side ellipsoid (face mesh must win)
    e += 1e3 * np.sum(np.clip(0.93 - ell_r(face_c, sc_, sa), 0, None) ** 2)
    if verbose:
        print("rms %.1f  beard low (%.0f, %.0f)  far r %s  jaw r %s" % (np.sqrt(e), low[0], low[1], np.round(ell_r(far_c, sc_, sa), 3), np.round(ell_r(jaw_c, bc_, ba, btilt), 3)))
    return e
x0 = np.array([1.0, -3.6, 7.2, 5.5, 8.0, -5.4, -2.4, 6.8, 5.2, 7.6, 12.0])
res = minimize(loss, x0, method="Powell", options=dict(maxiter=20000, xtol=1e-3, ftol=1e-5))
res = minimize(loss, res.x, method="Nelder-Mead", options=dict(maxiter=20000, xatol=1e-3, fatol=1e-5))
print(np.round(res.x, 3), res.fun); loss(res.x, True)
json.dump(dict(side=res.x[:5].tolist(), beard=res.x[5:].tolist()), open("out/side_beard.json", "w"))
