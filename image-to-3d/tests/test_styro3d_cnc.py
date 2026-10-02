"""Offline tests for styro3d_cnc.py  (python test_styro3d_cnc.py; needs numpy trimesh rtree shapely).
Part 1: stub the Rhino / .NET modules and test the pure helpers.
Part 2: re-run the same check logic with trimesh on known shapes (C-channel,
L-block, sphere, flat torus) to prove the method, not just the arithmetic."""
import importlib.util, os, sys, types, tempfile
from unittest import mock
import numpy as np
import trimesh


def stub(name, **attrs):
    m = types.ModuleType(name); m.__dict__.update(attrs); sys.modules[name] = m; return m


rhino = stub("Rhino"); rhino.RhinoApp = mock.MagicMock(ExeVersion=7)
geom = stub("Rhino.Geometry"); rhino.Geometry = geom
inter = stub("Rhino.Geometry.Intersect", Intersection=mock.MagicMock()); geom.Intersect = inter
stub("rhinoscriptsyntax"); stub("scriptcontext", sticky={})
stub("System"); stub("System.Collections")
stub("System.Collections.Generic", List=mock.MagicMock(), IEnumerable=mock.MagicMock())
stub("System.Drawing", Color=mock.MagicMock())

SCRIPT = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "styro3d_cnc.py")
spec = importlib.util.spec_from_file_location("s3dcnc", SCRIPT)
S = importlib.util.module_from_spec(spec)
spec.loader.exec_module(S)

# ---------------------------------------------------------------- part 1: pure helpers
assert S.parse_counts("1x1x2") == (1, 1, 2)
assert S.parse_counts(" 2 X 1 x 3 ") == (2, 1, 3)
assert S.parse_counts("1,1,2") == (1, 1, 2) and S.parse_counts("1*2*2") == (1, 2, 2)
assert S.parse_counts("") is None and S.parse_counts("1x2") is None and S.parse_counts("0x1x1") is None
assert S.parse_counts("axbxc") is None
f = S.fit_scale((500.0, 200.0, 1000.0), (1, 1, 2), (2000.0, 1000.0, 1000.0), 10.0)
assert abs(f - (2000 - 20) / 1000.0) < 1e-12, f
print("parse_counts / fit_scale OK")

counts, corner = S.block_grid((-300, -200, 0, 300, 200, 1800), (2000, 1000, 1000))
assert counts == (1, 1, 2) and corner == (-1000.0, -500.0, -100.0), (counts, corner)
counts, corner = S.block_grid((0, 0, 0, 2000, 1000, 1000), (2000, 1000, 1000))
assert counts == (1, 1, 1) and corner == (0.0, 0.0, 0.0)        # exact fit = 1 block
cuts = S.block_cuts((3, 1, 2), (0.0, 0.0, 0.0), (100.0, 50.0, 40.0), 0.5)
assert cuts == [[100.5, 200.5], [], [40.5]], cuts
assert [S.cell_index(v, [100.5, 200.5]) for v in (-5, 50, 100.4, 100.6, 250, 999)] == [0, 0, 0, 1, 2, 2]
ids = S.block_ids((2, 1, 2))
assert ids == [("B01", 0, 0, 0), ("B02", 1, 0, 0), ("B03", 0, 0, 1), ("B04", 1, 0, 1)], ids
assert S.block_box((10, 20, 30), (100, 50, 40), 1, 0, 2) == (110, 20, 110, 210, 70, 150)
sb = S.stock_box((0, 0, 0, 100, 100, 100), (10, 20, 30, 90, 80, 60), 5, 2)
assert sb == (0, 0, 25, 100, 100, 65), sb
sb = S.stock_box((0, 0, 0, 100, 100, 100), (10, 20, 30, 90, 80, 60), 5, 4)
assert sb == (0, 15, 25, 100, 85, 65), sb
print("block grid / cuts / ids / stock OK")

sq = lambda c, r: [(c[0] - r, c[1] - r), (c[0] + r, c[1] - r), (c[0] + r, c[1] + r), (c[0] - r, c[1] + r)]
assert abs(S.poly_area(sq((0, 0), 1)) - 4.0) < 1e-12
assert S.point_in_poly(0.2, 0.1, sq((0, 0), 1)) and not S.point_in_poly(1.5, 0, sq((0, 0), 1))
loops = [sq((0, 0), 10), sq((0, 0), 6), sq((0, 0), 2), sq((30, 0), 3)]   # outer, hole, island, separate
depth, parent = S.loop_nesting(loops)
assert depth == [0, 1, 2, 0] and parent == [-1, 0, 1, -1], (depth, parent)
assert S.loop_nesting([]) == ([], [])
print("loop nesting OK")

for name, a in S.AXIS_CANDIDATES:
    for th in S.turn_angles():
        b, c = S.turned(*S.perp_frame(a), theta=th)
        au = S.v_unit(a)
        assert abs(S.v_dot(b, b) - 1) < 1e-9 and abs(S.v_dot(c, c) - 1) < 1e-9
        assert abs(S.v_dot(b, c)) < 1e-9 and abs(S.v_dot(b, au)) < 1e-9 and abs(S.v_dot(c, au)) < 1e-9
        bc = S.v_cross(b, c)
        assert max(abs(bc[i] - au[i]) for i in range(3)) < 1e-9, (name, th)   # right-handed, normal = axis
print("machine frames orthonormal + right-handed OK")

rows = [("Z", 0, 12.0, 1800), ("Y", 0, 3.10, 420), ("X", 0, 3.0, 600), ("X+Y", 0, 3.3, 500)]
assert S.pick_axis(rows)[0] == "Y"          # within 0.25 of the best -> shallower wins
rows = [("Z", 0, 1.0, 1800), ("Y", 0, 3.0, 420)]
assert S.pick_axis(rows)[0] == "Z"
rows = [("Z", 0, 1.0, 400), ("Y", 0, 1.0, 400)]
assert S.pick_axis(rows)[0] == "Z"          # full tie -> list order
assert S.turn_score((1900, 900, 900), (2000, 1000, 1000)) == (1, 1900 * 900 * 900)
assert S.turn_score((2100, 900, 900), (2000, 1000, 1000))[0] == 2
assert S.turn_score((1000, 500, 1000), (2000, 1000, 1000), (1, 1, 2))[0] == 0.5
assert S.blocks_needed((4100, 900, 2500), (2000, 1000, 1000)) == [3, 1, 3]
assert S.layers_for_depth(1000, 300) == 2 and S.layers_for_depth(600, 300) == 1 and S.layers_for_depth(5, 0) == 1
print("axis pick / turn score / layers OK")

assert S.assign_side(0b01, [5.0, 1.0]) == (0, 5.0)
assert S.assign_side(0b11, [5.0, 1.0]) == (1, 1.0)
assert S.assign_side(0, [5.0, 1.0]) == (-1, 0.0)
assert S.face_depths((1, 2, 3), (0, 0, 0, 10, 10, 10), 4) == [7, 3, 8, 2]
box = (0, 0, 0, 100, 100, 100)
assert S.on_block_face((0.01, 50, 50), (-1, 0, 0), box, 0.05)
assert not S.on_block_face((0.01, 50, 50), (0, 0, 1), box, 0.05)
assert not S.on_block_face((5, 50, 50), (-1, 0, 0), box, 0.05)
faces = [(2.0, (50, 50, 90), 0b01), (1.0, (50, 50, 10), 0b11), (3.0, (50, 50, 50), 0b00), (1.0, (50, 50, 40), 0b01)]
job = S.job_numbers(faces, box, 2, 50.0)
assert job["area"] == 7.0 and job["undercut"] == 3.0 and job["too_deep"] == 1.0, job
assert job["depth"] == [60, 10], job
print("setup assignment / job numbers OK")

tmp = tempfile.mkdtemp()
box_m = trimesh.creation.box((10, 20, 30))
p = os.path.join(tmp, "b.stl")
S.write_binary_stl(p, box_m.vertices.tolist(), box_m.faces.tolist(), "t")
m2 = trimesh.load(p)
assert m2.is_watertight and abs(m2.volume - 6000) < 1e-3
print("STL writer OK")

# ---------------------------------------------------------------- part 2: method on real shapes
def access(mesh, dirs, eps=1e-3):
    """trimesh twin of access_faces(): bit i = ray from the face centre along dirs[i] escapes."""
    rmi = trimesh.ray.ray_triangle.RayMeshIntersector(mesh)
    c, n = mesh.triangles_center, mesh.face_normals
    mask = np.zeros(len(c), int)
    for bit, d in enumerate(dirs):
        d = np.asarray(d, float); d /= np.linalg.norm(d)
        ok = n @ d > -0.02
        start = c + n * eps + d * eps
        hit = rmi.intersects_any(start, np.repeat(d[None], len(c), 0))
        mask |= ((ok & ~hit).astype(int) << bit)
    return mask


def undercut_pct(mesh, mask):
    return 100.0 * mesh.area_faces[mask == 0].sum() / mesh.area


def fine(m, edge):
    v, f = trimesh.remesh.subdivide_to_size(m.vertices, m.faces, edge)
    return trimesh.Trimesh(v, f)


# (a) C-channel along X, opening toward +Y: Y (or X) has no undercut, Z has; Y is shallower than X
from shapely.geometry import Polygon
C = [(-50, -50), (50, -50), (50, -30), (-30, -30), (-30, 30), (50, 30), (50, 50), (-50, 50)]
chan = trimesh.creation.extrude_polygon(Polygon(C), 300.0)        # C in XY, extruded along Z
chan.apply_translation((0, 0, -150.0))
chan.apply_transform(trimesh.transformations.rotation_matrix(np.pi / 2, (0, 1, 0)))   # extrusion -> X
chan.apply_transform(trimesh.transformations.rotation_matrix(np.pi / 2, (1, 0, 0)))   # opening -> +Y
assert chan.center_mass[1] < -5 and np.allclose(chan.bounds[:, 2], (-50, 50))   # back bar at -Y, open at +Y
assert chan.is_watertight
chan = fine(chan, 8.0)
rows = []
for name, a in S.AXIS_CANDIDATES:
    m = access(chan, [a, tuple(-x for x in a)])
    au = np.asarray(S.v_unit(a))
    pr = chan.vertices @ au
    rows.append((name, a, undercut_pct(chan, m), pr.max() - pr.min()))
best = S.pick_axis(rows)
print("C-channel undercut %:", ", ".join("%s %.1f" % (r[0], r[2]) for r in rows), "-> pick", best[0])
assert best[0] == "Y", best
assert dict((r[0], r[2]) for r in rows)["Z"] > 20.0

# (b) ball-nose reach on an L-block: only points near the inside corner are flagged
Lp = [(-100, 0), (100, 0), (100, 40), (-60, 40), (-60, 160), (-100, 160)]   # L in XZ, extruded along Y
lb = trimesh.creation.extrude_polygon(Polygon(Lp), 100.0)
lb.apply_transform(trimesh.transformations.rotation_matrix(np.pi / 2, (1, 0, 0)))    # XY -> XZ
assert lb.is_watertight
lb = fine(lb, 3.0)
r = 6.0
vn = lb.vertex_normals
centres = lb.vertices + vn * r
_, dist, _ = trimesh.proximity.closest_point(lb, centres)
flag = dist < 0.9 * r
corner = np.array([-60.0, 40.0])                # inside edge at x=-60, z=40, along Y
dxz = np.hypot(lb.vertices[:, 0] - corner[0], lb.vertices[:, 2] - corner[1])
print("L-block ball R6: flagged %d of %d points, max distance from the inside corner %.1f mm" % (
    flag.sum(), len(flag), dxz[flag].max() if flag.any() else -1))
assert flag.any() and dxz[flag].max() < r * 1.5 and (~flag[dxz > 3 * r]).all()

# (c) sphere R600 cut into 1000 mm blocks: 8 closed pieces, volume kept
sph = trimesh.creation.icosphere(5, 600.0)
lo, hi = sph.bounds
counts, corner = S.block_grid(tuple(lo) + tuple(hi), (1000.0, 1000.0, 1000.0))
cuts = S.block_cuts(counts, corner, (1000.0, 1000.0, 1000.0), 0.0137)
pieces = [sph]
for axis in range(3):
    for v in cuts[axis]:
        nrm = np.eye(3)[axis]
        nxt = []
        for pc in pieces:
            if v <= pc.bounds[0][axis] or v >= pc.bounds[1][axis]:
                nxt.append(pc); continue
            o = nrm * v
            nxt.append(pc.slice_plane(o, nrm, cap=True))
            nxt.append(pc.slice_plane(o, -nrm, cap=True))
        pieces = [q for q in nxt if len(q.faces)]
assign = {}
for pc in pieces:
    cc = pc.bounds.mean(0)
    key = tuple(S.cell_index(cc[i], cuts[i]) for i in range(3))
    assign[key] = pc
vol = sum(pc.volume for pc in assign.values())
print("sphere R600 -> blocks %s, pieces %d, all closed %s, volume %.4f of the original" % (
    counts, len(assign), all(pc.is_watertight for pc in assign.values()), vol / sph.volume))
assert counts == (2, 2, 2) and len(assign) == 8     # (closed caps = Rhino's job in the script; trimesh's capper is only a stand-in)
assert abs(vol / sph.volume - 1) < 1e-6
assert sorted(assign) == sorted((ix, iy, iz) for _n, ix, iy, iz in S.block_ids(counts))

# (d) flat torus cut through its middle: the section is a ring -> outer + hole
tor = trimesh.creation.torus(300.0, 80.0, major_sections=96, minor_sections=48)
sec = tor.section(plane_origin=(0, 0, 0.0137), plane_normal=(0, 0, 1))
planar, _ = sec.to_2D()
loops2d = [np.asarray(p)[:, :2].tolist() for p in planar.discrete]
depth, parent = S.loop_nesting(loops2d)
print("flat torus section: %d loops, nesting depth %s" % (len(loops2d), depth))
assert sorted(depth) == [0, 1]
print("ALL CNC TESTS PASSED")
