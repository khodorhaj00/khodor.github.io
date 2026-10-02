"""Stage 3b: final closed bust surface on a structured grid.
front = observed (photo), far head side = mirrored observation, back = smooth 3D template calibrated on the rim,
everything clipped to the visual hull (silhouette)."""
import json, sys, time, numpy as np
from scipy import ndimage as ndi
from template3d import template_sdf, warped_template_sdf, build_warp, a0, d0, S, R as MP_R
build_warp()
NU = int(sys.argv[1]) if len(sys.argv) > 1 else 1024
NZ = int(sys.argv[2]) if len(sys.argv) > 2 else 260
NH = int(sys.argv[3]) if len(sys.argv) > 3 else 520
HF = sys.argv[4] if len(sys.argv) > 4 else "out/h_lin_c.npy"
OUT = sys.argv[5] if len(sys.argv) > 5 else "out/mesh_v2.npz"
mask = np.load("out/mask.npy"); Fd = np.where(mask, -np.load(HF).astype(np.float64), np.nan)
prims = json.load(open("out/prims2.json"))
M = np.load("mp_matrix.npy"); R = M[:3, :3] / np.linalg.norm(M[:3, :3], axis=0)
s_cm, t_a, t_b, t_d = 52.18, 835.3, 769.9, 204.4
def c2p(c):
    cam = np.atleast_2d(c) @ R.T
    return np.c_[s_cm * cam[:, 0] + t_a, -s_cm * cam[:, 1] + t_b, -1.007 * s_cm * cam[:, 2] + t_d]
def px2m(a, b, d): return np.stack([(a - a0) * S, (d - d0) * S, (1536.0 - b) * S], -1)
def m2px(P): return P[..., 0] / S + a0, 1536.0 - P[..., 2] / S, P[..., 1] / S + d0
BIG = 1e6
Fi = np.where(mask, np.nan_to_num(Fd, nan=BIG), BIG)
mf = ndi.gaussian_filter(mask.astype(np.float32), 0.7)
dFa = np.gradient(np.nan_to_num(Fd, nan=0), axis=1); dFb = np.gradient(np.nan_to_num(Fd, nan=0), axis=0)
Fsm = ndi.gaussian_filter(np.nan_to_num(Fd, nan=np.nanmax(Fd)), 2.0)
slope_img = np.hypot(np.gradient(Fsm, axis=1), np.gradient(Fsm, axis=0))
nz_img = 1 / np.sqrt(1 + dFa ** 2 + dFb ** 2) * np.clip((3.2 - slope_img) / 1.4, 0, 1); edge_img = ndi.distance_transform_edt(mask)
def sample(img, a, b, cval=0.0):
    return ndi.map_coordinates(img, [b.ravel(), a.ravel()], order=1, mode="constant", cval=cval).reshape(a.shape)
from scipy.ndimage import gaussian_filter1d
_r = np.load("out/rows.npz"); _al, _ar = _r["al"].copy(), _r["ar"].copy(); _okr = ~np.isnan(_al)
_rows = np.arange(1536.0)
_al_s = np.interp(_rows, _rows[_okr], gaussian_filter1d(_al[_okr], 1.5)); _ar_s = np.interp(_rows, _rows[_okr], gaussian_filter1d(_ar[_okr], 1.5))
_btop, _bbot = _rows[_okr].min(), _rows[_okr].max()
def in_hull(P):
    a, b, d = m2px(P)
    return (b >= _btop) & (b <= _bbot + 0.5) & (a >= np.interp(b, _rows, _al_s)) & (a <= np.interp(b, _rows, _ar_s))
def in_obs(P):
    a, b, d = m2px(P); return (sample(mf, a, b) > 0.5) & (d >= sample(Fi, a, b, cval=BIG))
def in_tmpl(P): return warped_template_sdf(P) < 0
def cast_first(test, O, D, tmax, step=1.0, iters=10, gap=2.0, chunk=200000):
    out = np.empty(O.shape[0]); valid = np.empty(O.shape[0], bool)
    ts = np.arange(0.0, tmax + step, step); k = max(1, int(round(gap / step)))
    for c0 in range(0, O.shape[0], chunk):
        o = O[c0:c0 + chunk]; dv = D[c0:c0 + chunk]; n = len(o)
        ins = np.zeros((n, len(ts)), bool)
        for i0 in range(0, len(ts), 24):
            tt = ts[i0:i0 + 24]; ins[:, i0:i0 + len(tt)] = test(o[:, None, :] + dv[:, None, :] * tt[None, :, None])
        outm = ~ins; run = outm.copy()
        for j in range(1, k): run[:, :-j] &= outm[:, j:]; run[:, -j:] = False
        started = np.maximum.accumulate(ins, axis=1); cand = run & started
        has = cand.any(1); first = np.where(has, np.argmax(cand, 1), len(ts) - 1)
        lo = ts[np.maximum(first - 1, 0)]; hi = ts[first]
        for _ in range(iters):
            mid = 0.5 * (lo + hi); inn = test(o + dv * mid[:, None]); lo = np.where(inn, mid, lo); hi = np.where(inn, hi, mid)
        out[c0:c0 + chunk] = 0.5 * (lo + hi); valid[c0:c0 + chunk] = has
    return out, valid
def confidence(P):
    a, b, d = m2px(P)
    f = sample(np.nan_to_num(Fd, nan=BIG), a, b, cval=BIG); nz = sample(nz_img, a, b); ed = sample(edge_img, a, b)
    vis = np.clip(1 - (np.abs(d - f) - 2.0) / 4.0, 0, 1)
    return vis * np.clip((nz - 0.22) / 0.35, 0, 1) * np.clip((ed - 6.0) / 30.0, 0, 1)
def nconv(X, W, su, sv):
    num = ndi.gaussian_filter(X * W, (sv, su), mode=("nearest", "wrap")); den = ndi.gaussian_filter(W, (sv, su), mode=("nearest", "wrap"))
    return num / np.maximum(den, 1e-6), den
def fuse(O, D, shape, rim_dir_y, mirror=None, label=""):
    """returns final radius grid. O/D flat arrays (rays)."""
    t0 = time.time()
    r_obs, v_obs = cast_first(in_obs, O, D, 240.0, 0.75)
    r_tm, v_tm = cast_first(in_tmpl, O, D, 240.0, 1.0)
    r_hull, v_hull = cast_first(in_hull, O, D, 260.0, 0.75)
    P_obs = O + D * r_obs[:, None]
    conf = confidence(P_obs) * v_obs
    # rim calibration: rays nearly perpendicular to the view that leave through the silhouette
    rim = np.exp(-(rim_dir_y / 0.18) ** 2) * v_obs * v_hull * (np.abs(r_obs - r_hull) < 1.5)
    wcal = np.clip(conf + rim, 0, 1).reshape(shape)
    lr = np.log(np.maximum(r_obs, 1.0) / np.maximum(r_tm, 1.0)).reshape(shape)
    corr, den = nconv(np.clip(lr, -0.35, 0.35), wcal, shape[1] / 28.0, shape[0] / 28.0)
    corr = np.where(den > 1e-4, corr, 0.0)
    r_back = r_tm.reshape(shape) * np.exp(0.0 * corr)       # warped template already matches the silhouette
    conf = ndi.gaussian_filter(conf.reshape(shape), 2.6 * shape[1] / 1024 + 0.8, mode=("nearest", "wrap"))
    if mirror is not None:
        Om, Dm = mirror
        r_m, v_m = cast_first(in_obs, Om, Dm, 240.0, 0.75)
        cm = (confidence(Om + Dm * r_m[:, None]) * v_m * MIRROR_W).reshape(shape)
        # mirrored radii are measured from H: re-express along the actual rays
        Pm_back = Om + Dm * r_m[:, None]
        Pm_back = Pm_back - 2 * ((Pm_back - Om) @ ns)[:, None] * ns            # reflect to our side
        r_m = np.sum((Pm_back - O) * D, axis=1)
        cm = ndi.gaussian_filter(cm, 5.0, mode=("nearest", "wrap"))
        rm2 = r_m.reshape(shape); ro2 = r_obs.reshape(shape)
        ov = ((conf > 0.3) & (cm > 0.3)).astype(float)
        off, den_o = nconv(np.clip(ro2 - rm2, -6, 6), ov, 14.0 * shape[1] / 1024, 14.0 * shape[0] / 780)
        off = np.where(den_o > 1e-3, off, 0.0)
        rm2 = rm2 + off
        alt = cm * rm2 + (1 - cm) * r_back
    else:
        alt = r_back
    r = conf * r_obs.reshape(shape) + (1 - conf) * alt
    def softmin(x, y, k=2.5):
        h = np.clip(0.5 + 0.5 * (y - x) / k, 0, 1); return y * (1 - h) + x * h - k * h * (1 - h)
    lim = np.minimum(np.where(v_hull, r_hull, 1e9), np.where(v_obs, r_obs, 1e9)).reshape(shape)
    clipped = (r > lim + 0.5).mean()
    r = np.where(lim < 1e8, softmin(r, lim), r)
    print('   %s: clipped by hull/depth limit: %.1f%% of rays' % (label, 100 * clipped))
    np.savez('out/diag_%s.npz' % label, r_obs=r_obs.reshape(shape), v_obs=v_obs.reshape(shape), r_tm=r_tm.reshape(shape), r_hull=r_hull.reshape(shape), v_hull=v_hull.reshape(shape), conf=conf, r_back=r_back, r=r, lim=lim)
    print("%s: %.0fs  conf>0.5 %.1f%%  mean |corr| %.3f" % (label, time.time() - t0, 100 * (conf > 0.5).mean(), np.abs(corr).mean()), flush=True)
    fuse.last = dict(r_obs=r_obs.reshape(shape), conf=conf, cm=(cm if mirror is not None else np.zeros(shape)))
    return r, conf
cran = json.load(open("out/cranium.json"))["cranium"]
H = px2m(*c2p([0.0, 0.5, -4.2])[0])
neck_a, neck_d, _ = prims["neck"]; Cn = px2m(neck_a, 1100.0, neck_d); Z_ring = (1536.0 - 1100.0) * S
def spine(Z):
    t = np.clip(Z / Z_ring, 0, 1); t = t * t * (3 - 2 * t); return np.stack([t * Cn[0], t * Cn[1], Z], -1)
u = np.linspace(0, 2 * np.pi, NU, endpoint=False); du = np.stack([np.cos(u), np.sin(u), np.zeros_like(u)], 1)
# --- torso rows by arc length of an average side profile
Zs = np.linspace(1.0 * S, Z_ring, 300)
prof_r = np.zeros(300)
for dvec in ([1.0, 0, 0], [-1.0, 0, 0], [0, -1.0, 0]):
    rr, _ = cast_first(in_obs, spine(Zs), np.tile(dvec, (300, 1)), 260.0, 1.0, 8); prof_r += rr / 3
arc = np.r_[0, np.cumsum(np.hypot(np.diff(prof_r), np.diff(Zs)))]
Zrows = np.interp(np.linspace(0, arc[-1], NZ + 1), arc, Zs)
O = np.repeat(spine(Zrows), NU, 0); D = np.tile(du, (NZ + 1, 1))
Rt, conf_t = fuse(O, D, (NZ + 1, NU), D[:, 1], None, "torso")
Pt = spine(Zrows)[:, None, :] + Rt[..., None] * du[None]
ring = Pt[-1]                                            # top ring (Z_ring) shared with the head
Dring = ring - H; dist_ring = np.linalg.norm(Dring, axis=1); Dring /= dist_ring[:, None]
up = np.array([0, 0, 1.0]); ang = np.arccos(np.clip(Dring @ up, -1, 1))
axis = np.cross(Dring, up); axis /= np.linalg.norm(axis, axis=1, keepdims=True)
def rot(vec, ax, th):
    c, s = np.cos(th)[..., None], np.sin(th)[..., None]
    return vec * c + np.cross(ax, vec) * s + ax * (np.sum(ax * vec, -1, keepdims=True)) * (1 - c)
vv = np.arange(1, NH) / float(NH)                       # rows strictly between ring and pole (t = i / NH)
Dh = rot(Dring[None], axis[None], vv[:, None] * ang[None])
ns = np.array([R[0, 0], -R[2, 0], R[1, 0]]); ns /= np.linalg.norm(ns)
Dm = Dh - 2 * (Dh @ ns)[..., None] * ns
KB = max(8, NH // 12)
kk = np.arange(1, NH); wk = np.clip(kk / float(KB), 0, 1); wk = wk * wk * (3 - 2 * wk)
C_ring = np.array([Cn[0], Cn[1], Z_ring])
O_rows = C_ring + wk[:, None] * (H - C_ring)
Dt = (1 - wk)[:, None, None] * du[None] + wk[:, None, None] * Dh; Dt /= np.linalg.norm(Dt, axis=-1, keepdims=True)
O_flat = np.repeat(O_rows, NU, 0)
Oh = np.tile(H, (Dh.shape[0] * NU, 1))
MIRROR_W = np.repeat(wk, NU) ** 2
Rh, conf_h = fuse(O_flat, Dt.reshape(-1, 3), Dh.shape[:2], Dt.reshape(-1, 3)[:, 1], (Oh, Dm.reshape(-1, 3)), "head")
# ---- hair texture transfer onto the hidden back of the head
info = fuse.last; ro = info["r_obs"]; cf = info["conf"]; cmir = info["cm"]
nh_, nu_ = Rh.shape
hp_obs = ro - ndi.gaussian_filter(ro, (2.5, 2.5 * nu_ / 512), mode=("nearest", "wrap"))
hp_obs = np.where(cf > 0.55, np.clip(hp_obs, -2.5, 2.5), 0.0)
Pg = O_rows[:, None, :] + Rh[..., None] * Dt
hz_hard = (Pg[..., 2] > 205.0) | ((Pg[..., 1] > -10.0) & (Pg[..., 2] > 135.0))
src_w = ((cf > 0.55) & hz_hard & (Pg[..., 2] > 200.0)).astype(float)
hidden = np.clip(1 - cf - cmir, 0, 1)
hair_zone = ((Pg[..., 2] > 200.0) | ((Pg[..., 1] > -15.0) & (Pg[..., 2] > 128.0))).astype(float)
hair_zone = ndi.gaussian_filter(hair_zone, 3.0, mode=("nearest", "wrap"))
acc = np.zeros_like(Rh); wacc = np.zeros_like(Rh)
for shift in (nu_ // 4, nu_ // 2, 3 * nu_ // 4, nu_ // 3):
    acc += np.roll(hp_obs, -shift, axis=1) * np.roll(src_w, -shift, axis=1)
    wacc += np.roll(src_w, -shift, axis=1)
    if (wacc > 0.5).mean() > 0.9: break
hair = np.where(wacc > 0.1, acc / np.maximum(wacc, 1e-6), 0.0)
Rh = Rh + hair * hidden * hair_zone
print("hair transfer: %.1f%% of head cells, rms %.2f mm" % (100 * (hidden * hair_zone > 0.5).mean(), np.sqrt(np.mean((hair * hidden * hair_zone) ** 2))))
# stitch to the ring: first rows blend from ring distance
Ph = O_rows[:, None, :] + Rh[..., None] * Dt
r_pole, _ = cast_first(in_obs, H[None], up[None], 240.0, 0.5, 12)
pole = H + up * r_pole[0]
base_c = np.array([spine(np.array([0.0]))[0][0], spine(np.array([0.0]))[0][1], 0.0])
base_ring = Pt[0].copy(); base_ring[:, 2] = 0.0
rings = [base_ring] + [Pt[i] for i in range(NZ + 1)] + [Ph[i] for i in range(Ph.shape[0])]
# ---- radius-domain assembly: one radius grid R_all (torso rings + head rows), analytic rays (see build_vertices)
R_all = np.vstack([Rt, Rh])                              # (NZ+1 + NH-1, NU)
C_all = np.vstack([conf_t, conf_h])
j0 = NZ                                                  # ring row index
PARAMS = dict(NU=NU, NZ=NZ, NH=NH, KB=KB, H=H.tolist(), Cn=Cn[:2].tolist(), Z_ring=float(Z_ring), Zrows=Zrows.tolist(), r_pole=float(r_pole[0]))
def build_vertices(R_all, P):
    """reference implementation of the analytic parametrisation (mirrored in the Rhino script)."""
    NU, NZ = P["NU"], P["NZ"]; H = np.array(P["H"]); cn = np.array(P["Cn"]); Zr = P["Z_ring"]; Zrows = np.array(P["Zrows"])
    u = np.arange(NU) * 2 * np.pi / NU; du = np.stack([np.cos(u), np.sin(u), np.zeros(NU)], 1)
    def sp(Z):
        t = np.clip(Z / Zr, 0, 1); t = t * t * (3 - 2 * t); return np.stack([t * cn[0], t * cn[1], Z], -1)
    Pt = sp(Zrows)[:, None, :] + R_all[:NZ + 1, :, None] * du[None]
    ring = Pt[-1]; Dr = ring - H; Dr /= np.linalg.norm(Dr, axis=1, keepdims=True)
    upv = np.array([0, 0, 1.0]); ang = np.arccos(np.clip(Dr @ upv, -1, 1))
    ax = np.cross(Dr, upv); ax /= np.linalg.norm(ax, axis=1, keepdims=True)
    nh = R_all.shape[0] - (NZ + 1); tt = np.arange(1, nh + 1) / float(nh + 1)  # nh = NH - 1 -> t = i / NH
    th = tt[:, None] * ang[None]; c, s_ = np.cos(th)[..., None], np.sin(th)[..., None]
    Dh = Dr[None] * c + np.cross(ax, Dr)[None] * s_ + ax[None] * (np.sum(ax * Dr, -1)[None, :, None]) * (1 - c)
    kk = np.arange(1, nh + 1); wk = np.clip(kk / float(P["KB"]), 0, 1); wk = wk * wk * (3 - 2 * wk)
    C_ring = np.array([cn[0], cn[1], Zr]); O_rows = C_ring + wk[:, None] * (H - C_ring)
    Dt = (1 - wk)[:, None, None] * du[None] + wk[:, None, None] * Dh; Dt /= np.linalg.norm(Dt, axis=-1, keepdims=True)
    Ph = O_rows[:, None, :] + R_all[NZ + 1:, :, None] * Dt
    base_ring = Pt[0].copy(); base_ring[:, 2] = 0.0
    rings = np.concatenate([base_ring[None], Pt, Ph], 0)
    pole = H + upv * P["r_pole"]; base_c = sp(np.array([0.0]))[0]; base_c[2] = 0.0
    return rings, base_c, pole
rings_arr, base_c, pole = build_vertices(R_all, PARAMS)
rings = [rings_arr[i] for i in range(rings_arr.shape[0])]
V = np.vstack([base_c[None]] + rings + [pole[None]]); nr = len(rings); pole_i = len(V) - 1
def vid(ri, ui): return 1 + ri * NU + (ui % NU)
ui = np.arange(NU)
tris = np.r_[np.c_[np.zeros(NU, int), vid(0, ui + 1), vid(0, ui)], np.c_[vid(nr - 1, ui), vid(nr - 1, ui + 1), np.full(NU, pole_i)]]
ri, uu = np.meshgrid(np.arange(nr - 1), ui, indexing="ij"); ri, uu = ri.ravel(), uu.ravel()
quads = np.c_[vid(ri, uu), vid(ri, uu + 1), vid(ri + 1, uu + 1), vid(ri + 1, uu)]
import json as _json
_json.dump(PARAMS, open(OUT.replace(".npz", "_params.json"), "w"))
np.save(OUT.replace(".npz", "_R.npy"), R_all.astype(np.float32)); np.save(OUT.replace(".npz", "_C.npy"), C_all.astype(np.float32))
np.savez(OUT, V=V, quads=quads, tris=tris, NU=NU, rows=nr, H=H)
print("mesh %s: %d verts %d quads %d tris" % (OUT, len(V), len(quads), len(tris)))
