#! python2
# -*- coding: utf-8 -*-
"""
Styro3D | AI image -> 3D -> CNC toolkit for Rhino
=================================================================
File    styro3d_ai_to_cnc.py   v1.0   2026-10-01
Rhino   7 (IronPython 2.7) and 8. The first line makes Rhino 8 run it in
        IronPython 2.7 too, so both versions execute the same code.
Run     command _RunPythonScript -> pick this file
        or _EditPythonScript -> open -> Run
        alias:  S3D  =  ! _-RunPythonScript "C:\\path\\styro3d_ai_to_cnc.py"
Undo    one Ctrl+Z removes everything a run added
Cancel  Esc during the long steps

MODES
 1  AI mesh -> CNC
    Select (or import) the mesh from Meshy / Tripo / Hunyuan3D / SAM 3D
    (OBJ, STL, FBX, PLY, 3MF; GLB/glTF needs Rhino 8). Steps:
    weld -> up axis -> real height -> drop floaters + inner shells ->
    heal + fill holes -> fix normals -> watertight (ShrinkWrap, Rhino 8) ->
    CNC checks (thin walls, undercuts for 2-sided 3-axis, foam blocks,
    volume, EPS weight) -> QuadRemesh -> SubD -> PNG previews ->
    binary STL in mm + report.txt
 2  Build legionary
    Roman legionary from code: SubD body + NURBS armour, helmet, shield,
    spear, sword and base plinth. Real scale, layers, PBR materials.
 3  Build legionary -> CNC
    Mode 2, then the Mode 1 CNC steps on the joined result.

NOTES
 * CNC does not need quads. The STL is written from the dense watertight
   mesh. Quads / SubD are for editing, smoothing and rendering.
 * All sizes are millimetres; the script converts to the model units.
 * Results go to layers S3D::... ; the input mesh is hidden, never changed.
"""
from __future__ import print_function, division

import codecs
import math
import os
import struct
import sys
import time
import traceback

import Rhino
import Rhino.Geometry as rg
from Rhino.Geometry.Intersect import Intersection
import rhinoscriptsyntax as rs
import scriptcontext as sc
import System
from System.Collections.Generic import List
from System.Drawing import Color

TITLE = "Styro3D AI -> CNC"
VERSION = "1.0"
RHINO_VER = int(Rhino.RhinoApp.ExeVersion)
PY3 = sys.version_info[0] >= 3
BUILD_TOL = 0.01          # mm; the legionary is modelled in mm, then scaled
FIGURE_BASE_MM = 1750.0   # design height of the legionary (top of head)


class UserCancel(Exception):
    pass


# =============================================================================
# Settings
# =============================================================================
# (key, label shown in the dialog, default)
CNC_SPEC = [
    ("height_mm",   "Target height mm (0 = keep size)",            "1800"),
    ("up_axis",     "Source up axis: auto / x / y / z",             "auto"),
    ("debris_pct",  "Drop loose pieces under % of faces",           "0.5"),
    ("heal_mm",     "Heal gaps up to mm",                           "0.5"),
    ("wrap",        "ShrinkWrap (Rhino 8): auto / always / never",  "auto"),
    ("wrap_mm",     "ShrinkWrap edge length mm (0 = auto)",         "0"),
    ("quads",       "QuadRemesh target quads (0 = skip)",           "6000"),
    ("subd",        "Make SubD from quads (y/n)",                   "y"),
    ("min_wall_mm", "Thin-wall warning below mm",                   "12"),
    ("block_x",     "Foam block X mm",                              "2000"),
    ("block_y",     "Foam block Y mm",                              "1000"),
    ("block_z",     "Foam block Z mm",                              "1000"),
    ("density",     "EPS density kg/m3",                            "20"),
    ("stl",         "Export binary STL in mm (y/n)",                "y"),
    ("png",         "Save preview PNGs (y/n)",                      "y"),
    ("out_dir",     "Output folder (blank = auto)",                 ""),
]

BUILD_SPEC = [
    ("height_mm", "Figure height mm (top of head)",     "1750"),
    ("plate_mm",  "Min plate thickness mm (foam: 15+)", "6"),
    ("shield",    "Shield (y/n)",                       "y"),
    ("spear",     "Spear / pilum (y/n)",                "y"),
    ("sword",     "Sword + scabbard (y/n)",             "y"),
    ("base",      "Round base plinth (y/n)",            "y"),
    ("png",       "Save preview PNG (y/n)",             "y"),
    ("out_dir",   "Output folder (blank = auto)",       ""),
]


class Settings(object):
    def __init__(self, spec, **overrides):
        self._spec = spec
        for key, _label, value in spec:
            setattr(self, key, overrides.get(key, value))

    def ask(self, title):
        labels = [row[1] for row in self._spec]
        values = [str(getattr(self, row[0])) for row in self._spec]
        result = rs.PropertyListBox(labels, values, "Edit the values, then OK", title)
        if result is None:
            return False
        for row, value in zip(self._spec, result):
            setattr(self, row[0], (value or "").strip())
        return True

    def num(self, key, default=0.0):
        try:
            return float(str(getattr(self, key)).replace(",", "."))
        except Exception:
            return default

    def flag(self, key):
        return str(getattr(self, key)).strip().lower() in ("y", "yes", "1", "true", "on")

    def text(self, key):
        return str(getattr(self, key)).strip().lower()


# =============================================================================
# Small helpers
# =============================================================================
def mm():
    """Model units per millimetre."""
    return Rhino.RhinoMath.UnitScale(Rhino.UnitSystem.Millimeters, sc.doc.ModelUnitSystem)


def check_escape():
    try:
        pressed = sc.escape_test(False)
    except Exception:
        pressed = False
    if pressed:
        raise UserCancel()


def net_list(items, net_type):
    out = List[net_type]()
    for item in items:
        out.Add(item)
    return out


def safe_name(text):
    out = "".join(ch if (ch.isalnum() or ch in "-_") else "_" for ch in (text or "model"))
    return out.strip("_")[:40] or "model"


def rgb(c):
    return Color.FromArgb(c[0], c[1], c[2])


class Report(object):
    """Prints to the command line and keeps the lines for report.txt."""

    def __init__(self, title):
        self.lines = []
        self.add("=" * 64)
        self.add("{}  v{}  |  {}".format(TITLE, VERSION, title))
        self.add("{}  |  Rhino {}  |  model units: {}".format(
            time.strftime("%Y-%m-%d %H:%M"), RHINO_VER, sc.doc.ModelUnitSystem))
        self.add("=" * 64)

    def add(self, text=""):
        self.lines.append(str(text))
        print(text)
        try:
            Rhino.RhinoApp.Wait()   # keep the UI alive during long runs
        except Exception:
            pass

    def save(self, path):
        f = codecs.open(path, "w", "utf-8")     # paths may contain non-ASCII folder names
        try:
            f.write(u"\n".join(self.lines) + u"\n")
        finally:
            f.close()


def output_dir(settings, label):
    folder = (getattr(settings, "out_dir", "") or "").strip()
    if not folder:
        doc_path = sc.doc.Path
        if doc_path:
            base = os.path.dirname(doc_path)
        else:
            base = System.Environment.GetFolderPath(System.Environment.SpecialFolder.Desktop)
        folder = os.path.join(base, "S3D_{}_{}".format(safe_name(label), time.strftime("%Y%m%d_%H%M%S")))
    if not os.path.isdir(folder):
        os.makedirs(folder)
    return folder


def ensure_layer(path, color=None, material_index=None):
    """Find or create a nested layer like 'S3D::01_CNC_Mesh'. Returns the layer index."""
    idx = sc.doc.Layers.FindByFullPath(path, -1)
    if idx >= 0:
        return idx
    parts = path.split("::")
    parent_id = None
    for i in range(len(parts)):
        sub = "::".join(parts[:i + 1])
        idx = sc.doc.Layers.FindByFullPath(sub, -1)
        if idx < 0:
            layer = Rhino.DocObjects.Layer()
            layer.Name = parts[i]
            if parent_id is not None:
                layer.ParentLayerId = parent_id
            if i == len(parts) - 1:
                if color is not None:
                    layer.Color = color
                if material_index is not None and material_index >= 0:
                    layer.RenderMaterialIndex = material_index
            idx = sc.doc.Layers.Add(layer)
            if idx < 0:
                return sc.doc.Layers.CurrentLayerIndex
        parent_id = sc.doc.Layers[idx].Id
    return idx


def ensure_material(name, color_rgb, metallic=0.0, roughness=0.5):
    for i in range(sc.doc.Materials.Count):
        existing = sc.doc.Materials[i]
        if existing.Name == name and not existing.IsDeleted:
            return i
    mat = Rhino.DocObjects.Material()
    mat.Name = name
    col = rgb(color_rgb)
    mat.DiffuseColor = col
    try:   # PBR look in Rendered / Raytraced; the plain colour stays as fallback
        mat.ToPhysicallyBased()
        pbr = mat.PhysicallyBased
        pbr.BaseColor = Rhino.Display.Color4f(col)
        pbr.Metallic = float(metallic)
        pbr.Roughness = float(roughness)
    except Exception:
        pass
    return sc.doc.Materials.Add(mat)


def add_obj(geom, layer_idx, name=None, color=None):
    attr = Rhino.DocObjects.ObjectAttributes()
    attr.LayerIndex = layer_idx
    if name:
        attr.Name = name
    if color is not None:
        attr.ObjectColor = color
        attr.ColorSource = Rhino.DocObjects.ObjectColorSource.ColorFromObject
    table = sc.doc.Objects
    if isinstance(geom, rg.Mesh):
        return table.AddMesh(geom, attr)
    if isinstance(geom, rg.SubD):
        return table.AddSubD(geom, attr)
    if isinstance(geom, rg.Extrusion):
        return table.AddExtrusion(geom, attr)
    if isinstance(geom, rg.Brep):
        return table.AddBrep(geom, attr)
    if isinstance(geom, rg.PointCloud):
        return table.AddPointCloud(geom, attr)
    if isinstance(geom, rg.Line):
        return table.AddLine(geom, attr)
    return System.Guid.Empty


# =============================================================================
# Mesh diagnostics
# =============================================================================
def is_manifold(m):
    try:
        r = m.IsManifold()
        if isinstance(r, tuple):
            r = r[0]
        return bool(r)
    except Exception:
        return False


def open_loops(m):
    try:
        loops = m.GetNakedEdges()
        return len(loops) if loops else 0
    except Exception:
        return -1


def stats_line(m):
    return "V {}  F {} (quads {}, tris {})  pieces {}  closed {}  manifold {}  open loops {}".format(
        m.Vertices.Count, m.Faces.Count, m.Faces.QuadCount, m.Faces.TriangleCount,
        m.DisjointMeshCount, m.IsClosed, is_manifold(m), open_loops(m))


def size_line(m):
    bb = m.GetBoundingBox(True)
    k = 1.0 / mm()
    return "Size mm: X {:.0f}  Y {:.0f}  Z {:.0f}".format(
        (bb.Max.X - bb.Min.X) * k, (bb.Max.Y - bb.Min.Y) * k, (bb.Max.Z - bb.Min.Z) * k)


# =============================================================================
# Mode 1 steps: AI mesh -> CNC
# =============================================================================
MESH_FILTER = ("3D mesh (*.obj;*.stl;*.fbx;*.ply;*.3mf;*.glb;*.gltf)|"
               "*.obj;*.stl;*.fbx;*.ply;*.3mf;*.glb;*.gltf|All files (*.*)|*.*||")


def get_input_meshes():
    """Returns (mesh ids, label) or (None, None)."""
    ids = rs.GetObjects("Select the AI mesh(es) - or press Enter to import a file",
                        rs.filter.mesh, preselect=True)
    if ids:
        ids = list(ids)
        doc_name = os.path.splitext(sc.doc.Name or "")[0]
        return ids, rs.ObjectName(ids[0]) or doc_name or "ai_mesh"
    path = rs.OpenFileName("Import AI mesh", MESH_FILTER)
    if not path:
        return None, None
    if os.path.splitext(path)[1].lower() in (".glb", ".gltf") and RHINO_VER < 8:
        rs.MessageBox("Rhino 7 cannot import GLB / glTF.\n"
                      "Download OBJ or FBX from the generator instead.", 48, TITLE)
        return None, None
    before = set(str(o.Id) for o in sc.doc.Objects)
    if not sc.doc.Import(path):
        rs.MessageBox("Import failed:\n" + path, 16, TITLE)
        return None, None
    new_ids = [o.Id for o in sc.doc.Objects
               if str(o.Id) not in before and isinstance(o.Geometry, rg.Mesh)]
    if not new_ids:
        rs.MessageBox("No mesh found in:\n" + path, 48, TITLE)
        return None, None
    return new_ids, os.path.splitext(os.path.basename(path))[0]


def combine(ids):
    m = rg.Mesh()
    for oid in ids:
        g = rs.coercemesh(oid)
        if g is not None:
            m.Append(g)
    return m


def basic_cleanup(m, log):
    n0 = m.Faces.Count
    m.Faces.CullDegenerateFaces()
    # AI exports split vertices along UV seams -> fake open edges. Welding closes them.
    # (Texture coordinates are dropped here; the textured original stays hidden.)
    m.Vertices.CombineIdentical(True, True)
    try:
        m.Faces.ExtractDuplicateFaces()
    except Exception:
        pass
    m.Vertices.CullUnused()
    m.Compact()
    log.add("Cleanup: faces {} -> {} (degenerate + duplicate faces removed, vertices welded)".format(
        n0, m.Faces.Count))


def orient_up(m, axis, log):
    bb = m.GetBoundingBox(True)
    dx, dy, dz = bb.Max.X - bb.Min.X, bb.Max.Y - bb.Min.Y, bb.Max.Z - bb.Min.Z
    if axis not in ("x", "y", "z"):          # auto: the tallest side becomes Z
        if dz >= 0.95 * max(dx, dy):
            axis = "z"
        elif dy >= dx:
            axis = "y"
        else:
            axis = "x"
    if axis == "y":      # glTF / most OBJ exports: Y up, front +Z -> front ends up at -Y
        m.Transform(rg.Transform.Rotation(math.pi / 2.0, rg.Vector3d.XAxis, bb.Center))
        log.add("Up axis: Y -> rotated +90 deg about X")
    elif axis == "x":
        m.Transform(rg.Transform.Rotation(-math.pi / 2.0, rg.Vector3d.YAxis, bb.Center))
        log.add("Up axis: X -> rotated -90 deg about Y")
    else:
        log.add("Up axis: Z (no rotation)")


def scale_and_place(m, height_doc, log):
    bb = m.GetBoundingBox(True)
    h = bb.Max.Z - bb.Min.Z
    if height_doc > 0 and h > 1e-9:
        f = height_doc / h
        m.Transform(rg.Transform.Scale(rg.Point3d(bb.Center.X, bb.Center.Y, bb.Min.Z), f))
        log.add("Scale: x{:.4f} -> height {:.0f} mm".format(f, height_doc / mm()))
    bb = m.GetBoundingBox(True)
    m.Transform(rg.Transform.Translation(rg.Vector3d(-bb.Center.X, -bb.Center.Y, -bb.Min.Z)))
    log.add("Placed: centred on the origin, base on Z = 0")


def _inside(container, piece, tol):
    bc = container.GetBoundingBox(True)
    bp = piece.GetBoundingBox(True)
    if not (bc.Contains(bp.Min) and bc.Contains(bp.Max)):
        return False
    n = piece.Vertices.Count
    for i in (0, n // 2, n - 1):
        if not container.IsPointInside(rg.Point3d(piece.Vertices[i]), tol, True):
            return False
    return True


def remove_debris(m, pct, log):
    """Drop tiny floaters and closed shells that sit inside the main body."""
    pieces = m.SplitDisjointPieces()
    if pieces is None or len(pieces) <= 1:
        log.add("Loose pieces: 1")
        return m
    pieces = sorted(pieces, key=lambda p: p.Faces.Count, reverse=True)
    total = sum(p.Faces.Count for p in pieces)
    diag = m.GetBoundingBox(True).Diagonal.Length
    tol = sc.doc.ModelAbsoluteTolerance
    main = pieces[0]
    keep, floaters, inner = [main], 0, 0
    for p in pieces[1:]:
        small_count = p.Faces.Count < total * pct / 100.0
        small_size = p.GetBoundingBox(True).Diagonal.Length < 0.03 * diag
        if small_count and small_size:      # both small -> debris (spear/props survive)
            floaters += 1
            continue
        if main.IsClosed and p.IsClosed and _inside(main, p, tol):
            inner += 1
            continue
        keep.append(p)
    out = rg.Mesh()
    for p in keep:
        out.Append(p)
    out.Compact()
    log.add("Loose pieces: {} -> kept {}, dropped {} floaters + {} inner shells".format(
        len(pieces), len(keep), floaters, inner))
    return out


def heal(m, heal_doc, log):
    loops0 = open_loops(m)
    if loops0 and heal_doc > 0:
        m.HealNakedEdges(heal_doc)
        m.Vertices.CombineIdentical(True, True)
    if not is_manifold(m):
        try:
            hanging = m.ExtractNonManifoldEdges(True)
            log.add("Non-manifold: removed {} hanging faces".format(
                hanging.Faces.Count if hanging else 0))
        except Exception:
            pass
    if open_loops(m):
        m.FillHoles()
    m.UnifyNormals()
    if m.SolidOrientation() == -1:      # closed but inside-out
        m.Flip(True, True, True)
    m.RebuildNormals()
    m.Compact()
    log.add("Heal: open loops {} -> {}, closed {}".format(loops0, open_loops(m), m.IsClosed))


def _set(obj, name, value):
    try:
        setattr(obj, name, value)
    except Exception:
        pass


def watertight(m, s, log):
    mode = s.text("wrap")
    needed = (not m.IsClosed) or (not is_manifold(m))
    if mode == "never" or (mode != "always" and not needed):
        if needed:
            log.add("WARNING: mesh is still open / non-manifold (ShrinkWrap is off).")
        return m
    if RHINO_VER < 8:
        if needed:
            log.add("WARNING: mesh still open. ShrinkWrap needs Rhino 8. In Rhino 7 use MeshRepair, "
                    "or remesh in Blender (Voxel) / Meshy Remesh, then run this again.")
        return m
    edge = s.num("wrap_mm", 0.0) * mm()
    if edge <= 0:   # ~400 edges over the height: about 4.5 mm on a 1.8 m figure
        bb = m.GetBoundingBox(True)
        edge = max(bb.Max.Z - bb.Min.Z, bb.Diagonal.Length * 0.5) / 400.0
    p = rg.ShrinkWrapParameters()
    _set(p, "TargetEdgeLength", float(edge))
    _set(p, "Offset", 0.0)
    _set(p, "SmoothingIterations", 1)
    _set(p, "FillHolesInInputObjects", True)
    _set(p, "InflateVerticesAndPoints", False)
    _set(p, "PolygonOptimization", 25)
    log.add("ShrinkWrap: edge {:.2f} mm (takes a while on big meshes) ...".format(edge / mm()))
    wrapped = m.ShrinkWrap(p)
    if wrapped is None or not wrapped.IsValid or wrapped.Faces.Count == 0:
        log.add("WARNING: ShrinkWrap failed - keeping the healed mesh.")
        return m
    wrapped.RebuildNormals()
    wrapped.Compact()
    log.add("ShrinkWrap OK: faces {} -> {}, closed {}".format(m.Faces.Count, wrapped.Faces.Count,
                                                              wrapped.IsClosed))
    return wrapped


def thin_wall_points(m, min_wall_doc, max_samples=20000):
    """Cast a ray inward from each sampled vertex; a hit closer than min_wall = thin."""
    m.Normals.ComputeNormals()
    pts = m.Vertices.ToPoint3dArray()
    n = len(pts)
    step = max(1, n // max_samples)
    eps = max(sc.doc.ModelAbsoluteTolerance, min_wall_doc * 0.002)
    flagged, tested = [], 0
    for i in range(0, n, step):
        nv = m.Normals[i]
        d = rg.Vector3d(-nv.X, -nv.Y, -nv.Z)
        length = d.Length
        if length < 1e-12:
            continue
        d = d / length
        t = Intersection.MeshRay(m, rg.Ray3d(pts[i] + d * eps, d))
        tested += 1
        if 0 <= t and (t + eps) < min_wall_doc:
            flagged.append(pts[i])
        if tested % 2000 == 0:
            check_escape()
    return flagged, tested


def _tri_area(a, b, c):
    return 0.5 * rg.Vector3d.CrossProduct(b - a, c - a).Length


def undercut_analysis(m_full, max_faces=80000):
    """Classify faces by tool access straight down (top setup) and straight up
    (flipped block). 'neither' = undercut for 2-sided 3-axis machining."""
    m = m_full
    if m_full.Faces.Count > max_faces:          # analyse a lighter copy
        m = m_full.DuplicateMesh()
        m.Reduce(int(max_faces), True, 5, False)
    m.FaceNormals.ComputeFaceNormals()
    verts = m.Vertices.ToPoint3dArray()
    eps = sc.doc.ModelAbsoluteTolerance * 5.0
    up = rg.Vector3d(0, 0, 1)
    down = rg.Vector3d(0, 0, -1)
    areas = {"top": 0.0, "bottom": 0.0, "both": 0.0, "neither": 0.0}
    neither = []
    count = m.Faces.Count
    for fi in range(count):
        f = m.Faces[fi]
        area = _tri_area(verts[f.A], verts[f.B], verts[f.C])
        if f.IsQuad:
            area += _tri_area(verts[f.A], verts[f.C], verts[f.D])
        nf = m.FaceNormals[fi]
        start = m.Faces.GetFaceCenter(fi) + rg.Vector3d(nf.X, nf.Y, nf.Z) * eps
        top = nf.Z > -0.02 and Intersection.MeshRay(m, rg.Ray3d(start + up * eps, up)) < 0
        bottom = nf.Z < 0.02 and Intersection.MeshRay(m, rg.Ray3d(start + down * eps, down)) < 0
        if top and bottom:
            key = "both"
        elif top:
            key = "top"
        elif bottom:
            key = "bottom"
        else:
            key = "neither"
            neither.append(fi)
        areas[key] += area
        if fi % 5000 == 0:
            check_escape()
    undercut_mesh = None
    if neither:
        undercut_mesh = m.DuplicateMesh().Faces.ExtractFaces(net_list(neither, int))
    return areas, undercut_mesh


def foam_grid(bbox, block):
    """Pure helper. bbox = (x0, y0, z0, x1, y1, z1), block = (bx, by, bz).
    Grid centred on the part in X/Y, starting at the part bottom in Z."""
    sizes = (bbox[3] - bbox[0], bbox[4] - bbox[1], bbox[5] - bbox[2])
    counts = [max(1, int(math.ceil(sizes[i] / block[i] - 1e-9))) for i in range(3)]
    x0 = (bbox[0] + bbox[3]) * 0.5 - counts[0] * block[0] * 0.5
    y0 = (bbox[1] + bbox[4]) * 0.5 - counts[1] * block[1] * 0.5
    z0 = bbox[2]
    boxes = []
    for ix in range(counts[0]):
        for iy in range(counts[1]):
            for iz in range(counts[2]):
                a = (x0 + ix * block[0], y0 + iy * block[1], z0 + iz * block[2])
                boxes.append((a[0], a[1], a[2], a[0] + block[0], a[1] + block[1], a[2] + block[2]))
    return tuple(counts), boxes


def quad_remesh(m, target, log):
    qp = rg.QuadRemeshParameters()
    qp.TargetQuadCount = int(target)
    qp.AdaptiveSize = 50.0
    qp.AdaptiveQuadCount = True
    qp.DetectHardEdges = True
    qp.PreserveMeshArrayEdgesMode = 0
    log.add("QuadRemesh: target {} quads ...".format(int(target)))
    q = m.QuadRemesh(qp)
    if q is None or q.Faces.Count == 0:
        log.add("WARNING: QuadRemesh failed.")
        return None
    log.add("QuadRemesh OK: {} faces ({} quads), closed {}".format(q.Faces.Count, q.Faces.QuadCount,
                                                                   q.IsClosed))
    return q


# ---- binary STL (pure Python, no export dialogs) ----------------------------
def _ascii_bytes(text):
    return text.encode("ascii", "replace") if PY3 else str(text)


def write_binary_stl(path, verts, tris, header="Styro3D"):
    """verts: [(x, y, z)], tris: [(i, j, k)] -> binary STL."""
    pack = struct.pack
    empty = pack("")
    f = open(path, "wb")
    try:
        f.write(pack("<80s", _ascii_bytes(header)[:80]))
        f.write(pack("<I", len(tris)))
        chunk = []
        for (a, b, c) in tris:
            ax, ay, az = verts[a]
            bx, by, bz = verts[b]
            cx, cy, cz = verts[c]
            ux, uy, uz = bx - ax, by - ay, bz - az
            vx, vy, vz = cx - ax, cy - ay, cz - az
            nx, ny, nz = uy * vz - uz * vy, uz * vx - ux * vz, ux * vy - uy * vx
            ln = math.sqrt(nx * nx + ny * ny + nz * nz) or 1.0
            chunk.append(pack("<12fH", nx / ln, ny / ln, nz / ln,
                              ax, ay, az, bx, by, bz, cx, cy, cz, 0))
            if len(chunk) >= 20000:
                f.write(empty.join(chunk))
                chunk = []
        if chunk:
            f.write(empty.join(chunk))
    finally:
        f.close()


def export_stl_mm(m, path, header="Styro3D CNC mesh, units mm"):
    k = 1.0 / mm()
    verts = [(p.X * k, p.Y * k, p.Z * k) for p in m.Vertices.ToPoint3dArray()]
    idx = list(m.Faces.ToIntArray(True))
    tris = [(idx[i], idx[i + 1], idx[i + 2]) for i in range(0, len(idx) - 2, 3)]
    write_binary_stl(path, verts, tris, header)
    return len(tris)


# ---- previews ------------------------------------------------------------------
def _preview_view():
    view = sc.doc.Views.Find("Perspective", False)
    if view is None:
        view = sc.doc.Views.ActiveView
    if view is not None:
        sc.doc.Views.ActiveView = view
    return view


def save_preview(path, ids, mode_name, px=1400, cam_dir=(0.55, -1.0, 0.30)):
    """Capture only `ids` in display mode `mode_name` (Arctic, Rendered, Wireframe...)."""
    ids = [i for i in ids if i and i != System.Guid.Empty]
    view = _preview_view()
    if view is None or not ids:
        return False
    vp = view.ActiveViewport
    old_mode = vp.DisplayMode
    keep = set(str(i) for i in ids)
    hidden = [o for o in (rs.NormalObjects() or []) if str(o) not in keep]
    try:
        if hidden:
            rs.HideObjects(hidden)
        mode = Rhino.Display.DisplayModeDescription.FindByName(mode_name)
        if mode is not None:
            vp.DisplayMode = mode
        bb = rg.BoundingBox.Empty
        for oid in ids:
            obj = sc.doc.Objects.FindId(oid)
            if obj is not None:
                bb = rg.BoundingBox.Union(bb, obj.Geometry.GetBoundingBox(True))
        if not bb.IsValid:
            return False
        try:
            vp.ChangeToPerspectiveProjection(True, 50.0)
        except Exception:
            pass
        d = rg.Vector3d(cam_dir[0], cam_dir[1], cam_dir[2])
        d = d / d.Length
        c = bb.Center
        vp.SetCameraLocations(c, c + d * (bb.Diagonal.Length * 2.0))
        vp.ZoomBoundingBox(bb)
        view.Redraw()
        width, height = int(px), int(px * 1.25)
        cap = Rhino.Display.ViewCapture()
        cap.Width = width
        cap.Height = height
        cap.ScaleScreenItems = False
        cap.DrawAxes = False
        cap.DrawGrid = False
        cap.DrawGridAxes = False
        cap.TransparentBackground = False
        bmp = cap.CaptureToBitmap(view)
        if bmp is None:
            bmp = view.CaptureToBitmap(System.Drawing.Size(width, height))
        if bmp is None:
            return False
        try:
            bmp.Save(path, System.Drawing.Imaging.ImageFormat.Png)
        except Exception:
            bmp.Save(path)    # in-memory bitmaps default to PNG
        bmp.Dispose()
        return True
    finally:
        if hidden:
            rs.ShowObjects(hidden)
        try:
            vp.DisplayMode = old_mode
        except Exception:
            pass
        view.Redraw()


def finish_message(log, out_dir):
    msg = "\n".join(log.lines[-14:]) + "\n\nOpen the output folder?"
    if rs.MessageBox(msg, 4 | 64, TITLE) == 6 and os.name == "nt":
        try:
            System.Diagnostics.Process.Start("explorer.exe", '"{}"'.format(out_dir))
        except Exception:
            pass


# ---- the pipeline -----------------------------------------------------------
def cnc_pipeline(mesh, s, label, orient=True, debris=True, log=None):
    k = mm()
    log = log or Report(label)
    out_dir = output_dir(s, label)
    name = safe_name(label)
    log.add("Output folder: " + out_dir)
    log.add("IN    " + stats_line(mesh))

    rs.EnableRedraw(False)
    basic_cleanup(mesh, log)
    if orient:
        orient_up(mesh, s.text("up_axis"), log)
        scale_and_place(mesh, s.num("height_mm", 0.0) * k, log)
    if debris and s.num("debris_pct", 0.0) > 0:
        mesh = remove_debris(mesh, s.num("debris_pct", 0.5), log)
    heal(mesh, max(s.num("heal_mm", 0.5), 0.0) * k, log)
    check_escape()
    mesh = watertight(mesh, s, log)
    mesh.RebuildNormals()
    mesh.Compact()
    log.add("CNC   " + stats_line(mesh))
    log.add(size_line(mesh))

    cnc_id = add_obj(mesh, ensure_layer("S3D::01_CNC_Mesh", Color.FromArgb(236, 236, 230)),
                     name + "_CNC")
    check_ids = [cnc_id]

    # ---------------- CNC checks ----------------
    log.add("")
    log.add("--- CNC CHECKS ---")
    wall = s.num("min_wall_mm", 0.0)
    if wall > 0:
        pts, tested = thin_wall_points(mesh, wall * k)
        log.add("Thin walls < {:.0f} mm: {} of {} sampled points ({:.1f}%)".format(
            wall, len(pts), tested, 100.0 * len(pts) / max(tested, 1)))
        if pts:
            layer = ensure_layer("S3D::04_Check_ThinWalls", Color.FromArgb(230, 30, 30))
            check_ids.append(add_obj(rg.PointCloud(net_list(pts, rg.Point3d)), layer, "thin_walls"))
            log.add("  red points: thicken these, or make them from denser foam / wood / ACP")

    areas, undercut_mesh = undercut_analysis(mesh)
    total = sum(areas.values()) or 1.0
    log.add("Tool access by surface area (3-axis, top setup + flipped setup):")
    for key, text in (("top", "top setup only"), ("bottom", "flipped setup only"),
                      ("both", "either setup"),
                      ("neither", "UNDERCUT - side setup / robot / split")):
        log.add("  {:<38} {:5.1f}%".format(text, 100.0 * areas[key] / total))
    if undercut_mesh is not None and undercut_mesh.Faces.Count:
        layer = ensure_layer("S3D::05_Check_Undercuts", Color.FromArgb(220, 0, 200))
        check_ids.append(add_obj(undercut_mesh, layer, "undercuts"))

    bb = mesh.GetBoundingBox(True)
    block = (s.num("block_x", 0.0), s.num("block_y", 0.0), s.num("block_z", 0.0))
    n_blocks = 0
    if min(block) > 0:
        counts, boxes = foam_grid((bb.Min.X, bb.Min.Y, bb.Min.Z, bb.Max.X, bb.Max.Y, bb.Max.Z),
                                  (block[0] * k, block[1] * k, block[2] * k))
        layer = ensure_layer("S3D::06_Foam_Blocks", Color.FromArgb(40, 140, 255))
        for (x0, y0, z0, x1, y1, z1) in boxes:
            for line in rg.BoundingBox(rg.Point3d(x0, y0, z0), rg.Point3d(x1, y1, z1)).GetEdges():
                add_obj(line, layer)
        n_blocks = counts[0] * counts[1] * counts[2]
        log.add("Foam blocks {:.0f} x {:.0f} x {:.0f} mm: {} x {} x {} = {} blocks".format(
            block[0], block[1], block[2], counts[0], counts[1], counts[2], n_blocks))
    if mesh.IsClosed:
        vol_m3 = mesh.Volume() / (k ** 3) * 1e-9
        density = s.num("density", 20.0)
        log.add("Part volume {:.3f} m3 -> EPS {:.0f} kg/m3 = {:.1f} kg".format(
            vol_m3, density, vol_m3 * density))
        if n_blocks:
            stock = n_blocks * block[0] * block[1] * block[2] * 1e-9
            log.add("Stock {:.3f} m3 -> material yield {:.0f}%".format(stock, 100.0 * vol_m3 / stock))
    else:
        log.add("Volume: n/a (mesh not closed)")

    # ---------------- editable / render versions ----------------
    log.add("")
    topo_id = None
    if int(s.num("quads", 0)) > 0:
        check_escape()
        quads = quad_remesh(mesh, s.num("quads", 0), log)
        if quads is not None:
            topo_id = add_obj(quads, ensure_layer("S3D::02_QuadMesh", Color.FromArgb(110, 190, 110)),
                              name + "_Quads")
            if s.flag("subd"):
                subd = rg.SubD.CreateFromMesh(quads)
                if subd is not None:
                    topo_id = add_obj(subd, ensure_layer("S3D::03_SubD", Color.FromArgb(140, 140, 220)),
                                      name + "_SubD")
                    log.add("SubD created (edit with Gumball / SubD tools; ToNURBS for NURBS)")
                else:
                    log.add("WARNING: SubD conversion failed (quad mesh kept)")

    rs.EnableRedraw(True)
    if s.flag("png"):
        shots = [("clay", [cnc_id], "Arctic"), ("checks", check_ids, "Shaded")]
        if topo_id is not None:
            shots.append(("topology", [topo_id], "Wireframe"))
        for tag, ids, mode in shots:
            path = os.path.join(out_dir, "{}_{}.png".format(name, tag))
            if save_preview(path, ids, mode):
                log.add("Preview: " + path)

    if s.flag("stl"):
        path = os.path.join(out_dir, name + "_CNC_mm.stl")
        n_tri = export_stl_mm(mesh, path)
        log.add("STL (binary, mm): {} ({} triangles)".format(path, n_tri))

    log.add("Layers: S3D::01_CNC_Mesh (STL source), 02_QuadMesh, 03_SubD, 04/05 checks, 06 blocks")
    report = os.path.join(out_dir, name + "_report.txt")
    log.save(report)
    log.add("Report: " + report)
    sc.doc.Views.Redraw()
    finish_message(log, out_dir)
    return cnc_id


def mode_ai_mesh():
    s = Settings(CNC_SPEC)
    if not s.ask(TITLE + " | AI mesh -> CNC"):
        return
    ids, label = get_input_meshes()
    if not ids:
        return
    mesh = combine(ids)
    if mesh.Faces.Count == 0:
        rs.MessageBox("The selection has no mesh faces.", 48, TITLE)
        return
    rs.HideObjects(ids)                      # original stays untouched, just hidden
    cnc_pipeline(mesh, s, label, orient=True, debris=True)


# =============================================================================
# Mode 2: Roman legionary from code (SubD body + NURBS hard surface)
# =============================================================================
# Coordinates: mm, figure 1750 tall, Z up, facing -Y (Front view looks at the face).
# +X = the figure's LEFT (shield side), -X = RIGHT (spear and sword side).

LEG_MATERIALS = {
    # key: (layer name, rgb, metallic, roughness)
    "skin":    ("Skin",    (222, 170, 136), 0.0, 0.55),
    "tunic":   ("Tunic",   (146, 22, 28),   0.0, 0.85),
    "steel":   ("Steel",   (186, 190, 196), 1.0, 0.30),
    "brass":   ("Brass",   (200, 152, 62),  1.0, 0.28),
    "leather": ("Leather", (96, 60, 36),    0.0, 0.70),
    "wood":    ("Wood",    (126, 86, 52),   0.0, 0.65),
    "shield":  ("Shield",  (158, 26, 24),   0.0, 0.55),
    "crest":   ("Crest",   (196, 22, 26),   0.0, 0.90),
    "iron":    ("Iron",    (74, 76, 80),    1.0, 0.45),
    "base":    ("Base",    (58, 58, 62),    0.0, 0.60),
}

TORSO = [  # z, half-width X, half-depth Y, centre Y
    (860.0, 150.0, 106.0, 0.0),
    (930.0, 166.0, 116.0, 0.0),
    (1040.0, 148.0, 104.0, 0.0),
    (1180.0, 166.0, 118.0, -4.0),
    (1310.0, 182.0, 122.0, -6.0),
    (1405.0, 176.0, 108.0, 0.0),
    (1450.0, 112.0, 72.0, 4.0),
    (1480.0, 62.0, 52.0, 6.0),
]

SKIRT = [  # z, rx, ry, cy  (tunic below the armour)
    (1005.0, 160.0, 114.0, 0.0),
    (930.0, 176.0, 124.0, 2.0),
    (830.0, 196.0, 138.0, 4.0),
    (718.0, 214.0, 150.0, 6.0),
]

ARMS = {   # side: (shoulder -> wrist path, fist path)
    -1: ([(-176, 0, 1410), (-210, 4, 1282), (-238, 12, 1142), (-252, -70, 1092), (-264, -168, 1042)],
         [(-264, -168, 1042), (-267, -214, 1024), (-269, -258, 1008)]),
    1: ([(176, 0, 1410), (212, 6, 1282), (240, 16, 1150), (266, -40, 1052), (292, -112, 962)],
        [(292, -112, 962), (303, -140, 950), (313, -168, 938)]),
}


# ---- pure vector maths (tuples) -----------------------------------------------
def v_add(a, b):
    return (a[0] + b[0], a[1] + b[1], a[2] + b[2])


def v_sub(a, b):
    return (a[0] - b[0], a[1] - b[1], a[2] - b[2])


def v_mul(a, f):
    return (a[0] * f, a[1] * f, a[2] * f)


def v_dot(a, b):
    return a[0] * b[0] + a[1] * b[1] + a[2] * b[2]


def v_cross(a, b):
    return (a[1] * b[2] - a[2] * b[1], a[2] * b[0] - a[0] * b[2], a[0] * b[1] - a[1] * b[0])


def v_unit(a):
    ln = math.sqrt(v_dot(a, a))
    return (a[0] / ln, a[1] / ln, a[2] / ln) if ln > 1e-12 else (0.0, 0.0, 1.0)


def torso_at(z):
    """(rx, ry, cy) of the torso at height z (linear between TORSO rows)."""
    t = TORSO
    if z <= t[0][0]:
        return t[0][1:]
    if z >= t[-1][0]:
        return t[-1][1:]
    for i in range(len(t) - 1):
        z0, z1 = t[i][0], t[i + 1][0]
        if z0 <= z <= z1:
            f = (z - z0) / (z1 - z0)
            return tuple(t[i][j] + (t[i + 1][j] - t[i][j]) * f for j in (1, 2, 3))
    return t[-1][1:]


def tube_cage(path, radii, ref=(1.0, 0.0, 0.0), segs=8, cap_bulge=0.6):
    """All-quad closed control cage around a polyline (rings of `segs` points,
    `segs` must be even). Ring frame: x = `ref` made perpendicular to the path,
    y = dir x x, so faces wind outward. Returns (verts, faces) as plain tuples."""
    n = len(path)
    dirs = [v_unit(v_sub(path[min(i + 1, n - 1)], path[max(i - 1, 0)])) for i in range(n)]
    verts, faces = [], []
    for i in range(n):
        d = dirs[i]
        x = v_unit(v_sub(ref, v_mul(d, v_dot(ref, d))))
        y = v_cross(d, x)
        rx, ry = radii[i]
        for k in range(segs):
            a = 2.0 * math.pi * k / segs
            verts.append(v_add(path[i], v_add(v_mul(x, rx * math.cos(a)), v_mul(y, ry * math.sin(a)))))
    for i in range(n - 1):
        for k in range(segs):
            k2 = (k + 1) % segs
            faces.append((i * segs + k, i * segs + k2, (i + 1) * segs + k2, (i + 1) * segs + k))
    # quad caps: one centre vertex + segs/2 quads
    end = len(verts)
    verts.append(v_add(path[-1], v_mul(dirs[-1], cap_bulge * min(radii[-1]))))
    base = (n - 1) * segs
    for j in range(0, segs, 2):
        faces.append((base + j, base + (j + 1) % segs, base + (j + 2) % segs, end))
    start = len(verts)
    verts.append(v_sub(path[0], v_mul(dirs[0], cap_bulge * min(radii[0]))))
    for j in range(0, segs, 2):
        faces.append(((j + 2) % segs, (j + 1) % segs, j, start))
    return verts, faces


def arc_band_math(s_half, drop, peak, t):
    """Shoulder-guard band cross-section in (y, z): outer and inner 3-point arcs."""
    r = (s_half ** 2 + drop ** 2) / (2.0 * drop)
    zc = peak - r
    a = math.asin(min(1.0, s_half / r))
    ri = r - t
    outer = [(-s_half, peak - drop), (0.0, peak), (s_half, peak - drop)]
    inner = [(ri * math.sin(a), zc + ri * math.cos(a)), (0.0, zc + ri),
             (-ri * math.sin(a), zc + ri * math.cos(a))]
    return outer, inner


# ---- Rhino geometry helpers (build in mm) -----------------------------------
def P(x, y, z):
    return rg.Point3d(x, y, z)


def V(x, y, z):
    return rg.Vector3d(x, y, z)


def unit(v):
    return v / v.Length


def subd_from_cage(verts, faces):
    m = rg.Mesh()
    for p in verts:
        m.Vertices.Add(p[0], p[1], p[2])
    for f in faces:
        m.Faces.AddFace(f[0], f[1], f[2], f[3])
    m.Normals.ComputeNormals()
    m.Compact()
    subd = rg.SubD.CreateFromMesh(m)
    return subd if subd is not None else m


def join_curves(curves):
    joined = rg.Curve.JoinCurves(net_list(curves, rg.Curve), BUILD_TOL)
    return joined[0] if joined and len(joined) > 0 else None


def smooth_closed(points):
    return rg.Curve.CreateInterpolatedCurve(net_list(points, rg.Point3d), 3,
                                            rg.CurveKnotStyle.ChordPeriodic)


def ellipse_crv(cx, cy, z, rx, ry):
    plane = rg.Plane(P(cx, cy, z), rg.Vector3d.XAxis, rg.Vector3d.YAxis)
    return rg.Ellipse(plane, rx, ry).ToNurbsCurve()


def capped_loft(curves):
    breps = rg.Brep.CreateFromLoft(net_list(curves, rg.Curve), rg.Point3d.Unset, rg.Point3d.Unset,
                                   rg.LoftType.Normal, False)
    if not breps:
        return None
    b = breps[0]
    if not b.IsSolid:
        capped = b.CapPlanarHoles(BUILD_TOL)
        if capped is not None:
            b = capped
    return b


def extrude_span(curve, axis, a0, length):
    """Extrude a planar closed curve by `length`, then move it to span
    [a0, a0 + length] along world axis 0/1/2 (works whichever way it went)."""
    if curve is None:
        return None
    ext = rg.Extrusion.Create(curve, length, True)
    if ext is None:
        return None
    b = ext.ToBrep(True)
    bb = b.GetBoundingBox(True)
    shift = [0.0, 0.0, 0.0]
    shift[axis] = a0 - (bb.Min.X, bb.Min.Y, bb.Min.Z)[axis]
    b.Transform(rg.Transform.Translation(V(shift[0], shift[1], shift[2])))
    return b


def sphere(c, r):
    return rg.Brep.CreateFromSphere(rg.Sphere(c, r))


def cyl(p0, p1, r):
    d = p1 - p0
    return rg.Brep.CreateFromCylinder(rg.Cylinder(rg.Circle(rg.Plane(p0, d), r), d.Length), True, True)


def cone(apex, base_centre, r):
    d = base_centre - apex                     # Rhino cones: apex at the plane origin
    return rg.Brep.CreateFromCone(rg.Cone(rg.Plane(apex, d), d.Length, r), True)


def box(c, sx, sy, sz):
    plane = rg.Plane(c, rg.Vector3d.XAxis, rg.Vector3d.YAxis)
    return rg.Brep.CreateFromBox(rg.Box(plane, rg.Interval(-sx / 2.0, sx / 2.0),
                                        rg.Interval(-sy / 2.0, sy / 2.0),
                                        rg.Interval(-sz / 2.0, sz / 2.0)))


def revolve(curve, a0=None, a1=None, cap=False):
    """Revolve around the local Z axis (helmet parts are built around the origin).
    cap=True closes the two flat sector ends of a partial revolve."""
    if curve is None:
        return None
    axis = rg.Line(P(0, 0, -1), P(0, 0, 1))
    if a0 is None:
        rev = rg.RevSurface.Create(curve, axis)
    else:
        rev = rg.RevSurface.Create(curve, axis, a0, a1)
    if rev is None:
        return None
    # CreateFromRevSurface's own cap flags only cover full 360 deg revolves
    b = rg.Brep.CreateFromRevSurface(rev, False, False)
    if b is None:
        return None
    b.Faces.SplitKinkyFaces(math.radians(1.0), True)
    if cap and not b.IsSolid:
        capped = b.CapPlanarHoles(BUILD_TOL)
        if capped is not None:
            b = capped
    return b


def rect_section(centre, d, width, thick):
    """Closed rectangle around `centre`, normal ~ d; width along world Y, thickness along X."""
    w = unit(V(0, 1, 0) - d * (d * V(0, 1, 0)))
    t = rg.Vector3d.CrossProduct(d, w)
    pts = [centre + w * (width / 2.0) + t * (thick / 2.0), centre - w * (width / 2.0) + t * (thick / 2.0),
           centre - w * (width / 2.0) - t * (thick / 2.0), centre + w * (width / 2.0) - t * (thick / 2.0)]
    pts.append(pts[0])
    return rg.Polyline(net_list(pts, rg.Point3d)).ToNurbsCurve()


def curved_plate_profile(alpha, r_out, r_in, cy):
    """Ring sector r_in..r_out around (0, cy) in the XY plane, convex side to -Y."""
    def pt(r, a):
        return P(r * math.sin(a), cy - r * math.cos(a), 0.0)
    segs = [rg.ArcCurve(rg.Arc(pt(r_out, -alpha), pt(r_out, 0.0), pt(r_out, alpha))),
            rg.LineCurve(pt(r_out, alpha), pt(r_in, alpha)),
            rg.ArcCurve(rg.Arc(pt(r_in, alpha), pt(r_in, 0.0), pt(r_in, -alpha))),
            rg.LineCurve(pt(r_in, -alpha), pt(r_out, -alpha))]
    return join_curves(segs)


# ---- the figure -----------------------------------------------------------------
def build_body(add):
    path = [(0.0, row[3], row[0]) for row in TORSO]
    radii = [(row[1] * 1.06, row[2] * 1.06) for row in TORSO]   # cage > limit surface
    add(subd_from_cage(*tube_cage(path, radii, segs=12)), "tunic", "torso")
    add(subd_from_cage(*tube_cage([(0, 4, 1440), (0, 2, 1505), (0, 0, 1565)],
                                  [(60, 54), (56, 50), (58, 52)])), "skin", "neck")
    add(subd_from_cage(*tube_cage([(0, -2, 1532), (0, -4, 1566), (0, -6, 1615), (0, -6, 1672),
                                   (0, -4, 1722), (0, -2, 1754)],
                                  [(50, 56), (72, 84), (84, 98), (86, 100), (74, 88), (40, 46)])),
        "skin", "head")
    add(subd_from_cage(*tube_cage([(0, -90, 1636), (0, -104, 1622), (0, -116, 1608)],
                                  [(15, 16), (12, 12), (8, 8)])), "skin", "nose")
    for s in (-1, 1):
        side = "R" if s < 0 else "L"
        add(subd_from_cage(*tube_cage(
            [(s * 92, 0, 935), (s * 95, -2, 740), (s * 100, -8, 505), (s * 102, -2, 360), (s * 106, 6, 112)],
            [(94, 90), (80, 78), (60, 60), (62, 60), (42, 42)])), "skin", "leg_" + side)
        add(subd_from_cage(*tube_cage(
            [(s * 108, 55, 58), (s * 110, 5, 52), (s * 114, -85, 40), (s * 118, -172, 30)],
            [(44, 44), (52, 42), (56, 32), (46, 22)])), "leather", "foot_" + side)
        arm, fist = ARMS[s]
        add(subd_from_cage(*tube_cage(arm, [(60, 60), (54, 52), (46, 46), (44, 42), (34, 30)])),
            "skin", "arm_" + side)
        add(subd_from_cage(*tube_cage(fist, [(36, 32), (48, 42), (42, 38)])), "skin", "fist_" + side)


def build_tunic(add):
    add(capped_loft([ellipse_crv(0, cy, z, rx, ry) for (z, rx, ry, cy) in SKIRT]), "tunic", "tunic_skirt")
    for s in (-1, 1):
        a0, a1 = P(*ARMS[s][0][0]), P(*ARMS[s][0][1])
        d = unit(a1 - a0)
        rings = [rg.Circle(rg.Plane(a0 + d * 30.0, d), 70.0).ToNurbsCurve(),
                 rg.Circle(rg.Plane(a0 + d * 150.0, d), 64.0).ToNurbsCurve()]
        add(capped_loft(rings), "tunic", "sleeve_" + ("R" if s < 0 else "L"))


def build_armour(add, plate):
    # lorica segmentata girth hoops (solid frustums - CNC friendly, no thin shells)
    for i in range(7):
        zb = 1048.0 + i * 44.0
        zt = zb + 52.0
        rxb, ryb, cyb = torso_at(zb)
        rxt, ryt, cyt = torso_at(zt)
        add(capped_loft([ellipse_crv(0, cyb, zb, rxb + 14.0, ryb + 14.0),
                         ellipse_crv(0, cyt, zt, rxt + 9.0, ryt + 9.0)]), "steel", "hoop_{}".format(i + 1))
        zm = (zb + zt) * 0.5
        rxm, rym, cym = torso_at(zm)
        for sx in (-1, 1):
            add(box(P(sx * 26.0, cym - rym - 12.5, zm), 16.0, 5.0, 22.0), "brass", "buckle_{}".format(i + 1))
    # chest + collar plates
    rxb, ryb, cyb = torso_at(1346.0)
    rxt, ryt, cyt = torso_at(1420.0)
    add(capped_loft([ellipse_crv(0, cyb, 1346.0, rxb + 14.0, ryb + 14.0),
                     ellipse_crv(0, cyt, 1420.0, rxt * 0.86 + 8.0, ryt * 0.9 + 8.0)]), "steel", "chest_plates")
    add(capped_loft([ellipse_crv(0, 2.0, 1416.0, 118.0, 84.0),
                     ellipse_crv(0, 4.0, 1452.0, 90.0, 66.0)]), "steel", "collar_plates")
    y_front = 0.5 * ((cyb - ryb - 14.0) + (cyt - ryt * 0.9 - 8.0)) - 1.5
    for sx in (-1, 1):
        add(box(P(sx * 44.0, y_front, 1384.0), 22.0, 5.0, 26.0), "brass", "chest_buckle")
    # shoulder guards: 5 curved bands per side, built on +X (left) then mirrored
    t_band = max(5.0, plate)
    mirror = rg.Transform.Mirror(rg.Plane.WorldYZ)
    for i in range(5):
        xc = 150.0 + i * 24.0
        peak = 1436.0 - i * 22.0            # inner face sits on the shoulder
        outer, inner = arc_band_math(104.0 - i * 3.0, 70.0 + i * 13.0, peak, t_band)
        o = [P(xc, y, z) for (y, z) in outer]
        n = [P(xc, y, z) for (y, z) in inner]
        profile = join_curves([rg.ArcCurve(rg.Arc(o[0], o[1], o[2])), rg.LineCurve(o[2], n[0]),
                               rg.ArcCurve(rg.Arc(n[0], n[1], n[2])), rg.LineCurve(n[2], o[0])])
        band = extrude_span(profile, 0, xc - 16.0, 32.0)
        if band is None:
            continue
        band.Transform(rg.Transform.Rotation(math.radians(12.0 + 7.0 * i), rg.Vector3d.YAxis, P(xc, 0, peak)))
        add(band, "steel", "shoulder_L{}".format(i + 1))
        twin = band.DuplicateBrep()
        twin.Transform(mirror)
        add(twin, "steel", "shoulder_R{}".format(i + 1))


def build_belt(add, plate):
    rxb, ryb, cyb = torso_at(986.0)
    rxt, ryt, cyt = torso_at(1030.0)
    add(capped_loft([ellipse_crv(0, cyb, 986.0, rxb + 18.0, ryb + 18.0),
                     ellipse_crv(0, cyt, 1030.0, rxt + 16.0, ryt + 16.0)]), "leather", "belt")
    rx, ry = rxb + 17.0, ryb + 17.0
    for ang in (-60, -40, -20, 0, 20, 40, 60):
        phi = math.radians(ang)
        plate_box = box(P(0, 0, 0), 28.0, 6.0, 34.0)
        plate_box.Transform(rg.Transform.Rotation(phi, rg.Vector3d.ZAxis, P(0, 0, 0)))
        plate_box.Transform(rg.Transform.Translation(V(rx * math.sin(phi), cyb - ry * math.cos(phi), 1008.0)))
        add(plate_box, "brass", "belt_plate")
    # apron: 6 studded straps hanging from the belt, tilted 6 deg forward
    t_strap = max(5.0, plate)
    y_top = cyb - (ryb + 19.0)          # strap back face overlaps the belt by ~1.5 mm
    for i in range(6):
        x = -62.5 + 25.0 * i
        tilt = rg.Transform.Rotation(math.radians(-6.0), rg.Vector3d.XAxis, P(x, y_top, 986.0))
        pieces = [(box(P(x, y_top, 861.0), 18.0, t_strap, 250.0), "leather")]
        for j in range(5):
            pieces.append((sphere(P(x, y_top - t_strap / 2.0, 956.0 - 48.0 * j), 6.5), "brass"))
        for geom, key in pieces:
            geom.Transform(tilt)
            add(geom, key, "apron_{}".format(i + 1))


def build_helmet(add, plate):
    R = 112.0
    centre = V(0, -6, 1668)
    parts = []
    # dome + brim: one profile from the top pole to the bottom pole, revolved 360 deg
    pts = [P(0.99 * R, 0, -0.10 * R), P(1.17 * R, 0, -0.30 * R), P(1.15 * R, 0, -0.36 * R),
           P(0.96 * R, 0, -0.22 * R), P(0, 0, -0.22 * R)]
    segs = [rg.ArcCurve(rg.Arc(P(0, 0, R), P(R * 0.70710678, 0, R * 0.70710678), P(R, 0, 0))),
            rg.LineCurve(P(R, 0, 0), pts[0])]
    for i in range(len(pts) - 1):
        segs.append(rg.LineCurve(pts[i], pts[i + 1]))
    dome = revolve(join_curves(segs))
    if dome is None:   # fallback: plain sphere cap
        dome = sphere(P(0, 0, 0), R)
    parts.append((dome, "steel", "helmet_dome"))
    # neck guard: closed sloped profile revolved over the back (+Y) only
    t_ng = max(7.0, plate)
    ng = [P(0.95 * R, 0, -0.16 * R), P(1.50 * R, 0, -0.50 * R), P(1.47 * R, 0, -0.50 * R - t_ng),
          P(0.92 * R, 0, -0.16 * R - t_ng)]
    ng.append(ng[0])
    neck = revolve(rg.Polyline(net_list(ng, rg.Point3d)).ToNurbsCurve(),
                   math.radians(35.0), math.radians(145.0), cap=True)
    parts.append((neck, "steel", "helmet_neck_guard"))
    # cheek guards
    t_ck = max(5.0, plate)
    ck = [(-0.62, -0.18), (-0.10, -0.16), (0.12, -0.40), (0.04, -1.02), (-0.30, -1.10), (-0.56, -0.80)]
    cheek = extrude_span(smooth_closed([P(0.88 * R, y * R, z * R) for (y, z) in ck]), 0, 0.86 * R, t_ck)
    if cheek is not None:
        cheek.Transform(rg.Transform.Rotation(math.radians(8.0), rg.Vector3d.YAxis, P(0.88 * R, 0, -0.17 * R)))
        twin = cheek.DuplicateBrep()
        twin.Transform(rg.Transform.Mirror(rg.Plane.WorldYZ))
        parts.append((cheek, "steel", "cheek_guard_L"))
        parts.append((twin, "steel", "cheek_guard_R"))
    # crest: side profile, extruded across X
    cr = [(-0.70, 0.70), (-0.86, 1.16), (-0.56, 1.70), (0.0, 1.96), (0.56, 1.82), (0.96, 1.40),
          (1.06, 0.86), (0.72, 0.70), (0.0, 0.97), (-0.40, 0.90)]
    crest = extrude_span(smooth_closed([P(0, y * R, z * R) for (y, z) in cr]), 0, -0.23 * R, 0.46 * R)
    parts.append((crest, "crest", "crest"))
    move = rg.Transform.Translation(centre)
    for geom, key, name in parts:
        if geom is not None:
            geom.Transform(move)
            add(geom, key, name)


def build_shield(add, plate):
    H, W, Rs = 1080.0, 640.0, 560.0
    T = max(22.0, plate)
    alpha = math.asin((W / 2.0) / Rs)
    alpha_rim = math.asin((W / 2.0 + 4.0) / Rs)
    parts = [
        (extrude_span(curved_plate_profile(alpha, Rs, Rs - T, Rs), 2, 0.0, H), "shield", "shield"),
        (extrude_span(curved_plate_profile(alpha_rim, Rs + 4.0, Rs - T - 4.0, Rs), 2, -4.0, 30.0),
         "brass", "shield_rim_bottom"),
        (extrude_span(curved_plate_profile(alpha_rim, Rs + 4.0, Rs - T - 4.0, Rs), 2, H - 26.0, 30.0),
         "brass", "shield_rim_top"),
        (box(P(0, -4, H / 2.0), 28.0, 12.0, H * 0.86), "brass", "shield_spine"),
    ]
    # boss (umbo): spherical cap, 55 mm high, 92 mm base radius, flat back sunk into the plate
    h, a = 55.0, 92.0
    r = (a * a + h * h) / (2.0 * h)
    half = 0.5 * math.asin(a / r)
    cap_profile = join_curves([
        rg.ArcCurve(rg.Arc(P(0, 0, h), P(r * math.sin(half), 0, h - r + r * math.cos(half)), P(a, 0, 0))),
        rg.LineCurve(P(a, 0, 0), P(a, 0, -12.0)),
        rg.LineCurve(P(a, 0, -12.0), P(0, 0, -12.0))])
    boss = revolve(cap_profile)
    if boss is not None:   # cap axis +Z -> -Y (out of the shield face), centred on the face
        boss.Transform(rg.Transform.Rotation(math.pi / 2.0, rg.Vector3d.XAxis, P(0, 0, 0)))
        boss.Transform(rg.Transform.Translation(V(0, 0, H / 2.0)))
        parts.append((boss, "brass", "shield_boss"))
    # outer-face centre at the origin -> turn 35 deg to face front-left -> in front of the left fist
    xf = rg.Transform.Translation(V(358.0, -220.0, 900.0 - H / 2.0)) * \
        rg.Transform.Rotation(math.radians(35.0), rg.Vector3d.ZAxis, P(0, 0, 0))
    for geom, key, name in parts:
        if geom is not None:
            geom.Transform(xf)
            add(geom, key, name)


def build_spear(add):
    x, y = -267.0, -214.0          # through the right fist
    add(cyl(P(x, y, 14.0), P(x, y, 1560.0), 15.0), "wood", "pilum_shaft")
    add(box(P(x, y, 1592.0), 34.0, 34.0, 64.0), "wood", "pilum_block")
    add(cyl(P(x, y, 1624.0), P(x, y, 2050.0), 6.0), "iron", "pilum_shank")
    add(cone(P(x, y, 2140.0), P(x, y, 2050.0), 13.0), "iron", "pilum_tip")
    add(cone(P(x, y, 0.0), P(x, y, 48.0), 15.0), "iron", "pilum_butt")


def build_sword(add):
    top, bot = P(-206.0, 14.0, 916.0), P(-214.0, -18.0, 480.0)   # right hip, hilt clear of the elbow
    d = unit(bot - top)
    add(capped_loft([rect_section(top, d, 64.0, 24.0), rect_section(bot, d, 48.0, 20.0)]), "leather", "scabbard")
    for off in (30.0, 120.0):
        add(capped_loft([rect_section(top + d * off, d, 70.0, 30.0),
                         rect_section(top + d * (off + 14.0), d, 70.0, 30.0)]), "brass", "scabbard_band")
    add(sphere(bot + d * 4.0, 14.0), "brass", "scabbard_chape")
    add(capped_loft([rect_section(top - d * 2.0, d, 70.0, 34.0),
                     rect_section(top - d * 18.0, d, 70.0, 34.0)]), "brass", "sword_guard")
    add(cyl(top - d * 18.0, top - d * 100.0, 14.0), "wood", "sword_grip")
    add(sphere(top - d * 116.0, 24.0), "brass", "sword_pommel")


def build_legionary(s):
    """Returns [(geometry, material key, name)], already scaled to the model units."""
    plate = max(s.num("plate_mm", 6.0), 1.0)
    parts = []

    def add(geom, key, name):
        if geom is not None:
            parts.append((geom, key, name))

    build_body(add)
    build_tunic(add)
    build_armour(add, plate)
    build_belt(add, plate)
    build_helmet(add, plate)
    if s.flag("shield"):
        build_shield(add, plate)
    if s.flag("spear"):
        build_spear(add)
    if s.flag("sword"):
        build_sword(add)
    if s.flag("base"):
        add(cyl(P(0, -20, -36), P(0, -20, 24), 440.0), "base", "base_plinth")   # feet sink ~10 mm
    height = s.num("height_mm", FIGURE_BASE_MM)
    if height <= 0:
        height = FIGURE_BASE_MM
    xf = rg.Transform.Scale(rg.Point3d.Origin, height / FIGURE_BASE_MM * mm())
    for geom, _key, _name in parts:
        geom.Transform(xf)
    return parts


def parts_to_mesh(geoms, log, try_union=True):
    mp = rg.MeshingParameters.QualityRenderMesh
    pieces = []
    for g in geoms:
        m = None
        try:
            if isinstance(g, rg.SubD):
                m = rg.Mesh.CreateFromSubD(g, 4)
            elif isinstance(g, rg.Brep):
                faces = rg.Mesh.CreateFromBrep(g, mp)
                if faces:
                    m = rg.Mesh()
                    for f in faces:
                        m.Append(f)
            elif isinstance(g, rg.Mesh):
                m = g.DuplicateMesh()
        except Exception:
            m = None
        if m is not None and m.Faces.Count:
            m.Vertices.CombineIdentical(True, True)
            m.Compact()
            pieces.append(m)
    log.add("Meshed {} parts".format(len(pieces)))
    if try_union:
        log.add("Mesh boolean union (can take a minute) ...")
        try:
            result = rg.Mesh.CreateBooleanUnion(net_list(pieces, rg.Mesh))
            if result and len(result) > 0:
                union = rg.Mesh()
                for r in result:
                    union.Append(r)
                if union.Faces.Count:
                    log.add("Union OK: {} shell(s)".format(union.DisjointMeshCount))
                    return union
        except Exception:
            pass
        log.add("Union failed -> keeping overlapping closed shells "
                "(fine for 3-axis raster CAM; Rhino 8 ShrinkWrap merges them)")
    out = rg.Mesh()
    for p in pieces:
        out.Append(p)
    return out


def mode_build(then_cnc=False):
    s = Settings(BUILD_SPEC)
    if not s.ask(TITLE + " | Build legionary"):
        return
    rs.EnableRedraw(False)
    parts = build_legionary(s)
    material_idx = {}
    layer_idx = {}
    for key, (layer_name, color_rgb, metallic, roughness) in LEG_MATERIALS.items():
        material_idx[key] = ensure_material("S3D_" + layer_name, color_rgb, metallic, roughness)
        layer_idx[key] = ensure_layer("S3D_Legionary::" + layer_name, rgb(color_rgb), material_idx[key])
    ids = []
    for geom, key, name in parts:
        oid = add_obj(geom, layer_idx[key], name)
        if oid and oid != System.Guid.Empty:
            ids.append(oid)
    if ids:
        sc.doc.Groups.Add("S3D_Legionary_{}".format(time.strftime("%H%M%S")), net_list(ids, System.Guid))
    rs.EnableRedraw(True)
    print("{}: legionary built - {} parts on layers S3D_Legionary::*".format(TITLE, len(ids)))
    out_dir = None
    if s.flag("png") and ids:
        out_dir = output_dir(s, "Legionary")
        path = os.path.join(out_dir, "Legionary_render.png")
        if save_preview(path, ids, "Rendered", cam_dir=(-0.6, -1.0, 0.25)):   # spear side, armour visible
            print("Preview: " + path)
    sc.doc.Views.Redraw()
    if not then_cnc:
        return
    c = Settings(CNC_SPEC, height_mm="0", up_axis="z", debris_pct="0",
                 wrap="always", quads="0", out_dir=out_dir or "")
    if not c.ask(TITLE + " | Legionary -> CNC"):
        return
    log = Report("Legionary -> CNC")
    union = RHINO_VER < 8 or c.text("wrap") == "never"   # Rhino 8 ShrinkWrap merges anyway
    rs.EnableRedraw(False)
    mesh = parts_to_mesh([p[0] for p in parts], log, try_union=union)
    rs.HideObjects(ids)
    cnc_pipeline(mesh, c, "Legionary", orient=False, debris=False, log=log)


# =============================================================================
def main():
    items = ["1  AI mesh -> clean -> CNC   (select or import a mesh)",
             "2  Build Roman legionary   (SubD + NURBS, real scale)",
             "3  Build legionary -> CNC mesh + checks"]
    pick = rs.ListBox(items, "Pick a mode", "{} v{}  (Rhino {})".format(TITLE, VERSION, RHINO_VER), items[0])
    if not pick:
        return
    try:
        if pick == items[0]:
            mode_ai_mesh()
        elif pick == items[1]:
            mode_build(False)
        else:
            mode_build(True)
    except UserCancel:
        print(TITLE + ": cancelled (Esc).")
    except Exception:
        print(traceback.format_exc())
        rs.MessageBox("Script error - details on the command line.\n"
                      "Send the text to Claude to get a fix.", 16, TITLE)
    finally:
        rs.EnableRedraw(True)
        sc.doc.Views.Redraw()


if __name__ == "__main__":
    main()
