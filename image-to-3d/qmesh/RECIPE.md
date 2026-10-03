# qmesh recipe reference (`s3d-qmesh/1`)

A recipe is a JSON file in **millimetres**. Every part becomes one closed, clean mesh, and parts stay separate shells.

```json
{
  "format": "s3d-qmesh/1",
  "name": "my_object",
  "units": "mm",
  "parts": [ { "name": "body", "op": "revolve", "profile": [[0, 0], [120, 0], [90, 300], [0, 310]] } ]
}
```

## Ops

| op | Fields (defaults) | Topology |
|---|---|---|
| `box` | `size` [x, y, z]; `segments` [nx, ny, nz] ([2, 2, 2]); `at` = centre | quad grid on 6 sides |
| `sphere` | `r`; `segments` per cube edge (8); `at` | quad sphere, **no poles** |
| `cylinder` | `r` (or `rx` / `ry`), `h`; `segments` (32, made a multiple of 4); `rings` (1); `n` superellipse exponent (2 = round, 4+ = rounded box); `at` = base centre | rings + quad caps |
| `cone` | `r1` (bottom), `r2` (top, 0 = point), `h`; `segments`; `rings`; `at` | rings + quad caps |
| `torus` | `R`, `r`; `segments` (48); `tube_segments` (16); `at` | all quads, genus 1 |
| `revolve` | `profile` [[r, z], …] from one end to the other; `segments` (48) | rings. Points with r = 0 at the ends become quad caps. Flat ends get a quad grid in the middle. |
| `loft` | `sections`: list of `{"points": [[x, y, z], …]}`, all with the same count, start and direction. Or `{"z", "rx", "ry", "cx", "cy", "n"}` superellipses, with `segments`. `cap_start` / `cap_end`: `quad` \| `fan` \| `open`. `dome_start` / `dome_end` mm. | rings + quad caps |
| `extrude` | `outer` [[x, y], …], `holes` [[[x, y], …], …], `height`, `z0`; `edge` = target quad size (resamples the outline, keeping corners); `layers`; `quad_caps` (true); `plane`: `XY` (along +Z) \| `XZ` (outline drawn in a front view: x right, y up, depth along +Y) \| `YZ` | quad walls. Caps: quad grid inside, a paired-triangle band at the outline. |
| `sweep` | `profile`: [[x, y], …] or `{"shape": "circle" \| "ellipse" \| "superellipse" \| "rect", "r" / "rx" / "ry" / "w" / "h", "n", "segments"}`; `path` [[x, y, z], …]; `closed`; `cap` (`quad`); `twist` deg; `scale_end` | rings on rotation-minimising frames, path resampled evenly |
| `mesh` | `vertices`, `faces` | taken as given, then oriented |
| `copy` | `of`: the name of an earlier part | copy of that part's mesh |

## Fields on every part

| Field | Meaning |
|---|---|
| `name` | Part name. It becomes the OBJ object name and the Rhino object name. |
| `subdivide` | Catmull-Clark levels. Use on organic parts only; it rounds every edge. |
| `scale` | Number or [sx, sy, sz]. Applied about `scale_centre` (default origin). |
| `rotate` | `{"axis": [0, 0, 1], "deg": 30, "centre": [x, y, z]}`, or a list of these. |
| `move` | [dx, dy, dz]. |
| `mirror` | `"X"`, `"Y"` or `"Z"`: adds a mirrored copy named `<name>_mirror`. |
| `skip` | true = ignore this part. |

Transforms run in this order: subdivide, then scale, then rotate, then move.

## Coordinates

- X is right, as seen in the front view.
- Y points away from the front camera, so the front of the object faces −Y.
- Z is up, and the base sits on Z = 0 for the auto routes.

This matches `views_to_3d` and `styro3d_cnc.py`.
