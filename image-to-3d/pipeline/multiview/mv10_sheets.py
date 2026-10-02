"""Final sheets: the 4 input views vs exact-framed renders of the decoded mesh, plus perspective views.
Run after: mv_render.py out/mv_decoded.npz out/fin mfront,mright,mback,mleft,front,q3,right,q3b 900 40"""
import numpy as np, cv2
VIEWS = ["front", "right", "back", "left"]
top, bot = [], []
for v in VIEWS:
    inp = (np.clip(np.load("out/c_%s_img.npy" % v), 0, 1) * 255).astype(np.uint8)
    r = cv2.resize(cv2.imread("out/fin_m%s.png" % v), (780, 480), interpolation=cv2.INTER_AREA)
    inp = inp[:, 150:630]; r = r[:, 150:630]                 # crop is symmetric (780 - 630 = 150)
    if v in ("right", "back"): inp = inp[:, ::-1]             # their common frame is mirrored: show them as on the sheet
    top.append(inp); bot.append(r)
W = 480 * 4
def bar(text, h=40):
    b = np.full((h, W, 3), 24, np.uint8); cv2.putText(b, text, (14, 28), cv2.FONT_HERSHEY_SIMPLEX, 0.75, (225, 225, 225), 2); return b
heads = np.full((40, W, 3), 24, np.uint8)
for i, t in enumerate(["FRONT", "RIGHT", "BACK", "LEFT"]):
    cv2.putText(heads, t, (i * 480 + 205, 28), cv2.FONT_HERSHEY_SIMPLEX, 0.8, (225, 225, 225), 2)
sheet = np.vstack([heads, bar("Input: your 4-view sheet"), np.hstack(top), bar("3D model built by the Rhino script (Mode 4), same orthographic cameras"), np.hstack(bot)])
cv2.imwrite("out/bust4v_compare.jpg", sheet, [cv2.IMWRITE_JPEG_QUALITY, 90])
ims = [cv2.resize(cv2.imread("out/fin_%s.png" % v), (640, 640), interpolation=cv2.INTER_AREA) for v in ["front", "q3", "right", "q3b"]]
cv2.imwrite("out/bust4v_views.jpg", np.hstack(ims), [cv2.IMWRITE_JPEG_QUALITY, 90])
print("sheets written")
