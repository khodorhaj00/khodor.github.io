"""Shared helpers for the 4-view bust reconstruction."""
import json, numpy as np, cv2
from scipy import ndimage as ndi
VIEWS = ["front", "right", "back", "left"]
def load(v):
    im = cv2.imread("out/%s.png" % v).astype(np.float64) / 255.0
    lum = 0.299 * im[..., 2] + 0.587 * im[..., 1] + 0.114 * im[..., 0]
    m = np.load("out/%s_mask.npy" % v)
    return im, lum, m
def soft_alpha(lum, m):
    """sub-pixel coverage near the silhouette from luminance (background is ~black)."""
    inner = ndi.binary_erosion(m, iterations=3)
    fg = ndi.gaussian_filter(np.where(inner, lum, 0), 3) / np.maximum(ndi.gaussian_filter(inner.astype(float), 3), 1e-6)
    fg = ndi.grey_dilation(np.where(inner, fg, 0), size=7)
    bg = 0.02
    a = np.clip((lum - bg) / np.maximum(fg - bg, 0.05), 0, 1)
    band = ndi.binary_dilation(m, iterations=2) & ~ndi.binary_erosion(m, iterations=2)
    return np.where(band, a, m.astype(float))
def row_extents(alpha, thr=0.5):
    """per row: (left, right) sub-pixel silhouette extents of the outermost crossing, NaN if empty."""
    h, w = alpha.shape; L = np.full(h, np.nan); R = np.full(h, np.nan)
    for y in range(h):
        row = alpha[y]; idx = np.nonzero(row >= thr)[0]
        if len(idx) < 3: continue
        i = idx[0]
        if i > 0: a0, a1 = row[i - 1], row[i]; L[y] = i - 1 + (thr - a0) / max(a1 - a0, 1e-6) - 0.5 + 0.5
        else: L[y] = 0.0
        j = idx[-1]
        if j < w - 1: b0, b1 = row[j], row[j + 1]; R[y] = j + (b0 - thr) / max(b0 - b1, 1e-6)
        else: R[y] = w - 1.0
    return L, R
