"""Cycles render of the bust mesh (npz: V mm, quads, tris). usage: python render_bust.py mesh.npz out_prefix views res samples"""
import sys, math, numpy as np, bpy, mathutils
mesh_path, prefix = sys.argv[1], sys.argv[2]
views = sys.argv[3].split(",") if len(sys.argv) > 3 else ["photo"]
RES = int(sys.argv[4]) if len(sys.argv) > 4 else 900
SPP = int(sys.argv[5]) if len(sys.argv) > 5 else 64
d = np.load(mesh_path)
V = d["V"].astype(np.float64) * 0.001          # mm -> m
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
# orientation check: make normals outward
bpy.context.view_layer.objects.active = ob; ob.select_set(True)
bpy.ops.object.mode_set(mode="EDIT"); bpy.ops.mesh.select_all(action="SELECT"); bpy.ops.mesh.normals_make_consistent(inside=False); bpy.ops.object.mode_set(mode="OBJECT")
# ---- marble material
mat = bpy.data.materials.new("marble"); mat.use_nodes = True
nt_ = mat.node_tree; bsdf = nt_.nodes["Principled BSDF"]
bsdf.inputs["Base Color"].default_value = (0.66, 0.60, 0.52, 1)
bsdf.inputs["Roughness"].default_value = 0.42
for name, val in (("Subsurface Weight", 0.30), ("Subsurface Scale", 0.004)):
    if name in bsdf.inputs: bsdf.inputs[name].default_value = val
if "Subsurface Radius" in bsdf.inputs: bsdf.inputs["Subsurface Radius"].default_value = (1.0, 0.78, 0.55)
# subtle veining
tex = nt_.nodes.new("ShaderNodeTexNoise"); tex.inputs["Scale"].default_value = 18.0; tex.inputs["Detail"].default_value = 8.0
ramp = nt_.nodes.new("ShaderNodeValToRGB"); ramp.color_ramp.elements[0].position = 0.45; ramp.color_ramp.elements[1].position = 0.75
ramp.color_ramp.elements[0].color = (0.60, 0.54, 0.46, 1); ramp.color_ramp.elements[1].color = (0.70, 0.65, 0.57, 1)
nt_.links.new(tex.outputs["Fac"], ramp.inputs["Fac"]); nt_.links.new(ramp.outputs["Color"], bsdf.inputs["Base Color"])
ob.data.materials.append(mat)
# ---- world + lights (key upper-left-front like the photo, fill right, rim back)
world = bpy.data.worlds.new("w"); scene.world = world; world.use_nodes = True
world.node_tree.nodes["Background"].inputs["Color"].default_value = (0.0, 0.0, 0.0, 1); world.node_tree.nodes["Background"].inputs["Strength"].default_value = 0.0
bb_min, bb_max = V.min(0), V.max(0); ctr = 0.5 * (bb_min + bb_max); size = (bb_max - bb_min).max()
head = np.array([ctr[0], ctr[1], bb_min[2] + 0.62 * (bb_max[2] - bb_min[2])])
def area(name, direction, dist, power, sz, color=(1, 1, 1)):
    L = bpy.data.lights.new(name, "AREA"); L.energy = power; L.size = sz; L.color = color
    o = bpy.data.objects.new(name, L); scene.collection.objects.link(o)
    dv = np.array(direction, float); dv /= np.linalg.norm(dv)
    o.location = mathutils.Vector(head + dv * dist)
    o.rotation_euler = (mathutils.Vector(head) - o.location).to_track_quat("-Z", "Y").to_euler()
    return o
area("key", (-0.65, -0.54, 0.54), 1.2, 52.0, 0.9)
area("fill", (0.75, -0.55, 0.10), 1.4, 9.0, 1.2, (0.95, 0.97, 1.0))
area("rim", (0.35, 0.85, 0.40), 1.2, 22.0, 0.6)
area("top", (0.0, -0.1, 1.0), 1.4, 5.0, 1.0)
# ---- camera
cam_data = bpy.data.cameras.new("cam"); cam = bpy.data.objects.new("cam", cam_data); scene.collection.objects.link(cam); scene.camera = cam
cam_data.lens = 100.0; cam_data.sensor_width = 36.0
scene.render.engine = "CYCLES"; scene.cycles.device = "CPU"; scene.cycles.samples = SPP
try:
    scene.cycles.use_denoising = True; scene.cycles.denoiser = "OPENIMAGEDENOISE"
except Exception: pass
scene.render.resolution_x = RES; scene.render.resolution_y = RES
scene.view_settings.view_transform = "AgX"; scene.view_settings.look = "AgX - Medium High Contrast" if "AgX - Medium High Contrast" in [l.identifier for l in bpy.types.ColorManagedViewSettings.bl_rna.properties["look"].enum_items] else "None"
scene.render.film_transparent = False
VIEWS = {"photo": (0.0, -1.0, 0.03), "face": (math.sin(math.radians(22)), -math.cos(math.radians(22)), 0.05),
         "q3": (-0.62, -0.78, 0.10), "left": (-1.0, -0.05, 0.05), "right": (1.0, -0.05, 0.05), "back": (0.45, 0.9, 0.1), "top": (0.25, -0.6, 0.75)}
for v in views:
    dv = np.array(VIEWS[v], float); dv /= np.linalg.norm(dv)
    target = ctr.copy(); target[2] = bb_min[2] + 0.50 * (bb_max[2] - bb_min[2])
    dist = size * 3.15
    cam.location = mathutils.Vector(target + dv * dist)
    cam.rotation_euler = (mathutils.Vector(target) - cam.location).to_track_quat("-Z", "Y").to_euler()
    scene.render.filepath = "%s_%s.png" % (prefix, v)
    bpy.ops.render.render(write_still=True)
    print("rendered", scene.render.filepath, flush=True)
