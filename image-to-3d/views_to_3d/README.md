# views_to_3d: any object, from a views sheet to a closed STL

This takes a turnaround sheet (4, 8 or any number of views around the vertical axis) and gives a **closed STL in mm** that `../styro3d_cnc.py` can machine. It needs no AI 3D generator and no settings tuned to one object. The bust pipelines in `../pipeline/` remain the face-specific, hand-tuned versions.

```
python views_to_3d.py sheet.png --views 4 --height-mm 1800
python views_to_3d.py sheet8.png --views 8 --height-mm 600 --out my_part
python views_to_3d.py --images front.png right.png back.png left.png --height-mm 900
python views_to_3d.py sheet.png --views 3 --angles 0,120,240 --height-mm 500
```

**Needs**: Python 3.9+, `numpy scipy opencv-python-headless scikit-image`.

**Output** goes in `<name>_3d/` next to the sheet:

| File | What it is |
|---|---|
| `<name>_mm.stl` | Closed binary STL in mm. Z is up, the base sits on Z = 0, and X/Y are centred. Front = −Y. |
| `<name>_check.png` | One column per view, three rows: the input; the outline match (grey = match, red = missed, blue = extra); the model rendered from the same angle. |
| `<name>_info.json` | Angles and centres found, outline IoU per view, size, volume, and whether the mesh is closed. |
| `<name>_log.txt` | The run log. |

## Views order

Views are read **left → right, top → bottom**.

- **4 views:** front, right side, back, left side (0, 90, 180, 270°).
- **8 views:** every 45°, starting at the front.
- **Any other set:** pass `--angles`.

"Right side" means the object's own right side: in that view its nose points to the image right.

If the sheet goes the other way round, or the LEFT/RIGHT labels are swapped, `--order auto` finds it. That is the default: it builds both versions and keeps the one whose views agree best in colour.

## How it works

Every step runs automatically:

1. **Split.**
   - The background colour comes from the image border.
   - The threshold is set from the background's own noise, so dark parts of the object stay in.
   - Grid lines, frames and text are removed: thin strokes are opened away.
   - Each view is one blob in reading order. Loose parts of one view are merged, but two views never are.
   - Small dark spots are filled. Real through-holes stay open: a handle, a ring, a letter O.
2. **Scale.** Every view is scaled to the same object height, with the base rows aligned.
3. **Centre.**
   - A view and the one 180° away see mirrored outlines, so a flip correlation gives their axis columns.
   - A pair whose overlap is under 0.92 is solved as two separate views.
4. **Angles.**
   - Views that are not at 0/90/180/270° are scored at every angle within ±25°, each with its best centre.
   - The score is how much of every outline the hull fills.
   - Outlines often fit equally well over a range of angles. If the drawn angle lies in that best range, it is kept. If not, the middle of the range is used.
   - The centre works the same way: the tool takes the middle of the band of centres that fit. Half that band's width is this view's **uncertainty**. The view's outline is grown by that amount, so a view whose position is uncertain never cuts true material.
5. **Order.**
   - The outlines alone cannot tell the turn direction: the front/back mirror of the object explains the reversed order exactly.
   - So colour decides. The tool tests how well neighbouring views agree in luminance and chroma, at raw and fine-detail scales, on the surface points both views see.
6. **Hull.**
   - A view and its mirror view count as one averaged outline (`--pairs mean`). AI sheets never draw front and back exactly mirrored, and a strict cut loses material.
   - With only two view directions (4 views), every slice of the hull is a set of rectangles. Each rectangle gets a superellipse inscribed in it (`--round 2.5`).
   - The tool keeps the largest solid and fills its internal holes.
7. **Mesh.** Marching cubes, then light smoothing, then a closed mesh in mm.

| Option | Default | When to change it |
|---|---|---|
| `--round` | `auto` (2.5 for 4 views) | `--round 2` for very round objects (heads, bodies, vases). `--round off` for boxy parts (letters, signs, furniture). |
| `--refine` | `oblique` | `none` if your diagonal views are known to be exact. `all` to also refine the 90/180/270 views. |
| `--order` | `auto` | `as-is` / `reverse` to force the turn direction. |
| `--pairs` | `mean` | `strict` for real, consistent photos (a turntable shoot). |
| `--soft` | `0` | A value in px rounds the hull edges. It was less accurate in the tests. |
| `--res` | `256` | `384`–`512` for more detail (slower, more memory). |

## Tested on objects with a known true shape (`selftest.py`)

`selftest.py` renders sheets of a test object whose shape is known, runs the tool, and measures the error against the truth. The test object is an asymmetric "kettle" with a spout, a handle ring, a front plate and a back fin.

The results table is in `../TOOLKIT.md`. Re-run it with:

```
python selftest.py                              # built-in test object
python selftest.py --mesh any_mesh.npz --height-mm 290
```

## Limits

- **Hidden concave areas.** The hull cannot see a concave area that no outline shows: eye sockets, the inside of a cup, or the gap between an arm and the body when seen from the front. These come out filled, as extra material. Carve them in Rhino or on the machine, or add views that show them.
- **Shaved corners with 4 views.** The default rounding (`--round 2.5`) is about 30 % closer overall, but it shaves sharp box corners: on the test object, a few % of the true surface by a few mm. For boxy parts, or when no material may be missing, use `--round off --pairs strict`.
- **4 views give a rough form.** Features that only the side view shows, such as a nose or a brow, become horizontal bands across the full width. 8 views are better. For faces, the face-specific pipeline (`../pipeline/multiview/`, Mode 4) is better still.
- **Perspective.** The views must be orthographic, or close to it: no strong perspective and no wide-angle look.
- **Background.** The object must stand on a plain background. Shadows on the floor count as part of the object.

## Prompt for a good sheet (ChatGPT / Gemini image)

> Orthographic turnaround sheet of [OBJECT], 4 views in a 2x2 grid: FRONT, RIGHT SIDE, BACK, LEFT SIDE. Same scale and same height in every view, the object centred in each cell. True orthographic projection, no perspective, camera at mid height. Plain flat white background, no floor, no cast shadows, even soft studio light. Full object visible in every view, nothing cropped. Small label under each view.

For 8 views, use "8 views in a 2x4 grid, every 45 degrees, starting at the front and turning to the object's right".
