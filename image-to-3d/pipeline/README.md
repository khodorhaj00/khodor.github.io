# Photo → 3D bust pipeline (research code behind Mode 4)

> **Mode 4 data now comes from the 4-view pipeline in [`multiview/`](multiview/README.md) (script v1.2).**
> This folder is the older one-photo version (v1.1). Use it when you only have a single photo.

This rebuilds a statue / bust from **one photo** without any AI 3D generator, then packs the result into
`../styro3d_ai_to_cnc.py` (Mode 4). It is the exact code used for the v1.1 bearded Roman bust.

**Needs**:
- Python 3.11 with `numpy scipy opencv-python-headless mediapipe jax trimesh pillow`.
- Blender 5 as a module (`pip install bpy==5.0.1`) for the renders.
- `face_landmarker.task` from MediaPipe.
- `libEGL` on Linux.

**Run in a work folder** containing `photo.jpg` (black or plain background) and `out/`:

| Step | Script | Does |
|---|---|---|
| 0 | `s0_landmarks.py`, `s0b_calibrate.py` | 478 face points, head pose, metric face model, scale (mm/px) |
| 1 | `s1a_prior.py` → `s1b_fit_cranium.py` → `s1c_fit_side_beard.py` → `s1d_union.py` → `s1e_smooth.py` → `s1f_light.py` | silhouette, fitted template (skull, side, beard, ear, neck, torso), prior depth, light direction |
| 2 | `s2_shape_from_shading.py 768 0.06 1.2 _c` | linear regularised shape-from-shading + fine relief → `out/h_lin_c.npy` |
| 3 | `s3_grid.py 1024 260 520 out/h_lin_c.npy out/mesh_final.npz` | closed quad grid: observed front, mirrored far side, template back, hair transfer |
| 4 | `s4_encode_inject.py` | radius map → base64 → injected into the Rhino script, then verified with the script's own decoder |
| 5 | `s5_render_blender.py mesh.npz out/r photo,face,q3,left,back 1024 128` | Cycles marble renders |

**Photo-specific constants to change for a new photo:**
- `s_cm, t_a, t_b, t_d` (paste from step 0b) in `s1*`, `s3_grid.py` and `template3d.py`.
- Ear rows `ear_b0/ear_b1` in `s1a`.
- Beard tip `(880, 1330)` in `s1c`.
- Neck ring row `1100` in `s3_grid.py`.
- Hair-zone heights in `s3_grid.py`.
- `S = 0.192` mm/px.

**Known limits:**
- Single view. The back and the far ear are estimated from the template, the mirrored near side and copied hair texture.
- A second photo (side or back) would turn those areas into measured data.
