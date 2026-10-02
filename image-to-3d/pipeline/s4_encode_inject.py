"""Encode the final radius grid, inject it into the Rhino script, then verify by decoding with the script's own code."""
import json, base64, struct, zlib, time, sys, types, importlib.util, re
import numpy as np
from scipy import ndimage as ndi
from unittest import mock
SCRIPT = sys.argv[1] if len(sys.argv) > 1 else "../styro3d_ai_to_cnc.py"
R = np.load("out/mesh_final_R.npy").astype(np.float64); P = json.load(open("out/mesh_final_params.json"))
ref = np.load("out/mesh_final.npz")
def load_script():
    for name in ("Rhino", "Rhino.Geometry", "Rhino.Geometry.Intersect", "rhinoscriptsyntax", "scriptcontext", "System",
                 "System.Collections", "System.Collections.Generic", "System.Drawing"):
        sys.modules.pop(name, None)
    def stub(name, **kw):
        m = types.ModuleType(name); m.__dict__.update(kw); sys.modules[name] = m; return m
    rh = stub("Rhino"); rh.RhinoApp = mock.MagicMock(ExeVersion=7)
    g = stub("Rhino.Geometry"); rh.Geometry = g; stub("Rhino.Geometry.Intersect", Intersection=mock.MagicMock())
    stub("rhinoscriptsyntax"); stub("scriptcontext"); stub("System"); stub("System.Collections")
    stub("System.Collections.Generic", List=mock.MagicMock()); stub("System.Drawing", Color=mock.MagicMock())
    spec = importlib.util.spec_from_file_location("s3d", SCRIPT); mod = importlib.util.module_from_spec(spec); spec.loader.exec_module(mod)
    return mod
s3d = load_script()
nr, nu = R.shape; STEP, LQ, DMAX = 4, 0.004, 12.0
Rf = ndi.gaussian_filter(R, (1.0, 1.0), mode=("nearest", "wrap"))
low = Rf[::STEP, ::STEP]; nlr, nlu = low.shape
lowq = np.round(low / LQ).astype(np.uint16)
t0 = time.time(); up = np.array(s3d._upsample((lowq.astype(np.float64) * LQ).ravel().tolist(), nlr, nlu, STEP, nr, nu)).reshape(nr, nu)
D = R - up
q = np.round(np.sign(D) * np.sqrt(np.minimum(np.abs(D), DMAX) / DMAX) * 127).astype(np.int8)
Vref = ref["V"]
hdr = dict(P); hdr.update(nr=nr, nu=nu, step=STEP, nlr=nlr, nlu=nlu, LQ=LQ, DMAX=DMAX,
                          native_height=float(Vref[:, 2].max()), base_centre=[float(Vref[0, 0]), float(Vref[0, 1])],
                          version="bust-1", note="radius map measured from the user's photo (Styro3D), mm, life size")
hj = json.dumps(hdr, separators=(",", ":")).encode("ascii")
zl = zlib.compress(lowq.astype("<u2").tobytes(), 9); zd = zlib.compress(q.tobytes(), 9)
blob = struct.pack("<I", len(hj)) + hj + struct.pack("<I", len(zl)) + zl + zd
b64 = base64.b64encode(blob).decode("ascii")
lines = "\n".join(b64[i:i + 100] for i in range(0, len(b64), 100))
src = open(SCRIPT).read()
src = re.sub(r'BUST_DATA = """\n.*?"""', lambda m: 'BUST_DATA = """\n' + lines + '\n"""', src, count=1, flags=re.S)
open(SCRIPT, "w").write(src)
print("injected: %d KB base64 (%d lines); header %d B, low %d KB, detail %d KB" % (len(b64) // 1024, lines.count("\n") + 1, len(hj), len(zl) // 1024, len(zd) // 1024))
# ---- verify with the script's own decoder and grid builder
s3d = load_script()
t0 = time.time(); h2, rad = s3d.bust_decode(); t_dec = time.time() - t0
t0 = time.time(); verts, quads, tris = s3d.bust_grid(h2, rad, 1); t_grid = time.time() - t0
V = np.array(verts)
err = np.linalg.norm(V - Vref, axis=1)
print("decode %.1fs grid %.1fs | verts %d (ref %d) quads %d tris %d | position error mm: p50 %.4f p99 %.4f max %.3f" % (
      t_dec, t_grid, len(V), len(Vref), len(quads), len(tris), np.median(err), np.percentile(err, 99), err.max()))
assert len(V) == len(Vref) and np.array_equal(np.array(quads), ref["quads"]) and np.array_equal(np.array(tris), ref["tris"])
np.savez("out/mesh_decoded.npz", V=V, quads=np.array(quads), tris=np.array(tris))
for every in (2, 4):
    v2, q2, t2 = s3d.bust_grid(h2, rad, every); print("every=%d: %d verts %d quads %d tris" % (every, len(v2), len(q2), len(t2)))
    if every == 2: np.savez("out/mesh_decoded_half.npz", V=np.array(v2), quads=np.array(q2), tris=np.array(t2))
