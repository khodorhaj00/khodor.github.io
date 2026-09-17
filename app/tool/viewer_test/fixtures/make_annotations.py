"""Writes annotations.3dm next to this script. Runs INSIDE Rhino 8 (Script Editor, or
_-RunPythonScript), because rhino3dm cannot create annotations or hatches.

    Rhino 8 > Tools > Script > Edit... > open this file > Run
    (or: Rhino.exe /nosplash /runscript="_-RunPythonScript <this file> _-Exit _No")

annotations.3dm (millimetres, saved as a Rhino 8 file), all on the XY plane:
    layer DIMS    (0,160,255)  linear (rotated) dimension 0,0 -> 200,0, line at y=-30;
                               aligned dimension 200,0 -> 200,100 (as drawn: vertical);
                               diameter dimension on a 60 mm circle centred at 100,50
    layer NOTES   (230,230,230) text "FOAM 30 KG" at 0,140; leader "CUT HERE" from 150,100
    layer HATCH   (220,70,60)  solid hatch: 80 x 40 rectangle at 260,0 with a 20 mm hole;
                               pattern hatch (second pattern in the table) 80 x 40 at 260,60
    layer PARTS   (200,200,200) a 200 x 100 x 20 box mesh at 0,0,-20 (under the drawing)
Dimension style "Fixture": text height 8, arrow length 6, text gap 2.
The viewer harness expects 5 annotations, 2 hatches, 1 mesh (run.mjs, checkAnnotations).
"""
import os

import Rhino
import Rhino.Geometry as rg
import System.Drawing as sd

HERE = os.path.dirname(os.path.abspath(__file__))
OUT = os.path.join(HERE, "annotations.3dm")


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


def box_mesh(x0, y0, z0, sx, sy, sz):
    box = rg.Box(rg.Plane.WorldXY, rg.Interval(x0, x0 + sx), rg.Interval(y0, y0 + sy), rg.Interval(z0, z0 + sz))
    return rg.Mesh.CreateFromBox(box, 1, 1, 1)


def main():
    doc = Rhino.RhinoDoc.CreateHeadless(None)
    try:
        doc.ModelUnitSystem = Rhino.UnitSystem.Millimeters

        style = Rhino.DocObjects.DimensionStyle()
        style.Name = "Fixture"
        style.TextHeight = 8.0
        style.ArrowLength = 6.0
        style.TextGap = 2.0
        style_index = doc.DimStyles.Add(style, False)
        doc.DimStyles.SetCurrent(style_index, True)
        style = doc.DimStyles[style_index]

        dims = add_layer(doc, "DIMS", (0, 160, 255))
        notes = add_layer(doc, "NOTES", (230, 230, 230))
        hatch_layer = add_layer(doc, "HATCH", (220, 70, 60))
        parts = add_layer(doc, "PARTS", (200, 200, 200))
        xy = rg.Plane.WorldXY

        linear = rg.LinearDimension.Create(
            Rhino.Geometry.AnnotationType.Rotated, style, xy, rg.Vector3d.XAxis,
            rg.Point3d(0, 0, 0), rg.Point3d(200, 0, 0), rg.Point3d(100, -30, 0), 0.0)
        doc.Objects.AddLinearDimension(linear, attributes(dims, "dim_linear"))

        aligned = rg.LinearDimension.Create(
            Rhino.Geometry.AnnotationType.Aligned, style, xy, rg.Vector3d.XAxis,
            rg.Point3d(200, 0, 0), rg.Point3d(200, 100, 0), rg.Point3d(230, 50, 0), 0.0)
        doc.Objects.AddLinearDimension(aligned, attributes(dims, "dim_aligned"))

        diameter = rg.RadialDimension.Create(
            style, Rhino.Geometry.AnnotationType.Diameter, xy,
            rg.Point3d(100, 50, 0), rg.Point3d(121.2, 71.2, 0), rg.Point3d(150, 90, 0))
        doc.Objects.AddRadialDimension(diameter, attributes(dims, "dim_diameter"))
        doc.Objects.AddCircle(rg.Circle(rg.Point3d(100, 50, 0), 30), attributes(dims, "hole"))

        text = rg.TextEntity.Create("FOAM 30 KG", rg.Plane(rg.Point3d(0, 140, 0), rg.Vector3d.ZAxis), style, False, 0, 0)
        doc.Objects.AddText(text, attributes(notes, "note_text"))

        leader = rg.Leader.Create(
            "CUT HERE", xy, style,
            [rg.Point3d(150, 100, 0), rg.Point3d(170, 120, 0), rg.Point3d(190, 120, 0)])
        doc.Objects.AddLeader(leader, attributes(notes, "note_leader"))

        tolerance = doc.ModelAbsoluteTolerance
        solid_index = doc.HatchPatterns.FindName("Solid").Index
        outer = rg.Rectangle3d(xy, rg.Point3d(260, 0, 0), rg.Point3d(340, 40, 0)).ToNurbsCurve()
        hole = rg.Circle(rg.Point3d(300, 20, 0), 10).ToNurbsCurve()
        solid = rg.Hatch.Create([outer, hole], solid_index, 0.0, 1.0, tolerance)[0]
        doc.Objects.AddHatch(solid, attributes(hatch_layer, "hatch_solid"))

        pattern_index = 1 if doc.HatchPatterns.Count > 1 else solid_index
        box = rg.Rectangle3d(xy, rg.Point3d(260, 60, 0), rg.Point3d(340, 100, 0)).ToNurbsCurve()
        pattern = rg.Hatch.Create([box], pattern_index, 0.0, 10.0, tolerance)[0]
        doc.Objects.AddHatch(pattern, attributes(hatch_layer, "hatch_pattern"))

        doc.Objects.AddMesh(box_mesh(0, 0, -20, 200, 100, 20), attributes(parts, "base_box"))

        options = Rhino.FileIO.FileWriteOptions()
        options.FileVersion = 8
        if not doc.Write3dmFile(OUT, options):
            raise RuntimeError("could not write " + OUT)
        print("wrote " + OUT)
    finally:
        doc.Dispose()


main()
