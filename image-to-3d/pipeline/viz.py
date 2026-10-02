import numpy as np, cv2
def normals(D, step=1.0):
    """D: depth (smaller = closer), returns camera-space normals (x right, y up, z to viewer)."""
    Dn = np.where(np.isnan(D), np.nanmax(D) if np.isfinite(np.nanmax(D)) else 0, D)
    da = np.gradient(Dn, axis=1) / step; db = np.gradient(Dn, axis=0) / step
    n = np.stack([da, -db, np.ones_like(Dn)], -1); n /= np.linalg.norm(n, axis=-1, keepdims=True)
    return n
def shade(D, l=(-0.45, 0.55, 0.70), amb=0.25, step=1.0):
    n = normals(D, step); l = np.array(l, float); l /= np.linalg.norm(l)
    s = amb + (1 - amb) * np.clip(n @ l, 0, 1)
    s[np.isnan(D)] = 0; return s
