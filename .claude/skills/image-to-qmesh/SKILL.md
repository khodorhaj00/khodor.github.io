---
name: image-to-qmesh
description: Turn one photo, a views sheet (2/4/8 views) or a photo + real dimensions into CLEAN, CLOSED quad meshes in mm (OBJ with quads, STL) for CNC / foam, and into Rhino SubD or NURBS polysurfaces. Use for image-to-3D of signs, letters, logos, turned parts (vases, columns), busts, figures, animals, products and hard-surface parts, when topology must be clean (even quads, edge loops, watertight) and not a triangle soup.
license: MIT
---

# Image -> clean closed quad mesh (Styro3D qmesh)

Everything lives in `image-to-3d/qmesh/` of this repo:

| File | Role |
|---|---|
| `s3d_qmesh.py` | The kernel. Pure Python (2.7 and 3), no dependencies. The same file runs in the cloud and inside Rhino. |
| `qmesh_image.py` | Image + real size -> recipe. Three routes: `sign`, `revolve`, `views`. |
| `qmesh_build.py` | Recipe -> OBJ (quads), STL, report, 6-view preview. |
| `s3d_qmesh_rhino.py` | Rhino 7/8: the same recipe built natively. Optional SubD and NURBS polysurface output. |
| `RECIPE.md` | Every op, with its fields. |
| `examples/*.json` | Example recipes, both auto-generated and hand-written. |

Cloud setup, once per session: `pip install numpy scipy opencv-python-headless scikit-image`. The kernel itself needs nothing.

## Hard rules

1. **Real units.** Every recipe is in millimetres. Ask for one real dimension, the height or the width, if the user gave none.
2. **Closed and clean or it does not ship.** Every part must pass the gate in `qmesh_build.py`:
   - closed, manifold, consistently oriented;
   - one shell per part, volume > 0, no unused vertices.

   Report quads %, edge CV (evenness) and the worst face aspect.
3. **Build with structure, not booleans.** Shapes come from rings and grids:
   - box, sphere (quad sphere, no poles), cylinder, cone, torus;
   - revolve, loft, sweep, extrude.

   Parts that touch stay **separate closed shells**: an assembly. Mesh booleans would destroy the topology. Overlapping closed shells are fine for 3-axis CAM. To get one shell, use Rhino `BooleanUnion` on the SubD/NURBS versions.
4. **Even quads.** Profiles and paths are resampled to the target edge length, keeping corners. Rings are spaced by distance along the surface, not by height. Quad caps are Coons grids. Ring sizes are multiples of 4.
5. **Measure, don't guess.** After every build, look at the 6-view sheet beside the reference images. Check size against the given dimensions. For the views route, read the outline IoU per view from the hull log. State what the images cannot show, such as the back or hidden hollows.

## Workflow (staged; each pass ends with a build + review)

0. **Intake.** Gather the images, at least one real dimension, and the use (CNC foam, wood, print, render). Pick the route by the shape:
   - **flat outline** (letters, logo, sign, relief, cut-out) -> `sign` (extrude, thickness in mm);
   - **turned** (vase, column, baluster, bottle, lamp base) -> `revolve` (front view);
   - **any solid with several views** (bust, figure, animal, product) -> `views`. This builds a visual hull from 2/4/8 views, then ring sections and quad lofts. A tracker splits branches such as arms and legs into separate lofts.
   - **hard-surface assembly** (furniture, machines, props) -> write the recipe by hand from the photo and dimensions, like `examples/bench.json`.
   - **mixed** -> combine: auto-route parts plus hand-written parts in one recipe.
1. **Detail inventory.** Before building, list the features that make the object recognisable, each with its size in mm (image px × mm_per_px). Every feature must map to a part or to a section of a part. Drop what cannot be placed rather than faking it.
2. **Blockout.** Main volumes only. Run `python qmesh_build.py recipe.json --out out/`, then check the gate and the overall size.
3. **Form.** Refine the profiles and sections from the outlines (the auto routes), or edit the numbers in the recipe JSON. Rebuild and compare the views.
4. **Detail.** Add the small parts: extrusions, sweeps (handles, rims) and plates. Use `"subdivide": 1` (Catmull-Clark) on organic parts only. Never subdivide hard edges you want sharp.
5. **Review.** Put the 6-view sheet side by side with the reference. Fix the worst mismatch first. Do at most 3 passes, then deliver and state what remains approximate.
6. **Deliver.**
   - Files: `<name>.obj` (quads), `<name>_mm.stl`, `<name>_recipe.json`, `<name>_report.json`, `<name>_views.png`.
   - In Rhino: run `s3d_qmesh_rhino.py`, pick the recipe or the OBJ, and choose output `nurbs` for mesh + SubD + polysurface (with an `IsSolid` check).
   - For CNC: `../styro3d_cnc.py` on the mesh (blocks, tool reach, job table).

## Commands

```
python qmesh_image.py sign logo.png --height-mm 600 --thickness-mm 50 --build
python qmesh_image.py revolve vase.png --height-mm 800 --segments 48 --build
python qmesh_image.py views sheet.png --views 4 --height-mm 1800 --segments 64 --build
python qmesh_image.py views --images front.png side.png --height-mm 900 --build --hull-args "--angles 0,90"
python qmesh_build.py my_recipe.json --out out/ [--subdivide 1]
```

The views route uses `../views_to_3d/views_to_3d.py`, which handles automatically:
- split, scale and centring;
- diagonal-angle refinement;
- turn direction from colour;
- averaged mirror pairs and rounding for 4 views.

Pass extra hull options with `--hull-args`, for example `"--round off"` for boxy objects.

## Limits (say them)

- **Hidden hollows.** A visual hull cannot see concave parts that no outline shows: eye sockets, the inside of a cup, the gap behind an arm. They come out filled, as extra material.
- **4 views give a rough form.** A nose or brow from the side view becomes a band across the face. 8 views are better.
- **Extrude caps are quad-dominant, not all-quad.** There is a grid inside and a thin triangle band at the outline. Walls are all quads.
- **No mesh booleans.** Touching parts are separate shells. Join them in Rhino (SubD/NURBS `BooleanUnion`) or keep them as an assembly for CAM.
