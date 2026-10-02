"""Pure-python codec for the bust radius grid (identical maths in the Rhino script)."""
import math, struct, zlib, base64
DMAX = 12.0
def cubic_w(t):
    # Catmull-Rom weights for offsets -1, 0, 1, 2
    t2 = t * t; t3 = t2 * t
    return (-0.5 * t3 + t2 - 0.5 * t, 1.5 * t3 - 2.5 * t2 + 1.0, -1.5 * t3 + 2.0 * t2 + 0.5 * t, 0.5 * t3 - 0.5 * t2)
def upsample(low, nlr, nlu, step, nr, nu):
    """low: flat list (nlr x nlu), rows clamped, columns periodic. returns flat list nr x nu."""
    # columns first (periodic), then rows (clamped)
    tmp = [0.0] * (nlr * nu)
    for j in range(nu):
        x = j / float(step); j0 = int(math.floor(x)); t = x - j0
        w0, w1, w2, w3 = cubic_w(t)
        c0, c1, c2, c3 = (j0 - 1) % nlu, j0 % nlu, (j0 + 1) % nlu, (j0 + 2) % nlu
        for i in range(nlr):
            b = i * nlu
            tmp[i * nu + j] = w0 * low[b + c0] + w1 * low[b + c1] + w2 * low[b + c2] + w3 * low[b + c3]
    out = [0.0] * (nr * nu)
    for i in range(nr):
        y = i / float(step); i0 = int(math.floor(y)); t = y - i0
        w0, w1, w2, w3 = cubic_w(t)
        r0, r1, r2, r3 = [min(max(k, 0), nlr - 1) for k in (i0 - 1, i0, i0 + 1, i0 + 2)]
        a0, a1, a2, a3 = r0 * nu, r1 * nu, r2 * nu, r3 * nu; o = i * nu
        for j in range(nu):
            out[o + j] = w0 * tmp[a0 + j] + w1 * tmp[a1 + j] + w2 * tmp[a2 + j] + w3 * tmp[a3 + j]
    return out
def decode_detail(q):
    return [(1.0 if v >= 0 else -1.0) * (abs(v) / 127.0) ** 2 * DMAX for v in q]
