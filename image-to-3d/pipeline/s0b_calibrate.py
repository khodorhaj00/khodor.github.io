"""Step 0b: orthographic fit of the canonical (metric, cm) face model to the landmarks.
Prints s_cm (px per cm), t_a, t_b (image offset) and t_d (depth offset). Paste them into s1*/s3/template3d."""
import numpy as np
pts = np.load("mp_landmarks_px.npy")[:468]; canon = np.load("canon_xyz.npy"); M = np.load("mp_matrix.npy")
R = M[:3, :3] / np.linalg.norm(M[:3, :3], axis=0); cam = canon @ R.T
sx, tx = np.linalg.lstsq(np.c_[cam[:, 0], np.ones(468)], pts[:, 0], rcond=None)[0]
sy, ty = np.linalg.lstsq(np.c_[-cam[:, 1], np.ones(468)], pts[:, 1], rcond=None)[0]
s = 0.5 * (sx + sy); k, c = np.linalg.lstsq(np.c_[-s * cam[:, 2], np.ones(468)], pts[:, 2], rcond=None)[0]
print("s_cm %.2f  t_a %.1f  t_b %.1f  t_d %.1f  (z scale %.3f)  -> life-size mm/px = %.4f" % (s, tx, ty, c, k, 10.0 / s))
