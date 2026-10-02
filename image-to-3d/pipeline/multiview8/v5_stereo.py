"""Dense points: stereo between neighbouring views. Both canonical images share rows (Z), so each pair is
rectified by stretching u by 1/cos(delta) around the bisector azimuth: disparity = 2 w' tan(delta)."""
import time, json, numpy as np, cv2
from scipy import ndimage as ndi
from v_common import *
order = sorted(NAMES, key=lambda v: AZ[v] % 360.0)
pairs = [(order[i], order[(i + 1) % 8]) for i in range(8)]
allpts = []; dmaps = {}
for a, b in pairs:
    ta = AZ[a] % 360.0; tb = AZ[b] % 360.0
    if tb <= ta: tb += 360.0
    phi = 0.5 * (ta + tb); dl = np.radians(0.5 * (tb - ta)); tdl = np.tan(dl)
    ia, La, ala = load_view(a); ib, Lb, alb = load_view(b)
    # stretched images: column j -> x = j - CX ; u = x cos(dl)
    CX = int(round(CU0 / np.cos(dl))) + 40; Wd = int(WC / np.cos(dl)) + 80
    xs = (np.arange(Wd) - CX) * np.cos(dl) + CU0
    mx = np.tile(xs.astype(np.float32), (HC, 1)); my = np.tile(np.arange(HC, dtype=np.float32)[:, None], (1, Wd))
    def prep(L, al):
        g = np.clip(ndi.gaussian_filter(L, 0.8) * 255, 0, 255).astype(np.uint8)
        g = cv2.createCLAHE(clipLimit=2.0, tileGridSize=(8, 8)).apply(g)
        return cv2.remap(g, mx, my, cv2.INTER_LINEAR), cv2.remap(al.astype(np.float32), mx, my, cv2.INTER_LINEAR)
    A, ma = prep(La, ala); B, mb = prep(Lb, alb)
    wmin, wmax = -260.0, 300.0
    D0 = int(np.ceil(-2 * wmin * tdl)); nd = int(np.ceil((2 * (wmax - wmin) * tdl) / 16.0) * 16)
    Bs = np.zeros_like(B); Bs[:, :Wd - D0] = B[:, D0:]                 # B'(x) = B(x + D0)
    mbs = np.zeros_like(mb); mbs[:, :Wd - D0] = mb[:, D0:]
    bs = 5
    sg = cv2.StereoSGBM_create(minDisparity=0, numDisparities=nd, blockSize=bs, P1=8 * bs * bs, P2=32 * bs * bs,
                               disp12MaxDiff=2, uniquenessRatio=8, speckleWindowSize=80, speckleRange=2, mode=cv2.STEREO_SGBM_MODE_HH)
    PADL = nd + 16
    padz = lambda I: np.hstack([np.zeros((HC, PADL), I.dtype), I, np.zeros((HC, PADL), I.dtype)])
    dL = (sg.compute(padz(A), padz(Bs)).astype(np.float32) / 16.0)[:, PADL:PADL + Wd]
    # right-left check: disparity of B' against A, mirrored trick
    sgr = cv2.StereoSGBM_create(minDisparity=-nd, numDisparities=nd, blockSize=bs, P1=8 * bs * bs, P2=32 * bs * bs,
                                disp12MaxDiff=2, uniquenessRatio=8, speckleWindowSize=80, speckleRange=2, mode=cv2.STEREO_SGBM_MODE_HH)
    dR = (sgr.compute(padz(Bs), padz(A)).astype(np.float32) / 16.0)[:, PADL:PADL + Wd]   # right pixels: x_left = x_right - dR
    jj = np.arange(Wd)[None, :].repeat(HC, 0)
    xr = np.clip(np.round(jj - dL).astype(int), 0, Wd - 1)
    back = -dR[np.arange(HC)[:, None], xr]
    ok = (dL > 0) & (np.abs(back - dL) <= 1.5) & (ma > 0.5) & (mbs[np.arange(HC)[:, None], xr] > 0.5)
    ok &= ndi.binary_erosion(ma > 0.5, iterations=3)
    d = dL - D0
    w = d / (2 * tdl); up = (jj - CX) - w * tdl                          # bisector-frame coordinates (px)
    t = np.radians(phi); X = up * np.cos(t) + w * np.sin(t); Y = -up * np.sin(t) + w * np.cos(t)
    Z = CR0 - np.arange(HC)[:, None].repeat(Wd, 1)
    P = np.stack([X, Y, Z], -1)[ok]
    col = cv2.remap(ia.astype(np.float32), mx, my, cv2.INTER_LINEAR)[ok]
    allpts.append(np.c_[P, col[:, ::-1], np.full(len(P), phi)])
    # depth map of this virtual view (bisector azimuth) on the canonical u grid
    dm = np.full((HC, WC), np.nan)
    ucan = (np.arange(WC) - CU0)
    for r in range(HC):
        sel = ok[r]
        if sel.sum() < 3: continue
        o = np.argsort(up[r][sel]); uu = up[r][sel][o]; ww = w[r][sel][o]
        dm[r] = np.interp(ucan, uu, ww, left=np.nan, right=np.nan)
        gap = np.abs(ucan[:, None] - uu[None, :]).min(1) > 3.0
        dm[r][gap] = np.nan
    dmaps["%.1f" % (phi % 360.0)] = dm
    print("%s-%s  bisector %.1f  half-angle %.1f  numDisp %d  valid %d px (%.0f%% of overlap)" % (a, b, phi % 360, np.degrees(dl), nd, ok.sum(), 100 * ok.sum() / max(((ma > 0.5)).sum(), 1)))
pts = np.vstack(allpts)
np.save("out/stereo_pts.npy", pts.astype(np.float32)); np.savez("out/stereo_depth.npz", **dmaps)
print("total stereo points: %d" % len(pts))
