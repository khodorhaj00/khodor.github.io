"""Cast the Rhino-script grid (spine rings + head rays) on the fused 8-view volume. Output in mm, base centre at the origin."""
import sys, json, time, numpy as np
from scipy import ndimage as ndi
from v_common import *
NU, NZ, NH = 1024, 260, 520
vol = np.load("out/fused8_vol.npy")
rows_in = np.nonzero((vol < 0).reshape(HC, -1).any(1))[0]; r_base = rows_in[-1]
Zb_px = CR0 - r_base
sl = vol[r_base - 2] < 0; ys, xs = np.nonzero(sl)
BXp = 0.5 * (XV[xs].min() + XV[xs].max()); BYp = 0.5 * (YV[ys].min() + YV[ys].max())
print("base row %d  base centre px (%.1f, %.1f)  S8 %.4f mm/px" % (r_base, BXp, BYp, S8))
json.dump(dict(BXp=float(BXp), BYp=float(BYp), Zb_px=float(Zb_px), S=S8, CU0=CU0, CR0=CR0, AZ=AZ), open("out/frame8.json", "w"))
def phi_at(P):
    X = P[..., 0] / S8 + BXp; Y = P[..., 1] / S8 + BYp; Z = P[..., 2] / S8 + Zb_px
    ci = np.stack([CR0 - Z, Y - YV[0], X - XV[0]])
    return S8 * ndi.map_coordinates(vol, ci.reshape(3, -1), order=1, mode="constant", cval=5.0).reshape(P.shape[:-1])
def cast_last(O, D, tmax, step=1.0, iters=12, chunk=60000):
    n = len(O); out = np.zeros(n); ok = np.zeros(n, bool); ts = np.arange(0.0, tmax + step, step)
    for c0 in range(0, n, chunk):
        o = O[c0:c0 + chunk]; dv = D[c0:c0 + chunk]
        ins = phi_at(o[:, None, :] + dv[:, None, :] * ts[None, :, None]) < 0
        cross = ins[:, :-1] & ~ins[:, 1:]; has = cross.any(1)
        last = np.where(has, cross.shape[1] - 1 - np.argmax(cross[:, ::-1], 1), 0)
        lo = ts[last]; hi = ts[last + 1]
        for _ in range(iters):
            mid = 0.5 * (lo + hi); inn = phi_at(o + dv * mid[:, None]) < 0; lo = np.where(inn, mid, lo); hi = np.where(inn, hi, mid)
        out[c0:c0 + chunk] = 0.5 * (lo + hi); ok[c0:c0 + chunk] = has
    return out, ok
def cast_first_exit(O, D, tmax, step=0.8, gap=4.0, iters=12, chunk=60000):
    n = len(O); out = np.zeros(n); ok = np.zeros(n, bool); ts = np.arange(0.0, tmax + step, step); kg = max(1, int(round(gap / step)))
    for c0 in range(0, n, chunk):
        o = O[c0:c0 + chunk]; dv = D[c0:c0 + chunk]
        ins = phi_at(o[:, None, :] + dv[:, None, :] * ts[None, :, None]) < 0
        outm = ~ins; run = outm.copy()
        for j in range(1, kg): run[:, :-j] &= outm[:, j:]; run[:, -j:] = False
        started = np.maximum.accumulate(ins, axis=1); cand = run & started
        has = cand.any(1); first = np.where(has, np.argmax(cand, 1), len(ts) - 1)
        lo = ts[np.maximum(first - 1, 0)]; hi = ts[first]
        for _ in range(iters):
            mid = 0.5 * (lo + hi); inn = phi_at(o + dv * mid[:, None]) < 0; lo = np.where(inn, mid, lo); hi = np.where(inn, hi, mid)
        out[c0:c0 + chunk] = 0.5 * (lo + hi); ok[c0:c0 + chunk] = has
    return out, ok
pf = np.load("out/mp_v000.npy")
r_mouth, r_chin, r_brow = pf[13, 1], pf[152, 1], pf[9, 1]
r_ring = int(round(r_mouth + 0.45 * (r_chin - r_mouth))); hr = int(round(r_brow + 10))
Zmm = lambda r: (CR0 - r - Zb_px) * S8
Z_ring = Zmm(r_ring)
s_h = vol[hr] < 0; yh, xh = np.nonzero(s_h)
H = np.array([(0.5 * (XV[xh].min() + XV[xh].max()) - BXp) * S8, (0.5 * (YV[yh].min() + YV[yh].max()) - BYp) * S8 + 5.0, Zmm(hr)])
s_r = vol[r_ring] < 0; yr, xr = np.nonzero(s_r)
Cn = np.array([(XV[xr].mean() - BXp) * S8, (YV[yr].mean() - BYp) * S8])
print("ring row %d (Z %.1f mm)  head-centre row %d  H %s  Cn %s" % (r_ring, Z_ring, hr, np.round(H, 1), np.round(Cn, 1)))
def spine(Z):
    t = np.clip(Z / Z_ring, 0, 1); t = t * t * (3 - 2 * t); return np.stack([t * Cn[0], t * Cn[1], Z], -1)
u = np.linspace(0, 2 * np.pi, NU, endpoint=False); du = np.stack([np.cos(u), np.sin(u), np.zeros_like(u)], 1)
Zs = np.linspace(1.0 * S8, Z_ring, 300); prof = np.zeros(300)
for dvec in ([1.0, 0, 0], [-1.0, 0, 0], [0, -1.0, 0], [0, 1.0, 0]):
    rr, _ = cast_last(spine(Zs), np.tile(dvec, (300, 1)), 320.0); prof += rr / 4
arc = np.r_[0, np.cumsum(np.hypot(np.diff(prof), np.diff(Zs)))]
Zrows = np.interp(np.linspace(0, arc[-1], NZ + 1), arc, Zs)
t0 = time.time()
Ot = np.repeat(spine(Zrows), NU, 0); Dt_ = np.tile(du, (NZ + 1, 1)); Rt, okt = cast_last(Ot, Dt_, 320.0)
Pt = spine(Zrows)[:, None, :] + Rt.reshape(NZ + 1, NU)[..., None] * du[None]
ring = Pt[-1]; Dring = ring - H; Dring /= np.linalg.norm(Dring, axis=1, keepdims=True)
up = np.array([0, 0, 1.0]); ang = np.arccos(np.clip(Dring @ up, -1, 1))
axis = np.cross(Dring, up); axis /= np.linalg.norm(axis, axis=1, keepdims=True)
def rot(vec, ax, th):
    c, s = np.cos(th)[..., None], np.sin(th)[..., None]
    return vec * c + np.cross(ax, vec) * s + ax * (np.sum(ax * vec, -1, keepdims=True)) * (1 - c)
vv = np.arange(1, NH) / float(NH); Dh = rot(Dring[None], axis[None], vv[:, None] * ang[None])
KB = max(8, NH // 12); kk = np.arange(1, NH); wk = np.clip(kk / float(KB), 0, 1); wk = wk * wk * (3 - 2 * wk)
C_ring = np.array([Cn[0], Cn[1], Z_ring]); O_rows = C_ring + wk[:, None] * (H - C_ring)
Dt = (1 - wk)[:, None, None] * du[None] + wk[:, None, None] * Dh; Dt /= np.linalg.norm(Dt, axis=-1, keepdims=True)
Rh, okh = cast_first_exit(np.repeat(O_rows, NU, 0), Dt.reshape(-1, 3), 320.0)
r_pole, _ = cast_last(H[None], up[None], 250.0, 0.5)
print("rays cast %.0fs  misses torso %d head %d" % (time.time() - t0, (~okt).sum(), (~okh).sum()))
R_all = np.r_[Rt, Rh].reshape(NZ + 1 + NH - 1, NU)
PARAMS = dict(NU=NU, NZ=NZ, NH=NH, KB=KB, H=H.tolist(), Cn=Cn.tolist(), Z_ring=float(Z_ring), Zrows=Zrows.tolist(), r_pole=float(r_pole[0]))
json.dump(PARAMS, open("out/mv_mesh_params.json", "w")); np.save("out/mv_mesh_R.npy", R_all.astype(np.float32))
print("saved grid", R_all.shape)
