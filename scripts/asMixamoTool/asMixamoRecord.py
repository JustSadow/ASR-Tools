# -*- coding: utf-8 -*-
"""Viewport recording (playblast) for asMixamoTool: MP4 / GIF / PNG sequence, any frame rate, with or without
joints and controls. Runs in GUI Maya (a playblast needs a viewport).

MP4: Maya's own QuickTime H.264 playblast, then the .mov header is turned into an .mp4 and its time scale set to the
chosen frame rate (no re-encoding). GIF: PNG frames encoded by asMixamoGif (in the background worker)."""
import glob
import os
import shutil
import struct
import tempfile

import maya.cmds as cmds
import maya.mel as mel

FORMATS = ("mp4", "gif", "png")
CONTROL_FLAGS = ("nurbsCurves", "locators", "ikHandles", "handles", "dimensions")   # dimensions = AS pole-vector annotation arrows


def log(cb, msg):
    if cb:
        cb(msg)
    else:
        print(msg)


def scene_fps():
    try:
        return float(mel.eval("currentTimeUnitToFPS()"))
    except Exception:
        return 30.0


def active_panel():
    p = cmds.getPanel(withFocus=True)
    if p and cmds.getPanel(typeOf=p) == "modelPanel":
        return p
    vis = [x for x in (cmds.getPanel(visiblePanels=True) or []) if cmds.getPanel(typeOf=x) == "modelPanel"]
    return vis[0] if vis else "modelPanel4"


def panel_size(panel):
    try:
        import maya.OpenMayaUI as omui
        from shiboken6 import wrapInstance
        from PySide6 import QtWidgets
        w = wrapInstance(int(omui.MQtUtil.findControl(panel)), QtWidgets.QWidget)
        d = w.devicePixelRatioF()
        return int(w.width() * d), int(w.height() * d)
    except Exception:
        return 1280, 720


def panel_camera(panel):
    """Camera shape of a model panel (None if it can't be found)."""
    try:
        cam = cmds.modelPanel(panel, q=True, camera=True)
    except Exception:
        return None
    if cam and cmds.nodeType(cam) == "transform":
        cam = (cmds.listRelatives(cam, shapes=True, type="camera") or [None])[0]
    return cam if cam and cmds.objExists(cam) else None


GATE_CAM = ("displayResolution", "displayGateMask", "overscan")
GATE_RES = ("width", "height", "deviceAspectRatio", "pixelAspect")


def show_gate(size=None, panel=None):
    """Draw the recording frame in the viewport: the camera's Resolution Gate with the recording's aspect ratio
    (shaded outside). Changes the scene's render resolution and the camera's gate display; returns the old values
    for hide_gate()."""
    panel = panel or active_panel()
    cam = panel_camera(panel)
    if not cam:
        raise RuntimeError(u"找不到 %s 的攝影機" % panel)
    w, h = size if size else panel_size(panel)
    old = {"cam": cam, "camv": {}, "resv": {}}
    for a in GATE_CAM:
        old["camv"][a] = cmds.getAttr(cam + "." + a)
    for a in GATE_RES:
        old["resv"][a] = cmds.getAttr("defaultResolution." + a)
    for a, v in (("width", int(w)), ("height", int(h)), ("pixelAspect", 1.0), ("deviceAspectRatio", float(w) / h)):
        cmds.setAttr("defaultResolution." + a, v)
    # zoom the viewport out enough that the whole frame (with a margin) fits, whatever its shape
    pw, ph = panel_size(panel)
    pa, ga = float(pw) / max(ph, 1), float(w) / h
    try:
        vertical = cmds.getAttr(cam + ".filmFit") == 2
    except Exception:
        vertical = False
    over = 1.15 * max(1.0, (ga / pa) if vertical else (pa / ga))
    for a, v in (("displayResolution", 1), ("displayGateMask", 1), ("overscan", max(old["camv"]["overscan"], over))):
        try:
            cmds.setAttr(cam + "." + a, v)
        except Exception:
            pass
    return old


def hide_gate(old):
    """Undo show_gate() (each value on its own, so a deleted camera or a new scene doesn't stop the rest)."""
    if not old:
        return
    for a, v in old["resv"].items():
        try:
            cmds.setAttr("defaultResolution." + a, v)
        except Exception:
            pass
    for a, v in old["camv"].items():
        try:
            cmds.setAttr(old["cam"] + "." + a, v)
        except Exception:
            pass


def sample_frames(start, end, fps):
    """Frames to record so the clip keeps real speed at `fps` (fractional frames when fps > scene fps)."""
    step = scene_fps() / float(fps)
    n = int((end - start) / step + 1e-6) + 1
    return [round(start + i * step, 4) for i in range(n)]


# --------------------------------------------------------------------------------------------- MOV -> MP4
def _boxes(data, off, end):
    while off + 8 <= end:
        size, typ = struct.unpack(">I4s", data[off:off + 8])
        hdr = 8
        if size == 1:
            size = struct.unpack(">Q", data[off + 8:off + 16])[0]
            hdr = 16
        elif size == 0:
            size = end - off
        yield off, size, hdr, typ
        off += size


def mov_to_mp4(src, dst, fps):
    """QuickTime H.264 .mov -> .mp4 (same streams): MP4 brands in ftyp, time scale set so every frame lasts 1/fps."""
    data = bytearray(open(src, "rb").read())
    container = {b"moov", b"trak", b"mdia", b"minf", b"stbl", b"edts"}
    found = {}

    def walk(off, end):
        for o, size, hdr, typ in _boxes(data, off, end):
            found.setdefault(typ, []).append(o)
            if typ in container:
                walk(o + hdr, o + size)
    walk(0, len(data))
    if b"ftyp" not in found or b"stts" not in found:
        raise RuntimeError("unexpected movie layout")
    o = found[b"ftyp"][0]
    size = struct.unpack(">I", data[o:o + 4])[0]
    payload = b"isom" + struct.pack(">I", 0x200)
    brands = [b"isom", b"iso2", b"avc1", b"mp41", b"mp42"]
    room = size - 16
    payload += b"".join(brands[:room // 4]).ljust(room, b"\0")
    data[o + 8:o + size] = payload
    o = found[b"stts"][0]
    delta = struct.unpack(">I", data[o + 20:o + 24])[0]          # first entry's sample delta
    new_ts = int(round(delta * fps))
    for typ in (b"mvhd", b"mdhd"):
        for o in found.get(typ, []):
            ver = data[o + 8]
            pos = o + (28 if ver == 1 else 20)                      # time scale field
            data[pos:pos + 4] = struct.pack(">I", new_ts)
    with open(dst, "wb") as f:
        f.write(bytes(data))
    return dst


# --------------------------------------------------------------------------------------------- MOV looping
_CONT = {b"moov", b"trak", b"mdia", b"minf", b"stbl", b"edts", b"dinf"}


def _parse(data, off, end):
    out = []
    for o, size, hdr, typ in _boxes(data, off, end):
        if typ in _CONT:
            out.append([typ, _parse(data, o + hdr, o + size)])
        else:
            out.append([typ, bytes(data[o + hdr:o + size])])
    return out


def _build(boxes):
    out = b""
    for typ, body in boxes:
        payload = _build(body) if isinstance(body, list) else body
        out += struct.pack(">I4s", len(payload) + 8, typ) + payload
    return out


def _find(boxes, typ):
    for b in boxes:
        if b[0] == typ:
            yield b
        if isinstance(b[1], list):
            for x in _find(b[1], typ):
                yield x


def mov_loop(src, dst, loops):
    """Repeat every sample of a one-track movie `loops` times by rewriting the sample tables (no re-encoding; the
    picture data is shared). Works for the closed-GOP H.264 that Maya's playblast writes."""
    data = open(src, "rb").read()
    top = _parse(data, 0, len(data))
    order = [b[0] for b in top]
    if order.index(b"moov") < order.index(b"mdat"):
        raise RuntimeError("moov before mdat not supported")
    stbl = next(_find(top, b"stbl"))[1]
    get = {b[0]: b for b in stbl}
    # sample sizes and offsets
    sz = get[b"stsz"][1]
    fixed, n = struct.unpack(">II", sz[4:12])
    sizes = [fixed] * n if fixed else list(struct.unpack(">%dI" % n, sz[12:12 + 4 * n]))
    sc = get[b"stsc"][1]
    m = struct.unpack(">I", sc[4:8])[0]
    stsc = [struct.unpack(">III", sc[8 + 12 * i:20 + 12 * i]) for i in range(m)]
    co_key = b"stco" if b"stco" in get else b"co64"
    co = get[co_key][1]
    k = struct.unpack(">I", co[4:8])[0]
    chunks = list(struct.unpack(">%d%s" % (k, "I" if co_key == b"stco" else "Q"), co[8:]))
    offsets, si = [], 0
    for ci, base in enumerate(chunks):
        per = next(e[1] for e in reversed(stsc) if e[0] <= ci + 1)
        off = base
        for _ in range(per):
            if si >= n:
                break
            offsets.append(off)
            off += sizes[si]
            si += 1
    L = int(loops)
    vf = b"\0\0\0\0"
    get[b"stsz"][1] = vf + struct.pack(">II", 0, n * L) + struct.pack(">%dI" % (n * L), *(sizes * L))
    get[b"stsc"][1] = vf + struct.pack(">IIII", 1, 1, 1, 1)
    big = max(offsets) > 0xFFFFFFFF
    newco = vf + struct.pack(">I", n * L) + struct.pack(">%d%s" % (n * L, "Q" if big else "I"), *(offsets * L))
    get[co_key][0] = b"co64" if big else b"stco"
    get[co_key][1] = newco
    st = get[b"stts"][1]
    e = struct.unpack(">I", st[4:8])[0]
    entries = st[8:8 + 8 * e]
    get[b"stts"][1] = vf + struct.pack(">I", e * L) + entries * L
    total_delta = sum(struct.unpack(">II", entries[8 * i:8 * i + 8])[0] * struct.unpack(">II", entries[8 * i:8 * i + 8])[1]
                      for i in range(e))
    if b"ctts" in get:
        ct = get[b"ctts"][1]
        e2 = struct.unpack(">I", ct[4:8])[0]
        get[b"ctts"][1] = ct[:4] + struct.pack(">I", e2 * L) + ct[8:8 + 8 * e2] * L
    if b"stss" in get:
        ss = get[b"stss"][1]
        e3 = struct.unpack(">I", ss[4:8])[0]
        nums = list(struct.unpack(">%dI" % e3, ss[8:8 + 4 * e3]))
        allnums = [x + i * n for i in range(L) for x in nums]
        get[b"stss"][1] = vf + struct.pack(">I", len(allnums)) + struct.pack(">%dI" % len(allnums), *allnums)
    if b"sdtp" in get:
        sd = get[b"sdtp"][1]
        get[b"sdtp"][1] = sd[:4] + sd[4:4 + n] * L
    # durations x L
    def scale(box, off32, off64):
        body = bytearray(box[1])
        if body[0] == 1:
            v = struct.unpack(">Q", body[off64:off64 + 8])[0]
            body[off64:off64 + 8] = struct.pack(">Q", v * L)
        else:
            v = struct.unpack(">I", body[off32:off32 + 4])[0]
            body[off32:off32 + 4] = struct.pack(">I", min(0xFFFFFFFF, v * L))
        box[1] = bytes(body)
    for b in _find(top, b"mvhd"):
        scale(b, 16, 24)
    for b in _find(top, b"mdhd"):
        scale(b, 16, 24)
    for b in _find(top, b"tkhd"):
        scale(b, 20, 28)
    for b in _find(top, b"elst"):
        body = bytearray(b[1])
        cnt = struct.unpack(">I", body[4:8])[0]
        if body[0] == 0:
            for i in range(cnt):
                o = 8 + 12 * i
                v = struct.unpack(">I", body[o:o + 4])[0]
                body[o:o + 4] = struct.pack(">I", min(0xFFFFFFFF, v * L))
        b[1] = bytes(body)
    with open(dst, "wb") as f:
        f.write(_build(top))
    return n * L


def is_seamless_loop(start, end):
    """True when the last frame looks the same as the first (typical Mixamo loop) -> skip it when repeating."""
    joints = (cmds.ls(type="joint") or [])[:300]
    if not joints:
        return False
    now = cmds.currentTime(q=True)
    cmds.currentTime(start)
    a = [cmds.xform(j, q=True, ws=True, t=True) for j in joints]
    cmds.currentTime(end)
    b = [cmds.xform(j, q=True, ws=True, t=True) for j in joints]
    cmds.currentTime(now)
    return max(max(abs(x - y) for x, y in zip(p, q)) for p, q in zip(a, b)) < 0.01


# --------------------------------------------------------------------------------------------- record
def record(out, fmt="mp4", fps=30, size=None, start=None, end=None, show_joints=False, show_controls=False,
           show_grid=False, show_hud=False, panel=None, cb=None, loops=1, background=None):
    """Returns dict(path, frames, fps, size, pngs (gif only: frame files to encode), tmp)."""
    fmt = fmt.lower()
    if fmt not in FORMATS:
        raise RuntimeError("format must be mp4, gif or png")
    if cmds.about(batch=True):
        raise RuntimeError(u"錄影要在 Maya 的視窗裡執行")
    panel = panel or active_panel()
    start = cmds.playbackOptions(q=True, min=True) if start is None else start
    end = cmds.playbackOptions(q=True, max=True) if end is None else end
    w, h = size if size else panel_size(panel)
    w, h = int(w) // 2 * 2, int(h) // 2 * 2                     # H.264 needs even sizes
    frames = sample_frames(start, end, fps)
    loops = max(1, int(loops))
    # the last frame is only a duplicate when it really is the end frame (lower fps may already skip it)
    if loops > 1 and len(frames) > 2 and abs(frames[-1] - end) < 1e-3 and is_seamless_loop(start, end):
        frames = frames[:-1]           # last == first: drop it so the loop has no hitch
        log(cb, u"頭尾同一個姿勢，循環時去掉最後一格")
    out = os.path.abspath(out)
    if not os.path.isdir(os.path.dirname(out)):
        os.makedirs(os.path.dirname(out))

    # display settings for the recording, put back afterwards
    flags = {"joints": show_joints, "grid": show_grid}
    for f in CONTROL_FLAGS:
        flags[f] = show_controls
    old = {}
    for k, v in flags.items():
        try:
            old[k] = cmds.modelEditor(panel, q=True, **{k: True})
            cmds.modelEditor(panel, e=True, **{k: v})
        except Exception:
            pass
    # no gate lines / overscan in the recording: the frame is exactly what the Resolution Gate shows
    cam = panel_camera(panel)
    old_cam = {}
    if cam:
        for a, v in (("overscan", 1.0), ("displayResolution", 0), ("displayGateMask", 0), ("displayFilmGate", 0)):
            try:
                old_cam[a] = cmds.getAttr(cam + "." + a)
                cmds.setAttr(cam + "." + a, v)
            except Exception:
                old_cam.pop(a, None)
    sel = cmds.ls(selection=True)
    cmds.select(clear=True)
    now = cmds.currentTime(q=True)
    tmp = tempfile.mkdtemp(prefix="asMixamoRec_")
    common = dict(viewer=False, showOrnaments=show_hud, offScreen=True, percent=100, widthHeight=(w, h),
                  forceOverwrite=True, editorPanelName=panel, frame=frames)
    result = {"frames": len(frames) * loops, "fps": fps, "size": (w, h), "tmp": tmp, "pngs": None, "loops": loops}
    transparent = background == "transparent" and fmt == "png"
    old_bg = _set_background(background)
    try:
        if fmt == "mp4":
            log(cb, u"錄影中（MP4，%d 格，%d fps，%dx%d）…" % (len(frames), fps, w, h))
            mov = None
            try:
                mov = cmds.playblast(format="qt", compression="H.264", quality=95,
                                     filename=os.path.join(tmp, "clip"), **common)
                mov = mov if mov.lower().endswith(".mov") else mov + ".mov"
            except Exception as e:
                log(cb, u"QuickTime H.264 不能用（%s），改用圖片序列" % e)
            if mov and os.path.isfile(mov):
                if loops > 1:
                    looped = os.path.join(tmp, "clip_loop.mov")
                    mov_loop(mov, looped, loops)
                    mov = looped
                mov_to_mp4(mov, out, fps)
            else:
                pngs = _png_blast(tmp, common, cb) * loops
                _png_to_mp4_blender(pngs, out, fps, cb)
            result["path"] = out
        else:
            pngs = _png_blast(tmp, common, cb, keep_alpha=transparent) * loops
            if fmt == "png":
                base = os.path.splitext(out)[0]
                os.makedirs(base, exist_ok=True)
                name = os.path.basename(base)
                for i, p in enumerate(pngs):
                    shutil.copy2(p, os.path.join(base, "%s.%04d.png" % (name, i + 1)))
                result["path"] = base
            else:
                result["path"] = out
                result["pngs"] = pngs                              # GIF: encoded by the worker
    finally:
        _restore_background(old_bg)
        for a, v in old_cam.items():
            try:
                cmds.setAttr(cam + "." + a, v)
            except Exception:
                pass
        for k, v in old.items():
            try:
                cmds.modelEditor(panel, e=True, **{k: v})
            except Exception:
                pass
        cmds.currentTime(now)
        if sel:
            cmds.select(sel)
    return result


def _png_blast(tmp, common, cb, keep_alpha=False):
    log(cb, u"錄影中（%d 格）…" % len(common["frame"]))
    cmds.playblast(format="image", compression="png", filename=os.path.join(tmp, "f"), framePadding=4, **common)
    pngs = sorted(glob.glob(os.path.join(tmp, "f.*.png")))
    if not pngs:
        raise RuntimeError(u"playblast 沒有輸出畫面")
    if not keep_alpha:
        flatten_pngs(pngs, cb)
    return pngs


BG_KEYS = ("background", "backgroundTop", "backgroundBottom")


def _set_background(background):
    """background: None (keep the viewport's) | ("solid", rgb) | ("gradient", top_rgb, bottom_rgb) | "transparent";
    rgb = 0-255 ints. Changes Maya's display colours for the recording; returns what to pass to _restore_background."""
    if not background or background == "transparent":
        return None
    old = {k: cmds.displayRGBColor(k, q=True) for k in BG_KEYS}
    old["gradient"] = cmds.displayPref(q=True, displayGradient=True)
    f = lambda c: [max(0.0, min(1.0, v / 255.0)) for v in c]
    if background[0] == "solid":
        cmds.displayRGBColor("background", *f(background[1]))
        cmds.displayPref(displayGradient=False)
    else:
        cmds.displayRGBColor("backgroundTop", *f(background[1]))
        cmds.displayRGBColor("backgroundBottom", *f(background[2]))
        cmds.displayPref(displayGradient=True)
    return old


def _restore_background(old):
    if not old:
        return
    for k in BG_KEYS:
        try:
            cmds.displayRGBColor(k, *old[k])
        except Exception:
            pass
    try:
        cmds.displayPref(displayGradient=old["gradient"])
    except Exception:
        pass


def _background_colors():
    """Viewport background as (top, bottom) 0-255 RGB (same colour twice when there is no gradient)."""
    def rgb(name):
        return [max(0, min(255, int(round(c * 255)))) for c in cmds.displayRGBColor(name, q=True)]
    try:
        if cmds.displayPref(q=True, displayGradient=True):
            return rgb("backgroundTop"), rgb("backgroundBottom")
    except Exception:
        pass
    c = rgb("background")
    return c, c


def flatten_pngs(pngs, cb=None):
    """A PNG playblast has a transparent background (alpha 0). Players and encoders that honour alpha (Blender's
    MP4 fallback, image viewers, some machines' GIFs) then show it as BLACK. Make every frame opaque, in place:
    keep the background colour the playblast stored in the transparent pixels; when it stored black instead
    (premultiplied output on some machines/GPUs), paint the viewport's background colour/gradient behind it."""
    from PySide6 import QtCore, QtGui
    top, bottom = _background_colors()
    painted = False
    for p in pngs:
        img = QtGui.QImage(p)
        if img.isNull() or not img.hasAlphaChannel():
            continue
        w, h = img.width(), img.height()
        c = img.pixelColor(0, 0)
        stored_black = c.alpha() == 0 and c.red() + c.green() + c.blue() == 0 and sum(top) > 30
        if stored_black:
            out = QtGui.QImage(w, h, QtGui.QImage.Format_RGB888)
            painter = QtGui.QPainter(out)
            grad = QtGui.QLinearGradient(0, 0, 0, h)
            grad.setColorAt(0.0, QtGui.QColor(*top))
            grad.setColorAt(1.0, QtGui.QColor(*bottom))
            painter.fillRect(QtCore.QRect(0, 0, w, h), QtGui.QBrush(grad))
            painter.drawImage(0, 0, img)          # source-over: uses the frame's alpha
            painter.end()
            painted = True
        else:
            out = img.convertToFormat(QtGui.QImage.Format_RGB888)   # drop alpha, keep stored background
        out.save(p, "PNG")
    if painted:
        log(cb, u"背景是透明的，已補上 viewport 的背景色")


def _png_to_mp4_blender(pngs, out, fps, cb):
    """Fallback when Maya has no H.264 movie support: encode with Blender if it is installed."""
    import subprocess
    exe = None
    for root in (r"C:\Program Files\Blender Foundation",):
        for b in sorted(glob.glob(os.path.join(root, "Blender*", "blender.exe")), reverse=True):
            exe = b
            break
    if not exe:
        raise RuntimeError(u"這台電腦的 Maya 不能輸出 H.264，也找不到 Blender；請改用 GIF 或 PNG")
    script = os.path.join(os.path.dirname(pngs[0]), "_enc.py")
    with open(script, "w", encoding="utf-8") as f:
        f.write(
            "import bpy,sys\n"
            "a=sys.argv[sys.argv.index('--')+1:]\nfiles=a[2:]\nscn=bpy.context.scene\n"
            "img=bpy.data.images.load(files[0]);w,h=img.size\n"
            "scn.render.resolution_x,scn.render.resolution_y=w-w%2,h-h%2;scn.render.resolution_percentage=100\n"
            "scn.render.fps=int(a[1]);scn.frame_start=1;scn.frame_end=len(files)\n"
            "scn.sequence_editor_create()\n"
            "st=scn.sequence_editor.sequences.new_image('f',files[0],channel=1,frame_start=1)\n"
            "import os\n[st.elements.append(os.path.basename(x)) for x in files[1:]]\n"
            "scn.render.image_settings.file_format='FFMPEG';scn.render.ffmpeg.format='MPEG4';scn.render.ffmpeg.codec='H264'\n"
            "scn.render.ffmpeg.constant_rate_factor='HIGH';scn.render.filepath=a[0];scn.render.use_sequencer=True\n"
            "bpy.ops.render.render(animation=True)\n")
    log(cb, u"用 Blender 轉 MP4…")
    subprocess.run([exe, "-b", "--factory-startup", "--python", script, "--", out, str(int(fps))] + pngs,
                   check=True, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)


def default_name(fmt):
    scene = cmds.file(q=True, sceneName=True)
    stem = os.path.splitext(os.path.basename(scene))[0] if scene else "untitled"
    folder = os.path.join(os.path.dirname(scene), "Playblast") if scene else os.path.join(tempfile.gettempdir(), "Playblast")
    return os.path.join(folder, stem + ("" if fmt == "png" else "." + fmt)).replace("\\", "/")
