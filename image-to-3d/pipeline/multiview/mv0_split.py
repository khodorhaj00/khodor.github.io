"""Stage 0: split the 4-view sheet (2x2 panels: FRONT | RIGHT / BACK | LEFT) and cut the bust out of each panel.
Writes out/<view>.png, out/<view>_mask.npy, out/panels.json."""
import json, numpy as np, cv2
from scipy import ndimage as ndi
im = cv2.imread("sheet.png")
# panel boxes (y0, y1, x0, x1) for the 1536 x 1024 sheet; the 4 px divider lines are skipped
panels = {"front": (0, 506, 0, 767), "right": (0, 506, 771, 1536), "back": (510, 1024, 0, 767), "left": (510, 1024, 771, 1536)}
info = {}
for name, (y0, y1, x0, x1) in panels.items():
    p = im[y0:y1, x0:x1].copy()
    L = cv2.cvtColor(p, cv2.COLOR_BGR2GRAY).astype(np.float32) / 255
    m = ndi.binary_opening(L > 0.10, iterations=1)
    lab, n = ndi.label(m); sizes = ndi.sum(m, lab, range(1, n + 1)); k = 1 + int(np.argmax(sizes))   # bust = largest blob (drops the caption)
    m = ndi.binary_fill_holes(lab == k)
    ys, xs = np.nonzero(m)
    cv2.imwrite("out/%s.png" % name, p); np.save("out/%s_mask.npy" % name, m)
    info[name] = dict(top=int(ys.min()), bot=int(ys.max()), x0=int(xs.min()), x1=int(xs.max()), size=[p.shape[1], p.shape[0]])
    print("%-5s bust rows %d..%d cols %d..%d" % (name, ys.min(), ys.max(), xs.min(), xs.max()))
json.dump(info, open("out/panels.json", "w"), indent=1)
