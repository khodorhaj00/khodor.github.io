"""Shared geometry for the 8-view pipeline. Units: canonical pixels (front view), S8 mm per px.
model: X right (front view), Y away from the front camera, Z up. View at azimuth az sees u = X cos az - Y sin az
(canonical column u + CU0) and depth w = X sin az + Y cos az (grows away from that camera); canonical row = CR0 - Z."""
import json, numpy as np, cv2
from scipy import ndimage as ndi
C = json.load(open("out/canon8.json"))
CU0, CR0, HC, WC = C["CU0"], C["CR0"], C["HC"], C["WC"]
AZ = {k: float(v) for k, v in C["az"].items()}
NAMES = ["v000", "v045", "v090", "v135", "v180", "v225", "v270", "v315"]
S8 = json.load(open("out/scale8.json"))["S"]
# voxel grid (canonical px)
XV = np.arange(-215.0, 215.0); YV = np.arange(-70.0, 290.0); RV = np.arange(HC)     # rows = canonical rows
def load_view(v):
    img = np.load("out/c8_%s_img.npy" % v).astype(np.float64); al = np.load("out/c8_%s_alpha.npy" % v).astype(np.float64)
    L = 0.299 * img[..., 2] + 0.587 * img[..., 1] + 0.114 * img[..., 0]
    return img, L, al
def sil_sdf(al):
    m = al > 0.5
    return (ndi.distance_transform_edt(~m) - ndi.distance_transform_edt(m)).astype(np.float32)
def uw(az):
    t = np.radians(az); X, Y = np.meshgrid(XV, YV)
    return X * np.cos(t) - Y * np.sin(t), X * np.sin(t) + Y * np.cos(t)
def depth_map(vol, az, ucols=None):
    """first crossing (inside: vol<0) seen from the camera at azimuth az. returns (HC, WC) depth w (px), NaN = miss."""
    t = np.radians(az)
    us = np.arange(WC) - CU0; ws = np.arange(-330.0, 330.0)
    U, Wd = np.meshgrid(us, ws, indexing="ij")                      # (WC, nw)
    X = U * np.cos(t) + Wd * np.sin(t); Y = -U * np.sin(t) + Wd * np.cos(t)
    xi = (X - XV[0]); yi = (Y - YV[0])
    out = np.full((HC, WC), np.nan)
    for r in range(HC):
        sl = vol[r]
        if sl.min() >= 0: continue
        ph = ndi.map_coordinates(sl, [yi.ravel(), xi.ravel()], order=1, mode="constant", cval=5.0).reshape(U.shape)
        ins = ph < 0; has = ins.any(1); i = np.argmax(ins, 1); i0 = np.maximum(i - 1, 0)
        p0 = ph[np.arange(WC), i0]; p1 = ph[np.arange(WC), i]
        tt = np.clip(p0 / np.maximum(p0 - p1, 1e-6), 0, 1)
        d = ws[i0] + tt * (ws[i] - ws[i0]); d[~has] = np.nan
        out[r] = d
    return out
def shade(d, light=(-0.45, 0.55, 0.70)):
    m = ~np.isnan(d); dd = np.where(m, d, np.nanmax(d) if m.any() else 0)
    gx = np.gradient(dd, axis=1); gy = np.gradient(dd, axis=0)
    n = np.stack([gx, -gy, np.ones_like(gx)], -1); n /= np.linalg.norm(n, axis=-1, keepdims=True)
    l = np.array(light, float); l /= np.linalg.norm(l)
    return np.where(m, 0.18 + 0.82 * np.clip(n @ l, 0, 1), 0.0)
def compare_sheet(dms, path):
    tiles = []
    for v in NAMES:
        img = np.load("out/c8_%s_img.npy" % v)
        sh = np.repeat(shade(dms[v])[..., None], 3, -1).astype(np.float32)
        tiles.append(np.vstack([img[:, 60:640], sh[:, 60:640]]))
    sheet = (np.clip(np.hstack(tiles), 0, 1) * 255).astype(np.uint8)
    cv2.imwrite(path, cv2.resize(sheet, None, fx=0.5, fy=0.5, interpolation=cv2.INTER_AREA))
