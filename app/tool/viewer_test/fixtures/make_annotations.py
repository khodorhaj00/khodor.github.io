#! python3
"""Writes annotations.3dm next to this script. Runs INSIDE Rhino 8 (Script Editor, or
_-RunPythonScript), because rhino3dm cannot create annotations or hatches.

    Rhino 8 > Tools > Script > Edit... > open this file > Run
    or, unattended (the output path may also come from RHINO_FIXTURE_OUT):
    Rhino.exe /nosplash /notemplate /runscript="_-RunPythonScript \"<this file>\" _-Exit"

annotations.3dm (millimetres, saved as a Rhino 8 file), all on the XY plane:
    layer DIMS    (0,160,255)  linear (rotated) dimension 0,0 -> 200,0, line at y=-30;
                               aligned dimension 200,0 -> 200,100, line at x=230;
                               diameter dimension on a 60 mm circle centred at 100,50
    layer NOTES   (230,230,230) text "FOAM 30 KG" at 0,140 (20 mm, bold, overriding the
                               style's 8 mm); leader "CUT HERE" from 150,100
    layer HATCH   (220,70,60)  solid hatch: 80 x 40 rectangle at 260,0 with a 20 mm hole;
                               pattern hatch 80 x 40 at 260,60
    layer PARTS   (200,200,200) a 200 x 100 x 20 box mesh at 0,0,-20 (under the drawing)
Dimension style "Fixture": text height 4, model space scale 2 (so 8 mm on screen), arrow
length 3, text gap 1.
The viewer harness expects 5 annotations, 2 hatches, 1 mesh (run.mjs, checkAnnotations).
"""
import os
import traceback

import System
import System.Drawing as sd
from System.Collections.Generic import List

import Rhino
import Rhino.Geometry as rg

HERE = os.path.dirname(os.path.abspath(__file__)) if "__file__" in globals() else os.getcwd()
OUT = os.environ.get("RHINO_FIXTURE_OUT") or os.path.join(HERE, "annotations.3dm")
LOG = OUT + ".log"


def add_layer(doc, name, rgb):
    layer = Rhino.DocObjects.Layer()
    layer.Name = name
    layer.Color = sd.Color.FromArgb(rgb[0], rgb[1], rgb[2])
    return doc.Layers.Add(layer)


def attributes(layer_index, name):
    attr = Rhino.DocObjects.ObjectAttributes()
    attr.LayerIndex = layer_index
    attr.Name = name
    return attr


def pattern_index(doc, name, default):
    found = doc.HatchPatterns.FindName(name)
    if found is not None:
        return found.Index
    return doc.HatchPatterns.Add(default)


def curves(*items):
    result = List[rg.Curve]()
    for item in items:
        result.Add(item)
    return result


def build(doc):
    doc.ModelUnitSystem = Rhino.UnitSystem.Millimeters
    tolerance = doc.ModelAbsoluteTolerance

    style = Rhino.DocObjects.DimensionStyle()
    style.Name = "Fixture"
    style.TextHeight = 4.0
    style.DimensionScale = 2.0
    style.ArrowLength = 3.0
    style.TextGap = 1.0
    style_index = doc.DimStyles.Add(style, False)
    doc.DimStyles.SetCurrent(style_index, True)
    style = doc.DimStyles[style_index]

    dims = add_layer(doc, "DIMS", (0, 160, 255))
    notes = add_layer(doc, "NOTES", (230, 230, 230))
    hatch_layer = add_layer(doc, "HATCH", (220, 70, 60))
    parts = add_layer(doc, "PARTS", (200, 200, 200))
    xy = rg.Plane.WorldXY

    linear = rg.LinearDimension.Create(
        rg.AnnotationType.Rotated, style, xy, rg.Vector3d.XAxis,
        rg.Point3d(0, 0, 0), rg.Point3d(200, 0, 0), rg.Point3d(100, -30, 0), 0.0)
    doc.Objects.AddLinearDimension(linear, attributes(dims, "dim_linear"))

    aligned = rg.LinearDimension.Create(
        rg.AnnotationType.Aligned, style, xy, rg.Vector3d.YAxis,
        rg.Point3d(200, 0, 0), rg.Point3d(200, 100, 0), rg.Point3d(230, 50, 0), 0.0)
    doc.Objects.AddLinearDimension(aligned, attributes(dims, "dim_aligned"))

    diameter = rg.RadialDimension.Create(
        style, rg.AnnotationType.Diameter, xy,
        rg.Point3d(100, 50, 0), rg.Point3d(121.2132, 71.2132, 0), rg.Point3d(150, 90, 0))
    doc.Objects.Add(diameter, attributes(dims, "dim_diameter"))
    doc.Objects.AddCircle(rg.Circle(rg.Point3d(100, 50, 0), 30), attributes(dims, "hole"))

    text = rg.TextEntity.Create(
        "FOAM 30 KG", rg.Plane(rg.Point3d(0, 140, 0), rg.Vector3d.ZAxis), style, False, 0, 0)
    text.TextHeight = 20.0
    try:
        text.SetBold(True)
    except Exception:
        pass
    doc.Objects.AddText(text, attributes(notes, "note_text"))

    points = System.Array[rg.Point3d]([rg.Point3d(150, 100, 0), rg.Point3d(170, 120, 0), rg.Point3d(190, 120, 0)])
    leader = rg.Leader.Create("CUT HERE", xy, style, points)
    doc.Objects.Add(leader, attributes(notes, "note_leader"))

    solid_index = pattern_index(doc, "Solid", Rhino.DocObjects.HatchPattern.Defaults.Solid)
    outer = rg.Rectangle3d(xy, rg.Point3d(260, 0, 0), rg.Point3d(340, 40, 0)).ToNurbsCurve()
    hole = rg.Circle(rg.Point3d(300, 20, 0), 10).ToNurbsCurve()
    solid = rg.Hatch.Create(curves(outer, hole), solid_index, 0.0, 1.0, tolerance)[0]
    doc.Objects.AddHatch(solid, attributes(hatch_layer, "hatch_solid"))

    grid_index = pattern_index(doc, "Grid", Rhino.DocObjects.HatchPattern.Defaults.Grid)
    box = rg.Rectangle3d(xy, rg.Point3d(260, 60, 0), rg.Point3d(340, 100, 0)).ToNurbsCurve()
    pattern = rg.Hatch.Create(curves(box), grid_index, 0.0, 10.0, tolerance)[0]
    doc.Objects.AddHatch(pattern, attributes(hatch_layer, "hatch_pattern"))

    mesh = rg.Mesh.CreateFromBox(
        rg.Box(xy, rg.Interval(0, 200), rg.Interval(0, 100), rg.Interval(-20, 0)), 1, 1, 1)
    doc.Objects.AddMesh(mesh, attributes(parts, "base_box"))

    options = Rhino.FileIO.FileWriteOptions()
    options.FileVersion = 8
    if not doc.Write3dmFile(OUT, options):
        raise RuntimeError("could not write " + OUT)


def main():
    doc = Rhino.RhinoDoc.CreateHeadless(None)
    try:
        build(doc)
        message = "wrote " + OUT
    except Exception:
        message = "FAILED\n" + traceback.format_exc()
    finally:
        doc.Dispose()
    with open(LOG, "w") as log:
        log.write(message + "\n")
    print(message)


main()
