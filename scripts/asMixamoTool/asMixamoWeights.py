# -*- coding: utf-8 -*-
"""Swap skin weights.

Reads every skinCluster of a rig file (e.g. CharA_Rig.mb with fixed weights) and writes the
weights into animation files that carry an older copy of the same rig.  Only skinCluster data
changes (weights, bind matrices, missing influences); keys, anim layers, controls and joints are
never touched - every file is checked before it is saved.
"""
import datetime
import os
import shutil

import maya.cmds as cmds
import maya.api.OpenMaya as om
import maya.api.OpenMayaAnim as oma

TOL_JOINT = 1e-4


def _log(cb, msg):
    if cb:
        cb(msg)


def _short(n):
    return n.split("|")[-1].split(":")[-1]


def _key(path):
    """DAG path without namespaces: |Group|Geometry|Body -> matching key between files."""
    return "|".join(p.split(":")[-1] for p in path.split("|"))


def _sel(node):
    sl = om.MSelectionList()
    sl.add(node)
    return sl


def _all_verts(n):
    fc = om.MFnSingleIndexedComponent()
    comp = fc.create(om.MFn.kMeshVertComponent)
    fc.setCompleteData(n)
    return comp


def _skin_map():
    """{key: (skinCluster, shape, transform)} for every skinned mesh in the scene."""
    out = {}
    for sc in cmds.ls(type="skinCluster"):
        for shape in cmds.skinCluster(sc, q=True, geometry=True) or []:
            shape = (cmds.ls(shape, long=True) or [shape])[0]
            if cmds.nodeType(shape) != "mesh":
                continue
            tr = cmds.listRelatives(shape, parent=True, fullPath=True)[0]
            out[_key(tr)] = (sc, shape, tr)
    return out


def _find(entry, skins):
    if entry["key"] in skins:
        return skins[entry["key"]]
    hits = [v for k, v in skins.items() if k.split("|")[-1] == entry["short"]]
    return hits[0] if len(hits) == 1 else None


def _read_skin(sc, shape):
    fn = oma.MFnSkinCluster(_sel(sc).getDependNode(0))
    dag = _sel(shape).getDagPath(0)
    n = cmds.polyEvaluate(shape, vertex=True)
    infs = fn.influenceObjects()
    w, _ = fn.getWeights(dag, _all_verts(n))
    names = [_short(p.partialPathName()) for p in infs]
    bpm = {}
    for p, name in zip(infs, names):
        li = fn.indexForInfluenceObject(p)
        bpm[name] = list(cmds.getAttr("%s.bindPreMatrix[%d]" % (sc, li)))
    method = cmds.getAttr(sc + ".skinningMethod")
    blend = list(fn.getBlendWeights(dag, _all_verts(n))) if method == 2 else None
    return {"vtx": n, "infs": names, "weights": list(w), "bpm": bpm, "method": method,
            "maxInf": cmds.getAttr(sc + ".maxInfluences"),
            "maintainMax": cmds.getAttr(sc + ".maintainMaxInfluences"), "blend": blend}


def read_scene(cb=None):
    """Weights of every skinned mesh in the current scene."""
    meshes = []
    for key, (sc, shape, tr) in sorted(_skin_map().items()):
        e = _read_skin(sc, shape)
        e.update({"key": key, "short": key.split("|")[-1], "skin": sc})
        meshes.append(e)
        _log(cb, u"  讀取 %s：%d 個頂點、%d 根骨頭" % (e["short"], e["vtx"], len(e["infs"])))
    return {"meshes": meshes}


def read_file(rig, cb=None):
    _log(cb, u"開新權重的 rig：" + os.path.basename(rig))
    cmds.file(rig, open=True, force=True, executeScriptNodes=False, ignoreVersion=True)
    data = read_scene(cb)
    data["rig"] = rig
    if not data["meshes"]:
        raise RuntimeError(u"rig 檔裡找不到有蒙皮的模型")
    return data


def _find_influence(name):
    hits = [n for n in cmds.ls(name, long=True) + cmds.ls("*:" + name, long=True)
            if cmds.objectType(n, isAType="transform")]
    return hits[0] if len(hits) == 1 else None


def _apply_one(e, sc, shape, cb):
    """Write one mesh's weights. Returns a dict describing what changed."""
    n = cmds.polyEvaluate(shape, vertex=True)
    if n != e["vtx"]:
        raise ValueError(u"頂點數不同（rig %d／動作檔 %d），模型可能改過拓樸" % (e["vtx"], n))
    cur = {_short(x): x for x in cmds.skinCluster(sc, q=True, influence=True) or []}
    missing = [x for x in e["infs"] if x not in cur]
    found = {x: _find_influence(x) for x in missing}
    lost = [x for x, v in found.items() if not v]
    if lost:
        raise ValueError(u"動作檔裡沒有這些骨頭：%s" % ", ".join(lost))
    for x in missing:
        cmds.skinCluster(sc, e=True, addInfluence=found[x], weight=0.0)
    fn = oma.MFnSkinCluster(_sel(sc).getDependNode(0))
    dag = _sel(shape).getDagPath(0)
    infs = fn.influenceObjects()
    names = [_short(p.partialPathName()) for p in infs]
    # bind matrices = the rig's (needed for added bones; same as before for the others)
    bpm_set = 0
    for p, name in zip(infs, names):
        m = e["bpm"].get(name)
        if not m:
            continue
        plug = "%s.bindPreMatrix[%d]" % (sc, fn.indexForInfluenceObject(p))
        if cmds.listConnections(plug, s=True, d=False):
            continue
        old = cmds.getAttr(plug)
        if max(abs(a - b) for a, b in zip(old, m)) > 1e-5:
            cmds.setAttr(plug, *m, type="matrix")
            bpm_set += 1
    nt, ns = len(names), len(e["infs"])
    idx = [names.index(x) for x in e["infs"]]
    vals = [0.0] * (n * nt)
    src = e["weights"]
    for v in range(n):
        so, to = v * ns, v * nt
        for i, t in enumerate(idx):
            vals[to + t] = src[so + i]
    for attr, key in (("skinningMethod", "method"), ("maxInfluences", "maxInf"), ("maintainMaxInfluences", "maintainMax")):
        if not cmds.listConnections("%s.%s" % (sc, attr), s=True, d=False):
            cmds.setAttr("%s.%s" % (sc, attr), e[key])
    comp = _all_verts(n)
    fn.setWeights(dag, comp, om.MIntArray(list(range(nt))), om.MDoubleArray(vals), False)
    if e.get("blend"):
        fn.setBlendWeights(dag, comp, om.MDoubleArray(e["blend"]))
    # read back: the weights must equal the rig's
    back, _ = fn.getWeights(dag, _all_verts(n))
    err = max(abs(back[i] - vals[i]) for i in range(len(vals))) if vals else 0.0
    return {"added": missing, "bpm": bpm_set, "err": err}


def apply_scene(data, cb=None):
    skins = _skin_map()
    done, skipped = [], []
    for e in data["meshes"]:
        t = _find(e, skins)
        if not t:
            skipped.append((e["short"], u"動作檔裡沒有這個模型（或沒蒙皮）"))
            continue
        try:
            r = _apply_one(e, t[0], t[1], cb)
            r["mesh"] = e["short"]
            done.append(r)
            extra = (u"，補上骨頭 %s" % ", ".join(r["added"])) if r["added"] else u""
            _log(cb, u"  %s：已換%s" % (e["short"], extra))
        except Exception as ex:
            skipped.append((e["short"], str(ex)))
    for name, why in skipped:
        _log(cb, u"  %s：略過（%s）" % (name, why))
    return {"done": done, "skipped": skipped}


def _joint_snapshot():
    joints = cmds.ls(type="joint", long=True)
    st, en = cmds.playbackOptions(q=True, minTime=True), cmds.playbackOptions(q=True, maxTime=True)
    frames = sorted({st, round((st + en) / 2.0), en})
    out = {}
    for f in frames:
        cmds.currentTime(f, edit=True)
        for j in joints:
            out[(j, f)] = cmds.xform(j, q=True, ws=True, m=True)
    return out


def _anim_stats():
    curves = cmds.ls(type="animCurve")
    keys = cmds.keyframe(curves, q=True, keyframeCount=True) if curves else 0
    return len(curves), keys, len(cmds.ls(type="animLayer"))


def _backup(path):
    d = os.path.join(os.path.dirname(path), "_weights_backup")
    if not os.path.isdir(d):
        os.makedirs(d)
    base, ext = os.path.splitext(os.path.basename(path))
    dst = os.path.join(d, base + ext)
    if os.path.exists(dst):
        dst = os.path.join(d, "%s_%s%s" % (base, datetime.datetime.now().strftime("%Y%m%d_%H%M%S"), ext))
    shutil.copy2(path, dst)
    return dst


def swap_file(path, out, data, overwrite=False, cb=None):
    """Open an animation file, put the rig's weights in, check the animation, save."""
    cmds.file(path, open=True, force=True, executeScriptNodes=False, ignoreVersion=True)
    cur = cmds.currentTime(q=True)
    stats0 = _anim_stats()
    snap0 = _joint_snapshot()
    rep = apply_scene(data, cb)
    if not rep["done"]:
        raise RuntimeError(u"沒有任何模型能換（%s）" % "; ".join(u"%s：%s" % s for s in rep["skipped"]))
    stats1 = _anim_stats()
    snap1 = _joint_snapshot()
    jerr = max([max(abs(a - b) for a, b in zip(snap0[k], snap1[k])) for k in snap0] or [0.0])
    if stats0 != stats1 or jerr > TOL_JOINT:
        raise RuntimeError(u"動畫有變化（key %s→%s，骨頭誤差 %.5f），沒有存檔" % (stats0, stats1, jerr))
    werr = max([r["err"] for r in rep["done"]] or [0.0])
    cmds.currentTime(cur, edit=True)
    backup = None
    if overwrite:
        backup = _backup(path)
        out = path
    cmds.file(rename=out)
    cmds.file(save=True, force=True, type="mayaAscii" if out.lower().endswith(".ma") else "mayaBinary")
    rep.update({"out": out, "backup": backup, "jointErr": jerr, "weightErr": werr,
                "curves": stats0[0], "keys": stats0[1]})
    return rep
