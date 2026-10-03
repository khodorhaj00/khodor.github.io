# -*- coding: utf-8 -*-
"""
s3d_qmesh.py | Styro3D clean quad-mesh kernel
=============================================
Pure Python (2.7 and 3.x, only math / json / struct). The same file runs in the
cloud (CPython 3) and inside Rhino 7 / 8 (IronPython 2.7), so a recipe builds the
same mesh in both places.

Every builder returns a CLOSED, consistently oriented mesh with clean topology:
structured quad grids (rings x segments), quad caps (Coons patches), no poles
unless asked for. Planar caps of extruded outlines are triangulated, then paired
into quads where the pair makes a good quad.

  mesh = revolve([(0, 0), (120, 0), (90, 300), (40, 420), (0, 430)], segments=64)
  print(check(mesh))
  write_obj(mesh, "vase.obj")

Recipe (JSON, units mm) -> build_recipe(recipe) -> [(name, QMesh)]. See RECIPE.md.
"""
from __future__ import division, print_function

import json
import math
import struct

VERSION = "1.0"
EPS = 1e-9


# =============================================================================
# Small vector maths (tuples)
# =============================================================================
def vadd(a, b):
    return (a[0] + b[0], a[1] + b[1], a[2] + b[2])


def vsub(a, b):
    return (a[0] - b[0], a[1] - b[1], a[2] - b[2])


def vmul(a, s):
    return (a[0] * s, a[1] * s, a[2] * s)


def vdot(a, b):
    return a[0] * b[0] + a[1] * b[1] + a[2] * b[2]


def vcross(a, b):
    return (a[1] * b[2] - a[2] * b[1], a[2] * b[0] - a[0] * b[2], a[0] * b[1] - a[1] * b[0])


def vlen(a):
    return math.sqrt(vdot(a, a))


def vunit(a):
    n = vlen(a)
    if n < EPS:
        return (0.0, 0.0, 0.0)
    return (a[0] / n, a[1] / n, a[2] / n)


def vlerp(a, b, t):
    return (a[0] + (b[0] - a[0]) * t, a[1] + (b[1] - a[1]) * t, a[2] + (b[2] - a[2]) * t)


# =============================================================================
# Mesh container
# =============================================================================
class QMesh(object):
    """verts: [(x, y, z)], faces: [(a, b, c, d)] quads or (a, b, c) triangles."""

    def __init__(self, verts=None, faces=None, name=""):
        self.v = list(verts or [])
        self.f = list(faces or [])
        self.name = name

    def copy(self, name=None):
        return QMesh(list(self.v), list(self.f), self.name if name is None else name)

    def add_vert(self, p):
        self.v.append((float(p[0]), float(p[1]), float(p[2])))
        return len(self.v) - 1

    def append(self, other):
        off = len(self.v)
        self.v.extend(other.v)
        self.f.extend(tuple(i + off for i in face) for face in other.f)
        return self

    # ---- transforms (in place, return self) ----
    def apply(self, fn):
        self.v = [fn(p) for p in self.v]
        return self

    def move(self, d):
        return self.apply(lambda p: (p[0] + d[0], p[1] + d[1], p[2] + d[2]))

    def scale(self, s, centre=(0.0, 0.0, 0.0)):
        if not isinstance(s, (list, tuple)):
            s = (s, s, s)
        c = centre
        self.apply(lambda p: (c[0] + (p[0] - c[0]) * s[0], c[1] + (p[1] - c[1]) * s[1],
                              c[2] + (p[2] - c[2]) * s[2]))
        if s[0] * s[1] * s[2] < 0:            # mirrored by scaling: keep normals outward
            self.flip()
        return self

    def rotate(self, axis, deg, centre=(0.0, 0.0, 0.0)):
        k = vunit(axis)
        t = math.radians(deg)
        ct, st = math.cos(t), math.sin(t)

        def rot(p):
            q = vsub(p, centre)
            # Rodrigues
            r = vadd(vadd(vmul(q, ct), vmul(vcross(k, q), st)), vmul(k, vdot(k, q) * (1 - ct)))
            return vadd(r, centre)
        return self.apply(rot)

    def mirror(self, axis):
        i = "xyz".index(axis.lower())
        s = [1.0, 1.0, 1.0]
        s[i] = -1.0
        return self.scale(tuple(s))

    def flip(self):
        self.f = [tuple(reversed(face)) for face in self.f]
        return self

    def bbox(self):
        xs = [p[0] for p in self.v]
        ys = [p[1] for p in self.v]
        zs = [p[2] for p in self.v]
        return (min(xs), min(ys), min(zs), max(xs), max(ys), max(zs))


# =============================================================================
# Topology helpers
# =============================================================================
def edge_faces(mesh):
    """{(a, b) sorted: [face index, ...]}"""
    out = {}
    for fi, face in enumerate(mesh.f):
        n = len(face)
        for i in range(n):
            a, b = face[i], face[(i + 1) % n]
            key = (a, b) if a < b else (b, a)
            out.setdefault(key, []).append(fi)
    return out


def orient(mesh):
    """Make neighbouring faces agree (each shared edge used in opposite directions),
    then flip the whole shell if its volume is negative. Works per connected shell."""
    ef = edge_faces(mesh)
    nf = len(mesh.f)
    done = [False] * nf
    faces = [list(f) for f in mesh.f]

    def directed(face):
        n = len(face)
        return set((face[i], face[(i + 1) % n]) for i in range(n))

    shells = []
    for start in range(nf):
        if done[start]:
            continue
        stack = [start]
        done[start] = True
        shell = []
        while stack:
            fi = stack.pop()
            shell.append(fi)
            face = faces[fi]
            n = len(face)
            for i in range(n):
                a, b = face[i], face[(i + 1) % n]
                key = (a, b) if a < b else (b, a)
                for fj in ef.get(key, ()):
                    if fj == fi or done[fj]:
                        continue
                    if (a, b) in directed(faces[fj]):     # same direction -> flip neighbour
                        faces[fj] = list(reversed(faces[fj]))
                    done[fj] = True
                    stack.append(fj)
        shells.append(shell)
    mesh.f = [tuple(f) for f in faces]
    for shell in shells:
        vol = 0.0
        for fi in shell:
            for tri in _tris(mesh.f[fi]):
                a, b, c = (mesh.v[i] for i in tri)
                vol += vdot(a, vcross(b, c))
        if vol < 0:
            for fi in shell:
                mesh.f[fi] = tuple(reversed(mesh.f[fi]))
    return mesh


def _tris(face):
    if len(face) == 3:
        return [face]
    if len(face) == 4:
        return [(face[0], face[1], face[2]), (face[0], face[2], face[3])]
    return [(face[0], face[i], face[i + 1]) for i in range(1, len(face) - 1)]


def weld(mesh, tol=1e-6):
    """Merge coincident vertices (used when grids are built side by side)."""
    key_of = {}
    remap = []
    newv = []
    inv = 1.0 / tol
    for p in mesh.v:
        key = (int(round(p[0] * inv)), int(round(p[1] * inv)), int(round(p[2] * inv)))
        if key not in key_of:
            key_of[key] = len(newv)
            newv.append(p)
        remap.append(key_of[key])
    faces = []
    for face in mesh.f:
        nf = []
        for i in face:
            j = remap[i]
            if not nf or nf[-1] != j:
                nf.append(j)
        if len(nf) > 1 and nf[0] == nf[-1]:
            nf.pop()
        if len(nf) >= 3:
            faces.append(tuple(nf))
    mesh.v, mesh.f = newv, faces
    return mesh


# =============================================================================
# Building blocks: tubes (ring grids) and caps
# =============================================================================
def add_rings(mesh, rings):
    """Append rings of points; returns [[vertex index]] per ring."""
    out = []
    for ring in rings:
        out.append([mesh.add_vert(p) for p in ring])
    return out


def connect_rings(mesh, ids, closed_u=True, closed_v=False):
    """Quads between consecutive index rings (all rings the same length)."""
    nv = len(ids)
    n = len(ids[0])
    last_v = nv if closed_v else nv - 1
    for i in range(last_v):
        r0, r1 = ids[i], ids[(i + 1) % nv]
        last_u = n if closed_u else n - 1
        for j in range(last_u):
            j1 = (j + 1) % n
            mesh.f.append((r0[j], r0[j1], r1[j1], r1[j]))


def cap_quad(mesh, ring, dome=0.0, normal=None):
    """Close a ring of N = 4k vertex indices with a k x k quad grid (Coons patch).
    dome > 0 lifts the inside along `normal` (a sine bump), for rounded ends."""
    n = len(ring)
    if n % 4 or n < 4:
        return cap_fan(mesh, ring)
    k = n // 4
    P = [mesh.v[i] for i in ring]
    G = [[None] * (k + 1) for _ in range(k + 1)]
    for i in range(k + 1):
        G[i][0] = ring[i]
        G[i][k] = ring[3 * k - i]
    for j in range(k + 1):
        G[k][j] = ring[k + j]
        G[0][j] = ring[(4 * k - j) % n]
    pos = lambda idx: mesh.v[idx]
    p00, p10, p11, p01 = pos(G[0][0]), pos(G[k][0]), pos(G[k][k]), pos(G[0][k])
    if normal is None:
        c = vmul(reduce_add(P), 1.0 / n)
        nrm = (0.0, 0.0, 0.0)
        for a in range(n):
            nrm = vadd(nrm, vcross(vsub(P[a], c), vsub(P[(a + 1) % n], c)))
        normal = vunit(nrm)
    for i in range(1, k):
        u = i / k
        for j in range(1, k):
            w = j / k
            b, t = pos(G[i][0]), pos(G[i][k])
            l, r = pos(G[0][j]), pos(G[k][j])
            p = vsub(vadd(vadd(vmul(b, 1 - w), vmul(t, w)), vadd(vmul(l, 1 - u), vmul(r, u))),
                     vadd(vadd(vmul(p00, (1 - u) * (1 - w)), vmul(p10, u * (1 - w))),
                          vadd(vmul(p01, (1 - u) * w), vmul(p11, u * w))))
            if dome:
                p = vadd(p, vmul(normal, dome * math.sin(math.pi * u) * math.sin(math.pi * w)))
            G[i][j] = mesh.add_vert(p)
    for i in range(k):
        for j in range(k):
            mesh.f.append((G[i][j], G[i + 1][j], G[i + 1][j + 1], G[i][j + 1]))


def cap_fan(mesh, ring, centre=None):
    """Triangle fan to the centre (the simple pole cap)."""
    if centre is None:
        centre = vmul(reduce_add([mesh.v[i] for i in ring]), 1.0 / len(ring))
    c = mesh.add_vert(centre)
    n = len(ring)
    for j in range(n):
        mesh.f.append((ring[j], ring[(j + 1) % n], c))


def reduce_add(pts):
    s = (0.0, 0.0, 0.0)
    for p in pts:
        s = vadd(s, p)
    return s


def ring_points(n, rx, ry, z=0.0, cx=0.0, cy=0.0, expo=2.0, phase=math.pi / 4):
    """N points on a superellipse |x/rx|^e + |y/ry|^e = 1 (e = 2: ellipse), starting at
    `phase` so a quad cap's corners sit on the diagonals (cap grid aligned with X/Y)."""
    out = []
    for j in range(n):
        t = phase + 2 * math.pi * j / n
        c, s = math.cos(t), math.sin(t)
        x = rx * _sgnpow(c, 2.0 / expo)
        y = ry * _sgnpow(s, 2.0 / expo)
        out.append((cx + x, cy + y, z))
    return out


def _sgnpow(v, p):
    return math.copysign(abs(v) ** p, v)


# =============================================================================
# Primitives (all quads, closed)
# =============================================================================
def box(size, segs=(1, 1, 1), centre=(0.0, 0.0, 0.0)):
    sx, sy, sz = size
    nx, ny, nz = [max(1, int(s)) for s in segs]
    m = QMesh(name="box")
    hx, hy, hz = sx / 2.0, sy / 2.0, sz / 2.0

    def grid(origin, du, dv, nu, nv):
        base = len(m.v)
        for i in range(nu + 1):
            for j in range(nv + 1):
                m.add_vert(vadd(origin, vadd(vmul(du, i / nu), vmul(dv, j / nv))))
        for i in range(nu):
            for j in range(nv):
                a = base + i * (nv + 1) + j
                m.f.append((a, a + nv + 1, a + nv + 2, a + 1))
    grid((-hx, -hy, -hz), (sx, 0, 0), (0, sy, 0), nx, ny)          # bottom
    grid((-hx, -hy, hz), (0, sy, 0), (sx, 0, 0), ny, nx)           # top
    grid((-hx, -hy, -hz), (0, 0, sz), (sx, 0, 0), nz, nx)          # front (-Y)
    grid((-hx, hy, -hz), (sx, 0, 0), (0, 0, sz), nx, nz)           # back
    grid((-hx, -hy, -hz), (0, sy, 0), (0, 0, sz), ny, nz)          # left (-X)
    grid((hx, -hy, -hz), (0, 0, sz), (0, sy, 0), nz, ny)           # right
    weld(m, 1e-7 * max(sx, sy, sz, 1.0))
    orient(m)
    return m.move(centre)


def sphere(r, n=8, centre=(0.0, 0.0, 0.0)):
    """Quad sphere (spherified cube): no poles, even quads."""
    m = box((2.0, 2.0, 2.0), (n, n, n))

    def sph(p):
        x, y, z = p
        x2, y2, z2 = x * x, y * y, z * z
        return (r * x * math.sqrt(max(0.0, 1 - y2 / 2 - z2 / 2 + y2 * z2 / 3)),
                r * y * math.sqrt(max(0.0, 1 - z2 / 2 - x2 / 2 + z2 * x2 / 3)),
                r * z * math.sqrt(max(0.0, 1 - x2 / 2 - y2 / 2 + x2 * y2 / 3)))
    m.apply(sph)
    m.name = "sphere"
    return m.move(centre)


def cylinder(r, h, segments=32, rings=1, centre=(0.0, 0.0, 0.0), rx=None, ry=None, expo=2.0):
    """Upright (Z) cylinder or superellipse prism, base at centre z, quad caps."""
    segments = _mult4(segments)
    rx = r if rx is None else rx
    ry = r if ry is None else ry
    m = QMesh(name="cylinder")
    rings_pts = [ring_points(segments, rx, ry, h * i / max(1, rings), expo=expo) for i in range(max(1, rings) + 1)]
    ids = add_rings(m, rings_pts)
    connect_rings(m, ids)
    cap_quad(m, ids[0], normal=(0, 0, -1))
    cap_quad(m, ids[-1], normal=(0, 0, 1))
    orient(m)
    return m.move(centre)


def cone(r1, r2, h, segments=32, rings=1, centre=(0.0, 0.0, 0.0)):
    """Frustum r1 (bottom) -> r2 (top); r2 = 0 gives a pointed top (small dome cap)."""
    segments = _mult4(segments)
    prof = [(r1 + (r2 - r1) * i / max(1, rings), h * i / max(1, rings)) for i in range(max(1, rings) + 1)]
    m = revolve(prof, segments)
    m.name = "cone"
    return m.move(centre)


def torus(R, r, nu=48, nv=16, centre=(0.0, 0.0, 0.0)):
    m = QMesh(name="torus")
    ids = []
    for i in range(nu):
        a = 2 * math.pi * i / nu
        ring = []
        for j in range(nv):
            b = 2 * math.pi * j / nv
            rr = R + r * math.cos(b)
            ring.append(m.add_vert((rr * math.cos(a), rr * math.sin(a), r * math.sin(b))))
        ids.append(ring)
    connect_rings(m, ids, closed_u=True, closed_v=True)
    orient(m)
    return m.move(centre)


def _mult4(n):
    n = max(4, int(n))
    return n + (-n) % 4


# =============================================================================
# Resampling (even quads need evenly spaced points)
# =============================================================================
def corner_flags(pts, closed, corner_deg=35.0):
    """True where the polyline turns more than corner_deg (kept as exact vertices)."""
    n = len(pts)
    out = [False] * n
    lim = math.radians(corner_deg)
    for i in range(n):
        if not closed and i in (0, n - 1):
            out[i] = True
            continue
        a, b, c = pts[(i - 1) % n], pts[i], pts[(i + 1) % n]
        u = (b[0] - a[0], b[1] - a[1])
        v = (c[0] - b[0], c[1] - b[1])
        nu, nv = math.hypot(*u), math.hypot(*v)
        if nu < EPS or nv < EPS:
            continue
        cosang = max(-1.0, min(1.0, (u[0] * v[0] + u[1] * v[1]) / (nu * nv)))
        out[i] = math.acos(cosang) > lim
    return out


def resample(pts, step=None, count=None, closed=False, corner_deg=35.0):
    """Even spacing along a 2D/3D polyline, corners kept as vertices. Give `step`
    (target edge length) or `count` (total points; a closed count is kept exact)."""
    pts = [tuple(float(c) for c in p) for p in pts]
    dim = len(pts[0])
    if closed and _dist(pts[0], pts[-1]) < EPS:
        pts = pts[:-1]
    n = len(pts)
    flags = corner_flags([p[:2] for p in pts], closed, corner_deg) if dim >= 2 else [False] * n
    seq = pts + [pts[0]] if closed else pts
    fl = flags + [flags[0]] if closed else flags
    seg = [_dist(seq[i], seq[i + 1]) for i in range(len(seq) - 1)]
    total = sum(seg)
    if total < EPS:
        return pts
    if count is None:
        count = max(3 if closed else 2, int(round(total / max(step, EPS))) + (0 if closed else 1))
    # split at corners, give each run a share of the points by length
    cuts = [i for i in range(len(seq) - (1 if closed else 0)) if fl[i]] if any(fl) else []
    if closed and not cuts:
        runs = [(0, len(seq) - 1)]
    else:
        if not closed:
            cuts = sorted(set([0, len(seq) - 1] + cuts))
        else:
            cuts = sorted(set(cuts))
            cuts = cuts + [cuts[0] + len(seq) - 1]
        runs = [(cuts[i], cuts[i + 1]) for i in range(len(cuts) - 1)]
    run_len = []
    for a, b in runs:
        run_len.append(sum(seg[i % len(seg)] for i in range(a, b)))
    nseg_total = count if closed else count - 1
    shares = [max(1, int(round(nseg_total * L / total))) for L in run_len]
    diff = nseg_total - sum(shares)
    order = sorted(range(len(runs)), key=lambda r: -run_len[r])
    i = 0
    while diff != 0 and order:
        r = order[i % len(order)]
        if diff > 0:
            shares[r] += 1
            diff -= 1
        elif shares[r] > 1:
            shares[r] -= 1
            diff += 1
        i += 1
        if i > 10 * len(order) + abs(diff) * 10:
            break
    out = []
    L = len(seg)
    for (a, b), k in zip(runs, shares):
        idxs = [j % L for j in range(a, b)]
        lens = [seg[j] for j in idxs]
        tot = sum(lens)
        for s_i in range(k):
            target = tot * s_i / k
            acc = 0.0
            for j, l in zip(idxs, lens):
                if acc + l >= target - 1e-12:
                    t = (target - acc) / l if l > EPS else 0.0
                    p0, p1 = seq[j], seq[j + 1]
                    out.append(tuple(p0[c] + (p1[c] - p0[c]) * t for c in range(dim)))
                    break
                acc += l
    if not closed:
        out.append(seq[-1])
    return out


def _dist(a, b):
    return math.sqrt(sum((a[i] - b[i]) ** 2 for i in range(len(a))))


# =============================================================================
# Profile operations
# =============================================================================
def revolve(profile, segments=48, axis_tol=1e-6, even=True):
    """profile: [(r, z)] from one end to the other (r >= 0). Points on the axis
    (r = 0) at either end become rounded quad caps (no pole). even: resample the
    profile so its steps match the ring spacing (near-square quads)."""
    segments = _mult4(segments)
    prof = [(max(0.0, float(r)), float(z)) for r, z in profile]
    if even and len(prof) >= 2:
        rmax = max(r for r, _z in prof)
        prof = resample(prof, step=2 * math.pi * max(rmax, EPS) / segments * 0.9)
        prof = _trim_flat_end(_trim_flat_end(prof, True, axis_tol), False, axis_tol)
    dome0 = dome1 = 0.0
    if prof[0][0] <= axis_tol:
        z_axis = prof[0][1]
        prof = prof[1:]
        dome0 = abs(z_axis - prof[0][1])
    if prof[-1][0] <= axis_tol:
        z_axis = prof[-1][1]
        prof = prof[:-1]
        dome1 = abs(z_axis - prof[-1][1])
    m = QMesh(name="revolve")
    rings = []
    for r, z in prof:
        rings.append([(r * math.cos(math.pi / 4 + 2 * math.pi * j / segments),
                       r * math.sin(math.pi / 4 + 2 * math.pi * j / segments), z) for j in range(segments)])
    ids = add_rings(m, rings)
    connect_rings(m, ids)
    down = (0.0, 0.0, -1.0) if prof[0][1] <= prof[-1][1] else (0.0, 0.0, 1.0)
    cap_quad(m, ids[0], dome=dome0, normal=down)
    cap_quad(m, ids[-1], dome=dome1, normal=vmul(down, -1.0))
    orient(m)
    return m


def _trim_flat_end(prof, from_start, axis_tol):
    """A flat end disc resampled into rings gives tiny centre quads: keep the rings
    down to 45 % of the disc radius, the quad cap fills the middle with a grid."""
    seq = prof if from_start else prof[::-1]
    if seq[0][0] > axis_tol:
        return prof
    z0 = seq[0][1]
    flat = [p for p in seq if abs(p[1] - z0) < 1e-9 * max(1.0, abs(z0)) + 1e-9]
    if len(flat) > 2:
        r_edge = max(p[0] for p in flat)
        seq = [seq[0]] + [p for p in seq[1:]
                          if not (abs(p[1] - z0) < 1e-9 * max(1.0, abs(z0)) + 1e-9 and p[0] < 0.45 * r_edge)]
    return seq if from_start else seq[::-1]


def loft(sections, cap_start="quad", cap_end="quad", dome_start=0.0, dome_end=0.0):
    """sections: list of rings, each a list of N 3D points (same N, same start and
    direction). Caps: 'quad' (Coons grid; N must be 4k), 'fan' or 'open'."""
    m = QMesh(name="loft")
    ids = add_rings(m, sections)
    connect_rings(m, ids)
    a0 = vsub(_centroid(sections[0]), _centroid(sections[1]))
    a1 = vsub(_centroid(sections[-1]), _centroid(sections[-2]))
    for ring, cap, dome, out in ((ids[0], cap_start, dome_start, a0), (ids[-1], cap_end, dome_end, a1)):
        if cap == "quad":
            cap_quad(m, ring, dome=dome, normal=vunit(out))
        elif cap == "fan":
            cap_fan(m, ring)
    orient(m)
    return m


def _centroid(pts):
    return vmul(reduce_add(pts), 1.0 / len(pts))


def sweep(profile, path, closed_path=False, cap="quad", twist_deg=0.0, scale_end=1.0, even=True):
    """profile: [(x, y)] ring (N = 4k for quad caps) in the path's normal plane;
    path: [(x, y, z)]. Rotation-minimising frames, optional twist and taper.
    even: resample the path so ring spacing matches the profile's edge length."""
    if even and len(path) >= 2:
        per = sum(math.hypot(profile[i][0] - profile[i - 1][0], profile[i][1] - profile[i - 1][1])
                  for i in range(len(profile)))
        path = resample([tuple(p) for p in path], step=per / len(profile), closed=closed_path, corner_deg=60.0)
    frames = rmf_frames(path, closed_path)
    m = QMesh(name="sweep")
    rings = []
    n = len(path)
    for i, (p, t, u, w) in enumerate(frames):
        f = i / max(1, n - 1)
        a = math.radians(twist_deg * f)
        s = 1.0 + (scale_end - 1.0) * f
        ca, sa = math.cos(a), math.sin(a)
        ring = []
        for x, y in profile:
            xr, yr = (x * ca - y * sa) * s, (x * sa + y * ca) * s
            ring.append(vadd(p, vadd(vmul(u, xr), vmul(w, yr))))
        rings.append(ring)
    ids = add_rings(m, rings)
    connect_rings(m, ids, closed_v=closed_path)
    if not closed_path and cap != "open":
        for ring in (ids[0], ids[-1]):
            cap_quad(m, ring) if cap == "quad" else cap_fan(m, ring)
    orient(m)
    return m


def rmf_frames(path, closed=False):
    """Rotation-minimising frames by the double-reflection method:
    [(point, tangent, normal, binormal)]."""
    n = len(path)
    tang = []
    for i in range(n):
        if closed:
            a, b = path[(i - 1) % n], path[(i + 1) % n]
        else:
            a, b = path[max(0, i - 1)], path[min(n - 1, i + 1)]
        tang.append(vunit(vsub(b, a)))
    t0 = tang[0]
    ref = (0.0, 0.0, 1.0) if abs(t0[2]) < 0.9 else (1.0, 0.0, 0.0)
    r = vunit(vcross(ref, t0))
    out = [(path[0], t0, r, vcross(t0, r))]
    for i in range(n - 1):
        x0, x1 = path[i], path[i + 1]
        v1 = vsub(x1, x0)
        c1 = vdot(v1, v1)
        if c1 < EPS:
            out.append((x1, tang[i + 1], r, vcross(tang[i + 1], r)))
            continue
        rl = vsub(r, vmul(v1, 2.0 / c1 * vdot(v1, r)))
        tl = vsub(tang[i], vmul(v1, 2.0 / c1 * vdot(v1, tang[i])))
        v2 = vsub(tang[i + 1], tl)
        c2 = vdot(v2, v2)
        r = rl if c2 < EPS else vsub(rl, vmul(v2, 2.0 / c2 * vdot(v2, rl)))
        r = vunit(r)
        out.append((x1, tang[i + 1], r, vcross(tang[i + 1], r)))
    return out


# =============================================================================
# Extrude (2.5D): outline with holes -> closed solid mesh
# =============================================================================
def poly_area(poly):
    a = 0.0
    n = len(poly)
    for i in range(n):
        x0, y0 = poly[i][0], poly[i][1]
        x1, y1 = poly[(i + 1) % n][0], poly[(i + 1) % n][1]
        a += x0 * y1 - x1 * y0
    return 0.5 * a


def point_in_poly(x, y, poly):
    inside = False
    n = len(poly)
    j = n - 1
    for i in range(n):
        xi, yi = poly[i][0], poly[i][1]
        xj, yj = poly[j][0], poly[j][1]
        if (yi > y) != (yj > y):
            if x < xi + (y - yi) * (xj - xi) / (yj - yi):
                inside = not inside
        j = i
    return inside


def _seg_cross(p, q, a, b):
    """True if segment pq properly crosses segment ab (shared endpoints do not count)."""
    def orient2(o, s, t):
        return (s[0] - o[0]) * (t[1] - o[1]) - (s[1] - o[1]) * (t[0] - o[0])
    d1, d2 = orient2(a, b, p), orient2(a, b, q)
    d3, d4 = orient2(p, q, a), orient2(p, q, b)
    return (d1 * d2 < -1e-12) and (d3 * d4 < -1e-12)


def _bridge_holes(outer, holes):
    """Join holes into the outer loop with zero-width bridges -> one simple loop of
    (x, y, original index). Outer must be CCW, holes CW."""
    loop = [(p[0], p[1], i) for i, p in enumerate(outer)]
    base = len(outer)
    tagged = []
    for h in holes:
        tagged.append([(p[0], p[1], base + i) for i, p in enumerate(h)])
        base += len(h)
    tagged.sort(key=lambda h: -max(p[0] for p in h))      # rightmost holes first
    all_edges = []

    def edges_of(poly):
        return [(poly[i], poly[(i + 1) % len(poly)]) for i in range(len(poly))]
    for h in tagged:
        hi = max(range(len(h)), key=lambda i: h[i][0])
        hp = h[hi]
        segs = edges_of(loop) + [e for hh in tagged for e in edges_of(hh)]
        best, best_d = None, None
        for li, lp in enumerate(loop):
            d = (lp[0] - hp[0]) ** 2 + (lp[1] - hp[1]) ** 2
            if best_d is not None and d >= best_d:
                continue
            ok = True
            for a, b in segs:
                if a[2] in (lp[2], hp[2]) or b[2] in (lp[2], hp[2]):
                    continue
                if _seg_cross(hp, lp, a, b):
                    ok = False
                    break
            if ok:
                best, best_d = li, d
        if best is None:
            best = min(range(len(loop)), key=lambda i: (loop[i][0] - hp[0]) ** 2 + (loop[i][1] - hp[1]) ** 2)
        hole_seq = h[hi:] + h[:hi] + [h[hi]]
        loop = loop[:best + 1] + hole_seq + [loop[best]] + loop[best + 1:]
        all_edges = edges_of(loop)
    del all_edges
    return loop


def triangulate(outer, holes=()):
    """Ear clipping of a polygon with holes. Returns triangles as index triples into
    outer + holes (concatenated, in that order). Outer CCW, holes CW (fixed here)."""
    outer = list(outer)
    if poly_area(outer) < 0:
        raise ValueError("outer loop must be counter-clockwise")
    hs = []
    for h in holes:
        h = list(h)
        if poly_area(h) > 0:
            raise ValueError("holes must be clockwise")
        hs.append(h)
    loop = _bridge_holes(outer, hs) if hs else [(p[0], p[1], i) for i, p in enumerate(outer)]
    tris = []
    idx = list(range(len(loop)))

    def cross(o, a, b):
        return (a[0] - o[0]) * (b[1] - o[1]) - (a[1] - o[1]) * (b[0] - o[0])

    def inside_tri(p, a, b, c):
        return (cross(a, b, p) >= -1e-12 and cross(b, c, p) >= -1e-12 and cross(c, a, p) >= -1e-12)

    guard = 0
    while len(idx) > 3 and guard < 200000:
        guard += 1
        n = len(idx)
        # only reflex corners can lie inside an ear
        reflex = []
        for k in range(n):
            a, b, c = loop[idx[(k - 1) % n]], loop[idx[k]], loop[idx[(k + 1) % n]]
            if cross(a, b, c) <= 1e-12:
                reflex.append(idx[k])
        best = None
        for k in range(n):
            ia, ib, ic = idx[(k - 1) % n], idx[k], idx[(k + 1) % n]
            a, b, c = loop[ia], loop[ib], loop[ic]
            if a[2] == c[2] or a[2] == b[2] or b[2] == c[2]:
                continue
            if cross(a, b, c) <= 1e-12:
                continue                      # reflex or flat corner
            ear = True
            for m in reflex:
                q = loop[m]
                if q[2] in (a[2], b[2], c[2]):
                    continue
                if inside_tri(q, a, b, c):
                    ear = False
                    break
            if ear:
                qa = _min_angle(a, b, c)      # prefer well-shaped ears
                if best is None or qa > best[0]:
                    best = (qa, k)
                    if qa > 0.6:
                        break
        k = 0 if best is None else best[1]
        ia, ib, ic = idx[(k - 1) % n], idx[k], idx[(k + 1) % n]
        tri = (loop[ia][2], loop[ib][2], loop[ic][2])
        if len(set(tri)) == 3:
            tris.append(tri)
        idx.pop(k)
    if len(idx) == 3:
        tri = tuple(loop[i][2] for i in idx)
        if len(set(tri)) == 3:
            tris.append(tri)
    return tris


def _min_angle(a, b, c):
    def ang(p, q, r):
        u = (q[0] - p[0], q[1] - p[1])
        v = (r[0] - p[0], r[1] - p[1])
        nu = math.hypot(*u)
        nv = math.hypot(*v)
        if nu < EPS or nv < EPS:
            return 0.0
        return math.acos(max(-1.0, min(1.0, (u[0] * v[0] + u[1] * v[1]) / (nu * nv))))
    return min(ang(a, b, c), ang(b, c, a), ang(c, a, b))


def pair_triangles(tris, pts, min_angle_deg=35.0):
    """Merge neighbouring triangles into convex, well-shaped quads (greedy, longest
    shared edge first). Returns faces (quads and leftover triangles)."""
    from_edge = {}
    for ti, t in enumerate(tris):
        for i in range(3):
            a, b = t[i], t[(i + 1) % 3]
            from_edge.setdefault((min(a, b), max(a, b)), []).append(ti)
    cands = []
    for (a, b), ts in from_edge.items():
        if len(ts) != 2:
            continue
        L = math.hypot(pts[a][0] - pts[b][0], pts[a][1] - pts[b][1])
        cands.append((-L, a, b, ts[0], ts[1]))
    cands.sort()
    used = [False] * len(tris)
    faces = []
    lim = math.radians(min_angle_deg)
    for _negL, a, b, t1, t2 in cands:
        if used[t1] or used[t2]:
            continue
        T1, T2 = tris[t1], tris[t2]
        c = [v for v in T1 if v not in (a, b)][0]
        d = [v for v in T2 if v not in (a, b)][0]
        # T1 runs a->b or b->a; build the quad in T1's winding
        i = T1.index(a)
        if T1[(i + 1) % 3] == b:
            quad = (a, d, b, c)
        else:
            quad = (b, d, a, c)
        if _convex_good(quad, pts, lim):
            used[t1] = used[t2] = True
            faces.append(quad)
    faces.extend(tris[i] for i in range(len(tris)) if not used[i])
    return faces


def _convex_good(q, pts, lim):
    P = [pts[i] for i in q]
    sign = 0
    for i in range(4):
        a, b, c = P[i], P[(i + 1) % 4], P[(i + 2) % 4]
        cr = (b[0] - a[0]) * (c[1] - b[1]) - (b[1] - a[1]) * (c[0] - b[0])
        s = 1 if cr > 0 else -1
        if abs(cr) < 1e-12:
            return False
        if sign == 0:
            sign = s
        elif s != sign:
            return False
    for i in range(4):
        p, q0, r = P[i], P[(i + 1) % 4], P[(i - 1) % 4]
        u = (q0[0] - p[0], q0[1] - p[1])
        v = (r[0] - p[0], r[1] - p[1])
        nu, nv = math.hypot(*u), math.hypot(*v)
        if nu < EPS or nv < EPS:
            return False
        ang = math.acos(max(-1.0, min(1.0, (u[0] * v[0] + u[1] * v[1]) / (nu * nv))))
        if ang < lim or ang > math.pi - lim * 0.6:
            return False
    return True


def _seg_dist2(p, a, b):
    ax, ay = a[0], a[1]
    dx, dy = b[0] - ax, b[1] - ay
    L2 = dx * dx + dy * dy
    t = 0.0 if L2 < EPS else max(0.0, min(1.0, ((p[0] - ax) * dx + (p[1] - ay) * dy) / L2))
    qx, qy = ax + t * dx - p[0], ay + t * dy - p[1]
    return qx * qx + qy * qy


def fill_planar(outer, holes=(), edge=None, margin=0.6):
    """Quad-dominant fill of a planar polygon with holes, for clean caps.
    A regular grid of square cells (size `edge`) covers the inside, cells stay at
    least margin*edge from the outline; the band between grid and outline is
    triangulated and its triangles are paired into quads.
    Returns (points, faces): points start with outer + holes (same order as given),
    grid points follow; faces wind counter-clockwise (+Z normal)."""
    outer = [tuple(p[:2]) for p in outer]
    holes = [[tuple(p[:2]) for p in h] for h in holes]
    loops = [outer] + holes
    pts = [p for loop in loops for p in loop]
    if not edge:
        per = sum(math.hypot(outer[i][0] - outer[i - 1][0], outer[i][1] - outer[i - 1][1]) for i in range(len(outer)))
        edge = per / max(8, len(outer))
    segs = []
    for loop in loops:
        n = len(loop)
        segs.extend((loop[i], loop[(i + 1) % n]) for i in range(n))
    xs = [p[0] for p in outer]
    ys = [p[1] for p in outer]
    x0, y0 = min(xs), min(ys)
    nx = int(math.ceil((max(xs) - x0) / edge)) + 1
    ny = int(math.ceil((max(ys) - y0) / edge)) + 1
    # bucket the segments for fast distance queries
    bsz = edge * 2.0
    buckets = {}
    for a, b in segs:
        bx0, bx1 = int(math.floor(min(a[0], b[0]) / bsz)), int(math.floor(max(a[0], b[0]) / bsz))
        by0, by1 = int(math.floor(min(a[1], b[1]) / bsz)), int(math.floor(max(a[1], b[1]) / bsz))
        for bx in range(bx0, bx1 + 1):
            for by in range(by0, by1 + 1):
                buckets.setdefault((bx, by), []).append((a, b))
    lim2 = (margin * edge) ** 2
    ok_corner = {}

    def corner_ok(i, j):
        key = (i, j)
        if key in ok_corner:
            return ok_corner[key]
        p = (x0 + i * edge, y0 + j * edge)
        res = point_in_poly(p[0], p[1], outer) and not any(point_in_poly(p[0], p[1], h) for h in holes)
        if res:
            bx, by = int(math.floor(p[0] / bsz)), int(math.floor(p[1] / bsz))
            for ddx in (-1, 0, 1):
                for ddy in (-1, 0, 1):
                    for a, b in buckets.get((bx + ddx, by + ddy), ()):
                        if _seg_dist2(p, a, b) < lim2:
                            res = False
                            break
                    if not res:
                        break
                if not res:
                    break
        ok_corner[key] = res
        return res
    cells = set()
    for i in range(nx):
        for j in range(ny):
            if corner_ok(i, j) and corner_ok(i + 1, j) and corner_ok(i + 1, j + 1) and corner_ok(i, j + 1):
                cells.add((i, j))
    # remove diagonal pinches (two cells touching only at a corner)
    changed = True
    while changed:
        changed = False
        for (i, j) in list(cells):
            for di, dj in ((1, 1), (1, -1)):
                c2 = (i + di, j + dj)
                if c2 in cells and (i + di, j) not in cells and (i, j + dj) not in cells:
                    cells.discard(c2)
                    changed = True
    # lone cells are worse than a triangle band: drop cells with < 2 neighbours
    for _ in range(2):
        for c in list(cells):
            nb = sum(1 for d in ((1, 0), (-1, 0), (0, 1), (0, -1)) if (c[0] + d[0], c[1] + d[1]) in cells)
            if nb < 2:
                cells.discard(c)
    gid = {}

    def gv(i, j):
        if (i, j) not in gid:
            gid[(i, j)] = len(pts)
            pts.append((x0 + i * edge, y0 + j * edge))
        return gid[(i, j)]
    faces = []
    directed = {}
    for (i, j) in sorted(cells):
        q = (gv(i, j), gv(i + 1, j), gv(i + 1, j + 1), gv(i, j + 1))
        faces.append(q)
        for k in range(4):
            directed[(q[k], q[(k + 1) % 4])] = True
    bnd = dict((a, b) for (a, b) in directed if (b, a) not in directed)
    grid_loops = []
    seen = set()
    for a in list(bnd):
        if a in seen:
            continue
        loop = [a]
        seen.add(a)
        b = bnd[a]
        while b != a and b not in seen:
            loop.append(b)
            seen.add(b)
            b = bnd[b]
        if len(loop) >= 4:
            grid_loops.append(loop)
    # band regions: every loop (index lists) nested by containment, even depth = band outer
    all_loops = []
    base = 0
    for loop in loops:
        all_loops.append(list(range(base, base + len(loop))))
        base += len(loop)
    all_loops += grid_loops
    polys = [[pts[i] for i in l] for l in all_loops]
    areas = [abs(poly_area(p)) for p in polys]
    depth, parent = [0] * len(polys), [-1] * len(polys)
    for a in range(len(polys)):
        pa = polys[a]
        mx = ((pa[0][0] + pa[1][0]) * 0.5, (pa[0][1] + pa[1][1]) * 0.5)
        for b in range(len(polys)):
            if a != b and areas[b] > areas[a] and point_in_poly(mx[0], mx[1], polys[b]):
                depth[a] += 1
                if parent[a] < 0 or areas[b] < areas[parent[a]]:
                    parent[a] = b
    for a in range(len(polys)):
        if depth[a] % 2:
            continue
        o_idx = all_loops[a]
        o_pts = polys[a]
        if poly_area(o_pts) < 0:
            o_idx, o_pts = o_idx[::-1], o_pts[::-1]
        h_idx, h_pts = [], []
        for b in range(len(polys)):
            if parent[b] == a and depth[b] % 2:
                hi, hp = all_loops[b], polys[b]
                if poly_area(hp) > 0:
                    hi, hp = hi[::-1], hp[::-1]
                h_idx.append(hi)
                h_pts.append(hp)
        if a >= len(loops) and not h_idx and grid_loops and all_loops[a] in grid_loops:
            continue                                  # a grid region's own outline: already quads
        tris = triangulate(o_pts, h_pts)
        flat = list(o_idx) + [i for h in h_idx for i in h]
        band = [tuple(flat[k] for k in t) for t in tris]
        faces.extend(pair_triangles(band, pts))
    return pts, faces


def extrude(outer, holes=(), height=10.0, z0=0.0, layers=None, edge=None, quad_caps=True):
    """outer / holes: [(x, y)] closed loops (any winding). Walls are quad bands
    (layers along Z), caps are triangulated, then paired into quads."""
    outer = [tuple(p[:2]) for p in outer]
    if edge:                                   # even walls and caps: resample, corners kept
        outer = resample(outer, step=edge, closed=True)
    if poly_area(outer) < 0:
        outer = outer[::-1]
    hs = []
    for h in holes:
        h = [tuple(p[:2]) for p in h]
        if edge:
            h = resample(h, step=edge, closed=True)
        if poly_area(h) > 0:
            h = h[::-1]
        hs.append(h)
    if layers is None:
        layers = 1 if not edge else max(1, int(round(abs(height) / edge)))
    m = QMesh(name="extrude")
    loops = [outer] + hs
    if quad_caps:
        flat, cap_faces = fill_planar(outer, hs, edge)
    else:
        flat = [p for loop in loops for p in loop]
        cap_faces = triangulate(outer, hs)
    level_ids = []
    for li in range(layers + 1):
        z = z0 + height * li / layers
        pts_level = flat if li in (0, layers) else flat[:sum(len(l) for l in loops)]
        level_ids.append([m.add_vert((p[0], p[1], z)) for p in pts_level])
    start = 0
    for loop in loops:
        n = len(loop)
        for li in range(layers):
            lo, hi = level_ids[li], level_ids[li + 1]
            for j in range(n):
                a, b = start + j, start + (j + 1) % n
                m.f.append((lo[a], lo[b], hi[b], hi[a]))
        start += n
    bot, top = level_ids[0], level_ids[-1]
    for face in cap_faces:
        m.f.append(tuple(bot[i] for i in reversed(face)))
        m.f.append(tuple(top[i] for i in face))
    orient(m)
    return m


# =============================================================================
# Catmull-Clark subdivision (all-quad output, closed meshes)
# =============================================================================
def catmull_clark(mesh, levels=1):
    for _ in range(max(0, int(levels))):
        mesh = _cc_once(mesh)
    return mesh


def _cc_once(m):
    V, F = m.v, m.f
    nv = len(V)
    face_pts = [vmul(reduce_add([V[i] for i in f]), 1.0 / len(f)) for f in F]
    ef = edge_faces(m)
    edge_index = {}
    newv = list(V)                                   # placeholders for moved originals
    for key, fs in ef.items():
        a, b = key
        mid = vmul(vadd(V[a], V[b]), 0.5)
        if len(fs) == 2:
            p = vmul(vadd(vadd(V[a], V[b]), vadd(face_pts[fs[0]], face_pts[fs[1]])), 0.25)
        else:
            p = mid                                  # boundary / non-manifold: keep midpoint
        edge_index[key] = len(newv)
        newv.append(p)
    fp_index = []
    for p in face_pts:
        fp_index.append(len(newv))
        newv.append(p)
    # move original vertices
    v_faces = [[] for _ in range(nv)]
    v_edges = [[] for _ in range(nv)]
    for fi, f in enumerate(F):
        for i in f:
            v_faces[i].append(fi)
    for key in ef:
        v_edges[key[0]].append(key)
        v_edges[key[1]].append(key)
    for i in range(nv):
        n = len(v_faces[i])
        if n == 0:
            continue
        if any(len(ef[e]) != 2 for e in v_edges[i]):
            continue                                 # boundary vertex: keep
        Fa = vmul(reduce_add([face_pts[fi] for fi in v_faces[i]]), 1.0 / n)
        R = vmul(reduce_add([vmul(vadd(V[e[0]], V[e[1]]), 0.5) for e in v_edges[i]]), 1.0 / len(v_edges[i]))
        k = len(v_edges[i])
        newv[i] = vmul(vadd(vadd(Fa, vmul(R, 2.0)), vmul(V[i], k - 3.0)), 1.0 / k)
    newf = []
    for fi, f in enumerate(F):
        n = len(f)
        for j in range(n):
            a, b, c = f[(j - 1) % n], f[j], f[(j + 1) % n]
            e_prev = edge_index[(min(a, b), max(a, b))]
            e_next = edge_index[(min(b, c), max(b, c))]
            newf.append((b, e_next, fp_index[fi], e_prev))
    out = QMesh(newv, newf, m.name)
    return out


# =============================================================================
# Checks
# =============================================================================
def check(mesh):
    """Topology and quality numbers. closed + manifold + oriented + one shell per
    part is what CNC / SubD / NURBS conversion need."""
    ef = edge_faces(mesh)
    directed = {}
    for face in mesh.f:
        n = len(face)
        for i in range(n):
            e = (face[i], face[(i + 1) % n])
            directed[e] = directed.get(e, 0) + 1
    open_e = sum(1 for fs in ef.values() if len(fs) == 1)
    nonman = sum(1 for fs in ef.values() if len(fs) > 2)
    flipped = sum(1 for e, c in directed.items() if c > 1)
    quads = sum(1 for f in mesh.f if len(f) == 4)
    tris = sum(1 for f in mesh.f if len(f) == 3)
    shells = _shells(mesh, ef)
    V, E, Fc = len(mesh.v), len(ef), len(mesh.f)
    used = set(i for f in mesh.f for i in f)
    vol = area = 0.0
    lens = []
    worst_aspect = 1.0
    for face in mesh.f:
        P = [mesh.v[i] for i in face]
        for tri in _tris(tuple(range(len(face)))):
            a, b, c = (P[i] for i in tri)
            vol += vdot(a, vcross(b, c)) / 6.0
            area += 0.5 * vlen(vcross(vsub(b, a), vsub(c, a)))
        el = [vlen(vsub(P[(i + 1) % len(P)], P[i])) for i in range(len(P))]
        lens.extend(el)
        if min(el) > EPS:
            worst_aspect = max(worst_aspect, max(el) / min(el))
    mean = sum(lens) / max(1, len(lens))
    var = sum((x - mean) ** 2 for x in lens) / max(1, len(lens))
    bb = mesh.bbox() if mesh.v else (0, 0, 0, 0, 0, 0)
    chi = len(used) - E + Fc
    return {
        "vertices": len(used), "faces": Fc, "quads": quads, "triangles": tris,
        "quad_pct": round(100.0 * quads / max(1, Fc), 2),
        "closed": open_e == 0, "open_edges": open_e, "nonmanifold_edges": nonman,
        "oriented": flipped == 0, "shells": len(shells), "euler": chi,
        "genus": (2 * len(shells) - chi) // 2 if open_e == 0 else None,
        "volume": vol, "area": area,
        "edge_mean": mean, "edge_cv": (math.sqrt(var) / mean) if mean > EPS else 0.0,
        "worst_face_aspect": worst_aspect,
        "size": (bb[3] - bb[0], bb[4] - bb[1], bb[5] - bb[2]),
        "unused_vertices": V - len(used),
    }


def _shells(mesh, ef):
    parent = list(range(len(mesh.f)))

    def find(i):
        while parent[i] != i:
            parent[i] = parent[parent[i]]
            i = parent[i]
        return i
    for fs in ef.values():
        for k in range(1, len(fs)):
            a, b = find(fs[0]), find(fs[k])
            if a != b:
                parent[a] = b
    groups = {}
    for i in range(len(mesh.f)):
        groups.setdefault(find(i), []).append(i)
    return list(groups.values())


def compact(mesh):
    """Drop unused vertices."""
    used = sorted(set(i for f in mesh.f for i in f))
    remap = dict((old, new) for new, old in enumerate(used))
    mesh.v = [mesh.v[i] for i in used]
    mesh.f = [tuple(remap[i] for i in f) for f in mesh.f]
    return mesh


# =============================================================================
# Export (pure Python)
# =============================================================================
def write_obj(parts, path, header="Styro3D qmesh, units mm"):
    """parts: QMesh or [(name, QMesh)]. Quads stay quads (Rhino / Blender read them)."""
    if isinstance(parts, QMesh):
        parts = [(parts.name or "part", parts)]
    with open(path, "w") as fh:
        fh.write("# %s\n" % header)
        off = 1
        for name, m in parts:
            fh.write("o %s\n" % (name or "part"))
            for p in m.v:
                fh.write("v %.6f %.6f %.6f\n" % p)
            for f in m.f:
                fh.write("f " + " ".join(str(i + off) for i in f) + "\n")
            off += len(m.v)


def write_stl(parts, path, header="Styro3D qmesh, units mm"):
    """Binary STL; quads split along their shorter diagonal."""
    if isinstance(parts, QMesh):
        parts = [(parts.name, parts)]
    tris = []
    for _name, m in parts:
        for f in m.f:
            if len(f) == 4:
                a, b, c, d = (m.v[i] for i in f)
                if vlen(vsub(c, a)) <= vlen(vsub(d, b)):
                    tris += [(a, b, c), (a, c, d)]
                else:
                    tris += [(a, b, d), (b, c, d)]
            else:
                P = [m.v[i] for i in f]
                tris += [(P[0], P[i], P[i + 1]) for i in range(1, len(P) - 1)]
    with open(path, "wb") as fh:
        hb = header.encode("ascii", "replace") if not isinstance(header, bytes) else header
        fh.write(struct.pack("<80s", hb[:80]))
        fh.write(struct.pack("<I", len(tris)))
        for a, b, c in tris:
            n = vunit(vcross(vsub(b, a), vsub(c, a)))
            fh.write(struct.pack("<12fH", n[0], n[1], n[2], a[0], a[1], a[2], b[0], b[1], b[2],
                                 c[0], c[1], c[2], 0))
    return len(tris)


# =============================================================================
# Recipes: JSON -> parts
# =============================================================================
def _vec(v, default=(0.0, 0.0, 0.0)):
    if v is None:
        return default
    return (float(v[0]), float(v[1]), float(v[2]))


def _profile2d(spec):
    """Profile spec -> list of (x, y): explicit points, or a shape."""
    if isinstance(spec, list):
        return [(float(p[0]), float(p[1])) for p in spec]
    kind = spec.get("shape", "points")
    n = _mult4(spec.get("segments", 32))
    if kind == "circle":
        r = float(spec["r"])
        return [(x, y) for x, y, _z in ring_points(n, r, r)]
    if kind in ("ellipse", "superellipse"):
        return [(x, y) for x, y, _z in ring_points(n, float(spec["rx"]), float(spec["ry"]),
                                                   expo=float(spec.get("n", 2.0)))]
    if kind == "rect":
        w, h = float(spec["w"]) / 2, float(spec["h"]) / 2
        return [(x, y) for x, y, _z in ring_points(n, w, h, expo=float(spec.get("n", 12.0)))]
    return [(float(p[0]), float(p[1])) for p in spec["points"]]


def build_part(spec, parts_by_name=None):
    op = spec.get("op")
    if op == "box":
        m = box(spec["size"], spec.get("segments", (2, 2, 2)), _vec(spec.get("at")))
    elif op == "sphere":
        m = sphere(float(spec["r"]), int(spec.get("segments", 8)), _vec(spec.get("at")))
    elif op == "cylinder":
        m = cylinder(float(spec.get("r", 0)), float(spec["h"]), int(spec.get("segments", 32)),
                     int(spec.get("rings", 1)), _vec(spec.get("at")), spec.get("rx"), spec.get("ry"),
                     float(spec.get("n", 2.0)))
    elif op == "cone":
        m = cone(float(spec["r1"]), float(spec["r2"]), float(spec["h"]), int(spec.get("segments", 32)),
                 int(spec.get("rings", 1)), _vec(spec.get("at")))
    elif op == "torus":
        m = torus(float(spec["R"]), float(spec["r"]), int(spec.get("segments", 48)),
                  int(spec.get("tube_segments", 16)), _vec(spec.get("at")))
    elif op == "revolve":
        m = revolve(spec["profile"], int(spec.get("segments", 48)))
    elif op == "loft":
        secs = []
        for s in spec["sections"]:
            if "points" in s:
                z = float(s.get("z", 0.0))
                secs.append([(float(p[0]), float(p[1]), float(p[2]) if len(p) > 2 else z) for p in s["points"]])
            else:
                secs.append(ring_points(_mult4(spec.get("segments", 32)), float(s["rx"]), float(s["ry"]),
                                        float(s["z"]), float(s.get("cx", 0.0)), float(s.get("cy", 0.0)),
                                        float(s.get("n", 2.0))))
        m = loft(secs, spec.get("cap_start", "quad"), spec.get("cap_end", "quad"),
                 float(spec.get("dome_start", 0.0)), float(spec.get("dome_end", 0.0)))
    elif op == "extrude":
        m = extrude(spec["outer"], spec.get("holes", ()), float(spec.get("height", 10.0)),
                    float(spec.get("z0", 0.0)), spec.get("layers"), spec.get("edge"),
                    bool(spec.get("quad_caps", True)))
        plane = spec.get("plane", "XY").upper()
        if plane == "XZ":           # outline drawn in a front view: x right, y up -> X, Z; depth along +Y
            m.apply(lambda p: (p[0], p[2], p[1]))
            m.flip()
        elif plane == "YZ":
            m.apply(lambda p: (p[2], p[0], p[1]))
    elif op == "sweep":
        m = sweep(_profile2d(spec["profile"]), [_vec(p) for p in spec["path"]],
                  bool(spec.get("closed", False)), spec.get("cap", "quad"),
                  float(spec.get("twist", 0.0)), float(spec.get("scale_end", 1.0)))
    elif op == "mesh":
        m = QMesh([_vec(p) for p in spec["vertices"]], [tuple(f) for f in spec["faces"]])
        orient(m)
    elif op == "copy":
        m = parts_by_name[spec["of"]].copy()
    else:
        raise ValueError("unknown op: %r" % op)
    if spec.get("subdivide"):
        m = catmull_clark(m, int(spec["subdivide"]))
    if spec.get("scale") is not None:
        m.scale(spec["scale"], _vec(spec.get("scale_centre")))
    rots = spec.get("rotate") or []
    if isinstance(rots, dict):
        rots = [rots]
    for rot in rots:                       # {"axis": [0, 0, 1], "deg": 30, "centre": [..]}
        m.rotate(_vec(rot.get("axis"), (0.0, 0.0, 1.0)), float(rot["deg"]), _vec(rot.get("centre")))
    if spec.get("move"):
        m.move(_vec(spec["move"]))
    m.name = spec.get("name", op)
    return m


def build_recipe(recipe):
    """recipe dict (or JSON text) -> [(name, QMesh)]. A part with "mirror": "X" also
    gets its mirrored copy (name + "_mirror")."""
    if not isinstance(recipe, dict):
        recipe = json.loads(recipe)
    out = []
    by_name = {}
    for i, spec in enumerate(recipe.get("parts", [])):
        if spec.get("skip"):
            continue
        m = build_part(spec, by_name)
        name = spec.get("name", "%s_%02d" % (spec.get("op"), i + 1))
        m.name = name
        by_name[name] = m
        out.append((name, m))
        if spec.get("mirror"):
            mm = m.copy(name + "_mirror").mirror(spec["mirror"])
            by_name[mm.name] = mm
            out.append((mm.name, mm))
    return out
