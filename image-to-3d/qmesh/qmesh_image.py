#!/usr/bin/env python3
"""
qmesh_image.py | image(s) + real dimensions -> qmesh recipe -> clean closed quad mesh
=====================================================================================
Three universal routes, chosen by the shape of the object:

  sign     flat outline (letters, logos, signs, reliefs, cut-outs)  -> extrude
           python qmesh_image.py sign logo.png --height-mm 600 --thickness-mm 50 --build
  revolve  turned object seen from the front (vase, column, baluster, bottle, lamp)
           python qmesh_image.py revolve vase.png --height-mm 800 --build
  views    any solid object from 2 / 4 / 8 views (bust, figure, animal, product)
           python qmesh_image.py views sheet.png --views 4 --height-mm 1800 --build

Each route writes <name>_recipe.json (editable: every number is real mm) and, with
--build, runs qmesh_build.py: OBJ with quads, STL, report and a 6-view preview, plus
an outline match (IoU) of the result against the input views.

Needs numpy, scipy, opencv-python-headless, scikit-image (+ ../views_to_3d).
"""
import argparse
import json
import math
import os
import sys

import numpy as np
from scipy import ndimage as ndi
from skimage import measure

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
sys.path.insert(0, os.path.join(HERE, "..", "views_to_3d"))
import s3d_qmesh as Q  # noqa: E402
import views_to_3d as VT  # noqa: E402


# =============================================================================
# Outlines -> clean loops in mm
# =============================================================================
def object_mask(path, bg="auto"):
    """Soft mask (0..1) of the single object in an image, plus the RGB image."""
    img, alpha = VT.load_rgb(path)
    views = VT.split_sheet(img, alpha, 1, VT.parse_bg(bg))
    crop, mask = views[0]
    return crop, mask


def full_mask(path, bg="auto"):
    """Soft mask of EVERYTHING on the image (all letters of a word, all logo parts).
    Thin lines and specks are removed the same way the views splitter does it."""
    img, alpha = VT.load_rgb(path)
    soft, hard, r_open = VT.foreground(img, alpha, VT.parse_bg(bg))
    lab, n = ndi.label(hard)
    if n:
        sizes = ndi.sum(hard, lab, np.arange(1, n + 1))
        hard = np.isin(lab, 1 + np.nonzero(sizes >= 0.002 * sizes.sum())[0])
    keep = ndi.binary_dilation(hard, structure=VT.disk(r_open + 1))
    return img, np.where(keep, np.maximum(soft, hard), 0.0)


def loops_px(mask):
    """Sub-pixel outline loops [(N, 2) array of (x, y) px, y down] with nesting."""
    pad = np.pad(mask.astype(np.float64), 2)
    cs = measure.find_contours(pad, 0.5)
    loops = []
    for c in cs:
        if len(c) < 8:
            continue
        xy = np.stack([c[:, 1] - 2, c[:, 0] - 2], 1)
        if np.hypot(*(xy[0] - xy[-1])) < 1e-6:
            xy = xy[:-1]
        loops.append(xy)
    areas = [abs(Q.poly_area([tuple(p) for p in l])) for l in loops]
    keep = [i for i, a in enumerate(areas) if a > 4.0]           # drop specks
    loops = [loops[i] for i in keep]
    return loops


def nest(loops):
    """Group loops into regions: [(outer, [holes])] by even-odd containment."""
    polys = [[tuple(p) for p in l] for l in loops]
    areas = [abs(Q.poly_area(p)) for p in polys]
    depth, parent = [0] * len(polys), [-1] * len(polys)
    for i, p in enumerate(polys):
        x, y = p[0]
        for j, q in enumerate(polys):
            if j != i and areas[j] > areas[i] and Q.point_in_poly(x, y, q):
                depth[i] += 1
                if parent[i] < 0 or areas[j] < areas[parent[i]]:
                    parent[i] = j
    regions = []
    for i in range(len(polys)):
        if depth[i] % 2 == 0:
            holes = [polys[j] for j in range(len(polys)) if parent[j] == i and depth[j] % 2 == 1]
            regions.append((polys[i], holes))
    return regions


def douglas_peucker(pts, tol, closed=True):
    pts = np.asarray(pts, float)
    if closed:
        # split at the farthest pair so the loop has two anchors
        d = np.hypot(*(pts - pts[0]).T)
        k = int(np.argmax(d))
        a = douglas_peucker(pts[:k + 1], tol, False)
        b = douglas_peucker(np.vstack([pts[k:], pts[:1]]), tol, False)
        return np.vstack([a[:-1], b[:-1]])
    if len(pts) < 3:
        return pts
    p0, p1 = pts[0], pts[-1]
    seg = p1 - p0
    L = np.hypot(*seg)
    if L < 1e-12:
        dist = np.hypot(*(pts - p0).T)
    else:
        d = pts - p0
        dist = np.abs(seg[0] * d[:, 1] - seg[1] * d[:, 0]) / L
    i = int(np.argmax(dist))
    if dist[i] > tol:
        a = douglas_peucker(pts[:i + 1], tol, False)
        b = douglas_peucker(pts[i:], tol, False)
        return np.vstack([a[:-1], b])
    return np.vstack([p0, p1])


def clean_loop(xy_mm, tol_mm, edge_mm, smooth_px_mm=0.0, corner_deg=35.0):
    """Pixel staircase off, corners kept, even spacing: the loop the mesh is built on."""
    pts = np.asarray(xy_mm, float)
    if smooth_px_mm > 0:
        n = len(pts)
        sig = max(0.5, smooth_px_mm)
        pts = np.stack([ndi.gaussian_filter1d(pts[:, 0], sig, mode="wrap"),
                        ndi.gaussian_filter1d(pts[:, 1], sig, mode="wrap")], 1) if n > 8 else pts
    simp = douglas_peucker(pts, tol_mm, True)
    loop = Q.resample([tuple(p) for p in simp], step=edge_mm, closed=True, corner_deg=corner_deg)
    if Q.poly_area(loop) < 0:
        loop = loop[::-1]
    return loop


# =============================================================================
# Route 1: sign / letters / logo -> extrude
# =============================================================================
def sign_recipe(path, height_mm=0.0, width_mm=0.0, thickness_mm=20.0, edge_mm=0.0, tol_mm=0.0,
                name=None):
    _img, mask = full_mask(path)
    H, W = mask.shape
    rows = np.nonzero((mask > 0.5).any(1))[0]
    cols = np.nonzero((mask > 0.5).any(0))[0]
    hpx = rows[-1] - rows[0] + 1
    wpx = cols[-1] - cols[0] + 1
    if height_mm > 0:
        k = height_mm / hpx
    elif width_mm > 0:
        k = width_mm / wpx
    else:
        raise SystemExit("give --height-mm or --width-mm (real size)")
    size = max(hpx, wpx) * k
    edge = edge_mm or max(size / 120.0, 1.0)
    tol = tol_mm or max(0.6 * k, size / 2000.0)
    x0, y1 = cols[0], rows[-1]
    regions = nest(loops_px(mask))
    parts = []
    for i, (outer, holes) in enumerate(sorted(regions, key=lambda r: min(p[0] for p in r[0]))):
        to_mm = lambda loop: [((x - x0) * k, (y1 - y) * k) for x, y in loop]     # y up, base on 0
        o = clean_loop(to_mm(outer), tol, edge, smooth_px_mm=0.0)
        hs = []
        for h in holes:
            hl = clean_loop(to_mm(h), tol, edge)
            if abs(Q.poly_area(hl)) > (2 * edge) ** 2:
                hs.append(hl[::-1])
        parts.append({"name": "piece_%02d" % (i + 1), "op": "extrude", "plane": "XZ", "height": thickness_mm,
                      "edge": edge, "outer": [[round(x, 3), round(y, 3)] for x, y in o],
                      "holes": [[[round(x, 3), round(y, 3)] for x, y in h] for h in hs]})
    return {"format": "s3d-qmesh/1", "name": name or os.path.splitext(os.path.basename(path))[0],
            "units": "mm", "source": {"route": "sign", "image": path, "mm_per_px": k, "thickness_mm": thickness_mm},
            "parts": parts}


# =============================================================================
# Route 2: turned object -> revolve
# =============================================================================
def revolve_recipe(path, height_mm, segments=48, tol_mm=0.0, name=None):
    _img, mask = object_mask(path)
    m = (mask > 0.5)
    rows = np.nonzero(m.any(1))[0]
    k = height_mm / float(rows[-1] - rows[0] + 1)
    lefts, rights, zs = [], [], []
    for r in rows:
        prof = mask[r]
        idx = np.nonzero(prof > 0.5)[0]
        a, b = idx[0], idx[-1]
        lo = a - 1 + (0.5 - prof[a - 1]) / max(prof[a] - prof[a - 1], 1e-6) if a > 0 else a - 0.5
        hi = b + (prof[b] - 0.5) / max(prof[b] - prof[b + 1], 1e-6) if b < len(prof) - 1 else b + 0.5
        lefts.append(lo)
        rights.append(hi)
        zs.append(rows[-1] - r + 0.5)
    lefts, rights, zs = np.array(lefts), np.array(rights), np.array(zs)
    axis = float(np.median(0.5 * (lefts + rights)))
    radius = 0.5 * (rights - lefts)                                   # symmetric turned part
    radius = ndi.gaussian_filter1d(radius, 1.0, mode="nearest")
    order = np.argsort(zs)
    pts = [(float(radius[i] * k), float(zs[i] * k)) for i in order]
    z_top = (rows[-1] - rows[0] + 1) * k
    prof = [(0.0, 0.0), (pts[0][0], 0.0)] + pts + [(pts[-1][0], z_top), (0.0, z_top)]
    tol = tol_mm or max(0.5 * k, height_mm / 1500.0)
    simp = douglas_peucker(np.array(prof), tol, closed=False)
    off = float(np.std(0.5 * (lefts + rights) - axis) * k)
    return {"format": "s3d-qmesh/1", "name": name or os.path.splitext(os.path.basename(path))[0],
            "units": "mm", "source": {"route": "revolve", "image": path, "mm_per_px": k,
                                       "axis_wobble_mm": round(off, 2)},
            "parts": [{"name": "body", "op": "revolve", "segments": segments,
                       "profile": [[round(float(r), 3), round(float(z), 3)] for r, z in simp]}]}


# =============================================================================
# Route 3: 2 / 4 / 8 views -> visual hull -> ring sections -> lofts
# =============================================================================
def views_recipe(sheet, n_views, height_mm, segments=48, edge_mm=0.0, extra=None, name=None, work=None,
                 images=None):
    segments = Q._mult4(segments)
    work = work or os.path.splitext(sheet if sheet else images[0])[0] + "_hull"
    args = ([sheet, "--views", str(n_views)] if sheet else ["--images"] + list(images))
    args += ["--height-mm", "%.3f" % height_mm, "--out", work, "--save-volume"] + list(extra or [])
    info = VT.main(args)
    nm = os.path.basename(os.path.normpath(work))
    d = np.load(os.path.join(work, nm + "_volume.npz"))
    vol, x0, y0, g, hc, mm_px, shift = (d["vol"], float(d["x0"]), float(d["y0"]), float(d["g"]),
                                         int(d["hc"]), float(d["mm_px"]), d["shift"])
    inside = vol < 0
    rows_any = np.nonzero(inside.any(axis=(1, 2)))[0]
    r_top, r_bot = int(rows_any[0]), int(rows_any[-1])           # padded index rows (top = small)
    angles = math.pi / 4 + 2 * math.pi * np.arange(segments) / segments
    dirs = np.stack([np.cos(angles), np.sin(angles)], 1)
    min_area_px = (0.02 * height_mm / (g * mm_px)) ** 2

    def ring_at(ri, cm):
        """Outermost boundary radius along each ray from the piece's centre (px)."""
        field = np.where(cm, vol[ri], np.maximum(vol[ri], 0.5))
        ys, xs = np.nonzero(cm)
        cy, cx = ys.mean(), xs.mean()
        rmax = float(np.hypot(ys - cy, xs - cx).max()) + 3.0
        ts = np.linspace(0.0, rmax, int(rmax * 4) + 2)
        P = np.stack([cy + ts[None, :] * dirs[:, 1:2], cx + ts[None, :] * dirs[:, 0:1]])
        vals = ndi.map_coordinates(field, P.reshape(2, -1), order=1, mode="constant", cval=5.0).reshape(segments, -1)
        rad = np.full(segments, 0.5)
        for j in range(segments):
            ins = np.nonzero(vals[j] < 0)[0]
            if not len(ins):
                continue
            last = ins[-1]
            if last + 1 < len(ts):
                v0, v1 = vals[j, last], vals[j, last + 1]
                t = v0 / (v0 - v1) if v0 != v1 else 0.0
                rad[j] = ts[last] + t * (ts[last + 1] - ts[last])
            else:
                rad[j] = ts[last]
        return cx, cy, ndi.gaussian_filter1d(rad, 0.8, mode="wrap")

    # 1 dense pass: every row, every piece, tracked bottom -> top by overlap
    tracks, prev = [], []
    for ri in range(r_bot, r_top - 1, -1):
        lab, n = ndi.label(inside[ri])
        comps = [lab == ci for ci in range(1, n + 1)]
        comps = [cm for cm in comps if cm.sum() >= min_area_px]
        new_prev, used = [], set()
        for cm in comps:
            best, best_ov = None, 0
            for ti, (tr, last) in enumerate(prev):
                ov = int((cm & last).sum())
                if ov > best_ov and ti not in used:
                    best, best_ov = ti, ov
            if best is not None:
                tr = prev[best][0]
                used.add(best)
            else:
                tr = []
                tracks.append(tr)
            cx, cy, rad = ring_at(ri, cm)
            tr.append((ri, cx, cy, rad))
            new_prev.append((tr, cm))
        prev = new_prev
    # 2 per piece: smooth, then place rings evenly along the surface (arc length)
    parts = []
    min_rows = max(4, int(0.03 * (r_bot - r_top)))                 # thin slivers (< 3 % of height): drop
    for ti, tr in enumerate(sorted([t for t in tracks if len(t) >= min_rows], key=len, reverse=True)):
        rows = np.array([t[0] for t in tr], float)
        C = np.array([[t[1], t[2]] for t in tr])
        R = np.array([t[3] for t in tr])
        if len(tr) > 6:
            C = ndi.gaussian_filter1d(C, 1.0, axis=0, mode="nearest")
            R = ndi.gaussian_filter1d(R, 1.0, axis=0, mode="nearest")
        dz = np.abs(np.diff(rows))
        dr = np.sqrt(np.mean(np.diff(R, axis=0) ** 2, axis=1) + np.sum(np.diff(C, axis=0) ** 2, axis=1))
        s_arc = np.concatenate([[0.0], np.cumsum(np.hypot(dz, dr))])
        perim = 2 * math.pi * float(R.mean(axis=1).max())
        edge_px = (edge_mm / (mm_px * g)) if edge_mm else max(perim / segments, 1.0)
        n_r = max(3, int(round(s_arc[-1] / edge_px)))
        picks = np.interp(np.linspace(0, s_arc[-1], n_r + 1), s_arc, np.arange(len(tr)))
        sections = []
        for pk in picks:
            i0f = int(math.floor(pk))
            i1f = min(i0f + 1, len(tr) - 1)
            f = pk - i0f
            row = rows[i0f] * (1 - f) + rows[i1f] * f
            cx, cy = C[i0f] * (1 - f) + C[i1f] * f
            rad = R[i0f] * (1 - f) + R[i1f] * f
            ring = []
            for j in range(segments):
                xi = cx + rad[j] * dirs[j, 0]
                yi = cy + rad[j] * dirs[j, 1]
                X = x0 + (xi - 2) * g
                Y = y0 + (yi - 2) * g
                Z = hc - 1 - (row - 2)
                ring.append([round(float(X * mm_px + shift[0]), 3), round(float(Y * mm_px + shift[1]), 3),
                             round(float(Z * mm_px + shift[2]), 3)])
            sections.append({"points": ring})
        starts_on_base = abs(rows[0] - r_bot) < 1.5
        top_dome = 0.5 * mm_px                                     # the last row is the piece's end
        parts.append({"name": "body" if ti == 0 else "part_%02d" % ti, "op": "loft",
                      "cap_start": "quad", "cap_end": "quad",
                      "dome_start": 0.0 if starts_on_base else 0.5 * mm_px,
                      "dome_end": round(float(top_dome), 3), "sections": sections})
    return {"format": "s3d-qmesh/1", "name": name or nm.replace("_hull", ""), "units": "mm",
            "source": {"route": "views", "sheet": sheet, "images": images, "views": n_views,
                       "hull": work, "hull_info": {k: info[k] for k in ("angles_deg", "order", "iou", "size_mm")}},
            "parts": parts}


def main(argv=None):
    ap = argparse.ArgumentParser(description="Image(s) + real size -> clean closed quad mesh recipe.")
    sub = ap.add_subparsers(dest="route", required=True)
    s1 = sub.add_parser("sign", help="flat outline -> extrude (letters, logos, signs)")
    s1.add_argument("image")
    s1.add_argument("--height-mm", type=float, default=0.0)
    s1.add_argument("--width-mm", type=float, default=0.0)
    s1.add_argument("--thickness-mm", type=float, default=20.0)
    s1.add_argument("--edge-mm", type=float, default=0.0, help="target quad size (default size/120)")
    s1.add_argument("--tol-mm", type=float, default=0.0, help="outline tolerance (default ~0.6 px)")
    s2 = sub.add_parser("revolve", help="turned object (front view) -> revolve")
    s2.add_argument("image")
    s2.add_argument("--height-mm", type=float, required=True)
    s2.add_argument("--segments", type=int, default=48)
    s3 = sub.add_parser("views", help="2/4/8 views sheet -> hull -> ring lofts")
    s3.add_argument("sheet", nargs="?")
    s3.add_argument("--images", nargs="+")
    s3.add_argument("--views", type=int, default=4)
    s3.add_argument("--height-mm", type=float, required=True)
    s3.add_argument("--segments", type=int, default=48)
    s3.add_argument("--edge-mm", type=float, default=0.0)
    s3.add_argument("--hull-args", default="", help='extra views_to_3d options, e.g. "--round 2.5"')
    for s in (s1, s2, s3):
        s.add_argument("--name", default=None)
        s.add_argument("--out", default="", help="folder for the recipe and the build")
        s.add_argument("--build", action="store_true", help="also build OBJ / STL / report / preview")
    a = ap.parse_args(argv)
    src = getattr(a, "image", None) or getattr(a, "sheet", None) or (a.images[0] if getattr(a, "images", None) else "")
    out = a.out or os.path.splitext(src)[0] + "_qmesh"
    os.makedirs(out, exist_ok=True)
    if a.route == "sign":
        rec = sign_recipe(a.image, a.height_mm, a.width_mm, a.thickness_mm, a.edge_mm, a.tol_mm, a.name)
    elif a.route == "revolve":
        rec = revolve_recipe(a.image, a.height_mm, a.segments, name=a.name)
    else:
        rec = views_recipe(a.sheet, a.views, a.height_mm, a.segments, a.edge_mm,
                           a.hull_args.split() if a.hull_args else [], a.name,
                           work=os.path.join(out, "hull"), images=a.images)
    rpath = os.path.join(out, rec["name"] + "_recipe.json")
    json.dump(rec, open(rpath, "w"), indent=1)
    print("recipe: %s (%d parts)" % (rpath, len(rec["parts"])))
    if a.build:
        import qmesh_build
        qmesh_build.main([rpath, "--out", out])
    return rpath


if __name__ == "__main__":
    main()
