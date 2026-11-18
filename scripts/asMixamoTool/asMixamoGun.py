# -*- coding: utf-8 -*-
"""Two-hand gun prop for any AdvancedSkeleton rig (asMixamoTool).

add_gun_to_rig(rig, out, ref_fbx) does it all on a copy of the rig:
  1. retargets a Mixamo rifle-aiming motion onto the rig (temp file) and measures where its hands really are
  2. places the gun: grip in the right palm, barrel along the SOURCE motion's aim line, sized to the character
  3. builds GunRig:  Gun_Space (Main <-> Wrist_R by Gun_Ctrl.gunInHand) / Gun_Ctrl / LeftGrip_Loc / LeftGrip_IK
     + Gun_Geo (placeholder rifle or your model) skinned to a weapon joint "Gun_Weapon" under Wrist_R, which follows
       Gun_Ctrl, so an FBX export carries the gun's own motion
     + IKArm_L.followGun: 0 = left hand free, 1 = left hand rides along with the gun (switch with toggle_follow_gun)
     + Gun_Ctrl.showGun (default 0 = hidden): the same rig serves motions without the gun
Never saves over the input rig."""
import json
import os
import re
import tempfile

import maya.cmds as cmds
import maya.api.OpenMaya as om

GUN_JOINT = "Gun_Weapon"
HERE = os.path.dirname(os.path.abspath(__file__))
DEFAULT_REF = os.path.join(HERE, "data", "firing_rifle.fbx")    # built-in Mixamo "Firing Rifle" (Y Bot)
REF_OVERRIDE = None   # set by the window: the aiming / firing motion the user picked


def _ref(ref_fbx=None):
    """The aiming motion to pose the rig with: the one given, the one picked in the window, else a local
    data/firing_rifle.fbx (not shipped: Mixamo motions may not be redistributed)."""
    for p in (ref_fbx, REF_OVERRIDE, DEFAULT_REF):
        if p and os.path.isfile(p):
            return p
    raise RuntimeError(u"請先選「開槍姿勢」用的動作 FBX（例如 Mixamo 免費的 Firing Rifle，下載一次就好）")
SETUP = "GunSetup"


def _core():
    try:
        from . import asMixamoCore as core
    except ImportError:
        import asMixamoCore as core
    return core


def _log(cb, msg):
    cb(msg) if cb else print(msg)


def _wmat(n):
    return om.MMatrix(cmds.xform(n, q=True, ws=True, m=True))


def _ws(n):
    return om.MVector(*cmds.xform(n, q=True, ws=True, t=True))


def _hand_tip(side):
    for f in ("MiddleFinger1_", "IndexFinger1_", "RingFinger1_", "PinkyFinger1_"):
        if cmds.objExists(f + side):
            return f + side
    return None


# --------------------------------------------------------------------------------------------- 1. reference pose
def reference_pose(rig, ref_fbx=None, frame=30, cb=None):
    """Retarget the aiming motion onto the rig (temp copy) and return the gun placement data."""
    ref_fbx = _ref(ref_fbx)
    tmp = os.path.join(tempfile.mkdtemp(prefix="asGunRef_"), "ref.mb")
    _log(cb, u"  參考瞄準動作 Retarget 中…")
    r = _core().retarget_motion(rig, ref_fbx, tmp, reduce=False, euler=False)
    frame = min(max(frame, r["start"]), r["end"])
    cmds.file(tmp, open=True, force=True, prompt=False)
    cmds.currentTime(frame)
    return _measure(ref_fbx, frame, cb)


def _measure(ref_fbx, frame, cb=None):
    """In the opened retargeted scene at `frame`: where the gun goes (gun space relative to the right wrist) and
    where the left hand grips it. Imports the source FBX into 'gunsrc' for the aim line and removes it again."""
    tip = _hand_tip("R")
    R_ref, WL_ref = _wmat("Wrist_R"), _wmat("Wrist_L")
    pr, pl = _ws("Wrist_R"), _ws("Wrist_L")
    tipv = _ws(tip) if tip else pr + (pr - _ws("Elbow_R")).normal() * ((pl - pr).length() * 0.3)
    hand = (tipv - pr).length()
    d = (pl - pr).length()
    # barrel = source motion's aim line (right hand -> left hand of the source skeleton)
    cmds.loadPlugin("fbxmaya", quiet=True)
    cmds.namespace(add="gunsrc")
    cmds.namespace(set="gunsrc")
    try:
        cmds.file(ref_fbx, i=True, type="FBX", ignoreVersion=True, options="fbx")
    finally:
        cmds.namespace(set=":")
    cmds.currentTime(frame)
    sr = (cmds.ls("gunsrc:*RightHand") + cmds.ls("gunsrc:*:RightHand") + cmds.ls("gunsrc:RightHand"))
    sl = (cmds.ls("gunsrc:*LeftHand") + cmds.ls("gunsrc:*:LeftHand") + cmds.ls("gunsrc:LeftHand"))
    z = ((_ws(sl[0]) - _ws(sr[0])) if (sr and sl) else (pl - pr)).normal()
    x = (om.MVector(0, 1, 0) ^ z).normal()
    y = (z ^ x).normal()
    palm = pr + (tipv - pr) * 0.55
    G_ref = om.MMatrix([x.x, x.y, x.z, 0, y.x, y.y, y.z, 0, z.x, z.y, z.z, 0, palm.x, palm.y, palm.z, 1])
    zl = max((pl - palm) * z, d * 0.6)
    geo_top = "Geometry" if cmds.objExists("Geometry") else ("DeformationSystem" if cmds.objExists("DeformationSystem") else None)
    if geo_top:                      # short / chibi characters: keep the gun under ~0.9 x body height
        bb = cmds.exactWorldBoundingBox(geo_top)
        zl = min(zl, (bb[4] - bb[1]) * 0.9 / 2.9)
    wl = om.MTransformationMatrix(WL_ref)
    wl.setTranslation(palm + z * zl - y * (hand * 0.35), om.MSpace.kWorld)
    out = {"gun_to_wrist": list(G_ref * R_ref.inverse()), "grip_local": list(wl.asMatrix() * G_ref.inverse()),
           "hand": hand, "zl": zl, "dist": d, "frame": frame}
    try:
        cmds.namespace(removeNamespace="gunsrc", deleteNamespaceContent=True)
    except Exception:
        pass
    _log(cb, u"  雙手距離 %.1f cm，手掌 %.1f cm → 槍長約 %.0f cm" % (d, hand, zl * 2.9))
    return out


# --------------------------------------------------------------------------------------------- 2. geometry
def _placeholder(hand, zl):
    """Chunky toy rifle in gun space: origin = grip in the palm, +Z = barrel, +Y = up."""
    parts = []

    def box(n, w, h, dz, cy, cz, col):
        t = cmds.polyCube(name=n, w=w, h=h, d=dz, ch=False)[0]
        cmds.move(0, cy, cz, t)
        parts.append((t, col))

    def cyl(n, r, length, cz, cy, col):
        t = cmds.polyCylinder(name=n, r=r, h=length, sx=12, ch=False)[0]
        cmds.rotate(90, 0, 0, t)
        cmds.move(0, cy, cz, t)
        parts.append((t, col))
    dark, mid, acc = (0.16, 0.17, 0.2), (0.32, 0.33, 0.36), (0.93, 0.55, 0.15)
    hand = max(hand, zl * 0.2)       # thickness follows the gun's length (tiny chibi hands made a thin rod)
    bh = hand * 0.15
    box("gun_receiver", hand * 1.0, hand * 1.1, zl * 0.7, bh, zl * 0.25, mid)
    box("gun_stock", hand * 0.8, hand * 1.1, zl * 0.35, bh - hand * 0.1, -zl * 0.25, dark)
    box("gun_butt", hand * 0.85, hand * 1.4, hand * 0.35, bh - hand * 0.15, -zl * 0.45, acc)
    box("gun_grip", hand * 0.55, hand * 1.1, hand * 0.55, bh - hand * 0.8, 0, dark)
    box("gun_mag", hand * 0.6, hand * 1.3, hand * 0.7, bh - hand * 0.95, zl * 0.45, acc)
    box("gun_handguard", hand * 1.05, hand * 0.9, zl * 0.75, bh, zl * 0.98, dark)
    cyl("gun_barrel", hand * 0.22, zl * 0.8, zl * 1.75, bh + hand * 0.1, mid)
    box("gun_muzzle", hand * 0.6, hand * 0.6, hand * 0.55, bh + hand * 0.1, zl * 2.18, acc)
    box("gun_sight", hand * 0.3, hand * 0.45, hand * 0.9, bh + hand * 0.7, zl * 0.2, acc)
    box("gun_sight2", hand * 0.25, hand * 0.5, hand * 0.3, bh + hand * 0.6, zl * 1.3, acc)
    for t, c in parts:
        sh = cmds.shadingNode("lambert", asShader=True, name="gunMat_" + t)
        cmds.setAttr(sh + ".color", *c, type="double3")
        sg = cmds.sets(renderable=True, noSurfaceShader=True, empty=True, name=sh + "SG")
        cmds.connectAttr(sh + ".outColor", sg + ".surfaceShader")
        cmds.sets(t, edit=True, forceElement=sg)
    return cmds.polyUnite([t for t, _ in parts], ch=False, mergeUVSets=True, name="Gun_Geo")[0]


def _import_model(path, zl, autoscale):
    """Your own rifle: modelled with the grip at the origin, barrel along +Z, up +Y (cm)."""
    before = set(cmds.ls(assemblies=True))
    cmds.file(path, i=True, ignoreVersion=True, mergeNamespacesOnClash=True, namespace=":")
    new = [n for n in cmds.ls(assemblies=True) if n not in before]
    meshes = [n for n in new if cmds.listRelatives(n, allDescendents=True, type="mesh")]
    if not meshes:
        raise RuntimeError(u"槍模型檔裡沒有網格：" + path)
    geo = cmds.polyUnite(meshes, ch=False, name="Gun_Geo")[0] if len(meshes) > 1 else cmds.rename(meshes[0], "Gun_Geo")
    leftover = [n for n in new if cmds.objExists(n) and n != geo]
    if leftover:
        cmds.delete(leftover)
    if autoscale:
        bb = cmds.exactWorldBoundingBox(geo)
        length = bb[5] - bb[2]
        if length > 1e-6:
            s = zl * 2.9 / length
            cmds.scale(s, s, s, geo, pivot=(0, 0, 0), absolute=True)
            cmds.makeIdentity(geo, apply=True, scale=True)
    return geo


# --------------------------------------------------------------------------------------------- 3. follow
def add_follow_gun(side="L", gun="Gun_Ctrl"):
    """IKArm_<side>.followGun: 0 = free, 1 = the hand rides along with the gun (on the IKExtra layer, offset taken at
    the bind pose, so the IK control stays free to animate)."""
    ik = "IKArm_" + side
    extra = (cmds.listRelatives(ik, parent=True) or [None])[0]
    if not extra or cmds.attributeQuery("followGun", node=ik, exists=True):
        return None
    anchor = cmds.createNode("transform", name="FollowGunAnchor_" + side, parent=cmds.listRelatives(extra, parent=True)[0])
    cmds.xform(anchor, os=True, m=cmds.xform(extra, q=True, os=True, m=True))
    con = cmds.parentConstraint(anchor, gun, extra, maintainOffset=True, name="FollowGun_" + side)[0]
    cmds.setAttr(con + ".interpType", 2)
    w = cmds.parentConstraint(con, q=True, weightAliasList=True)
    cmds.addAttr(ik, longName="followGun", attributeType="double", min=0, max=1, defaultValue=0, keyable=True)
    rev = cmds.createNode("reverse", name="FollowGunRev_" + side)
    cmds.connectAttr(ik + ".followGun", rev + ".inputX")
    cmds.connectAttr(rev + ".outputX", con + "." + w[0])
    cmds.connectAttr(ik + ".followGun", con + "." + w[1])
    return con


# --------------------------------------------------------------------------------------------- 4. all together
def add_gun_to_rig(rig, out, ref_fbx=None, frame=30, model=None, autoscale=True, cb=None):
    if os.path.normcase(os.path.abspath(out)) == os.path.normcase(os.path.abspath(rig)):
        raise RuntimeError(u"輸出不能是原本的 rig 檔")
    ref = reference_pose(rig, ref_fbx, frame, cb)
    cmds.file(rig, open=True, force=True, prompt=False)
    return _build_gun_rig(rig, out, ref, model, autoscale, cb)


def _build_gun_rig(rig, out, ref, model=None, autoscale=True, cb=None):
    """Build GunRig on the rig that is OPEN now (a clean A/T-pose rig) from placement data and save it as `out`."""
    for n in ("Wrist_R", "Wrist_L", "IKArm_L", "Main"):
        if not cmds.objExists(n):
            raise RuntimeError(u"rig 裡找不到 %s（不是 AS rig？）" % n)
    if cmds.objExists("GunRig"):
        raise RuntimeError(u"這個 rig 已經有槍了（GunRig）")
    hand, zl = ref["hand"], ref["zl"]
    G_bind = om.MMatrix(ref["gun_to_wrist"]) * _wmat("Wrist_R")
    geo = _import_model(model, zl, autoscale) if model else _placeholder(hand, zl)
    cmds.xform(geo, centerPivots=False, pivots=(0, 0, 0))

    top = cmds.group(empty=True, name="GunRig")
    space = cmds.group(empty=True, name="Gun_Space", parent=top)
    ctrl = cmds.circle(name="Gun_Ctrl", normal=(0, 0, 1), radius=hand * 1.6, ch=False)[0]
    cmds.setAttr(ctrl + "Shape.overrideEnabled", 1)
    cmds.setAttr(ctrl + "Shape.overrideColor", 17)
    cmds.parent(ctrl, space)
    loc = cmds.spaceLocator(name="LeftGrip_Loc")[0]
    cmds.setAttr(loc + "Shape.localScale", hand * 0.5, hand * 0.5, hand * 0.5)
    cmds.parent(loc, ctrl)
    cmds.addAttr(ctrl, longName="gunInHand", attributeType="double", min=0, max=1, defaultValue=1, keyable=True)
    cmds.addAttr(ctrl, longName="showGun", attributeType="bool", defaultValue=False, keyable=True)
    # geo in gun space -> world at the bind pose
    cmds.parent(geo, ctrl)
    cmds.xform(space, ws=True, m=list(G_bind))
    cmds.xform(loc, os=True, m=ref["grip_local"])
    ik_tgt = cmds.createNode("transform", name="LeftGrip_IK", parent=loc)
    cmds.xform(ik_tgt, os=True, m=list(_wmat("IKArm_L") * _wmat("Wrist_L").inverse()))
    # world <-> right hand
    con = cmds.parentConstraint("Main", "Wrist_R", space, maintainOffset=True, name="Gun_Space_parentConstraint")[0]
    w = cmds.parentConstraint(con, q=True, weightAliasList=True)
    rev = cmds.createNode("reverse", name="Gun_handRev")
    cmds.connectAttr(ctrl + ".gunInHand", rev + ".inputX")
    cmds.connectAttr(rev + ".outputX", con + "." + w[0])
    cmds.connectAttr(ctrl + ".gunInHand", con + "." + w[1])
    cmds.setAttr(con + ".interpType", 2)
    # weapon joint for export: under the right wrist, follows Gun_Ctrl; the gun mesh is skinned to it
    cmds.select(clear=True)
    jnt = cmds.joint(name=GUN_JOINT)
    cmds.parent(jnt, "Wrist_R")
    cmds.xform(jnt, ws=True, m=cmds.xform(ctrl, q=True, ws=True, m=True))
    cmds.makeIdentity(jnt, apply=True, rotate=True)
    cmds.setAttr(jnt + ".radius", hand * 0.4)
    cmds.parent(geo, top)
    cmds.skinCluster(jnt, geo, toSelectedBones=True, maximumInfluences=1, name="Gun_skinCluster")
    cmds.parentConstraint(ctrl, jnt, maintainOffset=True, name=GUN_JOINT + "_parentConstraint")
    if cmds.objExists("DeformSet"):
        try:
            cmds.sets(jnt, add="DeformSet")
        except Exception:
            pass
    # show / hide (hidden by default so non-gun motions are unaffected)
    for n in (geo, loc):
        cmds.connectAttr(ctrl + ".showGun", n + ".visibility")
    cmds.setAttr(geo + ".overrideEnabled", 1)
    cmds.setAttr(geo + ".overrideDisplayType", 2)
    for a in ("sx", "sy", "sz", "v"):
        cmds.setAttr(ctrl + "." + a, lock=True, keyable=False)
    if cmds.objExists("Group"):
        cmds.parent(top, "Group")
    add_follow_gun("L", ctrl)
    # remember how it was built, so 「重新調整」 can bring this gun back into a setup scene
    for name, val in (("cleanRig", os.path.abspath(rig).replace("\\", "/")), ("gunToWrist", json.dumps(ref["gun_to_wrist"])),
                      ("gripLocal", json.dumps(ref["grip_local"]))):
        cmds.addAttr(top, longName=name, dataType="string")
        cmds.setAttr(top + "." + name, val, type="string")
    for name, val in (("handSize", hand), ("gunHalf", zl)):
        cmds.addAttr(top, longName=name, attributeType="double", defaultValue=val)
    cmds.select(clear=True)
    folder = os.path.dirname(os.path.abspath(out))
    if not os.path.isdir(folder):
        os.makedirs(folder)
    cmds.file(rename=out)
    cmds.file(save=True, type="mayaBinary" if out.lower().endswith(".mb") else "mayaAscii", force=True)
    _log(cb, u"  已存：" + out)
    return {"out": out, "length": zl * 2.9, "hand_dist": ref.get("dist", 0)}


# --------------------------------------------------------------------------------------------- 5. interactive setup
# 1) setup_start: the clean rig in a temp scene, posed with the firing motion, a block gun in the right hand
# 2) the artist adjusts the pose (only to judge the placement), the gun (GunSetup_Ctrl), its mesh, the left hand
# 3) setup_finish: records gun-in-right-hand + gun mesh + left-hand grip, opens the CLEAN rig and builds GunRig there
def _no_scale(m):
    t = om.MTransformationMatrix(om.MMatrix(m))
    t.setScale([1, 1, 1], om.MSpace.kWorld)
    t.setShear([0, 0, 0], om.MSpace.kWorld)
    return t.asMatrix()


def _freeze_pose(frame):
    """Keep the pose of `frame` on every animated control and drop the keys, so the pose can be edited freely."""
    vals = []
    for c in cmds.ls(type=("animCurveTL", "animCurveTA", "animCurveTU")) or []:
        for p in cmds.listConnections(c + ".output", s=False, d=True, plugs=True, skipConversionNodes=True) or []:
            if ":" not in p and cmds.objectType(p.split(".")[0], isAType="transform"):
                vals.append((p, cmds.getAttr(p, time=frame)))
    for p, _ in vals:
        cmds.cutKey(p, clear=True)
    for p, v in vals:
        try:
            cmds.setAttr(p, v)
        except Exception:
            pass


def _clean_dup(dup):
    """A duplicated (maybe skinned) mesh -> plain mesh at world level: no intermediate shapes, unlocked, visible."""
    for sh in cmds.listRelatives(dup, shapes=True, fullPath=True) or []:
        if cmds.getAttr(sh + ".intermediateObject"):
            cmds.delete(sh)
    for a in ("tx", "ty", "tz", "rx", "ry", "rz", "sx", "sy", "sz", "v"):
        try:
            cmds.setAttr(dup + "." + a, lock=False)
        except Exception:
            pass
    for src in cmds.listConnections(dup + ".visibility", s=True, d=False, plugs=True) or []:
        cmds.disconnectAttr(src, dup + ".visibility")
    cmds.setAttr(dup + ".visibility", 1)
    cmds.setAttr(dup + ".overrideEnabled", 0)
    if cmds.listRelatives(dup, parent=True):
        dup = cmds.parent(dup, world=True)[0]
    return dup


def in_setup():
    return cmds.objExists(SETUP)


def _check_setup():
    if not in_setup():
        raise RuntimeError(u"目前場景不是加槍的調整場景（先按「開始調整」）")


def _setup_attr(name):
    return cmds.getAttr(SETUP + "." + name)


def setup_start(rig, ref_fbx=None, frame=None, init=None, cb=None):
    """Open a temp copy of the CLEAN `rig`, posed on `frame` of the firing motion, with an editable gun in the right
    hand. init (from setup_from_gun_rig): {gun_to_wrist, grip_local, hand, zl, model} to start from an existing gun."""
    rig = os.path.abspath(rig)
    if not os.path.isfile(rig):
        raise RuntimeError(u"找不到 rig：%s" % rig)
    ref_fbx = _ref(ref_fbx)
    tmpdir = tempfile.mkdtemp(prefix="asGunSetup_")
    _log(cb, u"套開槍姿勢（%s）…" % os.path.basename(ref_fbx))
    r = _core().retarget_motion(rig, ref_fbx, os.path.join(tmpdir, "pose.mb"), reduce=False, euler=False)
    frame = r["start"] if frame is None else min(max(frame, r["start"]), r["end"])
    cmds.file(os.path.join(tmpdir, "pose.mb"), open=True, force=True, prompt=False)
    if cmds.objExists("GunRig"):
        raise RuntimeError(u"這個 rig 已經有槍（GunRig）了，請選乾淨的 rig；要改既有的槍請用「重新調整」")
    cmds.currentTime(frame)
    data = _measure(ref_fbx, frame, cb)
    _freeze_pose(frame)
    if init:
        data.update({k: init[k] for k in ("gun_to_wrist", "grip_local", "hand", "zl") if k in init})
    hand, zl = data["hand"], data["zl"]

    grp = cmds.createNode("transform", name=SETUP)
    for name, val in (("cleanRig", rig.replace("\\", "/")), ("refFbx", ref_fbx.replace("\\", "/")),
                      ("gripLocal", json.dumps(data["grip_local"]))):
        cmds.addAttr(grp, longName=name, dataType="string")
        cmds.setAttr(grp + "." + name, val, type="string")
    for name, val in (("refFrame", frame), ("handSize", hand), ("gunHalf", zl)):
        cmds.addAttr(grp, longName=name, attributeType="double", defaultValue=val)
    space = cmds.group(empty=True, name="GunSetup_Space", parent=grp)
    cmds.xform(space, ws=True, m=list(om.MMatrix(data["gun_to_wrist"]) * _wmat("Wrist_R")))
    cmds.parentConstraint("Wrist_R", space, maintainOffset=True, name="GunSetup_Space_follow")
    ctrl = cmds.circle(name="GunSetup_Ctrl", normal=(0, 0, 1), radius=hand * 1.6, ch=False)[0]
    cmds.setAttr(ctrl + "Shape.overrideEnabled", 1)
    cmds.setAttr(ctrl + "Shape.overrideColor", 17)
    cmds.parent(ctrl, space, relative=True)
    geo = _import_model(init["model"], zl, False) if init and init.get("model") else _placeholder(hand, zl)
    cmds.parent(geo, ctrl, relative=True)
    gap = setup_snap_left_hand()
    if gap > 0.5:
        _log(cb, u"⚠ 左手差 %.1f cm 搆不到預設握點（手比較短），請把槍往身體拉近或調整姿勢，再按「左手貼到握點」" % gap)
    scene = os.path.join(tmpdir, "%s_GunSetup.mb" % os.path.splitext(os.path.basename(rig))[0])
    cmds.file(rename=scene)
    cmds.file(save=True, type="mayaBinary", force=True)
    cmds.select(ctrl)
    _log(cb, u"可以開始調整了：移動／旋轉 GunSetup_Ctrl 擺槍，Gun_Geo 可以直接改點線面，左手用 IKArm_L 擺。")
    return {"scene": scene, "frame": frame, "hand": hand, "zl": zl}


def _geo():
    kids = cmds.listRelatives("GunSetup_Ctrl", children=True, type="transform", fullPath=True) or []
    meshes = [k for k in kids if cmds.listRelatives(k, allDescendents=True, type="mesh")]
    if not meshes:
        raise RuntimeError(u"GunSetup_Ctrl 底下找不到槍模型")
    return meshes[0]


def setup_select(what):
    _check_setup()
    cmds.select({"ctrl": "GunSetup_Ctrl", "geo": _geo(), "hand": "IKArm_L"}[what])


def setup_reset_gun():
    _check_setup()
    for a, v in (("t", 0), ("r", 0), ("s", 1)):
        for ax in "xyz":
            cmds.setAttr("GunSetup_Ctrl.%s%s" % (a, ax), v)


def setup_snap_left_hand():
    """Left arm to IK, left hand onto the gun's grip point (the default one, moved along with the gun)."""
    _check_setup()
    target = om.MMatrix(json.loads(_setup_attr("gripLocal"))) * _no_scale(_wmat("GunSetup_Ctrl"))
    if cmds.objExists("FKIKArm_L") and cmds.attributeQuery("FKIKBlend", node="FKIKArm_L", exists=True):
        cmds.setAttr("FKIKArm_L.FKIKBlend", 10)
    offset = _wmat("IKArm_L") * _wmat("Wrist_L").inverse()
    m = om.MTransformationMatrix(offset * target)
    eul = m.rotation()
    eul.reorderIt(cmds.getAttr("IKArm_L.rotateOrder"))
    cmds.xform("IKArm_L", ws=True, t=list(m.translation(om.MSpace.kWorld)))
    cmds.xform("IKArm_L", ws=True, ro=[eul.x * 57.29577951308232, eul.y * 57.29577951308232, eul.z * 57.29577951308232])
    gap = (_ws("Wrist_L") - om.MTransformationMatrix(target).translation(om.MSpace.kWorld)).length()
    return gap        # > 0.5 cm: the arm can't reach (short / chibi arms) -> bring the gun closer or change the pose


def setup_replace_model(path, autoscale=True):
    """Swap the gun mesh for your own model (placed at the gun's grip, then move it where you like)."""
    _check_setup()
    old = _geo()
    new = _import_model(path, _setup_attr("gunHalf"), autoscale)
    cmds.delete(old)
    new = cmds.parent(new, "GunSetup_Ctrl", relative=True)[0]
    new = cmds.rename(new, "Gun_Geo")
    cmds.select(new)
    return new


def setup_finish(out, cb=None):
    """Record the adjusted gun, open the clean rig and build GunRig there, save as `out`."""
    _check_setup()
    rig = _setup_attr("cleanRig")
    if not os.path.isfile(rig):
        raise RuntimeError(u"找不到原本的乾淨 rig：%s" % rig)
    if os.path.normcase(os.path.abspath(out)) == os.path.normcase(os.path.abspath(rig)):
        raise RuntimeError(u"輸出不能是原本的 rig 檔")
    cmds.file(save=True, force=True)                     # keep the setup scene (temp) in case something fails
    G = _no_scale(_wmat("GunSetup_Ctrl"))
    ref = {"gun_to_wrist": list(G * _wmat("Wrist_R").inverse()),
           "grip_local": list(_wmat("Wrist_L") * G.inverse()),
           "hand": _setup_attr("handSize"), "zl": _setup_attr("gunHalf")}
    geo = _geo()
    geo_m = _wmat(geo)
    dup = _clean_dup(cmds.duplicate(geo, name="Gun_Geo_export")[0])
    cmds.xform(dup, ws=True, m=list(geo_m * G.inverse()))           # gun space = grip at origin
    cmds.makeIdentity(dup, apply=True, t=True, r=True, s=True, n=False)
    cmds.delete(dup, constructionHistory=True)
    model = os.path.join(os.path.dirname(cmds.file(q=True, sceneName=True)), "gun_model.mb")
    cmds.select(dup)
    cmds.file(model, exportSelected=True, type="mayaBinary", force=True, preserveReferences=False,
              constructionHistory=False, shader=True, channels=False, expressions=False, constraints=False)
    _log(cb, u"已記下槍的位置、模型和左手握點，打開乾淨的 rig：%s" % os.path.basename(rig))
    cmds.file(rig, open=True, force=True, prompt=False)
    return _build_gun_rig(rig, out, ref, model, False, cb)


def setup_from_gun_rig(gun_rig, clean_rig=None, ref_fbx=None, frame=None, cb=None):
    """「重新調整」: take the gun of an existing gun rig back into a setup scene built on the clean rig."""
    cmds.file(gun_rig, open=True, force=True, prompt=False)
    if not cmds.objExists("GunRig") or not cmds.objExists("Gun_Ctrl"):
        raise RuntimeError(u"這個檔案沒有用本工具加的槍（找不到 GunRig / Gun_Ctrl）")
    for a in ("tx", "ty", "tz", "rx", "ry", "rz"):          # the gun at its bind placement
        try:
            cmds.setAttr("Gun_Ctrl." + a, 0)
        except Exception:
            pass
    if cmds.attributeQuery("gunToWrist", node="GunRig", exists=True):
        g2w = json.loads(cmds.getAttr("GunRig.gunToWrist"))
        grip = json.loads(cmds.getAttr("GunRig.gripLocal"))
        hand, zl = cmds.getAttr("GunRig.handSize"), cmds.getAttr("GunRig.gunHalf")
        clean_rig = clean_rig or cmds.getAttr("GunRig.cleanRig")
    else:                                                     # rigs built before v1.8: measure them
        g2w = list(_no_scale(_wmat("Gun_Space")) * _wmat("Wrist_R").inverse())
        grip = cmds.xform("LeftGrip_Loc", q=True, os=True, m=True)
        bb = cmds.exactWorldBoundingBox("Gun_CtrlShape")
        hand = max(bb[3] - bb[0], bb[4] - bb[1], bb[5] - bb[2]) / 3.2
        zl = None
        clean_rig = clean_rig or guess_clean_rig(gun_rig)
    G = _no_scale(_wmat("Gun_Space"))
    geo = "Gun_Geo" if cmds.objExists("Gun_Geo") else None
    if not geo:
        raise RuntimeError(u"找不到 Gun_Geo")
    geo_m = _wmat(geo)
    dup = _clean_dup(cmds.duplicate(geo, name="Gun_Geo_export")[0])
    cmds.xform(dup, ws=True, m=list(geo_m * G.inverse()))
    cmds.makeIdentity(dup, apply=True, t=True, r=True, s=True, n=False)
    cmds.delete(dup, constructionHistory=True)
    if zl is None:
        bb = cmds.exactWorldBoundingBox(dup)
        zl = (bb[5] - bb[2]) / 2.9
    model = os.path.join(tempfile.mkdtemp(prefix="asGunRe_"), "gun_model.mb")
    cmds.select(dup)
    cmds.file(model, exportSelected=True, type="mayaBinary", force=True, preserveReferences=False,
              constructionHistory=False, shader=True, channels=False, expressions=False, constraints=False)
    if not clean_rig:
        raise RuntimeError(u"不知道這個帶槍 rig 的乾淨版本在哪，請指定乾淨的 rig")
    return setup_start(clean_rig, ref_fbx, frame,
                       init={"gun_to_wrist": g2w, "grip_local": grip, "hand": hand, "zl": zl, "model": model}, cb=cb)


def guess_clean_rig(gun_rig):
    """CharA_Rig_Gun.mb -> CharA_Rig.mb (same folder), if it exists."""
    stem, ext = os.path.splitext(gun_rig)
    for cand in (re.sub(r"(?i)_gun(_\w+)?$", "", stem) + ext, re.sub(r"(?i)_gun", "", stem) + ext):
        if cand != gun_rig and os.path.isfile(cand):
            return cand
    return None
