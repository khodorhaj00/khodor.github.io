# photo3d: photo → 3D model → Rhino (fastest route)

An AI makes the shape from your photo(s) in 1–3 minutes. One Rhino script then finishes it:
- real size in mm;
- closed mesh;
- clean quads;
- SubD;
- NURBS polysurface.

## 3 ways to run it

| Way | Where | You need |
|---|---|---|
| **A. Claude chat** | The chat runs the AI (Higgsfield `generate_3d`) and gives you a **GLB link**. In Rhino, run the script with source **URL** and paste the link. | Higgsfield credits: 7 per model (Hunyuan3D v3) or 13.5 (Tripo H3.1). Your balance on 3 Oct 2026 is **0**. |
| **B. Straight from Rhino** | Run the script with source **AI** and pick 1–4 photos. The model lands in Rhino. | A fal.ai API key (pay per model, e.g. Tripo H3.1 from $0.20). |
| **C. Free** | Get the GLB from any free web generator (Hunyuan3D, Tripo or Meshy free tiers), then run the script with source **File**. | Nothing |

## The Rhino script: `s3d_photo_to_rhino.py`

`_RunPythonScript` → pick the file → choose the source → set the real size → OK.

| Source | What it takes |
|---|---|
| AI | 1–4 photos: front, plus optional back, left and right. Then you pick the model: `hunyuan` (best detail), `tripo`, `tripo-quad` (comes back as quads), `meshy`, or `custom`. |
| URL | A model link from a Claude chat, Higgsfield, Meshy, Tripo, Hunyuan3D or fal |
| File | GLB, glTF, OBJ, FBX, STL, PLY, 3MF or ZIP. **GLB works in Rhino 7 too**, because the script reads it itself. |
| Pick | Meshes that are already in the model |

The script does all of this in one pass:
1. Welds the UV seams.
2. Turns the model Z up, with the front facing −Y.
3. Drops loose bits and inner shells.
4. Scales to your real size.
5. Closes holes; on Rhino 8 it uses ShrinkWrap if the mesh is still open.
6. QuadRemesh.
7. SubD.
8. NURBS polysurface, with an IsSolid check.

Results go on layers `S3D_Photo3D::Raw / Mesh / Quad / SubD / Polysurface`. Downloads are saved in `S3D_Photo3D\<date_time>\`, next to your .3dm or on the Desktop.

| Setting | Default | When to change it |
|---|---|---|
| Real size mm + size axis | 1000, height | Use width / depth / longest for wide objects |
| Up axis / turn | auto / 0 | The model lies on its side → change up. It faces the wrong way → turn 90 / 180 / 270. |
| QuadRemesh quads | 4000 | 1500–4000 for products, 3000–6000 for sculptures. 0 keeps the dense mesh. |
| Hard edges | n | y for machined or furniture parts |
| Symmetry | none | x for objects that are the same left and right |
| Output | nurbs | mesh, quad or subd to stop earlier |

## Cloud helper: `p3d_cloud.py` (for Claude chats)

```
python p3d_cloud.py prep sheet.png --sheet 4 --names front,right,back,left --out ai_in/
python p3d_cloud.py check model.glb --height-mm 1800 --out checked/
python p3d_cloud.py ai front.png --model hunyuan --height-mm 290 --out ai_out/
```

- `prep`: cuts the object out on white, squares it and gives every view the same scale. For best AI results, use true front / back / left / right views, not 3/4 views.
- `check`: reports size, closed, loose pieces and a 6-view picture, and writes a Z-up OBJ + STL in mm.
- `ai`: sends photo(s) to fal.ai with the same presets as the Rhino script, downloads the model and runs `check`. It needs the fal hosts allowed in the cloud environment and the key in `FAL_KEY` or `~/.config/styro3d/fal_key.txt`, never in the repo.

## Tests (`../tests/test_photo3d.py`, all pass)

| Test | Result |
|---|---|
| GLB reader against trimesh | Same vertices on a 2-node scene with transforms |
| Hand-built GLB, every awkward case | Interleaved buffer, uint8/16/32 indices, nested TRS nodes, int16-quantized positions, triangle strip, sparse accessor: all exact. `.gltf` with embedded or external buffers works. Draco is refused with a clear message. |
| AI request flow (local mock of the fal queue) | Submit → queued → running → done → GLB download. The key and photo are sent correctly; a bad field shows fal's own error text. |
| Stand-in AI file (Y up, 1 unit tall, split seam, stray speck) | Comes out closed, speck dropped, Z up, front −Y, 900 mm tall. Every vertex is within 0.02 mm of the true shape. |
| Views sheet prep | Splits into 4 squares on white, all at the same scale |
| Rhino script | Python 2.7 grammar and ASCII. Every RhinoCommon call exists in Rhino 7 and 8 (ShrinkWrap is Rhino 8 only and guarded). |

## Limits

- The AI guesses the sides it cannot see. With one photo the back is invented; 2–4 true views fix most of that.
- The size comes from the one dimension you give. Check a second dimension in Rhino.
- Fine detail under about 1 % of the size comes out soft. For more detail, raise the quad count or lower adaptive size.
- **Not yet run inside Rhino or against the live fal / Higgsfield services:** the cloud blocks those hosts. If something fails, paste the command-line text into the chat.
