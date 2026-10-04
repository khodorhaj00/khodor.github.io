"""Tests for image-to-3d/photo3d (photo -> AI 3D -> Rhino).
Run: python test_photo3d.py   (needs numpy; trimesh for the cross-check)

1 glTF reader: GLB written by trimesh (scene with node transforms) matches trimesh;
  hand-built GLB with every awkward case (interleaved buffer, uint8/uint16/uint32
  indices, TRS + nested nodes, quantized int16 positions, triangle strip, no indices,
  sparse accessor) matches numpy; .gltf with data-URI and external .bin; Draco refused
2 OBJ reader keeps quads, handles v/vt/vn and negative indices
3 fal payloads for every preset (single and multi-view) and the result-link finder
4 fal queue protocol against a local mock server: submit -> poll -> result -> download,
  the key header, data-URI photos, and a 422 error that shows the server's message
5 cloud helper: a stand-in AI file (Y up, ~1 unit, split seam, loose speck) is checked into
  a closed Z-up model in mm that matches the truth; a 4-view sheet is prepped at one scale
6 the Rhino script parses as Python 2.7, is ASCII, and imports without Rhino
"""
import base64
import json
import math
import os
import struct
import sys
import tempfile
import threading
from http.server import BaseHTTPRequestHandler, HTTPServer

import cv2
import numpy as np

HERE = os.path.dirname(os.path.abspath(__file__))
P3D = os.path.join(HERE, "..", "photo3d")
sys.path.insert(0, P3D)
import s3d_photo_to_rhino as R  # noqa: E402  (Rhino modules are optional at import)

TMP = tempfile.mkdtemp(prefix="photo3d_test_")


def world_points(parts):
    """Apply each part's 4x4 matrix -> (N, 3) array, plus total triangle count."""
    pts, nf = [], 0
    for p in parts:
        v = np.asarray(p["verts"], float)
        M = np.asarray(p["matrix"], float).reshape(4, 4)
        pts.append(v @ M[:3, :3].T + M[:3, 3])
        nf += len(p["faces"])
    return np.concatenate(pts), nf


# ------------------------------------------------------------------ 1a trimesh GLB
try:
    import trimesh
except ImportError:
    trimesh = None
if trimesh is not None:
    scene = trimesh.Scene()
    scene.add_geometry(trimesh.creation.icosphere(subdivisions=3, radius=0.4), node_name="ball",
                       transform=trimesh.transformations.translation_matrix([0.2, 0.9, -0.1]))
    rot = trimesh.transformations.rotation_matrix(math.radians(30), [0, 1, 0])
    rot[:3, 3] = [-0.5, 0.25, 0.3]
    scene.add_geometry(trimesh.creation.box(extents=[0.3, 0.5, 0.2]), node_name="box", transform=rot)
    glb = os.path.join(TMP, "scene.glb")
    scene.export(glb)
    parts = R.read_gltf(glb)
    ours, nf = world_points(parts)
    ref = trimesh.load(glb, force="scene").to_geometry()
    assert nf == len(ref.faces), (nf, len(ref.faces))
    a = np.sort(np.round(ours, 5).view("f8,f8,f8"), axis=0)
    b = np.sort(np.round(np.asarray(ref.vertices), 5).view("f8,f8,f8"), axis=0)
    assert a.shape == b.shape and np.allclose(a.view("f8"), b.view("f8"), atol=1e-5)
    print("1a GLB from trimesh (2 nodes with transforms): %d faces, vertices match trimesh" % nf)
else:
    print("1a skipped (no trimesh)")


# ------------------------------------------------------------------ 1b hand-built GLB
def pad4(b, fill=b"\x00"):
    return b + fill * ((4 - len(b) % 4) % 4)


class GltfBuilder(object):
    def __init__(self):
        self.bin = b""
        self.js = {"asset": {"version": "2.0"}, "buffers": [], "bufferViews": [], "accessors": [],
                   "meshes": [], "nodes": [], "scenes": [{"nodes": []}], "scene": 0}

    def view(self, data, stride=None):
        self.bin = pad4(self.bin)
        bv = {"buffer": 0, "byteOffset": len(self.bin), "byteLength": len(data)}
        if stride:
            bv["byteStride"] = stride
        self.bin += data
        self.js["bufferViews"].append(bv)
        return len(self.js["bufferViews"]) - 1

    def accessor(self, bv, ctype, count, typ, offset=0, **kw):
        acc = {"bufferView": bv, "componentType": ctype, "count": count, "type": typ, "byteOffset": offset}
        acc.update(kw)
        self.js["accessors"].append(acc)
        return len(self.js["accessors"]) - 1

    def mesh(self, prims):
        self.js["meshes"].append({"primitives": prims})
        return len(self.js["meshes"]) - 1

    def glb(self, path):
        self.js["buffers"] = [{"byteLength": len(pad4(self.bin))}]
        j = pad4(json.dumps(self.js).encode(), b" ")
        b = pad4(self.bin)
        with open(path, "wb") as fh:
            fh.write(struct.pack("<4sII", b"glTF", 2, 12 + 8 + len(j) + 8 + len(b)))
            fh.write(struct.pack("<II", len(j), 0x4E4F534A) + j)
            fh.write(struct.pack("<II", len(b), 0x004E4942) + b)


def trs(t=(0, 0, 0), q=(0, 0, 0, 1), s=(1, 1, 1)):
    x, y, z, w = q
    Rm = np.array([[1 - 2 * (y * y + z * z), 2 * (x * y - z * w), 2 * (x * z + y * w)],
                   [2 * (x * y + z * w), 1 - 2 * (x * x + z * z), 2 * (y * z - x * w)],
                   [2 * (x * z - y * w), 2 * (y * z + x * w), 1 - 2 * (x * x + y * y)]])
    M = np.eye(4)
    M[:3, :3] = Rm * np.asarray(s)
    M[:3, 3] = t
    return M


g = GltfBuilder()
cube = np.array([[0, 0, 0], [1, 0, 0], [1, 1, 0], [0, 1, 0], [0, 0, 1], [1, 0, 1], [1, 1, 1], [0, 1, 1]], float)
cube_tris = np.array([[0, 2, 1], [0, 3, 2], [4, 5, 6], [4, 6, 7], [0, 1, 5], [0, 5, 4],
                      [1, 2, 6], [1, 6, 5], [2, 3, 7], [2, 7, 6], [3, 0, 4], [3, 4, 7]])
# A: interleaved POSITION + NORMAL (stride 24), uint16 indices
inter = b"".join(struct.pack("<3f3f", *(list(p) + [0, 0, 1])) for p in cube)
bvA = g.view(inter, stride=24)
posA = g.accessor(bvA, 5126, 8, "VEC3", 0, min=[0, 0, 0], max=[1, 1, 1])
nrmA = g.accessor(bvA, 5126, 8, "VEC3", 12)
idxA = g.accessor(g.view(struct.pack("<36H", *cube_tris.ravel())), 5123, 36, "SCALAR")
# B: quantized int16 normalized positions (stride 8 = 6 bytes + 2 padding), uint8 indices
q16 = np.round(cube * 32767).astype(int)
bvB = g.view(b"".join(struct.pack("<3hxx", *p) for p in q16), stride=8)
posB = g.accessor(bvB, 5122, 8, "VEC3", 0, normalized=True)
idxB = g.accessor(g.view(struct.pack("<36B", *cube_tris.ravel())), 5121, 36, "SCALAR")
# C: triangle strip, no indices
strip = np.array([[0, 0, 0], [0, 1, 0], [1, 0, 0], [1, 1, 0], [2, 0, 0]], float)
posC = g.accessor(g.view(struct.pack("<15f", *strip.ravel())), 5126, 5, "VEC3")
# D: uint32 indices + sparse accessor moving vertices 1 and 6
bvD = g.view(struct.pack("<24f", *cube.ravel()))
sp_idx = g.view(struct.pack("<2H", 1, 6))
sp_val = g.view(struct.pack("<6f", 5, 0, 0, 5, 5, 5))
posD = g.accessor(bvD, 5126, 8, "VEC3", sparse={"count": 2,
                                                 "indices": {"bufferView": sp_idx, "componentType": 5123},
                                                 "values": {"bufferView": sp_val}})
idxD = g.accessor(g.view(struct.pack("<36I", *cube_tris.ravel())), 5125, 36, "SCALAR")
mA = g.mesh([{"attributes": {"POSITION": posA, "NORMAL": nrmA}, "indices": idxA}])
mB = g.mesh([{"attributes": {"POSITION": posB}, "indices": idxB}])
mC = g.mesh([{"attributes": {"POSITION": posC}, "mode": 5}])
mD = g.mesh([{"attributes": {"POSITION": posD}, "indices": idxD}])
q45 = (0, math.sin(math.radians(22.5)), 0, math.cos(math.radians(22.5)))       # 45 deg about Y
g.js["nodes"] = [
    {"mesh": mA, "translation": [10, 0, 0], "rotation": list(q45), "scale": [2, 2, 2], "children": [1]},
    {"mesh": mB, "translation": [0, 3, 0], "scale": [0.5, 0.5, 0.5]},                # child of 0
    {"mesh": mC, "matrix": list(trs(t=(0, 0, -4)).T.ravel())},                          # column-major
    {"mesh": mD},
]
g.js["scenes"][0]["nodes"] = [0, 2, 3]
hand = os.path.join(TMP, "hand.glb")
g.glb(hand)
parts = R.read_gltf(hand)
assert len(parts) == 4, len(parts)
byname = dict((p["name"].split("_")[0], p) for p in parts)
M0 = trs((10, 0, 0), q45, (2, 2, 2))
M1 = M0 @ trs((0, 3, 0), s=(0.5, 0.5, 0.5))
cases = {"mesh0": (cube, M0, 12), "mesh1": (cube, M1, 12), "mesh2": (strip, trs((0, 0, -4)), 3)}
moved = cube.copy()
moved[1] = (5, 0, 0)
moved[6] = (5, 5, 5)
cases["mesh3"] = (moved, np.eye(4), 12)
for name, (verts, M, ntri) in cases.items():
    p = byname[name]
    got, nf = world_points([p])
    want = verts @ M[:3, :3].T + M[:3, 3]
    tol = 1e-4 if name == "mesh1" else 1e-9                 # int16 quantization
    assert nf == ntri and np.allclose(got, want, atol=tol), (name, nf, np.abs(got - want).max())
strip_faces = byname["mesh2"]["faces"]
assert strip_faces == [(0, 1, 2), (2, 1, 3), (2, 3, 4)], strip_faces
print("1b hand-built GLB: interleaved, uint8/16/32 indices, TRS + child node, int16 quantized, "
      "strip, sparse - all match numpy")

# 1c .gltf with a data-URI buffer, and with an external .bin
js = dict(g.js)
js["buffers"] = [{"byteLength": len(pad4(g.bin)),
                  "uri": "data:application/octet-stream;base64," + base64.b64encode(pad4(g.bin)).decode()}]
gltf_a = os.path.join(TMP, "embedded.gltf")
json.dump(js, open(gltf_a, "w"))
js2 = dict(g.js)
js2["buffers"] = [{"byteLength": len(pad4(g.bin)), "uri": "hand%20data.bin"}]
open(os.path.join(TMP, "hand data.bin"), "wb").write(pad4(g.bin))
gltf_b = os.path.join(TMP, "external.gltf")
json.dump(js2, open(gltf_b, "w"))
for f in (gltf_a, gltf_b):
    a, na = world_points(R.read_gltf(f))
    b, nb = world_points(parts)
    assert na == nb and np.allclose(a, b)
# Draco is refused with a clear message
gd = GltfBuilder()
gd.js = json.loads(json.dumps(g.js))
gd.bin = g.bin
gd.js["extensionsUsed"] = ["KHR_draco_mesh_compression"]
draco = os.path.join(TMP, "draco.glb")
gd.glb(draco)
try:
    R.read_gltf(draco)
    raise AssertionError("Draco GLB should be refused")
except R.ModelFileError as e:
    assert "compressed" in str(e)
print("1c .gltf with data URI and external .bin match the GLB; Draco GLB refused with a message")

# ------------------------------------------------------------------ 2 OBJ
obj = os.path.join(TMP, "quads.obj")
with open(obj, "w") as fh:
    fh.write("# test\nv 0 0 0\nv 1 0 0\nv 1 1 0\nv 0 1 0\nv 0 0 1\nvt 0 0\nvn 0 0 1\n"
             "f 1/1/1 2/1/1 3/1/1 4/1/1\nf -5 -4 -1\nf 1//1 2//1 5//1 4//1 3//1\n")
p = R.read_obj(obj)[0]
assert p["faces"] == [(0, 1, 2, 3), (0, 1, 4), (0, 1, 4, 3, 2)], p["faces"]
assert len(p["verts"]) == 5 and p["matrix"] == R._IDENT
print("2 OBJ: quad kept, negative indices, v/vt/vn, n-gon kept for fanning")

# ------------------------------------------------------------------ 3 payloads + links
photos1 = {"front": "data:image/jpeg;base64,AAA"}
photos4 = {"front": "F", "back": "B", "left": "L", "right": "Rt"}
app, body = R.build_payload(R.PRESETS["hunyuan"], photos1)
assert app == "fal-ai/hunyuan3d-v3/image-to-3d" and body == {"input_image_url": photos1["front"],
                                                              "enable_geometry": True}
app, body = R.build_payload(R.PRESETS["hunyuan"], photos4, {"face_count": 300000})
assert body["back_image_url"] == "B" and body["right_image_url"] == "Rt" and body["face_count"] == 300000
app, body = R.build_payload(R.PRESETS["tripo"], photos4)
assert app == "tripo3d/h3.1/multiview-to-3d" and body["left_image_url"] == "L" and body["texture"] is False
app, body = R.build_payload(R.PRESETS["tripo-quad"], photos1)
assert app == "tripo3d/h3.1/image-to-3d" and body["quad"] is True and body["image_url"] == photos1["front"]
app, body = R.build_payload(R.PRESETS["meshy"], {"front": "F", "back": "B"})
assert app == "fal-ai/meshy/v6/multi-image-to-3d" and body["image_urls"] == ["F", "B"]
assert body["topology"] == "quad"
try:
    R.build_payload({"app": "x/y", "views": {"front": "image_url"}, "name": "custom"}, photos4)
    raise AssertionError("unsupported views must be refused")
except R.ApiError as e:
    assert "does not take" in str(e)
hy = {"model_glb": {"url": "https://v3.fal.media/files/a/model.glb", "content_type": "model/gltf-binary"},
      "model_urls": {"glb": {"url": "https://v3.fal.media/files/a/model.glb"},
                     "obj": {"url": "https://v3.fal.media/files/a/model.obj"}}, "seed": 1}
assert R.choose_model_url(R.find_model_urls(hy)) == (".glb", "https://v3.fal.media/files/a/model.glb")
tq = {"model_mesh": {"url": "https://x/fal/abc.fbx?sig=1"}, "rendered_image": {"url": "https://x/p.webp"},
      "pbr_model": {"url": "https://x/fal/abc_pbr.glb"}}
assert R.choose_model_url(R.find_model_urls(tq), ".fbx")[0] == ".fbx"
assert R.choose_model_url(R.find_model_urls(tq))[0] == ".glb"
odd = {"result": [{"file": {"url": "https://cdn/x/download", "file_name": "thing.zip"}}],
       "link": "https://cdn/y/model.obj"}
assert R.choose_model_url(R.find_model_urls(odd)) == (".obj", "https://cdn/y/model.obj")
del odd["link"]
assert R.choose_model_url(R.find_model_urls(odd)) == (".zip", "https://cdn/x/download")
assert R.find_model_urls({"images": [{"url": "https://cdn/a.png"}]}) == []
assert R.parse_extra(' {"face_limit": 20000} ') == {"face_limit": 20000} and R.parse_extra("") is None
print("3 payloads: hunyuan single + 4 views, tripo multiview, tripo quad, meshy list field, "
      "bad views refused; link finder picks GLB / FBX / OBJ correctly")

# ------------------------------------------------------------------ 4 fal protocol (mock server)
STATE = {"polls": 0, "body": None, "auth": None}
GLB_BYTES = open(hand, "rb").read()


class Fal(BaseHTTPRequestHandler):
    def log_message(self, *a):
        pass

    def _send(self, code, obj=None, raw=None, ctype="application/json"):
        data = raw if raw is not None else json.dumps(obj).encode()
        self.send_response(code)
        self.send_header("Content-Type", ctype)
        self.send_header("Content-Length", str(len(data)))
        self.end_headers()
        self.wfile.write(data)

    def do_POST(self):
        n = int(self.headers.get("Content-Length", 0))
        STATE["body"] = json.loads(self.rfile.read(n))
        STATE["auth"] = self.headers.get("Authorization")
        if self.path.startswith("/bad/"):
            return self._send(422, {"detail": [{"loc": ["body", "image_url"], "msg": "field required"}]})
        if self.path.startswith("/strict/"):                # wants image_url, forbids extra options
            errs = [] if "image_url" in STATE["body"] else [
                {"type": "missing", "loc": ["body", "image_url"], "msg": "Field required"}]
            errs += [{"type": "extra_forbidden", "loc": ["body", k], "msg": "Extra inputs are not permitted"}
                     for k in STATE["body"] if k != "image_url"]
            if errs:
                return self._send(422, {"detail": errs})
        base = "http://127.0.0.1:%d/fal-ai/hunyuan3d-v3/requests/r123" % PORT
        self._send(200, {"request_id": "r123", "status_url": base + "/status", "response_url": base,
                         "cancel_url": base + "/cancel"})

    def do_GET(self):
        if self.path.endswith("/status"):
            STATE["polls"] += 1
            s = ["IN_QUEUE", "IN_PROGRESS", "COMPLETED"][min(STATE["polls"] - 1, 2)]
            return self._send(200, {"status": s, "queue_position": 2 if s == "IN_QUEUE" else None,
                                    "logs": []})
        if self.path.endswith("/requests/r123"):
            return self._send(200, {"model_glb": {"url": "http://127.0.0.1:%d/files/m.glb" % PORT},
                                    "thumbnail": {"url": "http://127.0.0.1:%d/files/t.png" % PORT}})
        if self.path == "/files/m.glb":
            return self._send(200, raw=GLB_BYTES, ctype="model/gltf-binary")
        self._send(404, {"detail": "not found"})


srv = HTTPServer(("127.0.0.1", 0), Fal)
PORT = srv.server_address[1]
threading.Thread(target=srv.serve_forever, daemon=True).start()
R.FAL_QUEUE = "http://127.0.0.1:%d/" % PORT
photo = os.path.join(TMP, "photo.png")
open(photo, "wb").write(b"\x89PNG\r\n\x1a\nfake")
uri = R.image_data_uri(photo)
assert uri.startswith("data:image/png;base64,")
lines = []
result, rid = R.fal_generate(R.PRESETS["hunyuan"], {"front": uri}, "test-key", None, 1.0,
                             log=lines.append, wait=lambda s: None)
assert rid == "r123" and STATE["polls"] == 3 and STATE["auth"] == "Key test-key"
assert STATE["body"]["input_image_url"] == uri and STATE["body"]["enable_geometry"] is True
ext, url = R.choose_model_url(R.find_model_urls(result))
out = R.http_download(url, os.path.join(TMP, "dl" + ext))
a, _ = world_points(R.read_gltf(out))
b, _ = world_points(parts)
assert np.allclose(a, b)
try:
    R.fal_generate({"app": "bad/model", "views": {"front": "img"}}, {"front": uri}, "k", None, 1.0,
                   log=lines.append, wait=lambda s: None)
    raise AssertionError("422 must raise")
except R.ApiError as e:
    assert "field required" in str(e) and "image_url" in str(e)
# a wrong image field + an option the endpoint forbids -> one automatic retry fixes both
strict = {"app": "strict/model", "views": {"front": "input_image_url"}, "extra": {"enable_geometry": True}}
try:
    R.fal_generate(strict, {"front": uri}, "k", None, 1.0, log=lines.append, wait=lambda s: None)
    raise AssertionError("strict endpoint must reject the first try")
except R.ApiError as e:
    assert R.fal_missing_fields(str(e)) == ["image_url"], R.fal_missing_fields(str(e))
    fix = R.retry_preset(strict, str(e), {"front": uri})
STATE["polls"] = 0
result, rid = R.fal_generate(fix["preset"], {"front": uri}, "k", None, 1.0, log=lines.append,
                             wait=lambda s: None)
assert STATE["body"] == {"image_url": uri} and rid == "r123" and "image_url" in fix["why"]
assert R.retry_preset(strict, "GET x\nHTTP Error 500: boom", {"front": uri}) is None
lst = R.retry_preset({"app": "a/b", "views": {"front": "image"}, "extra": {}},
                     'POST x\nHTTP Error 422\n{"detail": [{"type": "missing", "loc": ["body", "image_urls"]}]}',
                     {"front": uri})
assert R.build_payload(lst["preset"], {"front": uri})[1] == {"image_urls": [uri]}
# the cloud one-command test: photo -> fal -> model file -> check
sys.path.insert(0, os.path.join(HERE, "..", "views_to_3d"))
import p3d_cloud as PC  # noqa: E402
os.environ["FAL_KEY"] = "env-key"
jpg = os.path.join(TMP, "front.jpg")
cv2.imwrite(jpg, np.full((3000, 2000, 3), 200, np.uint8))
STATE["polls"] = 0
info = PC.ai({"front": jpg}, os.path.join(TMP, "ai_out"), "hunyuan", 100.0, log=lines.append,
             wait=lambda s: None)
sent = STATE["body"]["input_image_url"]
im = cv2.imdecode(np.frombuffer(base64.b64decode(sent.split(",", 1)[1]), np.uint8), cv2.IMREAD_COLOR)
assert sent.startswith("data:image/jpeg;base64,") and im.shape[:2] == (2048, 1365), im.shape
assert STATE["auth"] == "Key env-key" and info["request_id"] == "r123" and os.path.isfile(info["model_file"])
assert abs(info["size_mm"][2] - 100.0) < 1e-6 and os.path.isfile(info["views_png"])
srv.shutdown()
print("4 fal protocol: submit -> IN_QUEUE -> IN_PROGRESS -> COMPLETED -> result -> GLB download; "
      "key header + data-URI photo sent; 422 shows the server's message; a 422 for a wrong image "
      "field / forbidden option is fixed by one automatic retry; cloud 'ai' command: photo shrunk to "
      "2048 px, sent, model downloaded and checked")

# ------------------------------------------------------------------ 5 cloud helper: check + prep
sys.path.insert(0, os.path.join(HERE, "..", "views_to_3d"))
import p3d_cloud as PC  # noqa: E402
import selftest as ST  # noqa: E402
if trimesh is not None:
    from skimage import measure
    step = 8.0
    xs = np.arange(-260, 261, step)
    zs = np.arange(-10, 900, step)
    Zg, Yg, Xg = np.meshgrid(zs, xs, xs, indexing="ij")
    pg = np.stack([Xg, Yg, Zg], -1)
    d = ST.sd_ellipsoid(pg, np.array([0, 0, 230.0]), np.array([230, 200, 230.0]))
    d = np.minimum(d, ST.sd_ellipsoid(pg, np.array([0, 0, 560.0]), np.array([160, 150, 160.0])))
    d = np.minimum(d, ST.sd_ellipsoid(pg, np.array([0, 0, 790.0]), np.array([100, 95, 100.0])))
    d = np.minimum(d, ST.sd_capsule(pg, np.array([0, -90, 790.0]), np.array([0, -170, 780.0]), 18))
    v, f, _n, _ = measure.marching_cubes(d.astype(np.float32), 0.0)
    Vt, Ft = ST.outward(np.stack([xs[0] + v[:, 2] * step, xs[0] + v[:, 1] * step, zs[0] + v[:, 0] * step], 1), f)
    # what a generator sends: Y up, front +Z, ~1 unit, split seam, a loose speck
    G = np.stack([Vt[:, 0], Vt[:, 2], -Vt[:, 1]], 1) / 900.0
    Fa = np.asarray(Ft)
    sel = G[Fa].mean(1)[:, 0] > 0
    dup = np.unique(Fa[sel])
    remap = -np.ones(len(G), int)
    remap[dup] = len(G) + np.arange(len(dup))
    G2 = np.concatenate([G, G[dup]])
    F2 = Fa.copy()
    F2[sel] = remap[Fa[sel]]
    speck = trimesh.creation.icosphere(1, 0.01)
    speck.apply_translation([0.6, 1.2, 0.0])                 # above the head: would skew the height
    ai_glb = os.path.join(TMP, "standin_ai.glb")
    trimesh.Scene([trimesh.Trimesh(G2, F2, process=False), speck]).export(ai_glb)
    info = PC.check(ai_glb, os.path.join(TMP, "checked"), height_mm=900.0)
    assert info["closed"] and info["pieces"] == 1 and info["dropped_loose_bits"] == 1, info
    true_h = Vt[:, 2].max() - Vt[:, 2].min()
    k = 900.0 / true_h
    want = (Vt.max(0) - Vt.min(0)) * k
    assert np.allclose(info["size_mm"], want, atol=1.0), (info["size_mm"], want)
    Vs = Vt * k
    lo, hi = Vs.min(0), Vs.max(0)
    Vs -= np.array([0.5 * (lo[0] + hi[0]), 0.5 * (lo[1] + hi[1]), lo[2]])
    got = np.array([[float(t) for t in ln.split()[1:4]] for ln in open(info["obj"]) if ln.startswith("v ")])
    from scipy.spatial import cKDTree                          # GLB stores float32: compare by distance
    gap = max(cKDTree(Vs).query(got)[0].max(), cKDTree(got).query(Vs)[0].max())
    assert gap < 0.02, gap                                     # every vertex within 0.02 mm both ways
    head = got[got[:, 2] > 0.85 * 900]
    assert head[:, 1].min() < -0.15 * 900                    # the nose points to -Y (front)
    print("5 cloud check: Y-up GLB with split seam + loose speck -> closed, speck dropped, Z up, "
          "front -Y, size %s mm, every vertex within 0.02 mm of the truth" % info["size_mm"])
    sheet = ST.make_sheet(Vt, Ft, [0, 90, 180, 270], ["FRONT", "RIGHT", "BACK", "LEFT"], 2, (255, 255, 255),
                          os.path.join(TMP, "sheet.png"), px=300)
    outs = PC.prep([sheet], os.path.join(TMP, "prep"), sheet=4, names=["front", "right", "back", "left"],
                   size=512)
    assert [os.path.basename(o) for o in outs] == ["front.png", "right.png", "back.png", "left.png"]
    heights = []
    for o in outs:
        im = cv2.imread(o)
        assert im.shape == (512, 512, 3) and (im[:5] > 250).all() and (im[:, :5] > 250).all()
        rows = np.nonzero((im < 200).any(2).any(1))[0]
        heights.append(rows[-1] - rows[0])
    assert max(heights) - min(heights) <= 4, heights           # one scale for every view
    print("5 cloud prep: 4-view sheet -> front/right/back/left, 512 px squares on white, same scale")
else:
    print("5 skipped (no trimesh)")

# ------------------------------------------------------------------ 6 Rhino script checks
from lib2to3 import pygram, pytree  # noqa: E402
from lib2to3.pgen2 import driver  # noqa: E402
src = open(os.path.join(P3D, "s3d_photo_to_rhino.py")).read()
driver.Driver(pygram.python_grammar_no_print_statement, convert=pytree.convert).parse_string(src + "\n")
assert all(ord(ch) < 128 for ch in src)
assert src.startswith("#! python2")
print("6 Rhino script: Python 2.7 grammar, ASCII, '#! python2' first line, imports without Rhino")
print("ALL PHOTO3D TESTS PASSED")
