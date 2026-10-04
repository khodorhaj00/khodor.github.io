import numpy as np, cv2
names = ["v000", "v045", "v090", "v135", "v180", "v225", "v270", "v315"]
top, bot = [], []
for v in names:
    inp = (np.clip(np.load("out/c8_%s_img.npy" % v), 0, 1) * 255).astype(np.uint8)[:, 90:610]
    r = cv2.resize(cv2.imread("out/fin8_%s.png" % v), (700, 448), interpolation=cv2.INTER_AREA)[:, 90:610]
    top.append(inp); bot.append(r)
W = 520 * 4
def bar(t):
    b = np.full((36, W, 3), 22, np.uint8); cv2.putText(b, t, (12, 25), cv2.FONT_HERSHEY_SIMPLEX, 0.7, (225, 225, 225), 2); return b
sheet = np.vstack([bar("Your 8-view sheet (calibrated: 3/4 views are at 29 and 34 deg, not 45)"), np.hstack(top[:4]), bar("Surface built from the points + 8 outlines + shading (same cameras)"), np.hstack(bot[:4]),
                   bar("Your 8-view sheet, back row"), np.hstack(top[4:]), bar("Model, back row"), np.hstack(bot[4:])])
cv2.imwrite("out/points8_compare.jpg", cv2.resize(sheet, None, fx=0.75, fy=0.75, interpolation=cv2.INTER_AREA), [cv2.IMWRITE_JPEG_QUALITY, 88])
print("ok")
