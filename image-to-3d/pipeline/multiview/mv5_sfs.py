"""Per-view linear regularised shape-from-shading on top of the smoothed base depth maps.
h = height toward that view's camera, in px (1 px = S mm). Output: refined depth maps in mm (model axes)."""
import sys, time, json, numpy as np, cv2
from scipy import ndimage as ndi, sparse
from scipy.sparse.linalg import lsqr
from mv_vol import *
from mv_viz import to_common
VIEWS = sys.argv[1].split(",") if len(sys.argv) > 1 else ["front", "right", "back", "left"]
EPS = float(sys.argv[2]) if len(sys.argv) > 2 else 0.10
FINE = float(sys.argv[3]) if len(sys.argv) > 3 else 1.5
SIGN = {"front": -1.0, "back": 1.0, "right": -1.0, "left": 1.0}      # h = SIGN * coord / S
dm = dict(np.load("out/b1s_depth.npz"))
def nblur(X, m, s):
    num = ndi.gaussian_filter(np.where(m, X, 0.0), s); den = ndi.gaussian_filter(m.astype(np.float64), s)
    return np.where(m, num / np.maximum(den, 1e-6), 0.0)
def fill_nearest(X, valid):
    idx = ndi.distance_transform_edt(~valid, return_distances=False, return_indices=True)
    return X[tuple(idx)]
out = {}
for v in VIEWS:
    t0 = time.time()
    img = np.load("out/c_%s_img.npy" % v).astype(np.float64)
    L = 0.299 * img[..., 2] + 0.587 * img[..., 1] + 0.114 * img[..., 0]
    m = np.load("out/c_%s_alpha.npy" % v) > 0.5
    m = ndi.binary_opening(m, iterations=1)
    D = to_common(v, dm[v].astype(np.float64))                    # model coordinate along the view axis (mm)
    hv = SIGN[v] * D / S
    valid = ~np.isnan(hv)
    hp = fill_nearest(np.where(valid, hv, 0.0), valid)
    gap = m & ~valid
    if gap.any():                                                 # pixels in the silhouette the base misses: diffuse in
        hp = np.where(valid, hp, ndi.gaussian_filter(hp, 3.0))
    hp = np.where(m, hp, hp)
    hs = nblur(hp, m, 1.0) * m + hp * ~m
    ha = np.gradient(hs, axis=1); hb = np.gradient(hs, axis=0)
    inv = 1 / np.sqrt(ha ** 2 + hb ** 2 + 1); N3 = np.stack([-ha * inv, hb * inv, inv], -1)
    # ---- light: L ~ c0 + l.n on the interior (low-pass normals), IRLS
    mi = ndi.binary_erosion(m, iterations=4)
    hl = nblur(hp, m, 4.0); la = np.gradient(hl, axis=1); lb = np.gradient(hl, axis=0)
    li = 1 / np.sqrt(la ** 2 + lb ** 2 + 1); NL = np.stack([-la * li, lb * li, li], -1)
    sel = mi & (L > 0.08) & (L < 0.97)
    Am = np.c_[np.ones(sel.sum()), NL[sel]]; y = ndi.gaussian_filter(L, 2.0)[sel]; wts = np.ones(len(y))
    for _ in range(4):
        coef, *_ = np.linalg.lstsq(Am * wts[:, None], y * wts, rcond=None)
        res = y - Am @ coef; s_ = 1.4826 * np.median(np.abs(res)) + 1e-6; wts = 1 / np.sqrt(1 + (res / (2 * s_)) ** 2)
    c0, cx, cy, cz = coef
    print("%-5s light c0 %.3f l (%.3f %.3f %.3f) |l| %.3f  fit rms %.3f" % (v, c0, cx, cy, cz, np.linalg.norm(coef[1:]), np.sqrt(np.mean(res ** 2))))
    def shade(ha, hb):
        inv = 1 / np.sqrt(ha ** 2 + hb ** 2 + 1); return c0 + cx * (-ha * inv) + cy * (hb * inv) + cz * inv
    S0 = shade(ha, hb)
    sg = 22.0
    mi2 = ndi.binary_erosion(m, iterations=2)
    gain = nblur(L, mi2, sg) / np.maximum(nblur(S0, mi2, sg), 1e-3)
    thr = 0.10
    r = np.where(mi2 & (L > thr), L / np.clip(gain, 0.6, 1.6) - S0, 0.0)
    w = (mi2 & (L > thr)).astype(np.float64) * np.clip((L - thr) / 0.15, 0, 1) * np.clip((inv - 0.15) / 0.35, 0, 1)
    e = 1e-3
    Ja = (shade(ha + e, hb) - shade(ha - e, hb)) / (2 * e); Jb = (shade(ha, hb + e) - shade(ha, hb - e)) / (2 * e)
    J2 = np.median((Ja ** 2 + Jb ** 2)[mi2])
    H, W = m.shape
    idx = -np.ones((H, W), np.int64); ys, xs = np.nonzero(m); idx[ys, xs] = np.arange(len(ys)); n = len(ys); k = np.arange(n)
    xp = np.clip(xs + 1, 0, W - 1); xm = np.clip(xs - 1, 0, W - 1); yp = np.clip(ys + 1, 0, H - 1); ym = np.clip(ys - 1, 0, H - 1)
    ip, im_ = idx[ys, xp], idx[ys, xm]; jp, jm = idx[yp, xs], idx[ym, xs]
    oa = (ip >= 0) & (im_ >= 0); ob = (jp >= 0) & (jm >= 0)
    Da = sparse.csr_matrix((np.r_[np.full(oa.sum(), 0.5), np.full(oa.sum(), -0.5)], (np.r_[k[oa], k[oa]], np.r_[ip[oa], im_[oa]])), shape=(n, n))
    Db = sparse.csr_matrix((np.r_[np.full(ob.sum(), 0.5), np.full(ob.sum(), -0.5)], (np.r_[k[ob], k[ob]], np.r_[jp[ob], jm[ob]])), shape=(n, n))
    fa = ip >= 0; fb = jp >= 0
    Fa = sparse.csr_matrix((np.r_[np.ones(fa.sum()), -np.ones(fa.sum())], (np.r_[k[fa], k[fa]], np.r_[ip[fa], k[fa]])), shape=(n, n))
    Fb = sparse.csr_matrix((np.r_[np.ones(fb.sum()), -np.ones(fb.sum())], (np.r_[k[fb], k[fb]], np.r_[jp[fb], k[fb]])), shape=(n, n))
    wv = w[ys, xs]
    A_data = sparse.diags(wv * Ja[ys, xs]) @ Da + sparse.diags(wv * Jb[ys, xs]) @ Db
    lam = np.sqrt(EPS * J2)
    edge = ndi.distance_transform_edt(m)[ys, xs]
    pin = np.sqrt(1e-6 + 2e-3 * np.clip(1 - edge / 13.0, 0, 1)) * np.sqrt(J2)
    A = sparse.vstack([A_data, lam * Fa, lam * Fb, sparse.diags(pin)]).tocsr()
    bvec = np.r_[wv * r[ys, xs], np.zeros(3 * n)]
    sol = lsqr(A, bvec, atol=1e-9, btol=1e-9, iter_lim=3000)
    dh = np.zeros((H, W)); dh[ys, xs] = sol[0]
    lp40 = nblur(dh, m, 40.0); lp60 = nblur(dh, m, 60.0)
    tor = np.clip((np.arange(H)[:, None] - 330.0) / 30.0, 0, 1)        # drapery: keep broader folds
    dh = dh - ((1 - tor) * lp40 + tor * lp60)                          # keep the mid band
    tap = np.clip(ndi.distance_transform_edt(m) / 10.0, 0, 1); tap = tap * tap * (3 - 2 * tap); dh *= tap
    # ---- fine relief from log-luminance (hair curls, beard strands, marble grain)
    lg = np.log(np.maximum(ndi.gaussian_filter(L, 0.6), 0.03))
    fine = (lg - nblur(lg, m, 1.0)) * 0.5 + (nblur(lg, m, 1.0) - nblur(lg, m, 3.2)) * 1.0
    fine = np.clip(fine, -0.35, 0.35) * np.clip(ndi.distance_transform_edt(m) / 8.0, 0, 1)
    h = np.where(m, hp + dh + FINE * 3.2 * fine, np.nan)
    print("%-5s lsqr istop %d it %d  %.0fs  |dh| p50 %.2f p99 %.2f px  fine p99 %.2f px" % (v, sol[1], sol[2], time.time() - t0,
          np.percentile(np.abs(sol[0]), 50), np.percentile(np.abs(sol[0]), 99), np.percentile(np.abs(FINE * 3.2 * fine[m]), 99)))
    out[v] = SIGN[v] * h * S                                      # back to the model coordinate (mm)
    out[v + "_mask"] = m
    out[v + "_prior"] = np.where(m, SIGN[v] * hp * S, np.nan)
    # check image: input | prior shading | refined shading (same light)
    def sh(hh):
        a = np.gradient(np.nan_to_num(hh), axis=1); b = np.gradient(np.nan_to_num(hh), axis=0); return np.where(m, shade(a, b), 0)
    tile = np.hstack([np.where(m, L, 0), sh(hs), sh(h)])[:, :]
    cv2.imwrite("out/sfs_%s.png" % v, np.clip(tile * 255, 0, 255).astype(np.uint8))
np.savez("out/sfs_%s.npz" % ("_".join(VIEWS) if len(VIEWS) < 4 else "all"), **out)
