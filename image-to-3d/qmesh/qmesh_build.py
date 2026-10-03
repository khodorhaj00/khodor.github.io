#!/usr/bin/env python3
"""
qmesh_build.py | build a qmesh recipe in the cloud: closed clean quad meshes + checks
=====================================================================================
  python qmesh_build.py recipe.json --out out_folder [--subdivide 1] [--views ref1.png ...]

Writes, per recipe:
  <name>.obj         all parts, quads kept (Rhino: Import -> mesh; SubD / ToNURBS)
  <name>_mm.stl      triangulated copy for CNC / slicers
  <name>_report.json topology + quality per part (closed, manifold, quads %, evenness)
  <name>_views.png   6 views: front, right, back, left, top, 3/4 (flat shaded, with edges)

Needs numpy + opencv for the preview only; the geometry is s3d_qmesh (pure Python).
"""
import argparse
import json
import math
import os
import sys
import time

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
import s3d_qmesh as Q  # noqa: E402


def gate(c):
    """What 'clean' means here. Returns a list of problems (empty = pass)."""
    bad = []
    if not c["closed"]:
        bad.append("open edges: %d" % c["open_edges"])
    if c["nonmanifold_edges"]:
        bad.append("non-manifold edges: %d" % c["nonmanifold_edges"])
    if not c["oriented"]:
        bad.append("faces not consistently oriented")
    if c["shells"] != 1:
        bad.append("%d shells (expected 1 per part)" % c["shells"])
    if c["volume"] <= 0:
        bad.append("negative or zero volume (inside out)")
    if c["unused_vertices"]:
        bad.append("%d unused vertices" % c["unused_vertices"])
    return bad


def render_views(parts, path, size=420):
    """Flat-shaded orthographic views with edges (numpy + cv2 painter)."""
    import numpy as np
    import cv2
    V = []
    F = []
    for _n, m in parts:
        off = len(V)
        V.extend(m.v)
        F.extend([tuple(i + off for i in f) for f in m.f])
    V = np.asarray(V, float)
    lo, hi = V.min(0), V.max(0)
    c = 0.5 * (lo + hi)
    R = np.linalg.norm(hi - lo) * 0.5 or 1.0
    # names = Rhino's named views: az 90 looks from -X (Left), az 270 from +X (Right)
    views = [("front", 0, 0), ("left", 90, 0), ("back", 180, 0), ("right", 270, 0), ("top", 0, 89.9), ("3/4", 35, 25)]
    tiles = []
    for name, az, el in views:
        a, e = math.radians(az), math.radians(el)
        # camera basis: view direction d (into the scene), right u, up w
        d = np.array([math.sin(a) * math.cos(e), math.cos(a) * math.cos(e), -math.sin(e)])
        u = np.array([math.cos(a), -math.sin(a), 0.0])
        w = np.cross(u, d)
        P = V - c
        x = P @ u
        y = P @ w
        z = P @ d
        s = 0.46 * size / R
        X = (size / 2 + x * s) * 16
        Y = (size / 2 - y * s) * 16
        img = np.full((size, size, 3), 245, np.uint8)
        light = -d * 0.6 + w * 0.6 + u * -0.4
        light /= np.linalg.norm(light)
        order = sorted(range(len(F)), key=lambda i: -float(np.mean(z[list(F[i])])))
        for fi in order:
            f = F[fi]
            pts = V[list(f)]
            n = np.cross(pts[1] - pts[0], pts[2] - pts[0])
            if len(f) == 4:
                n = n + np.cross(pts[2] - pts[0], pts[3] - pts[0])
            ln = np.linalg.norm(n)
            if ln < 1e-12:
                continue
            n /= ln
            if n @ d > 0:              # back face
                continue
            sh = 0.25 + 0.75 * max(0.0, float(n @ light))
            col = int(70 + 170 * sh)
            poly = np.stack([X[list(f)], Y[list(f)]], 1).astype(np.int32)
            cv2.fillPoly(img, [poly], (col, col, col), cv2.LINE_AA, 4)
            cv2.polylines(img, [poly], True, (60, 60, 60), 1, cv2.LINE_AA, 4)
        cv2.putText(img, name, (8, 20), cv2.FONT_HERSHEY_SIMPLEX, 0.55, (0, 0, 0), 1, cv2.LINE_AA)
        tiles.append(img)
    sheet = np.vstack([np.hstack(tiles[:3]), np.hstack(tiles[3:])])
    cv2.imwrite(path, sheet)
    return path


def main(argv=None):
    ap = argparse.ArgumentParser(description="Build a qmesh recipe: clean closed quad meshes + checks.")
    ap.add_argument("recipe")
    ap.add_argument("--out", default="")
    ap.add_argument("--subdivide", type=int, default=-1, help="Catmull-Clark levels for all parts (overrides recipe)")
    ap.add_argument("--no-preview", action="store_true")
    a = ap.parse_args(argv)
    t0 = time.time()
    recipe = json.load(open(a.recipe))
    name = recipe.get("name") or os.path.splitext(os.path.basename(a.recipe))[0]
    out = a.out or os.path.join(os.path.dirname(os.path.abspath(a.recipe)), name + "_qmesh")
    os.makedirs(out, exist_ok=True)
    parts = Q.build_recipe(recipe)
    if a.subdivide >= 0:
        parts = [(n, Q.catmull_clark(m, a.subdivide) if a.subdivide else m) for n, m in parts]
    report = {"recipe": a.recipe, "name": name, "units": recipe.get("units", "mm"), "parts": []}
    all_ok = True
    for n, m in parts:
        c = Q.check(m)
        problems = gate(c)
        all_ok = all_ok and not problems
        c["problems"] = problems
        c["name"] = n
        report["parts"].append(c)
        print("%-14s faces %7d  quads %6.2f%%  closed %-5s manifold %-5s shells %d  genus %s  "
              "vol %.3f L  size %.0f x %.0f x %.0f mm  edge CV %.2f  %s" % (
                  n, c["faces"], c["quad_pct"], c["closed"], c["nonmanifold_edges"] == 0, c["shells"],
                  c["genus"], c["volume"] * 1e-6, c["size"][0], c["size"][1], c["size"][2], c["edge_cv"],
                  "OK" if not problems else "PROBLEMS: " + "; ".join(problems)))
    obj = os.path.join(out, name + ".obj")
    Q.write_obj(parts, obj)
    stl = os.path.join(out, name + "_mm.stl")
    ntri = Q.write_stl(parts, stl)
    if not a.no_preview:
        try:
            report["preview"] = render_views(parts, os.path.join(out, name + "_views.png"))
        except ImportError:
            report["preview"] = None
    report["obj"], report["stl"], report["stl_triangles"] = obj, stl, ntri
    report["all_clean"] = all_ok
    report["seconds"] = round(time.time() - t0, 2)
    json.dump(report, open(os.path.join(out, name + "_report.json"), "w"), indent=1)
    print("OBJ (quads): %s\nSTL: %s (%d triangles)\nall parts clean: %s  (%.1f s)" % (obj, stl, ntri, all_ok, time.time() - t0))
    return report


if __name__ == "__main__":
    main()
