"""Per-view linear shape-from-shading for the 8 views on the point-based base (same solver as the 4-view version).
Depth convention per view: w (px) grows away from that camera; h = -w."""
import sys, time, numpy as np, cv2
from scipy import ndimage as ndi, sparse
from scipy.sparse.linalg import lsqr
from v_common import *
EPS = 0.25; FINE = 2.0
dm = dict(np.load("out/b1_depth.npz"))
def nblur(X, m, s):
    num = ndi.gaussian_filter(np.where(m, X, 0.0), s); den = ndi.gaussian_filter(m.astype(np.float64), s)
    return np.where(m, num / np.maximum(den, 1e-6), 0.0)
out = {}
for v in NAMES:
    t0 = time.time()
    img, L, al = load_view(v)
    m = ndi.binary_opening(al > 0.5, iterations=1)
    hv = -dm[v]; valid = ~np.isnan(hv)
    idx = ndi.distance_transform_edt(~valid, return_distances=False, return_indices=True)
    hp = np.where(valid, hv, hv[tuple(idx)])
    hp = np.where(valid, hp, ndi.gaussian_filter(hp, 3.0))
    hs = nblur(hp, m, 1.0) * m + hp * ~m
    ha = np.gradient(hs, axis=1); hb = np.gradient(hs, axis=0)
    inv = 1 / np.sqrt(ha ** 2 + hb ** 2 + 1)
    mi = ndi.binary_erosion(m, iterations=4)
    hl = nblur(hp, m, 4.0); la = np.gradient(hl, axis=1); lb = np.gradient(hl, axis=0)
    li = 1 / np.sqrt(la ** 2 + lb ** 2 + 1); NL = np.stack([-la * li, lb * li, li], -1)
    sel = mi & (L > 0.08) & (L < 0.97)
    Am = np.c_[np.ones(sel.sum()), NL[sel]]; y = ndi.gaussian_filter(L, 2.0)[sel]; wts = np.ones(len(y))
    for _ in range(4):
        coef, *_ = np.linalg.lstsq(Am * wts[:, None], y * wts, rcond=None)
        res = y - Am @ coef; s_ = 1.4826 * np.median(np.abs(res)) + 1e-6; wts = 1 / np.sqrt(1 + (res / (2 * s_)) ** 2)
    c0, cx, cy, cz = coef
    def lshade(ha, hb):
        inv = 1 / np.sqrt(ha ** 2 + hb ** 2 + 1); return c0 + cx * (-ha * inv) + cy * (hb * inv) + cz * inv
    S0 = lshade(ha, hb)
    mi2 = ndi.binary_erosion(m, iterations=2)
    gain = nblur(L, mi2, 22.0) / np.maximum(nblur(S0, mi2, 22.0), 1e-3)
    thr = 0.10
    r = np.where(mi2 & (L > thr), L / np.clip(gain, 0.6, 1.6) - S0, 0.0)
    w = (mi2 & (L > thr)).astype(np.float64) * np.clip((L - thr) / 0.15, 0, 1) * np.clip((inv - 0.15) / 0.35, 0, 1)
    e = 1e-3
    Ja = (lshade(ha + e, hb) - lshade(ha - e, hb)) / (2 * e); Jb = (lshade(ha, hb + e) - lshade(ha, hb - e)) / (2 * e)
    J2 = np.median((Ja ** 2 + Jb ** 2)[mi2])
    H, W = m.shape
    ix = -np.ones((H, W), np.int64); ys, xs = np.nonzero(m); ix[ys, xs] = np.arange(len(ys)); n = len(ys); k = np.arange(n)
    xp = np.clip(xs + 1, 0, W - 1); xm = np.clip(xs - 1, 0, W - 1); yp = np.clip(ys + 1, 0, H - 1); ym = np.clip(ys - 1, 0, H - 1)
    ip, im_ = ix[ys, xp], ix[ys, xm]; jp, jm = ix[yp, xs], ix[ym, xs]
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
    tor = np.clip((np.arange(H)[:, None] - 255.0) / 30.0, 0, 1)
    dh = dh - ((1 - tor) * nblur(dh, m, 40.0) + tor * nblur(dh, m, 60.0))
    tap = np.clip(ndi.distance_transform_edt(m) / 10.0, 0, 1); tap = tap * tap * (3 - 2 * tap); dh *= tap
    dh = 7.0 * np.tanh(dh / 7.0)                                      # flat light: cap the mid-band correction
    lg = np.log(np.maximum(ndi.gaussian_filter(L, 0.6), 0.03))
    fine = (lg - nblur(lg, m, 1.0)) * 0.5 + (nblur(lg, m, 1.0) - nblur(lg, m, 3.2)) * 1.0
    fine = np.clip(fine, -0.35, 0.35) * np.clip(ndi.distance_transform_edt(m) / 8.0, 0, 1)
    h = np.where(m, hp + dh + FINE * 3.2 * fine, np.nan)
    out[v] = -h; out[v + "_mask"] = m; out[v + "_prior"] = np.where(m, -hp, np.nan)
    print("%s light |l| %.3f  lsqr it %d %.0fs  |dh| p99 %.1f px" % (v, np.linalg.norm(coef[1:]), sol[2], time.time() - t0, np.percentile(np.abs(sol[0]), 99)))
np.savez("out/sfs8.npz", **out)
tiles = []
for v in NAMES:
    tiles.append(np.vstack([load_view(v)[1][:, 60:640], shade(-out[v])[:, 60:640]]))
cv2.imwrite("out/sfs8_geo.png", cv2.resize((np.clip(np.hstack(tiles), 0, 1) * 255).astype(np.uint8), None, fx=0.5, fy=0.5, interpolation=cv2.INTER_AREA))
