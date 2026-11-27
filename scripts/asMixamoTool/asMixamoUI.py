# -*- coding: utf-8 -*-
"""Window for asMixamoTool. Work runs in a background mayapy, so Maya stays usable."""
import json
import os
import re
import sys
import tempfile

from PySide6 import QtCore, QtGui, QtWidgets

HERE = os.path.dirname(os.path.abspath(__file__))
WORKER = os.path.join(HERE, "asMixamoWorker.py")
try:                       # one version number for the whole tool: the package's __version__
    from . import __version__ as VERSION
except ImportError:
    VERSION = "?"
TITLE = u"ASR Tools v" + VERSION   # ASR = AdvancedSkeleton + Retarget (formerly "AS × Mixamo")
_win = None


def _maya_window():
    try:
        import maya.OpenMayaUI as omui
        from shiboken6 import wrapInstance
        return wrapInstance(int(omui.MQtUtil.mainWindow()), QtWidgets.QWidget)
    except Exception:
        return None


def _mayapy():
    exe = os.path.join(os.path.dirname(sys.executable), "mayapy.exe")
    if os.path.exists(exe):
        return exe
    loc = os.environ.get("MAYA_LOCATION", "")
    exe = os.path.join(loc, "bin", "mayapy.exe")
    return exe if os.path.exists(exe) else "mayapy"


def _char_from_rig(path):
    stem = os.path.splitext(os.path.basename(path))[0]
    return re.sub(r"(?i)[_\-]?rig$", "", stem) or stem


def _motion_from_fbx(path):
    stem = os.path.splitext(os.path.basename(path))[0]
    return re.sub(r"[^0-9A-Za-z_]+", "_", stem).strip("_")


def _sources():
    """(label, key) for the 來源 menu: auto, then every built-in source."""
    out = [(u"自動判斷", "auto")]
    try:
        from . import asMixamoCore as core
        out += [(s.label, s.key) for s in core.list_sources()]
    except Exception:
        out += [(u"Mixamo 預設角色（Y Bot／X Bot）", "mixamo"), (u"客製模型（自己上傳 Mixamo 的版本）", "custom")]
    return out


SPLIT_CSS = ("QSplitter::handle{background:#3a3a3a;border-top:1px solid #5a5a5a;border-bottom:1px solid #5a5a5a;}"
             "QSplitter::handle:hover{background:#5285a6;}")

# 「深色圓角」theme: game-editor colours (near-black panels, orange accent) with flat rounded controls.
# Applied to this window only — the rest of Maya keeps its own look.
ACCENT = "#f08c00"
THEME_CSS = """
QDialog#asMixamoWin { background:#141414; }
QWidget { color:#d2d2d2; }
QDialog#asMixamoWin QWidget#page, QScrollArea, QScrollArea > QWidget > QWidget { background:#1b1b1b; }
QLabel { background:transparent; }
QTabWidget::pane { border:1px solid #2a2a2a; border-radius:8px; background:#1b1b1b; top:-1px; }
QTabBar::tab { background:#202020; color:#8f8f8f; padding:6px 14px; margin-right:3px;
               border-top-left-radius:6px; border-top-right-radius:6px; }
QTabBar::tab:selected { background:#1b1b1b; color:#ffffff; border-bottom:2px solid @A; }
QTabBar::tab:hover:!selected { background:#2a2a2a; color:#dddddd; }
QPushButton { background:#2a2a2a; color:#e2e2e2; border:1px solid #383838; border-radius:6px; padding:5px 12px; }
QPushButton:hover { background:#323232; border-color:@A; }
QPushButton:pressed { background:@A; color:#1a1a1a; }
QPushButton:disabled { background:#1f1f1f; color:#5c5c5c; border-color:#262626; }
QPushButton#primary { background:@A; color:#1a1a1a; border:none; font-size:13px; }
QPushButton#primary:hover { background:#ffa326; }
QPushButton#primary:disabled { background:#4a3a20; color:#8a7a60; }
QLineEdit, QComboBox, QSpinBox, QDoubleSpinBox, QPlainTextEdit, QTextEdit {
    background:#0f0f0f; color:#e6e6e6; border:1px solid #2f2f2f; border-radius:6px; padding:3px 6px;
    selection-background-color:@A; selection-color:#141414; }
QLineEdit:focus, QComboBox:focus, QSpinBox:focus, QDoubleSpinBox:focus, QPlainTextEdit:focus { border-color:@A; }
QLineEdit:disabled, QComboBox:disabled, QSpinBox:disabled, QDoubleSpinBox:disabled { color:#5c5c5c; background:#171717; }
QComboBox QAbstractItemView { background:#1f1f1f; border:1px solid #333; selection-background-color:@A;
                              selection-color:#141414; outline:none; }
QCheckBox, QRadioButton { spacing:6px; background:transparent; }
QCheckBox::indicator { width:13px; height:13px; border:1px solid #555; border-radius:4px; background:#0f0f0f; }
QCheckBox::indicator:hover { border-color:@A; }
QCheckBox::indicator:checked { background:@A; border-color:@A; }
QCheckBox::indicator:disabled { background:#1f1f1f; border-color:#333; }
QListView::indicator { width:13px; height:13px; border:1px solid #555; border-radius:4px; background:#0f0f0f; }
QListView::indicator:checked { background:@A; border-color:@A; }
QListView::item { padding:3px 2px; }
QRadioButton::indicator { width:13px; height:13px; border:1px solid #555; border-radius:7px; background:#0f0f0f; }
QRadioButton::indicator:checked { background:@A; border-color:@A; }
QGroupBox { border:1px solid #2c2c2c; border-radius:8px; margin-top:12px; padding-top:8px; background:transparent; }
QGroupBox::title { subcontrol-origin:margin; left:10px; padding:0 4px; color:@A; }
QProgressBar { background:#0f0f0f; border:1px solid #2a2a2a; border-radius:6px; text-align:center; color:#dddddd; }
QProgressBar::chunk { background:@A; border-radius:5px; }
QTableWidget, QTableView, QListWidget { background:#0f0f0f; border:1px solid #2a2a2a; border-radius:6px;
    gridline-color:#262626; alternate-background-color:#151515; selection-background-color:#4a3410; }
QHeaderView::section { background:#222222; color:#b8b8b8; border:none; border-right:1px solid #2c2c2c; padding:4px; }
QTableCornerButton::section { background:#222222; border:none; }
QScrollBar:vertical { background:transparent; width:10px; margin:2px; }
QScrollBar:horizontal { background:transparent; height:10px; margin:2px; }
QScrollBar::handle { background:#3a3a3a; border-radius:4px; min-height:24px; min-width:24px; }
QScrollBar::handle:hover { background:@A; }
QScrollBar::add-line, QScrollBar::sub-line { width:0; height:0; }
QScrollBar::add-page, QScrollBar::sub-page { background:transparent; }
QToolButton { background:transparent; border:none; }
QToolTip { background:#222222; color:#eeeeee; border:1px solid @A; border-radius:4px; padding:4px; }
QSplitter::handle { background:#202020; }
QSplitter::handle:hover { background:@A; }
""".replace("@A", ACCENT)
HELP_CSS_DARK = ("QLabel{color:%s;background:#2c2c2c;border:1px solid #444;border-radius:8px;"
                 "font-weight:bold;font-size:10px}" % ACCENT)
HELP_POP_DARK = "QLabel{background:#1f1f1f;color:#e6e6e6;border:1px solid %s;border-radius:6px;padding:6px 8px}" % ACCENT
HELP_CSS_MAYA = "QLabel{color:#ddd;background:#5a6a80;border-radius:8px;font-weight:bold;font-size:10px}"
HELP_POP_MAYA = "QLabel{background:#2b2b2b;color:#e6e6e6;border:1px solid #6a7a90;padding:6px 8px}"
THEMES = [(u"深色圓角", "dark"), (u"Maya 原生", "maya")]


class HelpBadge(QtWidgets.QLabel):
    """'?' badge with its own hover popup (Maya can swallow normal Qt tooltips, e.g. when Popup Help is off)."""

    def __init__(self, text, parent=None):
        super().__init__("?", parent)
        self.setAlignment(QtCore.Qt.AlignCenter)
        self.setFixedSize(16, 16)
        self.setStyleSheet("QLabel{color:#ddd;background:#5a6a80;border-radius:8px;font-weight:bold;font-size:10px}")
        self.setCursor(QtCore.Qt.WhatsThisCursor)
        self.pop = QtWidgets.QLabel(text, None, QtCore.Qt.ToolTip | QtCore.Qt.FramelessWindowHint)
        self.pop.setTextFormat(QtCore.Qt.RichText)
        self.pop.setStyleSheet("QLabel{background:#2b2b2b;color:#e6e6e6;border:1px solid #6a7a90;padding:6px 8px}")
        self.pop.adjustSize()

    def enterEvent(self, e):
        self.pop.adjustSize()
        self.pop.move(self.mapToGlobal(QtCore.QPoint(self.width() + 6, self.height() // 2 - self.pop.height() // 2)))
        self.pop.show()
        self.pop.raise_()
        super().enterEvent(e)

    def leaveEvent(self, e):
        self.pop.hide()
        super().leaveEvent(e)

    def hideEvent(self, e):
        self.pop.hide()
        super().hideEvent(e)

    def mousePressEvent(self, e):
        self.pop.setVisible(not self.pop.isVisible())


class DropLine(QtWidgets.QLineEdit):
    def __init__(self, exts, *a):
        super().__init__(*a)
        self.exts = exts
        self.setAcceptDrops(True)

    def dragEnterEvent(self, e):
        if e.mimeData().hasUrls():
            e.acceptProposedAction()

    def dropEvent(self, e):
        for u in e.mimeData().urls():
            p = u.toLocalFile()
            if (self.exts == "dir" and os.path.isdir(p)) or os.path.splitext(p)[1].lower() in self.exts:
                self.setText(p)
                self.editingFinished.emit()
                return


class MotionTable(QtWidgets.QTableWidget):
    filesDropped = QtCore.Signal(list)

    def __init__(self):
        super().__init__(0, 4)
        self.setHorizontalHeaderLabels([u"動作 FBX", u"動作名稱（可改）", u"輸出檔名", u"狀態"])
        h = self.horizontalHeader()
        h.setSectionResizeMode(0, QtWidgets.QHeaderView.Stretch)
        h.setSectionResizeMode(1, QtWidgets.QHeaderView.Interactive)
        h.setSectionResizeMode(2, QtWidgets.QHeaderView.Interactive)
        h.setSectionResizeMode(3, QtWidgets.QHeaderView.Stretch)
        self.setColumnWidth(1, 150)
        self.setColumnWidth(2, 170)
        self.verticalHeader().setVisible(False)
        self.setSelectionBehavior(QtWidgets.QAbstractItemView.SelectRows)
        self.setAcceptDrops(True)
        self.viewport().setAcceptDrops(True)
        self.setDragDropMode(QtWidgets.QAbstractItemView.DropOnly)

    def dragEnterEvent(self, e):
        if e.mimeData().hasUrls():
            e.acceptProposedAction()

    def dragMoveEvent(self, e):
        if e.mimeData().hasUrls():
            e.acceptProposedAction()

    def dropEvent(self, e):
        files = []
        for u in e.mimeData().urls():
            p = u.toLocalFile()
            if os.path.isdir(p):
                files += [os.path.join(p, f) for f in sorted(os.listdir(p)) if f.lower().endswith(".fbx")]
            elif p.lower().endswith(".fbx"):
                files.append(p)
        self.filesDropped.emit(files)


class SceneTable(QtWidgets.QTableWidget):
    """Animation-file list for the weights tab: drop .mb/.ma files or folders."""
    filesDropped = QtCore.Signal(list)

    def __init__(self):
        super().__init__(0, 3)
        self.setHorizontalHeaderLabels([u"動作檔", u"輸出", u"狀態"])
        h = self.horizontalHeader()
        h.setSectionResizeMode(0, QtWidgets.QHeaderView.Stretch)
        h.setSectionResizeMode(1, QtWidgets.QHeaderView.Interactive)
        h.setSectionResizeMode(2, QtWidgets.QHeaderView.Stretch)
        self.setColumnWidth(1, 220)
        self.verticalHeader().setVisible(False)
        self.setSelectionBehavior(QtWidgets.QAbstractItemView.SelectRows)
        self.setEditTriggers(QtWidgets.QAbstractItemView.NoEditTriggers)
        self.setAcceptDrops(True)
        self.viewport().setAcceptDrops(True)
        self.setDragDropMode(QtWidgets.QAbstractItemView.DropOnly)
        self.setMinimumHeight(160)

    def dragEnterEvent(self, e):
        if e.mimeData().hasUrls():
            e.acceptProposedAction()

    def dragMoveEvent(self, e):
        if e.mimeData().hasUrls():
            e.acceptProposedAction()

    def dropEvent(self, e):
        files = []
        for u in e.mimeData().urls():
            p = u.toLocalFile()
            if os.path.isdir(p):
                files += [os.path.join(p, f) for f in sorted(os.listdir(p)) if f.lower().endswith((".mb", ".ma"))]
            elif p.lower().endswith((".mb", ".ma")):
                files.append(p)
        self.filesDropped.emit(files)


class Window(QtWidgets.QDialog):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setWindowTitle(TITLE)
        self.setWindowFlags(self.windowFlags() | QtCore.Qt.WindowMinMaxButtonsHint)
        self.resize(820, 640)
        self.settings = QtCore.QSettings("ASRTools", "asMixamoTool")
        if not self.settings.allKeys():          # first run after the rename: bring the old settings along
            old = QtCore.QSettings("Sozopop", "asMixamoTool")
            for k in old.allKeys():
                self.settings.setValue(k, old.value(k))
        self.proc = None
        self.job_file = None

        self.setObjectName("asMixamoWin")
        top = QtWidgets.QHBoxLayout()
        top.addWidget(QtWidgets.QLabel(u"介面"))
        self.theme = QtWidgets.QComboBox()
        for label, key in THEMES:
            self.theme.addItem(label, key)
        keys = [k for _, k in THEMES]
        self.theme.setCurrentIndex(keys.index(self.settings.value("theme", "dark")) if self.settings.value("theme", "dark") in keys else 0)
        self.theme.currentIndexChanged.connect(lambda *_: self._apply_theme())
        top.addWidget(self.theme)
        top.addStretch(1)
        self.bt_fg = QtWidgets.QPushButton(u"左手跟槍 開／關")
        self.bt_fg.clicked.connect(self._follow_gun)
        top.addWidget(self.bt_fg)
        top.addWidget(HelpBadge(u"切換左手 IK 的 followGun（在目前這一格，手不會跳）。<br>開：左手跟著槍晃動，IK 本身照樣能調。"))
        top.addSpacing(16)
        self.bt_bp = QtWidgets.QPushButton(u"Go to Build Pose")
        self.bt_bp.clicked.connect(self._build_pose)
        top.addWidget(self.bt_bp)
        top.addWidget(HelpBadge(u"把 rig 回到綁定姿勢。<br>Ctrl+點擊：保留 Main 的位置。"))
        top.addSpacing(16)
        self.bt_upd = QtWidgets.QPushButton(u"版本／更新")
        self.bt_upd.setToolTip(u"檢查新版、看更新內容、退回舊版")
        self.bt_upd.clicked.connect(self._open_updater)
        top.addWidget(self.bt_upd)
        tabs = QtWidgets.QTabWidget()
        self.opt = {}
        self.tab_retarget = self._scroll(self._build_scene())
        self._pin(self.tab_retarget, [self.sc_note, self.sc_run])
        tabs.addTab(self.tab_retarget, u"Retarget")
        self.tab_asrt = self._scroll(self._build_asrt())
        self._pin(self.tab_asrt, [self.ar_run])
        tabs.addTab(self.tab_asrt, u"AS Retarget")
        tabs.currentChanged.connect(lambda i: self._asrt_refresh() if tabs.widget(i) is self.tab_asrt else None)
        tabs.addTab(self._build_batch(), u"批量 Retarget")
        self.tab_gun = self._scroll(self._build_gun())
        self._pin(self.tab_gun, [self.gs_finish])
        tabs.addTab(self.tab_gun, u"雙手武器骨架")
        tabs.currentChanged.connect(lambda i: self._gs_refresh() if tabs.widget(i) is self.tab_gun else None)
        self.tab_wt = self._scroll(self._build_weights())
        self._pin(self.tab_wt, [self.wt_run])
        tabs.addTab(self.tab_wt, u"模型更新")
        self.tab_ex = self._scroll(self._build_export())
        self._pin(self.tab_ex, [self.ex_run])
        tabs.addTab(self.tab_ex, u"匯出 FBX")
        tabs.currentChanged.connect(lambda i: self._ex_refresh() if tabs.widget(i) is self.tab_ex else None)
        self.tab_rec = self._build_record()
        tabs.addTab(self.tab_rec, u"錄影")
        tabs.currentChanged.connect(lambda i: self._rec_default_out() if tabs.widget(i) is self.tab_rec else None)
        tabs.currentChanged.connect(lambda i: self._scene_refresh() if tabs.widget(i) is self.tab_retarget else None)
        self.log = QtWidgets.QPlainTextEdit(readOnly=True)
        self.log.setMaximumBlockCount(3000)
        self.progress = QtWidgets.QProgressBar()
        self.progress.setTextVisible(True)
        self.progress.setValue(0)
        self.progress.setFixedHeight(16)
        # collapsible log: [▸ 紀錄][progress bar]  (collapsed by default, opens by itself on errors)
        self.bt_log = QtWidgets.QToolButton()
        self.bt_log.setText(u"紀錄")
        self.bt_log.setCheckable(True)
        self.bt_log.setToolButtonStyle(QtCore.Qt.ToolButtonTextBesideIcon)
        self.bt_log.setStyleSheet("QToolButton{border:none;color:#bbb}")
        self.bt_log.toggled.connect(self._show_log)
        status = QtWidgets.QHBoxLayout()
        status.setContentsMargins(0, 0, 0, 0)
        status.addWidget(self.bt_log)
        status.addWidget(self.progress, 1)
        self.split = QtWidgets.QSplitter(QtCore.Qt.Vertical)
        self.split.setHandleWidth(7)
        self.split.setStyleSheet(SPLIT_CSS)
        self.split.setChildrenCollapsible(False)
        self.split.addWidget(tabs)
        self.split.addWidget(self.log)
        lay = QtWidgets.QVBoxLayout(self)
        lay.addLayout(top)
        lay.addWidget(self.split, 1)
        lay.addLayout(status)
        self.bt_log.setChecked(self.settings.value("log_open", "false") == "true")
        self._show_log(self.bt_log.isChecked())
        tabs.setCurrentIndex(int(self.settings.value("tab_v3", 0)))   # v3: the 骨架轉 Mixamo tab was removed
        tabs.currentChanged.connect(lambda i: self.settings.setValue("tab_v3", i))
        self._scene_jobs = []
        if self._cmds():      # opening / saving another scene refreshes the scene names and the default output names
            try:
                import maya.api.OpenMaya as om
                for msg in (om.MSceneMessage.kAfterOpen, om.MSceneMessage.kAfterNew, om.MSceneMessage.kAfterSave):
                    self._scene_jobs.append(om.MSceneMessage.addCallback(msg, self._on_scene_changed))
            except Exception:
                pass
        for b in self.findChildren(QtWidgets.QPushButton):      # the big "run" buttons get the accent colour
            if b.minimumHeight() >= 34:
                b.setObjectName("primary")
        self._apply_theme()

    def _apply_theme(self):
        key = self.theme.currentData()
        self.settings.setValue("theme", key)
        dark = key == "dark"
        self.setStyleSheet(THEME_CSS if dark else "")
        self.split.setStyleSheet("" if dark else SPLIT_CSS)
        if hasattr(self, "bsplit"):
            self.bsplit.setStyleSheet("" if dark else SPLIT_CSS)
        self.bt_log.setStyleSheet("QToolButton{border:none;color:#bbb}")
        for b in self.findChildren(HelpBadge):
            b.setStyleSheet(HELP_CSS_DARK if dark else HELP_CSS_MAYA)
            b.pop.setStyleSheet(HELP_POP_DARK if dark else HELP_POP_MAYA)
        from .asMixamoPicker import PartsBox
        for pb in self.findChildren(PartsBox):
            pb.setStyle("tiles" if dark else "glow")

    # ------------------------------------------------------------------------------------------ tab 1
    def _build_convert(self):
        w = QtWidgets.QWidget()
        g = QtWidgets.QGridLayout(w)
        info = QtWidgets.QLabel(u"把 AS「FBX export」匯出的模型＋骨架，轉成可以上傳 Mixamo 的 FBX：\n"
                                u"・主要骨頭改成 Mixamo 名稱　・手指不足五根時補上（無權重）\n"
                                u"・只留一組 UV　・拿掉動畫 Take　（原檔不會被改）")
        info.setStyleSheet("color:#aaa")
        g.addWidget(info, 0, 0, 1, 3)
        g.addWidget(QtWidgets.QLabel(u"AS 匯出的 FBX"), 1, 0)
        self.cv_src = DropLine([".fbx"])
        self.cv_src.setPlaceholderText(u"拖曳 FBX 進來，或按「選擇」")
        self.cv_src.setText(self.settings.value("cv_src", ""))
        self.cv_src.editingFinished.connect(self._cv_auto_dst)
        g.addWidget(self.cv_src, 1, 1)
        b = QtWidgets.QPushButton(u"選擇")
        b.clicked.connect(lambda: self._pick_file(self.cv_src, "FBX (*.fbx)", self._cv_auto_dst))
        g.addWidget(b, 1, 2)
        g.addWidget(QtWidgets.QLabel(u"輸出"), 2, 0)
        self.cv_dst = QtWidgets.QLineEdit(self.settings.value("cv_dst", ""))
        g.addWidget(self.cv_dst, 2, 1)
        b = QtWidgets.QPushButton(u"另存為")
        b.clicked.connect(self._cv_pick_dst)
        g.addWidget(b, 2, 2)
        self.cv_fingers = QtWidgets.QCheckBox(u"手指不足五根時，暫時補上（無權重，只為了讓 Mixamo 認得）")
        self.cv_fingers.setChecked(True)
        g.addWidget(self.cv_fingers, 3, 1, 1, 2)
        self.cv_run = QtWidgets.QPushButton(u"轉換")
        self.cv_run.setMinimumHeight(34)
        self.cv_run.clicked.connect(self._cv_start)
        g.addWidget(self.cv_run, 4, 1, 1, 2)
        g.setRowStretch(5, 1)
        return w

    def _cv_auto_dst(self):
        s = self.cv_src.text().strip()
        if s:
            self.cv_dst.setText(os.path.splitext(s)[0] + "_Mixamo.fbx")

    def _cv_pick_dst(self):
        p, _ = QtWidgets.QFileDialog.getSaveFileName(self, u"輸出", self.cv_dst.text(), "FBX (*.fbx)")
        if p:
            self.cv_dst.setText(p)

    def _cv_start(self):
        src, dst = self.cv_src.text().strip(), self.cv_dst.text().strip()
        if not os.path.isfile(src):
            return self._warn(u"找不到輸入的 FBX")
        if not dst:
            return self._warn(u"請設定輸出檔")
        if os.path.normcase(os.path.abspath(src)) == os.path.normcase(os.path.abspath(dst)):
            return self._warn(u"輸出不能跟輸入同一個檔案")
        if os.path.exists(dst) and not self._ask(u"輸出檔已存在，要覆蓋嗎？\n" + dst):
            return
        self.settings.setValue("cv_src", src)
        self.settings.setValue("cv_dst", dst)
        self._run({"mode": "convert", "src": src, "dst": dst, "fixFingers": self.cv_fingers.isChecked()}, 1)

    # ------------------------------------------------------------------------------------------ tab 2
    def _build_batch(self):
        w = QtWidgets.QWidget()
        v = QtWidgets.QVBoxLayout(w)
        g = QtWidgets.QGridLayout()
        g.addWidget(QtWidgets.QLabel(u"AS 綁好的 rig 檔"), 0, 0)
        self.rig = DropLine([".mb", ".ma"])
        self.rig.setPlaceholderText(u"例如 角色A_Rig.mb（不會被修改）")
        self.rig.setText(self.settings.value("rig", ""))
        self.rig.editingFinished.connect(self._rig_changed)
        g.addWidget(self.rig, 0, 1)
        b = QtWidgets.QPushButton(u"選擇")
        b.clicked.connect(lambda: self._pick_file(self.rig, "Maya (*.mb *.ma)", self._rig_changed))
        g.addWidget(b, 0, 2)
        g.addWidget(QtWidgets.QLabel(u"角色名"), 1, 0)
        self.char = QtWidgets.QLineEdit(self.settings.value("char", ""))
        self.char.setPlaceholderText(u"輸出檔名前綴，例如 角色A")
        self.char.textChanged.connect(self._refresh_names)
        g.addWidget(self.char, 1, 1)
        g.addWidget(QtWidgets.QLabel(u"輸出資料夾"), 2, 0)
        self.outdir = DropLine("dir")
        self.outdir.setText(self.settings.value("outdir", ""))
        self.outdir.textChanged.connect(self._refresh_names)
        g.addWidget(self.outdir, 2, 1)
        b = QtWidgets.QPushButton(u"選擇")
        b.clicked.connect(self._pick_outdir)
        g.addWidget(b, 2, 2)
        v.addLayout(g)

        row = QtWidgets.QHBoxLayout()
        for text, fn in ((u"加入 FBX…", self._add_files), (u"加入資料夾…", self._add_folder),
                         (u"移除選取", self._remove_sel), (u"清空", self._clear)):
            b = QtWidgets.QPushButton(text)
            b.clicked.connect(fn)
            row.addWidget(b)
        row.addStretch(1)
        hint = QtWidgets.QLabel(u"也可以直接把 FBX／資料夾拖進表格")
        hint.setStyleSheet("color:#888")
        row.addWidget(hint)
        v.addLayout(row)
        self.table = MotionTable()
        self.table.filesDropped.connect(self._add_paths)
        self.table.itemChanged.connect(self._item_changed)
        # draggable bar between the file list and the settings below
        self.bsplit = QtWidgets.QSplitter(QtCore.Qt.Vertical)
        self.bsplit.setHandleWidth(7)
        self.bsplit.setStyleSheet(SPLIT_CSS)
        self.bsplit.setChildrenCollapsible(False)
        self.bsplit.addWidget(self.table)
        lower = QtWidgets.QWidget()
        v.addWidget(self.bsplit, 1)
        v = QtWidgets.QVBoxLayout(lower)
        v.setContentsMargins(0, 4, 0, 0)
        # in a scroll area: dragging the bar up/down scrolls the settings instead of squashing them
        self.bt_scroll = self._scroll(lower)
        self.bsplit.addWidget(self.bt_scroll)
        self.bsplit.setStretchFactor(0, 1)
        self.bsplit.setStretchFactor(1, 0)
        sizes = self.settings.value("bsplit_sizes")
        if sizes:
            try:
                self.bsplit.setSizes([int(x) for x in sizes])
            except Exception:
                pass
        self.bsplit.splitterMoved.connect(lambda *a: self.settings.setValue("bsplit_sizes", self.bsplit.sizes()))
        srow = QtWidgets.QHBoxLayout()
        srow.addWidget(QtWidgets.QLabel(u"來源"))
        srow.addWidget(self._source_combo("bt"), 1)
        v.addLayout(srow)

        v.addWidget(self._options_box("bt"))
        from .asMixamoPicker import PartsBox
        self.bt_parts = PartsBox(self.settings, "bt")
        v.addWidget(self.bt_parts)
        self.overwrite = QtWidgets.QCheckBox(u"覆蓋已存在的檔案（預設不勾：已存在的檔案可能是動畫師修過的，會略過）")
        self.overwrite.toggled.connect(self._refresh_names)
        v.addWidget(self.overwrite)
        self.bt_run = QtWidgets.QPushButton(u"開始批量 Retarget（背景處理，Maya 可繼續用）")
        self.bt_run.setMinimumHeight(36)
        self.bt_run.clicked.connect(self._batch_start)
        v.addWidget(self.bt_run)
        self._pin(self.bt_scroll, [self.bt_run])
        note = QtWidgets.QLabel(u"每個動作：開 rig → 30fps → 新 namespace 匯入 → 第 -1 格歸零 → Connect → Bake → "
                                u"Disconnect → 刪掉匯入骨架 → -1 格 key bind pose → Key Reducer → 另存 角色名_動作名.mb")
        note.setWordWrap(True)
        note.setStyleSheet("color:#888")
        v.addWidget(note)
        v.addStretch(1)
        for p in json.loads(self.settings.value("motions", "[]")):
            if os.path.isfile(p[0]):
                self._append(p[0], p[1])
        return w

    def _rig_changed(self):
        r = self.rig.text().strip()
        if not r:
            return
        self.char.setText(_char_from_rig(r))
        if not self.outdir.text().strip():
            self.outdir.setText(os.path.join(os.path.dirname(r), "Animation").replace("\\", "/"))
        self._refresh_names()

    def _pick_outdir(self):
        d = QtWidgets.QFileDialog.getExistingDirectory(self, u"輸出資料夾", self.outdir.text())
        if d:
            self.outdir.setText(d)

    def _add_files(self):
        start = self.settings.value("fbxdir", "")
        files, _ = QtWidgets.QFileDialog.getOpenFileNames(self, u"動作 FBX", start, "FBX (*.fbx)")
        self._add_paths(files)

    def _add_folder(self):
        d = QtWidgets.QFileDialog.getExistingDirectory(self, u"動作資料夾", self.settings.value("fbxdir", ""))
        if d:
            self._add_paths([os.path.join(d, f) for f in sorted(os.listdir(d)) if f.lower().endswith(".fbx")])

    def _add_paths(self, files):
        have = {self.table.item(r, 0).data(QtCore.Qt.UserRole) for r in range(self.table.rowCount())}
        for f in files:
            f = f.replace("\\", "/")
            if f not in have:
                self._append(f, _motion_from_fbx(f))
        if files:
            self.settings.setValue("fbxdir", os.path.dirname(files[0]))
        self._refresh_names()

    def _append(self, path, motion):
        self.table.blockSignals(True)
        r = self.table.rowCount()
        self.table.insertRow(r)
        it = QtWidgets.QTableWidgetItem(os.path.basename(path))
        it.setData(QtCore.Qt.UserRole, path)
        it.setToolTip(path)
        it.setFlags(it.flags() & ~QtCore.Qt.ItemIsEditable)
        self.table.setItem(r, 0, it)
        self.table.setItem(r, 1, QtWidgets.QTableWidgetItem(motion))
        for c in (2, 3):
            x = QtWidgets.QTableWidgetItem("")
            x.setFlags(x.flags() & ~QtCore.Qt.ItemIsEditable)
            self.table.setItem(r, c, x)
        self.table.blockSignals(False)
        self._refresh_names()

    def _remove_sel(self):
        for r in sorted({i.row() for i in self.table.selectedIndexes()}, reverse=True):
            self.table.removeRow(r)
        self._save_motions()

    def _clear(self):
        self.table.setRowCount(0)
        self._save_motions()

    def _item_changed(self, item):
        if item.column() == 1:
            self._refresh_names()

    def _out_path(self, r):
        motion = self.table.item(r, 1).text().strip()
        name = "%s_%s.mb" % (self.char.text().strip(), motion)
        return name, os.path.join(self.outdir.text().strip(), name).replace("\\", "/")

    def _refresh_names(self):
        if not hasattr(self, "table"):
            return
        self.table.blockSignals(True)
        for r in range(self.table.rowCount()):
            name, path = self._out_path(r)
            self.table.item(r, 2).setText(name)
            st = self.table.item(r, 3)
            if os.path.exists(path):
                st.setText(u"已存在 → 會覆蓋" if self.overwrite.isChecked() else u"已存在 → 會略過")
                st.setForeground(QtGui.QColor("#e0a040"))
            else:
                st.setText(u"")
                st.setForeground(QtGui.QColor("#cccccc"))
        self.table.blockSignals(False)
        self._save_motions()

    def _save_motions(self):
        rows = [[self.table.item(r, 0).data(QtCore.Qt.UserRole), self.table.item(r, 1).text()]
                for r in range(self.table.rowCount())]
        self.settings.setValue("motions", json.dumps(rows))

    def _batch_start(self):
        rig, char, outdir = self.rig.text().strip(), self.char.text().strip(), self.outdir.text().strip()
        if not os.path.isfile(rig):
            return self._warn(u"找不到 rig 檔")
        if not char or not outdir:
            return self._warn(u"請填角色名和輸出資料夾")
        if not self.table.rowCount():
            return self._warn(u"還沒加入任何 Mixamo 動作")
        items, names = [], set()
        for r in range(self.table.rowCount()):
            motion = self.table.item(r, 1).text().strip()
            if not motion or re.search(r'[\\/:*?"<>|]', motion):
                return self._warn(u"第 %d 列的動作名稱不合法" % (r + 1))
            name, path = self._out_path(r)
            if name.lower() in names:
                return self._warn(u"輸出檔名重複：" + name)
            if os.path.normcase(os.path.abspath(path)) == os.path.normcase(os.path.abspath(rig)):
                return self._warn(u"輸出檔不能是 rig 檔本身：" + name)
            names.add(name.lower())
            items.append({"fbx": self.table.item(r, 0).data(QtCore.Qt.UserRole), "out": path})
        exist = [os.path.basename(i["out"]) for i in items if os.path.exists(i["out"])]
        if exist and self.overwrite.isChecked():
            if not self._ask(u"以下 %d 個檔案已存在，確定要覆蓋嗎？（動畫師修過的內容會不見）\n\n%s" % (len(exist), "\n".join(exist))):
                return
        for k, val in (("rig", rig), ("char", char), ("outdir", outdir)):
            self.settings.setValue(k, val)
        o = self._opts("bt")
        parts = self.bt_parts.parts()
        if parts == []:
            return self._warn(u"「套用部位」沒有選任何骨頭")
        for r in range(self.table.rowCount()):
            self.table.item(r, 3).setText(u"等待中")
            self.table.item(r, 3).setForeground(QtGui.QColor("#cccccc"))
        self._job_table = self.table
        self._run({"mode": "batch", "rig": rig, "items": items, "overwrite": self.overwrite.isChecked(),
                   "reduce": o["reduce"], "precision": o["precision"], "euler": o["euler"],
                   "source": o["source"], "inPlace": o["in_place"],
                   "twoHand": o["two_hand"], "parts": parts}, len(items))

    # ------------------------------------------------------------------------------------------ tab 3
    def _build_scene(self):
        w = QtWidgets.QWidget()
        v = QtWidgets.QVBoxLayout(w)
        info = QtWidgets.QLabel(u"先在 Maya 打開乾淨的 rig 檔（例如 角色A_Rig.mb），再把動作 FBX 丟進來，直接套到目前場景。")
        info.setWordWrap(True)
        info.setStyleSheet("color:#aaa")
        v.addWidget(info)
        g = QtWidgets.QGridLayout()
        g.addWidget(QtWidgets.QLabel(u"目前場景"), 0, 0)
        self.sc_scene = QtWidgets.QLabel("-")
        self.sc_scene.setTextInteractionFlags(QtCore.Qt.TextSelectableByMouse)
        g.addWidget(self.sc_scene, 0, 1)
        b = QtWidgets.QPushButton(u"重新整理")
        b.clicked.connect(self._scene_refresh)
        g.addWidget(b, 0, 2)
        g.addWidget(QtWidgets.QLabel(u"動作 FBX"), 1, 0)
        self.sc_fbx = DropLine([".fbx"])
        self.sc_fbx.setPlaceholderText(u"拖曳 FBX 進來，或按「選擇」")
        self.sc_fbx.editingFinished.connect(self._scene_fbx_changed)
        g.addWidget(self.sc_fbx, 1, 1)
        b = QtWidgets.QPushButton(u"選擇")
        b.clicked.connect(lambda: self._pick_file(self.sc_fbx, "FBX (*.fbx)", self._scene_fbx_changed))
        g.addWidget(b, 1, 2)
        g.addWidget(QtWidgets.QLabel(u"來源"), 2, 0)
        g.addWidget(self._source_combo("sc"), 2, 1)
        g.addWidget(QtWidgets.QLabel(u"動作名稱"), 3, 0)
        self.sc_motion = QtWidgets.QLineEdit()
        self.sc_motion.textChanged.connect(self._scene_update_out)
        g.addWidget(self.sc_motion, 3, 1)
        g.addWidget(QtWidgets.QLabel(u"另存資料夾"), 4, 0)
        self.sc_outdir = DropLine("dir")
        self.sc_outdir.setText(self.settings.value("sc_outdir", ""))
        self.sc_outdir.textChanged.connect(self._scene_update_out)
        g.addWidget(self.sc_outdir, 4, 1)
        b = QtWidgets.QPushButton(u"選擇")
        b.clicked.connect(lambda: self._pick_dir(self.sc_outdir))
        g.addWidget(b, 4, 2)
        g.addWidget(QtWidgets.QLabel(u"另存檔名"), 5, 0)
        self.sc_out = QtWidgets.QLabel("-")
        g.addWidget(self.sc_out, 5, 1)
        v.addLayout(g)
        v.addWidget(self._options_box("sc"))
        from .asMixamoPicker import PartsBox
        self.sc_parts = PartsBox(self.settings, "sc")
        v.addWidget(self.sc_parts)
        note = QtWidgets.QLabel(u"套用時 Maya 會忙一下（約 10～30 秒）。")
        note.setStyleSheet("color:#888")
        v.addWidget(note)
        self.sc_note = note
        self.sc_run = QtWidgets.QPushButton(u"Retarget 到目前場景")
        self.sc_run.setMinimumHeight(36)
        self.sc_run.clicked.connect(self._scene_apply)
        v.addWidget(self.sc_run)
        v.addStretch(1)
        return w

    # ------------------------------------------------------------------------------------------ AS Retarget
    def _build_asrt(self):
        w = QtWidgets.QWidget()
        v = QtWidgets.QVBoxLayout(w)
        info = QtWidgets.QLabel(u"從<span style='color:#f0b860'>同一隻角色</span>（同一套 AS 控制器）的另一個檔案搬東西到目前場景：\n"
                                u"可以只搬你修動作用的 Anim Layer（例如持槍時修腰和頭的那層），也可以搬整段動作。")
        info.setWordWrap(True)
        info.setStyleSheet("color:#aaa")
        v.addWidget(info)
        g = QtWidgets.QGridLayout()
        g.addWidget(QtWidgets.QLabel(u"目前場景"), 0, 0)
        self.ar_scene = QtWidgets.QLabel("-")
        g.addWidget(self.ar_scene, 0, 1)
        b = QtWidgets.QPushButton(u"重新整理")
        b.clicked.connect(self._asrt_refresh)
        g.addWidget(b, 0, 2)
        g.addWidget(QtWidgets.QLabel(u"來源檔"), 1, 0)
        self.ar_src = DropLine([".mb", ".ma"])
        self.ar_src.setPlaceholderText(u"拖曳修好的 .mb / .ma 進來，或按「選擇」")
        self.ar_src.setText(self.settings.value("ar_src", ""))
        self.ar_src.editingFinished.connect(self._asrt_src_changed)
        g.addWidget(self.ar_src, 1, 1)
        b = QtWidgets.QPushButton(u"選擇")
        b.clicked.connect(lambda: self._pick_file(self.ar_src, "Maya (*.mb *.ma)", self._asrt_src_changed))
        g.addWidget(b, 1, 2)
        g.addWidget(QtWidgets.QLabel(u"要搬什麼"), 2, 0)
        row = QtWidgets.QHBoxLayout()
        self.ar_mode_layers = QtWidgets.QRadioButton(u"修正（Anim Layer＋Base 上的修改）")
        self.ar_mode_whole = QtWidgets.QRadioButton(u"整段動作")
        (self.ar_mode_whole if self.settings.value("ar_mode", "layers") == "whole" else self.ar_mode_layers).setChecked(True)
        row.addWidget(self.ar_mode_layers)
        row.addWidget(self.ar_mode_whole)
        row.addWidget(self._help(u"<span style='color:#f0b860'>修正用的 Anim Layer</span>：把來源檔裡你勾的 layer 原封不動複製過來"
                                 u"（Additive／Override、權重、key 都一樣），疊在目前場景的動作上面，"
                                 u"底下 retarget 的 key 一個都不動。修正層只有一格 key 的話，就是整段固定偏移，任何長度的動作都適用。<br>"
                                 u"<span style='color:#f0b860'>整段動作</span>：把來源的動作（各層加總後的結果）搬過來。"))
        row.addStretch(1)
        g.addLayout(row, 2, 1, 1, 2)
        v.addLayout(g)

        self.ar_lbox = QtWidgets.QWidget()
        lv = QtWidgets.QVBoxLayout(self.ar_lbox)
        lv.setContentsMargins(0, 0, 0, 0)
        row = QtWidgets.QHBoxLayout()
        row.addWidget(QtWidgets.QLabel(u"來源檔的 Anim Layer（勾要搬的修正層）"))
        row.addStretch(1)
        b = QtWidgets.QPushButton(u"重新讀取")
        b.clicked.connect(self._asrt_load_layers)
        row.addWidget(b)
        lv.addLayout(row)
        self.ar_layers = QtWidgets.QListWidget()
        self.ar_layers.setMinimumHeight(70)
        self.ar_layers.setMaximumHeight(120)
        lv.addWidget(self.ar_layers)
        row = QtWidgets.QHBoxLayout()
        row.addWidget(QtWidgets.QLabel(u"Base 動畫跟目前場景不一樣的控制器（只有同一段動作才需要勾）"))
        row.addWidget(self._help(u"來源檔裡<span style='color:#f0b860'>直接改在 Base Animation 上</span>的修改（沒有放進 layer），"
                                 u"例如 Gun_Ctrl 的位置、肩胛位移、左手 IK。<br>"
                                 u"勾的控制器會放進一個 Override layer「BaseFix_…」，排在搬過來的修正層下面，"
                                 u"讓它們跟來源檔一樣；修正層的偏移照樣疊在上面。<br>"
                                 u"<span style='color:#f0b860'>只在來源和目前場景是同一段動作時才勾</span>：動作不同時 Base 本來就全部不一樣，勾了會把整段動作蓋掉。"))
        row.addStretch(1)
        for text, state in ((u"全選", QtCore.Qt.Checked), (u"全不選", QtCore.Qt.Unchecked)):
            b = QtWidgets.QPushButton(text)
            b.clicked.connect(lambda _=False, st=state: [self.ar_base.item(i).setCheckState(st)
                                                         for i in range(self.ar_base.count())
                                                         if self.ar_base.item(i).data(QtCore.Qt.UserRole)])
            row.addWidget(b)
        lv.addLayout(row)
        self.ar_base = QtWidgets.QListWidget()
        self.ar_base.setMinimumHeight(70)
        self.ar_base.setMaximumHeight(140)
        lv.addWidget(self.ar_base)
        v.addWidget(self.ar_lbox)

        from .asMixamoPicker import PartsBox
        self.ar_parts = PartsBox(self.settings, "ar")
        v.addWidget(self.ar_parts)
        row = QtWidgets.QHBoxLayout()
        self.ar_others = QtWidgets.QCheckBox(u"也搬其他控制器（Main、武器、帽子、尾巴…）")
        self.ar_others.setChecked(self.settings.value("ar_others", "true") == "true")
        row.addWidget(self.ar_others)
        row.addWidget(self._help(u"人形圖上沒有的控制器，例如 Main、Gun_Ctrl、帽子或尾巴的 FK。<br>"
                                 u"選「全身」時一定會搬；只搬部分骨頭時，由這個勾選決定要不要一起搬。"))
        row.addStretch(1)
        v.addLayout(row)
        self.ar_wbox = QtWidgets.QWidget()
        row = QtWidgets.QHBoxLayout(self.ar_wbox)
        row.setContentsMargins(0, 0, 0, 0)
        self.ar_layer_on = QtWidgets.QCheckBox(u"放在新的 Anim Layer")
        self.ar_layer_on.setChecked(self.settings.value("ar_layer_on", "true") == "true")
        self.ar_layer = QtWidgets.QLineEdit()
        self.ar_layer.setPlaceholderText(u"Layer 名稱")
        self.ar_layer_on.toggled.connect(self.ar_layer.setEnabled)
        self.ar_layer.setEnabled(self.ar_layer_on.isChecked())
        row.addWidget(self.ar_layer_on)
        row.addWidget(self.ar_layer, 1)
        row.addWidget(self._help(u"<span style='color:#f0b860'>勾選</span>：建立一個 Override Layer 放搬過來的動畫，原本的動畫一個 key 都不動。<br>"
                                 u"<span style='color:#f0b860'>不勾</span>：直接換掉那些控制器原本的曲線。<br>"
                                 u"來源檔有 Anim Layer 時，會先把各層加起來的結果烘成 key（每格一個）再搬。"))
        v.addWidget(self.ar_wbox)
        self.ar_run = QtWidgets.QPushButton(u"搬到目前場景")
        self.ar_run.setMinimumHeight(36)
        self.ar_run.clicked.connect(self._asrt_apply)
        v.addWidget(self.ar_run)
        v.addStretch(1)
        self.ar_mode_layers.toggled.connect(self._asrt_mode_changed)
        self._asrt_mode_changed()
        self._asrt_src_changed(load=False)
        return w

    def _asrt_mode_changed(self, *a):
        layers = self.ar_mode_layers.isChecked()
        self.ar_lbox.setVisible(layers)
        self.ar_wbox.setVisible(not layers)
        self.ar_run.setText(u"把勾選的 Layer 搬到目前場景" if layers else u"AS Retarget 到目前場景")
        if layers and not self.ar_layers.count() and os.path.isfile(self.ar_src.text().strip()) and self._cmds():
            self._asrt_load_layers()

    def _asrt_src_changed(self, load=True):
        src = self.ar_src.text().strip()
        if src:
            self.ar_layer.setText(re.sub(r"[^A-Za-z0-9_]", "_", os.path.splitext(os.path.basename(src))[0]))
        self.ar_layers.clear()
        self.ar_base.clear()
        if load and self.ar_mode_layers.isChecked() and os.path.isfile(src):
            self._asrt_load_layers()

    def _asrt_load_layers(self):
        cmds = self._cmds()
        src = self.ar_src.text().strip()
        if not cmds or not os.path.isfile(src):
            return
        from . import asMixamoASRetarget as asrt
        QtWidgets.QApplication.setOverrideCursor(QtCore.Qt.WaitCursor)
        try:
            cmds.refresh(suspend=True)
            try:
                scan = asrt.scan_source(src)
            finally:
                cmds.refresh(suspend=False)
        except Exception as e:
            scan = {"layers": [], "base": []}
            self._warn(u"讀取來源檔失敗：%s" % e)
        finally:
            QtWidgets.QApplication.restoreOverrideCursor()
        layers = scan["layers"]
        self.ar_base.clear()
        for c in scan["base"]:
            it = QtWidgets.QListWidgetItem(u"%s　　差 %.2f · %d 個屬性" % (c["ctrl"], c["max"], len(c["plugs"])))
            it.setData(QtCore.Qt.UserRole, c["ctrl"])
            it.setData(QtCore.Qt.UserRole + 1, c["plugs"])
            it.setToolTip(", ".join(c["plugs"]))
            it.setFlags(it.flags() | QtCore.Qt.ItemIsUserCheckable)
            it.setCheckState(QtCore.Qt.Unchecked)       # off by default: on a different motion everything differs
            self.ar_base.addItem(it)
        if not scan["base"]:
            it = QtWidgets.QListWidgetItem(u"（Base 動畫跟目前場景一樣）")
            it.setFlags(QtCore.Qt.NoItemFlags)
            self.ar_base.addItem(it)
        checked = set(json.loads(self.settings.value("ar_layers_checked", "[]")))
        self.ar_layers.clear()
        for L in reversed(layers):           # top layer first, like Maya's layer editor
            if L["range"] is None:
                rng = u"沒有 key"
            elif L["range"][0] == L["range"][1]:
                rng = u"只有第 %g 格 = 整段固定偏移" % L["range"][0]
            else:
                rng = u"影格 %g-%g" % L["range"]
            it = QtWidgets.QListWidgetItem(u"%s　　%s · 權重 %.2f · %d 個屬性 · %s%s" % (
                L["name"], u"Override" if L["override"] else u"Additive", L["weight"], L["attrs"], rng,
                u" · 靜音中" if L["mute"] else u""))
            it.setData(QtCore.Qt.UserRole, L["name"])
            it.setFlags(it.flags() | QtCore.Qt.ItemIsUserCheckable)
            it.setCheckState(QtCore.Qt.Checked if L["name"] in checked else QtCore.Qt.Unchecked)
            self.ar_layers.addItem(it)
        if not layers:
            it = QtWidgets.QListWidgetItem(u"（這個檔案沒有 Anim Layer）")
            it.setFlags(QtCore.Qt.NoItemFlags)
            self.ar_layers.addItem(it)

    def _asrt_checked_layers(self):
        out = []
        for i in range(self.ar_layers.count()):
            it = self.ar_layers.item(i)
            if it.data(QtCore.Qt.UserRole) and it.checkState() == QtCore.Qt.Checked:
                out.append(it.data(QtCore.Qt.UserRole))
        return out

    def _asrt_refresh(self):
        path, ok = self._scene_info()
        name = os.path.basename(path) if path else u"（未存檔的場景）"
        self.ar_scene.setText(name + (u"　✔ AS rig" if ok else u"　✘ 找不到 AS 骨架"))
        self.ar_scene.setStyleSheet("color:%s" % ("#70d070" if ok else "#ff6060"))
        try:
            from . import asMixamoASRetarget as asrt
            self.ar_parts.setRigBones(asrt.pickable_bones() if ok else None)
        except Exception:
            self.ar_parts.setRigBones(None)

    def _asrt_apply(self):
        cmds = self._cmds()
        if not cmds:
            return self._warn(u"要在 Maya 裡使用")
        path, ok = self._scene_info()
        if not ok:
            return self._warn(u"目前場景不是 AS 綁好的 rig（找不到 DeformationSystem / RootX_M）")
        src = self.ar_src.text().strip()
        if not os.path.isfile(src):
            return self._warn(u"找不到來源檔")
        parts = self.ar_parts.parts()
        if parts == []:
            return self._warn(u"「套用部位」沒有選任何骨頭")
        layers_mode = self.ar_mode_layers.isChecked()
        names, layer = [], None
        base_plugs = []
        if layers_mode:
            names = self._asrt_checked_layers()
            for i in range(self.ar_base.count()):
                it = self.ar_base.item(i)
                if it.data(QtCore.Qt.UserRole) and it.checkState() == QtCore.Qt.Checked:
                    base_plugs += it.data(QtCore.Qt.UserRole + 1)
            if not names and not base_plugs:
                return self._warn(u"還沒有勾要搬的 Anim Layer 或 Base 修改（清單是空的話按「重新讀取」）")
            self.settings.setValue("ar_layers_checked", json.dumps(names))
        elif self.ar_layer_on.isChecked():
            layer = self.ar_layer.text().strip() or "AS_Retarget"
        elif not self._ask(u"沒有勾「放在新的 Anim Layer」：選到的控制器原本的動畫曲線會被換掉。\n\n確定要繼續嗎？"):
            return
        for k, val in (("ar_src", src), ("ar_others", self.ar_others.isChecked()),
                       ("ar_layer_on", self.ar_layer_on.isChecked()), ("ar_mode", "layers" if layers_mode else "whole")):
            self.settings.setValue(k, ("true" if val else "false") if isinstance(val, bool) else val)
        from . import asMixamoASRetarget as asrt
        self.log.clear()
        self.progress.setRange(0, 0)
        QtWidgets.QApplication.setOverrideCursor(QtCore.Qt.WaitCursor)
        self.ar_run.setEnabled(False)

        def cb(msg):
            self.log.appendPlainText(msg)
            QtWidgets.QApplication.processEvents()

        QtWidgets.QApplication.processEvents()
        cmds.undoInfo(openChunk=True, chunkName="asRetarget")
        try:
            cmds.refresh(suspend=True)
            try:
                if layers_mode:
                    asrt.copy_layers(src, names, parts=parts, others=self.ar_others.isChecked(), cb=cb,
                                     base_plugs=base_plugs)
                else:
                    res = asrt.as_retarget(src, parts=parts, layer=layer, others=self.ar_others.isChecked(), cb=cb)
            finally:
                cmds.refresh(suspend=False)
            cmds.refresh()
            if not layers_mode and res.get("otherCharacter"):
                self._warn(u"來源和目前場景看起來不是同一隻角色（骨頭長度差 %d%%）。\n\n"
                           u"AS Retarget 是照抄控制器數值，兩隻的 bind pose 不同（例如 A-pose 和 T-pose）時，"
                           u"手腳會整段偏掉。\n\n換角色請改用「Retarget」分頁：在來源檔用「匯出 FBX」導出動作，"
                           u"再套到這隻角色。" % res["otherCharacter"])
        except Exception as e:
            import traceback
            self.log.appendPlainText(u"失敗：%s\n%s" % (e, traceback.format_exc()))
            self.bt_log.setChecked(True)
            self._warn(u"失敗：%s" % e)
        finally:
            cmds.undoInfo(closeChunk=True)
            QtWidgets.QApplication.restoreOverrideCursor()
            self.progress.setRange(0, 1)
            self.progress.setValue(1)
            self.ar_run.setEnabled(True)

    def _on_scene_changed(self, *a):
        """Another scene was opened / created / saved under a new name: follow it (a name typed for the previous
        scene no longer applies)."""
        def run():
            try:
                self._rec_out_edited = False
                self._rec_default_out()
            except Exception:
                pass
            for f in (getattr(self, "_ex_refresh", None), getattr(self, "_scene_refresh", None)):
                try:
                    f and f()
                except Exception:
                    pass
        try:
            QtCore.QTimer.singleShot(0, run)
        except RuntimeError:     # window already deleted
            pass

    def _kill_scene_jobs(self):
        for j in getattr(self, "_scene_jobs", []) or []:
            try:
                import maya.api.OpenMaya as om
                om.MMessage.removeCallback(j)
            except Exception:
                pass
        self._scene_jobs = []

    def _cmds(self):
        try:
            import maya.cmds as cmds
            cmds.about(version=True)
            return cmds
        except Exception:
            return None

    def _core(self):
        from . import asMixamoCore as core
        return core

    def _scene_info(self):
        cmds = self._cmds()
        if not cmds:
            return "", False
        return cmds.file(q=True, sceneName=True) or "", self._core().is_as_rig()

    def _scene_refresh(self):
        path, ok = self._scene_info()
        name = os.path.basename(path) if path else u"（未存檔的場景）"
        self.sc_scene.setText(name + (u"　✔ AS rig" if ok else u"　✘ 找不到 AS 骨架"))
        self.sc_scene.setStyleSheet("color:%s" % ("#70d070" if ok else "#ff6060"))
        self.sc_scene.setToolTip(path)
        try:
            self.sc_parts.setRigBones(self._core().retarget_bones() if ok else None)
        except Exception:
            self.sc_parts.setRigBones(None)
        if path and not self.sc_outdir.text().strip():
            self.sc_outdir.setText(os.path.join(os.path.dirname(path), "Animation").replace("\\", "/"))
        self._scene_update_out()

    def _scene_fbx_changed(self):
        f = self.sc_fbx.text().strip()
        if f:
            self.sc_motion.setText(_motion_from_fbx(f))
        self._scene_update_out()

    def _scene_out_path(self):
        path, _ = self._scene_info()
        char = _char_from_rig(path) if path else "Character"
        motion = self.sc_motion.text().strip()
        if not motion or not self.sc_outdir.text().strip():
            return ""
        return os.path.join(self.sc_outdir.text().strip(), "%s_%s.mb" % (char, motion)).replace("\\", "/")

    def _scene_update_out(self):
        out = self._scene_out_path()
        if not out:
            self.sc_out.setText("-")
            return
        ex = os.path.exists(out)
        self.sc_out.setText(os.path.basename(out) + (u"　（已存在）" if ex else ""))
        self.sc_out.setStyleSheet("color:%s" % ("#e0a040" if ex else "#cccccc"))

    def _pick_dir(self, line):
        d = QtWidgets.QFileDialog.getExistingDirectory(self, u"資料夾", line.text())
        if d:
            line.setText(d)

    def _scene_apply(self):
        cmds = self._cmds()
        if not cmds:
            return self._warn(u"要在 Maya 裡使用")
        core = self._core()
        path, ok = self._scene_info()
        if not ok:
            return self._warn(u"目前場景不是 AS 綁好的 rig（找不到 DeformationSystem / RootX_M）")
        fbx = self.sc_fbx.text().strip()
        if not os.path.isfile(fbx):
            return self._warn(u"找不到動作 FBX")
        motion = self.sc_motion.text().strip()
        if not motion or re.search(r'[\\/:*?"<>|]', motion):
            return self._warn(u"動作名稱不合法")
        out = self._scene_out_path()
        if not out:
            return self._warn(u"請設定另存資料夾")
        if path and os.path.normcase(os.path.abspath(out)) == os.path.normcase(os.path.abspath(path)):
            return self._warn(u"另存檔名跟目前的 rig 檔一樣，請改動作名稱")
        parts = self.sc_parts.parts()
        if parts == []:
            return self._warn(u"「套用部位」沒有選任何骨頭")
        if parts is None and core.scene_has_control_animation():
            if not self._ask(u"目前場景的控制器已經有動畫了，套用會蓋掉動作範圍內的 key。\n"
                             u"建議重新打開乾淨的 rig 檔再套。\n\n還是要繼續嗎？"):
                return
        box = QtWidgets.QMessageBox(self)
        box.setWindowTitle(TITLE)
        box.setIcon(QtWidgets.QMessageBox.Question)
        box.setText(u"套用後要另存新檔嗎？（保護乾淨的 rig 檔）\n\n" + out +
                    (u"\n\n⚠ 這個檔案已經存在，會被覆蓋" if os.path.exists(out) else ""))
        box.setInformativeText(u"選「只套用，先不存」時，場景名稱也會先改成這個新檔名（不存檔），"
                               u"之後按 Ctrl+S 不會蓋到乾淨的 rig。")
        b_save = box.addButton(u"套用並另存新檔", QtWidgets.QMessageBox.AcceptRole)
        b_only = box.addButton(u"只套用，先不存", QtWidgets.QMessageBox.ActionRole)
        box.addButton(u"取消", QtWidgets.QMessageBox.RejectRole)
        box.setDefaultButton(b_save)
        box.exec()
        if box.clickedButton() not in (b_save, b_only):
            return
        save = box.clickedButton() is b_save
        self.settings.setValue("sc_outdir", self.sc_outdir.text().strip())
        o = self._opts("sc")

        self.log.clear()
        self.log.appendPlainText(u"套用 %s → %s" % (os.path.basename(fbx), os.path.basename(out)))
        self.progress.setRange(0, 0)
        QtWidgets.QApplication.setOverrideCursor(QtCore.Qt.WaitCursor)
        self.sc_run.setEnabled(False)

        def cb(msg):
            self.log.appendPlainText(msg)
            QtWidgets.QApplication.processEvents()

        QtWidgets.QApplication.processEvents()
        try:
            cmds.refresh(suspend=True)
            try:
                r = core.apply_motion(fbx, reduce=o["reduce"], precision=o["precision"], precision_mode=1,
                                      euler=o["euler"], cb=cb, source=o["source"], in_place=o["in_place"],
                                      two_hand=o["two_hand"], parts=parts)
            finally:
                cmds.refresh(suspend=False)
            if not os.path.isdir(os.path.dirname(out)):
                os.makedirs(os.path.dirname(out))
            cmds.file(rename=out)
            if save:
                cmds.file(save=True, type="mayaBinary", force=True)
            msg = u"完成：影格 %d-%d，連上 %d 根" % (r["start"], r["end"], r["connected"])
            msg += u"（%s%s）" % (r.get("sourceLabel", ""), (u"，比例 x%.3f" % r["scale"]) if r.get("standard") else u"")
            if o["reduce"]:
                msg += u"，key %d→%d" % (r["keysBefore"], r["keysAfter"])
            self.log.appendPlainText(msg)
            self.log.appendPlainText((u"已另存：" if save else u"場景已改名（尚未存檔）：") + out)
            cmds.refresh()
        except Exception as e:
            import traceback
            self.log.appendPlainText(u"失敗：%s\n%s" % (e, traceback.format_exc()))
            self.bt_log.setChecked(True)
            self._warn(u"失敗：%s" % e)
        finally:
            QtWidgets.QApplication.restoreOverrideCursor()
            self.progress.setRange(0, 1)
            self.progress.setValue(1)
            self.sc_run.setEnabled(True)
            self._scene_refresh()

    # ------------------------------------------------------------------------------------------ weapon tab
    def _step(self, n, title):
        """Step header: orange number badge + title (no bold: CJK bold blurs at this size)."""
        w = QtWidgets.QWidget()
        h = QtWidgets.QHBoxLayout(w)
        h.setContentsMargins(0, 10, 0, 4)
        badge = QtWidgets.QLabel(str(n))
        badge.setFixedSize(24, 24)
        badge.setAlignment(QtCore.Qt.AlignCenter)
        badge.setStyleSheet("QLabel{background:%s;color:#1a1a1a;border-radius:12px;font-size:14px}" % ACCENT)
        h.addWidget(badge)
        t = QtWidgets.QLabel(title)
        t.setStyleSheet("QLabel{color:#f2f2f2;font-size:14px}")
        h.addWidget(t)
        line = QtWidgets.QFrame()
        line.setFixedHeight(1)
        line.setStyleSheet("QFrame{background:#3a3a3a;border:none}")
        h.addWidget(line, 1)
        return w

    def _build_gun(self):
        w = QtWidgets.QWidget()
        v = QtWidgets.QVBoxLayout(w)
        info = QtWidgets.QLabel(u"在暫存場景裡套開槍姿勢、把槍和左手調到你要的位置（槍的模型也能直接改），"
                                u"按「確定」才回到乾淨的 A/T pose rig 把槍綁上去並另存新檔，原 rig 不動。")
        info.setWordWrap(True)
        info.setStyleSheet("color:#aaa")
        v.addWidget(info)

        v.addWidget(self._step(1, u"選乾淨 rig，套開槍姿勢"))
        g = QtWidgets.QGridLayout()
        g.setColumnMinimumWidth(0, 70)
        g.addWidget(QtWidgets.QLabel(u"乾淨 rig"), 0, 0)
        self.gs_rig = DropLine([".mb", ".ma"])
        self.gs_rig.setPlaceholderText(u"A/T pose、還沒有槍的 AS rig（拖進來或按「選擇」）")
        self.gs_rig.setText(self.settings.value("gs_rig", ""))
        self.gs_rig.textChanged.connect(self._gs_default_out)
        g.addWidget(self.gs_rig, 0, 1)
        row = QtWidgets.QHBoxLayout()
        b = QtWidgets.QPushButton(u"選擇")
        b.clicked.connect(lambda: self._pick_file(self.gs_rig, "Maya (*.mb *.ma)"))
        row.addWidget(b)
        b = QtWidgets.QPushButton(u"用目前場景")
        b.clicked.connect(self._gs_use_scene)
        row.addWidget(b)
        g.addLayout(row, 0, 2)
        g.addWidget(QtWidgets.QLabel(u"開槍姿勢"), 1, 0)
        row = QtWidgets.QHBoxLayout()
        self.gs_ref = DropLine([".fbx"])
        self.gs_ref.setPlaceholderText(u"開槍／瞄準動作 FBX（例如 Mixamo 的 Firing Rifle）")
        from . import asMixamoGun as _g
        self.gs_ref.setText(self.settings.value("gs_ref", "") or (_g.DEFAULT_REF if os.path.isfile(_g.DEFAULT_REF) else ""))
        row.addWidget(self.gs_ref, 1)
        b = QtWidgets.QPushButton(u"選擇")
        b.clicked.connect(lambda: self._pick_file(self.gs_ref, "FBX (*.fbx)"))
        row.addWidget(b)
        row.addWidget(QtWidgets.QLabel(u"第"))
        self.gs_frame = QtWidgets.QSpinBox()
        self.gs_frame.setRange(0, 1000)
        self.gs_frame.setValue(int(self.settings.value("gs_frame", 0)))
        row.addWidget(self.gs_frame)
        row.addWidget(QtWidgets.QLabel(u"格"))
        row.addWidget(self._help(u"拿來擺開槍姿勢的動作，例如 Mixamo 免費的「Firing Rifle」（第 0 格是瞄準），選一次就會記住。<br>"
                                 u"Mixamo 的動作檔不能隨工具散佈，所以要自己下載。<br>"
                                 u"姿勢只用來判斷槍和左手的位置，不會留在帶槍的 rig 裡。"))
        row.addStretch(1)
        g.addLayout(row, 1, 1, 1, 2)
        v.addLayout(g)
        row = QtWidgets.QHBoxLayout()
        self.gs_start = QtWidgets.QPushButton(u"開始調整")
        self.gs_start.setMinimumHeight(30)
        self.gs_start.clicked.connect(self._gs_start)
        row.addWidget(self.gs_start, 2)
        b = QtWidgets.QPushButton(u"重新調整帶槍 rig…")
        b.setMinimumHeight(30)
        b.clicked.connect(self._gs_readjust)
        row.addWidget(b, 1)
        row.addWidget(self._help(u"選一個已經用這個工具加過槍的 rig（例如 角色A_Rig_Gun.mb），"
                                 u"會帶著它現在的槍和握點回到調整場景，改完再另存新版。"))
        v.addLayout(row)
        self.gs_state = QtWidgets.QLabel(u"")
        self.gs_state.setWordWrap(True)
        v.addWidget(self.gs_state)

        v.addWidget(self._step(2, u"在 viewport 調整槍、模型和左手"))
        tools = QtWidgets.QGridLayout()
        self.gs_tools = []
        for i, (text, fn, tip) in enumerate((
                (u"選槍（位置／角度）", lambda: self._gs_do(lambda gun: gun.setup_select("ctrl")), u"選 GunSetup_Ctrl：移動、旋轉、縮放整把槍"),
                (u"選槍模型", lambda: self._gs_do(lambda gun: gun.setup_select("geo")), u"選 Gun_Geo：可以直接改點線面"),
                (u"選左手 IK", lambda: self._gs_do(lambda gun: gun.setup_select("hand")), u"選 IKArm_L：自己擺左手握的位置"),
                (u"左手貼到握點", self._gs_snap, u"左手切 IK，貼到槍上預設的握點（會跟著槍移動）"),
                (u"槍回預設位置", lambda: self._gs_do(lambda gun: gun.setup_reset_gun()), u"GunSetup_Ctrl 歸零"),
                (u"換成我的模型…", self._gs_model, u"匯入 .mb／.ma／.fbx／.obj 取代方塊槍，再自己擺到手上"))):
            bt = QtWidgets.QPushButton(text)
            bt.setToolTip(tip)
            bt.clicked.connect(fn)
            tools.addWidget(bt, i // 3, i % 3)
            self.gs_tools.append(bt)
        v.addLayout(tools)
        hint = QtWidgets.QLabel(u"姿勢只用來判斷位置；槍、模型、左手的位置會被記下來。")
        hint.setStyleSheet("color:#888")
        v.addWidget(hint)

        v.addWidget(self._step(3, u"確定，綁到乾淨 rig"))
        row = QtWidgets.QHBoxLayout()
        lb = QtWidgets.QLabel(u"輸出")
        lb.setMinimumWidth(70)
        row.addWidget(lb)
        self.gs_out = QtWidgets.QLineEdit()
        row.addWidget(self.gs_out, 1)
        b = QtWidgets.QPushButton(u"另存為")
        b.clicked.connect(self._gs_pick_out)
        row.addWidget(b)
        v.addLayout(row)
        self.gs_finish = QtWidgets.QPushButton(u"確定，綁到乾淨 rig")
        self.gs_finish.setMinimumHeight(38)
        self.gs_finish.clicked.connect(self._gs_finish)
        v.addWidget(self.gs_finish)
        note = QtWidgets.QLabel(u"會建立：Gun_Ctrl（gunInHand 右手／原地、showGun 顯示，預設隱藏）、左手握點、"
                                u"IKArm_L.followGun（左手跟槍）、武器骨頭 Gun_Weapon（掛在右手下，匯出 FBX 會帶槍的動作）。")
        note.setWordWrap(True)
        note.setStyleSheet("color:#888")
        v.addWidget(note)
        v.addStretch(1)
        self._gs_default_out()
        return w

    # ---------------------------------------------------------------- 雙手武器：調整後加槍
    def _gun_mod(self):
        from . import asMixamoGun as gun
        return gun

    def _gs_default_out(self, *a):
        rig = self.gs_rig.text().strip()
        if rig:
            self.gs_out.setText(self._gun_out(rig))

    def _gs_use_scene(self):
        cmds = self._cmds()
        if not cmds:
            return
        gun = self._gun_mod()
        path = cmds.getAttr(gun.SETUP + ".cleanRig") if gun.in_setup() else cmds.file(q=True, sceneName=True)
        if path:
            self.gs_rig.setText(path)

    def _gs_refresh(self):
        cmds = self._cmds()
        if not cmds:
            return
        gun = self._gun_mod()
        on = gun.in_setup()
        if on:
            rig = cmds.getAttr(gun.SETUP + ".cleanRig")
            if self.gs_rig.text().strip() != rig:
                self.gs_rig.setText(rig)
            self.gs_state.setText(u"● 調整中：%s（開槍姿勢第 %d 格）。調好後做步驟 3。" % (os.path.basename(rig),
                                                                              cmds.getAttr(gun.SETUP + ".refFrame")))
            self.gs_state.setStyleSheet("color:#f0a030")
        else:
            self.gs_state.setText(u"目前場景不是調整場景。先做步驟 1。")
            self.gs_state.setStyleSheet("color:#888")
        for b in self.gs_tools + [self.gs_finish]:
            b.setEnabled(on)

    def _gs_busy(self, fn, title):
        cmds = self._cmds()
        if not cmds:
            return self._warn(u"要在 Maya 裡使用")
        self.log.clear()
        self.progress.setRange(0, 0)
        QtWidgets.QApplication.setOverrideCursor(QtCore.Qt.WaitCursor)

        def cb(msg):
            self.log.appendPlainText(msg)
            QtWidgets.QApplication.processEvents()
        QtWidgets.QApplication.processEvents()
        try:
            cmds.refresh(suspend=True)
            try:
                return fn(cb)
            finally:
                cmds.refresh(suspend=False)
                cmds.refresh()
        except Exception as e:
            import traceback
            self.log.appendPlainText(u"%s失敗：%s\n%s" % (title, e, traceback.format_exc()))
            self.bt_log.setChecked(True)
            self._warn(u"%s失敗：%s" % (title, e))
        finally:
            QtWidgets.QApplication.restoreOverrideCursor()
            self.progress.setRange(0, 1)
            self.progress.setValue(1)
            self._gs_refresh()

    def _gs_scene_ok(self):
        cmds = self._cmds()
        if cmds and cmds.file(q=True, modified=True):
            return self._ask(u"目前場景有還沒存的修改，繼續會直接關掉它（不會存）。\n\n確定要繼續嗎？")
        return True

    def _gs_ref_ok(self):
        ref = self.gs_ref.text().strip()
        if not os.path.isfile(ref):
            self._warn(u"請先選「開槍姿勢」用的動作 FBX（例如 Mixamo 免費的 Firing Rifle，下載一次就好）")
            return False
        self.settings.setValue("gs_ref", ref)
        self._gun_mod().REF_OVERRIDE = ref
        return True

    def _gs_start(self):
        rig = self.gs_rig.text().strip()
        if not os.path.isfile(rig):
            return self._warn(u"找不到乾淨 rig 檔")
        if not self._gs_ref_ok():
            return
        if not self._gs_scene_ok():
            return
        self.settings.setValue("gs_rig", rig)
        self.settings.setValue("gs_frame", self.gs_frame.value())
        gun = self._gun_mod()
        self._gs_busy(lambda cb: gun.setup_start(rig, frame=self.gs_frame.value(), cb=cb), u"開始調整")

    def _gs_readjust(self):
        if not self._gs_ref_ok():
            return
        f, _ = QtWidgets.QFileDialog.getOpenFileName(self, u"選帶槍的 rig", self.settings.value("gun_dir", ""), "Maya (*.mb *.ma)")
        if not f or not self._gs_scene_ok():
            return
        gun = self._gun_mod()

        def run(cb):
            try:
                return gun.setup_from_gun_rig(f, frame=self.gs_frame.value(), cb=cb)
            except RuntimeError as e:
                if u"乾淨" not in str(e):
                    raise
            clean, _ = QtWidgets.QFileDialog.getOpenFileName(self, u"這個帶槍 rig 的乾淨版本（沒有槍的 rig）",
                                                             os.path.dirname(f), "Maya (*.mb *.ma)")
            if clean:
                return gun.setup_from_gun_rig(f, clean_rig=clean, frame=self.gs_frame.value(), cb=cb)
        self._gs_busy(run, u"重新調整")
        self.gs_out.setText(f.replace("\\\\", "/"))

    def _gs_do(self, fn):
        cmds = self._cmds()
        if not cmds:
            return
        try:
            fn(self._gun_mod())
        except Exception as e:
            self._warn(str(e))

    def _gs_snap(self):
        def fn(gun):
            gap = gun.setup_snap_left_hand()
            if gap > 0.5:
                self._warn(u"左手還差 %.1f cm 搆不到握點（手比較短）。\n請把槍往身體拉近，或調整姿勢後再按一次。" % gap)
        self._gs_do(fn)

    def _gs_model(self):
        f, _ = QtWidgets.QFileDialog.getOpenFileName(self, u"槍模型", self.settings.value("gun_model", ""),
                                                     "Model (*.mb *.ma *.fbx *.obj)")
        if f:
            self.settings.setValue("gun_model", f)
            self._gs_do(lambda gun: gun.setup_replace_model(f, autoscale=True))

    def _gs_pick_out(self):
        f, _ = QtWidgets.QFileDialog.getSaveFileName(self, u"輸出帶槍 rig", self.gs_out.text(), "Maya Binary (*.mb);;Maya ASCII (*.ma)")
        if f:
            self.gs_out.setText(f)

    def _gs_finish(self):
        out = self.gs_out.text().strip()
        if not out:
            return self._warn(u"請設定輸出檔名")
        if not os.path.splitext(out)[1]:
            out += ".mb"
        if os.path.exists(out) and not self._ask(u"已經有這個檔案，要覆蓋嗎？\n" + out):
            return
        gun = self._gun_mod()
        r = self._gs_busy(lambda cb: gun.setup_finish(out, cb=cb), u"綁定")
        if r:
            self.log.appendPlainText(u"完成：%s（槍長約 %.0f cm）。目前打開的就是帶槍的新 rig。" % (r["out"], r["length"]))
            QtWidgets.QMessageBox.information(self, TITLE, u"已經把槍綁到乾淨 rig 並另存：\n" + r["out"])

    def _gun_out(self, rig):
        stem, ext = os.path.splitext(rig)
        return (stem + "_Gun" + (ext or ".mb")).replace("\\", "/")

    # ------------------------------------------------------------------------------------------ record tab
    # ------------------------------------------------------------------------------------------ weights tab
    def _build_weights(self):
        w = QtWidgets.QWidget()
        v = QtWidgets.QVBoxLayout(w)
        info = QtWidgets.QLabel(u"rig 的權重修好後，把新權重換進以前做好的動作檔：只換模型的蒙皮，"
                                u"key、Anim Layer、控制器、骨頭都不動，每個檔存檔前都會檢查動作有沒有變。")
        info.setWordWrap(True)
        info.setStyleSheet("color:#aaa")
        v.addWidget(info)

        v.addWidget(self._step(1, u"權重修好的 rig 檔"))
        g = QtWidgets.QGridLayout()
        g.setColumnMinimumWidth(0, 70)
        g.addWidget(QtWidgets.QLabel(u"rig 檔"), 0, 0)
        self.wt_rig = DropLine([".mb", ".ma"])
        self.wt_rig.setPlaceholderText(u"例如 角色A_Rig.mb（只讀取，不會被修改）")
        self.wt_rig.setText(self.settings.value("wt_rig", ""))
        self.wt_rig.editingFinished.connect(self._wt_refresh)
        g.addWidget(self.wt_rig, 0, 1)
        row = QtWidgets.QHBoxLayout()
        b = QtWidgets.QPushButton(u"選擇")
        b.clicked.connect(lambda: self._pick_file(self.wt_rig, "Maya (*.mb *.ma)", self._wt_refresh))
        row.addWidget(b)
        b = QtWidgets.QPushButton(u"用目前場景")
        b.clicked.connect(self._wt_use_scene)
        row.addWidget(b)
        g.addLayout(row, 0, 2)
        v.addLayout(g)

        v.addWidget(self._step(2, u"要換權重的動作檔"))
        row = QtWidgets.QHBoxLayout()
        for text, fn in ((u"加入檔案…", self._wt_add_files), (u"加入資料夾…", self._wt_add_folder),
                         (u"移除選取", self._wt_remove), (u"清空", self._wt_clear)):
            b = QtWidgets.QPushButton(text)
            b.clicked.connect(fn)
            row.addWidget(b)
        row.addStretch(1)
        hint = QtWidgets.QLabel(u"也可以把 .mb／資料夾拖進表格")
        hint.setStyleSheet("color:#888")
        row.addWidget(hint)
        v.addLayout(row)
        self.wt_table = SceneTable()
        self.wt_table.filesDropped.connect(self._wt_add)
        v.addWidget(self.wt_table, 1)

        v.addWidget(self._step(3, u"輸出"))
        row = QtWidgets.QHBoxLayout()
        self.wt_new = QtWidgets.QRadioButton(u"另存新檔，檔名加上")
        self.wt_over = QtWidgets.QRadioButton(u"直接覆蓋原檔")
        self.wt_suffix = QtWidgets.QLineEdit(self.settings.value("wt_suffix", "_W"))
        self.wt_suffix.setMaximumWidth(110)
        (self.wt_over if self.settings.value("wt_mode", "new") == "over" else self.wt_new).setChecked(True)
        row.addWidget(self.wt_new)
        row.addWidget(self.wt_suffix)
        row.addSpacing(24)
        row.addWidget(self.wt_over)
        row.addWidget(self._help(u"覆蓋前會把原檔複製到同一個資料夾裡的 <span style='color:#f0b860'>_weights_backup</span>，"
                                 u"有問題可以拿回來。<br>檢查發現動作有變化的檔案不會存檔。"))
        row.addStretch(1)
        v.addLayout(row)
        for x in (self.wt_new, self.wt_over):
            x.toggled.connect(self._wt_refresh)
        self.wt_suffix.textChanged.connect(self._wt_refresh)
        self.wt_run = QtWidgets.QPushButton(u"開始模型更新（背景處理，Maya 可繼續用）")
        self.wt_run.setMinimumHeight(36)
        self.wt_run.clicked.connect(self._wt_start)
        v.addWidget(self.wt_run)
        note = QtWidgets.QLabel(u"每個檔：開檔 → 依模型名稱找到同一個模型（頂點數要一樣）→ 動作檔缺的骨頭補進蒙皮 → "
                                u"權重、綁定矩陣換成 rig 的 → 檢查 key 數量和骨頭位置完全沒變 → 存檔。"
                                u"rig 裡有、動作檔沒有的模型會略過。")
        note.setWordWrap(True)
        note.setStyleSheet("color:#888")
        v.addWidget(note)
        for f in json.loads(self.settings.value("wt_files", "[]")):
            if os.path.isfile(f):
                self._wt_append(f)
        self._wt_refresh()
        return w

    def _wt_use_scene(self):
        cmds = self._cmds()
        if not cmds:
            return self._warn(u"要在 Maya 裡使用")
        p = cmds.file(q=True, sceneName=True)
        if not p:
            return self._warn(u"目前場景還沒存檔")
        if cmds.file(q=True, modified=True):
            self._warn(u"目前場景有沒存的修改。背景讀的是存檔的內容，請先存檔。")
        self.wt_rig.setText(p)
        self._wt_refresh()

    def _wt_add_files(self):
        files, _ = QtWidgets.QFileDialog.getOpenFileNames(self, u"動作檔", self.settings.value("wt_dir", ""),
                                                          "Maya (*.mb *.ma)")
        self._wt_add(files)

    def _wt_add_folder(self):
        d = QtWidgets.QFileDialog.getExistingDirectory(self, u"動作檔資料夾", self.settings.value("wt_dir", ""))
        if d:
            self._wt_add([os.path.join(d, f) for f in sorted(os.listdir(d)) if f.lower().endswith((".mb", ".ma"))])

    def _wt_add(self, files):
        have = {self.wt_table.item(r, 0).data(QtCore.Qt.UserRole) for r in range(self.wt_table.rowCount())}
        rig = os.path.normcase(os.path.abspath(self.wt_rig.text().strip())) if self.wt_rig.text().strip() else ""
        suf = self.wt_suffix.text().strip()
        for f in files:
            f = f.replace("\\", "/")
            if f in have or os.path.normcase(os.path.abspath(f)) == rig:
                continue
            if suf and os.path.splitext(f)[0].endswith(suf):     # an output of an earlier run
                continue
            self._wt_append(f)
        if files:
            self.settings.setValue("wt_dir", os.path.dirname(files[0]))
        self._wt_refresh()

    def _wt_append(self, path):
        r = self.wt_table.rowCount()
        self.wt_table.insertRow(r)
        it = QtWidgets.QTableWidgetItem(os.path.basename(path))
        it.setData(QtCore.Qt.UserRole, path)
        it.setToolTip(path)
        self.wt_table.setItem(r, 0, it)
        for c in (1, 2):
            self.wt_table.setItem(r, c, QtWidgets.QTableWidgetItem(""))

    def _wt_remove(self):
        for r in sorted({i.row() for i in self.wt_table.selectedIndexes()}, reverse=True):
            self.wt_table.removeRow(r)
        self._wt_refresh()

    def _wt_clear(self):
        self.wt_table.setRowCount(0)
        self._wt_refresh()

    def _wt_out(self, src):
        if self.wt_over.isChecked():
            return src
        base, ext = os.path.splitext(src)
        return base + self.wt_suffix.text().strip() + ext

    def _wt_refresh(self, *a):
        if not hasattr(self, "wt_table"):
            return
        files = []
        for r in range(self.wt_table.rowCount()):
            src = self.wt_table.item(r, 0).data(QtCore.Qt.UserRole)
            files.append(src)
            out = self._wt_out(src)
            self.wt_table.item(r, 1).setText(u"（覆蓋原檔，先備份）" if out == src else os.path.basename(out))
            st = self.wt_table.item(r, 2)
            if out != src and os.path.exists(out):
                st.setText(u"輸出檔已存在 → 會略過")
                st.setForeground(QtGui.QColor("#e0a040"))
            else:
                st.setText(u"")
                st.setForeground(QtGui.QColor("#cccccc"))
        self.settings.setValue("wt_files", json.dumps(files))

    def _wt_start(self):
        rig = self.wt_rig.text().strip()
        if not os.path.isfile(rig):
            return self._warn(u"找不到權重修好的 rig 檔")
        if not self.wt_table.rowCount():
            return self._warn(u"還沒加入要換權重的動作檔")
        over = self.wt_over.isChecked()
        if not over and not self.wt_suffix.text().strip():
            return self._warn(u"新檔的檔名後綴不能空白（不然就是覆蓋原檔）")
        items = []
        for r in range(self.wt_table.rowCount()):
            src = self.wt_table.item(r, 0).data(QtCore.Qt.UserRole)
            items.append({"src": src, "out": self._wt_out(src)})
        if over and not self._ask(u"要直接覆蓋 %d 個動作檔嗎？\n原檔會先備份到各自資料夾的 _weights_backup。" % len(items)):
            return
        cmds = self._cmds()
        cur = cmds.file(q=True, sceneName=True) if cmds else ""
        if over and cur and any(os.path.normcase(os.path.abspath(i["src"])) == os.path.normcase(os.path.abspath(cur)) for i in items):
            self._warn(u"目前開著的場景也在清單裡。跑完後請重新開啟它，不要直接按存檔（會把新權重蓋回舊的）。")
        self.settings.setValue("wt_rig", rig)
        self.settings.setValue("wt_suffix", self.wt_suffix.text().strip())
        self.settings.setValue("wt_mode", "over" if over else "new")
        for r in range(self.wt_table.rowCount()):
            if self.wt_table.item(r, 2).text().startswith(u"輸出檔已存在") and not over:
                continue
            self.wt_table.item(r, 2).setText(u"等待中")
            self.wt_table.item(r, 2).setForeground(QtGui.QColor("#cccccc"))
        self._job_table = self.wt_table
        self.bt_log.setChecked(True)
        self._run({"mode": "weights", "rig": rig, "items": items, "overwrite": over}, len(items))

    def _build_record(self):
        w = QtWidgets.QWidget()
        v = QtWidgets.QVBoxLayout(w)
        info = QtWidgets.QLabel(u"錄目前 viewport 的畫面（最後點過的那個視窗、它的鏡頭和顯示設定）。")
        info.setStyleSheet("color:#aaa")
        v.addWidget(info)
        g = QtWidgets.QGridLayout()
        r = 0
        g.addWidget(QtWidgets.QLabel(u"範圍"), r, 0)
        row = QtWidgets.QHBoxLayout()
        self.rec_range = QtWidgets.QComboBox()
        self.rec_range.addItems([u"時間軸", u"自訂"])
        self.rec_start = QtWidgets.QDoubleSpinBox()
        self.rec_end = QtWidgets.QDoubleSpinBox()
        for sp in (self.rec_start, self.rec_end):
            sp.setRange(-100000, 100000)
            sp.setDecimals(0)
            sp.setEnabled(False)
        self.rec_end.setValue(24)
        self.rec_range.currentIndexChanged.connect(lambda i: [x.setEnabled(i == 1) for x in (self.rec_start, self.rec_end)])
        row.addWidget(self.rec_range)
        row.addWidget(QtWidgets.QLabel(u"從"))
        row.addWidget(self.rec_start)
        row.addWidget(QtWidgets.QLabel(u"到"))
        row.addWidget(self.rec_end)
        row.addStretch(1)
        g.addLayout(row, r, 1)
        r += 1
        g.addWidget(QtWidgets.QLabel(u"FPS"), r, 0)
        row = QtWidgets.QHBoxLayout()
        self.rec_fps = QtWidgets.QComboBox()
        for label, val in ((u"跟場景一樣", 0), ("60", 60), ("30", 30), ("24", 24), ("15", 15), ("12", 12), ("10", 10)):
            self.rec_fps.addItem(label, val)
        self.rec_fps.setCurrentIndex(int(self.settings.value("rec_fps_idx", 0)))
        row.addWidget(self.rec_fps)
        row.addWidget(self._help(u"跟場景不同時會自動換算，播放速度維持跟 Maya 一樣。<br>"
                                 u"GIF 建議 15 以下，檔案比較小。"))
        row.addStretch(1)
        g.addLayout(row, r, 1)
        r += 1
        g.addWidget(QtWidgets.QLabel(u"循環次數"), r, 0)
        row = QtWidgets.QHBoxLayout()
        self.rec_loops = QtWidgets.QSpinBox()
        self.rec_loops.setRange(1, 50)
        self.rec_loops.setSuffix(u" 次")
        self.rec_loops.setValue(int(self.settings.value("rec_loops", 3)))
        row.addWidget(self.rec_loops)
        row.addWidget(self._help(u"整段動作重複播幾次，短的循環動作才看得清楚。<br>"
                                 u"頭尾同一個姿勢時會自動去掉最後一格，循環不會卡一下。"))
        row.addStretch(1)
        g.addLayout(row, r, 1)
        r += 1
        g.addWidget(QtWidgets.QLabel(u"尺寸"), r, 0)
        row = QtWidgets.QHBoxLayout()
        self.rec_size = QtWidgets.QComboBox()
        for label, val in ((u"跟視窗一樣", None), ("1920 × 1080", (1920, 1080)), ("1280 × 720", (1280, 720)),
                           ("960 × 540", (960, 540)), ("640 × 360", (640, 360)), (u"自訂", "custom")):
            self.rec_size.addItem(label, val)
        self.rec_size.setCurrentIndex(int(self.settings.value("rec_size_idx", 2)))
        self.rec_w = QtWidgets.QSpinBox()
        self.rec_h = QtWidgets.QSpinBox()
        for sp, val in ((self.rec_w, 1280), (self.rec_h, 720)):
            sp.setRange(64, 4096)
            sp.setValue(val)
        self.rec_size.currentIndexChanged.connect(self._rec_size_changed)
        row.addWidget(self.rec_size)
        row.addWidget(self.rec_w)
        self.rec_x = QtWidgets.QLabel("×")
        row.addWidget(self.rec_x)
        row.addWidget(self.rec_h)
        row.addStretch(1)
        g.addLayout(row, r, 1)
        r += 1
        row = QtWidgets.QHBoxLayout()
        self.rec_gate = QtWidgets.QCheckBox(u"在視窗顯示錄影框")
        self._gate_state = None
        self.rec_gate.toggled.connect(self._rec_gate_toggled)
        for sp in (self.rec_w, self.rec_h):
            sp.valueChanged.connect(lambda *_: self._rec_gate_refresh())
        row.addWidget(self.rec_gate)
        row.addWidget(self._help(u"在目前的 viewport 畫出錄影框（框外變暗），<span style='color:#f0b860'>框裡面就是錄出來的畫面</span>，"
                                 u"比例跟上面選的尺寸一樣。<br>調好攝影機距離、角度再按開始錄影。<br>"
                                 u"取消勾選或關掉視窗會恢復原本的攝影機與 Render 解析度設定。"))
        row.addStretch(1)
        g.addLayout(row, r, 1)
        r += 1
        g.addWidget(QtWidgets.QLabel(u"格式"), r, 0)
        row = QtWidgets.QHBoxLayout()
        self.rec_fmt = QtWidgets.QComboBox()
        for label, val in (("MP4", "mp4"), ("GIF", "gif"), (u"PNG 序列", "png")):
            self.rec_fmt.addItem(label, val)
        self.rec_fmt.setCurrentIndex(int(self.settings.value("rec_fmt_idx", 0)))
        self.rec_fmt.currentIndexChanged.connect(lambda *_: self._rec_default_out(force_ext=True))
        row.addWidget(self.rec_fmt)
        row.addStretch(1)
        g.addLayout(row, r, 1)
        r += 1
        g.addWidget(QtWidgets.QLabel(u"顯示"), r, 0)
        row = QtWidgets.QHBoxLayout()
        self.rec_joints = QtWidgets.QCheckBox(u"骨頭")
        self.rec_ctrls = QtWidgets.QCheckBox(u"控制器")
        self.rec_grid = QtWidgets.QCheckBox(u"格線")
        self.rec_hud = QtWidgets.QCheckBox(u"HUD")
        for cb, key, dv in ((self.rec_joints, "rec_joints", "false"), (self.rec_ctrls, "rec_ctrls", "false"),
                            (self.rec_grid, "rec_grid", "false"), (self.rec_hud, "rec_hud", "false")):
            cb.setChecked(self.settings.value(key, dv) == "true")
            row.addWidget(cb)
        row.addWidget(self._help(u"只影響錄出來的畫面，錄完 viewport 會恢復原本的顯示設定。<br>"
                                 u"控制器 = AS 的曲線控制器、locator、IK handle。"))
        row.addStretch(1)
        g.addLayout(row, r, 1)
        r += 1
        g.addWidget(QtWidgets.QLabel(u"背景"), r, 0)
        row = QtWidgets.QHBoxLayout()
        self.rec_bg = QtWidgets.QComboBox()
        for label, val in ((u"跟 viewport 一樣", "viewport"), (u"單色", "solid"), (u"漸層", "gradient"),
                           (u"透明（只有 PNG）", "transparent")):
            self.rec_bg.addItem(label, val)
        self.rec_bg.setCurrentIndex(int(self.settings.value("rec_bg_idx", 0)))
        self.rec_bg1 = self._color_button("rec_bg1", "#5a6a7a", u"單色／漸層上方的顏色")
        self.rec_bg2 = self._color_button("rec_bg2", "#1e2228", u"漸層下方的顏色")
        self.rec_bg.currentIndexChanged.connect(self._rec_bg_changed)
        self.rec_fmt.currentIndexChanged.connect(self._rec_bg_changed)
        row.addWidget(self.rec_bg)
        row.addWidget(self.rec_bg1)
        row.addWidget(self.rec_bg2)
        row.addWidget(self._help(u"只影響錄出來的畫面，錄完 viewport 的背景色會恢復。<br>"
                                 u"點色塊選顏色；漸層 = 上方 → 下方。<br>"
                                 u"透明只有 PNG 序列能存，MP4／GIF 會用 viewport 的背景。"))
        row.addStretch(1)
        g.addLayout(row, r, 1)
        r += 1
        g.addWidget(QtWidgets.QLabel(u"輸出"), r, 0)
        row = QtWidgets.QHBoxLayout()
        self.rec_out = QtWidgets.QLineEdit()
        self.rec_out.textEdited.connect(lambda *_: setattr(self, "_rec_out_edited", True))
        b = QtWidgets.QPushButton(u"另存為")
        b.clicked.connect(self._rec_pick_out)
        row.addWidget(self.rec_out, 1)
        row.addWidget(b)
        g.addLayout(row, r, 1)
        r += 1
        self.rec_open = QtWidgets.QCheckBox(u"錄完打開資料夾")
        self.rec_open.setChecked(self.settings.value("rec_open", "true") == "true")
        g.addWidget(self.rec_open, r, 1)
        v.addLayout(g)
        self.rec_run = QtWidgets.QPushButton(u"開始錄影")
        self.rec_run.setMinimumHeight(36)
        self.rec_run.clicked.connect(self._rec_start)
        v.addWidget(self.rec_run)
        v.addStretch(1)
        self._rec_out_edited = False
        self._rec_size_changed()
        self._rec_bg_changed()
        return w

    def _color_button(self, key, default, tip):
        b = QtWidgets.QPushButton()
        b.setFixedSize(36, 22)
        b.setToolTip(tip)
        b.setProperty("color", self.settings.value(key, default))

        def paint():
            b.setStyleSheet("QPushButton{background:%s;border:1px solid #888;border-radius:3px}" % b.property("color"))

        def pick():
            c = QtWidgets.QColorDialog.getColor(QtGui.QColor(b.property("color")), self, tip)
            if c.isValid():
                b.setProperty("color", c.name())
                self.settings.setValue(key, c.name())
                paint()
        b.clicked.connect(pick)
        paint()
        return b

    def _rec_bg_changed(self, *a):
        mode = self.rec_bg.currentData()
        self.rec_bg1.setVisible(mode in ("solid", "gradient"))
        self.rec_bg2.setVisible(mode == "gradient")

    def _rec_background(self):
        mode = self.rec_bg.currentData()
        rgb = lambda b: QtGui.QColor(b.property("color")).getRgb()[:3]
        if mode == "solid":
            return ("solid", rgb(self.rec_bg1))
        if mode == "gradient":
            return ("gradient", rgb(self.rec_bg1), rgb(self.rec_bg2))
        if mode == "transparent":
            return "transparent"
        return None

    def _rec_size_changed(self, *a):
        custom = self.rec_size.currentData() == "custom"
        self.rec_w.setVisible(custom)
        self.rec_h.setVisible(custom)
        self.rec_x.setVisible(custom)
        self._rec_gate_refresh()

    def _rec_size_value(self):
        size = self.rec_size.currentData()
        return (self.rec_w.value(), self.rec_h.value()) if size == "custom" else size

    def _rec_gate_toggled(self, on):
        cmds = self._cmds()
        if not cmds:
            return
        from . import asMixamoRecord as rec
        rec.hide_gate(self._gate_state)
        self._gate_state = None
        if on:
            try:
                self._gate_state = rec.show_gate(self._rec_size_value())
            except Exception as e:
                self.rec_gate.blockSignals(True)
                self.rec_gate.setChecked(False)
                self.rec_gate.blockSignals(False)
                self._warn(u"顯示錄影框失敗：%s" % e)

    def _rec_gate_refresh(self):
        """Size or camera changed: redraw the frame (only while it's shown)."""
        if getattr(self, "_gate_state", None) is not None:
            self._rec_gate_toggled(True)

    def _rec_default_out(self, force_ext=False):
        if not self._cmds():
            return
        fmt = self.rec_fmt.currentData()
        cur = self.rec_out.text().strip()
        if self._rec_out_edited and cur:
            if force_ext:
                base = cur[:-4] if cur.lower().endswith((".mp4", ".gif")) else cur
                self.rec_out.setText(base if fmt == "png" else base + "." + fmt)
            return
        from . import asMixamoRecord as rec
        self.rec_out.setText(rec.default_name(fmt))

    def _rec_pick_out(self):
        fmt = self.rec_fmt.currentData()
        if fmt == "png":
            d = QtWidgets.QFileDialog.getExistingDirectory(self, u"PNG 序列存放的資料夾", os.path.dirname(self.rec_out.text()))
            if d:
                self.rec_out.setText(d)
                self._rec_out_edited = True
            return
        p, _ = QtWidgets.QFileDialog.getSaveFileName(self, u"輸出", self.rec_out.text(), "%s (*.%s)" % (fmt.upper(), fmt))
        if p:
            self.rec_out.setText(p)
            self._rec_out_edited = True

    def _rec_start(self):
        cmds = self._cmds()
        if not cmds:
            return self._warn(u"要在 Maya 裡使用")
        from . import asMixamoRecord as rec
        fmt = self.rec_fmt.currentData()
        out = self.rec_out.text().strip()
        if not out:
            self._rec_default_out()
            out = self.rec_out.text().strip()
        if fmt != "png" and not out.lower().endswith("." + fmt):
            out += "." + fmt
            self.rec_out.setText(out)
        if os.path.exists(out) and not self._ask(u"已經有這個檔案，要覆蓋嗎？\n" + out):
            return
        fps = self.rec_fps.currentData() or int(round(rec.scene_fps()))
        size = self.rec_size.currentData()
        if size == "custom":
            size = (self.rec_w.value(), self.rec_h.value())
        start = end = None
        if self.rec_range.currentIndex() == 1:
            start, end = self.rec_start.value(), self.rec_end.value()
            if end < start:
                return self._warn(u"結束格要大於開始格")
        for k, val in (("rec_fps_idx", self.rec_fps.currentIndex()), ("rec_size_idx", self.rec_size.currentIndex()),
                       ("rec_fmt_idx", self.rec_fmt.currentIndex()), ("rec_open", self.rec_open.isChecked()),
                       ("rec_joints", self.rec_joints.isChecked()), ("rec_ctrls", self.rec_ctrls.isChecked()),
                       ("rec_grid", self.rec_grid.isChecked()), ("rec_hud", self.rec_hud.isChecked()),
                       ("rec_loops", self.rec_loops.value()), ("rec_bg_idx", self.rec_bg.currentIndex())):
            self.settings.setValue(k, ("true" if val else "false") if isinstance(val, bool) else val)
        self.log.clear()
        self._rec_gate_refresh()          # follows a camera switched since the frame was turned on
        QtWidgets.QApplication.setOverrideCursor(QtCore.Qt.WaitCursor)
        self.rec_run.setEnabled(False)
        try:
            r = rec.record(out, fmt=fmt, fps=fps, size=size, start=start, end=end,
                           show_joints=self.rec_joints.isChecked(), show_controls=self.rec_ctrls.isChecked(),
                           show_grid=self.rec_grid.isChecked(), show_hud=self.rec_hud.isChecked(),
                           loops=self.rec_loops.value(), background=self._rec_background(),
                           cb=lambda m: (self.log.appendPlainText(m), QtWidgets.QApplication.processEvents()))
        except Exception as e:
            import traceback
            self.log.appendPlainText(traceback.format_exc())
            self.bt_log.setChecked(True)
            return self._warn(u"錄影失敗：%s" % e)
        finally:
            QtWidgets.QApplication.restoreOverrideCursor()
            self.rec_run.setEnabled(True)
        self.log.appendPlainText(u"錄好 %d 格（循環 %d 次），%d fps，%d×%d" % (r["frames"], r.get("loops", 1), r["fps"],
                                                                         r["size"][0], r["size"][1]))
        if fmt == "gif":
            self._rec_result = r["path"]
            self._run({"mode": "gif", "pngs": r["pngs"], "out": r["path"], "fps": r["fps"], "cleanup": r["tmp"]}, r["frames"])
            return
        import shutil
        shutil.rmtree(r["tmp"], ignore_errors=True)
        self._rec_done(r["path"])

    def _rec_done(self, path):
        self.log.appendPlainText(u"完成：" + path)
        if self.rec_open.isChecked():
            target = path if os.path.isdir(path) else os.path.dirname(path)
            QtGui.QDesktopServices.openUrl(QtCore.QUrl.fromLocalFile(target))

    # ------------------------------------------------------------------------------------------ process
    def _run(self, job, total):
        if self.proc and self.proc.state() != QtCore.QProcess.NotRunning:
            return self._warn(u"還在處理中，請等它跑完")
        fd, self.job_file = tempfile.mkstemp(prefix="asMixamo_", suffix=".json")
        with os.fdopen(fd, "w", encoding="utf-8") as f:
            json.dump(job, f, ensure_ascii=False)
        self.total, self._done_count = total, 0
        self.progress.setRange(0, total)
        self.progress.setValue(0)
        self.log.clear()
        self._busy(True)
        self.proc = QtCore.QProcess(self)
        env = QtCore.QProcessEnvironment.systemEnvironment()
        env.insert("PYTHONIOENCODING", "utf-8")
        env.insert("PYTHONUNBUFFERED", "1")
        self.proc.setProcessEnvironment(env)
        self.proc.setProcessChannelMode(QtCore.QProcess.MergedChannels)
        self.proc.readyReadStandardOutput.connect(self._read)
        self.proc.finished.connect(self._finished)
        self.proc.start(_mayapy(), [WORKER, self.job_file])

    def _read(self):
        while self.proc.canReadLine():
            line = bytes(self.proc.readLine()).decode("utf-8", "replace").rstrip()
            if not line.startswith("@@"):
                continue
            try:
                ev = json.loads(line[2:])
            except ValueError:
                continue
            t = ev.get("type")
            if t == "log":
                self.log.appendPlainText(ev["msg"])
            elif t == "item":
                tbl = getattr(self, "_job_table", None) or self.table
                st = tbl.item(ev["index"], 3 if tbl is self.table else 2)
                color = {"running": "#80b0ff", "done": "#70d070", "skipped": "#e0a040", "error": "#ff6060"}[ev["state"]]
                label = {"running": u"處理中…", "done": u"完成", "skipped": u"略過", "error": u"失敗"}[ev["state"]]
                st.setText(label + ((u"：" + ev["msg"]) if ev.get("msg") else ""))
                st.setToolTip(st.text())
                st.setForeground(QtGui.QColor(color))
                if ev["state"] == "error":
                    self.bt_log.setChecked(True)
                if ev["state"] != "running":
                    self._done_count += 1
                    self.progress.setValue(self._done_count)
                    self.log.appendPlainText(u"  → %s %s" % (label, ev.get("msg", "")))
            elif t == "progress":
                self.progress.setRange(0, ev["total"])
                self.progress.setValue(ev["n"])
            elif t == "gif":
                if ev["ok"]:
                    self.log.appendPlainText(u"GIF %.1f MB" % (ev["size"] / 1048576.0))
                    self._rec_done(ev["path"])
                else:
                    self.log.appendPlainText(u"GIF 失敗：" + ev.get("error", ""))
                    self.bt_log.setChecked(True)
            elif t == "export":
                self.progress.setValue(1)
                if ev["ok"]:
                    self.log.appendPlainText(u"匯出完成（%.1f MB）：%s\n  %s" % (ev["size"] / 1048576.0, ev["out"], ev["msg"]))
                    QtWidgets.QMessageBox.information(self, TITLE, u"匯出完成：\n%s\n\n%s" % (ev["out"], ev["msg"]))
                else:
                    self.log.appendPlainText(u"匯出失敗：" + ev["msg"])
                    self.bt_log.setChecked(True)
                    self._warn(u"匯出失敗：" + ev["msg"])
            elif t == "convert":
                self.progress.setValue(1)
                if ev["ok"]:
                    self.log.appendPlainText(u"完成：可以上傳 Mixamo 了 → " + ev["dst"])
                else:
                    self.log.appendPlainText(u"有問題：\n  " + "\n  ".join(ev["problems"]))
                    self.bt_log.setChecked(True)

    def _finished(self, *a):
        self._read()
        self._busy(False)
        try:
            os.remove(self.job_file)
        except Exception:
            pass
        self.log.appendPlainText(u"—— 結束 ——")
        self._refresh_names()
        self._job_table = None

    def _show_log(self, on):
        self.bt_log.setArrowType(QtCore.Qt.DownArrow if on else QtCore.Qt.RightArrow)
        self.log.setVisible(on)
        self.settings.setValue("log_open", "true" if on else "false")
        if on:
            h = sum(self.split.sizes())
            if h > 300:
                self.split.setSizes([h - 140, 140])

    # ------------------------------------------------------------------------------------------ export FBX
    def _build_export(self):
        w = QtWidgets.QWidget()
        v = QtWidgets.QVBoxLayout(w)
        info = QtWidgets.QLabel(u"把目前打開的 rig 匯出成遊戲用的 FBX：只有骨架（DeformationSystem）和蒙皮模型（Geometry），"
                                u"控制器和其他 rig 節點都不會帶出去。<br>在背景處理，目前場景不會被修改。")
        info.setWordWrap(True)
        info.setStyleSheet("color:#aaa")
        v.addWidget(info)
        g = QtWidgets.QGridLayout()
        g.addWidget(QtWidgets.QLabel(u"目前場景"), 0, 0)
        self.ex_scene = QtWidgets.QLabel("-")
        self.ex_scene.setTextInteractionFlags(QtCore.Qt.TextSelectableByMouse)
        g.addWidget(self.ex_scene, 0, 1)
        b = QtWidgets.QPushButton(u"重新整理")
        b.clicked.connect(lambda: self._ex_refresh())
        g.addWidget(b, 0, 2)
        self.ex_anim = QtWidgets.QCheckBox(u"含動畫")
        self.ex_anim.setChecked(self.settings.value("ex_anim", "true") == "true")
        g.addWidget(self.ex_anim, 1, 0)
        row = QtWidgets.QHBoxLayout()
        row.addWidget(QtWidgets.QLabel(u"影格"))
        self.ex_start, self.ex_end = QtWidgets.QSpinBox(), QtWidgets.QSpinBox()
        for sp in (self.ex_start, self.ex_end):
            sp.setRange(-100000, 100000)
        row.addWidget(self.ex_start)
        row.addWidget(QtWidgets.QLabel(u"到"))
        row.addWidget(self.ex_end)
        b = QtWidgets.QPushButton(u"跟時間軸")
        b.clicked.connect(lambda: self._ex_refresh(range_only=True))
        row.addWidget(b)
        row.addWidget(self._help(u"<span style='color:#f0b860'>勾選</span>：把這段影格的動作烘焙到每一根骨頭（每格一個 key）。<br>"
                                 u"<span style='color:#f0b860'>不勾</span>：只匯出 bind pose 的骨架和模型，沒有動畫（給引擎建角色用）。"))
        row.addStretch(1)
        g.addLayout(row, 1, 1, 1, 2)
        self.ex_anim.toggled.connect(lambda on: [x.setEnabled(on) for x in (self.ex_start, self.ex_end)])
        self.ex_gun = QtWidgets.QCheckBox(u"含槍（GunRig）")
        self.ex_gun.setChecked(self.settings.value("ex_gun", "true") == "true")
        g.addWidget(self.ex_gun, 2, 0)
        self.ex_gun_note = QtWidgets.QLabel("")
        self.ex_gun_note.setStyleSheet("color:#888")
        row = QtWidgets.QHBoxLayout()
        row.addWidget(self.ex_gun_note)
        row.addWidget(self._help(u"帶槍的 rig（用「雙手武器骨架」做的）：<br>"
                                 u"<span style='color:#f0b860'>勾選</span>：一起匯出武器骨頭 Gun_Weapon（在右手下）和槍模型 Gun_Geo。<br>"
                                 u"<span style='color:#f0b860'>不勾</span>：只有角色本身。"))
        row.addStretch(1)
        g.addLayout(row, 2, 1, 1, 2)
        self.ex_wpn = QtWidgets.QCheckBox(u"含武器（Weapon）")
        self.ex_wpn.setChecked(self.settings.value("ex_wpn", "true") == "true")
        g.addWidget(self.ex_wpn, 3, 0)
        self.ex_wpn_note = QtWidgets.QLabel("")
        self.ex_wpn_note.setStyleSheet("color:#888")
        row = QtWidgets.QHBoxLayout()
        row.addWidget(self.ex_wpn_note)
        row.addWidget(self._help(u"手持武器的 rig（例如 Weapon_Joint 掛在右手、或可切換左右手的 Weapon 骨頭）：<br>"
                                 u"<span style='color:#f0b860'>勾選</span>：一起匯出武器骨頭和只蒙皮在武器骨頭上的武器模型。<br>"
                                 u"<span style='color:#f0b860'>不勾</span>：武器骨頭和武器模型都不匯出。"))
        row.addStretch(1)
        g.addLayout(row, 3, 1, 1, 2)
        g.addWidget(QtWidgets.QLabel(u"輸出 FBX"), 4, 0)
        self.ex_out = QtWidgets.QLineEdit()
        g.addWidget(self.ex_out, 4, 1)
        b = QtWidgets.QPushButton(u"另存為")
        b.clicked.connect(self._ex_pick_out)
        g.addWidget(b, 4, 2)
        g.setColumnStretch(1, 1)
        v.addLayout(g)
        v.addStretch(1)
        self.ex_run = QtWidgets.QPushButton(u"匯出 FBX（背景處理，Maya 可繼續用）")
        self.ex_run.setMinimumHeight(36)
        self.ex_run.clicked.connect(self._ex_start)
        v.addWidget(self.ex_run)
        return w

    def _ex_refresh(self, range_only=False):
        import maya.cmds as cmds
        from . import asMixamoExport as ex
        info = ex.scene_info()
        self.ex_start.setValue(int(info["range"][0]))
        self.ex_end.setValue(int(info["range"][1]))
        if range_only:
            return
        scene = cmds.file(q=True, sceneName=True)
        name = os.path.basename(scene) if scene else u"（未存檔的場景）"
        self.ex_scene.setText(name + ("" if info["as"] else u"　✘ 不是 AS rig"))
        self.ex_scene.setStyleSheet("" if info["as"] else "color:#ff7070")
        self.ex_gun.setEnabled(info["gun"])
        self.ex_gun_note.setText(u"這個 rig 有槍" if info["gun"] else u"這個 rig 沒有槍")
        self.ex_wpn.setEnabled(info["weapon"])
        self.ex_wpn_note.setText(u"這個 rig 有武器" if info["weapon"] else u"這個 rig 沒有武器")
        if scene:
            folder = self.settings.value("ex_dir", "") or os.path.dirname(scene)
            self.ex_out.setText(os.path.join(folder, os.path.splitext(os.path.basename(scene))[0] + ".fbx").replace("\\", "/"))
        self.ex_anim.setChecked(bool(info["animated"]))

    def _ex_pick_out(self):
        p, _ = QtWidgets.QFileDialog.getSaveFileName(self, u"輸出 FBX", self.ex_out.text(), "FBX (*.fbx)")
        if p:
            self.ex_out.setText(p)

    def _ex_start(self):
        import maya.cmds as cmds
        from . import asMixamoExport as ex
        info = ex.scene_info()
        if not info["as"]:
            return self._warn(u"目前場景不是 AdvancedSkeleton 的 rig（找不到 DeformationSystem）")
        out = self.ex_out.text().strip()
        if not out:
            return self._warn(u"請設定輸出 FBX 的位置")
        if not out.lower().endswith(".fbx"):
            out += ".fbx"
        if os.path.exists(out) and not self._ask(u"%s 已經存在，要覆蓋嗎？" % os.path.basename(out)):
            return
        anim, gun = self.ex_anim.isChecked(), self.ex_gun.isChecked() and info["gun"]
        weapon = self.ex_wpn.isChecked() and info["weapon"]
        self.settings.setValue("ex_wpn", "true" if self.ex_wpn.isChecked() else "false")
        self.settings.setValue("ex_anim", "true" if anim else "false")
        self.settings.setValue("ex_gun", "true" if self.ex_gun.isChecked() else "false")
        self.settings.setValue("ex_dir", os.path.dirname(out))
        tmp = os.path.join(tempfile.mkdtemp(prefix="asrExport_"), "scene.mb")
        sel = cmds.ls(selection=True)
        cmds.file(tmp, exportAll=True, type="mayaBinary", force=True, preserveReferences=False)
        if sel:
            cmds.select(sel, replace=True)
        self._run({"mode": "export", "scene": tmp, "out": out, "anim": anim, "gun": gun, "weapon": weapon,
                   "start": self.ex_start.value(), "end": self.ex_end.value()}, 1)

    # ------------------------------------------------------------------------------------------ updates
    def _open_updater(self):
        """Look for versions only when asked (no automatic check)."""
        for k in ("upd_checked", "upd_new"):          # leftovers of the automatic check in v1.8.0
            self.settings.remove(k)
        try:
            import asrUpdater
        except ImportError:
            return self._warn(u"找不到 asrUpdater.py（請用最新的安裝包重新安裝一次）")
        asrUpdater.show(self)

    def _busy(self, on):
        for name in ("cv_run", "bt_run", "rec_run", "wt_run", "ex_run"):
            b = getattr(self, name, None)
            if b is not None:
                b.setEnabled(not on)

    def _follow_gun(self):
        if not self._cmds():
            return self._warn(u"要在 Maya 裡使用")
        try:
            v = self._core().toggle_follow_gun()
            self.log.appendPlainText(u"左手跟槍：%s（第 %d 格，已 key）" % (u"開" if v > 0.5 else u"關", int(self._cmds().currentTime(q=True))))
        except Exception as e:
            self._warn(str(e))

    def _build_pose(self):
        if not self._cmds():
            return self._warn(u"要在 Maya 裡使用")
        keep = bool(QtWidgets.QApplication.keyboardModifiers() & QtCore.Qt.ControlModifier)
        try:
            n, failed = self._core().go_to_build_pose(keep_main=keep)
            self.log.appendPlainText(u"Go to Build Pose：%d 個控制器屬性%s%s" % (
                n, u"（保留 Main）" if keep else u"", (u"，%d 個失敗" % len(failed)) if failed else u""))
        except Exception as e:
            self._warn(str(e))

    # ------------------------------------------------------------------------------------------ options
    def _scroll(self, w):
        """Scroll area for a tab's settings, inside a container that also has a footer (see _pin) outside the scroll."""
        sc = QtWidgets.QScrollArea()
        sc.setWidget(w)
        sc.setWidgetResizable(True)
        sc.setFrameShape(QtWidgets.QFrame.NoFrame)
        box = QtWidgets.QWidget()
        lay = QtWidgets.QVBoxLayout(box)
        lay.setContentsMargins(0, 0, 0, 0)
        lay.setSpacing(4)
        lay.addWidget(sc, 1)
        foot = QtWidgets.QVBoxLayout()
        foot.setContentsMargins(9, 0, 9, 6)
        lay.addLayout(foot)
        box.scroll_area, box.footer = sc, foot
        return box

    def _pin(self, box, widgets):
        """Move the tab's final action widgets out of the scroll area into its footer: always visible, never
        scrolled by the mouse wheel."""
        for wdg in widgets:
            box.footer.addWidget(wdg)

    def _help(self, text):
        """Small round '?' that explains a setting when the mouse is over it."""
        return HelpBadge(text, self)

    def _source_combo(self, key):
        src = QtWidgets.QComboBox()
        items = _sources()
        for label, val in items:
            src.addItem(label, val)
        vals = [v for _, v in items]
        cur = self.settings.value(key + "_source", "auto")
        cur = "mixamo" if cur == "standard" else cur
        src.setCurrentIndex(vals.index(cur) if cur in vals else 0)
        src.setToolTip(u"自動判斷：依骨頭名稱找最符合的來源。判斷錯時再手動選。<br>"
                       u"所有動作庫的骨頭名稱對應都內建在工具裡，不需要裝 AdvancedSkeleton。")
        self.opt.setdefault(key, {})["source"] = src
        return src

    def _options_box(self, key):
        """Key Reducer + Euler Filter, one set per tab (saved separately)."""
        box = QtWidgets.QGroupBox(u"設定")
        h = QtWidgets.QHBoxLayout(box)
        red = QtWidgets.QCheckBox(u"Key Reducer")
        red.setChecked(self.settings.value(key + "_reduce", "true") == "true")
        pre = QtWidgets.QDoubleSpinBox()
        pre.setRange(0.1, 20)
        pre.setSingleStep(0.5)
        pre.setSuffix(" %")
        pre.setValue(float(self.settings.value(key + "_precision", 3.0)))
        red.toggled.connect(pre.setEnabled)
        pre.setEnabled(red.isChecked())
        eul = QtWidgets.QCheckBox(u"Euler Filter")
        eul.setChecked(self.settings.value(key + "_euler", "true") == "true")
        h.addWidget(red)
        h.addWidget(self._help(u"刪除多餘的 key，保留曲線形狀。<br>精度：允許誤差（%），數值越大 key 越少。建議 3%。"))
        h.addSpacing(12)
        h.addWidget(QtWidgets.QLabel(u"精度"))
        h.addWidget(pre)
        h.addSpacing(24)
        h.addWidget(eul)
        h.addWidget(self._help(u"bake 後旋轉值可能突然跳 ±180°／360°，<br>造成曲線斷開、key 之間多轉一圈。<br>修正成連續數值，不影響姿勢。"))
        h.addSpacing(24)
        inp = QtWidgets.QCheckBox(u"In Place")
        inp.setChecked(self.settings.value(key + "_in_place", "false") == "true")
        h.addWidget(inp)
        h.addWidget(self._help(u"去掉整段的前後左右位移，角色原地播放。<br>保留上下起伏與身體擺動，頭尾位置對齊、可循環。<br>Mixamo 下載時沒勾 In Place 的移動動作用這個。"))
        h.addSpacing(24)
        twh = QtWidgets.QCheckBox(u"雙手武器")
        twh.setChecked(self.settings.value(key + "_two_hand", "false") == "true")
        h.addWidget(twh)
        h.addWidget(self._help(u"rig 裡有槍道具（LeftGrip_IK）時：左手改 IK，整段黏在槍的握點上。<br>"
                               u"手臂太短搆不到的格子會自動拉長一點。"))
        h.addStretch(1)
        self.opt.setdefault(key, {}).update({"reduce": red, "precision": pre, "euler": eul, "in_place": inp, "two_hand": twh})
        return box

    def _opts(self, key):
        w = self.opt[key]
        o = {"source": w["source"].currentData(), "reduce": w["reduce"].isChecked(),
             "precision": w["precision"].value(), "euler": w["euler"].isChecked(),
             "in_place": w["in_place"].isChecked(), "two_hand": w["two_hand"].isChecked()}
        for k, v in o.items():
            self.settings.setValue(key + "_" + k, ("true" if v else "false") if isinstance(v, bool) else v)
        return o

    # ------------------------------------------------------------------------------------------ helpers
    def _pick_file(self, line, flt, after=None):
        p, _ = QtWidgets.QFileDialog.getOpenFileName(self, u"選擇", line.text(), flt)
        if p:
            line.setText(p)
            if after:
                after()

    def _warn(self, msg):
        QtWidgets.QMessageBox.warning(self, TITLE, msg)

    def _ask(self, msg):
        return QtWidgets.QMessageBox.question(self, TITLE, msg) == QtWidgets.QMessageBox.Yes

    def closeEvent(self, e):
        try:
            running = self.proc is not None and self.proc.state() != QtCore.QProcess.NotRunning
        except RuntimeError:          # QProcess already gone
            running = False
        if running:
            box = QtWidgets.QMessageBox(QtWidgets.QMessageBox.Question, TITLE, u"背景還在處理中，關掉視窗會中斷，確定嗎？",
                                        QtWidgets.QMessageBox.Yes | QtWidgets.QMessageBox.No, self)
            box.setWindowFlags(box.windowFlags() | QtCore.Qt.WindowStaysOnTopHint)
            if box.exec() != QtWidgets.QMessageBox.Yes:
                e.ignore()
                return
            try:
                self.proc.kill()
            except RuntimeError:
                pass
        for b in self.findChildren(HelpBadge):
            b.pop.hide()
        if getattr(self, "_gate_state", None) is not None:
            try:
                from . import asMixamoRecord as rec
                rec.hide_gate(self._gate_state)
            except Exception:
                pass
            self._gate_state = None
        self._kill_scene_jobs()
        e.accept()
        super().closeEvent(e)


def _close_all():
    """Close every ASR Tools window (also ones left over after a module reload, and old "AS × Mixamo" ones)."""
    for w in QtWidgets.QApplication.topLevelWidgets():
        try:
            if w.windowTitle().startswith((u"ASR Tools", u"AS × Mixamo")) and isinstance(w, QtWidgets.QDialog):
                if getattr(w, "_gate_state", None) is not None:      # put the camera / render size back
                    from . import asMixamoRecord as rec
                    rec.hide_gate(w._gate_state)
                    w._gate_state = None
                if hasattr(w, "_kill_scene_jobs"):
                    w._kill_scene_jobs()
                w.hide()
                w.deleteLater()
        except RuntimeError:
            pass


def show():
    global _win
    _close_all()
    _win = Window(_maya_window())
    _win.show()
    return _win


def build_pose(keep_main=False):
    """Shelf / hotkey entry: Go to Build Pose without AdvancedSkeleton (Ctrl held = keep Main)."""
    try:
        keep_main = keep_main or bool(QtWidgets.QApplication.keyboardModifiers() & QtCore.Qt.ControlModifier)
    except Exception:
        pass
    from . import asMixamoCore as core
    return core.go_to_build_pose(keep_main=keep_main)


def add_shelf_button():
    import maya.cmds as cmds
    import maya.mel as mel
    shelf = cmds.tabLayout(mel.eval("$tmp=$gShelfTopLevel"), q=True, selectTab=True)
    cmds.shelfButton(parent=shelf, image="asMixamoTool.png", image1="asMixamoTool.png", label="ASR Tools",
                     annotation=u"ASR Tools（AdvancedSkeleton + Retarget）：骨架轉換＋套動作",
                     command="import asMixamoTool; asMixamoTool.show()", sourceType="python")
    print(u"已加到工具架：%s" % shelf)
