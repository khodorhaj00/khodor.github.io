"""Radius grid -> closed quad mesh (reference implementation of the Rhino script's bust_grid)."""
import sys, json, numpy as np
RF = sys.argv[1] if len(sys.argv) > 1 else "out/mv_mesh_R.npy"
OUT = sys.argv[2] if len(sys.argv) > 2 else "out/mv_mesh.npz"
R_all = np.load(RF).astype(np.float64); P = json.load(open("out/mv_mesh_params.json"))
def build_vertices(R_all, P):
    NU, NZ = P["NU"], P["NZ"]; H = np.array(P["H"]); cn = np.array(P["Cn"]); Zr = P["Z_ring"]; Zrows = np.array(P["Zrows"])
    u = np.arange(NU) * 2 * np.pi / NU; du = np.stack([np.cos(u), np.sin(u), np.zeros(NU)], 1)
    def sp(Z):
        t = np.clip(Z / Zr, 0, 1); t = t * t * (3 - 2 * t); return np.stack([t * cn[0], t * cn[1], Z], -1)
    Pt = sp(Zrows)[:, None, :] + R_all[:NZ + 1, :, None] * du[None]
    ring = Pt[-1]; Dr = ring - H; Dr /= np.linalg.norm(Dr, axis=1, keepdims=True)
    upv = np.array([0, 0, 1.0]); ang = np.arccos(np.clip(Dr @ upv, -1, 1))
    ax = np.cross(Dr, upv); ax /= np.linalg.norm(ax, axis=1, keepdims=True)
    nh = R_all.shape[0] - (NZ + 1); tt = np.arange(1, nh + 1) / float(nh + 1)
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
rings, base_c, pole = build_vertices(R_all, P)
NU = P["NU"]; nr = rings.shape[0]
V = np.vstack([base_c[None], rings.reshape(-1, 3), pole[None]]); pole_i = len(V) - 1
def vid(ri, ui): return 1 + ri * NU + (ui % NU)
ui = np.arange(NU)
tris = np.r_[np.c_[np.zeros(NU, int), vid(0, ui + 1), vid(0, ui)], np.c_[vid(nr - 1, ui), vid(nr - 1, ui + 1), np.full(NU, pole_i)]]
ri, uu = np.meshgrid(np.arange(nr - 1), ui, indexing="ij"); ri, uu = ri.ravel(), uu.ravel()
quads = np.c_[vid(ri, uu), vid(ri, uu + 1), vid(ri + 1, uu + 1), vid(ri + 1, uu)]
np.savez(OUT, V=V, quads=quads, tris=tris, NU=NU, rows=nr)
print("mesh %s: %d verts %d quads %d tris | bbox %s .. %s" % (OUT, len(V), len(quads), len(tris), np.round(V.min(0), 1), np.round(V.max(0), 1)))
