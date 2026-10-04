"""Stage 2 (v5): linearised, regularised shape-from-shading (one sparse least-squares solve, no sawtooth),
plus isotropic fine relief from luminance.  h = -depth, full-res px units."""
import sys, time, numpy as np, cv2
from scipy import ndimage as ndi, sparse
from scipy.sparse.linalg import lsqr
N = int(sys.argv[1]) if len(sys.argv) > 1 else 768
EPS = float(sys.argv[2]) if len(sys.argv) > 2 else 0.06       # isotropic gradient regulariser (relative to |J|^2)
FINE = float(sys.argv[3]) if len(sys.argv) > 3 else 1.2       # fine relief amplitude (px per unit log-contrast)
TAG = sys.argv[4] if len(sys.argv) > 4 else ""
L_full = np.load("out/lum.npy").astype(np.float64); mask_full = np.load("out/mask.npy")
hp_full = np.where(mask_full, -np.load("out/F_prior_s.npy"), 0).astype(np.float64)
c0, cx, cy, cz = np.load("out/light_rim.npy").astype(np.float64)
def down(x, n): return cv2.resize(x, (n, n), interpolation=cv2.INTER_AREA)
def nblur(X, m, s):
    num = ndi.gaussian_filter(np.where(m, X, 0.0), s); den = ndi.gaussian_filter(m.astype(np.float64), s)
    return np.where(m, num / np.maximum(den, 1e-6), 0.0)
def shade(ha, hb):
    inv = 1 / np.sqrt(ha ** 2 + hb ** 2 + 1); return c0 + cx * (-ha * inv) + cy * (hb * inv) + cz * inv
f = 1536.0 / N
L = down(L_full, N); m = down(mask_full.astype(np.float64), N) > 0.99; hp = down(hp_full, N)
ha = np.gradient(hp, axis=1) / f; hb = np.gradient(hp, axis=0) / f
S0 = shade(ha, hb)
# gain-normalise the photo at large scale so only the mid band remains in the residual
sg = 70.0 / f
mi = ndi.binary_erosion(m, iterations=2)
gain = nblur(L, mi, sg) / np.maximum(nblur(S0, mi, sg), 1e-3)
r = np.where(mi & (L > 0.22), L / np.clip(gain, 0.6, 1.6) - S0, 0.0)
nz0 = 1 / np.sqrt(ha ** 2 + hb ** 2 + 1)
w = (mi & (L > 0.22)).astype(np.float64) * np.clip((L - 0.22) / 0.20, 0, 1) * np.clip((nz0 - 0.15) / 0.35, 0, 1)
# Jacobian of shading w.r.t. the gradient (per full-res px), numeric
e = 1e-3
Ja = (shade(ha + e, hb) - shade(ha - e, hb)) / (2 * e); Jb = (shade(ha, hb + e) - shade(ha, hb - e)) / (2 * e)
J2 = np.median((Ja ** 2 + Jb ** 2)[m])
print("N %d  median |J|^2 %.4f  residual rms %.4f" % (N, J2, np.sqrt(np.mean(r[w > 0] ** 2))))
# sparse system over mask pixels: unknown dh (px). gradient by central differences in grid units -> divide by f
idx = -np.ones((N, N), np.int64); ys, xs = np.nonzero(m); idx[ys, xs] = np.arange(len(ys)); n = len(ys)
def grad_ops():
    rows_a, cols_a, vals_a, rows_b, cols_b, vals_b = [], [], [], [], [], []
    xp = np.clip(xs + 1, 0, N - 1); xm = np.clip(xs - 1, 0, N - 1); yp = np.clip(ys + 1, 0, N - 1); ym = np.clip(ys - 1, 0, N - 1)
    ip, im = idx[ys, xp], idx[ys, xm]; jp, jm = idx[yp, xs], idx[ym, xs]
    ok_a = (ip >= 0) & (im >= 0); ok_b = (jp >= 0) & (jm >= 0)
    k = np.arange(n)
    Da = sparse.csr_matrix((np.r_[np.full(ok_a.sum(), 0.5 / f), np.full(ok_a.sum(), -0.5 / f)], (np.r_[k[ok_a], k[ok_a]], np.r_[ip[ok_a], im[ok_a]])), shape=(n, n))
    Db = sparse.csr_matrix((np.r_[np.full(ok_b.sum(), 0.5 / f), np.full(ok_b.sum(), -0.5 / f)], (np.r_[k[ok_b], k[ok_b]], np.r_[jp[ok_b], jm[ok_b]])), shape=(n, n))
    return Da, Db
Da, Db = grad_ops()
def fwd_ops():
    xp = np.clip(xs + 1, 0, N - 1); yp = np.clip(ys + 1, 0, N - 1); ip = idx[ys, xp]; jp = idx[yp, xs]; k = np.arange(n)
    oa = ip >= 0; ob = jp >= 0
    Fa = sparse.csr_matrix((np.r_[np.full(oa.sum(), 1.0 / f), np.full(oa.sum(), -1.0 / f)], (np.r_[k[oa], k[oa]], np.r_[ip[oa], k[oa]])), shape=(n, n))
    Fb = sparse.csr_matrix((np.r_[np.full(ob.sum(), 1.0 / f), np.full(ob.sum(), -1.0 / f)], (np.r_[k[ob], k[ob]], np.r_[jp[ob], k[ob]])), shape=(n, n))
    return Fa, Fb
Fa, Fb = fwd_ops()
wv = w[ys, xs]; ja = Ja[ys, xs]; jb = Jb[ys, xs]
A_data = sparse.diags(wv * ja) @ Da + sparse.diags(wv * jb) @ Db
lam = np.sqrt(EPS * J2)
edge = ndi.distance_transform_edt(m)[ys, xs] * f
pin = np.sqrt(1e-6 + 2e-3 * np.clip(1 - edge / 40.0, 0, 1)) * np.sqrt(J2)     # stronger pin near the rim
A = sparse.vstack([A_data, lam * Fa, lam * Fb, sparse.diags(pin)]).tocsr()
bvec = np.r_[wv * r[ys, xs], np.zeros(3 * n)]
t0 = time.time()
sol = lsqr(A, bvec, atol=1e-9, btol=1e-9, iter_lim=2500)
dh = np.zeros((N, N)); dh[ys, xs] = sol[0]
print("lsqr: istop %d  iters %d  %.0fs  |dh| p50 %.2f p99 %.2f" % (sol[1], sol[2], time.time() - t0, np.percentile(np.abs(sol[0]), 50), np.percentile(np.abs(sol[0]), 99)))
# keep only the mid band (remove low-frequency drift), taper at the silhouette
dh = dh - nblur(dh, m, 90.0 / f)
tap = np.clip(ndi.distance_transform_edt(m) * f / 30.0, 0, 1); tap = tap * tap * (3 - 2 * tap); dh *= tap
# ---- full-res composition: prior + mid band (upsampled) + fine luminance relief
dh_full = cv2.resize(dh, (1536, 1536), interpolation=cv2.INTER_CUBIC)
lg = np.log(np.maximum(ndi.gaussian_filter(L_full, 1.1), 0.03))
mf = mask_full
fine = (lg - nblur(lg, mf, 3.0)) * 0.5 + (nblur(lg, mf, 3.0) - nblur(lg, mf, 9.0)) * 1.0
fine = np.clip(fine, -0.35, 0.35)
tapf = np.clip(ndi.distance_transform_edt(mf) / 30.0, 0, 1); tapf = tapf * tapf * (3 - 2 * tapf)
h = np.where(mf, hp_full + dh_full + FINE * 10.0 * fine * tapf, 0)
np.save("out/h_lin%s.npy" % TAG, h.astype(np.float32))
def shade2(hh):
    a = np.gradient(hh, axis=1); b = np.gradient(hh, axis=0); inv = 1 / np.sqrt(a ** 2 + b ** 2 + 1)
    return 0.45 + 0.30 * (-a * inv) + 0.10 * (b * inv) + 0.25 * inv
def shade1(hh):
    a = np.gradient(hh, axis=1); b = np.gradient(hh, axis=0); return shade(a, b)
s1 = np.where(mf, shade1(h), 0); s2 = np.where(mf, shade2(h), 0)
crop = lambda x: cv2.resize(x, (640, 640), interpolation=cv2.INTER_AREA)
cv2.imwrite("out/lin_check%s.png" % TAG, np.clip(np.hstack([crop(L_full), crop(s1), crop(s2)]) * 255, 0, 255).astype(np.uint8))
zc = lambda x: cv2.resize(x[450:1100, 600:1250], (520, 520), interpolation=cv2.INTER_AREA)
cv2.imwrite("out/lin_zoom%s.png" % TAG, np.clip(np.hstack([zc(L_full), zc(s1), zc(s2)]) * 255, 0, 255).astype(np.uint8))
print("saved")
