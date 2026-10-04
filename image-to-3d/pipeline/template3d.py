"""Smooth 3D template SDF of the bust in model mm (X right, Y away from camera, Z up)."""
import json, numpy as np
S = 0.192
M = np.load("mp_matrix.npy"); R = M[:3, :3] / np.linalg.norm(M[:3, :3], axis=0)
s_cm, t_a, t_b, t_d = 52.18, 835.3, 769.9, 204.4
prims = json.load(open("out/prims2.json")); cran = json.load(open("out/cranium.json"))["cranium"]
sb = json.load(open("out/side_beard.json"))
r = np.load("out/rows.npz"); al, ar = r["al"], r["ar"]
a0 = 0.5 * (np.nanmean(al[1500:1530]) + np.nanmean(ar[1500:1530])); d0 = prims["d_t"]
# canonical cm -> model mm is affine: P = A c + t
def c2m(c):
    c = np.atleast_2d(c); cam = c @ R.T
    a = s_cm * cam[:, 0] + t_a; b = -s_cm * cam[:, 1] + t_b; d = -1.007 * s_cm * cam[:, 2] + t_d
    return np.stack([(a - a0) * S, (d - d0) * S, (1536.0 - b) * S], -1)
T0 = c2m([0, 0, 0])[0]
A = np.stack([c2m(e)[0] - T0 for e in np.eye(3)], 1)          # columns: model image of canonical unit axes
Ainv = np.linalg.inv(A)
def m2c(P): return (P - T0) @ Ainv.T
def rotx(t):
    t = np.radians(t); return np.array([[1, 0, 0], [0, np.cos(t), -np.sin(t)], [0, np.sin(t), np.cos(t)]])
def sd_ellipsoid(p, rad):
    k0 = np.linalg.norm(p / rad, axis=-1); k1 = np.linalg.norm(p / (rad * rad), axis=-1)
    return k0 * (k0 - 1.0) / np.maximum(k1, 1e-9)
SCALE = float(np.mean(np.linalg.norm(A, axis=0)))               # mm per canonical cm (~10)
def head_ell(P, c, ax, tilt=0.0):
    q = (m2c(P) - np.array(c)) @ rotx(tilt)
    return sd_ellipsoid(q, np.array(ax, float)) * SCALE
def smin(a, b, k):
    h = np.clip(0.5 + 0.5 * (b - a) / k, 0, 1); return b * (1 - h) + a * h - k * h * (1 - h)
neck_a, neck_d, neck_rpx = prims["neck"]
NECK = np.array([(neck_a - a0) * S, (neck_d - d0) * S]); NECK_R = neck_rpx * S
def sd_capsule_z(P, cxy, z0, z1, rad):
    q = P.copy(); q[..., 2] = np.clip(P[..., 2], z0, z1)
    q[..., 0] = cxy[0]; q[..., 1] = cxy[1]
    return np.linalg.norm(P - q, axis=-1) - rad
TORSO = dict(c=np.array([0.0, 8.0, -28.0]), ax=np.array([140.0, 92.0, 112.0]), n=2.6)
def sd_superellipsoid(P, c, ax, n):
    q = np.abs(P - c) / ax
    f = (q[..., 0] ** n + q[..., 1] ** n + q[..., 2] ** n) ** (1.0 / n)
    return (f - 1.0) * np.min(ax) * 0.9
def ear_sdf(P, side):
    """dish-shaped ear: flattened ellipsoid with a concave bowl on its outer face (side -1 = near/right ear)."""
    c = np.array([side * 8.4, 0.84, -4.14])
    outer = head_ell(P, c, [1.25, 3.2, 1.85], -14.0)
    bowl = head_ell(P, c + np.array([side * 1.05, -0.35, 0.25]), [0.75, 1.9, 1.05], -14.0)
    return np.maximum(outer, -bowl)
def template_sdf(P, far_ear=True, near_ear=True):
    d = head_ell(P, [0.0, cran[1], cran[2]], cran[3:])
    sy, sz, sax, say, saz = sb["side"]; d = smin(d, head_ell(P, [0.0, sy, sz], [sax, say, saz]), 22.0)
    by, bz, bax, bay, baz, bt = sb["beard"]; d = smin(d, head_ell(P, [0.0, by, bz], [bax, bay, baz], bt), 18.0)
    if near_ear: d = smin(d, ear_sdf(P, -1), 3.0)
    if far_ear: d = smin(d, ear_sdf(P, 1), 3.0)
    d = smin(d, sd_capsule_z(P, NECK, 20.0, 150.0, NECK_R * 0.97), 20.0)
    d = smin(d, sd_superellipsoid(P, TORSO["c"], TORSO["ax"], TORSO["n"]), 22.0)
    d = np.maximum(d, -P[..., 2])                     # flat cut at the base Z = 0
    return d

# ---------- per-row lateral warp so the template silhouette equals the photo silhouette ----------
import os
WARP = None
def smooth_warp(bs, Tl, Tr, Xl, Xr, sig=3.0):
    from scipy.ndimage import gaussian_filter1d
    ok = ~(np.isnan(Tl) | np.isnan(Xl))
    out = [bs[ok]]
    for arr in (Tl, Tr, Xl, Xr):
        out.append(gaussian_filter1d(arr[ok], sig, mode="nearest"))
    return tuple(out)
def build_warp(step_rows=4, xs=np.arange(-210, 210, 0.5), ys=np.arange(-200, 220, 2.0)):
    global WARP
    if os.path.exists("out/tmpl_warp.npz"):
        w = np.load("out/tmpl_warp.npz"); WARP = smooth_warp(w["b"], w["Tl"], w["Tr"], w["Xl"], w["Xr"]); return
    bs = np.arange(0, 1536, step_rows); Tl = np.full(len(bs), np.nan); Tr = np.full(len(bs), np.nan)
    X, Y = np.meshgrid(xs, ys, indexing="ij")
    for i, b in enumerate(bs):
        Z = (1536.0 - b) * S
        ins = template_sdf(np.stack([X, Y, np.full_like(X, Z)], -1), far_ear=False, near_ear=False) < 0
        col = ins.any(1)
        if col.any(): Tl[i] = xs[np.argmax(col)]; Tr[i] = xs[len(col) - 1 - np.argmax(col[::-1])]
    Xl = (r["al_skull"][bs] - a0) * S; Xr = (ar[bs] - a0) * S
    np.savez("out/tmpl_warp.npz", b=bs, Tl=Tl, Tr=Tr, Xl=Xl, Xr=Xr); WARP = smooth_warp(bs, Tl, Tr, Xl, Xr)
def warped_template_sdf(P):
    bs, Tl, Tr, Xl, Xr = WARP
    b = 1536.0 - P[..., 2] / S
    tl = np.interp(b, bs, Tl); tr = np.interp(b, bs, Tr); xl = np.interp(b, bs, Xl); xr = np.interp(b, bs, Xr)
    Xt = tl + (P[..., 0] - xl) * (tr - tl) / np.maximum(xr - xl, 1e-3)
    Q = P.copy(); Q[..., 0] = Xt
    return template_sdf(Q)
