---
name: photo-to-rhino
description: Fastest way from one photo or several views to a 3D model in Rhino - AI image-to-3D (Higgsfield generate_3d in the chat, or fal.ai straight from Rhino), then one Rhino script that sets real size, closes the mesh, QuadRemeshes it and makes SubD and a NURBS polysurface. Use when the user wants a 3D model, mesh, SubD or polysurface from an image or views and speed matters more than exact dimensions. For exact outlines (signs, letters, turned parts) use the image-to-qmesh skill instead.
license: MIT
---

# Photo -> 3D model -> Rhino (fastest route)

Files: `image-to-3d/photo3d/`

| File | Runs in | Role |
|---|---|---|
| `s3d_photo_to_rhino.py` | Rhino 7 / 8 | One script. Source **AI** (photos -> fal.ai with the user's key), **URL** (a model link, e.g. from Higgsfield), **File** (GLB / glTF / OBJ / FBX / STL / PLY / 3MF / ZIP; GLB works in Rhino 7 too), or **Pick** (meshes already in the model). Then: weld, Z up, real size, drop loose bits, close holes, QuadRemesh, SubD, NURBS polysurface (IsSolid). |
| `p3d_cloud.py` | cloud chat | `prep`: cut out, crop, square, split a views sheet, same scale for every view. `check`: size, closed, loose pieces, a 6-view picture, and an OBJ + STL in mm. |
| `README.md` | - | The guide for the user |

Cloud setup: `pip install numpy scipy opencv-python-headless scikit-image trimesh`.

## Pick the AI model (state the pick in one line)

| Input | Model (Higgsfield id / fal preset) | Credits on Higgsfield* |
|---|---|---|
| 1 photo, organic: sculpture, figure, animal, bust | Hunyuan3D v3, `generate_type: Geometry` (`hunyuan3d_v3_image_to_3d` / `hunyuan`) | 7 |
| 1 photo, product or hard-surface, clean quads wanted | Tripo H3.1, `quad: true`, `texture: false` (`tripo_h3_1_image_to_3d` / `tripo-quad`) | 13.5 |
| 2-4 views of the same object | Tripo H3.1 multiview (`tripo_h3_1_multiview_to_3d` / `tripo`), or Meshy (`multi_image_to_3d` / `meshy`) | 13.5 |
| Object in a busy photo | SAM 3 3D Objects (`sam_3_3d`), with a prompt naming the object | check `get_cost` |
| Human body shape and pose | `sam_3_3d_body` | check `get_cost` |

*Prices from `get_cost` on 3 Oct 2026 for untextured output. Always preflight with `get_cost: true` before spending.

Textures are not needed for Rhino or CNC. Always turn them off: it costs less and finishes faster.

## Route A: in the Claude chat (Higgsfield)

1. Ask, with multiple-choice answers:
   - what the object is;
   - one real dimension in mm;
   - how many views there are.
2. Call `balance` and `generate_3d` with `get_cost: true`. **Never spend credits without a clear yes.** If the balance is 0, say so and offer Route B or Route C.
3. Get the photo to Higgsfield. Remote tools cannot read chat attachments. Ways in:
   - `media_import_url` with any public HTTPS link to the photo. A file in the user's public GitHub repo works via `raw.githubusercontent.com`; say that it becomes public.
   - `media_upload_widget`: the user picks the file.
   - `media_upload` plus a PUT from the container. This only works if the environment allows `upload.higgsfield.ai`.
   - Run `p3d_cloud.py prep` first when the photo is on disk. For a views sheet, look at the views and name them correctly (`--names front,right,back,left`). Multi-view models need true front, back, left and right views; 3/4 views confuse them.
4. Call `generate_3d` with the chosen model and options, then `jobs_wait` until it is done. Give the user the **GLB link**.
5. In Rhino: `_RunPythonScript` -> `s3d_photo_to_rhino.py` -> **URL** -> paste the link. Then set the real size and `output nurbs`.
6. If the container can download the GLB, run `p3d_cloud.py check model.glb --height-mm H` and show the 6-view picture before Rhino. This works only if the environment allows Higgsfield's media host, `d2ol7oe51mr4n9.cloudfront.net`.

## Route A2: in the Claude chat with fal.ai

Use this when the environment allows `queue.fal.run`, `fal.run`, `fal.media`, `v3.fal.media` and `rest.alpha.fal.ai`, and the key is in `FAL_KEY` or `~/.config/styro3d/fal_key.txt`. Never put the key in the repo.

```
python p3d_cloud.py ai front.png [--back b.png --left l.png --right r.png] --model hunyuan --height-mm 290 --out ai_out/
```

It sends the photos, waits, downloads the model and runs `check`, which gives the 6-view picture and an OBJ + STL in mm. Send the user the model file. In Rhino they run the script with source **File**.

## Route B: straight from Rhino (no chat)

Use `s3d_photo_to_rhino.py`, source **AI**, with a fal.ai key. The key is read from the `FAL_KEY` environment variable, or `%APPDATA%\Styro3D\fal_key.txt`, or asked once.

- Presets: `hunyuan` (default), `tripo`, `tripo-quad`, `meshy`, or `custom` (any fal endpoint id plus its image field names).
- The script sends the photos as data URIs (shrunk to 2048 px, phone EXIF rotation applied), polls the fal queue, downloads the result and runs the same Rhino pass.
- If fal rejects a field, the error box shows fal's own message. Fix it with the `Extra JSON options` line or the custom preset.

## Route C: free, no AI

- Exact outlines (signs, letters, turned parts): use the `image-to-qmesh` skill.
- Any object from 4 or 8 views: `views_to_3d`.

These are slower to set up, but the size is measured, not guessed.

## Rhino settings to suggest

| Object | quads | hard edges | symmetry | output |
|---|---|---|---|---|
| Sculpture, figure, animal | 3000-6000 | n | x if symmetric | nurbs |
| Product, furniture, machine part | 1500-4000 | y | x if symmetric | subd or nurbs |
| Very detailed (relief, face close-up) | 0 (skip): keep the dense mesh | - | - | mesh |

- Front must face -Y. If the model lies on its side, rerun with `up` = y / z / x; if it faces the wrong way, use `turn` = 90 / 180 / 270.
- Use `size axis` for wide objects: set the width or the longest side instead of the height.

## Limits (say them)

- AI invents the sides it cannot see. With one photo, the back is a guess; 2-4 true views fix most of it.
- AI sizes are relative. The real size comes from the one dimension the user gives, so check another dimension in Rhino.
- Fine detail (text, thin parts under ~1 % of the size) is soft or missing. QuadRemesh smooths it further: lower `adaptive` or raise `quads` to keep more.
- Draco-compressed GLB: in Rhino 8, `_Import` it, then use source **Pick**.
- Tripo `quad` output is FBX. Rhino imports it natively, and the script skips QuadRemesh when the mesh is already quads.
