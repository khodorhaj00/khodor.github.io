"""Split the 4x2 eight-view sheet by the background gaps of each row band; cut out each bust."""
import numpy as np, cv2, json
from scipy import ndimage as ndi
im = cv2.imread("sheet8.png"); H, W = im.shape[:2]
L = cv2.cvtColor(im, cv2.COLOR_BGR2GRAY).astype(np.float32) / 255
names = ["v000", "v045", "v090", "v135", "v180", "v225", "v270", "v315"]
rowsum = (L > 0.10).sum(1)
# row split: middle of the widest empty run near the centre
zr = np.nonzero(rowsum[H // 2 - 60:H // 2 + 60] == 0)[0] + H // 2 - 60
ysplit = int(np.median(zr)) if len(zr) else H // 2
bands = [(0, ysplit), (ysplit, H)]
info = {}; k = 0
PAD = 448                                                     # every panel is placed in a square canvas of this size
for (y0, y1) in bands:
    colsum = (L[y0:y1] > 0.10).sum(0)
    # split columns at the 3 widest empty runs between content
    z = colsum == 0; runs = []; i = 0
    while i < W:
        if z[i]:
            j = i
            while j < W and z[j]: j += 1
            if i > 0 and j < W: runs.append((j - i, i, j))
            i = j
        else: i += 1
    runs = sorted(sorted(runs)[::-1][:3], key=lambda t: t[1])
    cuts = [0] + [(a + b) // 2 for _, a, b in runs] + [W]
    for c in range(4):
        x0, x1 = cuts[c], cuts[c + 1]
        p = im[y0:y1, x0:x1]
        Lp = L[y0:y1, x0:x1]
        m = ndi.binary_opening(Lp > 0.10, iterations=1)
        lab, n = ndi.label(m); sizes = ndi.sum(m, lab, range(1, n + 1)); kk = 1 + int(np.argmax(sizes))
        m = ndi.binary_fill_holes(lab == kk)
        ys, xs = np.nonzero(m)
        # centre the bust horizontally in a square canvas, keep rows (sheet rows of this band)
        canvas = np.zeros((PAD, PAD, 3), np.uint8); cm = np.zeros((PAD, PAD), bool)
        cx = 0.5 * (xs.min() + xs.max()); ox = int(round(PAD / 2 - cx))
        hh = min(PAD, p.shape[0])
        for dst, src in ((canvas, p), (cm, m)):
            xa, xb = max(0, ox), min(PAD, ox + p.shape[1])
            dst[:hh, xa:xb] = src[:hh, xa - ox:xb - ox]
        nm = names[k]
        cv2.imwrite("out/%s.png" % nm, canvas); np.save("out/%s_mask.npy" % nm, cm)
        ys, xs = np.nonzero(cm)
        info[nm] = dict(sheet_box=[int(x0), int(y0), int(x1), int(y1)], ox=int(ox), top=int(ys.min()), bot=int(ys.max()), x0=int(xs.min()), x1=int(xs.max()))
        print("%s sheet x %4d..%4d y %3d..%3d | bust rows %3d..%3d (h %d) cols %3d..%3d" % (nm, x0, x1, y0, y1, ys.min(), ys.max(), ys.max() - ys.min(), xs.min(), xs.max()))
        k += 1
json.dump(info, open("out/panels.json", "w"), indent=1)
tiles = [cv2.imread("out/%s.png" % n) for n in names]
cv2.imwrite("out/panels_check.png", np.vstack([np.hstack(tiles[:4]), np.hstack(tiles[4:])]))
