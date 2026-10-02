#!/usr/bin/env python3
"""
views_to_3d.py | Styro3D universal views -> 3D (any object, no AI 3D generator)
=================================================================================
In : one sheet image with N views of the object (2x2, 1x4, 2x4 ... any grid),
     or N separate images. Views turn around the vertical axis, plain background.
Out: closed STL in mm (Z up, base on Z=0) for styro3d_cnc.py, plus a check sheet.

  python views_to_3d.py sheet.png --views 4 --height-mm 1800
  python views_to_3d.py sheet8.png --views 8 --height-mm 600 --out my_part
  python views_to_3d.py --images front.png right.png back.png left.png --height-mm 900

Default view order (reading order on the sheet, left->right, top->bottom):
  4 views: front, right side, back, left side            (0, 90, 180, 270 deg)
  8 views: front, front-right, right, back-right, back ... (0, 45, ... 315 deg)
  other:   --angles 0,120,240   (camera angle of each view in degrees)
"Right side" = the object's own right side (its nose points to the image right).
If the sheet uses the other direction, --order auto (default) finds it.

Method (every step is automatic, nothing is tuned to one object):
 1 split    background colour from the image border, foreground by colour
            distance (Otsu), the N biggest blobs in reading order = the views
 2 scale    every view scaled to the same object height, base rows aligned
 3 centre   mirror pairs (a view and the one 180 deg away) see mirrored
            outlines: their axis columns come from a flip correlation
 4 angles   views that are not 0/90/180/270 get their angle and centre refined
            by outline consistency (the hull must fill every outline)
 5 order    clockwise vs counter-clockwise (or left/right labels swapped):
            the hypothesis whose views agree best in colour wins
 6 hull     visual hull from all outlines (signed distances, optional
            tolerance for views that disagree), largest solid, holes filled
 7 mesh     marching cubes -> smoothed closed mesh in mm -> binary STL
 8 check    per-view outline IoU, renders of the model next to the inputs

Limits: the hull cannot see concave areas that no outline shows (eye sockets,
the inside of a cup, the gap between an arm and the body seen from the front).
They come out filled; carve them in Rhino / on the CNC, or add views.

Needs: python 3.9+, numpy, scipy, opencv-python-headless, scikit-image
"""
import argparse
import json
import math
import os
import struct
import sys
import time

import cv2
import numpy as np
from scipy import ndimage as ndi
from skimage import measure

VERSION = "1.0"


# =============================================================================
# 1 split
# =============================================================================
def load_rgb(path):
    im = cv2.imread(path, cv2.IMREAD_UNCHANGED)
    if im is None:
        sys.exit("cannot read " + path)
    alpha = None
    if im.ndim == 2:
        im = cv2.cvtColor(im, cv2.COLOR_GRAY2BGR)
    elif im.shape[2] == 4:
        alpha = im[..., 3].astype(np.float32) / 255.0
        im = im[..., :3]
    if im.dtype != np.uint8:
        im = (im / max(1, im.max()) * 255).astype(np.uint8)
    return im[..., ::-1].astype(np.float32) / 255.0, alpha


def parse_bg(text):
    t = (text or "auto").strip().lower()
    if t == "auto":
        return None
    if t == "white":
        return np.array([1.0, 1.0, 1.0])
    if t == "black":
        return np.array([0.0, 0.0, 0.0])
    t = t.lstrip("#")
    return np.array([int(t[i:i + 2], 16) / 255.0 for i in (0, 2, 4)])


def disk(r):
    y, x = np.mgrid[-r:r + 1, -r:r + 1]
    return x * x + y * y <= r * r + 0.5


def foreground(img, alpha=None, bg=None):
    """(soft 0..1 foreground, hard mask without thin lines, line radius).
    Soft = colour distance to the background colour; the threshold comes from the
    background's own noise, so dark parts of the object stay in. Thin strokes (grid
    lines, frames, text) are removed from the hard mask by an opening."""
    H, W = img.shape[:2]
    r_open = max(2, int(round(0.002 * max(H, W))))
    if alpha is not None and alpha.min() < 0.5:
        soft = np.clip(alpha, 0, 1)
        return soft, ndi.binary_opening(soft > 0.5, structure=disk(r_open)), r_open
    b = max(2, min(H, W) // 100)
    border = np.concatenate([img[:b].reshape(-1, 3), img[-b:].reshape(-1, 3),
                             img[:, :b].reshape(-1, 3), img[:, -b:].reshape(-1, 3)])
    if bg is None:
        bg = np.median(border, 0)
    dist = np.linalg.norm(img - bg[None, None], axis=-1)
    noise = np.percentile(np.linalg.norm(border - bg[None], axis=-1), 90)
    t = float(np.clip(3.0 * noise + 0.03, 0.05, 0.30))      # 5 % .. 30 % colour distance
    soft = np.clip((dist - 0.5 * t) / t, 0, 1)                 # anti-aliased edge band
    hard = ndi.binary_opening(dist > t, structure=disk(r_open))
    return soft, hard, r_open


def split_sheet(img, alpha, n, bg=None):
    """The n biggest foreground blobs in reading order -> [(rgb crop, soft mask crop)]."""
    soft, hard, r_open = foreground(img, alpha, bg)
    H, W = hard.shape
    # merge loose parts of one view (a detached spear, a gap) but never two views:
    # take the biggest merge radius that still leaves n big blobs
    best = None
    for frac in (0.010, 0.007, 0.005, 0.0035, 0.0025, 0.0015, 0.0):
        r = int(round(frac * max(H, W)))
        big = ndi.binary_dilation(hard, structure=np.ones((3, 3), bool), iterations=r) if r else hard
        lab, nl = ndi.label(big)
        if nl == 0:
            continue
        area = ndi.sum(hard, lab, np.arange(1, nl + 1))
        n_big = int((area >= 0.2 * area.max()).sum())
        if n_big == n:
            best = (lab, nl, area)
            break
        if n_big > n and best is None:
            best = (lab, nl, area)
    if best is None:
        sys.exit("could not find %d separate views on the sheet (use --views or --images)" % n)
    lab, nl, area = best
    if nl < n:
        sys.exit("found %d separate objects on the sheet, expected %d (use --views or --images)" % (nl, n))
    keep = 1 + np.argsort(area)[::-1][:n]
    boxes = []
    for k in keep:
        ys, xs = np.nonzero(lab == k)
        boxes.append((ys.min(), ys.max(), xs.min(), xs.max(), k))
    # reading order: group into rows by vertical overlap, then left -> right
    boxes.sort(key=lambda b: 0.5 * (b[0] + b[1]))
    rows, cur = [], [boxes[0]]
    for b in boxes[1:]:
        ref = cur[0]
        if b[0] < 0.5 * (ref[0] + ref[1]) < b[1] or ref[0] < 0.5 * (b[0] + b[1]) < ref[1]:
            cur.append(b)
        else:
            rows.append(cur)
            cur = [b]
    rows.append(cur)
    out = []
    for row in rows:
        for (y0, y1, x0, x1, k) in sorted(row, key=lambda b: b[2]):
            pad = max(4, int(0.02 * (y1 - y0)))
            ya, yb = max(0, y0 - pad), min(H, y1 + pad + 1)
            xa, xb = max(0, x0 - pad), min(W, x1 + pad + 1)
            hc = hard[ya:yb, xa:xb] & (lab[ya:yb, xa:xb] == k)
            # keep the object's parts (>= 2 % of the biggest); drop specks and labels
            l2, n2 = ndi.label(hc)
            if n2 > 1:
                s2 = ndi.sum(hc, l2, np.arange(1, n2 + 1))
                hc = np.isin(l2, 1 + np.nonzero(s2 >= 0.02 * s2.max())[0])
            # fill only small holes (dark spots that look like the background);
            # real through-holes such as a handle, a ring or a letter O stay open
            holes, nh = ndi.label(ndi.binary_fill_holes(hc) & ~hc)
            if nh:
                hs = ndi.sum(np.ones_like(hc), holes, np.arange(1, nh + 1))
                hc = hc | np.isin(holes, 1 + np.nonzero(hs < 0.004 * hc.sum())[0])
            keep_px = ndi.binary_dilation(hc, structure=disk(r_open + 1))
            mc = np.where(keep_px, np.maximum(soft[ya:yb, xa:xb], hc), 0.0)
            out.append((img[ya:yb, xa:xb], mc))
    return out


# =============================================================================
# 2 scale + 3 centre
# =============================================================================
def soft_extent(m, axis):
    """Sub-pixel first / last position (pixel-index coordinates) where the soft mask's
    profile along `axis` crosses 0.5."""
    prof = m.max(axis=axis)
    idx = np.nonzero(prof > 0.5)[0]
    a, b = idx[0], idx[-1]
    lo = a - 0.5
    if a > 0:
        lo = a - 1 + (0.5 - prof[a - 1]) / max(prof[a] - prof[a - 1], 1e-6)
    hi = b + 0.5
    if b < len(prof) - 1:
        hi = b + (prof[b] - 0.5) / max(prof[b] - prof[b + 1], 1e-6)
    return lo, hi


def normalise(views, Hn, pad):
    """Same object height Hn px for every view, top and base on the same rows, the
    outline centred. Sub-pixel extents and one exact scale per view (no rounding)."""
    geo = []
    for img, m in views:
        top, bot = soft_extent(m, 1)
        left, right = soft_extent(m, 0)
        f = Hn / max(bot - top, 1.0)
        geo.append((f, top, left, right))
    Wn = max((r - l) * f for f, _t, l, r in geo)
    Wc = int(Wn * 1.6) + 2 * pad
    Hc = Hn + 2 * pad
    out = []
    for (img, m), (f, top, left, right) in zip(views, geo):
        # canvas = f * (crop - [cx, top]) + [Wc/2 - 0.5, pad]  (pixel-index coordinates)
        cx = 0.5 * (left + right)
        M = np.float32([[f, 0, (Wc - 1) * 0.5 - f * cx], [0, f, pad - f * top]])
        sig = max(0.0, 0.5 / f - 0.5) if f < 1 else 0.0         # anti-alias before shrinking
        src_i = cv2.GaussianBlur(img, (0, 0), sig) if sig > 0 else img
        src_m = cv2.GaussianBlur(m.astype(np.float32), (0, 0), sig) if sig > 0 else m.astype(np.float32)
        I = cv2.warpAffine(src_i, M, (Wc, Hc), flags=cv2.INTER_LINEAR, borderValue=(0, 0, 0))
        Mk = cv2.warpAffine(src_m, M, (Wc, Hc), flags=cv2.INTER_LINEAR, borderValue=0)
        out.append({"img": I.astype(np.float32), "mask": Mk.astype(np.float32)})
    return out, Hc, Wc


def flip_sum(ma, mb):
    """Mirror pair: mask_b(x) = mask_a(S - x). Returns S (sub-pixel) and the overlap score."""
    W = ma.shape[1]
    fa = np.fft.rfft(ma, 2 * W, axis=1)
    fb = np.fft.rfft(mb, 2 * W, axis=1)
    corr = np.fft.irfft(fa * fb, 2 * W, axis=1).sum(0)        # sum_x a(x) b(S - x)
    s = int(np.argmax(corr))
    if 0 < s < len(corr) - 1:
        a, b, c = corr[s - 1], corr[s], corr[s + 1]
        den = a - 2 * b + c
        s = s + (0.5 * (a - c) / den if abs(den) > 1e-12 else 0.0)
    return float(s), float(corr.max() / max(np.sqrt((ma ** 2).sum() * (mb ** 2).sum()), 1e-9))


def mask_centre(m):
    """Middle of the outline's columns in pixel-index coordinates (same as flip_sum)."""
    cols = np.nonzero((m > 0.5).any(0))[0]
    return 0.5 * (cols[0] + cols[-1])


# =============================================================================
# hull maths (orthographic cameras turning about the vertical axis)
#   world X right (front view), Y away from the front camera, Z up
#   view at angle t: column u = X cos t - Y sin t (+ centre), depth w = X sin t + Y cos t
# =============================================================================
def sdf2d(m, up=2):
    """Signed distance (px, + outside) of a soft mask, sub-pixel via 2x supersampling."""
    big = cv2.resize(m.astype(np.float32), None, fx=up, fy=up, interpolation=cv2.INTER_LINEAR) > 0.5
    d = (ndi.distance_transform_edt(~big) - ndi.distance_transform_edt(big)) / up
    return cv2.resize(d.astype(np.float32), (m.shape[1], m.shape[0]), interpolation=cv2.INTER_AREA)


def grid_xy(n, half):
    g = (np.arange(n) - (n - 1) / 2.0) * (2.0 * half / n)
    X, Y = np.meshgrid(g, g)
    return X, Y, g


def constraint_groups(angles, pair_mean):
    """Views that constrain the same direction (a view and its mirror view) form one
    group when pair_mean is on; their outline distances are averaged."""
    groups, used = [], set()
    for k in range(len(angles)):
        if k in used:
            continue
        j = mirror_partner(angles, k) if pair_mean else -1
        if j >= 0 and j not in used:
            groups.append([k, j])
            used.update((k, j))
        else:
            groups.append([k])
            used.add(k)
    return groups


def hull_volume(sdfs, angles, centres, rows, X, Y, tol_views=0, outside=50.0, pair_mean=False, soft=0.0,
                grow=None):
    """vol[row, y, x] = signed distance-like field, < 0 inside the hull.
    pair_mean: a view and its mirror view count as one averaged outline (sheets drawn
    by AI rarely have identical front / back outlines; the strict cut loses material)."""
    W = sdfs[0].shape[1]
    cols = np.arange(W, dtype=np.float64)
    us = [X * math.cos(math.radians(a)) - Y * math.sin(math.radians(a)) for a in angles]
    groups = constraint_groups(angles, pair_mean)
    n = len(groups)
    vol = np.empty((len(rows),) + X.shape, np.float32)
    for i, r in enumerate(rows):
        st = np.empty((n,) + X.shape, np.float32)
        for gi, grp in enumerate(groups):
            acc = 0.0
            for k in grp:
                acc = acc + np.interp(us[k] + centres[k], cols, sdfs[k][r], left=outside, right=outside)
                if grow is not None:
                    acc = acc - grow[k]           # grown outline: an uncertain view must not cut
            st[gi] = acc / len(grp)
        if 0 < tol_views < n:
            st.sort(0)
            vol[i] = st[n - 1 - tol_views]
        elif soft > 0:                     # smooth max: rounds the edges between facets
            m = st.max(0)
            vol[i] = m + soft * np.log(np.exp((st - m[None]) / soft).sum(0))
        else:
            vol[i] = st.max(0)
    return vol


def _edge(v, comp, axis, first):
    """Sub-pixel outer edge of a component along one axis (zero crossing of v)."""
    vv = np.moveaxis(v, axis, -1)
    cc = np.moveaxis(comp, axis, -1)
    if not first:
        vv, cc = vv[..., ::-1], cc[..., ::-1]
    has = cc.any(-1)
    i = np.argmax(cc, -1)[has]
    lines = np.nonzero(has)[0]
    vin = vv[lines, i]
    vout = np.where(i > 0, vv[lines, np.maximum(i - 1, 0)], 1.0)
    t = np.clip(vout / np.maximum(vout - vin, 1e-6), 0.0, 1.0)      # crossing before pixel i
    pos = (i - 1 + t).min()
    n = cc.shape[-1]
    return pos if first else (n - 1) - pos


def round_cells(vol, n_exp):
    """With only two view directions every hull slice is a set of rectangles. Inscribe
    a superellipse |x/a|^n + |y/b|^n = 1 in each one (n = 2 ellipse, larger = boxier).
    The rectangle edges are found to sub-pixel accuracy, so rows do not step."""
    out = vol.copy()
    for i in range(vol.shape[0]):
        inside = vol[i] < 0
        if not inside.any():
            continue
        lab, nl = ndi.label(inside)
        for ci, sl in enumerate(ndi.find_objects(lab)):
            if sl is None:
                continue
            ys, xs = sl
            if ys.stop - ys.start < 3 or xs.stop - xs.start < 3:
                continue
            # one-pixel frame so the outside neighbour of every edge pixel is in the window
            y0, y1 = max(0, ys.start - 1), min(vol.shape[1], ys.stop + 1)
            x0, x1 = max(0, xs.start - 1), min(vol.shape[2], xs.stop + 1)
            v = vol[i, y0:y1, x0:x1]
            comp = lab[y0:y1, x0:x1] == ci + 1
            ex0, ex1 = _edge(v, comp, 1, True), _edge(v, comp, 1, False)
            ey0, ey1 = _edge(v, comp, 0, True), _edge(v, comp, 0, False)
            ax, ay = 0.5 * (ex1 - ex0), 0.5 * (ey1 - ey0)
            if ax < 1.0 or ay < 1.0:
                continue
            yy, xx = np.mgrid[0:y1 - y0, 0:x1 - x0].astype(np.float64)
            dx = np.abs(xx - 0.5 * (ex0 + ex1)) / ax
            dy = np.abs(yy - 0.5 * (ey0 + ey1)) / ay
            f = ((dx ** n_exp + dy ** n_exp) ** (1.0 / n_exp) - 1.0) * min(ax, ay)
            blk = out[i, y0:y1, x0:x1]
            blk[comp] = np.maximum(blk[comp], f[comp])
    return out


def directions(angles):
    """Number of distinct view directions (a view and its mirror view count once)."""
    return len(set(int(round(a % 180.0)) % 180 for a in angles))


def projections(inside, angles, centres, W, X, Y):
    """Outline of a boolean hull (rows, ny, nx) in each view -> list of (rows, W) bool.
    Every voxel is splatted over its full footprint, so the outline has no gaps."""
    g = X[0, 1] - X[0, 0]
    out = []
    for a, c in zip(angles, centres):
        ca, sa = math.cos(math.radians(a)), math.sin(math.radians(a))
        u = X * ca - Y * sa + c
        h = 0.5 * g * (abs(ca) + abs(sa))
        offs = np.linspace(-h, h, max(2, int(math.ceil(2 * h / 0.5)) + 1))
        proj = np.zeros((inside.shape[0], W), bool)
        for i in range(inside.shape[0]):
            sl = inside[i]
            if sl.any():
                cols = np.round(u[sl][:, None] + offs[None, :]).astype(int).ravel()
                proj[i, np.clip(cols, 0, W - 1)] = True
        out.append(proj)
    return out


def consistency(masks_lr, sdfs_lr, angles, centres, rows, X, Y, tol_views=0):
    """How much of every outline the hull fills (mean over views; 1 = all of it).
    A wrong angle or centre cuts the hull, so other outlines stop being filled."""
    vol = hull_volume(sdfs_lr, angles, centres, rows, X, Y, tol_views)
    inside = vol < 0
    if not inside.any():
        return 0.0
    W = sdfs_lr[0].shape[1]
    cov = []
    for proj, m in zip(projections(inside, angles, centres, W, X, Y), masks_lr):
        mm = m[rows] > 0.5
        cov.append((proj & mm).sum() / max(mm.sum(), 1))
    return float(np.mean(cov))


def nominal(a):
    return min(abs(((a - b) + 180) % 360 - 180) for b in (0, 90, 180, 270)) < 1e-6


def mirror_partner(angles, k):
    for j, a in enumerate(angles):
        if j != k and abs(((a - angles[k] - 180) + 180) % 360 - 180) < 1e-6:
            return j
    return -1


def calibrate(V, angles, refine, Hc, Wc, log):
    """Axis column of every view; refine the angles of oblique views (or all)."""
    n = len(V)
    masks = [v["mask"] for v in V]
    centres = [mask_centre(m) for m in masks]
    pairs = {}
    for k in range(n):
        j = mirror_partner(angles, k)
        if j > k:
            S, score = flip_sum(masks[k], masks[j])
            ok = score >= 0.92
            log("  mirror pair %3.0f / %3.0f deg: overlap %.3f%s" % (
                angles[k], angles[j], score, "" if ok else "  -> not mirror images, solved separately"))
            if ok:
                pairs[k] = (j, S)
                pairs[j] = (k, S)
    # gauge: the 0 and 90 deg views keep their own centres; their mirror views follow
    for k, (j, S) in list(pairs.items()):
        if k < j and nominal(angles[k]):
            centres[j] = S - centres[k]
    # low-res copies for the search
    f = 128.0 / max(Hc, Wc)
    small = lambda m: cv2.resize(m, (int(Wc * f), int(Hc * f)), interpolation=cv2.INTER_AREA)
    m_lr = [small(m) for m in masks]
    s_lr = [sdf2d(m) for m in m_lr]
    rows = np.arange(0, m_lr[0].shape[0], 2)
    X, Y, _ = grid_xy(96, 0.5 * m_lr[0].shape[1])
    c_lr = lambda cs: [c * f for c in cs]
    ang = list(angles)
    free = [k for k in range(n) if (refine == "all" and k > 0) or (refine == "oblique" and not nominal(angles[k]))]
    groups, seen = [], set()
    for k in free:
        if k in seen:
            continue
        j, S = pairs.get(k, (-1, None))
        groups.append((k, j, S))
        seen.update([k, j])

    def apply(a2, c2, grp, da, c):
        k, j, S = grp
        a2[k] = angles[k] + da
        c2[k] = c
        if j >= 0:
            a2[j] = angles[j] + da
            c2[j] = S - c

    # Outlines often fit equally well over a range of angles (a round object looks the
    # same from 40 and 45 deg). Score every angle (best centre each), then take the middle
    # of the best-scoring plateau, not its noisy maximum. Coarse pass, then 1 deg steps.
    def scan(grp, steps_a, c_steps):
        best_c, best_s = [], []
        for da in steps_a:
            sc_c = []
            for c in c_steps:
                a2, c2 = list(ang), list(centres)
                apply(a2, c2, grp, da, c)
                sc_c.append(consistency(m_lr, s_lr, a2, c_lr(c2), rows, X, Y))
            sc_c = np.array(sc_c)
            best_s.append(sc_c.max())
            best_c.append(float(np.mean(c_steps[sc_c >= sc_c.max() - 1e-4])))
        best_s = np.convolve(np.pad(best_s, 1, mode="edge"), np.ones(3) / 3.0, mode="valid")
        tol = max(5e-4, 0.1 * (best_s.max() - best_s.min()))
        lo = hi = int(np.argmax(best_s))
        while lo > 0 and best_s[lo - 1] >= best_s.max() - tol:
            lo -= 1
        while hi < len(best_s) - 1 and best_s[hi + 1] >= best_s.max() - tol:
            hi += 1
        mid = (lo + hi) // 2
        zero = int(np.argmin(np.abs(steps_a)))
        if lo <= zero <= hi and abs(steps_a[zero]) < 1e-9:
            mid = zero                     # the drawn angle fits as well as any: keep it
        return steps_a[mid], best_c[mid], steps_a[lo], steps_a[hi], best_s[mid]

    slack = [0.0] * n
    for grp in groups:
        k, j, _S = grp
        c_ref = centres[k]
        da, c, lo, hi, _sc = scan(grp, np.arange(-25.0, 25.01, 2.5), c_ref + np.arange(-0.12, 0.1201, 0.02) * Wc)
        fine_a = np.arange(max(-25.0, lo - 2.5), min(25.0, hi + 2.5) + 0.01, 1.0)
        da, c, lo, hi, sc = scan(grp, fine_a, c + np.arange(-0.03, 0.0301, 0.005) * Wc)
        # last pass: the centre alone, fine steps. Outlines fit equally well over a band of
        # centres; take its middle, and keep its half width as this view's uncertainty
        c_steps = c + np.arange(-0.025, 0.02501, 0.0025) * Wc
        sc_c = []
        for cc in c_steps:
            a2, c2 = list(ang), list(centres)
            apply(a2, c2, grp, da, cc)
            sc_c.append(consistency(m_lr, s_lr, a2, c_lr(c2), rows, X, Y))
        sc_c = np.array(sc_c)
        top = c_steps[sc_c >= sc_c.max() - 1e-4]
        c = 0.5 * (top.min() + top.max())
        apply(ang, centres, grp, float(da), c)
        unc = min(0.5 * (top.max() - top.min()) + 0.5 / f, 0.03 * Wc)    # + half a search pixel
        for g in (k, j):
            if g >= 0:
                slack[g] = unc
        log("  view %d%s: angle %+.1f deg -> %.1f (outlines fit from %+.0f to %+.0f deg), "
            "centre +/- %.1f px, fill %.4f" % (k + 1, " + mirror view %d" % (j + 1) if j >= 0 else "",
                                              da, ang[k], lo, hi, unc, sc))
    total = consistency(m_lr, s_lr, ang, c_lr(centres), rows, X, Y)
    return ang, centres, total, slack


# =============================================================================
# 5 order: which way round the views go (colour agreement between neighbours)
# =============================================================================
def surface_points(vol, rows, X, Y):
    """Points (x, y, image row) + outward normals on the zero level of vol[row, y, x]."""
    pv = np.pad(vol, 1, constant_values=50.0)
    v = measure.marching_cubes(pv, 0.0)[0]
    grads = np.gradient(pv)                                  # vol grows outward -> gradient = outward
    gn = np.stack([ndi.map_coordinates(grads[i], v.T, order=1) for i in (2, 1, 0)], 1)
    g = X[0, 1] - X[0, 0]
    dr = float(rows[1] - rows[0]) if len(rows) > 1 else 1.0
    gn[:, 0] /= g
    gn[:, 1] /= g
    gn[:, 2] /= dr
    nrm = gn / np.maximum(np.linalg.norm(gn, axis=1, keepdims=True), 1e-9)
    pts = np.stack([X[0, 0] + (v[:, 2] - 1) * g, Y[0, 0] + (v[:, 1] - 1) * g, rows[0] + (v[:, 0] - 1) * dr], 1)
    return pts, nrm


def view_channels(V, band=None):
    """Luminance + two chromaticity channels per view (chroma survives a light that
    moves with the camera). band = (s1, s2) px: difference of Gaussians, else raw."""
    chans = []
    for v in V:
        im = v["img"]
        s3 = im.sum(-1) + 1e-3
        ch = [0.299 * im[..., 0] + 0.587 * im[..., 1] + 0.114 * im[..., 2],
              im[..., 0] / s3, im[..., 1] / s3]
        if band:
            m = (v["mask"] > 0.5).astype(np.float32)
            out = []
            for c in ch:
                lo = []
                for sg in band:                      # normalised blur: no halo from the background
                    lo.append(ndi.gaussian_filter(c * m, sg) / np.maximum(ndi.gaussian_filter(m, sg), 1e-3))
                out.append(lo[0] - lo[1])
            ch = out
        chans.append(ch)
    return chans


def colour_agreement(V, angles, centres, pts, nrm, band=None):
    """Mean NCC between neighbouring views over hull points both see."""
    chans = view_channels(V, band)
    H, W = chans[0][0].shape
    vis, samp = [], []
    for a, c, ch in zip(angles, centres, chans):
        t = math.radians(a)
        d = np.array([math.sin(t), math.cos(t), 0.0])             # camera looks along +d
        u = pts[:, 0] * math.cos(t) - pts[:, 1] * math.sin(t) + c
        w = pts @ d
        r = pts[:, 2]
        face = -(nrm @ d)
        ui = np.clip(np.round(u).astype(int), 0, W - 1)
        ri = np.clip(np.round(r).astype(int), 0, H - 1)
        zb = np.full((H, W), np.inf)
        np.minimum.at(zb, (ri, ui), w)
        zb = ndi.minimum_filter(zb, 3)
        ok = (face > 0.35) & (w <= zb[ri, ui] + 2.0)
        vis.append(ok)
        samp.append([ndi.map_coordinates(L, [r, u], order=1, mode="nearest") for L in ch])
    scores, weights = [], []
    n = len(V)
    for k in range(n):
        for j in range(k + 1, n):
            gap = abs(((angles[k] - angles[j]) + 180) % 360 - 180)
            if gap > 100:
                continue
            both = vis[k] & vis[j]
            if both.sum() < 100:
                continue
            ncc = []
            for c in range(3):
                a, b = samp[k][c][both], samp[j][c][both]
                if a.std() < 0.004 or b.std() < 0.004:      # flat channel (one-colour object)
                    continue
                a = (a - a.mean()) / a.std()
                b = (b - b.mean()) / b.std()
                ncc.append(float((a * b).mean()))
            if ncc:
                scores.append(float(np.mean(ncc)))
                weights.append(both.sum())
    if not scores:
        return 0.0
    return float(np.average(scores, weights=weights))


# =============================================================================
# 7 mesh + files
# =============================================================================
def largest_solid(vol):
    lab, n = ndi.label(vol < 0)
    if n == 0:
        sys.exit("empty hull - the outlines do not agree (check --views / --angles / --order)")
    sizes = ndi.sum(np.ones(vol.shape, np.float32), lab, np.arange(1, n + 1))
    solid = lab == (1 + int(np.argmax(sizes)))
    filled = ndi.binary_fill_holes(solid)
    return np.where(solid, vol, np.where(filled, -np.abs(vol) - 0.05, np.maximum(vol, 0.05))).astype(np.float32)


def write_stl(path, verts, faces, header=b"Styro3D views_to_3d, units mm"):
    tri = verts[faces]
    n = np.cross(tri[:, 1] - tri[:, 0], tri[:, 2] - tri[:, 0])
    n /= np.maximum(np.linalg.norm(n, axis=1, keepdims=True), 1e-12)
    rec = np.zeros(len(faces), dtype=[("n", "<f4", 3), ("v", "<f4", (3, 3)), ("a", "<u2")])
    rec["n"] = n
    rec["v"] = tri
    with open(path, "wb") as fh:
        fh.write(header[:80].ljust(80, b" "))
        fh.write(struct.pack("<I", len(faces)))
        fh.write(rec.tobytes())


def sample_volume(path, pts_mm):
    """Hull value (px, < 0 inside) at points in output mm coordinates, from --save-volume."""
    d = np.load(path)
    q = pts_mm - d["shift"][None]
    k = q[:, 0] / d["mm_px"]
    j = q[:, 1] / d["mm_px"]
    zr = q[:, 2] / d["mm_px"]
    ix = (k - d["x0"]) / d["g"] + 2
    iy = (j - d["y0"]) / d["g"] + 2
    ir = (int(d["hc"]) - 1 - zr) + 2
    return ndi.map_coordinates(d["vol"], [ir, iy, ix], order=1, mode="constant", cval=50.0)


def mesh_stats(verts, faces):
    e = np.sort(np.concatenate([faces[:, [0, 1]], faces[:, [1, 2]], faces[:, [2, 0]]]), 1)
    _, cnt = np.unique(e, axis=0, return_counts=True)
    tri = verts[faces]
    vol = np.einsum("ij,ij->i", tri[:, 0], np.cross(tri[:, 1], tri[:, 2])).sum() / 6.0
    return {"closed": bool((cnt == 2).all()), "open_edges": int((cnt == 1).sum()),
            "nonmanifold_edges": int((cnt > 2).sum()), "volume_mm3": float(vol)}


def shade_depth(vol, angle, centre, rows_idx, X, Y, W, light=(-0.4, 0.5, 0.75)):
    """Orthographic render of the hull from one view (for the check sheet)."""
    t = math.radians(angle)
    g = X[0, 1] - X[0, 0]
    half = -X[0, 0]
    us = np.arange(W) - centre
    ws = np.arange(-half * 1.5, half * 1.5, g)
    U, Wd = np.meshgrid(us, ws, indexing="ij")
    Xs = U * math.cos(t) + Wd * math.sin(t)
    Ys = -U * math.sin(t) + Wd * math.cos(t)
    xi = (Xs - X[0, 0]) / g
    yi = (Ys - Y[0, 0]) / g
    depth = np.full((len(rows_idx), W), np.nan)
    for i in range(len(rows_idx)):
        sl = vol[i]
        if sl.min() >= 0:
            continue
        ph = ndi.map_coordinates(sl, [yi.ravel(), xi.ravel()], order=1, mode="constant", cval=5.0).reshape(U.shape)
        ins = ph < 0
        has = ins.any(1)
        k = np.argmax(ins, 1)
        k0 = np.maximum(k - 1, 0)
        p0, p1 = ph[np.arange(W), k0], ph[np.arange(W), k]
        tt = np.clip(p0 / np.maximum(p0 - p1, 1e-6), 0, 1)
        d = ws[k0] + tt * (ws[k] - ws[k0])
        d[~has] = np.nan
        depth[i] = d
    m = ~np.isnan(depth)
    dd = np.where(m, depth, np.nanmax(depth) if m.any() else 0)
    gx = np.gradient(dd, axis=1)
    gy = np.gradient(dd, axis=0)
    nn = np.stack([gx, -gy, np.ones_like(gx)], -1)
    nn /= np.linalg.norm(nn, axis=-1, keepdims=True)
    l = np.array(light, float)
    l /= np.linalg.norm(l)
    return np.where(m, 0.15 + 0.85 * np.clip(nn @ l, 0, 1), 0.0), m


# =============================================================================
def main(argv=None):
    ap = argparse.ArgumentParser(description="Views sheet -> closed STL (visual hull), any object.")
    ap.add_argument("sheet", nargs="?", help="sheet image with all views")
    ap.add_argument("--images", nargs="+", help="separate view images instead of a sheet")
    ap.add_argument("--views", type=int, default=0, help="number of views on the sheet (default 4)")
    ap.add_argument("--angles", default="", help="camera angle per view in degrees, reading order")
    ap.add_argument("--order", default="auto", choices=["auto", "as-is", "reverse"],
                    help="turn direction; auto = colour agreement test")
    ap.add_argument("--refine", default="oblique", choices=["none", "oblique", "all"],
                    help="refine view angles by outline consistency")
    ap.add_argument("--height-mm", type=float, default=1000.0, help="real height of the object")
    ap.add_argument("--res", type=int, default=256, help="voxels over the height")
    ap.add_argument("--pairs", default="mean", choices=["mean", "strict"],
                    help="a view and its mirror view: average their outlines (mean) or cut by both")
    ap.add_argument("--round", default="auto",
                    help="superellipse exponent for 2-direction sheets (4 views): auto = 2.5, off, or a number")
    ap.add_argument("--soft", default="0",
                    help="round the edges between hull facets, px at --res (0 = off; tests: off is more accurate)")
    ap.add_argument("--tolerance", type=int, default=0,
                    help="outlines allowed to disagree per voxel (default 0)")
    ap.add_argument("--smooth", type=float, default=1.0, help="smoothing in voxels before meshing")
    ap.add_argument("--bg", default="auto", help="background: auto / white / black / #rrggbb")
    ap.add_argument("--out", default="", help="output name / folder (default: next to the input)")
    ap.add_argument("--save-volume", action="store_true", help="also save the hull volume (.npz) for tests")
    a = ap.parse_args(argv)
    t0 = time.time()
    msgs = []

    def log(s):
        msgs.append(s)
        print(s)

    if a.images:
        views = []
        for p in a.images:
            img, al = load_rgb(p)
            views.extend(split_sheet(img, al, 1, parse_bg(a.bg)))
        src = a.images[0]
    elif a.sheet:
        img, al = load_rgb(a.sheet)
        n = a.views or 4
        views = split_sheet(img, al, n, parse_bg(a.bg))
        src = a.sheet
    else:
        ap.error("give a sheet image or --images")
    n = len(views)
    if a.angles:
        angles = [float(x) for x in a.angles.replace(";", ",").split(",") if x.strip()]
        if len(angles) != n:
            sys.exit("--angles has %d values for %d views" % (len(angles), n))
    else:
        angles = [360.0 * k / n for k in range(n)]
    tol_views = max(0, a.tolerance)
    pair_mean = a.pairs == "mean"
    if a.round == "auto":
        round_n = 2.5 if directions(angles) <= 2 else 0.0
    elif a.round == "off":
        round_n = 0.0
    else:
        round_n = float(a.round)
    soft_px = max(0.0, float(a.soft))
    base = a.out or os.path.splitext(src)[0] + "_3d"
    os.makedirs(base, exist_ok=True)
    name = os.path.basename(os.path.normpath(base))
    log("views_to_3d v%s | %d views | angles %s | height %.0f mm | pairs %s | round %s | soft %s" % (
        VERSION, n, ", ".join("%.0f" % x for x in angles), a.height_mm, a.pairs,
        ("%.1f" % round_n) if round_n else "off", ("%.1f px" % soft_px) if soft_px else "off"))

    Hn, pad = a.res, max(4, a.res // 16)
    V, Hc, Wc = normalise(views, Hn, pad)
    mm_px = a.height_mm / float(Hn)

    # 3 + 4: centres and angles. The reverse turn direction needs no own calibration:
    # the front/back mirror of the object explains it exactly (same centres, angles negated)
    sign0 = -1.0 if a.order == "reverse" else 1.0
    log("calibration:")
    ang, cen, cons, slack = calibrate(V, [(sign0 * x) % 360.0 for x in angles], a.refine, Hc, Wc, log)
    hyps = [["reverse" if sign0 < 0 else "as-is", ang, cen, cons, 0.0]]
    if a.order == "auto":
        hyps.append(["reverse", [(-x) % 360.0 for x in ang], list(cen), cons, 0.0])
    # 5: colour agreement decides the direction
    rows = np.arange(Hc)
    sdfs = [sdf2d(v["mask"]) for v in V]

    def grid_for(cen, step):
        # half width = farthest outline column from the axis in any view (+ margin)
        reach = 0.0
        for v, c in zip(V, cen):
            cols = np.nonzero((v["mask"] > 0.5).any(0))[0]
            reach = max(reach, c - cols[0], cols[-1] + 1 - c)
        half = reach + 2.0 * step
        return grid_xy(int(math.ceil(2 * half / step)), half)

    def build(ang_, cen_, rows_, X_, Y_):
        vol_ = hull_volume(sdfs, ang_, cen_, rows_, X_, Y_, tol_views, pair_mean=pair_mean, soft=soft_px,
                           grow=slack)
        return round_cells(vol_, round_n) if round_n else vol_

    if len(hyps) > 1:
        rows_l = np.arange(0, Hc, 2)
        band = (0.006 * Hc, 0.03 * Hc)
        for h in hyps:
            Xl, Yl, _ = grid_for(h[2], 2.0)
            vol_l = build(h[1], h[2], rows_l, Xl, Yl)
            if (vol_l < 0).sum() < 50:
                h[4] = -1.0
                continue
            pts, nrm = surface_points(vol_l, rows_l, Xl, Yl)
            raw = colour_agreement(V, h[1], h[2], pts, nrm)
            fine = colour_agreement(V, h[1], h[2], pts, nrm, band)
            h[4] = raw + fine
            log("order %-7s: outline consistency %.4f, colour agreement %.3f (raw %.3f, detail %.3f)" % (
                h[0], h[3], h[4], raw, fine))
        # the outline test cannot tell the two apart (the front/back mirror of the object
        # explains the reversed order exactly), so colour decides
        hyps.sort(key=lambda h: h[4], reverse=True)
    label, ang, cen, cons, col = hyps[0]
    log("using order %s, angles %s" % (label, ", ".join("%.1f" % x for x in ang)))

    # 6 hull at full resolution (1 px voxels)
    X, Y, _ = grid_for(cen, 1.0)
    vol = largest_solid(build(ang, cen, rows, X, Y))
    if a.smooth > 0:
        vol = ndi.gaussian_filter(vol, a.smooth)
    vol = np.pad(vol, 2, constant_values=50.0)
    verts, faces, _n, _v = measure.marching_cubes(vol, 0.0)
    g = X[0, 1] - X[0, 0]
    # index -> world mm: x = X0 + (i-2) g, y = Y0 + (j-2) g, z = (Hc - 1 - row) ; then mm
    P = np.stack([X[0, 0] + (verts[:, 2] - 2) * g,
                  Y[0, 0] + (verts[:, 1] - 2) * g,
                  (Hc - 1 - (verts[:, 0] - 2))], 1) * mm_px
    shift = np.array([-0.5 * (P[:, 0].min() + P[:, 0].max()), -0.5 * (P[:, 1].min() + P[:, 1].max()),
                      -P[:, 2].min()])
    P += shift
    if a.save_volume:      # world mm p -> index: x=(p+shift)/mm_px ... see sample_volume()
        np.savez_compressed(os.path.join(base, name + "_volume.npz"), vol=vol, x0=X[0, 0], y0=Y[0, 0], g=g,
                            hc=Hc, mm_px=mm_px, shift=shift)
    st = mesh_stats(P, faces)
    if st["volume_mm3"] < 0:
        faces = faces[:, ::-1]
        st = mesh_stats(P, faces)
    stl = os.path.join(base, name + "_mm.stl")
    write_stl(stl, P.astype(np.float32), faces)
    size = P.max(0) - P.min(0)
    log("mesh: %d vertices, %d triangles, closed %s, open edges %d, non-manifold edges %d" % (
        len(P), len(faces), st["closed"], st["open_edges"], st["nonmanifold_edges"]))
    log("size mm: X %.0f  Y %.0f  Z %.0f | volume %.2f L" % (size[0], size[1], size[2], st["volume_mm3"] * 1e-6))
    log("STL: " + stl)

    # 8 check sheet: input | outline overlap | model render, per view
    inside = vol[2:-2, 2:-2, 2:-2] < 0
    projs = projections(inside, ang, cen, Wc, X, Y)
    tiles, ious = [], []
    for k, v in enumerate(V):
        m = v["mask"] > 0.5
        pr = projs[k]
        iou = (pr & m).sum() / max((pr | m).sum(), 1)
        ious.append(iou)
        ov = np.ones((Hc, Wc, 3), np.float32)
        ov[m & pr] = (0.55, 0.55, 0.55)
        ov[m & ~pr] = (0.95, 0.2, 0.2)                     # outline the model misses
        ov[~m & pr] = (0.2, 0.45, 0.95)                    # model outside the outline
        sh, hit = shade_depth(vol[2:-2, 2:-2, 2:-2], ang[k], cen[k], rows, X, Y, Wc)
        rd = np.repeat(sh[..., None], 3, -1).astype(np.float32)
        col_img = np.where(v["mask"][..., None] > 0.05, v["img"], 1.0)
        tile = np.vstack([col_img, ov, np.where(hit[..., None], rd, 1.0)])
        tile = np.ascontiguousarray((np.clip(tile[..., ::-1], 0, 1) * 255).astype(np.uint8))
        cv2.putText(tile, "%d: %.1f deg  IoU %.3f" % (k + 1, ang[k], iou), (6, 18),
                    cv2.FONT_HERSHEY_SIMPLEX, 0.5, (0, 0, 0), 1, cv2.LINE_AA)
        tiles.append(tile)
    sheet = np.hstack(tiles)
    scale = min(1.0, 2400.0 / sheet.shape[1])
    sheet = cv2.resize(sheet, None, fx=scale, fy=scale, interpolation=cv2.INTER_AREA)
    chk = os.path.join(base, name + "_check.png")
    cv2.imwrite(chk, sheet)
    log("outline IoU per view: " + ", ".join("%.3f" % x for x in ious) + "  (1 = perfect)")
    log("check sheet: %s  (rows: input | grey = match, red = missed, blue = extra | model)" % chk)
    info = {"version": VERSION, "views": n, "angles_deg": ang, "centres_px": cen, "order": label,
            "pairs": a.pairs, "round": round_n, "soft_px": soft_px, "centre_uncertainty_px": slack,
            "outline_consistency": cons, "colour_agreement": col, "iou": ious, "mm_per_px": mm_px,
            "size_mm": size.tolist(), "mesh": st, "tolerance_views": tol_views, "seconds": time.time() - t0}
    json.dump(info, open(os.path.join(base, name + "_info.json"), "w"), indent=1)
    with open(os.path.join(base, name + "_log.txt"), "w") as fh:
        fh.write("\n".join(msgs) + "\n")
    log("done in %.0f s" % (time.time() - t0))
    return info


if __name__ == "__main__":
    main()
