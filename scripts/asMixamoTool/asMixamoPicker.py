# -*- coding: utf-8 -*-
"""Body-part picker for the retarget: one clickable region per AS deform joint that the Mixamo retarget drives
(21 body bones + palm and 15 finger bones per hand = 51). Selected parts glow amber.

Art: an AI-generated silhouette, split into bones offline; the runtime files are in
picker/ (body_off.png, body_on.png, body_ids.png = 8-bit bone id per pixel, picker.json = names + hand polygons)."""
import json
import os

import numpy as np
from PySide6 import QtCore, QtGui, QtWidgets

HERE = os.path.join(os.path.dirname(os.path.abspath(__file__)), "picker")

FINGERS = ("Thumb", "Index", "Middle", "Ring", "Pinky")
FINGER_ZH = {"Thumb": u"大拇指", "Index": u"食指", "Middle": u"中指", "Ring": u"無名指", "Pinky": u"小指"}
BONE_ZH = {"Head_M": u"頭", "Neck_M": u"脖子", "Chest_M": u"胸", "Spine1_M": u"腰（脊椎）", "Root_M": u"骨盆（含整體位移）",
           "Scapula": u"肩胛", "Shoulder": u"上臂", "Elbow": u"前臂", "Wrist": u"手掌",
           "Hip": u"大腿", "Knee": u"小腿", "Ankle": u"腳踝", "Toes": u"腳趾"}
SIDE_ZH = {"L": u"左", "R": u"右"}


def bone_label(name):
    """'Elbow_R' -> '右前臂（Elbow_R）'"""
    if name in BONE_ZH:
        return u"%s（%s）" % (BONE_ZH[name], name)
    base, side = name.rsplit("_", 1)
    for f in FINGERS:
        if base.startswith(f + "Finger"):
            return u"%s%s 第 %s 節（%s）" % (SIDE_ZH[side], FINGER_ZH[f], base[-1], name)
    return u"%s%s（%s）" % (SIDE_ZH.get(side, ""), BONE_ZH.get(base, base), name)


def all_bones():
    meta = _meta()
    names = list(meta["body"])
    for n, _ in meta["hands"]:
        if n not in names:
            names.append(n)
    return names


def finger_bones(side=None):
    sides = (side,) if side else ("L", "R")
    return ["%sFinger%d_%s" % (f, k, s) for s in sides for f in FINGERS for k in (1, 2, 3)]


PRESETS = [
    (u"全身", lambda: all_bones()),
    (u"上半身", lambda: [b for b in all_bones() if not b.startswith(("Hip_", "Knee_", "Ankle_", "Toes_", "Root_"))]),
    (u"下半身", lambda: ["Root_M"] + ["%s_%s" % (b, s) for s in "LR" for b in ("Hip", "Knee", "Ankle", "Toes")]),
    (u"雙手臂", lambda: ["%s_%s" % (b, s) for s in "LR" for b in ("Scapula", "Shoulder", "Elbow", "Wrist")] + finger_bones()),
    (u"只有手指", lambda: finger_bones()),
    (u"清除", lambda: []),
]

_META = None


def _meta():
    global _META
    if _META is None:
        with open(os.path.join(HERE, "picker.json"), encoding="utf-8") as f:
            _META = json.load(f)
    return _META


# picker looks: "glow" = the original cyan / amber art (Maya theme); "tiles" = single orange family with rounded,
# separated tiles (the 深色圓角 theme). Art files per look are in picker/ (tiles built offline from the glow art).
STYLES = {
    "glow": dict(files=("body_off.png", "body_on.png", "body_ids.png"), bg=(30, 34, 42),
                 on=((205, 132, 48), (255, 225, 160)), off=((18, 25, 37), (63, 200, 255)),
                 dis=((36, 38, 42), (80, 84, 92)), label=(170, 185, 205), round=0.0, pen=1.4),
    "tiles": dict(files=("body_off_r.png", "body_on_r.png", "body_ids_r.png"), bg="#141210",
                  on=("#f08c00", "#ffe2b0"), off=("#231a10", "#8a5418"),
                  dis=("#1c1a18", "#3a3530"), label=(200, 170, 130), round=3.0, pen=1.3),
}


def _qc(v):
    return QtGui.QColor(v) if isinstance(v, str) else QtGui.QColor(*v)


def _rounded_path(poly, r):
    """QPolygonF -> QPainterPath with every corner rounded (quadratic, radius capped at half the edge)."""
    pts = [poly[i] for i in range(poly.count())]
    path = QtGui.QPainterPath()
    n = len(pts)
    for i in range(n):
        p0, p1, p2 = pts[i - 1], pts[i], pts[(i + 1) % n]
        d0, d2 = p0 - p1, p2 - p1
        l0 = max((d0.x() ** 2 + d0.y() ** 2) ** 0.5, 1e-6)
        l2 = max((d2.x() ** 2 + d2.y() ** 2) ** 0.5, 1e-6)
        rr = min(r, l0 / 2, l2 / 2)
        a, b = p1 + d0 * (rr / l0), p1 + d2 * (rr / l2)
        if i == 0:
            path.moveTo(a)
        else:
            path.lineTo(a)
        path.quadTo(p1, b)
    path.closeSubpath()
    return path


def _to_array(img):
    img = img.convertToFormat(QtGui.QImage.Format_RGBA8888)
    w, h = img.width(), img.height()
    arr = np.frombuffer(img.constBits(), np.uint8, count=img.sizeInBytes()).reshape(h, img.bytesPerLine())
    return arr[:, :w * 4].reshape(h, w, 4).copy()


def _to_image(arr):
    h, w = arr.shape[:2]
    arr = np.ascontiguousarray(arr)
    return QtGui.QImage(arr.data, w, h, w * 4, QtGui.QImage.Format_RGBA8888).copy()


class BodyPicker(QtWidgets.QWidget):
    """Click a part to toggle it; Shift+drag paints (on or off, by the first part touched).
    selectionChanged(list of bone names) fires on every change; hovered(str) gives the bone under the mouse."""
    selectionChanged = QtCore.Signal(list)
    hovered = QtCore.Signal(str)

    BG = QtGui.QColor(30, 34, 42)
    ON_FILL, ON_EDGE = QtGui.QColor(205, 132, 48), QtGui.QColor(255, 225, 160)
    OFF_FILL, OFF_EDGE = QtGui.QColor(18, 25, 37), QtGui.QColor(63, 200, 255)
    DIS_FILL, DIS_EDGE = QtGui.QColor(36, 38, 42), QtGui.QColor(80, 84, 92)

    def __init__(self, parent=None, style="glow"):
        super().__init__(parent)
        m = _meta()
        self._size = QtCore.QSize(*m["size"])
        self._off = QtCore.QPoint(*m["bodyOffset"])
        self.names = list(m["body"])
        self._hands = [(n, QtGui.QPolygonF([QtCore.QPointF(x, y) for x, y in poly])) for n, poly in m["hands"]]
        self._load_style(style)
        self._labels = m["labels"]
        self._all = all_bones()
        self._sel = set(self._all)
        self._enabled = set(self._all)
        self._hover = ""
        self._drag = None
        self._body_img = None
        self.setMouseTracking(True)
        self.setFixedSize(self._size)
        self._recompose()

    def _load_style(self, style):
        st = STYLES.get(style, STYLES["glow"])
        self.style_key = style if style in STYLES else "glow"
        f_off, f_on, f_ids = st["files"]
        self._arr_off = _to_array(QtGui.QImage(os.path.join(HERE, f_off)))
        self._arr_on = _to_array(QtGui.QImage(os.path.join(HERE, f_on)))
        ids = QtGui.QImage(os.path.join(HERE, f_ids)).convertToFormat(QtGui.QImage.Format_Grayscale8)
        self._ids = np.frombuffer(ids.constBits(), np.uint8, count=ids.sizeInBytes()).reshape(
            ids.height(), ids.bytesPerLine())[:, :ids.width()].copy()
        self.BG = _qc(st["bg"])
        self.ON_FILL, self.ON_EDGE = [_qc(c) for c in st["on"]]
        self.OFF_FILL, self.OFF_EDGE = [_qc(c) for c in st["off"]]
        self.DIS_FILL, self.DIS_EDGE = [_qc(c) for c in st["dis"]]
        self._label_col = _qc(st["label"])
        self._pen_w = st["pen"]
        self._hand_paths = [(n, _rounded_path(poly, st["round"]) if st["round"] else None) for n, poly in self._hands]

    def setStyle(self, style):
        if style != getattr(self, "style_key", None):
            self._load_style(style)
            self._recompose()

    # ------------------------------------------------------------------ state
    def selection(self):
        return [b for b in self._all if b in self._sel and b in self._enabled]

    def setSelection(self, names, emit=True):
        self._sel = set(n for n in names if n in self._all)
        self._recompose()
        if emit:
            self.selectionChanged.emit(self.selection())

    def setEnabledBones(self, names):
        """Bones the rig really has (others grey out). None = all."""
        self._enabled = set(self._all) if names is None else set(n for n in names if n in self._all)
        self._recompose()
        self.selectionChanged.emit(self.selection())

    def enabledBones(self):
        return [b for b in self._all if b in self._enabled]

    def isWholeBody(self):
        return set(self.selection()) == set(self.enabledBones())

    # ------------------------------------------------------------------ drawing
    def _recompose(self):
        sel_ids = [i + 1 for i, n in enumerate(self.names) if n in self._sel and n in self._enabled]
        dis_ids = [i + 1 for i, n in enumerate(self.names) if n not in self._enabled]
        out = self._arr_off.copy()
        if sel_ids:
            m = np.isin(self._ids, sel_ids)
            out[m] = self._arr_on[m]
        if dis_ids:
            m = np.isin(self._ids, dis_ids)
            grey = out[m][:, :3].mean(axis=1, keepdims=True) * 0.55
            out[m, :3] = grey.astype(np.uint8)
        if self._hover in self.names:
            m = self._ids == self.names.index(self._hover) + 1
            out[m, :3] = np.minimum(255, out[m, :3].astype(np.int32) + 40).astype(np.uint8)
        self._body_img = _to_image(out)
        self.update()

    def paintEvent(self, e):
        p = QtGui.QPainter(self)
        p.setRenderHint(QtGui.QPainter.Antialiasing)
        p.fillRect(self.rect(), self.BG)
        p.drawImage(self._off, self._body_img)
        for (name, poly), (_, path) in zip(self._hands, self._hand_paths):
            if name not in self._enabled:
                fill, edge = self.DIS_FILL, self.DIS_EDGE
            elif name in self._sel:
                fill, edge = self.ON_FILL, self.ON_EDGE
            else:
                fill, edge = self.OFF_FILL, self.OFF_EDGE
            if name == self._hover:
                fill = fill.lighter(140)
            p.setBrush(fill)
            p.setPen(QtGui.QPen(edge, self._pen_w))
            if path is not None:
                p.drawPath(path)
            else:
                p.drawPolygon(poly)
        p.setPen(self._label_col)
        f = p.font()
        f.setPointSize(9)
        p.setFont(f)
        for side, (x, y) in self._labels.items():
            p.drawText(QtCore.QRectF(x - 60, y - 10, 120, 20), QtCore.Qt.AlignCenter, u"%s手 _%s" % (SIDE_ZH[side], side))
        p.end()

    # ------------------------------------------------------------------ mouse
    def boneAt(self, pos):
        for name, poly in self._hands:
            if poly.containsPoint(QtCore.QPointF(pos), QtCore.Qt.OddEvenFill):
                return name
        x, y = pos.x() - self._off.x(), pos.y() - self._off.y()
        if 0 <= y < self._ids.shape[0] and 0 <= x < self._ids.shape[1]:
            i = int(self._ids[y, x])
            if i:
                return self.names[i - 1]
        return ""

    def _set_hover(self, name):
        if name != self._hover:
            self._hover = name
            self._recompose()
            self.hovered.emit(name)
            self.setToolTip(bone_label(name) if name else "")

    def mousePressEvent(self, e):
        if e.button() != QtCore.Qt.LeftButton:
            return
        name = self.boneAt(e.position().toPoint())
        if not name or name not in self._enabled:
            return
        turn_on = name not in self._sel
        self._drag = turn_on if e.modifiers() & QtCore.Qt.ShiftModifier else None
        (self._sel.add if turn_on else self._sel.discard)(name)
        self._recompose()
        self.selectionChanged.emit(self.selection())

    def mouseMoveEvent(self, e):
        name = self.boneAt(e.position().toPoint())
        self._set_hover(name)
        if self._drag is not None and name and name in self._enabled and ((name in self._sel) != self._drag):
            (self._sel.add if self._drag else self._sel.discard)(name)
            self._recompose()
            self.selectionChanged.emit(self.selection())

    def mouseReleaseEvent(self, e):
        self._drag = None

    def leaveEvent(self, e):
        self._set_hover("")


class PartsBox(QtWidgets.QWidget):
    """Collapsible '套用部位' section: a header line with the summary, the picker and preset buttons."""
    changed = QtCore.Signal()

    def __init__(self, settings, key, parent=None):
        super().__init__(parent)
        self.settings, self.key = settings, key
        v = QtWidgets.QVBoxLayout(self)
        v.setContentsMargins(0, 0, 0, 0)
        head = QtWidgets.QHBoxLayout()
        self.bt = QtWidgets.QToolButton()
        self.bt.setCheckable(True)
        self.bt.setToolButtonStyle(QtCore.Qt.ToolButtonTextBesideIcon)
        self.bt.setStyleSheet("QToolButton{border:none;font-size:13px;color:#f2f2f2}")
        self.bt.toggled.connect(self._toggle)
        head.addWidget(self.bt)
        self.summary = QtWidgets.QLabel()
        head.addWidget(self.summary, 1)
        v.addLayout(head)
        self.body = QtWidgets.QFrame()
        self.body.setFrameShape(QtWidgets.QFrame.StyledPanel)
        h = QtWidgets.QHBoxLayout(self.body)
        self.picker = BodyPicker()
        h.addWidget(self.picker, 0, QtCore.Qt.AlignTop)
        side = QtWidgets.QVBoxLayout()
        grid = QtWidgets.QGridLayout()
        for i, (label, fn) in enumerate(PRESETS):
            b = QtWidgets.QPushButton(label)
            b.clicked.connect(lambda _=False, fn=fn: self.picker.setSelection(fn()))
            grid.addWidget(b, i // 2, i % 2)
        side.addLayout(grid)
        self.hover = QtWidgets.QLabel(" ")
        self.hover.setStyleSheet("color:#f0b860")
        self.hover.setWordWrap(True)
        side.addWidget(self.hover)
        tip = QtWidgets.QLabel(u"點一下：選／取消一根骨頭\nShift＋拖曳：連續選一整串\n"
                               u"左右以角色為準（_L = 角色的左邊）\n灰色 = 這個 rig 沒有的骨頭\n\n"
                               u"只套用亮橘色的骨頭；\n其他部位保留場景原本的動畫。")
        tip.setStyleSheet("color:#999")
        side.addWidget(tip)
        side.addStretch(1)
        h.addLayout(side, 1)
        v.addWidget(self.body)
        self.picker.selectionChanged.connect(self._changed)
        self.picker.hovered.connect(lambda n: self.hover.setText(bone_label(n) if n else " "))
        saved = settings.value(key + "_parts", None)
        if saved:
            try:
                self.picker.setSelection(json.loads(saved), emit=False)
            except Exception:
                pass
        self.bt.setChecked(settings.value(key + "_parts_open", "false") == "true")
        self._toggle(self.bt.isChecked())
        self._changed()

    def _toggle(self, on):
        self.body.setVisible(on)
        self.bt.setArrowType(QtCore.Qt.DownArrow if on else QtCore.Qt.RightArrow)
        self.bt.setText(u"套用部位")
        self.settings.setValue(self.key + "_parts_open", "true" if on else "false")

    def _changed(self, *a):
        sel, en = self.picker.selection(), self.picker.enabledBones()
        if not sel:
            txt, col = u"沒有選任何部位", "#ff6060"
        elif set(sel) == set(en):
            txt, col = u"全身（%d 根骨頭）" % len(en), "#aaaaaa"
        else:
            txt, col = u"只套用 %d／%d 根骨頭" % (len(sel), len(en)), "#f0b860"
        self.summary.setText(txt)
        self.summary.setStyleSheet("color:%s" % col)
        self.settings.setValue(self.key + "_parts", json.dumps(self.picker.selection()))
        self.changed.emit()

    def setStyle(self, style):
        self.picker.setStyle(style)

    def parts(self):
        """None = whole body (the normal retarget); otherwise the selected AS joint names."""
        return None if self.picker.isWholeBody() else self.picker.selection()

    def setRigBones(self, names):
        self.picker.setEnabledBones(names)
