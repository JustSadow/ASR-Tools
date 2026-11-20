# -*- coding: utf-8 -*-
"""Export an AS rig scene as a game FBX: the deformation skeleton + the skinned meshes only.

Runs on a COPY of the scene (in the background worker), so the animator's scene is never touched:
  1. animation on  -> bake every DeformationSystem joint (translate / rotate / scale) over the range
     animation off -> put the rig in its build pose (bind pose), no keys
  2. gun on  -> keep Gun_Weapon (joint under Wrist_R) and Gun_Geo (skinned to it); gun off -> delete them
     weapon on -> keep the weapon joints (Weapon_Joint, Weapon...) and the meshes skinned only to them; off -> delete
  3. drop constraints, controls and every other rig node; Root_M and the meshes go to the world
  4. FBX: skins + blend shapes, baked animation (or none), Y-up, centimetres
"""
import os
import re

import maya.cmds as cmds
import maya.mel as mel

GUN_JOINTS = ("Gun_Weapon",)
GUN_GROUPS = ("GunRig",)


def weapon_joints():
    """Joints of a hand-held weapon rig (Weapon_Joint under Wrist_R, a switch-hand 'Weapon' under Root_M...):
    deformation joints whose name has 'weapon', the gun's Gun_Weapon excepted (it has its own option)."""
    js = cmds.listRelatives("DeformationSystem", allDescendents=True, type="joint", fullPath=True) or []         if cmds.objExists("DeformationSystem") else []
    return [j for j in js if "weapon" in j.split("|")[-1].lower() and j.split("|")[-1] not in GUN_JOINTS]


def _only_on(mesh, joints):
    """True if every influence of the mesh's skin is one of `joints`."""
    sk = cmds.ls(cmds.listHistory(mesh) or [], type="skinCluster")
    if not sk:
        return False
    inf = [cmds.ls(i, long=True)[0] for i in cmds.skinCluster(sk[0], q=True, inf=True) or []]
    return bool(inf) and all(i in joints for i in inf)


def _log(cb, msg):
    if cb:
        cb(msg)


def _skinned_meshes(roots):
    """Mesh transforms that carry a skinCluster, under the given groups (Geometry, GunRig...)."""
    out = []
    for r in roots:
        for shp in cmds.listRelatives(r, allDescendents=True, type="mesh", fullPath=True) or []:
            if cmds.getAttr(shp + ".intermediateObject"):
                continue
            tr = cmds.listRelatives(shp, parent=True, fullPath=True)[0]
            if cmds.ls(cmds.listHistory(tr) or [], type="skinCluster") and tr not in out:
                out.append(tr)
    return out


def scene_info():
    """For the window: does the current scene look like an AS rig, does it have a gun rig, keys, range."""
    curves = cmds.ls(type=("animCurveTL", "animCurveTA", "animCurveTU"))
    return {"as": cmds.objExists("DeformationSystem"),
            "gun": cmds.objExists("Gun_Weapon") or cmds.objExists("GunRig"),
            "weapon": bool(weapon_joints()),
            "animated": bool(curves),
            "range": (cmds.playbackOptions(q=True, min=True), cmds.playbackOptions(q=True, max=True))}


def _skin_bind(meshes):
    """{joint long name: world MMatrix at skin bind} = inverse(bindPreMatrix) of the skinCluster using it."""
    import maya.api.OpenMaya as om
    out = {}
    for m in meshes:
        for sc in cmds.ls(cmds.listHistory(m) or [], type="skinCluster"):
            for idx in cmds.getAttr(sc + ".matrix", multiIndices=True) or []:
                src = cmds.listConnections("%s.matrix[%d]" % (sc, idx), s=True, d=False)
                if src:
                    out.setdefault(cmds.ls(src[0], long=True)[0],
                                   om.MMatrix(cmds.getAttr("%s.bindPreMatrix[%d]" % (sc, idx))).inverse())
    return out


def _free(joints):
    """Cut every rig input of the joints (constraints, offsetParentMatrix, driven translate/rotate/scale/orient, keys)
    and set offsetParentMatrix to identity: FBX ignores offsetParentMatrix, so afterwards the plain transform must
    carry the whole pose."""
    jset = set(joints)
    for c in cmds.ls(type="constraint"):
        driven = cmds.listConnections(c, s=False, d=True) or []
        if any(cmds.ls(d, long=True)[0] in jset for d in driven if cmds.objExists(d) and cmds.nodeType(d) == "joint"):
            try:
                cmds.delete(c)
            except Exception:
                pass
    for j in joints:
        pairs = cmds.listConnections(j, s=True, d=False, plugs=True, connections=True) or []
        for dst, src in zip(pairs[0::2], pairs[1::2]):
            if dst.split(".")[-1] in ("inverseScale",) or dst.split(".")[-1].startswith("message"):
                continue
            try:
                cmds.disconnectAttr(src, dst)
            except Exception:
                pass
        if cmds.attributeQuery("offsetParentMatrix", node=j, exists=True):
            cmds.setAttr(j + ".offsetParentMatrix", [1, 0, 0, 0, 0, 1, 0, 0, 0, 0, 1, 0, 0, 0, 0, 1], type="matrix")


def export_rig_fbx(scene, out, anim=True, gun=True, start=None, end=None, cb=None, weapon=True):
    """Open `scene` (a temp copy), reduce it to skeleton + meshes and export `out`. Returns a summary dict."""
    try:
        from . import asMixamoCore as core
    except ImportError:          # top-level import in the background worker
        import asMixamoCore as core
    core.load_fbx()
    cmds.file(scene, open=True, force=True, prompt=False)
    if not cmds.objExists("DeformationSystem"):
        raise RuntimeError(u"這不是 AdvancedSkeleton 的 rig（找不到 DeformationSystem）")
    if start is None or end is None:
        start, end = cmds.playbackOptions(q=True, min=True), cmds.playbackOptions(q=True, max=True)
    start, end = int(round(start)), int(round(end))
    joints = cmds.listRelatives("DeformationSystem", allDescendents=True, type="joint", fullPath=True) or []
    has_gun = any(cmds.objExists(n) for n in GUN_JOINTS + GUN_GROUPS)
    geo_roots = [g for g in ("Geometry",) if cmds.objExists(g)]
    if gun and has_gun:
        geo_roots += [g for g in GUN_GROUPS if cmds.objExists(g)]
    meshes = _skinned_meshes(geo_roots)
    wjoints = weapon_joints()
    has_weapon = bool(wjoints)
    if not weapon and wjoints:          # the weapon meshes are the ones skinned only to weapon joints
        meshes = [m for m in meshes if not _only_on(m, set(wjoints))]
    if not meshes:
        raise RuntimeError(u"找不到有蒙皮的模型（Geometry 底下）")

    import maya.api.OpenMaya as om
    joints = sorted(joints, key=lambda x: x.count("|"))          # parents first
    parent = {jn: (cmds.listRelatives(jn, parent=True, fullPath=True) or [None])[0] for jn in joints}
    W = lambda n: om.MMatrix(cmds.xform(n, q=True, ws=True, m=True))

    # 1. what the joints must show: every frame's world matrices, or the skin bind pose
    if anim:
        _log(cb, u"記錄骨架動作 %d-%d（%d 根骨頭）…" % (start, end, len(joints)))
        frames = list(range(start, end + 1))
        mats = {}
        for f in frames:
            cmds.currentTime(f)
            mats[f] = [list(W(jn)) for jn in joints]
    else:
        _log(cb, u"放到蒙皮時的姿勢（不含動畫）…")
        layers = [l for l in cmds.ls(type="animLayer") if l != "BaseAnimation"]
        if layers:
            cmds.delete(layers)
        curves = cmds.ls(type=("animCurveTL", "animCurveTA", "animCurveTU", "animCurveTT"))
        if curves:
            cmds.delete(curves)
        cmds.currentTime(cmds.currentTime(q=True))
        cur = {jn: W(jn) for jn in joints}
        bind = _skin_bind(meshes)
        target = {}
        for jn in joints:      # skinned: the bind matrix; others: same offset to their parent as now
            p = parent[jn]
            if jn in bind:
                target[jn] = bind[jn]
            elif p in target:
                target[jn] = cur[jn] * cur[p].inverse() * target[p]
            else:
                target[jn] = cur[jn]

    # 2. free the joints from the rig, then write the matrices back on plain transforms
    _free(joints)
    if anim:
        _log(cb, u"寫回 %d 格…" % len(frames))
        attrs = ["tx", "ty", "tz", "rx", "ry", "rz", "sx", "sy", "sz"]
        for f in frames:
            cmds.currentTime(f, update=False)
            for jn, m in zip(joints, mats[f]):
                cmds.xform(jn, ws=True, m=m)
                cmds.setKeyframe(jn, attribute=attrs, time=f)
        rot = cmds.listConnections(joints, type="animCurveTA") or []
        if rot:
            cmds.filterCurve(list(set(rot)), filter="euler")
    else:
        for jn in joints:
            cmds.xform(jn, ws=True, m=list(target[jn]))

    # 3. gun off: remove the weapon joint and mesh
    removed = []
    if not gun:
        for n in GUN_GROUPS + GUN_JOINTS:
            if cmds.objExists(n):
                cmds.delete(n)
                removed.append(n)
        joints = [j for j in joints if cmds.objExists(j)]
    if not weapon and wjoints:
        for wj in sorted(wjoints, key=lambda x: -x.count("|")):
            if cmds.objExists(wj):
                removed.append(wj.split("|")[-1])
                cmds.delete(wj)
        joints = [j for j in joints if cmds.objExists(j)]

    # 4. keep only Root_M's skeleton and the meshes, at the world
    roots = [j for j in (cmds.listRelatives("DeformationSystem", children=True, type="joint", fullPath=True) or [])]
    keep = []
    for r in roots:
        keep.append(cmds.parent(r, world=True)[0])
    for m in meshes:
        if cmds.objExists(m):
            for at in ("tx", "ty", "tz", "rx", "ry", "rz", "sx", "sy", "sz"):
                cmds.setAttr(m + "." + at, lock=False)
            keep.append(cmds.parent(m, world=True)[0] if cmds.listRelatives(m, parent=True) else m)
    for top in cmds.ls(assemblies=True):
        if top in keep or cmds.listRelatives(top, shapes=True, type="camera"):
            continue
        try:
            cmds.delete(top)
        except Exception:
            pass

    # 5. FBX
    os.makedirs(os.path.dirname(out) or ".", exist_ok=True)
    cmds.select(keep, replace=True)
    mel.eval("FBXResetExport")
    mel.eval("FBXExportSkins -v true")
    mel.eval("FBXExportShapes -v true")
    mel.eval("FBXExportSmoothingGroups -v true")
    mel.eval("FBXExportInputConnections -v false")
    mel.eval("FBXExportConstraints -v false")
    mel.eval("FBXExportCameras -v false")
    mel.eval("FBXExportLights -v false")
    mel.eval("FBXExportUpAxis y")
    mel.eval("FBXExportInAscii -v false")
    if anim:
        mel.eval("FBXExportBakeComplexAnimation -v true")
        mel.eval("FBXExportBakeComplexStart -v %d" % start)
        mel.eval("FBXExportBakeComplexEnd -v %d" % end)
        mel.eval("FBXExportBakeComplexStep -v 1")
        mel.eval("FBXExportBakeResampleAnimation -v true")
    else:
        mel.eval("FBXExportBakeComplexAnimation -v false")
        mel.eval("FBXExportAnimationOnly -v false")
    mel.eval('FBXExport -f "%s" -s' % out.replace("\\", "/"))
    return {"out": out, "joints": len(cmds.ls(type="joint")), "meshes": [m.split("|")[-1] for m in meshes if cmds.objExists(m.split("|")[-1])],
            "anim": anim, "range": (start, end) if anim else None, "gun": bool(gun and has_gun), "weapon": bool(weapon and has_weapon), "removed": removed,
            "size": os.path.getsize(out) if os.path.isfile(out) else 0}
