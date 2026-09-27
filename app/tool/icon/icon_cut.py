import sys
from collections import deque
from PIL import Image, ImageFilter
import numpy as np

src, out = sys.argv[1], sys.argv[2]
im = Image.open(src).convert('RGB')
a = np.asarray(im).astype(np.float32)
h, w, _ = a.shape
# Background colour: median of the border pixels.
border = np.concatenate([a[0], a[-1], a[:, 0], a[:, -1]])
bg = np.median(border, axis=0)
dist = np.sqrt(((a - bg) ** 2).sum(axis=2))
# Flood fill from the border through pixels close to the background colour.
lum = a.mean(axis=2); sat = a.max(axis=2) - a.min(axis=2)
close = (dist < 38) | ((sat < 14) & (lum < 125))
mask_bg = np.zeros((h, w), bool)
q = deque()
for x in range(w):
    for y in (0, h - 1):
        if close[y, x] and not mask_bg[y, x]:
            mask_bg[y, x] = True; q.append((y, x))
for y in range(h):
    for x in (0, w - 1):
        if close[y, x] and not mask_bg[y, x]:
            mask_bg[y, x] = True; q.append((y, x))
while q:
    y, x = q.popleft()
    for dy, dx in ((1, 0), (-1, 0), (0, 1), (0, -1)):
        ny, nx = y + dy, x + dx
        if 0 <= ny < h and 0 <= nx < w and close[ny, nx] and not mask_bg[ny, nx]:
            mask_bg[ny, nx] = True; q.append((ny, nx))
alpha = np.where(mask_bg, 0, 255).astype(np.uint8)
# Soft edge: blur the mask a little, keep solid inside.
am = Image.fromarray(alpha).filter(ImageFilter.MinFilter(3)).filter(ImageFilter.GaussianBlur(1.2))
rgba = im.copy(); rgba.putalpha(am)
rgba.save(out)
print('bg', bg, 'kept', (alpha > 0).mean())
