"""Radius grid in the Rhino-script parametrisation (spine rings + head rays from H, transition rays),
cast on the smoothed base volume, then per-view shading detail added as a weighted normal displacement,
then soft-clipped to the front/side silhouettes.  Output: out/mv_mesh.npz, out/mv_mesh_R.npy, out/mv_mesh_params.json"""
import sys, json, time, numpy as np
from scipy import ndimage as ndi
from mv_vol import *
NU = int(sys.argv[1]) if len(sys.argv) > 1 else 1024
NZ = int(sys.argv[2]) if len(sys.argv) > 2 else 260
NH = int(sys.argv[3]) if len(sys.argv) > 3 else 520
POW = 3.0
MODE = sys.argv[4] if len(sys.argv) > 4 else "tsdf"          # tsdf: cast the fused volume (used) | disp: base + view displacement (kept for tests)
vol = np.load("out/b1s_vol.npy") if MODE == "disp" else np.load("out/fused_vol.npy")
sf = dict(np.load("out/sfs_push.npz"))
# ---------------- frame: base centre at the origin
from mv_common import row_extents
def ext_mm(v):
    L, R = row_extents(np.load("out/c_%s_alpha.npy" % v)); return (L - 390.0) * S, (R - 390.0) * S
fL, fR = ext_mm("front"); bL, bR = ext_mm("back"); rL, rR = ext_mm("right"); lL, lR = ext_mm("left")
rb = 472
BX = 0.25 * (fL[rb] + fR[rb] + bL[rb] + bR[rb]); BY = 0.25 * (rL[rb] + rR[rb] + lL[rb] + lR[rb])
print("base centre in view frame: X %.1f Y %.1f" % (BX, BY))
json.dump(dict(BX=float(BX), BY=float(BY), S=S), open("out/frame.json", "w"))
def Zr(r): return (474.0 - r) * S
def phi_at(P):
    """P: (...,3) in MODEL frame (shifted). trilinear sample of the base volume."""
    X = P[..., 0] + BX; Y = P[..., 1] + BY; Z = P[..., 2]
    ci = np.stack([474.0 - Z / S, (Y / S + 390.0) - YC[0], (X / S + 390.0) - XC[0]])
    return ndi.map_coordinates(vol, ci.reshape(3, -1), order=1, mode="constant", cval=5.0).reshape(P.shape[:-1])
def cast_last(O, D, tmax, step=1.2, iters=12, chunk=60000):
    """outermost inside->outside crossing along each ray (fills concavities along the ray)."""
    n = len(O); out = np.zeros(n); ok = np.zeros(n, bool)
    ts = np.arange(0.0, tmax + step, step)
    for c0 in range(0, n, chunk):
        o = O[c0:c0 + chunk]; dv = D[c0:c0 + chunk]
        ph = phi_at(o[:, None, :] + dv[:, None, :] * ts[None, :, None])
        ins = ph < 0
        cross = ins[:, :-1] & ~ins[:, 1:]
        has = cross.any(1)
        last = np.where(has, cross.shape[1] - 1 - np.argmax(cross[:, ::-1], 1), 0)
        lo = ts[last]; hi = ts[last + 1]
        for _ in range(iters):
            mid = 0.5 * (lo + hi); inn = phi_at(o + dv * mid[:, None]) < 0
            lo = np.where(inn, mid, lo); hi = np.where(inn, hi, mid)
        out[c0:c0 + chunk] = 0.5 * (lo + hi); ok[c0:c0 + chunk] = has
    return out, ok
def cast_first_exit(O, D, tmax, step=0.8, gap=4.0, iters=12, chunk=60000):
    """first inside->outside crossing followed by >= gap mm of outside (bridges small cracks)."""
    n = len(O); out = np.zeros(n); ok = np.zeros(n, bool)
    ts = np.arange(0.0, tmax + step, step); kg = max(1, int(round(gap / step)))
    for c0 in range(0, n, chunk):
        o = O[c0:c0 + chunk]; dv = D[c0:c0 + chunk]
        ins = phi_at(o[:, None, :] + dv[:, None, :] * ts[None, :, None]) < 0
        outm = ~ins; run = outm.copy()
        for j in range(1, kg): run[:, :-j] &= outm[:, j:]; run[:, -j:] = False
        started = np.maximum.accumulate(ins, axis=1); cand = run & started
        has = cand.any(1); first = np.where(has, np.argmax(cand, 1), len(ts) - 1)
        lo = ts[np.maximum(first - 1, 0)]; hi = ts[first]
        for _ in range(iters):
            mid = 0.5 * (lo + hi); inn = phi_at(o + dv * mid[:, None]) < 0
            lo = np.where(inn, mid, lo); hi = np.where(inn, hi, mid)
        out[c0:c0 + chunk] = 0.5 * (lo + hi); ok[c0:c0 + chunk] = has
    return out, ok
def normal_at(P, h=0.7):
    g = np.stack([phi_at(P + np.array([h, 0, 0])) - phi_at(P - np.array([h, 0, 0])),
                  phi_at(P + np.array([0, h, 0])) - phi_at(P - np.array([0, h, 0])),
                  phi_at(P + np.array([0, 0, h])) - phi_at(P - np.array([0, 0, h]))], -1)
    return g / np.maximum(np.linalg.norm(g, axis=-1, keepdims=True), 1e-9)
# ---------------- parametrisation (same maths as the Rhino script's bust_grid)
r_ring = 330; Z_ring = Zr(r_ring)
hr = 180; H = np.array([0.5 * (fL[hr] + fR[hr]) * 0.6 + 0.5 * (bL[hr] + bR[hr]) * 0.4 - BX, 5.0 - BY, Zr(hr)])
# neck centre at the ring: middle of the section along the ring height
sl = vol[r_ring] < 0; ys, xs = np.nonzero(sl)
Cn = np.array([Xv[xs].mean() - BX, Yv[ys].mean() - BY])
print("H", np.round(H, 1), "Cn", np.round(Cn, 1), "Z_ring %.1f" % Z_ring)
def spine(Z):
    t = np.clip(Z / Z_ring, 0, 1); t = t * t * (3 - 2 * t); return np.stack([t * Cn[0], t * Cn[1], Z], -1)
u = np.linspace(0, 2 * np.pi, NU, endpoint=False); du = np.stack([np.cos(u), np.sin(u), np.zeros_like(u)], 1)
Zs = np.linspace(1.0 * S, Z_ring, 300)
prof = np.zeros(300)
for dvec in ([1.0, 0, 0], [-1.0, 0, 0], [0, -1.0, 0], [0, 1.0, 0]):
    rr, _ = cast_last(spine(Zs), np.tile(dvec, (300, 1)), 260.0); prof += rr / 4
arc = np.r_[0, np.cumsum(np.hypot(np.diff(prof), np.diff(Zs)))]
Zrows = np.interp(np.linspace(0, arc[-1], NZ + 1), arc, Zs)
t0 = time.time()
Ot = np.repeat(spine(Zrows), NU, 0); Dt_ = np.tile(du, (NZ + 1, 1))
Rt, okt = cast_last(Ot, Dt_, 260.0)
print("torso rays %d cast %.0fs (miss %d)" % (len(Ot), time.time() - t0, (~okt).sum()))
Pt = spine(Zrows)[:, None, :] + Rt.reshape(NZ + 1, NU)[..., None] * du[None]
ring = Pt[-1]; Dring = ring - H; Dring /= np.linalg.norm(Dring, axis=1, keepdims=True)
up = np.array([0, 0, 1.0]); ang = np.arccos(np.clip(Dring @ up, -1, 1))
axis = np.cross(Dring, up); axis /= np.linalg.norm(axis, axis=1, keepdims=True)
def rot(vec, ax, th):
    c, s = np.cos(th)[..., None], np.sin(th)[..., None]
    return vec * c + np.cross(ax, vec) * s + ax * (np.sum(ax * vec, -1, keepdims=True)) * (1 - c)
vv = np.arange(1, NH) / float(NH)
Dh = rot(Dring[None], axis[None], vv[:, None] * ang[None])
KB = max(8, NH // 12)
kk = np.arange(1, NH); wk = np.clip(kk / float(KB), 0, 1); wk = wk * wk * (3 - 2 * wk)
C_ring = np.array([Cn[0], Cn[1], Z_ring]); O_rows = C_ring + wk[:, None] * (H - C_ring)
Dt = (1 - wk)[:, None, None] * du[None] + wk[:, None, None] * Dh; Dt /= np.linalg.norm(Dt, axis=-1, keepdims=True)
Oh = np.repeat(O_rows, NU, 0); Dhf = Dt.reshape(-1, 3)
t0 = time.time(); Rh, okh = cast_first_exit(Oh, Dhf, 260.0)
print("head rays %d cast %.0fs (miss %d)" % (len(Oh), time.time() - t0, (~okh).sum()))
r_pole, _ = cast_last(H[None], up[None], 200.0, 0.5)
O_all = np.vstack([Ot, Oh]); D_all = np.vstack([Dt_, Dhf]); R0 = np.r_[Rt, Rh]
P0 = O_all + D_all * R0[:, None]
N0 = normal_at(P0)
np.savez("out/grid_base.npz", O=O_all, D=D_all, R0=R0, N0=N0)
if MODE == "tsdf":
    NR_all = NZ + 1 + NH - 1
    PARAMS = dict(NU=NU, NZ=NZ, NH=NH, KB=KB, H=H.tolist(), Cn=Cn.tolist(), Z_ring=float(Z_ring), Zrows=Zrows.tolist(), r_pole=float(r_pole[0]))
    json.dump(PARAMS, open("out/mv_mesh_params.json", "w"))
    np.save("out/mv_mesh_R.npy", R0.reshape(NR_all, NU).astype(np.float32)); print("tsdf grid saved"); sys.exit(0)
# ---------------- per-view shading detail -> radius displacement
AX = {"front": (1, +1.0), "back": (1, +1.0), "right": (0, +1.0), "left": (0, +1.0)}  # depth coordinate index
num = np.zeros(len(R0)); den = np.full(len(R0), 0.05)
Xw = P0[:, 0] + BX; Yw = P0[:, 1] + BY; Zw = P0[:, 2]
row = 474.0 - Zw / S
for v in ["front", "right", "back", "left"]:
    k = AX[v][0]
    if v in ("front", "back"): col = Xw / S + 390.0; coord = Yw; e = np.array([0, 1.0, 0])
    else: col = Yw / S + 390.0; coord = Xw; e = np.array([1.0, 0, 0])
    m = sf[v + "_mask"]; Dref = np.nan_to_num(sf[v], nan=0.0); Dpri = np.nan_to_num(sf[v + "_prior"], nan=0.0)
    samp = lambda img: ndi.map_coordinates(img, [row, col], order=1, mode="constant", cval=0.0)
    inm = samp(m.astype(np.float64)) > 0.99
    dpri = samp(Dpri); dref = samp(Dref)
    vis = inm & (np.abs(coord - dpri) < 1.6)
    edge = samp(np.clip(ndi.distance_transform_edt(m) / 8.0, 0, 1))
    en = N0 @ e
    facing = np.abs(en)
    # the view must look at the outside of the surface: front (camera -Y) sees n_y<0, back sees n_y>0, right (camera -X) n_x<0, left n_x>0
    side_ok = {"front": en < 0, "back": en > 0, "right": en < 0, "left": en > 0}[v]
    w = vis * side_ok * edge * facing ** POW
    # smooth the weight field on the grid (visibility / side switches must not leave seams)
    wg = w.reshape(NZ + 1 + NH - 1, NU)
    wg = ndi.gaussian_filter(wg, (3.0, 3.0), mode=("nearest", "wrap"))
    w = wg.ravel() * (w > 0)
    w = np.where(w > 0, w, 0.0)
    dn = np.sum(D_all * N0, 1); dn = np.where(np.abs(dn) < 0.3, 0.3 * np.sign(dn + 1e-9), dn)
    dr = (dref - dpri) * en / dn
    dr = np.clip(dr, -15, 15)
    num += w * dr; den += w
    print("%-5s visible %.1f%%  mean w %.3f  |dr| p99 %.2f" % (v, 100 * (w > 0.05).mean(), w.mean(), np.percentile(np.abs(dr[w > 0.05]), 99)))
dR = num / den
R1 = R0 + dR
# ---------------- soft clip to the silhouette hull (front silhouette x mean side silhouette)
al_f = np.load("out/c_front_alpha.npy"); al_s = 0.5 * (np.load("out/c_right_alpha.npy") + np.load("out/c_left_alpha.npy"))
def in_hull(P):
    X = P[..., 0] + BX; Y = P[..., 1] + BY; Z = P[..., 2]; rw = 474.0 - Z / S
    a = ndi.map_coordinates(al_f, [rw.ravel(), (X / S + 390.0).ravel()], order=1, cval=0.0).reshape(rw.shape)
    b = ndi.map_coordinates(al_s, [rw.ravel(), (Y / S + 390.0).ravel()], order=1, cval=0.0).reshape(rw.shape)
    return (a > 0.5) & (b > 0.5) & (Z >= 0)
def cast_first_out(test, O, D, t_start, tmax, step=0.4, chunk=60000):
    """first t >= t_start where the ray leaves the hull (scan from t_start)"""
    n = len(O); out = np.full(n, np.inf)
    ts = np.arange(0, tmax, step)
    for c0 in range(0, n, chunk):
        o = O[c0:c0 + chunk]; dv = D[c0:c0 + chunk]; t0_ = t_start[c0:c0 + chunk]
        T = t0_[:, None] + ts[None, :]
        ins = test(o[:, None, :] + dv[:, None, :] * T[..., None])
        outm = ~ins; has = outm.any(1); first = np.argmax(outm, 1)
        out[c0:c0 + chunk] = np.where(has, T[np.arange(len(o)), first], np.inf)
    return out
t_hull = cast_first_out(in_hull, O_all, D_all, np.maximum(R1 - 12.0, 0.0), 30.0)
def softmin(x, y, k=1.2):
    h = np.clip(0.5 + 0.5 * (y - x) / k, 0, 1); return y * (1 - h) + x * h - k * h * (1 - h)
clipped = R1 > t_hull + 0.3
R2 = np.where(np.isfinite(t_hull), softmin(R1, t_hull), R1)
print("hull-clipped rays %.1f%%" % (100 * clipped.mean()))
NR_all = NZ + 1 + NH - 1
R_all = R2.reshape(NR_all, NU)
PARAMS = dict(NU=NU, NZ=NZ, NH=NH, KB=KB, H=H.tolist(), Cn=Cn.tolist(), Z_ring=float(Z_ring), Zrows=Zrows.tolist(), r_pole=float(r_pole[0]))
json.dump(PARAMS, open("out/mv_mesh_params.json", "w"))
np.save("out/mv_mesh_R.npy", R_all.astype(np.float32)); np.save("out/mv_mesh_R0.npy", R0.reshape(NR_all, NU).astype(np.float32))
print("saved radius grid", R_all.shape)
