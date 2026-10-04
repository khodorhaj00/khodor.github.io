#!/usr/bin/env python3
"""
selftest.py | proves views_to_3d.py on objects with a known true shape.
Renders turntable sheets of a test object (and optionally of any mesh .npz with
V + tris/quads), runs views_to_3d, and measures the error against the truth.

  python selftest.py                 # built-in test object, 4 cases
  python selftest.py --mesh bust.npz --height-mm 290

Cases: 4 views | 4 views with left/right swapped | 8 views with the
diagonal views off by 7 deg | 8 views exact.  Needs numpy scipy opencv scikit-image.
"""
import argparse
import json
import math
import os
import sys
import time

import cv2
import numpy as np
from scipy.spatial import cKDTree
from skimage import measure

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
import views_to_3d  # noqa: E402


# ---------------------------------------------------------------- test object (signed distances, mm)
def sd_ellipsoid(p, c, r):
    q = (p - c) / r
    return (np.linalg.norm(q, axis=-1) - 1.0) * r.min()


def sd_capsule(p, a, b, r):
    pa, ba = p - a, b - a
    h = np.clip((pa @ ba) / (ba @ ba), 0, 1)
    return np.linalg.norm(pa - h[..., None] * ba, axis=-1) - r


def sd_box(p, c, h):
    q = np.abs(p - c) - h
    return np.linalg.norm(np.maximum(q, 0), axis=-1) + np.minimum(q.max(-1), 0)


def sd_torus_xz(p, c, R, r):          # ring in the XZ plane (axis along Y)
    q = p - c
    xz = np.hypot(q[..., 0], q[..., 2]) - R
    return np.hypot(xz, q[..., 1]) - r


def sd_cyl_z(p, c, r, z0, z1):
    d = np.hypot(p[..., 0] - c[0], p[..., 1] - c[1]) - r
    dz = np.maximum(z0 - p[..., 2], p[..., 2] - z1)
    return np.minimum(np.maximum(d, dz), 0) + np.hypot(np.maximum(d, 0), np.maximum(dz, 0))


def test_object(step=4.0):
    """Asymmetric 'kettle': body, base, spout (+X), handle ring (-X), knob,
    plate on the front (-Y), fin on the back (+Y). About 800 mm tall."""
    xs = np.arange(-560, 560, step)
    ys = np.arange(-360, 360, step)
    zs = np.arange(-20, 830, step)
    Z, Y, X = np.meshgrid(zs, ys, xs, indexing="ij")
    p = np.stack([X, Y, Z], -1)
    d = sd_ellipsoid(p, np.array([0, 0, 400.0]), np.array([300, 260, 300.0]))
    d = np.minimum(d, sd_cyl_z(p, (0, 0), 200, 0, 140))
    d = np.minimum(d, sd_capsule(p, np.array([250, 0, 420.0]), np.array([480, 0, 650.0]), 55))
    d = np.minimum(d, sd_torus_xz(p, np.array([-330, 0, 450.0]), 140, 40))
    d = np.minimum(d, sd_ellipsoid(p, np.array([0, 0, 720.0]), np.array([70, 70, 70.0])))
    d = np.minimum(d, sd_box(p, np.array([0, -270, 380.0]), np.array([120, 40, 60.0])))
    d = np.minimum(d, sd_box(p, np.array([0, 250, 560.0]), np.array([40, 60, 120.0])))
    v, f, _n, _ = measure.marching_cubes(d.astype(np.float32), 0.0)
    V = np.stack([xs[0] + v[:, 2] * step, ys[0] + v[:, 1] * step, zs[0] + v[:, 0] * step], 1)
    return outward(V, f)


def outward(V, F):
    """Flip the winding if the signed volume is negative (normals must point out)."""
    tri = V[F]
    vol = np.einsum("ij,ij->i", tri[:, 0], np.cross(tri[:, 1], tri[:, 2])).sum() / 6.0
    return (V, F) if vol > 0 else (V, F[:, ::-1].copy())


def load_mesh(path):
    d = np.load(path)
    V = d["V"].astype(np.float64)
    tris = [d["tris"]] if "tris" in d.files else []
    if "quads" in d.files:
        q = d["quads"]
        tris += [q[:, [0, 1, 2]], q[:, [0, 2, 3]]]
    return outward(V, np.concatenate(tris).astype(np.int64))


# ---------------------------------------------------------------- renderer (orthographic painter)
def albedo(P):
    return np.stack([0.62 + 0.28 * np.sin(P[:, 0] / 47.0 + 0.5 * np.sin(P[:, 2] / 61.0)),
                     0.55 + 0.30 * np.sin(P[:, 2] / 39.0 + 1.0),
                     0.50 + 0.30 * np.sin(P[:, 1] / 43.0 + 2.0 + P[:, 0] / 97.0)], 1).clip(0, 1)


def render(V, F, angle, px, scale, centre, bg, light=(-0.45, 0.55, 0.70)):
    t = math.radians(angle)
    u = V[:, 0] * math.cos(t) - V[:, 1] * math.sin(t)
    w = V[:, 0] * math.sin(t) + V[:, 1] * math.cos(t)
    tri = V[F]
    n = np.cross(tri[:, 1] - tri[:, 0], tri[:, 2] - tri[:, 0])
    n /= np.maximum(np.linalg.norm(n, axis=1, keepdims=True), 1e-12)
    eu = np.array([math.cos(t), -math.sin(t), 0.0])
    ed = np.array([math.sin(t), math.cos(t), 0.0])
    ncam = np.stack([n @ eu, n[:, 2], -(n @ ed)], 1)            # (right, up, toward camera)
    lv = np.array(light) / np.linalg.norm(light)
    shade = 0.30 + 0.70 * np.clip(ncam @ lv, 0, 1)          # key light + fill, like a studio sheet
    col = albedo(tri.mean(1)) * shade[:, None]
    facing = ncam[:, 2] > 0
    order = np.argsort(-w[F].mean(1))
    order = order[facing[order]]
    xs = np.round((centre[0] + u * scale) * 16).astype(np.int32)
    ys = np.round((centre[1] - V[:, 2] * scale) * 16).astype(np.int32)
    img = np.empty((px[0], px[1], 3), np.uint8)
    img[:] = bg
    c255 = (col * 255).astype(np.uint8)
    for fi in order:
        a, b, c = F[fi]
        pts = np.array([[xs[a], ys[a]], [xs[b], ys[b]], [xs[c], ys[c]]], np.int32)
        cv2.fillConvexPoly(img, pts, tuple(int(x) for x in c255[fi][::-1]), cv2.LINE_AA, 4)
    return img


def make_sheet(V, F, angles, labels, cols, bg, path, px=520):
    zmin, zmax = V[:, 2].min(), V[:, 2].max()
    scale = 0.80 * px / (zmax - zmin)
    reach = np.hypot(V[:, 0], V[:, 1]).max()                  # widest outline in any view
    pw = int(2 * reach * scale + 0.1 * px)
    centre = (pw / 2.0, px / 2.0 + 0.5 * (zmax + zmin) * scale)
    tiles = []
    for a, lab in zip(angles, labels):
        im = render(V, F, a, (px, pw), scale, centre, bg)
        cell = np.empty((px + 60, pw + 40, 3), np.uint8)
        cell[:] = bg
        cell[:px, 20:20 + pw] = im
        tc = (40, 40, 40) if sum(bg) > 380 else (220, 220, 220)
        cv2.putText(cell, lab, (pw // 2 - 12 * len(lab), px + 40), cv2.FONT_HERSHEY_SIMPLEX, 1.0, tc, 2, cv2.LINE_AA)
        tiles.append(cell)
    rows = [np.hstack(tiles[i:i + cols]) for i in range(0, len(tiles), cols)]
    sheet = np.vstack(rows)
    cv2.imwrite(path, sheet)
    return path


# ---------------------------------------------------------------- error vs truth
def sample_surface(V, F, n, rng, normals=False):
    tri = V[F]
    cr = np.cross(tri[:, 1] - tri[:, 0], tri[:, 2] - tri[:, 0])
    area = 0.5 * np.linalg.norm(cr, axis=1)
    idx = rng.choice(len(F), n, p=area / area.sum())
    r1, r2 = rng.random(n), rng.random(n)
    s = np.sqrt(r1)
    pts = tri[idx, 0] * (1 - s)[:, None] + tri[idx, 1] * (s * (1 - r2))[:, None] + tri[idx, 2] * (s * r2)[:, None]
    if normals:
        return pts, cr[idx] / np.maximum(2 * area[idx, None], 1e-12)
    return pts


def read_stl(path):
    with open(path, "rb") as fh:
        fh.read(80)
        n = int(np.frombuffer(fh.read(4), "<u4")[0])
        rec = np.frombuffer(fh.read(), dtype=[("n", "<f4", 3), ("v", "<f4", (3, 3)), ("a", "<u2")], count=n)
    tri = rec["v"].reshape(-1, 3).astype(np.float64)
    return tri, np.arange(len(tri)).reshape(-1, 3)


def error_vs_truth(Vt, Ft, stl, rng, volume=None, voxel_mm=0.0):
    Vr, Fr = read_stl(stl)
    # same placement rule as views_to_3d: base on Z=0, X/Y centred on the bounding box
    Vt = Vt.copy()
    Vt[:, 2] -= Vt[:, 2].min()
    for i in (0, 1):
        Vt[:, i] -= 0.5 * (Vt[:, i].min() + Vt[:, i].max())
    a = sample_surface(Vt, Ft, 60000, rng)
    b, nb = sample_surface(Vr, Fr, 120000, rng, normals=True)
    d_ab, ib = cKDTree(b).query(a)          # truth -> model
    d_ba = cKDTree(a).query(b)[0]           # model -> truth (extra material: hull fill)
    h = Vt[:, 2].max()
    # CNC safety: true surface that lies OUTSIDE the model = material the model is missing.
    # Exact inside test on the saved hull volume; nearest-normal sign as a fallback.
    if volume:
        mm_px = float(np.load(volume)["mm_px"])
        inside_val = views_to_3d.sample_volume(volume, a)                  # px, > 0 outside
        signed = np.where(inside_val > 0, d_ab, -d_ab)
        signed = np.where(inside_val > 0.5, np.maximum(signed, inside_val * mm_px), signed)
    else:
        signed = np.einsum("ij,ij->i", a - b[ib], nb[ib])
    miss = signed > max(0.003 * h, voxel_mm)      # deeper than one voxel = really missing
    return {"height_mm": float(h), "missing_pct": float(100.0 * miss.mean()),
            "missing_p95_mm": float(np.percentile(signed[miss], 95)) if miss.any() else 0.0,
            "truth_to_model_mean": float(d_ab.mean()),
            "truth_to_model_p95": float(np.percentile(d_ab, 95)),
            "model_to_truth_mean": float(d_ba.mean()), "model_to_truth_p95": float(np.percentile(d_ba, 95))}


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--mesh", default="", help=".npz with V and tris/quads (default: built-in test object)")
    ap.add_argument("--height-mm", type=float, default=0.0)
    ap.add_argument("--out", default=os.path.join(HERE, "selftest_out"))
    ap.add_argument("--res", type=int, default=256)
    a = ap.parse_args()
    os.makedirs(a.out, exist_ok=True)
    rng = np.random.default_rng(1)
    if a.mesh:
        V, F = load_mesh(a.mesh)
        tag = os.path.splitext(os.path.basename(a.mesh))[0]
    else:
        V, F = test_object()
        tag = "kettle"
    H = a.height_mm or float(V[:, 2].max() - V[:, 2].min())
    print("%s: %d vertices, %d triangles, height %.0f mm" % (tag, len(V), len(F), H))
    L4 = ["FRONT", "RIGHT", "BACK", "LEFT"]
    cases = [
        ("4views", [0, 90, 180, 270], [0, 90, 180, 270], L4, 2, (255, 255, 255), []),
        ("4views_safe", [0, 90, 180, 270], [0, 90, 180, 270], L4, 2, (255, 255, 255),
         ["--round", "off", "--pairs", "strict"]),
        ("4views_swapped", [0, 270, 180, 90], [0, 90, 180, 270], L4, 2, (255, 255, 255), []),
        ("8views_off7", [0, 38, 90, 142, 180, 218, 270, 322], None, [str(x) for x in range(8)], 4, (0, 0, 0), []),
        ("8views", [0, 45, 90, 135, 180, 225, 270, 315], None, [str(x) for x in range(8)], 4, (255, 255, 255), []),
    ]
    results = {}
    for name, true_angles, _nom, labels, cols, bg, extra in cases:
        t0 = time.time()
        sname = name.replace("_safe", "")
        sheet = os.path.join(a.out, "%s_%s_sheet.png" % (tag, sname))
        if not os.path.exists(sheet) or sname == name:
            make_sheet(V, F, true_angles, labels, cols, bg, sheet)
        out = os.path.join(a.out, "%s_%s" % (tag, name))
        info = views_to_3d.main([sheet, "--views", str(len(true_angles)), "--height-mm", "%.3f" % H,
                                 "--out", out, "--res", str(a.res), "--save-volume"] + extra)
        stl = os.path.join(out, os.path.basename(out) + "_mm.stl")
        err = error_vs_truth(V, F, stl, rng, os.path.join(out, os.path.basename(out) + "_volume.npz"),
                             voxel_mm=H / float(a.res))
        err.update({"true_angles": true_angles, "found_angles": [round(x, 2) for x in info["angles_deg"]],
                    "order": info["order"], "iou": [round(x, 4) for x in info["iou"]],
                    "closed": info["mesh"]["closed"], "seconds": round(time.time() - t0, 1)})
        results[name] = err
        print("== %s: order %s | angles %s | mean error %.2f mm (truth->model) %.2f mm (model->truth) | "
              "p95 %.1f / %.1f mm | missing material on %.2f%% of the true surface (p95 %.1f mm) | closed %s" % (
                  name, info["order"], err["found_angles"], err["truth_to_model_mean"], err["model_to_truth_mean"],
                  err["truth_to_model_p95"], err["model_to_truth_p95"], err["missing_pct"], err["missing_p95_mm"],
                  err["closed"]))
    json.dump(results, open(os.path.join(a.out, "%s_results.json" % tag), "w"), indent=1)


if __name__ == "__main__":
    main()
