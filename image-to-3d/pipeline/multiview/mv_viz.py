import numpy as np, cv2
from mv_vol import *
def shade(d, light=(-0.45, 0.55, 0.70)):
    """d: depth (mm, + away from camera) on a grid with spacing S; NaN = background."""
    m = ~np.isnan(d); dd = np.where(m, d, np.nanmax(d) if m.any() else 0)
    gx = np.gradient(dd, axis=1) / S; gy = np.gradient(dd, axis=0) / S
    n = np.stack([gx, -gy, np.ones_like(gx)], -1); n /= np.linalg.norm(n, axis=-1, keepdims=True)
    l = np.array(light, float); l /= np.linalg.norm(l)
    s = 0.18 + 0.82 * np.clip(n @ l, 0, 1)
    return np.where(m, s, 0.0)
def to_common(view, arr):
    """place a depth/shade map from voxel columns into the 780-wide common image"""
    out = np.full((NR, 780), np.nan if arr.dtype.kind == "f" else 0, arr.dtype)
    cols = XC if view in ("front", "back") else YC
    out[:, cols] = arr; return out
def compare_sheet(dm, path, title=""):
    tiles = []
    for v in ["front", "right", "back", "left"]:
        img = np.load("out/c_%s_img.npy" % v)
        d = dm[v].copy()
        if v == "back": d = -d
        if v == "left": d = -d
        sh = to_common(v, shade(d))
        sh3 = np.repeat(np.nan_to_num(sh)[..., None], 3, -1).astype(np.float32)
        tiles.append(np.vstack([img[:, 140:640], sh3[:, 140:640]]))
    sheet = (np.clip(np.hstack(tiles), 0, 1) * 255).astype(np.uint8)
    cv2.imwrite(path, cv2.resize(sheet, None, fx=0.75, fy=0.75, interpolation=cv2.INTER_AREA))
