# -*- coding: utf-8 -*-
"""Small GIF writer (numpy + Qt only, no Pillow / ffmpeg needed).
Global median-cut palette (no colour flicker between frames), changed-area-only frames with transparency,
exact real-time timing (centisecond durations spread so the total length is right)."""
import struct
import numpy as np


# ------------------------------------------------------------------------------------------- load
def load_png(path):
    from PySide6 import QtGui
    img = QtGui.QImage(path)
    if img.isNull():
        raise IOError("cannot read " + path)
    img = img.convertToFormat(QtGui.QImage.Format_RGB888)
    w, h, bpl = img.width(), img.height(), img.bytesPerLine()
    buf = np.frombuffer(img.constBits(), dtype=np.uint8, count=bpl * h).reshape(h, bpl)
    return buf[:, :w * 3].reshape(h, w, 3).copy()


# ------------------------------------------------------------------------------------------- palette
def median_cut(pixels, n):
    """pixels: (N,3) uint8 -> (n,3) palette."""
    boxes = [pixels]
    while len(boxes) < n:
        # split the box with the largest (range * count)
        best, score = -1, -1
        for i, b in enumerate(boxes):
            if len(b) < 2:
                continue
            rng = b.max(0).astype(int) - b.min(0)
            s = rng.max() * len(b)
            if s > score:
                best, score = i, s
        if best < 0 or score == 0:
            break
        b = boxes.pop(best)
        ch = int(np.argmax(b.max(0).astype(int) - b.min(0)))
        b = b[np.argsort(b[:, ch], kind="stable")]
        m = len(b) // 2
        boxes += [b[:m], b[m:]]
    pal = np.array([b.mean(0) for b in boxes if len(b)], dtype=np.float32)
    return np.clip(np.round(pal), 0, 255).astype(np.uint8)


def build_lut(pal, bits=6):
    """Nearest palette index for every colour quantised to `bits` per channel."""
    q = (np.arange(1 << bits) << (8 - bits)) + (1 << (7 - bits))
    r, g, b = np.meshgrid(q, q, q, indexing="ij")
    cols = np.stack([r.ravel(), g.ravel(), b.ravel()], 1).astype(np.int32)
    p = pal.astype(np.int32)
    lut = np.empty(len(cols), dtype=np.uint8)
    step = 32768
    for s in range(0, len(cols), step):
        c = cols[s:s + step]
        d = ((c[:, None, :] - p[None, :, :]) ** 2).sum(2)
        lut[s:s + step] = d.argmin(1)
    return lut


def map_frame(rgb, lut, bits=6):
    x = (rgb >> (8 - bits)).astype(np.int32)
    return lut[(x[..., 0] << (2 * bits)) | (x[..., 1] << bits) | x[..., 2]]


# ------------------------------------------------------------------------------------------- LZW
def lzw(indices, min_code_size):
    """GIF LZW of a flat uint8 index array -> bytes (sub-blocked)."""
    clear = 1 << min_code_size
    eoi = clear + 1
    out = bytearray()
    bitbuf = 0
    nbits = 0
    code_size = min_code_size + 1
    table = {}
    next_code = eoi + 1

    def emit(code):
        nonlocal bitbuf, nbits
        bitbuf |= code << nbits
        nbits += code_size
        while nbits >= 8:
            out.append(bitbuf & 0xFF)
            bitbuf >>= 8
            nbits -= 8

    emit(clear)
    data = indices.tobytes()
    if not data:
        emit(eoi)
    else:
        prefix = data[0]
        get = table.get
        for c in data[1:]:
            key = (prefix << 8) | c
            nxt = get(key)
            if nxt is not None:
                prefix = nxt
                continue
            emit(prefix)
            if next_code < 4096:
                table[key] = next_code
                next_code += 1
                if next_code > (1 << code_size) and code_size < 12:
                    code_size += 1
            else:
                emit(clear)
                table.clear()
                get = table.get
                next_code = eoi + 1
                code_size = min_code_size + 1
            prefix = c
        emit(prefix)
        emit(eoi)
    if nbits:
        out.append(bitbuf & 0xFF)
    blocks = bytearray()
    for i in range(0, len(out), 255):
        chunk = out[i:i + 255]
        blocks.append(len(chunk))
        blocks += chunk
    blocks.append(0)
    return bytes(blocks)


# ------------------------------------------------------------------------------------------- write
def frame_durations_cs(n, fps):
    t = [int(round(k * 100.0 / fps)) for k in range(n + 1)]
    return [max(2, t[k + 1] - t[k]) for k in range(n)]


def write_gif(frames, out, fps, loop=0, progress=None):
    """frames: list of (H,W,3) uint8 arrays (same size)."""
    return _write(len(frames), lambda i: frames[i], out, fps, loop, progress)


def _write(count, get, out, fps, loop=0, progress=None):
    """Streaming writer: get(i) -> (H,W,3) uint8; only a few frames are held in memory at a time."""
    first = get(0)
    h, w = first.shape[:2]

    def fit(f):
        return f if f.shape[:2] == (h, w) else np.ascontiguousarray(f[:h, :w])
    # global palette from up to 24 evenly spaced frames; index 255 kept for transparency
    rng = np.random.default_rng(0)
    picks = sorted(set(int(round(i * (count - 1) / max(1, min(24, count) - 1))) for i in range(min(24, count))))
    sample = []
    for i in picks:
        flat = fit(get(i)).reshape(-1, 3)
        sample.append(flat[rng.integers(0, len(flat), min(20000, len(flat)))])
    pal = median_cut(np.concatenate(sample), 255)
    lut = build_lut(pal)
    palette = np.zeros((256, 3), np.uint8)
    palette[:len(pal)] = pal
    TRANS = 255
    durs = frame_durations_cs(count, fps)

    with open(out, "wb") as fp:
        fp.write(b"GIF89a")
        fp.write(struct.pack("<HHBBB", w, h, 0xF7, 0, 0))
        fp.write(palette.tobytes())
        fp.write(b"\x21\xFF\x0BNETSCAPE2.0\x03\x01" + struct.pack("<H", loop) + b"\x00")
        prev = None
        for i in range(count):
            idx = map_frame(fit(first if i == 0 else get(i)), lut)
            if prev is None:
                x0, y0, x1, y1 = 0, 0, w, h
                sub = idx
                transp = False
            else:
                diff = idx != prev
                if not diff.any():
                    x0, y0, x1, y1 = 0, 0, 1, 1
                    sub = np.array([[TRANS]], np.uint8)
                    transp = True
                else:
                    ys = np.where(diff.any(1))[0]
                    xs = np.where(diff.any(0))[0]
                    y0, y1, x0, x1 = ys[0], ys[-1] + 1, xs[0], xs[-1] + 1
                    sub = idx[y0:y1, x0:x1].copy()
                    sub[~diff[y0:y1, x0:x1]] = TRANS
                    transp = True
            fp.write(struct.pack("<BBBBHBB", 0x21, 0xF9, 4, (1 << 2) | (1 if transp else 0), durs[i], TRANS, 0))
            fp.write(struct.pack("<BHHHHB", 0x2C, int(x0), int(y0), int(x1 - x0), int(y1 - y0), 0))
            fp.write(b"\x08")
            fp.write(lzw(np.ascontiguousarray(sub, np.uint8).ravel(), 8))
            prev = idx
            if progress:
                progress(i + 1, count)
        fp.write(b"\x3B")
    return {"frames": count, "size": (w, h), "durations_cs": sum(durs)}


def pngs_to_gif(paths, out, fps, loop=0, progress=None):
    return _write(len(paths), lambda i: load_png(paths[i]), out, fps, loop, progress)
