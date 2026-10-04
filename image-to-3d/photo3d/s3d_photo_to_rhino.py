#! python2
# -*- coding: utf-8 -*-
"""
Styro3D | Photo -> 3D model -> Rhino
====================================
File    s3d_photo_to_rhino.py   v1.0
Rhino   7 (IronPython 2.7) and 8. The first line makes Rhino 8 run it in
        IronPython 2.7 too, so both versions run the same code.
Run     _RunPythonScript -> pick this file
        alias:  P3D  =  ! _-RunPythonScript "C:\\path\\s3d_photo_to_rhino.py"
Undo    one Ctrl+Z removes the whole run

SOURCE (asked first)
  AI    1-4 photos (front, back, left, right) -> AI image-to-3D on fal.ai with
        your FAL key -> the model lands here. About 1-3 min per model.
  URL   paste a model link: Higgsfield result from a Claude chat, Meshy,
        Tripo, Hunyuan3D, fal ... (GLB, OBJ, FBX, STL, PLY, 3MF or ZIP)
  File  a model file from any generator. GLB / glTF work in Rhino 7 too.
  Pick  meshes that are already in this model

THEN, ONE PASS
  weld UV seams -> Z up, front to -Y -> real size in mm -> drop loose bits
  and inner shells -> close holes -> QuadRemesh (clean quads) -> SubD ->
  NURBS polysurface with an IsSolid check.
  Layers S3D_Photo3D::Raw / Mesh / Quad / SubD / Polysurface.

FAL KEY (AI source only)
  fal.ai -> Dashboard -> API keys. The script reads the FAL_KEY environment
  variable, or %APPDATA%\\Styro3D\\fal_key.txt, or asks once and offers to save it.
"""
from __future__ import print_function, division

import base64
import json
import math
import os
import struct
import sys
import time
import traceback
import zipfile

try:                                    # Rhino; the pure helpers below run without it
    import Rhino
    import Rhino.Geometry as rg
    import rhinoscriptsyntax as rs
    import scriptcontext as sc
    import System
    from System.Collections.Generic import List
    from System.Drawing import Color
except ImportError:                     # tests / plain Python
    Rhino = rg = rs = sc = System = List = Color = None

try:
    from urllib import unquote          # Python 2 / IronPython
except ImportError:
    from urllib.parse import unquote    # Python 3

TITLE = "Styro3D Photo -> Rhino"
VERSION = "1.0"
PY3 = sys.version_info[0] >= 3
IRON = sys.platform == "cli"
FAL_QUEUE = "https://queue.fal.run/"
MODEL_EXTS = (".glb", ".gltf", ".fbx", ".obj", ".zip", ".stl", ".ply", ".3mf")
NATIVE_EXTS = (".fbx", ".stl", ".ply", ".3mf")       # imported by Rhino itself
MESH_FILTER = ("3D model (*.glb;*.gltf;*.obj;*.fbx;*.stl;*.ply;*.3mf;*.zip)|"
               "*.glb;*.gltf;*.obj;*.fbx;*.stl;*.ply;*.3mf;*.zip|All files (*.*)|*.*||")
PHOTO_FILTER = "Photo (*.jpg;*.jpeg;*.png;*.bmp)|*.jpg;*.jpeg;*.png;*.bmp||"
VIEWS = ("front", "back", "left", "right")
_STR = (str, type(u""))

# (key, label, default)
SPEC = [
    ("size_mm",   "Real size in mm (0 = keep file size)",                "1000"),
    ("size_axis", "That size is the: height / width / depth / longest",   "height"),
    ("up",        "File up axis: auto / y / z / x / -y / -z",              "auto"),
    ("turn",      "Turn about Z, degrees (front should face -Y)",          "0"),
    ("debris",    "Drop loose bits under % of faces",                      "1"),
    ("wrap",      "Rhino 8 ShrinkWrap if still open: auto / never",         "auto"),
    ("quads",     "QuadRemesh target quads (0 = skip)",                    "4000"),
    ("adaptive",  "QuadRemesh adaptive size 0-100",                        "50"),
    ("hard",      "Keep hard edges (y/n) - y for hard-surface parts",      "n"),
    ("symmetry",  "Symmetry: none / x (left-right) / y (front-back)",      "none"),
    ("output",    "Output: mesh / quad / subd / nurbs",                    "nurbs"),
]

AI_SPEC = [
    ("model",    "AI model: hunyuan / tripo / tripo-quad / meshy / custom", "hunyuan"),
    ("endpoint", "Custom fal endpoint id (model = custom only)",            ""),
    ("fields",   "Custom image fields, front,back,left,right (custom only)", "image_url"),
    ("extra",    "Extra JSON options (blank = preset defaults)",            ""),
    ("max_px",   "Shrink photos to max pixels",                             "2048"),
    ("timeout",  "Give up after minutes",                                   "15"),
]

# fal.ai endpoints. 'views' maps our view names to the endpoint's input fields;
# 'list_field' = one field that takes a list of images instead.
PRESETS = {
    "hunyuan": {
        "app": "fal-ai/hunyuan3d-v3/image-to-3d",
        "views": {"front": "input_image_url", "back": "back_image_url",
                  "left": "left_image_url", "right": "right_image_url"},
        "extra": {"enable_geometry": True},
        "note": "Tencent Hunyuan3D v3, geometry only (no texture), best detail",
    },
    "tripo": {
        "app": "tripo3d/h3.1/image-to-3d",
        "app_multi": "tripo3d/h3.1/multiview-to-3d",
        "views": {"front": "image_url"},
        "views_multi": {"front": "front_image_url", "back": "back_image_url",
                        "left": "left_image_url", "right": "right_image_url"},
        "extra": {"texture": False, "pbr": False, "geometry_quality": "detailed"},
        "note": "Tripo H3.1, geometry only, detailed",
    },
    "tripo-quad": {
        "app": "tripo3d/h3.1/image-to-3d",
        "app_multi": "tripo3d/h3.1/multiview-to-3d",
        "views": {"front": "image_url"},
        "views_multi": {"front": "front_image_url", "back": "back_image_url",
                        "left": "left_image_url", "right": "right_image_url"},
        "extra": {"texture": False, "pbr": False, "quad": True, "face_limit": 8000},
        "prefer": ".fbx",
        "note": "Tripo H3.1 quad mesh (FBX); QuadRemesh is skipped",
    },
    "meshy": {
        "app": "fal-ai/meshy/v6/image-to-3d",
        "app_multi": "fal-ai/meshy/v6/multi-image-to-3d",
        "views": {"front": "image_url"},
        "list_field_multi": "image_urls",
        "extra": {"should_texture": False, "topology": "quad", "target_polycount": 30000},
        "note": "Meshy 6, quad topology, no texture",
    },
}


class UserCancel(Exception):
    pass


class ApiError(Exception):
    pass


class ModelFileError(Exception):
    pass


# =============================================================================
# Pure helpers (no Rhino): glTF / OBJ readers, fal payloads, result parsing
# =============================================================================
_COMP = {5120: ("b", 1, 127.0), 5121: ("B", 1, 255.0), 5122: ("h", 2, 32767.0),
         5123: ("H", 2, 65535.0), 5125: ("I", 4, None), 5126: ("f", 4, None)}
_NCOMP = {"SCALAR": 1, "VEC2": 2, "VEC3": 3, "VEC4": 4, "MAT2": 4, "MAT3": 9, "MAT4": 16}
_IDENT = [1.0, 0.0, 0.0, 0.0, 0.0, 1.0, 0.0, 0.0, 0.0, 0.0, 1.0, 0.0, 0.0, 0.0, 0.0, 1.0]


def _mat_mul(a, b):
    """4x4 row-major product a * b."""
    out = [0.0] * 16
    for r in range(4):
        for c in range(4):
            out[r * 4 + c] = sum(a[r * 4 + k] * b[k * 4 + c] for k in range(4))
    return out


def node_matrix(node):
    """glTF node -> 4x4 row-major local matrix (matrix, or T * R * S)."""
    if "matrix" in node:
        m = [float(x) for x in node["matrix"]]          # column-major in glTF
        return [m[c * 4 + r] for r in range(4) for c in range(4)]
    tx, ty, tz = node.get("translation", (0.0, 0.0, 0.0))
    qx, qy, qz, qw = node.get("rotation", (0.0, 0.0, 0.0, 1.0))
    sx, sy, sz = node.get("scale", (1.0, 1.0, 1.0))
    r = [1 - 2 * (qy * qy + qz * qz), 2 * (qx * qy - qz * qw), 2 * (qx * qz + qy * qw),
         2 * (qx * qy + qz * qw), 1 - 2 * (qx * qx + qz * qz), 2 * (qy * qz - qx * qw),
         2 * (qx * qz - qy * qw), 2 * (qy * qz + qx * qw), 1 - 2 * (qx * qx + qy * qy)]
    return [r[0] * sx, r[1] * sy, r[2] * sz, tx,
            r[3] * sx, r[4] * sy, r[5] * sz, ty,
            r[6] * sx, r[7] * sy, r[8] * sz, tz,
            0.0, 0.0, 0.0, 1.0]


def _read_accessor(js, buffers, index):
    acc = js["accessors"][index]
    n = int(acc["count"])
    nc = _NCOMP[acc["type"]]
    fmt, size, norm = _COMP[acc["componentType"]]
    out = [0] * (n * nc)
    if "bufferView" in acc:
        bv = js["bufferViews"][acc["bufferView"]]
        buf = buffers[bv["buffer"]]
        base = int(bv.get("byteOffset", 0)) + int(acc.get("byteOffset", 0))
        elem = size * nc
        stride = int(bv.get("byteStride", 0) or elem)
        if stride == elem:
            out = list(struct.unpack_from("<%d%s" % (n * nc, fmt), buf, base))
        else:                                           # interleaved / padded
            f = "<%d%s" % (nc, fmt)
            out = []
            for i in range(n):
                out.extend(struct.unpack_from(f, buf, base + i * stride))
    sp = acc.get("sparse")
    if sp:
        k = int(sp["count"])
        iv, ivals = sp["indices"], sp["values"]
        ifmt, isize, _n = _COMP[iv["componentType"]]
        bvi = js["bufferViews"][iv["bufferView"]]
        idx = struct.unpack_from("<%d%s" % (k, ifmt), buffers[bvi["buffer"]],
                                 int(bvi.get("byteOffset", 0)) + int(iv.get("byteOffset", 0)))
        bvv = js["bufferViews"][ivals["bufferView"]]
        vals = struct.unpack_from("<%d%s" % (k * nc, fmt), buffers[bvv["buffer"]],
                                  int(bvv.get("byteOffset", 0)) + int(ivals.get("byteOffset", 0)))
        for j, ix in enumerate(idx):
            out[ix * nc:(ix + 1) * nc] = vals[j * nc:(j + 1) * nc]
    if acc.get("normalized") and norm:
        out = [max(v / norm, -1.0) for v in out]
    return out, nc


def _triangles(indices, mode):
    if mode == 4:
        return [(indices[i], indices[i + 1], indices[i + 2]) for i in range(0, len(indices) - 2, 3)]
    if mode == 5:                                       # strip
        tris = []
        for i in range(len(indices) - 2):
            a, b, c = indices[i], indices[i + 1], indices[i + 2]
            tris.append((a, b, c) if i % 2 == 0 else (b, a, c))
        return tris
    if mode == 6:                                       # fan
        return [(indices[0], indices[i], indices[i + 1]) for i in range(1, len(indices) - 1)]
    return []                                           # points / lines


def read_gltf(path):
    """GLB or glTF -> list of parts: {"name", "verts": [(x,y,z)], "faces": [(a,b,c)], "matrix"}.
    Vertices are in file units (metres, Y up); "matrix" is the node's 4x4 world matrix."""
    data = open(path, "rb").read()
    js, bin_chunk = None, None
    if data[:4] == b"glTF":
        _version, total = struct.unpack_from("<II", data, 4)
        off = 12
        while off + 8 <= min(total, len(data)):
            clen, ctype = struct.unpack_from("<II", data, off)
            chunk = data[off + 8:off + 8 + clen]
            off += 8 + clen
            if ctype == 0x4E4F534A:
                js = json.loads(chunk.decode("utf-8"))
            elif ctype == 0x004E4942:
                bin_chunk = chunk
    else:
        js = json.loads(data.decode("utf-8"))
    if js is None:
        raise ModelFileError("Not a glTF / GLB file: " + path)
    used = set(js.get("extensionsUsed", [])) | set(js.get("extensionsRequired", []))
    for ext in ("KHR_draco_mesh_compression", "EXT_meshopt_compression"):
        if ext in used:
            raise ModelFileError(
                "This GLB is compressed (%s). Rhino 8: _Import it, then run this script with "
                "source Pick. Or ask the generator for an uncompressed GLB / OBJ." % ext)
    buffers = []
    for b in js.get("buffers", []):
        uri = b.get("uri")
        if uri is None:
            buffers.append(bin_chunk)
        elif uri.startswith("data:"):
            buffers.append(base64.b64decode(uri.split(",", 1)[1]))
        else:
            buffers.append(open(os.path.join(os.path.dirname(path), unquote(uri)), "rb").read())
    nodes = js.get("nodes", [])
    scenes = js.get("scenes", [])
    if scenes:
        roots = scenes[js.get("scene", 0)].get("nodes", [])
    else:
        children = set(c for nd in nodes for c in nd.get("children", []))
        roots = [i for i in range(len(nodes)) if i not in children]
    parts = []
    stack = [(i, _IDENT) for i in roots]
    seen_mesh_at_node = False
    while stack:
        ni, parent = stack.pop()
        node = nodes[ni]
        world = _mat_mul(parent, node_matrix(node))
        if "mesh" in node:
            seen_mesh_at_node = True
            parts.extend(_mesh_parts(js, buffers, node["mesh"], world))
        for c in node.get("children", []):
            stack.append((c, world))
    if not seen_mesh_at_node:                           # meshes without nodes
        for mi in range(len(js.get("meshes", []))):
            parts.extend(_mesh_parts(js, buffers, mi, _IDENT))
    if not parts:
        raise ModelFileError("No triangle mesh in: " + path)
    return parts


def _mesh_parts(js, buffers, mesh_index, world):
    mesh = js["meshes"][mesh_index]
    out = []
    for pi, prim in enumerate(mesh.get("primitives", [])):
        if "POSITION" not in prim.get("attributes", {}):
            continue
        pos, _nc = _read_accessor(js, buffers, prim["attributes"]["POSITION"])
        verts = [(pos[i], pos[i + 1], pos[i + 2]) for i in range(0, len(pos) - 2, 3)]
        if "indices" in prim:
            idx, _n = _read_accessor(js, buffers, prim["indices"])
            idx = [int(i) for i in idx]
        else:
            idx = list(range(len(verts)))
        faces = _triangles(idx, prim.get("mode", 4))
        if faces:
            out.append({"name": "%s_%d" % (mesh.get("name") or "mesh%d" % mesh_index, pi),
                        "verts": verts, "faces": faces, "matrix": world})
    return out


def read_obj(path):
    """OBJ -> one part; quads and n-gons are kept (Rhino gets quads, n-gons are fanned)."""
    verts, faces = [], []
    with open(path, "rb") as fh:
        for raw in fh:
            line = raw.decode("utf-8", "replace") if PY3 else raw
            if line.startswith("v "):
                t = line.split()
                verts.append((float(t[1]), float(t[2]), float(t[3])))
            elif line.startswith("f "):
                idx = []
                for tok in line.split()[1:]:
                    i = int(tok.split("/")[0])
                    idx.append(i - 1 if i > 0 else len(verts) + i)
                if len(idx) >= 3:
                    faces.append(tuple(idx))
    if not faces:
        raise ModelFileError("No faces in OBJ: " + path)
    return [{"name": os.path.splitext(os.path.basename(path))[0], "verts": verts,
             "faces": faces, "matrix": _IDENT}]


def pick_model_in_folder(folder):
    """Best model file inside an unzipped folder (GLB first)."""
    found = []
    for root, _dirs, files in os.walk(folder):
        for f in files:
            ext = os.path.splitext(f)[1].lower()
            if ext in MODEL_EXTS and ext != ".zip":
                found.append((MODEL_EXTS.index(ext), os.path.join(root, f)))
    if not found:
        raise ModelFileError("No 3D model inside the ZIP.")
    return sorted(found)[0][1]


def default_up(ext):
    """glTF is Y up by spec; AI generators also write OBJ Y up. Rhino converts FBX itself."""
    return "y" if ext in (".glb", ".gltf", ".obj") else "z"


def keep_scale_mm(ext):
    """mm per file unit, used only when the real size is 0 (keep). glTF is metres by spec and
    generators write OBJ in metres too; Rhino's own importers already convert units (None)."""
    return 1000.0 if ext in (".glb", ".gltf", ".obj") else None


def build_payload(preset, photos, extra=None):
    """photos: {"front": data_uri, "back": ..., ...} -> (endpoint, JSON body)."""
    multi = len(photos) > 1
    app = preset.get("app_multi") if (multi and preset.get("app_multi")) else preset["app"]
    body = {}
    list_field = preset.get("list_field_multi") if multi else preset.get("list_single")
    if list_field:
        body[list_field] = [photos[v] for v in VIEWS if v in photos]
    else:
        fields = preset.get("views_multi") if (multi and preset.get("views_multi")) else preset["views"]
        missing = [v for v in photos if v not in fields]
        if missing:
            raise ApiError("Model '%s' does not take the %s view(s). Use front only, or "
                           "another model." % (preset.get("name", app), ", ".join(missing)))
        for v, uri in photos.items():
            body[fields[v]] = uri
    opts = dict(preset.get("extra", {}))
    if extra:
        opts.update(extra)
    for k, val in opts.items():
        body.setdefault(k, val)
    return app, body


def find_model_urls(result):
    """Every model-file URL in a generator result (any JSON shape), best first."""
    found = []

    def ext_of(url, hint=""):
        u = url.split("?")[0].split("#")[0].lower()
        for e in MODEL_EXTS:
            if u.endswith(e) or hint.lower().endswith(e):
                return e
        return None

    def walk(o):
        if isinstance(o, dict):
            url = o.get("url")
            if isinstance(url, _STR) and url.startswith("http"):
                hint = str(o.get("file_name") or o.get("filename") or "")
                e = ext_of(url, hint)
                ctype = str(o.get("content_type") or "")
                if e is None and ("gltf" in ctype or "glb" in ctype):
                    e = ".glb"
                if e:
                    found.append((e, url))
            for v in o.values():
                walk(v)
        elif isinstance(o, (list, tuple)):
            for v in o:
                walk(v)
        elif isinstance(o, _STR) and o.startswith("http"):
            e = ext_of(o)
            if e:
                found.append((e, o))
    walk(result)
    out, seen = [], set()
    for e, u in found:
        if u not in seen:
            seen.add(u)
            out.append((e, u))
    return out


def choose_model_url(found, prefer=None):
    if not found:
        return None
    order = list(MODEL_EXTS)
    if prefer in order:
        order.remove(prefer)
        order.insert(0, prefer)
    return sorted(found, key=lambda eu: order.index(eu[0]))[0]


def status_urls(app, submit):
    """fal returns status_url / response_url; fall back to the documented pattern."""
    rid = submit.get("request_id")
    owner_alias = "/".join(app.split("/")[:2])
    base = FAL_QUEUE + owner_alias + "/requests/" + str(rid)
    return (submit.get("status_url") or base + "/status", submit.get("response_url") or base, rid)


def fal_missing_fields(err_text):
    """Field names a fal 422 reply says are missing: {"detail": [{"loc": ["body", "image_url"], ...}]}."""
    i, j = err_text.find("{"), err_text.rfind("}")
    if i < 0 or j < i:
        return []
    try:
        js = json.loads(err_text[i:j + 1])
    except ValueError:
        return []
    out = []
    for d in (js.get("detail") or []) if isinstance(js, dict) else []:
        if not isinstance(d, dict):
            continue
        loc, kind, msg = d.get("loc") or [], str(d.get("type", "")), str(d.get("msg", "")).lower()
        if loc and ("missing" in kind or "required" in msg):
            out.append(str(loc[-1]))
    return out


def retry_preset(preset, err_text, photos):
    """After a 422 (rejected before any work, so nothing is charged): send the photo under the
    image field fal asked for and drop the optional extras. None = nothing to retry."""
    if "422" not in err_text and "Unprocessable" not in err_text:
        return None
    fixed = dict(preset)
    fixed["extra"] = {}
    why = ["optional settings dropped"]
    wanted = [f for f in fal_missing_fields(err_text) if "image" in f.lower()]
    if wanted and len(photos) == 1:
        field = wanted[0]
        fixed.pop("app_multi", None)
        if field.endswith("s"):                         # e.g. image_urls takes a list
            fixed["views"] = {}
            fixed["list_field_multi"] = None
            fixed["list_single"] = field
        else:
            fixed["views"] = {"front": field}
        why.insert(0, "photo sent as '%s'" % field)
    elif not preset.get("extra"):
        return None                                     # nothing left to change
    return {"preset": fixed, "why": ", ".join(why)}


def parse_extra(text):
    text = (text or "").strip()
    if not text:
        return None
    try:
        val = json.loads(text)
    except ValueError as e:
        raise ApiError("Extra JSON options are not valid JSON: %s" % e)
    if not isinstance(val, dict):
        raise ApiError("Extra JSON options must be an object, like {\"face_limit\": 20000}")
    return val


# =============================================================================
# HTTP: .NET in Rhino, urllib elsewhere (tests)
# =============================================================================
def _net_setup():
    from System.Net import ServicePointManager, SecurityProtocolType
    try:
        ServicePointManager.SecurityProtocol = (ServicePointManager.SecurityProtocol |
                                                SecurityProtocolType.Tls12)
    except Exception:
        pass


def http_json(method, url, key=None, body=None, timeout_s=120):
    """GET or POST JSON -> parsed JSON. Errors carry the server's message (fal explains bad fields)."""
    if IRON:
        from System.Net import WebClient, WebException
        from System.Text import Encoding
        from System.IO import StreamReader
        _net_setup()
        wc = WebClient()
        wc.Encoding = Encoding.UTF8
        wc.Headers.Add("Accept", "application/json")
        if key:
            wc.Headers.Add("Authorization", "Key " + key)
        try:
            if method == "POST":
                wc.Headers.Add("Content-Type", "application/json")
                text = wc.UploadString(url, "POST", json.dumps(body))
            else:
                text = wc.DownloadString(url)
        except WebException as e:
            detail = ""
            try:
                detail = StreamReader(e.Response.GetResponseStream()).ReadToEnd()
            except Exception:
                pass
            raise ApiError("%s %s\n%s\n%s" % (method, url.split("?")[0], e.Message, detail[:1500]))
        return json.loads(text)
    try:
        import urllib.request as ureq
        from urllib.error import HTTPError
    except ImportError:
        import urllib2 as ureq
        from urllib2 import HTTPError
    data = json.dumps(body).encode("utf-8") if method == "POST" else None
    req = ureq.Request(url, data=data, method=method) if PY3 else ureq.Request(url, data=data)
    req.add_header("Accept", "application/json")
    if data is not None:
        req.add_header("Content-Type", "application/json")
    if key:
        req.add_header("Authorization", "Key " + key)
    try:
        resp = ureq.urlopen(req, timeout=timeout_s)
        return json.loads(resp.read().decode("utf-8"))
    except HTTPError as e:
        raise ApiError("%s %s\n%s\n%s" % (method, url.split("?")[0], e,
                                          e.read()[:1500].decode("utf-8", "replace")))


def http_download(url, path):
    if IRON:
        from System.Net import WebClient
        _net_setup()
        WebClient().DownloadFile(url, path)
        return path
    try:
        import urllib.request as ureq
    except ImportError:
        import urllib2 as ureq
    resp = ureq.urlopen(url, timeout=300)
    with open(path, "wb") as fh:
        fh.write(resp.read())
    return path


def image_data_uri(path, max_px=2048):
    """Photo -> data URI. In Rhino the photo is shrunk to max_px and sent as JPEG
    (PNG when it has transparency); fal accepts data URIs for image inputs."""
    if IRON:
        import System.Drawing as SD
        from System.Drawing.Drawing2D import InterpolationMode
        from System.Drawing.Imaging import (Encoder, EncoderParameter, EncoderParameters,
                                            ImageCodecInfo, ImageFormat)
        from System.IO import MemoryStream
        src = SD.Bitmap(path)
        try:
            try:                                    # phone photos: apply the EXIF rotation
                if 0x0112 in list(src.PropertyIdList):
                    rft = SD.RotateFlipType
                    turn = {2: rft.RotateNoneFlipX, 3: rft.Rotate180FlipNone, 4: rft.Rotate180FlipX,
                            5: rft.Rotate90FlipX, 6: rft.Rotate90FlipNone, 7: rft.Rotate270FlipX,
                            8: rft.Rotate270FlipNone}.get(int(src.GetPropertyItem(0x0112).Value[0]))
                    if turn is not None:
                        src.RotateFlip(turn)
            except Exception:
                pass
            w, h = src.Width, src.Height
            s = min(1.0, float(max_px) / max(w, h))
            alpha = SD.Image.IsAlphaPixelFormat(src.PixelFormat)
            nw, nh = max(1, int(round(w * s))), max(1, int(round(h * s)))
            img = SD.Bitmap(nw, nh)
            g = SD.Graphics.FromImage(img)
            g.InterpolationMode = InterpolationMode.HighQualityBicubic
            if not alpha:
                g.Clear(SD.Color.White)
            g.DrawImage(src, 0, 0, nw, nh)
            g.Dispose()
        finally:
            src.Dispose()
        ms = MemoryStream()
        if alpha:
            img.Save(ms, ImageFormat.Png)
            mime = "image/png"
        else:
            codec = [c for c in ImageCodecInfo.GetImageEncoders() if c.MimeType == "image/jpeg"][0]
            ep = EncoderParameters(1)
            ep.Param[0] = EncoderParameter(Encoder.Quality, System.Int64(92))
            img.Save(ms, codec, ep)
            mime = "image/jpeg"
        img.Dispose()
        return "data:%s;base64,%s" % (mime, System.Convert.ToBase64String(ms.ToArray()))
    ext = os.path.splitext(path)[1].lower()
    mime = "image/png" if ext == ".png" else ("image/webp" if ext == ".webp" else "image/jpeg")
    with open(path, "rb") as fh:
        return "data:%s;base64,%s" % (mime, base64.b64encode(fh.read()).decode("ascii"))


def fal_generate(preset, photos, key, extra=None, timeout_min=15.0, log=print, wait=None):
    """Submit to the fal queue, poll until done, return (result JSON, request id).
    'wait(seconds)' keeps the UI alive and raises UserCancel on Esc."""
    app, body = build_payload(preset, photos, extra)
    log("fal: %s  (%d photo%s)" % (app, len(photos), "s" if len(photos) > 1 else ""))
    submit = http_json("POST", FAL_QUEUE + app, key, body)
    status_url, response_url, rid = status_urls(app, submit)
    log("fal: request %s queued" % rid)
    t0, last = time.time(), None
    while True:
        (wait or time.sleep)(3.0)
        st = http_json("GET", status_url, key)
        s = st.get("status")
        if s != last:
            pos = st.get("queue_position")
            log("fal: %s%s  (%.0f s)" % (s, "" if pos in (None, 0) else ", queue %s" % pos,
                                         time.time() - t0))
            last = s
        if s == "COMPLETED":
            if st.get("error"):
                raise ApiError("fal: %s" % st.get("error"))
            break
        if s not in ("IN_QUEUE", "IN_PROGRESS"):
            raise ApiError("fal: unexpected status %r" % st)
        if time.time() - t0 > timeout_min * 60.0:
            raise ApiError("fal: still not done after %.0f min. Request id %s - the model may "
                           "still arrive in your fal dashboard." % (timeout_min, rid))
    return http_json("GET", response_url, key), rid


# =============================================================================
# Rhino helpers
# =============================================================================
class Settings(object):
    def __init__(self, spec):
        self._spec = spec
        for key, _label, value in spec:
            setattr(self, key, value)

    def ask(self, title, note):
        labels = [row[1] for row in self._spec]
        values = [str(getattr(self, row[0])) for row in self._spec]
        res = rs.PropertyListBox(labels, values, note, title)
        if res is None:
            return False
        for row, value in zip(self._spec, res):
            setattr(self, row[0], (value or "").strip())
        return True

    def num(self, key, default=0.0):
        try:
            return float(str(getattr(self, key)).replace(",", "."))
        except Exception:
            return default

    def text(self, key):
        return str(getattr(self, key)).strip().lower()


class Log(object):
    def __init__(self):
        self.lines = []

    def __call__(self, text=""):
        self.lines.append(str(text))
        print(text)
        try:
            Rhino.RhinoApp.Wait()
        except Exception:
            pass


def mm():
    """Model units per millimetre."""
    return Rhino.RhinoMath.UnitScale(Rhino.UnitSystem.Millimeters, sc.doc.ModelUnitSystem)


def ui_wait(seconds):
    t_end = time.time() + seconds
    while time.time() < t_end:
        Rhino.RhinoApp.Wait()
        if sc.escape_test(False):
            raise UserCancel()
        time.sleep(0.05)


def ensure_layer(path, rgb):
    idx = sc.doc.Layers.FindByFullPath(path, -1)
    if idx >= 0:
        return idx
    parent_id = None
    names = path.split("::")
    for i in range(len(names)):
        sub = "::".join(names[:i + 1])
        idx = sc.doc.Layers.FindByFullPath(sub, -1)
        if idx < 0:
            layer = Rhino.DocObjects.Layer()
            layer.Name = names[i]
            if parent_id is not None:
                layer.ParentLayerId = parent_id
            if i == len(names) - 1:
                layer.Color = Color.FromArgb(rgb[0], rgb[1], rgb[2])
            idx = sc.doc.Layers.Add(layer)
        parent_id = sc.doc.Layers[idx].Id
    return idx


def add_geom(geom, layer, name):
    a = Rhino.DocObjects.ObjectAttributes()
    a.LayerIndex = layer
    a.Name = name
    if isinstance(geom, rg.Mesh):
        return sc.doc.Objects.AddMesh(geom, a)
    if isinstance(geom, rg.SubD):
        return sc.doc.Objects.AddSubD(geom, a)
    return sc.doc.Objects.AddBrep(geom, a)


def to_transform(m16):
    t = rg.Transform(1.0)
    for r in range(4):
        for c in range(4):
            setattr(t, "M%d%d" % (r, c), float(m16[r * 4 + c]))
    return t


def part_to_mesh(part):
    m = rg.Mesh()
    pts = List[rg.Point3f]()
    for x, y, z in part["verts"]:
        pts.Add(rg.Point3f(x, y, z))
    m.Vertices.AddVertices(pts)
    faces = List[rg.MeshFace]()
    for f in part["faces"]:
        if len(f) == 3:
            faces.Add(rg.MeshFace(f[0], f[1], f[2]))
        elif len(f) == 4:
            faces.Add(rg.MeshFace(f[0], f[1], f[2], f[3]))
        else:
            for i in range(1, len(f) - 1):
                faces.Add(rg.MeshFace(f[0], f[i], f[i + 1]))
    m.Faces.AddFaces(faces)
    if part["matrix"] != _IDENT:
        m.Transform(to_transform(part["matrix"]))
    return m


def is_manifold(m):
    try:
        r = m.IsManifold(True)
        return bool(r[0] if isinstance(r, tuple) else r)
    except Exception:
        return False


def open_loops(m):
    try:
        loops = m.GetNakedEdges()
        return len(loops) if loops else 0
    except Exception:
        return -1


def size_text(geom):
    bb = geom.GetBoundingBox(True)
    k = 1.0 / mm()
    return "%.0f x %.0f x %.0f mm" % ((bb.Max.X - bb.Min.X) * k, (bb.Max.Y - bb.Min.Y) * k,
                                      (bb.Max.Z - bb.Min.Z) * k)


# =============================================================================
# Getting the model
# =============================================================================
def work_dir():
    base = os.path.dirname(sc.doc.Path) if sc.doc.Path else \
        System.Environment.GetFolderPath(System.Environment.SpecialFolder.Desktop)
    folder = os.path.join(base, "S3D_Photo3D", time.strftime("%Y%m%d_%H%M%S"))
    if not os.path.isdir(folder):
        os.makedirs(folder)
    return folder


def fal_key():
    key = (os.environ.get("FAL_KEY") or "").strip()
    store = os.path.join(System.Environment.GetFolderPath(
        System.Environment.SpecialFolder.ApplicationData), "Styro3D", "fal_key.txt")
    if not key and os.path.isfile(store):
        key = open(store).read().strip()
    if key:
        return key
    key = (rs.StringBox("Paste your fal.ai API key (fal.ai -> Dashboard -> API keys)",
                        "", TITLE) or "").strip()
    if key and rs.MessageBox("Save the key on this PC for next time?\n" + store, 4 | 32, TITLE) == 6:
        if not os.path.isdir(os.path.dirname(store)):
            os.makedirs(os.path.dirname(store))
        with open(store, "w") as fh:
            fh.write(key)
    return key


def get_photos():
    photos = {}
    for v in VIEWS:
        msg = "Pick the %s photo%s" % (v.upper(), "" if v == "front" else " (Cancel = skip)")
        path = rs.OpenFileName(msg, PHOTO_FILTER)
        if not path:
            if v == "front":
                return None
            continue
        photos[v] = path
        if v == "front" and rs.MessageBox("Add more views (back / left / right)?\n"
                                          "More views = more accurate shape.", 4 | 32, TITLE) != 6:
            break
    return photos


def prepare_ai():
    """Photos, model and key - asked up front so the long wait needs no clicks."""
    ai = Settings(AI_SPEC)
    note = "Models: " + "; ".join("%s = %s" % (k, PRESETS[k]["note"]) for k in sorted(PRESETS))
    photos = get_photos()
    if not photos:
        return None
    if not ai.ask(TITLE + " - AI", note):
        return None
    name = ai.text("model")
    if name == "custom":
        fields = [f.strip() for f in ai.fields.split(",")]
        preset = {"app": ai.endpoint.strip(), "extra": {},
                  "views": dict((VIEWS[i], fields[i]) for i in range(min(4, len(fields))) if fields[i])}
        if not preset["app"]:
            raise ApiError("Type the custom fal endpoint id, e.g. fal-ai/hunyuan3d-v3/image-to-3d")
    elif name in PRESETS:
        preset = dict(PRESETS[name])
    else:
        raise ApiError("Unknown AI model '%s'. Use: %s or custom" % (name, ", ".join(sorted(PRESETS))))
    preset["name"] = name
    extra = parse_extra(ai.extra)
    key = fal_key()
    if not key:
        return None
    return {"ai": ai, "photos": photos, "preset": preset, "extra": extra, "key": key}


def source_ai(job, log):
    ai, photos, preset, extra, key = job["ai"], job["photos"], job["preset"], job["extra"], job["key"]
    name = preset["name"]
    folder = work_dir()
    uris = {}
    for v, p in photos.items():
        uris[v] = image_data_uri(p, int(ai.num("max_px", 2048)))
        log("Photo %-5s %s (%.0f kB sent)" % (v, os.path.basename(p), len(uris[v]) * 0.75 / 1024))
    log("AI: %s - about 1-3 minutes. Esc stops waiting." % preset.get("note", name))
    try:
        result, rid = fal_generate(preset, uris, key, extra, ai.num("timeout", 15.0), log, ui_wait)
    except ApiError as err:
        fix = retry_preset(preset, str(err), uris)
        if fix is None:
            raise
        log("fal rejected the request (nothing charged). Retrying once: %s" % fix["why"])
        result, rid = fal_generate(fix["preset"], uris, key, None, ai.num("timeout", 15.0), log, ui_wait)
    with open(os.path.join(folder, "fal_result.json"), "w") as fh:
        json.dump(result, fh, indent=1)
    best = choose_model_url(find_model_urls(result), preset.get("prefer"))
    if best is None:
        raise ApiError("fal finished but no model link was found. See fal_result.json in\n" + folder)
    ext, url = best
    path = os.path.join(folder, "model_%s%s" % (str(rid)[:8], ext))
    log("Download %s" % url.split("?")[0])
    http_download(url, path)
    return path


def ask_url():
    clip = ""
    try:
        clip = (rs.ClipboardText() or "").strip()
    except Exception:
        pass
    url = rs.StringBox("Paste the model link (GLB / OBJ / FBX / STL / ZIP)",
                       clip if clip.startswith("http") else "", TITLE)
    return (url or "").strip() or None


def source_url(url, log):
    name = unquote(url.split("?")[0].rstrip("/").split("/")[-1]) or "model.glb"
    if os.path.splitext(name)[1].lower() not in MODEL_EXTS:
        name += ".glb"
    path = os.path.join(work_dir(), name)
    log("Download %s" % url.split("?")[0])
    http_download(url, path)
    return path


def import_native(path):
    """FBX / STL / PLY / 3MF (and anything else) through Rhino's own importers."""
    before = set(str(o.Id) for o in sc.doc.Objects)
    if not sc.doc.Import(path):
        raise ModelFileError("Rhino could not import:\n" + path)
    meshes = []
    new = [o for o in sc.doc.Objects if str(o.Id) not in before]
    for o in new:
        g = o.Geometry
        if isinstance(g, rg.Mesh):
            meshes.append(g.DuplicateMesh())
        elif isinstance(g, rg.Brep):
            for bm in rg.Mesh.CreateFromBrep(g, rg.MeshingParameters.QualityRenderMesh) or []:
                meshes.append(bm)
    for o in new:
        sc.doc.Objects.Delete(o, True)
    if not meshes:
        raise ModelFileError("No mesh found in:\n" + path)
    return meshes


def load_model(path, log):
    """Model file -> (list of Rhino meshes, extension)."""
    ext = os.path.splitext(path)[1].lower()
    if ext == ".zip":
        folder = os.path.splitext(path)[0] + "_unzipped"
        zipfile.ZipFile(path).extractall(folder)
        path = pick_model_in_folder(folder)
        ext = os.path.splitext(path)[1].lower()
        log("ZIP -> %s" % os.path.basename(path))
    if ext in (".glb", ".gltf"):
        parts = read_gltf(path)
    elif ext == ".obj":
        parts = read_obj(path)
    else:
        return import_native(path), ext
    log("Read %s: %d part(s), %d faces" % (os.path.basename(path), len(parts),
                                           sum(len(p["faces"]) for p in parts)))
    return [part_to_mesh(p) for p in parts], ext


# =============================================================================
# The pass: clean -> orient -> size -> heal -> quads -> SubD -> NURBS
# =============================================================================
def combine(meshes):
    m = rg.Mesh()
    for g in meshes:
        m.Append(g)
    return m


def basic_cleanup(m, log):
    n0 = m.Faces.Count
    m.Faces.CullDegenerateFaces()
    m.Vertices.CombineIdentical(True, True)      # AI files split vertices at UV seams
    try:
        m.Faces.ExtractDuplicateFaces()
    except Exception:
        pass
    m.Vertices.CullUnused()
    m.Compact()
    log("Weld: faces %d -> %d, quads %d" % (n0, m.Faces.Count, m.Faces.QuadCount))


def orient(m, up, turn_deg, log):
    """Z up, front to -Y. Returns the transform it applied."""
    c = m.GetBoundingBox(True).Center
    rot = {"y": (math.pi / 2, rg.Vector3d.XAxis), "-y": (-math.pi / 2, rg.Vector3d.XAxis),
           "x": (-math.pi / 2, rg.Vector3d.YAxis), "-z": (math.pi, rg.Vector3d.XAxis)}
    xf = rg.Transform.Identity
    if up in rot:
        xf = rg.Transform.Rotation(rot[up][0], rot[up][1], c)
    if abs(turn_deg) > 1e-9:
        xf = rg.Transform.Rotation(math.radians(turn_deg), rg.Vector3d.ZAxis, c) * xf
    m.Transform(xf)
    log("Orient: file up %s -> Z, turned %.0f deg" % (up, turn_deg))
    return xf


def size_and_place(m, size_doc, axis, keep_mm, log):
    bb = m.GetBoundingBox(True)
    ext = {"width": bb.Max.X - bb.Min.X, "depth": bb.Max.Y - bb.Min.Y, "height": bb.Max.Z - bb.Min.Z}
    ext["longest"] = max(ext.values())
    cur = ext.get(axis, ext["height"])
    base = rg.Point3d(bb.Center.X, bb.Center.Y, bb.Min.Z)
    if size_doc > 0 and cur > 1e-12:
        f = size_doc / cur
    else:
        f = keep_mm * mm() if keep_mm else 1.0
    xf = rg.Transform.Scale(base, f)
    m.Transform(xf)
    bb = m.GetBoundingBox(True)
    move = rg.Transform.Translation(rg.Vector3d(-bb.Center.X, -bb.Center.Y, -bb.Min.Z))
    m.Transform(move)
    log("Size: %s (scale x%.4g), centred, base on Z = 0" % (size_text(m), f))
    return move * xf


def _inside(container, piece, tol):
    bc, bp = container.GetBoundingBox(True), piece.GetBoundingBox(True)
    if not (bc.Contains(bp.Min) and bc.Contains(bp.Max)):
        return False
    n = piece.Vertices.Count
    return all(container.IsPointInside(rg.Point3d(piece.Vertices[i]), tol, True)
               for i in (0, n // 2, n - 1))


def remove_debris(m, pct, log):
    pieces = m.SplitDisjointPieces()
    if pieces is None or len(pieces) <= 1:
        log("Pieces: 1")
        return m
    pieces = sorted(pieces, key=lambda p: p.Faces.Count, reverse=True)
    total = sum(p.Faces.Count for p in pieces)
    diag = m.GetBoundingBox(True).Diagonal.Length
    tol = sc.doc.ModelAbsoluteTolerance
    main, keep, bits, inner = pieces[0], [pieces[0]], 0, 0
    for p in pieces[1:]:
        if p.Faces.Count < total * pct / 100.0 and p.GetBoundingBox(True).Diagonal.Length < 0.05 * diag:
            bits += 1
        elif main.IsClosed and p.IsClosed and _inside(main, p, tol):
            inner += 1
        else:
            keep.append(p)
    out = combine(keep)
    out.Compact()
    log("Pieces: %d -> kept %d, dropped %d loose bits + %d inner shells" % (len(pieces), len(keep),
                                                                           bits, inner))
    return out


def heal(m, log):
    loops0 = open_loops(m)
    if loops0:
        m.HealNakedEdges(sc.doc.ModelAbsoluteTolerance * 10)
        m.Vertices.CombineIdentical(True, True)
    if not is_manifold(m):
        try:
            m.ExtractNonManifoldEdges(True)
        except Exception:
            pass
    if open_loops(m):
        m.FillHoles()
    m.UnifyNormals()
    if m.IsClosed and m.SolidOrientation() == -1:
        m.Flip(True, True, True)
    m.RebuildNormals()
    m.Compact()
    log("Heal: open loops %d -> %d, closed %s, manifold %s" % (loops0, open_loops(m), m.IsClosed,
                                                              is_manifold(m)))


def shrink_wrap(m, log):
    if int(Rhino.RhinoApp.ExeVersion) < 8:
        log("Still open: in Rhino 7 run _MeshRepair, or use Rhino 8 (ShrinkWrap).")
        return m
    p = rg.ShrinkWrapParameters()
    bb = m.GetBoundingBox(True)
    for name, val in (("TargetEdgeLength", float(bb.Diagonal.Length / 500.0)), ("Offset", 0.0),
                      ("SmoothingIterations", 1), ("FillHolesInInputObjects", True),
                      ("PolygonOptimization", 25)):
        try:
            setattr(p, name, val)
        except Exception:
            pass
    log("ShrinkWrap (Rhino 8) to close the mesh ...")
    w = m.ShrinkWrap(p)
    if w is None or not w.IsValid or w.Faces.Count == 0:
        log("ShrinkWrap failed - keeping the healed mesh.")
        return m
    w.RebuildNormals()
    log("ShrinkWrap: closed %s, %d faces" % (w.IsClosed, w.Faces.Count))
    return w


def quad_remesh(m, s, log):
    src = m
    if m.Faces.Count > 400000:                     # QuadRemesh is much faster on a lighter copy
        src = m.DuplicateMesh()
        src.Reduce(300000, True, 10, False)
        log("Reduce for QuadRemesh: %d -> %d faces" % (m.Faces.Count, src.Faces.Count))
    qp = rg.QuadRemeshParameters()
    qp.TargetQuadCount = int(s.num("quads", 4000))
    qp.AdaptiveSize = max(0.0, min(100.0, s.num("adaptive", 50)))
    qp.AdaptiveQuadCount = True
    qp.DetectHardEdges = s.text("hard") in ("y", "yes", "1", "true")
    qp.PreserveMeshArrayEdgesMode = 0
    sym = s.text("symmetry")
    if sym in ("x", "y"):
        qp.SymmetryAxis = rg.QuadRemeshSymmetryAxis.X if sym == "x" else rg.QuadRemeshSymmetryAxis.Y
    log("QuadRemesh: target %d quads ..." % qp.TargetQuadCount)
    q = src.QuadRemesh(qp)
    if q is None or q.Faces.Count == 0:
        log("QuadRemesh failed.")
        return None
    log("QuadRemesh: %d faces (%d quads), closed %s" % (q.Faces.Count, q.Faces.QuadCount, q.IsClosed))
    return q


def run(s, path=None, picked=None, label="model", log=print):
    ksize = s.num("size_mm", 0.0) * mm()
    if picked is not None:
        meshes, ext = picked, ".3dm"
    else:
        meshes, ext = load_model(path, log)
    raw = combine(meshes)
    up = s.text("up")
    if up not in ("y", "z", "x", "-y", "-z"):
        up = default_up(ext)
    lay = dict((k, ensure_layer("S3D_Photo3D::" + k, c)) for k, c in (
        ("Raw", (150, 150, 150)), ("Mesh", (200, 200, 195)), ("Quad", (230, 170, 90)),
        ("SubD", (140, 150, 230)), ("Polysurface", (90, 170, 110))))
    m = raw.DuplicateMesh()
    basic_cleanup(m, log)
    m = remove_debris(m, s.num("debris", 1.0), log)        # before sizing: a stray bit skews the box
    xf = orient(m, up, s.num("turn", 0.0), log)
    xf = size_and_place(m, ksize, s.text("size_axis"), keep_scale_mm(ext), log) * xf
    raw_placed = raw.DuplicateMesh()
    raw_placed.Transform(xf)
    heal(m, log)
    if (not m.IsClosed) and s.text("wrap") != "never":
        m = shrink_wrap(m, log)
    if picked is None:
        rid = add_geom(raw_placed, lay["Raw"], label + "_Raw")
        sc.doc.Objects.Hide(rid, True)
    out = {"mesh": m}
    output = s.text("output")
    add_geom(m, lay["Mesh"], label + "_Mesh")
    q = None
    if output in ("quad", "subd", "nurbs") and s.num("quads", 4000) > 0:
        quad_share = m.Faces.QuadCount / float(max(1, m.Faces.Count))
        if quad_share >= 0.9 and m.Faces.Count <= 3 * s.num("quads", 4000):
            q = m.DuplicateMesh()
            log("Already %.0f%% quads - QuadRemesh skipped." % (quad_share * 100))
        else:
            q = quad_remesh(m, s, log)
        if q is not None:
            add_geom(q, lay["Quad"], label + "_Quad")
            out["quad"] = q
    if q is not None and output in ("subd", "nurbs"):
        subd = rg.SubD.CreateFromMesh(q, rg.SubDCreationOptions.Smooth)
        if subd is None:
            log("SubD failed (mesh not manifold?). The quad mesh is on S3D_Photo3D::Quad.")
        else:
            add_geom(subd, lay["SubD"], label + "_SubD")
            out["subd"] = subd
            log("SubD: %d faces" % subd.Faces.Count)
            if output == "nurbs":
                log("NURBS polysurface ...")
                brep = subd.ToBrep(rg.SubDToBrepOptions.DefaultPacked)
                if brep is None:
                    log("Polysurface failed.")
                else:
                    add_geom(brep, lay["Polysurface"], label + "_Polysurface")
                    out["brep"] = brep
                    vol = brep.GetVolume() / (mm() ** 3) / 1e6 if brep.IsSolid else 0.0
                    log("Polysurface: %d faces, solid %s%s" % (
                        brep.Faces.Count, brep.IsSolid, ", %.2f L" % vol if brep.IsSolid else ""))
    return out


def main():
    log = Log()
    choice = rs.GetString("Model source", "AI", ["AI", "URL", "File", "Pick"])
    if not choice:
        return
    choice = choice.lower()
    s = Settings(SPEC)
    picked = path = url = job = None
    label = "model"
    if choice == "pick":
        ids = rs.GetObjects("Select the mesh(es)", rs.filter.mesh, preselect=True)
        if not ids:
            return
        picked = [rs.coercemesh(i).DuplicateMesh() for i in ids]
        label = rs.ObjectName(ids[0]) or "model"
    elif choice == "file":
        path = rs.OpenFileName("Pick a 3D model", MESH_FILTER)
        if not path:
            return
    elif choice == "url":
        url = ask_url()
        if not url:
            return
    else:
        job = prepare_ai()
        if not job:
            return
    if not s.ask(TITLE, "Real size, orientation and clean-up. Front of the object faces -Y."):
        return
    log("=" * 64)
    log("%s v%s | source %s | Rhino %s | units %s" % (TITLE, VERSION, choice, Rhino.RhinoApp.ExeVersion,
                                                      sc.doc.ModelUnitSystem))
    if choice == "url":
        path = source_url(url, log)
    elif choice == "ai":
        path = source_ai(job, log)
    if path:
        label = "".join(ch if ch.isalnum() or ch in "-_" else "_"
                        for ch in os.path.splitext(os.path.basename(path))[0])[:40] or "model"
    rs.EnableRedraw(False)
    out = run(s, path, picked, label, log)
    rs.EnableRedraw(True)
    rs.ZoomExtents(all=True)
    final = out.get("brep") or out.get("subd") or out.get("quad") or out["mesh"]
    log("Done: %s. Layers S3D_Photo3D::Mesh / Quad / SubD / Polysurface." % size_text(final))
    if path:
        log("Files: " + os.path.dirname(path))


if __name__ == "__main__":
    try:
        main()
    except UserCancel:
        print("Stopped (Esc).")
    except (ApiError, ModelFileError) as err:
        print(str(err))
        rs.MessageBox(str(err)[:1800], 48, TITLE)
    except Exception:
        print(traceback.format_exc())
        rs.MessageBox("Script error - details on the command line.", 16, TITLE)
    finally:
        try:
            rs.EnableRedraw(True)
        except Exception:
            pass
