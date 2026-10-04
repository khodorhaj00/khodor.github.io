# 4-view sheet → 3D bust pipeline (research code behind Mode 4, v1.2)

This rebuilds the bust from **one sheet with 4 views**: FRONT, RIGHT, BACK and LEFT, in a 2×2 grid. It uses no AI 3D generator. The result is packed into `../../styro3d_ai_to_cnc.py` as `BUST_DATA` (Mode 4). It is the exact code used for the bearded Roman bust.

**Needs**:
- Python 3.11 with `numpy scipy opencv-python-headless mediapipe`.
- Blender 5 as a module (`pip install bpy==5.0.1`) for the renders.
- `face_landmarker.task` from MediaPipe.
- `libEGL` / `libGLES` on Linux.

**Run in a work folder** that contains `sheet.png`, `face_landmarker.task`, `canon_tris.npy` and an empty `out/`. Copy all scripts there.

| Step | Script | Does |
|---|---|---|
| 0 | `mv0_split.py`, `mv0b_landmarks.py` | Split the sheet into 4 panels and cut out the bust. Find the 478 MediaPipe face points on the front view. |
| 1 | `mv1_profiles.py` | Sub-pixel outline extents per view row (soft alpha from the black background) |
| 2 | `mv2_align.py` | Put all views into one orthographic frame (Z up, face toward −Y, 0.618 mm/px). Each view gets a feature-matched height warp and X/Y centring. |
| 3 | `mv3_base.py` → `mv3b_volume.py` | Per-height lobes (head→neck, beard, torso) fitted to the outlines, turned into a voxel distance field |
| 4 | `mv4_face.py` | MediaPipe face mesh with its depth calibrated to the side profile, plus ears (gap filled for CNC). Exact 3D distance, then smoothing → base `B1s`. |
| 5 | `mv5_sfs.py` | Linear regularised shape-from-shading per view on B1s's depth maps, plus fine relief from luminance |
| 6 | `mv6_fuse.py` | Fusion of the 4 views. See the list below the table. |
| 7 | `mv7_grid.py 1024 260 520` → `mv7b_clean.py` | Cast the Rhino-script grid (spine rings + head rays from H) on the fused volume. Remove spikes and anti-alias fold steps. |
| 8 | `mv8_mesh.py out/mv_mesh_Rc.npy out/mv_final.npz` | Reference mesh (same maths as `bust_grid` in the Rhino script) |
| 9 | `mv9_inject.py [path/to/styro3d_ai_to_cnc.py]` | Encode: uint16 low-res + companded int8 detail → base64 → `BUST_DATA`. Then decode with the script's own code and compare. |
| 10 | `mv_render.py out/mv_decoded.npz out/fin mfront,mright,mback,mleft,front,q3,right,q3b 900 40` → `mv10_sheets.py` | Cycles renders with exact view framing; input-vs-model sheets |

Step 6 (`mv6_fuse.py`) does this, in order:
1. Pushes back any view that sticks out of another view's outline (smoothly, not with a flat cut).
2. Pulls the views into agreement at large scale over 2 rounds.
3. Fuses everything into a TSDF, weighted by facing³.
4. Carves the result to the front and side outlines.

**Sheet-specific values to re-measure for a new sheet:**
- `ANCH` in `mv2_align.py`: per-view rows of the head top, brow, nasion, nose tip, subnasale, mouth, beard tip and base.
- Panel boxes in `mv0_split.py`.
- Ear boxes in `mv4_face.py` (rows and Y range from the side views, outer X from the front/back outlines).
- Beard U-outline and the hidden jaw/throat line in `mv3_base.py`, and the beard line in `mv4_face.py`.
- Ring row `r_ring = 330` and head-centre row `hr = 180` in `mv7_grid.py`.

**Result (this sheet):**
- 799,746 vertices, 798,720 quads + 2,048 tris.
- 290 mm tall, 6.83 L.
- Closed manifold (Euler 2).
- Decoder error 0.08 mm max.
