# -*- coding: utf-8 -*-
"""ASR Tools updater: check GitHub Releases for new versions, install any version (newer or older = roll back).

Kept OUTSIDE the asMixamoTool package on purpose: if a release of the tool is broken, this still opens
(shelf button right-click > 版本管理, or:  import asrUpdater; asrUpdater.show()).

Each GitHub release: tag "v1.2.3", one asset ASR_Tools_v1.2.3.zip (the normal install package, with install.py).
"""
import datetime
import importlib.util
import json
import os
import re
import shutil
import sys
import tempfile
import time
import urllib.request
import zipfile

REPO = "JustSadow/ASR-Tools"      # GitHub "owner/name" of the public repo
# version list: a plain file in the repo (raw files are not rate-limited like the API, which allows only 60 calls an
# hour per office IP without login); the Releases API is the fallback
INDEX = "https://raw.githubusercontent.com/%s/main/releases.json"
API = "https://api.github.com/repos/%s/releases?per_page=50"
UA = "ASR-Tools-updater"


def _scripts_dir():
    import maya.cmds as cmds
    return cmds.internalVar(userScriptDir=True)


def installed_version():
    """Version of the installed tool, read from the file (no import, so a broken install can still be read)."""
    p = os.path.join(_scripts_dir(), "asMixamoTool", "__init__.py")
    try:
        m = re.search(r'__version__\s*=\s*"([^"]+)"', open(p, encoding="utf-8").read())
        return m.group(1) if m else None
    except OSError:
        return None


def _vkey(v):
    return tuple(int(x) for x in re.findall(r"\d+", v or "0")[:3])


def list_releases(timeout=8):
    """[{version, tag, title, notes, date, url, size, prerelease}] newest first."""
    try:
        req = urllib.request.Request(INDEX % REPO + "?t=%d" % int(time.time() // 300), headers={"User-Agent": UA})
        with urllib.request.urlopen(req, timeout=timeout) as r:
            out = json.loads(r.read().decode("utf-8"))
        for x in out:
            x.setdefault("tag", "v" + x["version"])
            x.setdefault("title", x["tag"])
            x.setdefault("notes", "")
            x.setdefault("date", "")
            x.setdefault("size", 0)
            x.setdefault("prerelease", False)
        out.sort(key=lambda x: _vkey(x["version"]), reverse=True)
        if out:
            return out
    except Exception:
        pass
    return _list_from_api(timeout)


def _list_from_api(timeout=8):
    req = urllib.request.Request(API % REPO, headers={"User-Agent": UA, "Accept": "application/vnd.github+json"})
    with urllib.request.urlopen(req, timeout=timeout) as r:
        data = json.loads(r.read().decode("utf-8"))
    out = []
    for rel in data:
        if rel.get("draft"):
            continue
        asset = next((a for a in rel.get("assets", []) if a["name"].lower().endswith(".zip")), None)
        if not asset:
            continue
        tag = rel.get("tag_name", "")
        out.append({"version": tag.lstrip("vV"), "tag": tag, "title": rel.get("name") or tag,
                    "notes": rel.get("body") or "", "date": (rel.get("published_at") or "")[:10],
                    "url": asset["browser_download_url"], "size": asset.get("size", 0),
                    "prerelease": bool(rel.get("prerelease"))})
    out.sort(key=lambda x: _vkey(x["version"]), reverse=True)
    return out


def newer_release(timeout=4):
    """The newest release if it is newer than the installed version, else None. Never raises."""
    try:
        rels = [r for r in list_releases(timeout) if not r["prerelease"]]
    except Exception:
        return None
    cur = installed_version()
    return rels[0] if rels and _vkey(rels[0]["version"]) > _vkey(cur) else None


def _safe_extract(zf, dest):
    root = os.path.realpath(dest)
    for m in zf.infolist():
        target = os.path.realpath(os.path.join(dest, m.filename))
        if not (target == root or target.startswith(root + os.sep)):
            raise RuntimeError("bad path in zip: %s" % m.filename)
    zf.extractall(dest)


def install(release, log=print):
    """Download and install `release` (from list_releases). The current version is backed up by install.py."""
    tmp = tempfile.mkdtemp(prefix="asr_update_")
    try:
        zpath = os.path.join(tmp, "pkg.zip")
        log(u"下載 %s …" % release["tag"])
        url = release["url"]
        # tags are case-sensitive in download URLs: a release tagged "V1.2.3" instead of "v1.2.3" is still found
        alt = re.sub(r"/download/([vV])", lambda m: "/download/" + ("V" if m.group(1) == "v" else "v"), url, count=1)
        for i, u in enumerate([url] + ([alt] if alt != url else [])):
            try:
                req = urllib.request.Request(u, headers={"User-Agent": UA})
                with urllib.request.urlopen(req, timeout=60) as r, open(zpath, "wb") as f:
                    shutil.copyfileobj(r, f)
                break
            except urllib.error.HTTPError as e:
                if e.code != 404 or i == 1 or alt == url:
                    raise
        ext = os.path.join(tmp, "pkg")
        with zipfile.ZipFile(zpath) as zf:
            _safe_extract(zf, ext)
        inst = None
        for dirpath, _, files in os.walk(ext):
            if "install.py" in files:
                inst = os.path.join(dirpath, "install.py")
                break
        if not inst:
            raise RuntimeError(u"安裝包裡找不到 install.py")
        spec = importlib.util.spec_from_file_location("asr_install_%d" % int(time.time()), inst)
        mod = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(mod)
        mod._install(log)
        _remember(release["version"])
        log(u"已安裝 %s" % release["tag"])
    finally:
        shutil.rmtree(tmp, ignore_errors=True)


def _remember(version):
    try:
        import maya.cmds as cmds
        cmds.optionVar(stringValue=("asrToolsInstalledAt", "%s %s" % (version, datetime.datetime.now().isoformat(timespec="seconds"))))
    except Exception:
        pass


def _reopen_tool():
    for m in [k for k in list(sys.modules) if k == "asMixamoTool" or k.startswith("asMixamoTool.")]:
        del sys.modules[m]
    try:
        import asMixamoTool
        asMixamoTool.show()
    except Exception as e:
        print(u"ASR Tools 開啟失敗（可以用 版本管理 退回上一版）：%s" % e)


# ------------------------------------------------------------------------------------------------ window
_dlg = None


def show(parent=None):
    """Version manager: every release with its notes; install any of them."""
    global _dlg
    from PySide6 import QtWidgets, QtCore
    if parent is None:
        try:
            import maya.OpenMayaUI as omui
            from shiboken6 import wrapInstance
            parent = wrapInstance(int(omui.MQtUtil.mainWindow()), QtWidgets.QWidget)
        except Exception:
            parent = None
    if _dlg is not None:
        try:
            _dlg.close()
        except Exception:
            pass
    d = QtWidgets.QDialog(parent)
    d.setWindowTitle(u"ASR Tools 版本管理")
    d.resize(620, 460)
    v = QtWidgets.QVBoxLayout(d)
    cur = installed_version()
    head = QtWidgets.QLabel(u"目前安裝：<b>%s</b>" % (("v" + cur) if cur else u"（未安裝）"))
    v.addWidget(head)
    split = QtWidgets.QSplitter(QtCore.Qt.Horizontal)
    lst = QtWidgets.QListWidget()
    notes = QtWidgets.QTextBrowser()
    split.addWidget(lst)
    split.addWidget(notes)
    split.setSizes([200, 420])
    v.addWidget(split, 1)
    status = QtWidgets.QLabel("")
    status.setStyleSheet("color:#aaa")
    v.addWidget(status)
    row = QtWidgets.QHBoxLayout()
    btn = QtWidgets.QPushButton(u"安裝這一版")
    btn.setMinimumHeight(32)
    btn.setEnabled(False)
    row.addStretch(1)
    row.addWidget(btn)
    v.addLayout(row)
    rels = []

    def load():
        status.setText(u"讀取版本清單…")
        QtWidgets.QApplication.processEvents()
        try:
            rels[:] = list_releases()
        except Exception as e:
            status.setText(u"讀不到 GitHub（%s）。請確認網路，或稍後再試。" % e)
            return
        lst.clear()
        for r in rels:
            tag = r["tag"] + (u"（目前）" if cur and _vkey(r["version"]) == _vkey(cur) else "")
            tag += u"（測試版）" if r["prerelease"] else ""
            it = QtWidgets.QListWidgetItem(u"%s   %s" % (tag, r["date"]))
            lst.addItem(it)
        status.setText(u"共 %d 個版本。選一個版本可以看更新內容；裝舊版就是退回。" % len(rels))
        if rels:
            lst.setCurrentRow(0)

    def picked(i):
        if 0 <= i < len(rels):
            r = rels[i]
            notes.setMarkdown(u"## %s\n%s\n\n%s" % (r["title"], r["date"], r["notes"] or u"（沒有說明）"))
            same = cur and _vkey(r["version"]) == _vkey(cur)
            older = cur and _vkey(r["version"]) < _vkey(cur)
            btn.setText(u"重新安裝這一版" if same else (u"退回到 %s" % r["tag"] if older else u"更新到 %s" % r["tag"]))
            btn.setEnabled(True)

    def do_install():
        i = lst.currentRow()
        if not (0 <= i < len(rels)):
            return
        r = rels[i]
        if QtWidgets.QMessageBox.question(d, u"ASR Tools", u"安裝 %s？\n目前的版本會先備份。" % r["tag"]) != QtWidgets.QMessageBox.Yes:
            return
        msgs = []
        try:
            for w in QtWidgets.QApplication.topLevelWidgets():     # close the tool window before replacing its files
                if w.windowTitle().startswith((u"ASR Tools v", u"AS × Mixamo")) and w is not d:
                    w.close()
            install(r, lambda m: (msgs.append(m), status.setText(m), QtWidgets.QApplication.processEvents()))
        except Exception as e:
            QtWidgets.QMessageBox.warning(d, u"ASR Tools", u"安裝失敗：%s" % e)
            return
        QtWidgets.QMessageBox.information(d, u"ASR Tools", u"已安裝 %s。" % r["tag"])
        d.close()
        _reopen_tool()

    lst.currentRowChanged.connect(picked)
    btn.clicked.connect(do_install)
    d.show()
    _dlg = d
    QtCore.QTimer.singleShot(50, load)
    return d
