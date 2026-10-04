"""End-to-end tests for image-to-3d/qmesh (clean closed quad meshes).
Run: python test_qmesh.py   (needs numpy scipy opencv-python-headless scikit-image)

1 kernel: every builder gives a closed, manifold, oriented, single-shell mesh with the
  right genus and volume; quads 100 % except planar caps of extrusions
2 example recipes build clean
3 image routes on generated pictures: sign (letters with holes) and vase (revolve),
  each with an outline match (IoU) of the mesh against the input picture
4 views route on a generated 4-view sheet of a known object, IoU against its views
5 Rhino script: Python 2.7 grammar, ASCII, and its OBJ reader matches the cloud build
"""
import importlib.util
import json
import math
import os
import sys
import tempfile
import types
import warnings
from unittest import mock

import cv2
import numpy as np

HERE = os.path.dirname(os.path.abspath(__file__))
QM = os.path.join(HERE, "..", "qmesh")
sys.path.insert(0, QM)
sys.path.insert(0, os.path.join(HERE, "..", "views_to_3d"))
import s3d_qmesh as Q  # noqa: E402
import qmesh_image as QI  # noqa: E402

TMP = tempfile.mkdtemp(prefix="qmesh_test_")


def clean(m, genus=0, quads_min=100.0):
    c = Q.check(m)
    assert c["closed"] and c["nonmanifold_edges"] == 0 and c["oriented"], c
    assert c["shells"] == 1 and c["genus"] == genus and c["volume"] > 0, c
    assert c["quad_pct"] >= quads_min, c
    return c


# ------------------------------------------------------------------ 1 kernel
c = clean(Q.box((100, 60, 40), (4, 3, 2)))
assert abs(c["volume"] - 240000) < 1e-6
c = clean(Q.sphere(50, 8))
assert abs(c["volume"] / (4 / 3 * math.pi * 50 ** 3) - 1) < 0.02
clean(Q.cylinder(30, 100, 32, 4))
clean(Q.cone(40, 0, 80, 32, 6))
clean(Q.torus(60, 15), genus=1)
clean(Q.revolve([(0, 0), (60, 0), (70, 40), (50, 120), (30, 180), (45, 230), (0, 235)], 48))
clean(Q.loft([Q.ring_points(32, 40 + 10 * math.sin(z / 30.0), 30, z) for z in range(0, 201, 20)], dome_end=15))
sq = [(0, 0), (100, 0), (100, 60), (0, 60)]
hole = [(30, 20), (30, 40), (50, 40), (50, 20)]
c = clean(Q.extrude(sq, [hole], 20, edge=10), genus=1, quads_min=85)
assert abs(c["volume"] - (6000 - 400) * 20) < 1e-6
path = [(math.cos(t) * 80, math.sin(t) * 80, t * 10) for t in [i * 0.2 for i in range(40)]]
clean(Q.sweep([(x, y) for x, y, _ in Q.ring_points(16, 8, 8)], path))
c = clean(Q.catmull_clark(Q.box((100, 100, 100), (1, 1, 1)), 3))
assert c["faces"] == 6 * 4 ** 3
tri = Q.triangulate([(0, 0), (10, 0), (10, 10), (0, 10)], [[(3, 3), (3, 7), (7, 7), (7, 3)]])
assert len(tri) == 8, tri
print("1 kernel builders: closed, manifold, oriented, right genus and volume")

# ------------------------------------------------------------------ 2 example recipes
for ex in ("test_all_ops.json", "bench.json"):
    parts = Q.build_recipe(json.load(open(os.path.join(QM, "examples", ex))))
    for name, m in parts:
        g = 1 if name in ("ring", "plate") else 0
        clean(m, genus=g, quads_min=0 if m.name in ("plate", "plaque") else 100)
    print("2 %-18s %d parts clean" % (ex, len(parts)))


# ------------------------------------------------------------------ 3 image routes
def front_iou(parts, mask, k):
    """Rasterise the mesh seen from the front (X right, Z up) at the picture's scale."""
    rows = np.nonzero((mask > 0.5).any(1))[0]
    cols = np.nonzero((mask > 0.5).any(0))[0]
    ref = (mask[rows[0]:rows[-1] + 1, cols[0]:cols[-1] + 1] > 0.5).astype(np.uint8)
    img = np.zeros_like(ref)
    V = np.concatenate([np.asarray(m.v) for _n, m in parts])
    x0, z0 = V[:, 0].min(), V[:, 2].min()
    off = 0
    for _n, m in parts:
        P = np.asarray(m.v)
        X = (P[:, 0] - x0) / k
        Y = (ref.shape[0] - 1) - (P[:, 2] - z0) / k
        for f in m.f:
            poly = np.stack([X[list(f)], Y[list(f)]], 1)
            cv2.fillPoly(img, [np.round(poly * 16).astype(np.int32)], 1, cv2.LINE_8, 4)
        off += len(m.v)
    inter = (img & ref).sum()
    return inter / float((img | ref).sum())


im = np.full((420, 1500, 3), 255, np.uint8)
cv2.putText(im, "STYRO 3D", (40, 330), cv2.FONT_HERSHEY_DUPLEX, 7.5, (30, 30, 160), 28, cv2.LINE_AA)
sign_png = os.path.join(TMP, "sign.png")
cv2.imwrite(sign_png, im)
rec = QI.sign_recipe(sign_png, width_mm=2400, thickness_mm=80)
parts = Q.build_recipe(rec)
assert len(parts) == 7, len(parts)                     # S T Y R O 3 D
for n, m in parts:
    c = Q.check(m)
    assert c["closed"] and c["oriented"] and c["shells"] == 1 and c["quad_pct"] > 60, (n, c)
assert sorted(Q.check(m)["genus"] for _n, m in parts) == [0, 0, 0, 0, 1, 1, 1]   # R, O, D have holes
_img, mask = QI.full_mask(sign_png)
iou = front_iou(parts, mask, rec["source"]["mm_per_px"])
print("3 sign: 7 letters, holes in R O D, all closed; front outline IoU %.3f" % iou)
assert iou > 0.97, iou

H, W = 900, 600
im = np.full((H, W, 3), 210, np.uint8)
z = np.arange(80, 860)
t = (z - 80) / 780.0
r = 70 + 140 * np.sin(np.pi * (t * 0.9 + 0.05)) ** 1.5 - 60 * np.exp(-((t - 0.85) / 0.06) ** 2)
r[t > 0.93] = 95
pts = np.concatenate([np.stack([300 - r, 860 - (z - 80)], 1), np.stack([300 + r, 860 - (z - 80)], 1)[::-1]])
cv2.fillPoly(im, [pts.astype(np.int32)], (60, 90, 140), cv2.LINE_AA)
vase_png = os.path.join(TMP, "vase.png")
cv2.imwrite(vase_png, im)
rec = QI.revolve_recipe(vase_png, height_mm=800)
parts = Q.build_recipe(rec)
clean(parts[0][1])
_img, mask = QI.object_mask(vase_png)
iou = front_iou(parts, mask, rec["source"]["mm_per_px"])
print("3 vase: 100 %% quads, closed; front outline IoU %.3f" % iou)
assert iou > 0.97, iou

# ------------------------------------------------------------------ 4 views route on a known object
import selftest as ST  # noqa: E402  (views_to_3d/selftest.py: renderer + test shapes)


def snowman(step=6.0):
    xs = np.arange(-260, 261, step)
    ys = np.arange(-260, 261, step)
    zs = np.arange(-10, 900, step)
    Z, Y, X = np.meshgrid(zs, ys, xs, indexing="ij")
    p = np.stack([X, Y, Z], -1)
    d = ST.sd_ellipsoid(p, np.array([0, 0, 230.0]), np.array([230, 200, 230.0]))
    d = np.minimum(d, ST.sd_ellipsoid(p, np.array([0, 0, 560.0]), np.array([160, 150, 160.0])))
    d = np.minimum(d, ST.sd_ellipsoid(p, np.array([0, 0, 790.0]), np.array([100, 95, 100.0])))
    d = np.minimum(d, ST.sd_capsule(p, np.array([0, -90, 790.0]), np.array([0, -170, 780.0]), 18))   # nose (-Y)
    from skimage import measure
    v, f, _n, _ = measure.marching_cubes(d.astype(np.float32), 0.0)
    V = np.stack([xs[0] + v[:, 2] * step, ys[0] + v[:, 1] * step, zs[0] + v[:, 0] * step], 1)
    return ST.outward(V, f)


Vt, Ft = snowman()
sheet = ST.make_sheet(Vt, Ft, [0, 90, 180, 270], ["FRONT", "RIGHT", "BACK", "LEFT"], 2, (255, 255, 255),
                      os.path.join(TMP, "snowman_sheet.png"), px=360)
with warnings.catch_warnings():
    warnings.simplefilter("ignore")
    rec = QI.views_recipe(sheet, 4, 900.0, segments=48, work=os.path.join(TMP, "hull"))
parts = Q.build_recipe(rec)
body = parts[0][1]
c = clean(body)
hull_iou = rec["source"]["hull_info"]["iou"]
vol_true = None
rng = np.random.default_rng(0)
stl = os.path.join(TMP, "snow.stl")
Q.write_stl(parts, stl)
err = ST.error_vs_truth(Vt, Ft, stl, rng)
print("4 views (snowman, 4 views): %d parts, body %d quads closed; hull outline IoU %s; "
      "mean distance to the true shape %.1f / %.1f mm on 900 mm" % (
          len(parts), c["quads"], ", ".join("%.3f" % x for x in hull_iou), err["truth_to_model_mean"],
          err["model_to_truth_mean"]))
assert min(hull_iou) > 0.95 and err["truth_to_model_mean"] < 25 and err["model_to_truth_mean"] < 40

# ------------------------------------------------------------------ 5 Rhino script
from lib2to3 import pygram, pytree  # noqa: E402
from lib2to3.pgen2 import driver  # noqa: E402
drv = driver.Driver(pygram.python_grammar_no_print_statement, convert=pytree.convert)
for f in ("s3d_qmesh.py", "s3d_qmesh_rhino.py"):
    src = open(os.path.join(QM, f)).read()
    drv.parse_string(src + "\n")
    assert all(ord(ch) < 128 for ch in src), f


def stub(name, **kw):
    mod = types.ModuleType(name)
    mod.__dict__.update(kw)
    sys.modules[name] = mod
    return mod


rh = stub("Rhino")
rh.Geometry = stub("Rhino.Geometry")
stub("rhinoscriptsyntax")
stub("scriptcontext")
stub("System")
stub("System.Drawing", Color=mock.MagicMock())
spec = importlib.util.spec_from_file_location("rh_script", os.path.join(QM, "s3d_qmesh_rhino.py"))
R = importlib.util.module_from_spec(spec)
spec.loader.exec_module(R)
bench = Q.build_recipe(json.load(open(os.path.join(QM, "examples", "bench.json"))))
obj = os.path.join(TMP, "bench.obj")
Q.write_obj(bench, obj)
back = R.read_obj(obj)
assert [(n, len(m.v), len(m.f)) for n, m in back] == [(n, len(m.v), len(m.f)) for n, m in bench]
assert all(Q.check(m)["closed"] for _n, m in back)
print("5 Rhino script: Python 2.7 grammar + ASCII OK; OBJ round trip matches the cloud build")
print("ALL QMESH TESTS PASSED")
