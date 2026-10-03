"""Styro3D photo3d - cloud helper for the Claude-chat route (photo -> AI 3D -> Rhino).

  prep   photos or a views sheet -> AI-ready images: object cut out on white, cropped,
         square, same scale for every view (a sheet is split into its views)
  check  a model from any generator (GLB / glTF / OBJ / STL / PLY) -> size, faces,
         closed, loose pieces, a 6-view picture; with --height-mm also a Z-up OBJ + STL
         in real millimetres (the Rhino script does the full clean + quads + SubD)

  python p3d_cloud.py prep photo.jpg --out ai_in/
  python p3d_cloud.py prep sheet.png --sheet 4 --names front,right,back,left --out ai_in/
  python p3d_cloud.py check model.glb --height-mm 1800 --out checked/

Needs: numpy scipy opencv-python-headless (prep); trimesh only for STL / PLY in check.
"""
from __future__ import print_function, division

import argparse
import json
import math
import os
import struct
import sys

import cv2
import numpy as np

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
sys.path.insert(0, os.path.join(HERE, "..", "views_to_3d"))
import s3d_photo_to_rhino as R  # noqa: E402  (pure readers; Rhino not needed)


# ----------------------------------------------------------------------------- prep
def prep(paths, out_dir, sheet=0, names=None, size=1024, margin=0.08, cut=True, bg=None):
    """-> list of written image paths. All views share one scale so their sizes stay true."""
    import views_to_3d as VT
    crops = []
    for p in paths:
        img, alpha = VT.load_rgb(p)
        if sheet and sheet > 1:
            crops.extend(VT.split_sheet(img, alpha, sheet, VT.parse_bg(bg) if bg else None))
            continue
        soft, hard, _r = VT.foreground(img, alpha, VT.parse_bg(bg) if bg else None)
        ys, xs = np.nonzero(hard)
        if len(ys) == 0 or hard.mean() > 0.97:          # nothing found / busy photo: keep it all
            crops.append((img, np.ones(img.shape[:2], np.float32)))
            continue
        y0, y1, x0, x1 = ys.min(), ys.max() + 1, xs.min(), xs.max() + 1
        crops.append((img[y0:y1, x0:x1], soft[y0:y1, x0:x1]))
    if not crops:
        raise SystemExit("no images")
    biggest = max(max(c.shape[:2]) for c, _m in crops)
    k = size * (1.0 - 2 * margin) / float(biggest)         # one scale for every view
    names = names or ["view%d" % (i + 1) for i in range(len(crops))]
    if len(names) < len(crops):
        names = names + ["view%d" % (i + 1) for i in range(len(names), len(crops))]
    if not os.path.isdir(out_dir):
        os.makedirs(out_dir)
    written = []
    for (rgb, m), name in zip(crops, names):
        h, w = rgb.shape[:2]
        nh, nw = max(1, int(round(h * k))), max(1, int(round(w * k)))
        rgb_s = cv2.resize(rgb, (nw, nh), interpolation=cv2.INTER_AREA)
        m_s = cv2.resize(m.astype(np.float32), (nw, nh), interpolation=cv2.INTER_AREA)[..., None]
        canvas = np.ones((size, size, 3), np.float32)
        y0, x0 = (size - nh) // 2, (size - nw) // 2
        tile = rgb_s * m_s + (1.0 - m_s) if cut else rgb_s
        canvas[y0:y0 + nh, x0:x0 + nw] = tile
        path = os.path.join(out_dir, name + ".png")
        cv2.imwrite(path, (np.clip(canvas, 0, 1)[..., ::-1] * 255).round().astype(np.uint8))
        written.append(path)
    return written


# ----------------------------------------------------------------------------- check
def load_model(path):
    """-> (V (n,3) in file units, F list of faces, ext). Quads kept for OBJ."""
    ext = os.path.splitext(path)[1].lower()
    if ext in (".glb", ".gltf", ".obj"):
        parts = R.read_gltf(path) if ext != ".obj" else R.read_obj(path)
        V, F = [], []
        for p in parts:
            v = np.asarray(p["verts"], float)
            M = np.asarray(p["matrix"], float).reshape(4, 4)
            off = sum(len(x) for x in V)
            V.append(v @ M[:3, :3].T + M[:3, 3])
            F.extend(tuple(i + off for i in f) for f in p["faces"])
        return np.concatenate(V), F, ext
    import trimesh
    m = trimesh.load(path, force="mesh")
    return np.asarray(m.vertices, float), [tuple(f) for f in m.faces], ext


def to_z_up(V, up):
    if up == "y":                                   # glTF: Y up, front +Z -> Z up, front -Y
        return np.stack([V[:, 0], -V[:, 2], V[:, 1]], 1)
    if up == "x":
        return np.stack([-V[:, 2], V[:, 1], V[:, 0]], 1)
    return V.copy()


def weld(V, F, tol):
    """Merge vertices closer than tol (AI files split vertices at UV seams)."""
    key = np.round(V / tol).astype(np.int64)
    _u, first, inv = np.unique(key, axis=0, return_index=True, return_inverse=True)
    inv = inv.ravel()
    F2 = []
    for f in F:
        g = [int(inv[i]) for i in f]
        if len(set(g)) >= 3:
            F2.append(tuple(g))
    return V[first], F2


def topology(V, F):
    """closed / boundary edges / non-manifold edges / loose pieces / quads."""
    from collections import defaultdict
    edges = defaultdict(int)
    parent = list(range(len(V)))

    def find(a):
        while parent[a] != a:
            parent[a] = parent[parent[a]]
            a = parent[a]
        return a
    for f in F:
        for i in range(len(f)):
            a, b = f[i], f[(i + 1) % len(f)]
            edges[(min(a, b), max(a, b))] += 1
            ra, rb = find(a), find(b)
            if ra != rb:
                parent[ra] = rb
    used = set(i for f in F for i in f)
    pieces = len(set(find(i) for i in used))
    boundary = sum(1 for c in edges.values() if c == 1)
    nonman = sum(1 for c in edges.values() if c > 2)
    return {"faces": len(F), "vertices": len(used), "quads": sum(1 for f in F if len(f) == 4),
            "closed": boundary == 0 and nonman == 0, "boundary_edges": boundary,
            "nonmanifold_edges": nonman, "pieces": pieces}


def drop_debris(V, F, pct=1.0):
    """Remove small loose pieces (< pct % of faces and < 5 % of the size) -> (F, dropped)."""
    parent = list(range(len(V)))

    def find(a):
        while parent[a] != a:
            parent[a] = parent[parent[a]]
            a = parent[a]
        return a
    for f in F:
        for i in f[1:]:
            ra, rb = find(f[0]), find(i)
            if ra != rb:
                parent[ra] = rb
    groups = {}
    for fi, f in enumerate(F):
        groups.setdefault(find(f[0]), []).append(fi)
    if len(groups) <= 1:
        return F, 0
    diag = float(np.linalg.norm(V.max(0) - V.min(0)))
    keep, dropped = [], 0
    for faces in groups.values():
        vid = sorted(set(i for fi in faces for i in F[fi]))
        size = float(np.linalg.norm(V[vid].max(0) - V[vid].min(0)))
        if len(faces) < pct / 100.0 * len(F) and size < 0.05 * diag:
            dropped += 1
        else:
            keep.extend(faces)
    return [F[i] for i in sorted(keep)], dropped


def triangles(F):
    T = []
    for f in F:
        for i in range(1, len(f) - 1):
            T.append((f[0], f[i], f[i + 1]))
    return np.asarray(T, np.int64)


def render6(V, T, path, size=360, n_pts=500000, seed=0):
    """6 views (front, right, back, left, top, 3/4) by surface splatting with a z-buffer."""
    rng = np.random.default_rng(seed)
    a, b, c = V[T[:, 0]], V[T[:, 1]], V[T[:, 2]]
    cr = np.cross(b - a, c - a)
    area = np.linalg.norm(cr, axis=1)
    keep = area > 0
    a, b, c, cr, area = a[keep], b[keep], c[keep], cr[keep], area[keep]
    nrm = cr / area[:, None]
    idx = rng.choice(len(area), size=n_pts, p=area / area.sum())
    r1, r2 = rng.random(n_pts), rng.random(n_pts)
    s = np.sqrt(r1)
    P = (1 - s)[:, None] * a[idx] + (s * (1 - r2))[:, None] * b[idx] + (s * r2)[:, None] * c[idx]
    N = nrm[idx]
    lo, hi = V.min(0), V.max(0)
    ctr = 0.5 * (lo + hi)
    rad = 0.5 * np.linalg.norm(hi - lo) or 1.0
    tiles = []
    # names = Rhino's named views: az 90 looks from -X (Left), az 270 from +X (Right)
    for name, az, el in (("front", 0, 0), ("left", 90, 0), ("back", 180, 0), ("right", 270, 0),
                         ("top", 0, 89.9), ("3/4", 35, 25)):
        A, E = math.radians(az), math.radians(el)
        d = np.array([math.sin(A) * math.cos(E), math.cos(A) * math.cos(E), -math.sin(E)])
        u = np.array([math.cos(A), -math.sin(A), 0.0])
        w = np.cross(u, d)
        Q = P - ctr
        k = 0.46 * size / rad
        x = np.round(size / 2 + (Q @ u) * k).astype(int)
        y = np.round(size / 2 - (Q @ w) * k).astype(int)
        z = Q @ d
        ok = (x >= 0) & (x < size) & (y >= 0) & (y < size)
        x, y, z, n = x[ok], y[ok], z[ok], N[ok]
        pix = y * size + x
        order = np.lexsort((z, pix))                    # nearest first within each pixel
        pix_s = pix[order]
        first = np.ones(len(pix_s), bool)
        first[1:] = pix_s[1:] != pix_s[:-1]
        sel = order[first]
        light = -d * 0.6 + w * 0.6 - u * 0.4
        light /= np.linalg.norm(light)
        shade = 0.25 + 0.75 * np.clip(np.abs(n[sel] @ light), 0, 1)
        img = np.full(size * size, 245.0)
        img[pix[sel]] = 60 + 175 * shade
        img = img.reshape(size, size).astype(np.uint8)
        hole = (img == 245).astype(np.uint8)
        filled = cv2.morphologyEx(img, cv2.MORPH_CLOSE, np.ones((3, 3), np.uint8))
        img = np.where(hole & (filled != 245), filled, img).astype(np.uint8)
        tile = cv2.cvtColor(img, cv2.COLOR_GRAY2BGR)
        cv2.putText(tile, name, (8, 20), cv2.FONT_HERSHEY_SIMPLEX, 0.55, (0, 0, 0), 1, cv2.LINE_AA)
        tiles.append(tile)
    cv2.imwrite(path, np.vstack([np.hstack(tiles[:3]), np.hstack(tiles[3:])]))
    return path


def write_obj(path, V, F):
    with open(path, "w") as fh:
        fh.write("# Styro3D photo3d, units mm, Z up, front -Y\n")
        fh.write("".join("v %.4f %.4f %.4f\n" % tuple(v) for v in V))
        fh.write("".join("f " + " ".join(str(i + 1) for i in f) + "\n" for f in F))


def write_stl(path, V, T):
    with open(path, "wb") as fh:
        fh.write(struct.pack("<80sI", b"Styro3D photo3d, units mm", len(T)))
        a, b, c = V[T[:, 0]], V[T[:, 1]], V[T[:, 2]]
        n = np.cross(b - a, c - a)
        n /= np.maximum(np.linalg.norm(n, axis=1, keepdims=True), 1e-12)
        rec = np.zeros(len(T), dtype=[("n", "<f4", 3), ("a", "<f4", 3), ("b", "<f4", 3), ("c", "<f4", 3),
                                      ("x", "<u2")])
        rec["n"], rec["a"], rec["b"], rec["c"] = n, a, b, c
        fh.write(rec.tobytes())


def check(path, out_dir, height_mm=0.0, up="auto", size_axis="height", turn=0.0):
    V, F, ext = load_model(path)
    up = up if up in ("x", "y", "z") else R.default_up(ext)
    V = to_z_up(V, up)
    if turn:
        t = math.radians(turn)
        V = V @ np.array([[math.cos(t), -math.sin(t), 0], [math.sin(t), math.cos(t), 0], [0, 0, 1]]).T
    V, F = weld(V, F, max(1e-9, 1e-6 * float(np.linalg.norm(V.max(0) - V.min(0)))))
    F, dropped = drop_debris(V, F)
    used = np.unique(np.concatenate([np.asarray(f) for f in F]))
    remap = -np.ones(len(V), np.int64)
    remap[used] = np.arange(len(used))
    V = V[used]
    F = [tuple(int(remap[i]) for i in f) for f in F]
    ext_xyz = V.max(0) - V.min(0)
    cur = {"width": ext_xyz[0], "depth": ext_xyz[1], "height": ext_xyz[2]}.get(size_axis, ext_xyz.max())
    k = height_mm / cur if height_mm > 0 and cur > 0 else (R.keep_scale_mm(ext) or 1.0)
    V = V * k
    lo, hi = V.min(0), V.max(0)
    V = V - np.array([0.5 * (lo[0] + hi[0]), 0.5 * (lo[1] + hi[1]), lo[2]])
    info = topology(V, F)
    info["dropped_loose_bits"] = dropped
    size = V.max(0) - V.min(0)
    info.update({"file": os.path.basename(path), "up": up, "scale_to_mm": float(k),
                 "size_mm": [round(float(s), 1) for s in size]})
    if not os.path.isdir(out_dir):
        os.makedirs(out_dir)
    base = os.path.join(out_dir, os.path.splitext(os.path.basename(path))[0])
    T = triangles(F)
    info["views_png"] = render6(V, T, base + "_views.png")
    if height_mm > 0:
        write_obj(base + "_mm.obj", V, F)
        write_stl(base + "_mm.stl", V, T)
        info["obj"], info["stl"] = base + "_mm.obj", base + "_mm.stl"
    json.dump(info, open(base + "_check.json", "w"), indent=1)
    return info


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    sub = ap.add_subparsers(dest="cmd")
    p = sub.add_parser("prep", help="photos / views sheet -> AI-ready images")
    p.add_argument("images", nargs="+")
    p.add_argument("--out", default="ai_in")
    p.add_argument("--sheet", type=int, default=0, help="split each image into N views")
    p.add_argument("--names", default="", help="comma list, e.g. front,right,back,left")
    p.add_argument("--size", type=int, default=1024)
    p.add_argument("--no-cut", action="store_true", help="keep the photo background")
    p.add_argument("--bg", default="", help="background colour: auto / white / black / #rrggbb")
    c = sub.add_parser("check", help="model file -> size, topology, 6-view picture [, mm OBJ + STL]")
    c.add_argument("model")
    c.add_argument("--out", default="checked")
    c.add_argument("--height-mm", type=float, default=0.0, help="real size; writes OBJ + STL in mm")
    c.add_argument("--axis", default="height", help="the size is the height / width / depth / longest")
    c.add_argument("--up", default="auto", help="file up axis: auto / y / z / x")
    c.add_argument("--turn", type=float, default=0.0, help="turn about Z in degrees")
    a = ap.parse_args(argv)
    if a.cmd == "prep":
        names = [n.strip() for n in a.names.split(",") if n.strip()] or None
        for w in prep(a.images, a.out, a.sheet, names, a.size, cut=not a.no_cut, bg=a.bg or None):
            print(w)
    elif a.cmd == "check":
        print(json.dumps(check(a.model, a.out, a.height_mm, a.up, a.axis, a.turn), indent=1))
    else:
        ap.print_help()


if __name__ == "__main__":
    main()
