"""Voxel helpers: per-slice lobe SDFs, union, depth maps along the 4 view axes."""
import numpy as np
S = 0.6181
NR = 480
XC = np.arange(99, 681); YC = np.arange(180, 666)              # voxel columns in common-image columns
Xv = (XC - 390.0) * S; Yv = (YC - 390.0) * S
def lobe_phi(X, Y, xl, xr, yf, yb, kap, n):
    """approx. signed distance (mm, + outside) of a 4-quadrant superellipse in the box [xl,xr]x[yf,yb]."""
    if not (xr > xl + 0.5 and yb > yf + 0.5): return np.full(np.broadcast(X, Y).shape, 1e3)
    cx = 0.5 * (xl + xr); cy = yf + kap * (yb - yf)
    dx = X - cx; dy = Y - cy
    a = np.where(dx > 0, xr - cx, cx - xl); b = np.where(dy > 0, yb - cy, cy - yf)
    g = (np.abs(dx / a) ** n + np.abs(dy / b) ** n) ** (1.0 / n)
    rr = np.hypot(dx, dy)
    return rr * (1.0 - 1.0 / np.maximum(g, 1e-6))
def smin(a, b, k):
    h = np.clip(0.5 + 0.5 * (b - a) / k, 0, 1); return b * (1 - h) + a * h - k * h * (1 - h)
def slice_phi(P, r):
    X, Y = np.meshgrid(Xv, Yv)                                  # (NYv, NXv)
    if r < P["TOP"]: return np.full(X.shape, 1e3)
    ph = lobe_phi(X, Y, P["mXL"][r], P["mXR"][r], P["mYF"][r], P["mYB"][r], P["kap"][r], P["mN"][r])
    if P["Bt"] <= r <= P["Bb"]:
        pb = lobe_phi(X, Y, P["bXL"][r], P["bXR"][r], P["bYF"][r], P["bYB"][r], P["bkap"][r], P["bN"])
        ph = smin(ph, pb, 9.0)
    if "Tt" in P and r >= P["Tt"]:
        pt = lobe_phi(X, Y, P["tXL"][r], P["tXR"][r], P["tYF"][r], P["tYB"][r], 0.5, P["tN"])
        ph = smin(ph, pt, 8.0)
    return ph
def depth_maps(vol):
    """vol: (NR, NYv, NXv) phi (+ outside). returns dict of depth maps (mm) along the 4 view axes, NaN = miss.
    front: Y of first hit from -Y; back: Y of first hit from +Y; right: X of first hit from -X; left: X from +X."""
    out = {}
    def first(arr, coords, axis, rev):
        a = np.moveaxis(arr, axis, -1)
        if rev: a = a[..., ::-1]; c = coords[::-1]
        else: c = coords
        ins = a < 0
        has = ins.any(-1); i = np.argmax(ins, -1); i0 = np.maximum(i - 1, 0)
        p0 = np.take_along_axis(a, i0[..., None], -1)[..., 0]; p1 = np.take_along_axis(a, i[..., None], -1)[..., 0]
        t = np.clip(p0 / np.maximum(p0 - p1, 1e-6), 0, 1)
        d = c[i0] + t * (c[i] - c[i0])
        d[(i == 0) & has] = c[0]; d[~has] = np.nan
        return d
    out["front"] = first(vol, Yv, 1, False)       # (NR, NXv)
    out["back"] = first(vol, Yv, 1, True)
    out["right"] = first(vol, Xv, 2, False)       # (NR, NYv)
    out["left"] = first(vol, Xv, 2, True)
    return out
def sdf3d(vol, trunc=30.0):
    """exact Euclidean signed distance (mm, + outside) of the occupancy vol<0, truncated."""
    from scipy import ndimage as ndi
    occ = vol < 0
    out = np.empty(vol.shape, np.float32)
    dout = ndi.distance_transform_edt(~occ).astype(np.float32); din = ndi.distance_transform_edt(occ).astype(np.float32)
    out[:] = (dout - din) * S
    # half-voxel bias: crossing sits between the two voxel centres
    out[occ] += 0.5 * S; out[~occ] -= 0.5 * S
    return np.clip(out, -trunc, trunc)
