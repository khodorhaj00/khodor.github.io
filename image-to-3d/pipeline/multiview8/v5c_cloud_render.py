"""Point-cloud pictures (z-buffered splats): stereo points coloured by the photo, triangulated face points in green."""
import numpy as np, cv2
from v_common import *
P = np.load("out/points_stereo_clean.npy").astype(np.float64)
face = np.load("out/face3d.npy"); face = face[~np.isnan(face).any(1)]
def render(az, W=560, H=470, scale=1.0):
    img = np.full((H, W, 3), 22, np.uint8); zb = np.full((H, W), np.inf)
    t = np.radians(az)
    def put(pts, cols, rad):
        u = pts[:, 0] * np.cos(t) - pts[:, 1] * np.sin(t); w = pts[:, 0] * np.sin(t) + pts[:, 1] * np.cos(t)
        x = np.round(u * scale + W / 2).astype(int); y = np.round((CR0 - pts[:, 2]) * scale + 14).astype(int)
        for dx in range(-rad, rad + 1):
            for dy in range(-rad, rad + 1):
                xx, yy = x + dx, y + dy; ok = (xx >= 0) & (xx < W) & (yy >= 0) & (yy < H)
                o = np.nonzero(ok)[0]; o = o[np.argsort(-w[o])]
                for i0 in range(0, len(o), 200000):
                    oo = o[i0:i0 + 200000]
                    closer = w[oo] < zb[yy[oo], xx[oo]]
                    oo = oo[closer]; zb[yy[oo], xx[oo]] = w[oo]; img[yy[oo], xx[oo]] = cols[oo]
    cols = (np.clip(P[:, 3:6], 0, 1) * 255 * 0.9).astype(np.uint8)
    side = np.cos(np.radians(P[:, 6] - az)) > 0.2                      # only points measured from this side
    put(P[side, :3], cols[side], 1)
    if np.cos(np.radians(az)) > 0.1:                                  # face points belong to the front half
        put(face, np.tile(np.array([[80, 255, 110]], np.uint8), (len(face), 1)), 1)
    return img
tiles = []
for az, txt in ((0, "FRONT"), (35, "3/4"), (90, "SIDE"), (180, "BACK")):
    t = render(az); cv2.putText(t, txt, (12, 28), cv2.FONT_HERSHEY_SIMPLEX, 0.7, (230, 230, 230), 2); tiles.append(t)
sheet = np.hstack(tiles)
bar = np.full((40, sheet.shape[1], 3), 22, np.uint8)
cv2.putText(bar, "%d 3D points matched between the 8 views  +  %d face points triangulated from 3 views (green)" % (len(P), len(face)), (12, 28), cv2.FONT_HERSHEY_SIMPLEX, 0.7, (230, 230, 230), 2)
cv2.imwrite("out/points8_cloud.jpg", np.vstack([bar, sheet]), [cv2.IMWRITE_JPEG_QUALITY, 92])
print("cloud image saved")
