"""Cycles render of the bust mesh with camera-relative lighting. usage: python mv_render.py mesh.npz out_prefix views res spp [ortho]"""
import sys, math, numpy as np, bpy, mathutils
mesh_path, prefix = sys.argv[1], sys.argv[2]
views = sys.argv[3].split(",")
RES = int(sys.argv[4]); SPP = int(sys.argv[5]); ORTHO = len(sys.argv) > 6 and sys.argv[6] == "ortho"
d = np.load(mesh_path)
V = d["V"].astype(np.float64) * 0.001
quads = d["quads"].astype(np.int64); tris = d["tris"].astype(np.int64)
bpy.ops.wm.read_factory_settings(use_empty=True)
scene = bpy.context.scene
me = bpy.data.meshes.new("bust")
nq, nt = len(quads), len(tris)
loops = np.concatenate([quads.ravel(), tris.ravel()])
loop_start = np.concatenate([np.arange(nq) * 4, nq * 4 + np.arange(nt) * 3])
loop_total = np.concatenate([np.full(nq, 4), np.full(nt, 3)])
me.vertices.add(len(V)); me.vertices.foreach_set("co", V.ravel())
me.loops.add(len(loops)); me.loops.foreach_set("vertex_index", loops)
me.polygons.add(nq + nt); me.polygons.foreach_set("loop_start", loop_start); me.polygons.foreach_set("loop_total", loop_total)
me.update(calc_edges=True); me.validate(verbose=False)
me.polygons.foreach_set("use_smooth", np.ones(nq + nt, bool))
ob = bpy.data.objects.new("bust", me); scene.collection.objects.link(ob)
bpy.context.view_layer.objects.active = ob; ob.select_set(True)
bpy.ops.object.mode_set(mode="EDIT"); bpy.ops.mesh.select_all(action="SELECT"); bpy.ops.mesh.normals_make_consistent(inside=False); bpy.ops.object.mode_set(mode="OBJECT")
mat = bpy.data.materials.new("marble"); mat.use_nodes = True
nt_ = mat.node_tree; bsdf = nt_.nodes["Principled BSDF"]
bsdf.inputs["Roughness"].default_value = 0.45
for name, val in (("Subsurface Weight", 0.25), ("Subsurface Scale", 0.003)):
    if name in bsdf.inputs: bsdf.inputs[name].default_value = val
if "Subsurface Radius" in bsdf.inputs: bsdf.inputs["Subsurface Radius"].default_value = (1.0, 0.78, 0.55)
tex = nt_.nodes.new("ShaderNodeTexNoise"); tex.inputs["Scale"].default_value = 18.0; tex.inputs["Detail"].default_value = 8.0
ramp = nt_.nodes.new("ShaderNodeValToRGB"); ramp.color_ramp.elements[0].position = 0.45; ramp.color_ramp.elements[1].position = 0.75
ramp.color_ramp.elements[0].color = (0.62, 0.56, 0.48, 1); ramp.color_ramp.elements[1].color = (0.72, 0.67, 0.59, 1)
nt_.links.new(tex.outputs["Fac"], ramp.inputs["Fac"]); nt_.links.new(ramp.outputs["Color"], bsdf.inputs["Base Color"])
ob.data.materials.append(mat)
world = bpy.data.worlds.new("w"); scene.world = world; world.use_nodes = True
world.node_tree.nodes["Background"].inputs["Color"].default_value = (0.02, 0.02, 0.02, 1); world.node_tree.nodes["Background"].inputs["Strength"].default_value = 1.0
bb_min, bb_max = V.min(0), V.max(0); ctr = 0.5 * (bb_min + bb_max); size = (bb_max - bb_min).max()
cam_data = bpy.data.cameras.new("cam"); cam = bpy.data.objects.new("cam", cam_data); scene.collection.objects.link(cam); scene.camera = cam
if ORTHO: cam_data.type = "ORTHO"; cam_data.ortho_scale = size * 1.12
else: cam_data.lens = 100.0; cam_data.sensor_width = 36.0
scene.render.engine = "CYCLES"; scene.cycles.device = "CPU"; scene.cycles.samples = SPP
try:
    scene.cycles.use_denoising = True; scene.cycles.denoiser = "OPENIMAGEDENOISE"
except Exception: pass
scene.render.resolution_x = RES; scene.render.resolution_y = RES
scene.view_settings.view_transform = "AgX"
looks = [l.identifier for l in bpy.types.ColorManagedViewSettings.bl_rna.properties["look"].enum_items]
scene.view_settings.look = "AgX - Medium High Contrast" if "AgX - Medium High Contrast" in looks else "None"
lights = []
def area(name, power, sz, color=(1, 1, 1)):
    L = bpy.data.lights.new(name, "AREA"); L.energy = power; L.size = sz; L.color = color
    o = bpy.data.objects.new(name, L); scene.collection.objects.link(o); return o
key = area("key", 60.0, 0.9); fill = area("fill", 12.0, 1.4, (0.95, 0.97, 1.0)); rim = area("rim", 26.0, 0.6); top = area("top", 8.0, 1.0)
VIEWS = {"front": (0.0, -1.0, 0.0), "right": (-1.0, 0.0, 0.0), "back": (0.0, 1.0, 0.0), "left": (1.0, 0.0, 0.0),
         "q3": (-0.62, -0.78, 0.10), "q3l": (0.62, -0.78, 0.10), "q3b": (-0.6, 0.75, 0.15), "top": (0.25, -0.6, 0.75)}
head = np.array([ctr[0], ctr[1], bb_min[2] + 0.62 * (bb_max[2] - bb_min[2])])
import json, os
FR = json.load(open(os.path.join(os.path.dirname(mesh_path), "frame.json"))) if os.path.exists(os.path.join(os.path.dirname(mesh_path), "frame.json")) else None
MATCH = {"mfront": "front", "mright": "right", "mback": "back", "mleft": "left"}
for v in views:
    dv = np.array(VIEWS[MATCH.get(v, v)], float); dv /= np.linalg.norm(dv)
    target = ctr.copy(); target[2] = bb_min[2] + 0.50 * (bb_max[2] - bb_min[2])
    if v in MATCH:            # exact framing of the aligned input views (780 x 480 px at S mm/px)
        Sm = FR["S"] * 0.001
        target = np.array([-FR["BX"] * 0.001, -FR["BY"] * 0.001, (474.0 - 240.0) * Sm])
        cam_data.type = "ORTHO"; cam_data.ortho_scale = 780 * Sm
        scene.render.resolution_x = 1560; scene.render.resolution_y = 960
    else:
        scene.render.resolution_x = RES; scene.render.resolution_y = RES
        if ORTHO: cam_data.type = "ORTHO"; cam_data.ortho_scale = size * 1.12
        else: cam_data.type = "PERSP"
    cam.location = mathutils.Vector(target + dv * size * 3.15)
    cam.rotation_euler = (mathutils.Vector(target) - cam.location).to_track_quat("-Z", "Y").to_euler()
    # camera frame: right = forward x up
    fwd = -dv; upw = np.array([0, 0, 1.0]); right = np.cross(fwd, upw); right /= max(np.linalg.norm(right), 1e-6)
    for o, (a, b, c), dist in ((key, (-0.65, 0.55, 0.55), 1.2), (fill, (0.8, 0.05, 0.6), 1.4), (rim, (0.3, 0.45, -0.85), 1.2), (top, (0.0, 1.0, 0.1), 1.4)):
        # a: along camera right, b: up, c: toward camera (negative = behind the subject)
        dd = a * right + b * upw + c * dv; dd /= np.linalg.norm(dd)
        o.location = mathutils.Vector(head + dd * dist)
        o.rotation_euler = (mathutils.Vector(head) - o.location).to_track_quat("-Z", "Y").to_euler()
    scene.render.filepath = "%s_%s.png" % (prefix, v)
    bpy.ops.render.render(write_still=True)
    print("rendered", scene.render.filepath, flush=True)
