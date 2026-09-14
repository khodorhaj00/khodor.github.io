"""Regenerates the viewer-only .3dm fixtures used by run.mjs (the shared ones live in
backend/test/fixtures).

    pip install rhino3dm && python make_fixtures.py

nested_blocks.3dm   definition 'inner' (50 mm box) and definition 'outer' whose only member
                    is a reference to 'inner' moved by (100,0,0); two top-level references
                    to 'outer' at y=100 / y=300 and one to 'inner' at y=-200. Rhino shows
                    boxes centred at (100,100,0), (100,300,0) and (0,-200,0).
hidden_objects.3dm  three boxes: visible, hidden in Rhino (Visible=False, Mode Hidden) at
                    x=1000, locked at x=500. Rhino draws two.
black_layer.3dm     layer 'Default' coloured black (Rhino's factory default) with a box, a
                    polyline and a point; a dark-red (64,0,0) layer with a second box.
textured.3dm        40 boxes on a layer whose render material carries an embedded PNG
                    texture, as Rhino writes with "Save textures" on.
"""
import os
import struct
import zlib

import rhino3dm as r

HERE = os.path.dirname(os.path.abspath(__file__))


def add_layer(f, name, rgb):
    layer = r.Layer()
    layer.Name = name
    layer.Color = (rgb[0], rgb[1], rgb[2], 255)
    return f.Layers.Add(layer)


def box_mesh(cx, cy, cz, s):
    m = r.Mesh()
    h = s / 2.0
    for p in [(-h, -h, -h), (h, -h, -h), (h, h, -h), (-h, h, -h), (-h, -h, h), (h, -h, h), (h, h, h), (-h, h, h)]:
        m.Vertices.Add(cx + p[0], cy + p[1], cz + p[2])
    for a, b, c, d in [(0, 3, 2, 1), (4, 5, 6, 7), (0, 1, 5, 4), (1, 2, 6, 5), (2, 3, 7, 6), (3, 0, 4, 7)]:
        m.Faces.AddFace(a, b, c, d)
    m.Normals.ComputeNormals()
    m.Compact()
    return m


def new_file():
    f = r.File3dm()
    f.Settings.ModelUnitSystem = r.UnitSystem.Millimeters
    return f


def nested_blocks():
    f = new_file()
    lay = add_layer(f, 'BLOCKS', (180, 60, 200))
    inner_idx = f.InstanceDefinitions.Add('inner', 'inner block', '', '', r.Point3d(0, 0, 0),
                                          (box_mesh(0, 0, 0, 50),), (r.ObjectAttributes(),))
    inner = f.InstanceDefinitions[inner_idx]
    nested_ref = r.InstanceReference(inner.Id, r.Transform.Translation(100.0, 0.0, 0.0))
    outer_idx = f.InstanceDefinitions.Add('outer', 'outer block', '', '', r.Point3d(0, 0, 0),
                                          (nested_ref,), (r.ObjectAttributes(),))
    outer = f.InstanceDefinitions[outer_idx]
    for k, y in enumerate([100.0, 300.0]):
        a = r.ObjectAttributes()
        a.LayerIndex = lay
        a.Name = f'outer_ref_{k}'
        a.SetUserString('PART_ID', f'OUTER{k}')
        f.Objects.AddInstanceObject(r.InstanceReference(outer.Id, r.Transform.Translation(0.0, y, 0.0)), a)
    a = r.ObjectAttributes()
    a.LayerIndex = lay
    a.Name = 'inner_ref'
    f.Objects.AddInstanceObject(r.InstanceReference(inner.Id, r.Transform.Translation(0.0, -200.0, 0.0)), a)
    f.Write(os.path.join(HERE, 'nested_blocks.3dm'), 7)


def hidden_objects():
    f = new_file()
    lay = add_layer(f, 'PARTS', (200, 60, 40))
    a = r.ObjectAttributes()
    a.LayerIndex = lay
    a.Name = 'visible_box'
    f.Objects.AddMesh(box_mesh(0, 0, 0, 100), a)
    a = r.ObjectAttributes()
    a.LayerIndex = lay
    a.Name = 'hidden_box'
    a.Visible = False
    f.Objects.AddMesh(box_mesh(1000, 0, 0, 100), a)
    a = r.ObjectAttributes()
    a.LayerIndex = lay
    a.Name = 'locked_box'
    a.Mode = r.ObjectMode.Locked
    f.Objects.AddMesh(box_mesh(500, 0, 0, 100), a)
    f.Write(os.path.join(HERE, 'hidden_objects.3dm'), 7)


def black_layer():
    f = new_file()
    black = add_layer(f, 'Default', (0, 0, 0))
    dark_red = add_layer(f, 'DARKRED', (64, 0, 0))
    a = r.ObjectAttributes()
    a.LayerIndex = black
    a.Name = 'black_box'
    f.Objects.AddMesh(box_mesh(0, 0, 0, 100), a)
    a = r.ObjectAttributes()
    a.LayerIndex = black
    pl = r.Polyline([r.Point3d(-100, -100, 0), r.Point3d(400, -100, 0), r.Point3d(400, 100, 0),
                     r.Point3d(-100, 100, 0), r.Point3d(-100, -100, 0)])
    f.Objects.AddCurve(pl.ToNurbsCurve(), a)
    f.Objects.AddPoint(r.Point3d(150, 0, 120), a)
    a = r.ObjectAttributes()
    a.LayerIndex = dark_red
    a.Name = 'dark_red_box'
    f.Objects.AddMesh(box_mesh(300, 0, 0, 100), a)
    f.Write(os.path.join(HERE, 'black_layer.3dm'), 7)


def write_png(path, w, h):
    rows = []
    for y in range(h):
        row = bytearray(b'\x00')
        for x in range(w):
            row += bytes([(x * 4) & 255, (y * 4) & 255, 128])
        rows.append(bytes(row))

    def chunk(tag, data):
        body = struct.pack('>I', len(data)) + tag + data
        return body + struct.pack('>I', zlib.crc32(tag + data) & 0xffffffff)

    png = b'\x89PNG\r\n\x1a\n'
    png += chunk(b'IHDR', struct.pack('>IIBBBBB', w, h, 8, 2, 0, 0, 0))
    png += chunk(b'IDAT', zlib.compress(b''.join(rows), 9))
    png += chunk(b'IEND', b'')
    with open(path, 'wb') as fh:
        fh.write(png)


def textured(n=40):
    f = new_file()
    # Relative path (the generator chdirs to HERE) so the fixture does not embed a machine path.
    tex_path = 'texture.png'
    write_png(tex_path, 64, 64)
    f.EmbeddedFiles.Add(r.EmbeddedFile.Read(tex_path))
    m = r.Material()
    m.Name = 'wood'
    m.DiffuseColor = (200, 150, 100, 255)
    m.SetBitmapTexture(tex_path)
    mat = f.Materials.Add(m)
    layer = r.Layer()
    layer.Name = 'TEXTURED'
    layer.Color = (200, 60, 40, 255)
    layer.RenderMaterialIndex = mat
    lay = f.Layers.Add(layer)
    for i in range(n):
        a = r.ObjectAttributes()
        a.LayerIndex = lay
        a.Name = f'box_{i}'
        f.Objects.AddMesh(box_mesh((i % 8) * 120.0, (i // 8) * 120.0, 0, 100), a)
    f.Write(os.path.join(HERE, 'textured.3dm'), 7)
    os.remove(tex_path)


if __name__ == '__main__':
    os.chdir(HERE)
    nested_blocks()
    hidden_objects()
    black_layer()
    textured()
    for name in ['nested_blocks.3dm', 'hidden_objects.3dm', 'black_layer.3dm', 'textured.3dm']:
        g = r.File3dm.Read(os.path.join(HERE, name))
        print(name, 'objects', len(g.Objects), 'layers', len(g.Layers), 'idefs', len(g.InstanceDefinitions),
              'embedded', len(g.EmbeddedFiles), 'bytes', os.path.getsize(os.path.join(HERE, name)))
