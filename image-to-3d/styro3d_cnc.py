#! python2
# -*- coding: utf-8 -*-
"""
Styro3D | Universal part -> CNC for Rhino  (foam blocks, 3-axis, 2 or 4 setups)
=================================================================
File    styro3d_cnc.py   v1.0   2026-10-02
Rhino   7 (IronPython 2.7) and 8. The first line makes Rhino 8 run it in
        IronPython 2.7 too, so both versions execute the same code.
Run     command _RunPythonScript -> pick this file
        alias:  S3DCNC  =  ! _-RunPythonScript "C:\\path\\styro3d_cnc.py"
Undo    one Ctrl+Z removes everything a run added
Cancel  Esc during the long steps

INPUT   any mesh, polysurface, surface, extrusion or SubD. Select it, or press
        Enter to import a file (OBJ, STL, FBX, PLY, 3MF, STEP, IGES ...;
        GLB / glTF needs Rhino 8). Nothing here is specific to one model.

STEPS
 1 clean   weld -> up axis -> drop floaters + inner shells -> heal + fill
           holes -> fix normals -> watertight (ShrinkWrap, Rhino 8)
 2 size    target height, or "fit": the biggest size that fits N x N x N
           foam blocks
 3 axis    tests 9 tool axes and keeps the one with the least undercut area
           (ties: the shallower one), then turns the part about that axis so
           it needs the fewest blocks
 4 checks  thin walls, ball-nose reach (inside corners and slots tighter than
           the tool radius), undercuts for 2 or 4 setups, cut depth per side
           against the tool length, volume, EPS weight, material yield
 5 blocks  cuts the part into closed pieces, one per foam block. Every piece
           gets its own STL in block coordinates (origin = block corner,
           Z = tool axis) and one row in blocks.csv: size, volume, weight,
           undercut, depth per side, OK / not OK for the tool
 6 output  binary STL of the whole part in mm, PNG previews, report.txt,
           optional QuadRemesh + SubD

LAYERS  S3D_CNC::01_Part        cleaned watertight part (STL source)
        S3D_CNC::02_ThinWalls   red points    (walls under the limit)
        S3D_CNC::03_ToolReach   orange points (corners the ball cannot reach)
        S3D_CNC::04_Undercuts   magenta faces (no setup can reach them)
        S3D_CNC::05_Setup       part on the block grid in machine axes + labels
        S3D_CNC::06_Blocks      cut pieces, spread apart (exploded view)
        S3D_CNC::07_QuadMesh / 08_SubD
NOTES
 * All sizes are millimetres; the script converts to the model units.
 * The input objects are hidden, never changed.
 * The values you type are remembered for the next run (this Rhino session).
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
from System.Collections.Generic import List, IEnumerable
from System.Drawing import Color

TITLE = "Styro3D part -> CNC"
VERSION = "1.0"
RHINO_VER = int(Rhino.RhinoApp.ExeVersion)
PY3 = sys.version_info[0] >= 3
STICKY_KEY = "styro3d_cnc_settings_v1"
CUT_NUDGE_MM = 0.0137      # keeps cut planes off grid-aligned faces of CAD parts
ANALYSIS_FACES = 15000     # undercut / axis tests run on a reduced copy this size


class UserCancel(Exception):
    pass


# =============================================================================
# Settings
# =============================================================================
# (key, label shown in the dialog, default)
SPEC = [
    ("height_mm",   "Target height mm (0 = keep size)",                 "0"),
    ("fit",         "Or fit into blocks X x Y x Z, e.g. 1x1x2 (blank = off)", ""),
    ("up_axis",     "Source up axis: auto / x / y / z",                 "auto"),
    ("debris_pct",  "Drop loose pieces under % of faces",               "0.5"),
    ("heal_mm",     "Heal gaps up to mm",                               "0.5"),
    ("wrap",        "ShrinkWrap (Rhino 8): auto / always / never",      "auto"),
    ("wrap_mm",     "ShrinkWrap edge length mm (0 = auto)",             "0"),
    ("min_wall_mm", "Thin-wall warning below mm",                       "12"),
    ("tool_d_mm",   "Ball-nose tool diameter mm",                       "12"),
    ("tool_len_mm", "Tool usable length (stick-out) mm",                "300"),
    ("cut_axis",    "Tool axis: auto / x / y / z (model axes, Z = up)", "auto"),
    ("sides",       "Setups: 2 = top + flip, 4 = + both long sides",    "2"),
    ("block_x",     "Foam block X mm (machine bed long side)",          "2000"),
    ("block_y",     "Foam block Y mm",                                  "1000"),
    ("block_z",     "Foam block Z mm (thickness, along the tool)",      "1000"),
    ("cut_blocks",  "Cut into closed block pieces + STL each (y/n)",    "y"),
    ("density",     "EPS density kg/m3",                                "20"),
    ("quads",       "QuadRemesh target quads (0 = skip)",               "0"),
    ("subd",        "Make SubD from quads (y/n)",                       "n"),
    ("each",        "Several objects: machine each on its own (y/n)",   "n"),
    ("stl",         "Export binary STL in mm (y/n)",                    "y"),
    ("png",         "Save preview PNGs (y/n)",                          "y"),
    ("out_dir",     "Output folder (blank = auto)",                     ""),
]


class Settings(object):
    def __init__(self, spec, sticky_key=None, **overrides):
        self._spec = spec
        self._key = sticky_key
        saved = {}
        if sticky_key:
            try:
                saved = sc.sticky.get(sticky_key, None) or {}
            except Exception:
                saved = {}
        for key, _label, value in spec:
            setattr(self, key, overrides.get(key, saved.get(key, value)))

    def ask(self, title):
        labels = [row[1] for row in self._spec]
        values = [str(getattr(self, row[0])) for row in self._spec]
        result = rs.PropertyListBox(labels, values, "Edit the values, then OK", title)
        if result is None:
            return False
        for row, value in zip(self._spec, result):
            setattr(self, row[0], (value or "").strip())
        if self._key:
            try:
                sc.sticky[self._key] = dict((row[0], getattr(self, row[0])) for row in self._spec)
            except Exception:
                pass
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
# Clean-up and checks (same maths as Mode 1 of styro3d_ai_to_cnc.py)
# =============================================================================
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


# =============================================================================
# Pure helpers (no Rhino calls; tested offline)
# =============================================================================
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
    n = math.sqrt(v_dot(a, a)) or 1.0
    return (a[0] / n, a[1] / n, a[2] / n)


# Tool-axis candidates in model axes (Z = up after the up-axis step).
# A 2-setup job machines from +axis, then flips the block and machines from -axis.
AXIS_CANDIDATES = [
    ("Z", (0.0, 0.0, 1.0)), ("Y", (0.0, 1.0, 0.0)), ("X", (1.0, 0.0, 0.0)),
    ("X+Y", (1.0, 1.0, 0.0)), ("X-Y", (1.0, -1.0, 0.0)),
    ("Y+Z", (0.0, 1.0, 1.0)), ("Y-Z", (0.0, 1.0, -1.0)),
    ("X+Z", (1.0, 0.0, 1.0)), ("X-Z", (1.0, 0.0, -1.0)),
]


def pick_axis(rows, tie_pct=0.25):
    """rows: [(name, axis, undercut %, depth along axis)] -> the row to use.
    Least undercut wins; rows within tie_pct of the best go to the shallower
    one; equal depth keeps the list order (main axes before diagonals)."""
    best_u = min(r[2] for r in rows)
    close = [(r[3], i, r) for i, r in enumerate(rows) if r[2] <= best_u + tie_pct]
    return min(close)[2]


def perp_frame(a):
    """Unit axis a -> (b, c): (b, c, a) is a right-handed orthonormal frame.
    b starts from the world axis least aligned with a."""
    a = v_unit(a)
    ref = min(((1.0, 0.0, 0.0), (0.0, 1.0, 0.0), (0.0, 0.0, 1.0)),
              key=lambda e: abs(v_dot(e, a)))
    b = v_unit(v_sub(ref, v_mul(a, v_dot(ref, a))))
    return b, v_cross(a, b)


def turned(b, c, theta):
    """Turn the pair (b, c) by theta about their common normal."""
    cs, sn = math.cos(theta), math.sin(theta)
    return v_add(v_mul(b, cs), v_mul(c, sn)), v_sub(v_mul(c, cs), v_mul(b, sn))


def turn_angles(steps=12):
    """0 .. 165 deg: a bounding box repeats after half a turn."""
    return [math.pi * k / steps for k in range(steps)]


def blocks_needed(extent, block):
    return [max(1, int(math.ceil(extent[i] / block[i] - 1e-9))) for i in range(3)]


def turn_score(extent, block, fit_counts=None):
    """Lower is better. Fit mode: how full the target blocks are (the biggest
    part fits at the lowest value). Otherwise: block count, then box volume."""
    if fit_counts:
        return (max(extent[i] / (fit_counts[i] * block[i]) for i in range(3)), 0.0)
    if min(block) <= 0:
        return (0, extent[0] * extent[1] * extent[2])
    n = blocks_needed(extent, block)
    return (n[0] * n[1] * n[2], extent[0] * extent[1] * extent[2])


def parse_counts(text):
    """'1x1x2', '1 1 2', '1,1,2', '1*1*2' -> (1, 1, 2). Blank or bad -> None."""
    t = (text or "").strip().lower()
    if not t:
        return None
    for ch in "*,; ":
        t = t.replace(ch, "x")
    parts = [p for p in t.split("x") if p]
    if len(parts) != 3:
        return None
    try:
        out = tuple(int(float(p)) for p in parts)
    except ValueError:
        return None
    if min(out) < 1:
        return None
    return out


def fit_scale(extent, counts, block, margin=0.0):
    """Largest uniform scale so a part of `extent` fits counts x block,
    keeping `margin` of stock on every side. None if nothing to scale."""
    best = None
    for i in range(3):
        if extent[i] <= 1e-12:
            continue
        f = (counts[i] * block[i] - 2.0 * margin) / extent[i]
        best = f if best is None else min(best, f)
    return best


def block_grid(bbox, block):
    """bbox = (x0, y0, z0, x1, y1, z1) in machine axes, block = (bx, by, bz).
    Returns (counts, grid min corner) with the part centred in the grid."""
    size = [bbox[i + 3] - bbox[i] for i in range(3)]
    counts = blocks_needed(size, block)
    corner = [(bbox[i] + bbox[i + 3]) * 0.5 - counts[i] * block[i] * 0.5 for i in range(3)]
    return tuple(counts), tuple(corner)


def block_cuts(counts, corner, block, nudge=0.0):
    """Inner cut positions per axis: corner + k * block (+ nudge), k = 1 .. n-1."""
    return [[corner[i] + k * block[i] + nudge for k in range(1, counts[i])] for i in range(3)]


def cell_index(value, cuts):
    """Slab of a coordinate: 0 .. len(cuts)."""
    i = 0
    for c in cuts:
        if value > c:
            i += 1
        else:
            break
    return i


def block_ids(counts):
    """[(name, ix, iy, iz)] numbered bottom layer first, then row (Y), then column (X)."""
    out, n = [], 0
    for iz in range(counts[2]):
        for iy in range(counts[1]):
            for ix in range(counts[0]):
                n += 1
                out.append(("B%02d" % n, ix, iy, iz))
    return out


def block_box(corner, block, ix, iy, iz):
    x0 = corner[0] + ix * block[0]
    y0 = corner[1] + iy * block[1]
    z0 = corner[2] + iz * block[2]
    return (x0, y0, z0, x0 + block[0], y0 + block[1], z0 + block[2])


def stock_box(box, part_bb, margin, n_dirs):
    """Stock really needed inside a block: the block trimmed (hot wire) to the
    part extent + margin along the tool axis Z, and along Y for 4 setups."""
    x0, y0, z0, x1, y1, z1 = box
    z0, z1 = max(z0, part_bb[2] - margin), min(z1, part_bb[5] + margin)
    if n_dirs > 2:
        y0, y1 = max(y0, part_bb[1] - margin), min(y1, part_bb[4] + margin)
    return (x0, y0, z0, x1, y1, z1)


def poly_area(poly):
    a = 0.0
    n = len(poly)
    for i in range(n):
        x0, y0 = poly[i]
        x1, y1 = poly[(i + 1) % n]
        a += x0 * y1 - x1 * y0
    return 0.5 * a


def point_in_poly(x, y, poly):
    """Even-odd rule."""
    inside = False
    n = len(poly)
    j = n - 1
    for i in range(n):
        xi, yi = poly[i]
        xj, yj = poly[j]
        if (yi > y) != (yj > y):
            if x < xi + (y - yi) * (xj - xi) / (yj - yi):
                inside = not inside
        j = i
    return inside


def loop_nesting(loops):
    """loops: closed 2D polygons that do not cross. Returns (depth, parent):
    depth 0 = outer boundary, 1 = hole, 2 = island in a hole ...;
    parent = smallest loop containing it (-1 = none)."""
    n = len(loops)
    areas = [abs(poly_area(p)) for p in loops]
    depth, parent = [0] * n, [-1] * n
    for i in range(n):
        p = loops[i]
        if len(p) < 2:
            continue
        x = (p[0][0] + p[1][0]) * 0.5      # mid-point of the first edge: never
        y = (p[0][1] + p[1][1]) * 0.5      # on another loop
        for j in range(n):
            if j == i or areas[j] <= areas[i]:
                continue
            if point_in_poly(x, y, loops[j]):
                depth[i] += 1
                if parent[i] < 0 or areas[j] < areas[parent[i]]:
                    parent[i] = j
    return depth, parent


def assign_side(mask, depths):
    """mask bit i = setup i reaches the face, depths[i] = cut depth from setup i.
    Returns (setup, depth) of the shallowest setup that reaches it, or (-1, 0)."""
    best, best_d = -1, 0.0
    for i in range(len(depths)):
        if mask & (1 << i) and (best < 0 or depths[i] < best_d):
            best, best_d = i, depths[i]
    return best, best_d


def face_depths(c, box, n_dirs):
    """Cut depth of point c from each setup: +Z (top), -Z (flip), +Y, -Y."""
    d = [box[5] - c[2], c[2] - box[2], box[4] - c[1], c[1] - box[1]]
    return d[:n_dirs]


def on_block_face(c, n, box, tol):
    """True for a face lying on the block skin (made by the cut, never machined)."""
    for axis in range(3):
        if abs(n[axis]) > 0.99 and (abs(c[axis] - box[axis]) <= tol or
                                    abs(c[axis] - box[axis + 3]) <= tol):
            return True
    return False


def job_numbers(faces, box, n_dirs, tool_len):
    """faces: [(area, centre, mask)] in machine axes. Each face goes to the
    shallowest setup that reaches it. Returns areas and the depth per setup."""
    total = under = deep = 0.0
    max_d = [0.0] * n_dirs
    for area, c, mask in faces:
        total += area
        side, depth = assign_side(mask, face_depths(c, box, n_dirs))
        if side < 0:
            under += area
            continue
        if depth > max_d[side]:
            max_d[side] = depth
        if depth > tool_len:
            deep += area
    return {"area": total, "undercut": under, "too_deep": deep, "depth": max_d}


def layers_for_depth(thickness, tool_len, setups_along_axis=2):
    """Layers of stock needed so no setup cuts deeper than the tool reaches."""
    if tool_len <= 0:
        return 1
    return max(1, int(math.ceil(thickness / (setups_along_axis * tool_len) - 1e-9)))


SETUP_NAMES = ("top", "flip", "side +Y", "side -Y")


# =============================================================================
# Input: any solid-like object -> mesh
# =============================================================================
IMPORT_FILTER = ("3D file (*.obj;*.stl;*.fbx;*.ply;*.3mf;*.step;*.stp;*.igs;*.iges;*.glb;*.gltf;*.3dm)|"
                 "*.obj;*.stl;*.fbx;*.ply;*.3mf;*.step;*.stp;*.igs;*.iges;*.glb;*.gltf;*.3dm|"
                 "All files (*.*)|*.*||")


def input_filter():
    f = 0
    for name in ("mesh", "polysurface", "surface", "extrusion", "subd"):
        f |= int(getattr(rs.filter, name, 0) or 0)
    return f or None


def solid_like(g):
    return isinstance(g, (rg.Mesh, rg.Brep, rg.Extrusion, rg.Surface, rg.SubD))


def to_mesh(geo, tol_doc):
    """Mesh, SubD, Brep, Extrusion or Surface -> a new Mesh (None if not possible)."""
    if isinstance(geo, rg.Mesh):
        return geo.DuplicateMesh()
    if isinstance(geo, rg.SubD):
        return rg.Mesh.CreateFromSubD(geo, 4)
    if isinstance(geo, rg.Extrusion):
        geo = geo.ToBrep(True)
    elif isinstance(geo, rg.Surface):
        geo = geo.ToBrep()
    if isinstance(geo, rg.Brep):
        mp = rg.MeshingParameters.QualityRenderMesh
        _set(mp, "Tolerance", float(tol_doc))
        _set(mp, "JaggedSeams", False)
        _set(mp, "ClosedObjectPostProcess", True)
        parts = rg.Mesh.CreateFromBrep(geo, mp)
        if not parts:
            return None
        out = rg.Mesh()
        for p in parts:
            out.Append(p)
        return out
    return None


def get_input():
    """Returns (object ids, label) or (None, None)."""
    ids = rs.GetObjects("Select the part(s) - or press Enter to import a file",
                        input_filter(), preselect=True)
    if ids:
        ids = list(ids)
        doc_name = os.path.splitext(sc.doc.Name or "")[0]
        return ids, rs.ObjectName(ids[0]) or doc_name or "part"
    path = rs.OpenFileName("Import part", IMPORT_FILTER)
    if not path:
        return None, None
    if os.path.splitext(path)[1].lower() in (".glb", ".gltf") and RHINO_VER < 8:
        rs.MessageBox("Rhino 7 cannot import GLB / glTF.\nExport OBJ or FBX instead.", 48, TITLE)
        return None, None
    before = set(str(o.Id) for o in sc.doc.Objects)
    if not sc.doc.Import(path):
        rs.MessageBox("Import failed:\n" + path, 16, TITLE)
        return None, None
    new_ids = [o.Id for o in sc.doc.Objects
               if str(o.Id) not in before and solid_like(o.Geometry)]
    if not new_ids:
        rs.MessageBox("No mesh or solid found in:\n" + path, 48, TITLE)
        return None, None
    return new_ids, os.path.splitext(os.path.basename(path))[0]


def meshes_of(ids, log):
    """[(id, name, mesh)] for every object that converts to a mesh."""
    out = []
    for oid in ids:
        obj = sc.doc.Objects.FindId(oid)
        if obj is None:
            continue
        geo = obj.Geometry
        bb = geo.GetBoundingBox(True)
        tol = max(0.05 * mm(), bb.Diagonal.Length * 1e-4)
        m = to_mesh(geo, tol)
        if m is None or m.Faces.Count == 0:
            log.add("Skipped (no mesh): " + str(obj.ObjectType))
            continue
        if not isinstance(geo, rg.Mesh):
            log.add("Meshed {} -> {} faces (tolerance {:.2f} mm)".format(
                obj.ObjectType, m.Faces.Count, tol / mm()))
        out.append((oid, rs.ObjectName(oid) or "", m))
    return out


# =============================================================================
# Rhino helpers for the new checks
# =============================================================================
def V(t):
    return rg.Vector3d(t[0], t[1], t[2])


def xyz(p):
    return (p.X, p.Y, p.Z)


def reduced(m, max_faces):
    """Light copy for ray tests (the original is never changed)."""
    if m.Faces.Count <= max_faces:
        return m.DuplicateMesh()
    r = m.DuplicateMesh()
    r.Reduce(int(max_faces), True, 5, False)
    r.Normals.ComputeNormals()
    return r


def access_faces(m, dirs, skip=None):
    """Per face: (index, area, centre, mask). Bit i of mask = a tool coming
    from the +dirs[i] side (moving along -dirs[i]) reaches the face centre."""
    m.FaceNormals.ComputeFaceNormals()
    verts = m.Vertices.ToPoint3dArray()
    eps = max(sc.doc.ModelAbsoluteTolerance * 5.0, m.GetBoundingBox(True).Diagonal.Length * 1e-6)
    out = []
    for fi in range(m.Faces.Count):
        f = m.Faces[fi]
        area = _tri_area(verts[f.A], verts[f.B], verts[f.C])
        if f.IsQuad:
            area += _tri_area(verts[f.A], verts[f.C], verts[f.D])
        nf = m.FaceNormals[fi]
        n = rg.Vector3d(nf.X, nf.Y, nf.Z)
        c = m.Faces.GetFaceCenter(fi)
        if skip is not None and skip(c, n):
            continue
        start = c + n * eps
        mask = 0
        for bit in range(len(dirs)):
            d = dirs[bit]
            if n * d > -0.02 and Intersection.MeshRay(m, rg.Ray3d(start + d * eps, d)) < 0:
                mask |= 1 << bit
        out.append((fi, area, c, mask))
        if fi % 4000 == 0:
            check_escape()
    return out


def undercut_pct(res):
    total = sum(r[1] for r in res) or 1.0
    return 100.0 * sum(r[1] for r in res if r[3] == 0) / total


def extent_along(m, a):
    pts = m.Vertices.ToPoint3dArray()
    pr = [p.X * a[0] + p.Y * a[1] + p.Z * a[2] for p in pts]
    return (max(pr) - min(pr)) if pr else 0.0


def choose_axis(small, forced, log):
    """Returns (name, unit axis) of the tool axis in model axes."""
    rows = []
    names = [c[0] for c in AXIS_CANDIDATES]
    todo = AXIS_CANDIDATES
    if forced in ("x", "y", "z"):
        todo = [AXIS_CANDIDATES[names.index(forced.upper())]]
    for name, vec in todo:
        a = v_unit(vec)
        d = V(a)
        res = access_faces(small, [d, -d])
        rows.append((name, a, undercut_pct(res), extent_along(small, a)))
    best = pick_axis(rows)
    log.add("Tool axis, 2 setups (top + flip):   axis   undercut   depth through part")
    k = 1.0 / mm()
    for r in rows:
        log.add("    {:<5} {:6.1f} %   {:7.0f} mm{}".format(
            r[0], r[2], r[3] * k, "   <- used" if r is best else ""))
    return best[0], best[1]


def machine_plane(a, theta):
    b, c = perp_frame(a)
    b, c = turned(b, c, theta)
    return rg.Plane(rg.Point3d.Origin, V(b), V(c))


def best_turn(small, a, block, fit_counts):
    """Turn about the tool axis that needs the fewest blocks (or, in fit mode,
    lets the biggest part fit). Returns (plane, degrees)."""
    best = None
    for th in turn_angles():
        plane = machine_plane(a, th)
        bb = small.GetBoundingBox(plane)
        ext = (bb.Max.X - bb.Min.X, bb.Max.Y - bb.Min.Y, bb.Max.Z - bb.Min.Z)
        key = (turn_score(ext, block, fit_counts), th)
        if best is None or key < best[0]:
            best = (key, plane, math.degrees(th))
    return best[1], best[2]


def ball_reach_points(m, r_doc, max_samples=20000):
    """Points a ball-nose of radius r cannot touch: a ball resting on the point
    (centre = p + r * normal) cuts into the part somewhere else, so the corner
    or slot is tighter than the tool. The CNC leaves it rounded to >= r."""
    m.Normals.ComputeNormals()
    pts = m.Vertices.ToPoint3dArray()
    n = len(pts)
    step = max(1, n // max_samples)
    flagged, tested = [], 0
    for i in range(0, n, step):
        nv = m.Normals[i]
        d = rg.Vector3d(nv.X, nv.Y, nv.Z)
        length = d.Length
        if length < 1e-12:
            continue
        c = pts[i] + d * (r_doc / length)
        q = m.ClosestPoint(c)
        tested += 1
        if q.IsValid and c.DistanceTo(q) < 0.9 * r_doc:
            flagged.append(pts[i])
        if tested % 2000 == 0:
            check_escape()
    return flagged, tested


# ---- cutting into blocks ------------------------------------------------------
def _finish_solid(m):
    m.Vertices.CombineIdentical(True, True)
    m.Faces.CullDegenerateFaces()
    m.UnifyNormals()
    if m.SolidOrientation() == -1:
        m.Flip(True, True, True)
    m.RebuildNormals()
    m.Compact()
    return m


def _on_plane(polyline, plane, tol):
    for pt in polyline:
        if abs(plane.DistanceTo(pt)) > tol:
            return False
    return True


def _uv_loop(polyline, plane):
    pts = list(polyline)
    if len(pts) > 1 and pts[0].DistanceTo(pts[-1]) < 1e-12:
        pts = pts[:-1]
    out = []
    for pt in pts:
        _ok, u, v = plane.ClosestParameter(pt)
        out.append((u, v))
    return out


def _planar_cap(group, plane, tol):
    """Cap for one outer loop + its holes. Tessellation first, planar Brep second."""
    pts = List[rg.Point3d]()
    edges = List[IEnumerable[rg.Point3d]]()
    for loop in group:
        edges.Add(loop)
        ring = list(loop)
        if len(ring) > 1 and ring[0].DistanceTo(ring[-1]) < 1e-12:
            ring = ring[:-1]                 # closed polylines repeat the start point
        for pt in ring:
            pts.Add(pt)
    try:
        cap = rg.Mesh.CreateFromTessellation(pts, edges, plane, False)
        if cap is not None and cap.Faces.Count:
            return cap
    except Exception:
        pass
    try:
        curves = [rg.PolylineCurve(loop) for loop in group]
        breps = rg.Brep.CreatePlanarBreps(curves, tol)
        if breps:
            mp = rg.MeshingParameters.Minimal
            _set(mp, "SimplePlanes", True)
            cap = rg.Mesh()
            for b in breps:
                for part in (rg.Mesh.CreateFromBrep(b, mp) or []):
                    cap.Append(part)
            if cap.Faces.Count:
                return cap
    except Exception:
        pass
    return None


def cap_cut(piece, plane, tol):
    """Close the flat openings a Split left on `plane`. Returns the mesh to use
    (the same one, or a fixed copy). Nested loops (a ring cut flat, a letter O)
    get one cap with holes; plain loops use Rhino's own FillHoles."""
    if piece.IsClosed:
        return piece
    # float vertices: allow 1e-5 of the piece size off the plane
    ptol = max(tol, piece.GetBoundingBox(True).Diagonal.Length * 1e-5)
    loops = [pl for pl in (piece.GetNakedEdges() or []) if _on_plane(pl, plane, ptol)]
    depth, parent = loop_nesting([_uv_loop(pl, plane) for pl in loops])
    if not loops or all(d == 0 for d in depth):
        piece.FillHoles()
        return _finish_solid(piece)
    capped = piece.DuplicateMesh()
    for i in range(len(loops)):
        if depth[i] % 2:
            continue
        group = [loops[i]] + [loops[j] for j in range(len(loops))
                              if parent[j] == i and depth[j] % 2]
        cap = _planar_cap(group, plane, tol)
        if cap is not None:
            capped.Append(cap)
    capped.Vertices.CombineIdentical(True, True)
    if not capped.IsClosed:
        capped.HealNakedEdges(tol)
        capped.Vertices.CombineIdentical(True, True)
    if capped.IsClosed and is_manifold(capped):
        return _finish_solid(capped)
    piece.FillHoles()                     # last resort: closed, caps may overlap
    return _finish_solid(piece)


def split_by_plane(pieces, axis, value, tol):
    """Split every piece that crosses the plane {axis = value}; cap the cuts."""
    origin = [0.0, 0.0, 0.0]
    normal = [0.0, 0.0, 0.0]
    origin[axis] = value
    normal[axis] = 1.0
    plane = rg.Plane(rg.Point3d(origin[0], origin[1], origin[2]),
                     rg.Vector3d(normal[0], normal[1], normal[2]))
    out = []
    for p in pieces:
        bb = p.GetBoundingBox(True)
        if value <= bb.Min[axis] + tol or value >= bb.Max[axis] - tol:
            out.append(p)
            continue
        parts = p.Split(plane)
        if not parts:
            out.append(p)
            continue
        for q in parts:
            qb = q.GetBoundingBox(True)
            sub = [q]
            if qb.Min[axis] < value - tol and qb.Max[axis] > value + tol:
                sub = list(q.SplitDisjointPieces() or [q])     # both sides in one result
            for r in sub:
                out.append(cap_cut(r, plane, tol))
    return out


def cut_blocks(machine, counts, corner, block, tol):
    """Machine-axes mesh -> {(ix, iy, iz): closed piece mesh}."""
    cuts = block_cuts(counts, corner, block, CUT_NUDGE_MM * mm())
    pieces = [machine.DuplicateMesh()]
    for axis in range(3):
        for value in cuts[axis]:
            pieces = split_by_plane(pieces, axis, value, tol)
            check_escape()
    groups = {}
    for p in pieces:
        if p.Faces.Count == 0:
            continue
        c = p.GetBoundingBox(True).Center
        key = (cell_index(c.X, cuts[0]), cell_index(c.Y, cuts[1]), cell_index(c.Z, cuts[2]))
        groups.setdefault(key, []).append(p)
    out = {}
    for key, plist in groups.items():
        m = rg.Mesh()
        for p in plist:
            m.Append(p)
        m.Compact()
        out[key] = m
    return out


def setup_dirs(n_dirs):
    d = [rg.Vector3d(0, 0, 1), rg.Vector3d(0, 0, -1), rg.Vector3d(0, 1, 0), rg.Vector3d(0, -1, 0)]
    return d[:n_dirs]


def job_for(piece, box, sbox, n_dirs, tool_len, tol):
    """CNC job numbers for one block (machine axes). Faces on the block skin
    (`box`, left by the cut) are skipped; depths count from the stock `sbox`."""
    m = reduced(piece, ANALYSIS_FACES)

    def skip(c, n):
        return on_block_face(xyz(c), xyz(n), box, tol)

    res = access_faces(m, setup_dirs(n_dirs), skip)
    faces = [(r[1], xyz(r[2]), r[3]) for r in res]
    return job_numbers(faces, sbox, n_dirs, tool_len)


def add_dot(text, pt, layer_idx):
    attr = Rhino.DocObjects.ObjectAttributes()
    attr.LayerIndex = layer_idx
    return sc.doc.Objects.AddTextDot(rg.TextDot(text, pt), attr)


def box_lines(box, layer_idx):
    bb = rg.BoundingBox(rg.Point3d(box[0], box[1], box[2]), rg.Point3d(box[3], box[4], box[5]))
    return [add_obj(line, layer_idx) for line in bb.GetEdges()]


def export_local_stl(m, offset, path, header):
    """STL in mm with `offset` (doc units) subtracted: block corner -> origin."""
    k = 1.0 / mm()
    ox, oy, oz = offset
    verts = [((p.X - ox) * k, (p.Y - oy) * k, (p.Z - oz) * k) for p in m.Vertices.ToPoint3dArray()]
    idx = list(m.Faces.ToIntArray(True))
    tris = [(idx[i], idx[i + 1], idx[i + 2]) for i in range(0, len(idx) - 2, 3)]
    write_binary_stl(path, verts, tris, header)
    return len(tris)


def write_text(path, lines):
    f = codecs.open(path, "w", "utf-8")
    try:
        f.write(u"\n".join(lines) + u"\n")
    finally:
        f.close()


# =============================================================================
# The pipeline
# =============================================================================
def run_part(mesh, s, label, log):
    """One part: clean -> size -> axis -> checks -> blocks -> files. Returns the summary line."""
    k = mm()
    tol = max(sc.doc.ModelAbsoluteTolerance, 0.001 * k)
    out_dir = output_dir(s, label)
    name = safe_name(label)
    log.add("Output folder: " + out_dir)
    log.add("IN    " + stats_line(mesh))

    rs.EnableRedraw(False)
    # ---------------- 1 clean + 2 size ----------------
    basic_cleanup(mesh, log)
    orient_up(mesh, s.text("up_axis"), log)
    scale_and_place(mesh, s.num("height_mm", 0.0) * k, log)
    if s.num("debris_pct", 0.0) > 0:
        mesh = remove_debris(mesh, s.num("debris_pct", 0.5), log)
    heal(mesh, max(s.num("heal_mm", 0.5), 0.0) * k, log)
    check_escape()
    mesh = watertight(mesh, s, log)
    mesh.RebuildNormals()
    mesh.Compact()

    # ---------------- 3 tool axis + turn ----------------
    log.add("")
    log.add("--- MACHINING SETUP ---")
    block = (s.num("block_x", 0.0) * k, s.num("block_y", 0.0) * k, s.num("block_z", 0.0) * k)
    use_blocks = min(block) > 0
    fit = parse_counts(s.text("fit")) if use_blocks else None
    n_dirs = 4 if s.num("sides", 2) >= 4 else 2
    small = reduced(mesh, ANALYSIS_FACES)
    axis_name, a = choose_axis(small, s.text("cut_axis"), log)
    plane, turn_deg = best_turn(small, a, block if use_blocks else (0, 0, 0), fit)
    log.add("Turned {:.0f} deg about the tool axis ({}).".format(
        turn_deg, "biggest part that fits" if fit else "fewest blocks"))
    if fit:
        bbp = mesh.GetBoundingBox(plane)
        ext = (bbp.Max.X - bbp.Min.X, bbp.Max.Y - bbp.Min.Y, bbp.Max.Z - bbp.Min.Z)
        f = fit_scale(ext, fit, block, 10.0 * k)
        if f and f > 0:
            bb = mesh.GetBoundingBox(True)
            xf = rg.Transform.Scale(rg.Point3d(bb.Center.X, bb.Center.Y, bb.Min.Z), f)
            mesh.Transform(xf)
            small.Transform(xf)
            log.add("Fit into {} x {} x {} blocks: scale x{:.4f}".format(fit[0], fit[1], fit[2], f))
    log.add("CNC   " + stats_line(mesh))
    log.add(size_line(mesh))

    part_id = add_obj(mesh, ensure_layer("S3D_CNC::01_Part", Color.FromArgb(236, 236, 230)), name + "_CNC")
    check_ids = [part_id]

    # ---------------- 4 checks (model axes) ----------------
    log.add("")
    log.add("--- CNC CHECKS ---")
    wall = s.num("min_wall_mm", 0.0)
    if wall > 0:
        pts, tested = thin_wall_points(mesh, wall * k)
        log.add("Thin walls < {:.0f} mm: {} of {} sampled points ({:.1f}%)".format(
            wall, len(pts), tested, 100.0 * len(pts) / max(tested, 1)))
        if pts:
            layer = ensure_layer("S3D_CNC::02_ThinWalls", Color.FromArgb(230, 30, 30))
            check_ids.append(add_obj(rg.PointCloud(net_list(pts, rg.Point3d)), layer, "thin_walls"))
    r_tool = 0.5 * s.num("tool_d_mm", 0.0) * k
    if r_tool > 0:
        pts, tested = ball_reach_points(mesh, r_tool)
        log.add("Ball-nose D{:.0f}: {} of {} sampled points ({:.1f}%) sit in corners / slots "
                "tighter than R{:.1f} -> left rounded".format(
                    2 * r_tool / k, len(pts), tested, 100.0 * len(pts) / max(tested, 1), r_tool / k))
        if pts:
            layer = ensure_layer("S3D_CNC::03_ToolReach", Color.FromArgb(255, 140, 0))
            check_ids.append(add_obj(rg.PointCloud(net_list(pts, rg.Point3d)), layer, "tool_reach"))
    yv = plane.YAxis
    dirs = [V(a), -V(a), yv, -yv][:n_dirs]
    res = access_faces(small, dirs)
    under = undercut_pct(res)
    log.add("Undercut ({} setups, axis {}): {:.1f}% of the surface".format(n_dirs, axis_name, under))
    neither = [r[0] for r in res if r[3] == 0]
    if neither:
        um = small.DuplicateMesh().Faces.ExtractFaces(net_list(neither, int))
        if um is not None and um.Faces.Count:
            layer = ensure_layer("S3D_CNC::04_Undercuts", Color.FromArgb(220, 0, 200))
            check_ids.append(add_obj(um, layer, "undercuts"))
            log.add("  magenta faces: no setup reaches them -> robot / extra setup / split / accept")

    volume_l = mesh.Volume() / (k ** 3) * 1e-6 if mesh.IsClosed else 0.0
    density = s.num("density", 20.0)
    if mesh.IsClosed:
        log.add("Part volume {:.1f} L -> EPS {:.0f} kg/m3 = {:.1f} kg".format(
            volume_l, density, volume_l * 1e-3 * density))
    else:
        log.add("Volume: n/a (mesh not closed)")

    # ---------------- 5 machine axes + blocks ----------------
    machine = mesh.DuplicateMesh()
    machine.Transform(rg.Transform.PlaneToPlane(plane, rg.Plane.WorldXY))
    mb = machine.GetBoundingBox(True)
    pbb = (mb.Min.X, mb.Min.Y, mb.Min.Z, mb.Max.X, mb.Max.Y, mb.Max.Z)
    tool_len = s.num("tool_len_mm", 0.0) * k
    margin = 10.0 * k                       # stock left around the part per side
    skin_tol = max(10.0 * tol, 0.05 * k)    # > CUT_NUDGE_MM: cut faces count as block skin
    model_bb = mesh.GetBoundingBox(True)
    gap = 0.15 * (min(block) if use_blocks else mb.Diagonal.Length)
    setup_ids, block_rows = [], []
    if use_blocks:
        counts, corner = block_grid(pbb, block)
    else:
        counts, corner = (1, 1, 1), (pbb[0] - margin, pbb[1] - margin, pbb[2] - margin)
        block = (pbb[3] - pbb[0] + 2 * margin, pbb[4] - pbb[1] + 2 * margin, pbb[5] - pbb[2] + 2 * margin)
    grid_w = counts[0] * block[0]
    # display: setup to the right of the part, exploded pieces to the right of that
    shift = rg.Vector3d(model_bb.Max.X + gap - corner[0], -corner[1] - counts[1] * block[1] * 0.5, -corner[2])
    shift2 = rg.Vector3d(shift.X + grid_w + gap * (counts[0] + 2), shift.Y, shift.Z)
    show = machine.DuplicateMesh()
    show.Translate(shift)
    lay_setup = ensure_layer("S3D_CNC::05_Setup", Color.FromArgb(40, 140, 255))
    setup_ids.append(add_obj(show, lay_setup, name + "_machine_axes"))
    ids = block_ids(counts)
    for (bname, ix, iy, iz) in ids:
        box = block_box(corner, block, ix, iy, iz)
        moved = (box[0] + shift.X, box[1] + shift.Y, box[2] + shift.Z,
                 box[3] + shift.X, box[4] + shift.Y, box[5] + shift.Z)
        setup_ids.extend(box_lines(moved, lay_setup))
        setup_ids.append(add_dot(bname, rg.Point3d(0.5 * (moved[0] + moved[3]), 0.5 * (moved[1] + moved[4]),
                                                   moved[5]), lay_setup))
    log.add("Machine axes: tool = Z ({} of the model), bed long side = X".format(axis_name))
    log.add("Blocks {:.0f} x {:.0f} x {:.0f} mm: {} x {} x {} = {}".format(
        block[0] / k, block[1] / k, block[2] / k, counts[0], counts[1], counts[2],
        counts[0] * counts[1] * counts[2]))
    if use_blocks and mesh.IsClosed:
        stock = counts[0] * counts[1] * counts[2] * block[0] * block[1] * block[2] / (k ** 3) * 1e-6
        log.add("Stock {:.0f} L -> material yield {:.0f}%".format(stock, 100.0 * volume_l / max(stock, 1e-9)))

    if s.flag("cut_blocks") and counts[0] * counts[1] * counts[2] >= 1:
        log.add("Cutting into block pieces ...")
        pieces = cut_blocks(machine, counts, corner, block, tol) if counts != (1, 1, 1) \
            else {(0, 0, 0): machine.DuplicateMesh()}
        lay_blocks = ensure_layer("S3D_CNC::06_Blocks", Color.FromArgb(120, 200, 255))
        blk_dir = os.path.join(out_dir, "blocks")
        if s.flag("stl") and not os.path.isdir(blk_dir):
            os.makedirs(blk_dir)
        hdr = ["block", "ix", "iy", "iz", "corner_x_mm", "corner_y_mm", "corner_z_mm",
               "stock_x_mm", "stock_y_mm", "stock_z_mm", "part_L", "weight_kg", "closed",
               "undercut_pct", "too_deep_pct"] + ["depth_%s_mm" % SETUP_NAMES[i].replace(" ", "")
                                                  for i in range(n_dirs)] + ["tool_ok", "stl"]
        block_rows.append(",".join(hdr))
        log.add("  block  stock (trimmed) mm        part L   undercut  deepest cut per setup mm   tool")
        worst = 0.0
        for (bname, ix, iy, iz) in ids:
            p = pieces.get((ix, iy, iz))
            if p is None or p.Faces.Count == 0:
                continue
            box = block_box(corner, block, ix, iy, iz)
            pb = p.GetBoundingBox(True)
            sbox = stock_box(box, (pb.Min.X, pb.Min.Y, pb.Min.Z, pb.Max.X, pb.Max.Y, pb.Max.Z), margin, n_dirs)
            job = job_for(p, box, sbox, n_dirs, tool_len if tool_len > 0 else 1e30, skin_tol)
            vol = p.Volume() / (k ** 3) * 1e-6 if p.IsClosed else 0.0
            area = job["area"] or 1.0
            und = 100.0 * job["undercut"] / area
            deep = 100.0 * job["too_deep"] / area
            ok = (deep == 0.0) and (tool_len <= 0 or max(job["depth"]) <= tool_len)
            worst = max(worst, max(job["depth"]))
            stl_name = ""
            if s.flag("stl"):
                stl_name = "{}_{}_x{}y{}z{}_mm.stl".format(name, bname, ix + 1, iy + 1, iz + 1)
                export_local_stl(p, (box[0], box[1], box[2]), os.path.join(blk_dir, stl_name),
                                 "Styro3D block {} mm, origin = block corner".format(bname))
            log.add("  {}  {:5.0f} x {:5.0f} x {:5.0f}  {:8.1f}  {:6.1f}%   {}   {}{}".format(
                bname, (sbox[3] - sbox[0]) / k, (sbox[4] - sbox[1]) / k, (sbox[5] - sbox[2]) / k, vol, und,
                " / ".join("{:.0f}".format(d / k) for d in job["depth"]),
                "OK" if ok else "TOO DEEP", "" if p.IsClosed else "  (piece open)"))
            row = [bname, ix + 1, iy + 1, iz + 1, "%.1f" % (box[0] / k), "%.1f" % (box[1] / k),
                   "%.1f" % (box[2] / k), "%.1f" % ((sbox[3] - sbox[0]) / k), "%.1f" % ((sbox[4] - sbox[1]) / k),
                   "%.1f" % ((sbox[5] - sbox[2]) / k), "%.2f" % vol, "%.2f" % (vol * 1e-3 * density),
                   "y" if p.IsClosed else "n", "%.2f" % und, "%.2f" % deep] + \
                  ["%.1f" % (d / k) for d in job["depth"]] + ["y" if ok else "n", stl_name]
            block_rows.append(",".join(str(v) for v in row))
            ex = p.DuplicateMesh()
            ex.Translate(rg.Vector3d(shift2.X + ix * gap, shift2.Y + iy * gap, shift2.Z + iz * gap))
            setup_ids.append(add_obj(ex, lay_blocks, name + "_" + bname))
            eb = ex.GetBoundingBox(True)
            setup_ids.append(add_dot(bname, rg.Point3d(eb.Center.X, eb.Center.Y, eb.Max.Z), lay_blocks))
            check_escape()
        if tool_len > 0 and worst > tool_len:
            log.add("  TOO DEEP: deepest cut {:.0f} mm > tool {:.0f} mm. Use thinner blocks "
                    "(block Z <= {:.0f} mm), a longer tool, or 4 setups.".format(
                        worst / k, tool_len / k, 2 * tool_len / k))
        csv_path = os.path.join(out_dir, name + "_blocks.csv")
        write_text(csv_path, block_rows)
        log.add("Job table: " + csv_path)
        if s.flag("stl"):
            log.add("Block STLs (origin = block corner, Z = tool): " + blk_dir)

    # ---------------- 6 editable versions + files ----------------
    log.add("")
    topo_id = None
    if int(s.num("quads", 0)) > 0:
        check_escape()
        quads = quad_remesh(mesh, s.num("quads", 0), log)
        if quads is not None:
            topo_id = add_obj(quads, ensure_layer("S3D_CNC::07_QuadMesh", Color.FromArgb(110, 190, 110)),
                              name + "_Quads")
            if s.flag("subd"):
                subd = rg.SubD.CreateFromMesh(quads)
                if subd is not None:
                    topo_id = add_obj(subd, ensure_layer("S3D_CNC::08_SubD", Color.FromArgb(140, 140, 220)),
                                      name + "_SubD")
                    log.add("SubD created (ToNURBS for NURBS)")

    rs.EnableRedraw(True)
    if s.flag("png"):
        shots = [("clay", [part_id], "Arctic"), ("checks", check_ids, "Shaded"),
                 ("blocks", setup_ids, "Shaded")]
        if topo_id is not None:
            shots.append(("topology", [topo_id], "Wireframe"))
        for tag, sid, mode in shots:
            path = os.path.join(out_dir, "{}_{}.png".format(name, tag))
            if sid and save_preview(path, sid, mode):
                log.add("Preview: " + path)
    if s.flag("stl"):
        path = os.path.join(out_dir, name + "_CNC_mm.stl")
        log.add("STL (binary, mm, model axes): {} ({} triangles)".format(path, export_stl_mm(mesh, path)))
    report = os.path.join(out_dir, name + "_report.txt")
    log.save(report)
    log.add("Report: " + report)
    sc.doc.Views.Redraw()
    return out_dir, "{}: {} | undercut {:.1f}% | blocks {}".format(
        label, size_line(mesh), under, counts[0] * counts[1] * counts[2])


def main():
    s = Settings(SPEC, STICKY_KEY)
    if not s.ask("{} v{}  (Rhino {})".format(TITLE, VERSION, RHINO_VER)):
        return
    ids, label = get_input()
    if not ids:
        return
    log = Report(label)
    items = meshes_of(ids, log)
    if not items:
        rs.MessageBox("Nothing to machine in the selection.", 48, TITLE)
        return
    rs.HideObjects([i[0] for i in items])            # originals stay untouched, just hidden
    if s.flag("each") and len(items) > 1:
        jobs = [(m, safe_name(nm or "{}_{:02d}".format(label, n + 1))) for n, (_i, nm, m) in enumerate(items)]
    else:
        whole = rg.Mesh()
        for _i, _nm, m in items:
            whole.Append(m)
        jobs = [(whole, label)]
    out_dir, summary = None, []
    for mesh, lab in jobs:
        if len(jobs) > 1:
            log = Report(lab)
        out_dir, line = run_part(mesh, s, lab, log)
        summary.append(line)
    if len(jobs) > 1:
        log.add("")
        log.add("--- BATCH ---")
        for line in summary:
            log.add(line)
    finish_message(log, out_dir)


if __name__ == "__main__":
    try:
        main()
    except UserCancel:
        print(TITLE + ": cancelled (Esc).")
    except Exception:
        print(traceback.format_exc())
        rs.MessageBox("Script error - details on the command line.\n"
                      "Send the text to Claude to get a fix.", 16, TITLE)
    finally:
        rs.EnableRedraw(True)
        sc.doc.Views.Redraw()
