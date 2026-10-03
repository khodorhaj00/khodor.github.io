#! python2
# -*- coding: utf-8 -*-
"""
Styro3D | qmesh recipe -> clean closed quad mesh in Rhino (+ SubD / NURBS polysurface)
=====================================================================================
File    s3d_qmesh_rhino.py   v1.0
Rhino   7 (IronPython 2.7) and 8. Keep s3d_qmesh.py in the SAME folder.
Run     _RunPythonScript -> pick this file -> pick a *_recipe.json (or a cloud .obj)

What it does
 1 builds every part of the recipe with s3d_qmesh (the same code the cloud uses),
   so the mesh is identical: closed, quads, even rings, real millimetres
 2 adds each part to S3D_QMesh::Mesh, checks closed + manifold
 3 optional SubD (S3D_QMesh::SubD) and NURBS polysurface (S3D_QMesh::Polysurface),
   with an IsSolid check: clean quads in -> clean SubD -> clean polysurface out
Undo    one Ctrl+Z removes the whole run
"""
from __future__ import print_function, division

import json
import os
import sys
import traceback

import Rhino
import Rhino.Geometry as rg
import rhinoscriptsyntax as rs
import scriptcontext as sc
from System.Drawing import Color

TITLE = "Styro3D qmesh -> Rhino"
HERE = os.path.dirname(os.path.abspath(__file__)) if "__file__" in dir() else os.getcwd()
if HERE not in sys.path:
    sys.path.insert(0, HERE)

SPEC = [
    ("output", "Output: mesh / subd / nurbs (nurbs = mesh + SubD + polysurface)", "subd"),
    ("subdivide", "Catmull-Clark levels before Rhino (0 = none)", "0"),
    ("scale", "Extra scale factor (1 = recipe size)", "1"),
    ("each_layer", "One sub-layer per part (y/n)", "n"),
]


def mm():
    return Rhino.RhinoMath.UnitScale(Rhino.UnitSystem.Millimeters, sc.doc.ModelUnitSystem)


def ensure_layer(path, color):
    idx = sc.doc.Layers.FindByFullPath(path, -1)
    if idx >= 0:
        return idx
    parent_id = None
    parts = path.split("::")
    for i in range(len(parts)):
        sub = "::".join(parts[:i + 1])
        idx = sc.doc.Layers.FindByFullPath(sub, -1)
        if idx < 0:
            layer = Rhino.DocObjects.Layer()
            layer.Name = parts[i]
            if parent_id is not None:
                layer.ParentLayerId = parent_id
            if i == len(parts) - 1:
                layer.Color = color
            idx = sc.doc.Layers.Add(layer)
        parent_id = sc.doc.Layers[idx].Id
    return idx


def attrs(layer_idx, name):
    a = Rhino.DocObjects.ObjectAttributes()
    a.LayerIndex = layer_idx
    a.Name = name
    return a


def to_rhino_mesh(q, k):
    """QMesh (mm) -> Rhino Mesh in model units, quads kept."""
    m = rg.Mesh()
    for x, y, z in q.v:
        m.Vertices.Add(x * k, y * k, z * k)
    for f in q.f:
        if len(f) == 4:
            m.Faces.AddFace(f[0], f[1], f[2], f[3])
        elif len(f) == 3:
            m.Faces.AddFace(f[0], f[1], f[2])
    m.Normals.ComputeNormals()
    m.Compact()
    return m


def is_manifold(m):
    try:
        r = m.IsManifold(True)
        return bool(r[0] if isinstance(r, tuple) else r)
    except Exception:
        return False


def read_obj(path):
    """Minimal OBJ reader (v / f, any polygon) -> [(name, QMesh)] in file units (mm)."""
    import s3d_qmesh as Q
    parts, name, verts = [], "part", []
    base = 0
    cur = None
    with open(path) as fh:
        for line in fh:
            t = line.split()
            if not t:
                continue
            if t[0] == "o":
                if cur is not None and cur.f:
                    parts.append((name, cur))
                name = " ".join(t[1:]) or "part"
                cur = Q.QMesh(name=name)
                base = len(verts)
            elif t[0] == "v":
                verts.append((float(t[1]), float(t[2]), float(t[3])))
                if cur is None:
                    cur = Q.QMesh(name=name)
                cur.v.append(verts[-1])
            elif t[0] == "f":
                idx = [int(s.split("/")[0]) for s in t[1:]]
                idx = [(i - 1 if i > 0 else len(verts) + i) - base for i in idx]
                cur.f.append(tuple(idx))
    if cur is not None and cur.f:
        parts.append((name, cur))
    return parts


def main():
    try:
        import s3d_qmesh as Q
    except ImportError:
        rs.MessageBox("Put s3d_qmesh.py in the same folder as this script:\n" + HERE, 16, TITLE)
        return
    path = rs.OpenFileName("Pick a qmesh recipe (.json) or a qmesh .obj",
                           "qmesh recipe or mesh (*.json;*.obj)|*.json;*.obj||")
    if not path:
        return
    labels = [s[1] for s in SPEC]
    values = [s[2] for s in SPEC]
    res = rs.PropertyListBox(labels, values, "Edit, then OK", TITLE)
    if res is None:
        return
    opt = dict((SPEC[i][0], (res[i] or "").strip().lower()) for i in range(len(SPEC)))
    output = opt["output"] if opt["output"] in ("mesh", "subd", "nurbs") else "subd"
    try:
        levels = max(0, int(float(opt["subdivide"] or 0)))
    except ValueError:
        levels = 0
    try:
        extra = float(opt["scale"].replace(",", ".") or 1)
    except ValueError:
        extra = 1.0
    each = opt["each_layer"] in ("y", "yes", "1", "true")
    if path.lower().endswith(".obj"):
        parts = read_obj(path)
        title = os.path.splitext(os.path.basename(path))[0]
    else:
        recipe = json.load(open(path))
        parts = Q.build_recipe(recipe)
        title = recipe.get("name", os.path.splitext(os.path.basename(path))[0])
    if levels:
        parts = [(n, Q.catmull_clark(m, levels)) for n, m in parts]
    k = mm() * extra
    rs.EnableRedraw(False)
    lay_m = ensure_layer("S3D_QMesh::Mesh", Color.FromArgb(200, 200, 195))
    lay_s = ensure_layer("S3D_QMesh::SubD", Color.FromArgb(140, 150, 230))
    lay_b = ensure_layer("S3D_QMesh::Polysurface", Color.FromArgb(90, 170, 110))
    print("=" * 60)
    print("%s | %s | %d parts | output %s" % (TITLE, title, len(parts), output))
    n_ok = 0
    for name, q in parts:
        c = Q.check(q)
        mesh = to_rhino_mesh(q, k)
        lay = ensure_layer("S3D_QMesh::Mesh::" + name, Color.FromArgb(200, 200, 195)) if each else lay_m
        sc.doc.Objects.AddMesh(mesh, attrs(lay, name))
        line = "%-14s faces %6d  quads %5.1f%%  closed %s  manifold %s" % (
            name, mesh.Faces.Count, c["quad_pct"], mesh.IsClosed, is_manifold(mesh))
        if output in ("subd", "nurbs"):
            subd = rg.SubD.CreateFromMesh(mesh)
            if subd is not None:
                sc.doc.Objects.AddSubD(subd, attrs(lay_s, name + "_SubD"))
                line += "  SubD ok"
                if output == "nurbs":
                    brep = subd.ToBrep()
                    if brep is not None:
                        sc.doc.Objects.AddBrep(brep, attrs(lay_b, name + "_Polysurface"))
                        line += "  polysurface %d faces, solid %s" % (brep.Faces.Count, brep.IsSolid)
                    else:
                        line += "  polysurface FAILED"
            else:
                line += "  SubD FAILED"
        if mesh.IsClosed:
            n_ok += 1
        print(line)
    print("closed parts: %d of %d. Layers: S3D_QMesh::Mesh / SubD / Polysurface" % (n_ok, len(parts)))
    rs.EnableRedraw(True)
    sc.doc.Views.Redraw()


if __name__ == "__main__":
    try:
        main()
    except Exception:
        print(traceback.format_exc())
        rs.MessageBox("Script error - details on the command line.", 16, TITLE)
    finally:
        rs.EnableRedraw(True)
