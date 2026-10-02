import numpy as np, cv2, json
from mv_common import *
out = {}
for v in VIEWS:
    im, lum, m = load(v); a = soft_alpha(lum, m); L, R = row_extents(a)
    np.save("out/%s_alpha.npy" % v, a.astype(np.float32))
    out[v] = (L, R)
    ok = ~np.isnan(L); rows = np.nonzero(ok)[0]
    print("%-5s rows %d..%d" % (v, rows[0], rows[-1]))
np.savez("out/extents.npz", **{v + "_L": out[v][0] for v in VIEWS}, **{v + "_R": out[v][1] for v in VIEWS})
# plot profiles: front/back widths, side front/back extents
H = 520; W = 900
img = np.zeros((H, W, 3), np.uint8)
cols = {"front": (0, 200, 255), "back": (255, 120, 0), "right": (0, 255, 0), "left": (255, 0, 255)}
for v in VIEWS:
    L, R = out[v]
    for y in range(len(L)):
        if np.isnan(L[y]): continue
        if v in ("front", "back"):
            wv = R[y] - L[y]; x = int(450 + wv / 2); cv2.circle(img, (x, y), 1, cols[v], -1); cv2.circle(img, (int(450 - wv / 2), y), 1, cols[v], -1)
        elif v == "right":
            cv2.circle(img, (int(R[y]) + 250, y), 1, cols[v], -1); cv2.circle(img, (int(L[y]) + 250, y), 1, cols[v], -1)
        else:
            cv2.circle(img, (int(1015 - L[y]) - 250 + 0, y), 1, cols[v], -1); cv2.circle(img, (int(1015 - R[y]) - 250, y), 1, cols[v], -1)
for y in range(0, H, 20):
    cv2.line(img, (0, y), (12, y), (90, 90, 90), 1); cv2.putText(img, str(y), (14, y + 4), cv2.FONT_HERSHEY_SIMPLEX, 0.3, (140, 140, 140), 1)
cv2.imwrite("out/profiles.png", img)
