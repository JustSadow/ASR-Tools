# -*- coding: utf-8 -*-
"""ASR Tools 安裝程式（ASR = AdvancedSkeleton + Retarget）
把這個檔案「拖曳」到 Maya 的 viewport 就會安裝：
  - ASR Tools（程式名 asMixamoTool：骨架轉 Mixamo / Retarget / 批量 Retarget）
  - weightTransfer（權重轉移）
  - Go to Build Pose 按鈕
裝到目前 Maya 版本的 文件\\maya\\<版本>\\scripts 與 prefs\\icons，並在「目前打開的工具架」加按鈕。
舊版會先備份成 *_backup_<日期時間>。
"""
import datetime
import os
import shutil
import sys

HERE = os.path.dirname(os.path.abspath(__file__))


def _install(log=print):
    import maya.cmds as cmds
    import maya.mel as mel

    scripts = cmds.internalVar(userScriptDir=True)
    icons = os.path.join(cmds.internalVar(userPrefDir=True), "icons")
    for d in (scripts, icons):
        if not os.path.isdir(d):
            os.makedirs(d)
    stamp = datetime.datetime.now().strftime("%Y%m%d_%H%M%S")

    # --- code (back up what is there)
    src_pkg = os.path.join(HERE, "scripts", "asMixamoTool")
    dst_pkg = os.path.join(scripts, "asMixamoTool")
    keep_ref = None
    if os.path.isdir(dst_pkg):
        old_ref = os.path.join(dst_pkg, "data", "firing_rifle.fbx")   # a local copy from an old package: keep using it
        backup = dst_pkg + "_backup_" + stamp
        n = 1
        while os.path.exists(backup):
            n += 1
            backup = "%s_backup_%s_%d" % (dst_pkg, stamp, n)
        shutil.move(dst_pkg, backup)
        keep_ref = os.path.join(backup, "data", "firing_rifle.fbx") if os.path.isfile(old_ref) else None
        log(u"舊版 asMixamoTool 已備份")
    shutil.copytree(src_pkg, dst_pkg, ignore=shutil.ignore_patterns("__pycache__", "*.pyc"))
    if keep_ref and not os.path.isfile(os.path.join(dst_pkg, "data", "firing_rifle.fbx")):
        os.makedirs(os.path.join(dst_pkg, "data"), exist_ok=True)
        shutil.copy2(keep_ref, os.path.join(dst_pkg, "data", "firing_rifle.fbx"))
    # keep the 5 newest backups of the tool
    olds = sorted(d for d in os.listdir(scripts) if d.startswith("asMixamoTool_backup_"))
    for d in olds[:-5]:
        shutil.rmtree(os.path.join(scripts, d), ignore_errors=True)
    # the updater lives outside the package so it still works if a version of the tool is broken
    shutil.copy2(os.path.join(HERE, "scripts", "asrUpdater.py"), os.path.join(scripts, "asrUpdater.py"))
    dst_wt = os.path.join(scripts, "weightTransfer.py")
    if os.path.isfile(dst_wt):
        shutil.copy2(dst_wt, dst_wt.replace(".py", "_backup_%s.py.bak" % stamp))
        for f in sorted(x for x in os.listdir(scripts) if x.startswith("weightTransfer_backup_"))[:-5]:
            try:
                os.remove(os.path.join(scripts, f))      # keep the 5 newest
            except OSError:
                pass
    shutil.copy2(os.path.join(HERE, "scripts", "weightTransfer.py"), dst_wt)
    for f in os.listdir(os.path.join(HERE, "icons")):
        shutil.copy2(os.path.join(HERE, "icons", f), os.path.join(icons, f))
    log(u"已複製到 %s 和 %s" % (scripts, icons))

    # --- reload so the new version is used right away
    if scripts not in sys.path:
        sys.path.insert(0, scripts)
    for m in [k for k in list(sys.modules) if k in ("weightTransfer", "asrUpdater") or k == "asMixamoTool" or k.startswith("asMixamoTool.")]:
        del sys.modules[m]

    # --- shelf buttons on the current shelf (skip if already there)
    if cmds.about(batch=True):
        log(u"批次模式，略過工具架")
        return None
    shelf = cmds.tabLayout(mel.eval("$tmp=$gShelfTopLevel"), q=True, selectTab=True)
    have = [cmds.shelfButton(b, q=True, command=True) for b in (cmds.shelfLayout(shelf, q=True, childArray=True) or [])
            if cmds.objectTypeUI(b) == "shelfButton"]
    buttons = [("ASR Tools", "asMixamoTool.png", u"ASR Tools（AdvancedSkeleton + Retarget）：骨架轉 Mixamo／Retarget／批量 Retarget",
                "import asMixamoTool; asMixamoTool.show()"),
               ("WeightTransfer", "weightTransfer.png", u"權重轉移 Weight Transfer",
                "import weightTransfer; weightTransfer.show()"),
               ("BuildPose", "asBuildPose.png", u"Go to Build Pose（不用裝 AS；Ctrl+點擊保留 Main）",
                "import asMixamoTool; asMixamoTool.build_pose()")]
    for label, icon, ann, cmd in buttons:
        if cmd in have:
            # keep the button; just give it the current name (e.g. "AS Mixamo" -> "ASR Tools")
            for b in (cmds.shelfLayout(shelf, q=True, childArray=True) or []):
                if cmds.objectTypeUI(b) == "shelfButton" and cmds.shelfButton(b, q=True, command=True) == cmd:
                    cmds.shelfButton(b, e=True, label=label, annotation=ann)
                    if label == "ASR Tools":
                        _version_menu(b)
            log(u"工具架已有 %s（已更新名稱）" % label)
            continue
        b = cmds.shelfButton(parent=shelf, image=icon, image1=icon, label=label, annotation=ann,
                             command=cmd, sourceType="python")
        if label == "ASR Tools":
            _version_menu(b)
        log(u"已加到工具架「%s」：%s" % (shelf, label))
    mel.eval("saveAllShelves $gShelfTopLevel")
    return shelf


def _version_menu(button):
    """Right-click on the ASR Tools shelf button > Versions / Update (works even if the tool itself fails to open).
    A shelf-button menu item is saved with the shelf as MEL with a plain-ASCII label, so: English label, MEL command."""
    import maya.cmds as cmds
    label = "Versions / Update"
    # the items of a shelf-button menu cannot be read back, so the button carries a docTag (saved with the shelf)
    # once the item is added
    if (cmds.shelfButton(button, q=True, docTag=True) or "") == "asrVersionMenu":
        return
    cmds.shelfButton(button, e=True, menuItem=[(label, 'python("import asrUpdater; asrUpdater.show()")')],
                     docTag="asrVersionMenu")


def onMayaDroppedPythonFile(*args):
    import maya.cmds as cmds
    msgs = []
    try:
        _install(msgs.append)
        for m in msgs:
            print(m)
        cmds.confirmDialog(title="ASR Tools", message=u"安裝完成！\n\n" + "\n".join(msgs), button=["OK"])
    except Exception as e:
        import traceback
        traceback.print_exc()
        cmds.confirmDialog(title="ASR Tools", message=u"安裝失敗：%s" % e, button=["OK"])
