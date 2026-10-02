"""Smooth the prior: normalized-convolution blur inside the mask, stronger on the faceted face region and torso rows."""
import numpy as np, cv2
from scipy import ndimage as ndi
F = np.load("out/F_prior.npy").astype(np.float64); B = np.load("out/B_prior.npy").astype(np.float64)
mask = np.load("out/mask.npy")
def nblur(X, m, sx, sy=None):
    sy = sx if sy is None else sy
    Xn = np.where(m, np.nan_to_num(X), 0.0); w = m.astype(np.float64)
    num = ndi.gaussian_filter(Xn, (sy, sx)); den = ndi.gaussian_filter(w, (sy, sx))
    return np.where(m, num / np.maximum(den, 1e-6), np.nan)
edge = ndi.distance_transform_edt(mask)
# 1) vertical smoothing for the torso slice streaks
rows = np.arange(1536)[:, None] * np.ones((1, 1536))
tor = rows > 1050
Fs = np.where(tor, nblur(F, mask, 2.0, 9.0), F); Bs = np.where(tor, nblur(B, mask, 2.0, 9.0), B)
# 2) general smoothing; keep the rim (distance < 12 px) less blurred to protect the silhouette roundness
F1 = nblur(Fs, mask, 7.0); B1 = nblur(Bs, mask, 10.0)
wrim = np.clip(edge / 25.0, 0, 1)
F2 = wrim * F1 + (1 - wrim) * Fs; B2 = wrim * B1 + (1 - wrim) * Bs
# keep a consistent rounded rim: thickness -> 0 at the edge
mid = 0.5 * (F2 + B2); half = 0.5 * np.clip(B2 - F2, 0, None)
half *= np.sqrt(np.clip(edge / 18.0, 0, 1))
F3, B3 = mid - half, mid + half
F3[~mask] = np.nan; B3[~mask] = np.nan
np.save("out/F_prior_s.npy", F3.astype(np.float32)); np.save("out/B_prior_s.npy", B3.astype(np.float32))
from viz import shade
l = np.load("out/light.npy")
s = shade(F3, l[:3], amb=0.45)
L = np.load("out/lum.npy")
cv2.imwrite("out/prior_s_vs_photo.png", np.clip(np.hstack([cv2.resize(L, (768, 768)), cv2.resize(s * 0.8, (768, 768))]) * 255, 0, 255).astype(np.uint8))
print("ok")
