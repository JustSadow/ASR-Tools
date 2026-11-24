# -*- coding: utf-8 -*-
"""asMixamoTool core (independent from AdvancedSkeleton - it never edits AS files, it only works on the scene).

convert_rig_fbx()  : AS-exported FBX -> Mixamo-ready FBX
                     (Mixamo joint names, missing fingers added without weights, one UV set, no animation)
retarget_motion()  : AS rig .mb + Mixamo motion FBX -> <Char>_<motion>.mb
                     (same steps as MoCapMatcher: zero-out at -1, connect, bake, disconnect, then
                      bind pose key at -1, key reduce, mocap skeleton deleted)
"""
import math
import os
import re
import maya.cmds as cmds
import maya.mel as mel

# ----------------------------------------------------------------------------------------------- names
CENTER = {"Root": "Hips", "Spine1": "Spine", "Chest": "Spine2", "Neck": "Neck", "Head": "Head", "HeadEnd": "HeadTop_End"}
SIDED = {"Scapula": "Shoulder", "Shoulder": "Arm", "Elbow": "ForeArm", "Wrist": "Hand",
         "Hip": "UpLeg", "Knee": "Leg", "Ankle": "Foot", "Toes": "ToeBase", "ToesEnd": "Toe_End"}
FINGERS = ("Thumb", "Index", "Middle", "Ring", "Pinky")
for _fg in FINGERS:
    for _n in range(1, 5):
        SIDED["%sFinger%d" % (_fg, _n)] = "Hand%s%d" % (_fg, _n)
SIDE = {"L": "Left", "R": "Right"}


def mixamo_name(as_name):
    """AS deform joint name (Shoulder_L) -> Mixamo name (LeftArm), or None when it has no Mixamo counterpart."""
    m = re.match(r"^(.+)_([MLR])$", as_name)
    if not m:
        return None
    base, side = m.groups()
    if side == "M":
        return CENTER.get(base)
    return SIDE[side] + SIDED[base] if base in SIDED else None


def short(n):
    return n.split("|")[-1].split(":")[-1]


def log(cb, msg):
    if cb:
        cb(msg)
    else:
        print(msg)


def load_fbx():
    if not cmds.pluginInfo("fbxmaya", q=True, loaded=True):
        cmds.loadPlugin("fbxmaya", quiet=True)


# ======================================================================================= 1. rig FBX -> Mixamo FBX
def _skin_snapshot():
    weights = {}
    for sc in cmds.ls(type="skinCluster"):
        geo = cmds.skinCluster(sc, q=True, geometry=True)[0]
        mesh = short(cmds.listRelatives(geo, parent=True)[0] if cmds.nodeType(geo) == "mesh" else geo)
        infs = [short(i) for i in cmds.skinCluster(sc, q=True, influence=True)]
        rows = []
        for v in range(cmds.polyEvaluate(geo, vertex=True)):
            vals = cmds.skinPercent(sc, "%s.vtx[%d]" % (geo, v), q=True, value=True)
            rows.append({infs[k]: w for k, w in enumerate(vals) if w > 1e-6})
        weights[mesh] = rows
    return weights


def _bake_rotation_to_orient(j):
    wm = cmds.xform(j, q=True, ws=True, m=True)
    cmds.setAttr(j + ".rotate", 0, 0, 0)
    cmds.setAttr(j + ".jointOrient", 0, 0, 0)
    cmds.xform(j, ws=True, m=wm)
    r = cmds.getAttr(j + ".rotate")[0]
    cmds.setAttr(j + ".rotate", 0, 0, 0)
    cmds.setAttr(j + ".jointOrient", *r)


def _chain(side, fg):
    return [side + "Hand%s%d" % (fg, n) for n in range(1, 5) if cmds.objExists(side + "Hand%s%d" % (fg, n))]


def add_missing_fingers(cb=None):
    """Mixamo only maps a hand with all five fingers. Missing fingers get a joint chain (no weights) placed between /
    next to the neighbouring fingers, under the same parent as those fingers."""
    added = []
    for side in ("Left", "Right"):
        if not cmds.objExists(side + "Hand"):
            continue
        have = {fg: _chain(side, fg) for fg in FINGERS}
        if all(have.values()):
            continue
        order = ["Index", "Middle", "Ring", "Pinky"]
        for fg in FINGERS:
            if have[fg]:
                continue
            pos_list = []
            ref = None
            if fg == "Thumb":
                donors = [f for f in order if have[f]]
                if len(donors) >= 2:
                    a, b = have[donors[0]], have[donors[1]]
                    n = min(len(a), len(b))
                    pos_list = [[2 * x - y for x, y in zip(cmds.xform(a[i], q=True, ws=True, t=True),
                                                             cmds.xform(b[i], q=True, ws=True, t=True))] for i in range(n)]
                    ref = a
            else:
                i = order.index(fg)
                lo = next((have[order[k]] for k in range(i - 1, -1, -1) if have[order[k]]), None)
                hi = next((have[order[k]] for k in range(i + 1, 4) if have[order[k]]), None)
                if lo and hi:
                    n = min(len(lo), len(hi))
                    pos_list = [[(x + y) / 2 for x, y in zip(cmds.xform(lo[k], q=True, ws=True, t=True),
                                                             cmds.xform(hi[k], q=True, ws=True, t=True))] for k in range(n)]
                    # same parent as the pinky-side neighbour (on AS rigs that is the Cup joint, as in the mapped rigs)
                    ref = hi if any("Cup" in (cmds.listRelatives(x[0], parent=True) or [""])[0] for x in (hi,)) else lo
                else:
                    near = lo or hi
                    far_names = [order[k] for k in (range(i - 2, -1, -1) if lo else range(i + 2, 4)) if have[order[k]]]
                    if near and far_names:
                        far = have[far_names[0]]
                        n = min(len(near), len(far))
                        pos_list = [[2 * x - y for x, y in zip(cmds.xform(near[k], q=True, ws=True, t=True),
                                                                 cmds.xform(far[k], q=True, ws=True, t=True))] for k in range(n)]
                        ref = near
            if not pos_list:  # nothing to copy from: short chain straight out of the hand
                h = cmds.xform(side + "Hand", q=True, ws=True, t=True)
                fa = cmds.xform(side + "ForeArm", q=True, ws=True, t=True) if cmds.objExists(side + "ForeArm") else [0, 0, 0]
                d = [(a - b) * 0.12 for a, b in zip(h, fa)]
                pos_list = [[h[k] + d[k] * (s + 1) for k in range(3)] for s in range(4)]
                ref = None
            parent = cmds.listRelatives(ref[0], parent=True)[0] if ref else side + "Hand"
            prev = parent
            names = []
            for k, p in enumerate(pos_list):
                j = cmds.createNode("joint", name=side + "Hand%s%d" % (fg, k + 1), parent=prev)
                cmds.xform(j, ws=True, t=p)
                if ref:
                    cmds.xform(j, ws=True, ro=cmds.xform(ref[min(k, len(ref) - 1)], q=True, ws=True, ro=True))
                    cmds.setAttr(j + ".radius", cmds.getAttr(ref[0] + ".radius"))
                names.append(j)
                prev = j
            for j in names:
                _bake_rotation_to_orient(j)
            have[fg] = names
            added.append("%s%s x%d (under %s)" % (side, fg, len(names), short(parent)))
    for a in added:
        log(cb, u"  補上手指（無權重）: " + a)
    return added


def single_uv_set():
    changed = []
    for m in cmds.ls(type="mesh", noIntermediate=True):
        sets = cmds.polyUVSet(m, q=True, allUVSets=True) or []
        if len(sets) < 2:
            continue
        cnt = {s: cmds.polyEvaluate(m, uvcoord=True, uvSetName=s) for s in sets}
        keep = (cmds.polyUVSet(m, q=True, currentUVSet=True) or [sets[0]])[0]
        if not cnt.get(keep):
            keep = max(cnt, key=cnt.get)
        if keep != sets[0]:
            cmds.polyCopyUV(m, uvSetNameInput=keep, uvSetName=sets[0], ch=False)
        cmds.polyUVSet(m, currentUVSet=True, uvSet=sets[0])
        for s in sets[1:]:
            cmds.polyUVSet(m, delete=True, uvSet=s)
        changed.append("%s (%s)" % (short(m), ", ".join(sets[1:])))
    return changed


def export_fbx(path, skins=True):
    load_fbx()
    mel.eval("FBXResetExport")
    mel.eval("FBXExportSkins -v %s" % ("true" if skins else "false"))
    mel.eval("FBXExportShapes -v true")
    mel.eval("FBXExportAnimationOnly -v false")
    mel.eval("FBXExportBakeComplexAnimation -v false")
    mel.eval("FBXExportInputConnections -v false")
    mel.eval("FBXExportInAscii -v false")
    mel.eval('FBXExport -f "%s"' % path.replace("\\", "/"))


def convert_rig_fbx(src, dst, fix_fingers=True, cb=None):
    """Returns dict(ok, renamed, added, uv, anim, problems)."""
    load_fbx()
    cmds.file(new=True, force=True)
    cmds.file(src, i=True, type="FBX", ignoreVersion=True, mergeNamespacesOnClash=False, options="fbx")
    w0 = _skin_snapshot()
    pos0 = {short(j): cmds.xform(j, q=True, ws=True, t=True) for j in cmds.ls(type="joint", long=True)}

    mapping = {}
    for uid in cmds.ls(type="joint", uuid=True):
        node = cmds.ls(uid, long=True)[0]
        nn = mixamo_name(short(node))
        if nn:
            mapping[short(node)] = nn
            cmds.rename(node, nn)
    log(cb, u"  改名 %d 根骨頭" % len(mapping))

    added = add_missing_fingers(cb) if fix_fingers else []
    uv = single_uv_set()
    for u in uv:
        log(cb, u"  刪掉多的 UV set: " + u)
    anim = cmds.ls(type="animCurve")
    anim = [a for a in anim if not cmds.nodeType(a).startswith("animCurveU")]  # keep driven keys
    if anim:
        cmds.delete(anim)
        log(cb, u"  刪掉動畫曲線 %d 條（不帶 Take）" % len(anim))

    if os.path.normcase(os.path.abspath(dst)) == os.path.normcase(os.path.abspath(src)):
        raise RuntimeError("output equals input")
    export_fbx(dst)
    log(cb, u"  已輸出 " + dst)

    # ---- verify
    cmds.file(new=True, force=True)
    cmds.file(dst, i=True, type="FBX", ignoreVersion=True, options="fbx")
    problems = []
    inv = {v: k for k, v in mapping.items()}
    joints = {short(j): cmds.xform(j, q=True, ws=True, t=True) for j in cmds.ls(type="joint", long=True)}
    new_names = set()
    for n, p in joints.items():
        o = inv.get(n, n)
        if o in pos0:
            if max(abs(a - b) for a, b in zip(pos0[o], p)) > 1e-3:
                problems.append(u"骨頭位置變了: " + n)
        else:
            new_names.add(n)
    lost = sorted(set(pos0) - {inv.get(n, n) for n in joints})
    if lost:
        problems.append(u"少了骨頭: %s" % lost)
    w1 = _skin_snapshot()
    for mesh, rows in w1.items():
        ref = w0.get(mesh)
        if ref is None or len(ref) != len(rows):
            problems.append(u"網格對不上: " + mesh)
            continue
        worst = 0.0
        for a, b in zip(ref, rows):
            b2 = {inv.get(k, k): v for k, v in b.items()}
            for k in set(a) | set(b2):
                worst = max(worst, abs(a.get(k, 0) - b2.get(k, 0)))
        if worst > 1e-4:
            problems.append(u"%s 權重差 %.5f" % (mesh, worst))
    need = ["Hips", "Spine", "Spine2", "Neck", "Head"] + [s + b for s in ("Left", "Right") for b in
            ("Shoulder", "Arm", "ForeArm", "Hand", "UpLeg", "Leg", "Foot", "ToeBase")] + \
           [s + "Hand%s1" % f for s in ("Left", "Right") for f in FINGERS]
    miss = [n for n in need if n not in joints]
    if miss:
        problems.append(u"Mixamo 需要的骨頭還缺: %s" % miss)
    if "LeftArm" in joints and joints["LeftArm"][0] <= 0:
        problems.append(u"左手不在 +X（Mixamo 可能左右顛倒）")
    multi_uv = [m for m in cmds.ls(type="mesh", noIntermediate=True) if len(cmds.polyUVSet(m, q=True, allUVSets=True) or []) > 1]
    if multi_uv:
        problems.append(u"還有多組 UV: %s" % multi_uv)
    log(cb, u"  檢查: %d 根骨頭（新增 %d），%d 個網格權重一致" % (len(joints), len(new_names), len(w1)))
    cmds.file(new=True, force=True)
    return {"ok": not problems, "renamed": len(mapping), "added": added, "uv": uv, "anim": len(anim), "problems": problems}


# ======================================================================================= 2. retarget one motion
def _find_mocap(ns, name):
    if not name:
        return None
    hits =cmds.ls("%s:%s" % (ns, name), long=True) or cmds.ls("%s:*:%s" % (ns, name), long=True)
    if not hits and "FBXASC032" in name:   # spaces in FBX names: Maya writes FBXASC032 or '_' depending on settings
        alt = name.replace("FBXASC032", "_")
        hits = cmds.ls("%s:%s" % (ns, alt), long=True) or cmds.ls("%s:*:%s" % (ns, alt), long=True)
    hits = [h for h in hits if cmds.nodeType(h) == "joint"] or hits
    return hits[0] if hits else None


def _disable(con, holder="MoCapConstraints"):
    cmds.connectAttr(holder + ".disableConstraints", con + ".nodeState", force=True)



def is_standard_skeleton(ns):
    """Mixamo's own characters (Y Bot / X Bot...) have Spine > Spine1 > Spine2; our uploaded AS skeletons have no 'Spine1'."""
    return _find_mocap(ns, "Spine1") is not None


class Source(object):
    """How an AS deform joint (Shoulder_L) is called in a motion skeleton.
    foreign=True: a skeleton with other proportions/rest pose (anything but our own upload) -> align + scale."""

    def __init__(self, key, label, foreign, mapping=None, side=None):
        self.key, self.label, self.foreign = key, label, foreign
        self.mapping, self.side = mapping, side
        self.override = {}     # {AS joint: exact source joint name} found while importing (e.g. a deeper pelvis)

    def name(self, as_joint):
        if as_joint in self.override:
            return self.override[as_joint]
        if self.key == "custom":
            return mixamo_name(as_joint)
        if self.key == "mixamo":
            return "Spine1" if as_joint == "Spine1_M" else mixamo_name(as_joint)
        m = re.match(r"^(.+)_([MLR])$", as_joint)
        if not m or m.group(1) not in self.mapping:
            return None
        base, side = m.group(1), m.group(2)
        other = self.mapping[base]
        sd = self.side
        us = "_" if sd["underscore"] else ""
        s = {"L": sd["left"], "R": sd["right"], "M": sd["middle"]}[side]
        if side == "M" and s == "":
            return other
        return (s + us + other) if sd["before"] else (other + us + s)


# 3ds Max Biped (Bip001 ...), used by many Asset Store / Unity motion packs.
# Maya imports the spaces in "Bip001 L Thigh" as FBXASC032 (or '_', handled in _find_mocap).
_SP = "FBXASC032"
_BIPED_MAP = {"Root": "Bip001" + _SP + "Pelvis", "Spine1": "Bip001" + _SP + "Spine", "Chest": "Bip001" + _SP + "Spine2",
              "Neck": "Bip001" + _SP + "Neck", "Head": "Bip001" + _SP + "Head",
              "Scapula": "Clavicle", "Shoulder": "UpperArm", "Elbow": "Forearm", "Wrist": "Hand",
              "Hip": "Thigh", "Knee": "Calf", "Ankle": "Foot", "Toes": "Toe0"}
for _i, _f in enumerate(("Thumb", "Index", "Middle", "Ring", "Pinky")):
    _BIPED_MAP.update({"%sFinger1" % _f: "Finger%d" % _i, "%sFinger2" % _f: "Finger%d1" % _i, "%sFinger3" % _f: "Finger%d2" % _i})
_BIPED_SIDE = {"right": "Bip001" + _SP + "R" + _SP, "left": "Bip001" + _SP + "L" + _SP, "middle": "",
               "before": True, "underscore": False}

# Unreal Engine mannequin names (pelvis, spine_01, upperarm_l ...): also what many 3ds Max / Unity motion packs use
_UNREAL_MAP = {"Root": "pelvis", "Spine1": "spine_01", "Chest": "spine_03", "Neck": "neck_01", "Head": "head",
               "Scapula": "clavicle", "Shoulder": "upperarm", "Elbow": "lowerarm", "Wrist": "hand",
               "Hip": "thigh", "Knee": "calf", "Ankle": "foot", "Toes": "ball"}
for _f in ("Thumb", "Index", "Middle", "Ring", "Pinky"):
    _UNREAL_MAP.update({"%sFinger%d" % (_f, _n): "%s_0%d" % (_f.lower(), _n) for _n in (1, 2, 3)})
_UNREAL_SIDE = {"right": "r", "left": "l", "middle": "", "before": False, "underscore": True}

# AdvancedSkeleton deform joints (Root_M, Hip_L ...): motion exported from another AS rig, e.g. with the 匯出 FBX tab
_AS_MAP = {b: b for b in ("Root", "Spine1", "Chest", "Neck", "Head", "HeadEnd", "Scapula", "Shoulder", "Elbow", "Wrist",
                          "Hip", "Knee", "Ankle", "Toes", "ToesEnd")}
for _f in ("Thumb", "Index", "Middle", "Ring", "Pinky"):
    _AS_MAP.update({"%sFinger%d" % (_f, _n): "%sFinger%d" % (_f, _n) for _n in (1, 2, 3, 4)})
_AS_SIDE = {"right": "R", "left": "L", "middle": "M", "before": False, "underscore": True}

try:
    from . import asMixamoSources as _tables
except ImportError:           # imported as a top-level module (background worker)
    import asMixamoSources as _tables


def list_sources():
    """[Source...]: Mixamo default character, our own upload, 3ds Max Biped, Unreal, then the other motion libraries.
    Every name table is built into the tool: nothing is read from AdvancedSkeleton."""
    out = [Source("mixamo", u"Mixamo 預設角色（Y Bot／X Bot）", True),
           Source("custom", u"客製模型（自己上傳 Mixamo 的版本）", False),
           Source("Biped", u"3ds Max Biped（Bip001，Asset Store 動作包常見）", True, _BIPED_MAP, _BIPED_SIDE),
           Source("Unreal", u"Unreal（pelvis／spine_01／upperarm_l，UE 與部分 Unity 動作包）", True, _UNREAL_MAP, _UNREAL_SIDE),
           Source("AdvancedSkeleton", u"AdvancedSkeleton 角色（Root_M／Hip_L，別隻 AS 角色匯出的 FBX）", True, _AS_MAP, _AS_SIDE)]
    for key, label, mapping, side in _tables.TABLES:
        out.append(Source(key, label, True, dict(mapping), dict(side)))
    return out


_DETECT = ["Root_M", "Spine1_M", "Chest_M", "Neck_M", "Head_M"] + \
          [b + "_" + s for s in "LR" for b in ("Shoulder", "Elbow", "Wrist", "Hip", "Knee", "Ankle")]


def detect_source(ns, sources=None):
    """Pick the source whose names match the imported skeleton best."""
    sources = sources or list_sources()
    best, score = None, -1
    for src in sources:
        n = sum(1 for j in _DETECT if src.name(j) and _find_mocap(ns, src.name(j)))
        if n > score:
            best, score = src, n
    by = {s.key: s for s in sources}
    if best and best.key in ("mixamo", "custom", "MotionBuilder"):  # same names apart from the spine
        best = by["mixamo"] if is_standard_skeleton(ns) else by["custom"]
    return best, score


def get_source(key):
    for s in list_sources():
        if s.key == key:
            return s
    raise RuntimeError(u"找不到來源：%s" % key)


def source_name(as_joint, src):
    if isinstance(src, Source):
        return src.name(as_joint)
    if src:  # legacy True = Mixamo default character
        return "Spine1" if as_joint == "Spine1_M" else mixamo_name(as_joint)
    return mixamo_name(as_joint)


# bone directions used to pose the source skeleton like the rig's bind pose (parent first)
_ALIGN = [("Root_M", "Spine1_M"), ("Spine1_M", "Chest_M"), ("Chest_M", "Neck_M"), ("Neck_M", "Head_M"), ("Head_M", "HeadEnd_M")]
for _s in ("L", "R"):
    _ALIGN += [("Scapula_" + _s, "Shoulder_" + _s), ("Shoulder_" + _s, "Elbow_" + _s), ("Elbow_" + _s, "Wrist_" + _s),
               ("Wrist_" + _s, "MiddleFinger1_" + _s),
               ("Hip_" + _s, "Knee_" + _s), ("Knee_" + _s, "Ankle_" + _s), ("Ankle_" + _s, "Toes_" + _s), ("Toes_" + _s, "ToesEnd_" + _s)]
    for _f in ("Thumb", "Index", "Middle", "Ring", "Pinky"):
        _ALIGN += [("%sFinger%d_%s" % (_f, _k, _s), "%sFinger%d_%s" % (_f, _k + 1, _s)) for _k in (1, 2, 3)]


def _ws(n):
    return cmds.xform(n, q=True, ws=True, t=True)


def _rotate_world(node, q):
    import maya.api.OpenMaya as om
    m = om.MMatrix(cmds.xform(node, q=True, ws=True, m=True))
    r = q.asMatrix()
    new = [m.getElement(i, j) for i in range(4) for j in range(4)]
    for i in range(3):
        for j in range(3):
            new[i * 4 + j] = sum(m.getElement(i, k) * r.getElement(k, j) for k in range(3))
    cmds.xform(node, ws=True, m=new)


# left-right line used to match the facing of the body joints (rig names; looked up in the source like the others)
_ALIGN_LATERAL = {"Root_M": ("Hip_R", "Hip_L"), "Spine1_M": ("Scapula_R", "Scapula_L"), "Chest_M": ("Scapula_R", "Scapula_L"),
                  "Neck_M": ("Scapula_R", "Scapula_L"), "Head_M": ("Scapula_R", "Scapula_L")}


def _frame(primary, lateral):
    """Orthonormal frame (rows: primary, lateral, normal) or None when the two vectors are (nearly) parallel."""
    import maya.api.OpenMaya as om
    p = primary.normal()
    l = lateral - p * (lateral * p)
    if l.length() < 1e-4 * max(lateral.length(), 1e-9):
        return None
    l = l.normal()
    n = p ^ l
    return om.MMatrix([p.x, p.y, p.z, 0, l.x, l.y, l.z, 0, n.x, n.y, n.z, 0, 0, 0, 0, 1])


def align_rest_pose(ns, standard, ref=None, foot_pitch=None):
    """Rotate the source joints (at frame -1) so every bone points the same way as in the rig's bind pose
    (Mixamo's own characters are in T-pose, a rig may be in A-pose). Twist differences are kept by -mo."""
    import maya.api.OpenMaya as om
    n = 0
    for a, b in _ALIGN:
        if not (cmds.objExists(a) and cmds.objExists(b)):
            continue
        sa, sb = _find_mocap(ns, source_name(a, standard)), _find_mocap(ns, source_name(b, standard))
        if not (sa and sb):
            continue
        ra, rb, pa, pb = _ws(a), _ws(b), _ws(sa), _ws(sb)
        v_rig = om.MVector(*[y - x for x, y in zip(ra, rb)])
        v_src = om.MVector(*[y - x for x, y in zip(pa, pb)])
        if v_rig.length() < 1e-6 or v_src.length() < 1e-6:
            continue
        # foot: the source's foot is flat on the ground at its own slope (ankle high above the ball: ~30 degrees
        # for a human) while the rig's flat foot has another slope (a chibi foot ~5 degrees). Matching the two
        # directions would tip the rig's toes down whenever the source stands flat -> give the source foot the
        # slope it has when planted in the clip, on the rig foot's heading, so planted == the rig's flat bind foot.
        side = a[-1]
        if foot_pitch and a.startswith("Ankle_") and foot_pitch.get(side) is not None:
            hz = om.MVector(v_rig.x, 0, v_rig.z)
            if hz.length() > 1e-6:
                pr = math.radians(foot_pitch[side])
                v_rig = hz.normal() * math.cos(pr) + om.MVector(0, -1, 0) * math.sin(pr)
        q = om.MQuaternion(v_src.normal(), v_rig.normal())
        # body joints: also match the facing (twist around the bone) with a left-right line, otherwise a skeleton
        # whose zero pose lies on its side (3ds Max exports) ends up with the hips turned e.g. 90 degrees
        lat = _ALIGN_LATERAL.get(a)
        if lat:
            lr = [cmds.objExists(x) and x for x in lat]
            ls = [_find_mocap(ns, source_name(x, standard)) for x in lat]
            if all(lr) and all(ls):
                f_rig = _frame(v_rig, om.MVector(*_ws(lat[1])) - om.MVector(*_ws(lat[0])))
                f_src = _frame(v_src, om.MVector(*_ws(ls[1])) - om.MVector(*_ws(ls[0])))
                if f_rig is not None and f_src is not None:
                    q = om.MTransformationMatrix(f_src.transpose() * f_rig).rotation(asQuaternion=True)
        try:
            _rotate_world(sa, q)
            n += 1
        except Exception:
            continue
        # twist around the bone: the zero pose of some skeletons has a bone rolled e.g. 180 degrees compared with how
        # the clip holds it (3ds Max clavicles) -> the rig bone would be twisted by that much for the whole clip.
        # If the clip's first frame (swung onto the same direction) is rolled more than 90 degrees from the aligned
        # zero pose, take the clip's roll instead. Small differences keep the zero pose (Mixamo T-pose unchanged).
        key = cmds.ls(sa, long=True)[0]
        child = _ref_child(ref, sb) if ref else None
        if ref and key in ref and child and not lat:
            d_ref = om.MVector(*[y - x for x, y in zip(ref[key + "|pos"], ref[child])])
            par = (cmds.listRelatives(sa, parent=True, fullPath=True) or [None])[0]
            if d_ref.length() > 1e-6 and par and par + "|par" in ref:
                # the clip's pose of this bone RELATIVE TO ITS PARENT, put on the parent as it is posed now
                to_now = _rot3(om.MMatrix(ref[par + "|par"])).inverse() * _rot3(om.MMatrix(cmds.xform(par, q=True, ws=True, m=True)))
                m_tmp = _rot3(om.MMatrix(ref[key])) * to_now
                d_tmp = d_ref * to_now
                m_now = _rot3(om.MMatrix(cmds.xform(sa, q=True, ws=True, m=True)))
                m_cand = m_tmp * om.MQuaternion(d_tmp.normal(), v_rig.normal()).asMatrix()
                w = om.MTransformationMatrix(m_now.inverse() * m_cand).rotation(asQuaternion=True)
                if abs(w.asAxisAngle()[1]) > math.pi / 2:      # world rotation from the aligned pose to the clip's roll
                    _rotate_world(sa, w)
                    _TWIST_FIXED.append(key.split(":")[-1])
    # feet: the whole planted foot (slope AND side roll) is the rig's flat bind foot. Take the source foot's
    # orientation on its planted frame, turned about world Y so it points where the rig's foot points; then a planted
    # source foot gives the rig's bind orientation (IKLeg rotate X/Z = 0) on any rig, whatever its feet point at.
    for side, (m_foot, m_toe) in ((foot_pitch or {}).get("toes") or {}).items():
        fa = _find_mocap(ns, source_name("Ankle_" + side, standard))
        if not (fa and cmds.objExists("Ankle_" + side) and cmds.objExists("Toes_" + side)):
            continue
        mf, mt = om.MMatrix(m_foot), om.MMatrix(m_toe)
        d_src = om.MVector(mt.getElement(3, 0) - mf.getElement(3, 0), 0, mt.getElement(3, 2) - mf.getElement(3, 2))
        r_a, r_t = _ws("Ankle_" + side), _ws("Toes_" + side)
        d_rig = om.MVector(r_t[0] - r_a[0], 0, r_t[2] - r_a[2])
        if d_src.length() < 1e-6 or d_rig.length() < 1e-6:
            continue
        want = _rot3(mf) * om.MQuaternion(d_src.normal(), d_rig.normal()).asMatrix()
        now = _rot3(om.MMatrix(cmds.xform(fa, q=True, ws=True, m=True)))
        _rotate_world(fa, om.MTransformationMatrix(now.inverse() * want).rotation(asQuaternion=True))
    # toes: put each source toe at the angle (relative to its foot) it has while the foot is planted, so planted
    # toes == the rig's flat bind toes (a skeleton without a toe-end joint cannot be aimed like the other bones)
    for side, (m_foot, m_toe) in ((foot_pitch or {}).get("toes") or {}).items():
        fa = _find_mocap(ns, source_name("Ankle_" + side, standard))
        fb = _find_mocap(ns, source_name("Toes_" + side, standard))
        if not (fa and fb):
            continue
        want = _rot3(om.MMatrix(m_toe)) * _rot3(om.MMatrix(m_foot)).inverse() * _rot3(om.MMatrix(cmds.xform(fa, q=True, ws=True, m=True)))
        now = _rot3(om.MMatrix(cmds.xform(fb, q=True, ws=True, m=True)))
        _rotate_world(fb, om.MTransformationMatrix(now.inverse() * want).rotation(asQuaternion=True))
    return n


_TWIST_FIXED = []


def _rot3(m):
    import maya.api.OpenMaya as om
    return om.MMatrix([m.getElement(0, 0), m.getElement(0, 1), m.getElement(0, 2), 0, m.getElement(1, 0), m.getElement(1, 1), m.getElement(1, 2), 0,
                       m.getElement(2, 0), m.getElement(2, 1), m.getElement(2, 2), 0, 0, 0, 0, 1])


def _ref_child(ref, child):
    c = cmds.ls(child, long=True)
    return (c[0] + "|pos") if c and (c[0] + "|pos") in ref else None


def flat_foot_pitch(ns, standard, start, end):
    """{side: slope in degrees of the source ankle->toes line while that foot is planted in the clip} (None when the
    foot never stands still on its lowest level, e.g. an airborne clip)."""
    out = {}
    for side in "LR":
        a = _find_mocap(ns, source_name("Ankle_" + side, standard))
        b = _find_mocap(ns, source_name("Toes_" + side, standard))
        h = _find_mocap(ns, source_name("Hip_" + side, standard))
        if not (a and b and h):
            out[side] = []
            continue
        rows = []
        for fr in range(int(start), int(end) + 1):
            cmds.currentTime(fr)
            rows.append((_ws(h), _ws(a), _ws(b)))
        leg = max(sum((x - y) ** 2 for x, y in zip(r[0], r[1])) ** 0.5 for r in rows) or 1.0
        min_a, min_b = min(r[1][1] for r in rows), min(r[2][1] for r in rows)
        pitches = []
        for i, (hp, ap, bp) in enumerate(rows):
            if bp[1] > min_b + 0.04 * leg or ap[1] > min_a + 0.10 * leg:
                continue
            if hp[1] - ap[1] < 0.6 * leg:          # standing on it: hip well above the ankle (not lying / rolling)
                continue
            prev = rows[max(0, i - 1)][2]
            if ((bp[0] - prev[0]) ** 2 + (bp[2] - prev[2]) ** 2) ** 0.5 > 0.02 * leg:   # sliding / stepping
                continue
            v = [y - x for x, y in zip(ap, bp)]
            pitches.append((math.degrees(math.atan2(-v[1], math.hypot(v[0], v[2]))), int(start) + i))
        out[side] = pitches
    # both feet share the skeleton's shape: pool them. While planted the heel may lift (the slope grows), so the
    # flat foot is the low end of the contact frames. A flat human foot slopes down from ankle to ball; anything
    # outside 5-55 degrees is not a planted foot (e.g. dangling feet at the low point of an airborne loop).
    pool = sorted(x[0] for v in out.values() for x in v)
    flat = pool[len(pool) // 4] if len(pool) >= 3 else None
    if flat is not None and not 5.0 <= flat <= 55.0:
        flat = None
    res = {"L": flat, "R": flat, "frames": {}}
    if flat is not None:
        # per side, the planted frame whose slope is closest to the flat one: used for the toes' flat pose
        for side in "LR":
            if out[side]:
                res["frames"][side] = min(out[side], key=lambda x: abs(x[0] - flat))[1]
    return res


def capture_ref_pose(ns, standard, frame):
    """World matrices / positions of the mapped source joints at `frame` (the clip's own pose), for align_rest_pose."""
    cmds.currentTime(frame)
    ref = {}
    for a, b in _ALIGN:
        for j in (a, b):
            sj = _find_mocap(ns, source_name(j, standard))
            if sj:
                k = cmds.ls(sj, long=True)[0]
                ref[k] = cmds.xform(sj, q=True, ws=True, m=True)
                ref[k + "|pos"] = cmds.xform(sj, q=True, ws=True, t=True)
                par = (cmds.listRelatives(sj, parent=True, fullPath=True) or [None])[0]
                if par:
                    ref[par + "|par"] = cmds.xform(par, q=True, ws=True, m=True)
    return ref


def _chain_len(nodes):
    p = [_ws(x) for x in nodes]
    return sum(sum((u - v) ** 2 for u, v in zip(p[i], p[i + 1])) ** 0.5 for i in range(len(p) - 1))


def body_scale(ns, standard):
    """rig leg length / source leg length (1.0 for our own uploaded skeletons)."""
    vals = []
    for s in ("L", "R"):
        rig = ["Hip_" + s, "Knee_" + s, "Ankle_" + s]
        src = [_find_mocap(ns, source_name(x, standard)) for x in rig]
        if all(cmds.objExists(x) for x in rig) and all(src):
            l_src = _chain_len(src)
            if l_src > 1e-6:
                vals.append(_chain_len(rig) / l_src)
    return sum(vals) / len(vals) if vals else 1.0


def _scaled_proxy(src, s, holder="MoCapConstraints"):
    """A transform that follows src's world position multiplied by s (so strides / jumps match the rig's size)."""
    base = "MoCapProxy_" + short(src).replace(":", "_")
    dm = cmds.createNode("decomposeMatrix", name=base + "_dm")
    md = cmds.createNode("multiplyDivide", name=base + "_md")
    px = cmds.createNode("transform", name=base, parent=holder)
    cmds.connectAttr(src + ".worldMatrix[0]", dm + ".inputMatrix")
    cmds.connectAttr(dm + ".outputTranslate", md + ".input1")
    for ax in "XYZ":
        cmds.setAttr(md + ".input2" + ax, s)
    cmds.connectAttr(md + ".output", px + ".translate")
    return px


def _hip_relative_proxy(src_hip, src_foot, rig_hip, k, holder="MoCapConstraints", tag=""):
    """A transform at  rigHip + k * (srcFoot - srcHip)  (world space). The rig hip is read from a reference
    under the hip's parent (Root_M), so it does not depend on the leg IK it drives (no cycle)."""
    par = cmds.listRelatives(rig_hip, parent=True, fullPath=True)[0]
    base = "MoCapProxy_HipRel%s_%s" % (tag, rig_hip)
    ref = cmds.createNode("transform", name="MoCapHipRef%s_%s" % (tag, rig_hip), parent=par)
    cmds.xform(ref, ws=True, t=_ws(rig_hip))
    dms = []
    for n, tag in ((ref, "ref"), (src_hip, "hip"), (src_foot, "foot")):
        dm = cmds.createNode("decomposeMatrix", name="%s_%s_dm" % (base, tag))
        cmds.connectAttr(n + ".worldMatrix[0]", dm + ".inputMatrix")
        dms.append(dm)
    sub = cmds.createNode("plusMinusAverage", name=base + "_sub")
    cmds.setAttr(sub + ".operation", 2)
    cmds.connectAttr(dms[2] + ".outputTranslate", sub + ".input3D[0]")
    cmds.connectAttr(dms[1] + ".outputTranslate", sub + ".input3D[1]")
    md = cmds.createNode("multiplyDivide", name=base + "_md")
    cmds.connectAttr(sub + ".output3D", md + ".input1")
    for ax in "XYZ":
        cmds.setAttr(md + ".input2" + ax, k)
    add = cmds.createNode("plusMinusAverage", name=base + "_add")
    cmds.connectAttr(dms[0] + ".outputTranslate", add + ".input3D[0]")
    cmds.connectAttr(md + ".output", add + ".input3D[1]")
    px = cmds.createNode("transform", name=base, parent=holder)
    cmds.connectAttr(add + ".output3D", px + ".translate")
    return px


def connect_mocap(ns, cb=None, standard=False, scale=1.0, parts=None):
    """Python port of AdvancedSkeleton 6.940 MoCapMatcher 'Connect MoCap Skeleton' (non-Extra), with this
    pipeline's own Mixamo names (Spine1_M <- Spine, which AS's Mixamo.txt maps to a 'Spine1' that our upload has not)."""
    if cmds.objExists("MoCapConstraints"):
        raise RuntimeError("MoCapConstraints already exists")
    holder = cmds.createNode("transform", name="MoCapConstraints")
    for a in ("t", "r", "s"):
        for ax in "xyz":
            cmds.setAttr("%s.%s%s" % (holder, a, ax), lock=True, keyable=False)
    cmds.addAttr(holder, longName="disableConstraints", attributeType="bool", keyable=True)

    deform = cmds.listRelatives("DeformationSystem", allDescendents=True, type="joint") or []
    dests, connected, missing = [], 0, []

    def con(kind, src, dst, mo=True, **kw):
        try:
            c = getattr(cmds, kind)(src, dst, maintainOffset=mo, **kw)[0]
            _disable(c)
            if dst not in dests:
                dests.append(dst)
            return True
        except Exception as e:
            log(cb, u"    略過 %s -> %s (%s)" % (short(src), dst, str(e).strip()))
            return False

    def pt(src):
        return src if abs(scale - 1.0) < 1e-4 else _scaled_proxy(src, scale)

    for dj in deform:
        if parts is not None and dj not in parts:
            continue
        mname = source_name(dj, standard)
        if not mname:
            continue
        target = _find_mocap(ns, mname)
        dest = "RootX_M" if dj == "Root_M" else "FK" + dj
        if not cmds.objExists(dest):
            continue
        if not target:
            missing.append(mname)
            continue
        side = dj[-2:]
        if dj == "Root_M":
            con("pointConstraint", pt(target), dest)
        base = dj[:-2]
        if con("orientConstraint", target, dest):
            connected += 1
        if base in ("Ankle", "Wrist"):
            ik = ("IKLeg" if base == "Ankle" else "IKArm") + side
            if cmds.objExists(ik):
                src_hip = _find_mocap(ns, source_name("Hip" + side, standard)) if base == "Ankle" else None
                if base == "Ankle" and getattr(standard, "foreign", False) and src_hip and cmds.objExists("Hip" + side):
                    # foreign proportions (e.g. chibi: wide hips, short legs): place the foot relative to the
                    # rig's OWN hip, using the source's hip->foot vector scaled by the leg ratio, so a pose the
                    # source can reach is always reachable for the rig
                    # no offset: the proxy already sits on the rig's ankle at rest; an offset taken there (legs
                    # with other thigh/shin ratios differ a few cm when the knee is not perfectly straight) would be
                    # added in world space all clip long and stop the leg from straightening, e.g. in a kick
                    con("pointConstraint", _hip_relative_proxy(src_hip, target, "Hip" + side, scale, holder), ik, mo=False)
                else:
                    con("pointConstraint", pt(target), ik)
                con("orientConstraint", target, ik)
        if base == "Toes" and cmds.objExists("IKToes" + side):
            con("orientConstraint", target, "IKToes" + side)
        if base in ("Knee", "Elbow"):
            pole = ("PoleLeg" if base == "Knee" else "PoleArm") + side
            if cmds.objExists(pole):
                par = cmds.listRelatives(target, parent=True, fullPath=True)
                kids = cmds.listRelatives(target, children=True, type="transform", fullPath=True)
                if par and kids:
                    hip, knee, ankle = par[0], target, kids[0]
                    a = cmds.createNode("transform", name="PoleVectorLocatorOffsetA" + dj + side, parent=holder)
                    b = cmds.createNode("transform", name="PoleVectorLocatorOffsetB" + dj + side, parent=a)
                    loc = cmds.createNode("transform", name="PoleVectorLocator" + dj + side, parent=b)
                    pa, pb, pc = [cmds.xform(x, q=True, ws=True, t=True) for x in (hip, knee, ankle)]
                    da = sum((x - y) ** 2 for x, y in zip(pa, pb)) ** 0.5
                    db = sum((x - y) ** 2 for x, y in zip(pb, pc)) ** 0.5
                    cmds.pointConstraint(hip, a, weight=db)
                    cmds.pointConstraint(ankle, a, weight=da)
                    cmds.orientConstraint("RootX_M", a)
                    cmds.setAttr(b + ".tz", (da + db) / (10.0 if base == "Elbow" else -10.0))
                    cmds.aimConstraint(knee, b, aimVector=(1, 0, 0), upVector=(0, 1, 0), worldUpType="vector", worldUpVector=(0, 1, 0))
                    cmds.setAttr(loc + ".tx", da + db)
                    src_hip = _find_mocap(ns, source_name("Hip" + side, standard)) if base == "Knee" else None
                    if base == "Knee" and getattr(standard, "foreign", False) and src_hip and cmds.objExists("Hip" + side):
                        # same space as the IK foot (relative to the rig's own hip), else wide hips turn the knee
                        # no offset: at the rest pose the leg is straight, so the knee direction (and any offset
                        # measured there) is undefined -> put the pole right on the knee's bend plane
                        con("pointConstraint", _hip_relative_proxy(src_hip, loc, "Hip" + side, scale, holder, tag="Pole"), pole, mo=False)
                    else:
                        con("pointConstraint", pt(loc), pole)
        if dj == "Chest_M" and cmds.objExists("IKSpine3_M"):
            for at in ("followRoot", "ikHybridVis"):
                if cmds.attributeQuery(at, node="IKSpine3_M", exists=True):
                    cmds.setAttr("IKSpine3_M." + at, 0)
            con("pointConstraint", pt(target), "IKSpine3_M")
            con("orientConstraint", target, "IKSpine3_M")
    return dests, connected, missing


def disconnect_mocap():
    if cmds.objExists("MoCapConstraints"):
        cons = cmds.listConnections("MoCapConstraints.disableConstraints", s=False, d=True) or []
        cmds.delete(list(set(cons)) + ["MoCapConstraints"])
    dg = cmds.ls("MoCapProxy_*", type=("decomposeMatrix", "multiplyDivide", "plusMinusAverage"))
    if dg:
        cmds.delete(dg)
    refs = cmds.ls("MoCapHipRef*", type="transform")
    if refs:
        cmds.delete(refs)


def _source_skin_bind(ns, top):
    """{joint long name: world matrix at skin bind} for the joints under `top` that a skinned mesh in the motion file
    uses (inverse bindPreMatrix), or None when the file has no skin (skeleton-only FBX)."""
    import maya.api.OpenMaya as om
    under = set(cmds.listRelatives(top, allDescendents=True, type="joint", fullPath=True) or [])
    under.add(cmds.ls(top, long=True)[0])
    out = {}
    for sc in cmds.ls(ns + ":*", type="skinCluster") + cmds.ls(ns + ":*:*", type="skinCluster"):
        for idx in cmds.getAttr(sc + ".matrix", multiIndices=True) or []:
            j = cmds.listConnections("%s.matrix[%d]" % (sc, idx), s=True, d=False)
            if j:
                j = cmds.ls(j[0], long=True)[0]
                if j in under:
                    out.setdefault(j, list(om.MMatrix(cmds.getAttr("%s.bindPreMatrix[%d]" % (sc, idx))).inverse()))
    return out if len(out) >= 10 else None


def _bind_foot_pitch(ns, standard, mats):
    """Like flat_foot_pitch's result, but exact: the source's flat foot is its bind foot (slope and ankle/toes matrices)."""
    res = {"toes": {}}
    for side in "LR":
        fa = _find_mocap(ns, source_name("Ankle_" + side, standard))
        fb = _find_mocap(ns, source_name("Toes_" + side, standard))
        fa, fb = [cmds.ls(x, long=True)[0] if x else None for x in (fa, fb)]
        if not (fa in mats and fb in mats):
            res[side] = None
            continue
        ma, mb = mats[fa], mats[fb]
        v = [mb[12] - ma[12], mb[13] - ma[13], mb[14] - ma[14]]
        res[side] = math.degrees(math.atan2(-v[1], math.hypot(v[0], v[2])))
        res["toes"][side] = (list(ma), list(mb))
    return res


def _pose_world(mats):
    """Put joints at their world rotations from `mats` (parents first); positions stay (bone lengths don't change)."""
    import maya.api.OpenMaya as om
    for j in sorted(mats or {}, key=lambda n: n.count("|")):
        if not cmds.objExists(j):
            continue
        want = _rot3(om.MMatrix(mats[j]))
        now = _rot3(om.MMatrix(cmds.xform(j, q=True, ws=True, m=True)))
        try:
            _rotate_world(j, om.MTransformationMatrix(now.inverse() * want).rotation(asQuaternion=True))
        except Exception:
            pass


def zero_out_mocap(ns, zero_top_translate=True, from_node=None):
    """Step 8 of the manual flow at the current frame (-1): top root position = 0, then Select > Hierarchy and
    every rotate = 0 (the top 'Group' node of a Mixamo download can carry a rotation too)."""
    nodes = cmds.ls(ns + ":*", long=True, type="transform") + cmds.ls(ns + ":*:*", long=True, type="transform")
    joints = [n for n in nodes if cmds.nodeType(n) == "joint"]
    tops = set("|" + n.split("|")[1] for n in joints)
    for t in (tops if zero_top_translate else []):
        for ax in "xyz":
            try:
                cmds.setAttr("%s.t%s" % (t, ax), 0)
            except Exception:
                pass
    hier = set()
    # foreign skeletons: only the hips and below (nodes above can hold a static axis conversion, e.g. Z-up)
    for t in ([cmds.ls(from_node, long=True)[0]] if from_node else tops):
        hier.add(t)
        hier.update(cmds.listRelatives(t, allDescendents=True, type="transform", fullPath=True) or [])
    for n in hier:
        for ax in "xyz":
            try:
                cmds.setAttr("%s.r%s" % (n, ax), 0)
            except Exception:
                pass
    return len(joints)


def _key_static_channels(top, frame):
    """Key every un-animated translate/rotate channel of `top` and its descendants at `frame` (current values)."""
    cmds.currentTime(frame)
    nodes = [top] + (cmds.listRelatives(top, allDescendents=True, type="joint", fullPath=True) or [])
    n = 0
    for node in nodes:
        for ch in ("tx", "ty", "tz", "rx", "ry", "rz"):
            plug = node + "." + ch
            try:
                if cmds.getAttr(plug, lock=True) or cmds.listConnections(plug, s=True, d=False):
                    continue
                cmds.setKeyframe(node, attribute=ch, time=frame)
                n += 1
            except Exception:
                pass
    return n


def _attr_default(plug):
    node, attr = plug.split(".", 1)
    try:
        d = cmds.attributeQuery(attr, node=node, listDefault=True)
        return d[0] if d else 0.0
    except Exception:
        return 0.0


def key_bind_pose(nodes, frame=-1):
    n = 0
    for node in nodes:
        for c in cmds.listConnections(node, s=True, d=False, type="animCurve", plugs=False) or []:
            plugs = cmds.listConnections(c + ".output", s=False, d=True, plugs=True) or []
            for p in plugs:
                cmds.setKeyframe(p, time=frame, value=_attr_default(p))
                n += 1
    return n


def anim_curves_of(nodes):
    out = []
    for node in nodes:
        out += cmds.listConnections(node, s=True, d=False, type="animCurve") or []
    return [c for c in set(out) if not cmds.nodeType(c).startswith("animCurveU")]


def key_reduce(curves, precision=0.5, mode=1):
    """Maya Key Reducer (filterCurve keyReducer). mode 0 = absolute value, 1 = percentage of each curve's range."""
    before = sum(cmds.keyframe(c, q=True, kc=True) for c in curves)
    if curves:
        cmds.filterCurve(curves, filter="keyReducer", precisionMode=mode, precision=precision)
    after = sum(cmds.keyframe(c, q=True, kc=True) for c in curves)
    return before, after


def char_name_from_rig(rig_path):
    stem = os.path.splitext(os.path.basename(rig_path))[0]
    return re.sub(r"(?i)[_\-]?rig$", "", stem) or stem


def is_as_rig():
    return cmds.objExists("DeformationSystem") and cmds.objExists("RootX_M")


def scene_has_control_animation():
    """True when AS controllers already carry time keys (e.g. a motion was applied before)."""
    for c in cmds.ls(type=("animCurveTL", "animCurveTA", "animCurveTU")) or []:
        for d in cmds.listConnections(c + ".output", s=False, d=True) or []:
            if d.startswith(("FK", "IK", "Pole", "RootX", "Root")) and ":" not in d:
                return True
    return False


def _bake_ik_to(ik, target, attrs, start, end):
    """Bake the IK control onto the target over the clip (rig without a live grip); -1 keeps the bind pose."""
    con = cmds.parentConstraint(target, ik, maintainOffset=False,
                                skipTranslate=[x.lower() for x in "XYZ" if "translate" + x not in attrs] or "none",
                                skipRotate=[x.lower() for x in "XYZ" if "rotate" + x not in attrs] or "none")[0]
    cmds.bakeResults(ik, attribute=attrs, simulation=True, t=(start, end), sampleBy=1, disableImplicitControl=True,
                     preserveOutsideKeys=True, sparseAnimCurveBake=False)
    cmds.delete(con)
    for a in attrs:
        cmds.setKeyframe(ik, attribute=a, time=-1, value=0.0)


def two_hand_grip(start, end, cb=None, side="L", target="LeftGrip_IK"):
    """Left hand holds the weapon: the arm goes to IK for the clip and its IK control is baked onto the grip target
    (a node of the gun prop that follows the right hand). With IKArm_L.followGun the hand also rides with the gun.
    The -1 frame keeps the bind pose."""
    ik, fkik = "IKArm_" + side, "FKIKArm_" + side
    if not (cmds.objExists(target) and cmds.objExists(ik) and cmds.objExists(fkik)):
        log(cb, u"    雙手武器：rig 裡沒有 %s，略過" % target)
        return False
    attrs = [a + x for a in ("translate", "rotate") for x in "XYZ"
             if not cmds.getAttr("%s.%s" % (ik, a + x), lock=True)]
    cmds.cutKey(ik, attribute=attrs, clear=True)
    if cmds.attributeQuery("followGun", node=ik, exists=True):
        # hand rides with the gun from the clip start; baked in world space, so the keys live in the gun's space
        # and later gun sway/recoil edits carry the hand along
        cmds.cutKey(ik, attribute="followGun", clear=True)       # the main bake keyed it on every frame
        cmds.setKeyframe(ik, attribute="followGun", time=-1, value=0)
        cmds.setKeyframe(ik, attribute="followGun", time=start, value=1)
        cmds.keyTangent(ik, attribute="followGun", outTangentType="step")
    _bake_ik_to(ik, target, attrs, start, end)
    old = cmds.getAttr(fkik + ".FKIKBlend")
    cmds.setKeyframe(fkik, attribute="FKIKBlend", time=-1, value=old)
    cmds.setKeyframe(fkik, attribute="FKIKBlend", time=start, value=10)
    cmds.keyTangent(fkik, attribute="FKIKBlend", outTangentType="step")
    # short (chibi) arms may not reach the grip when the right hand pushes the gun forward: on those frames
    # lengthen the IK arm (AS Lenght1/Lenght2) just enough to reach, otherwise keep it at 1
    sh, el, wr = "Shoulder_" + side, "Elbow_" + side, "Wrist_" + side
    grip = cmds.listRelatives(target, parent=True)[0] if cmds.listRelatives(target, parent=True) else target
    stretched = 0
    if all(cmds.objExists(n) for n in (sh, el, wr)) and cmds.attributeQuery("Lenght1", node=ik, exists=True):
        def _d(a, b):
            pa, pb = _ws(a), _ws(b)
            return sum((x - y) ** 2 for x, y in zip(pa, pb)) ** 0.5
        cmds.currentTime(-1)
        arm = _d(sh, el) + _d(el, wr)
        lens = ["Lenght1", "Lenght2"]
        cmds.cutKey(ik, attribute=lens, clear=True)
        for f in range(int(start), int(end) + 1):
            cmds.currentTime(f)
            ratio = max(1.0, _d(sh, grip) / arm * 1.01) if arm > 1e-6 else 1.0
            stretched += ratio > 1.0
            for a in lens:
                cmds.setKeyframe(ik, attribute=a, time=f, value=ratio)
        for a in lens:
            cmds.setKeyframe(ik, attribute=a, time=-1, value=1.0)
    if cmds.objExists("Gun_Ctrl") and cmds.attributeQuery("gunInHand", node="Gun_Ctrl", exists=True):
        cmds.setKeyframe("Gun_Ctrl", attribute="gunInHand", time=start, value=1)
    if cmds.objExists("Gun_Ctrl") and cmds.attributeQuery("showGun", node="Gun_Ctrl", exists=True):
        cmds.cutKey("Gun_Ctrl", attribute="showGun", clear=True)
        cmds.setKeyframe("Gun_Ctrl", attribute="showGun", time=-1, value=0)
        cmds.setKeyframe("Gun_Ctrl", attribute="showGun", time=start, value=1)
    log(cb, u"    雙手武器：左手改 IK，黏在槍的握點上（%d-%d）%s" % (start, end,
            (u"，%d 格手臂太短、自動拉長" % stretched) if stretched else u""))
    return True


def make_in_place(node, start, end):
    """Remove the root's travel: subtract the straight line from its start to its end position on world X/Z, frame by
    frame (height, sway and bob stay; start and end now match so a cycle loops in place). Returns the drift removed."""
    start, end = int(start), int(end)
    pos = {}
    for f in range(start, end + 1):
        cmds.currentTime(f)
        pos[f] = cmds.xform(node, q=True, ws=True, t=True)
    span = float(max(1, end - start))
    dx = pos[end][0] - pos[start][0]
    dz = pos[end][2] - pos[start][2]
    if abs(dx) < 1e-3 and abs(dz) < 1e-3:
        return 0.0, 0.0
    for f in range(start, end + 1):
        k = (f - start) / span
        p = pos[f]
        cmds.currentTime(f)
        cmds.xform(node, ws=True, t=(p[0] - dx * k, p[1], p[2] - dz * k))
        cmds.setKeyframe(node, attribute=["translateX", "translateY", "translateZ"], time=f)
    return dx, dz


def retarget_bones():
    """AS deform joints in the current scene that a retarget can drive (have an FK/Root control), e.g. Elbow_R."""
    out = []
    for dj in cmds.listRelatives("DeformationSystem", allDescendents=True, type="joint") or []:
        if mixamo_name(dj) and cmds.objExists("RootX_M" if dj == "Root_M" else "FK" + dj):
            out.append(dj)
    return out


def animated_controls():
    """AS controllers that already carry animation curves."""
    out = set()
    for c in cmds.ls(type=("animCurveTL", "animCurveTA", "animCurveTU")) or []:
        for d in cmds.listConnections(c + ".output", s=False, d=True) or []:
            if d.startswith(("FK", "IK", "Pole", "RootX", "Root")) and ":" not in d and cmds.nodeType(d) == "transform":
                out.add(d)
    return sorted(out)


def _root_namespaces():
    return set(cmds.namespaceInfo(":", listOnlyNamespaces=True) or [])


def apply_motion(*args, **kwargs):
    """See _apply_motion. If it fails part-way, the imported source skeleton (its temp namespace) and the MoCap
    constraints are removed again, so a failed retarget does not leave the source bones in the scene."""
    before = _root_namespaces()
    # Auto Key must be off: the source is posed at frame -1 with plain setAttr (no keys) to measure the constraint
    # offsets. With Auto Key on, Maya keys that rest pose at -1 and the clip ramps from the rest pose to its first key.
    auto_key = cmds.autoKeyframe(q=True, state=True)
    if auto_key:
        cmds.autoKeyframe(state=False)
    try:
        return _apply_motion(*args, **kwargs)
    except BaseException:
        try:
            cmds.namespace(set=":")
            disconnect_mocap()
            for ns in sorted(_root_namespaces() - before):
                if re.match(r"^new\d*$", ns.lstrip(":")) and cmds.namespace(exists=ns):
                    cmds.namespace(removeNamespace=ns, deleteNamespaceContent=True)
        except Exception:
            pass   # never hide the original error
        raise
    finally:
        if auto_key:
            cmds.autoKeyframe(state=True)


def _hips_joint(ns, src, hips):
    """The joint under `hips` that is the common parent of the source spine and both thighs, if it is deeper than
    `hips` and not a mapped bone; else None."""
    kids = [_find_mocap(ns, src.name(j)) for j in ("Spine1_M", "Hip_L", "Hip_R")]
    if not all(kids):
        return None
    chains = [cmds.ls(k, long=True)[0].split("|") for k in kids]
    common = []
    for parts in zip(*chains):
        if len(set(parts)) != 1:
            break
        common.append(parts[0])
    lca = "|".join(common)
    hips_long = cmds.ls(hips, long=True)[0]
    if not lca or lca == hips_long or not lca.startswith(hips_long + "|") or cmds.nodeType(lca) != "joint":
        return None
    short = lca.split("|")[-1]
    mapped = set(_find_mocap(ns, src.name(j)) for j in _DETECT)
    if lca in mapped or any(m and m.split("|")[-1] == short for m in mapped):
        return None
    return lca


def toes_only_bend(ctrls, start, end, limit=90.0):
    """AS toe controls only bend on Z: keep the part of each baked toe rotation that turns about the control's own Z
    (swing-twist, so an equivalent Euler like (180, 180, z) cannot fold the toe back), clamp it to +-limit degrees,
    and zero X / Y."""
    import maya.api.OpenMaya as om
    toes = [c for c in ctrls if re.match(r"^(IK|FK)Toes_[LR]$", c)]
    for c in toes:
        order = cmds.getAttr(c + ".rotateOrder")
        vals = {}
        for fr in range(int(start), int(end) + 1):
            r = cmds.getAttr(c + ".rotate", time=fr)[0]
            q = om.MEulerRotation(*[math.radians(v) for v in r], order=order).asQuaternion()
            z = math.degrees(2.0 * math.atan2(q.z, q.w))
            z = ((z + 180.0) % 360.0) - 180.0
            vals[fr] = max(-limit, min(limit, z))
        for ax in ("rx", "ry"):
            if cmds.keyframe(c + "." + ax, q=True, kc=True):
                cmds.cutKey(c, attribute=ax, time=(start, end), clear=True)
            cmds.setKeyframe(c, attribute=ax, time=start, value=0.0)
            cmds.setKeyframe(c, attribute=ax, time=end, value=0.0)
        for fr, v in vals.items():
            cmds.setKeyframe(c, attribute="rz", time=fr, value=v)
    return len(toes)


def _apply_motion(fbx, reduce=True, precision=3.0, precision_mode=1, euler=True, cb=None, source="auto", in_place=False,
                  two_hand=False, parts=None):
    """Bake a motion FBX onto the AS rig in the CURRENT scene (no file open / save).
    source: 'auto' | 'mixamo' (Y Bot / X Bot) | 'custom' (our uploaded skeleton) | a built-in library key (Biped, Unreal, Rokoko...).
    parts: AS deform joint names to drive (e.g. ['Shoulder_R', 'Elbow_R']); None = the whole body. Controls of the
    other bones keep whatever animation they already have."""
    load_fbx()
    if not is_as_rig():
        raise RuntimeError(u"這不是 AdvancedSkeleton 的 rig 檔（找不到 DeformationSystem / RootX_M）")
    if parts is not None:
        parts = set(parts)
        if not parts:
            raise RuntimeError(u"沒有選任何部位")
        if two_hand and not {"Shoulder_L", "Elbow_L", "Wrist_L"} <= parts:
            two_hand = False
            log(cb, u"    雙手武器略過：要選左手臂（Shoulder_L、Elbow_L、Wrist_L）才會套用")
    old_range = (cmds.playbackOptions(q=True, min=True), cmds.playbackOptions(q=True, max=True))
    existing = animated_controls() if parts is not None else []
    cmds.currentUnit(time="ntsc")  # 30 fps
    ns = "new"
    i = 1
    while cmds.namespace(exists=ns):
        i += 1
        ns = "new%d" % i
    cmds.namespace(add=ns)
    cmds.namespace(set=ns)
    try:
        cmds.file(fbx, i=True, type="FBX", ignoreVersion=True, options="fbx")
    finally:
        cmds.namespace(set=":")
    if cmds.currentUnit(q=True, time=True) != "ntsc":
        cmds.currentUnit(time="ntsc")
    mjoints = cmds.ls(ns + ":*", type="joint") + cmds.ls(ns + ":*:*", type="joint")
    if not mjoints:
        raise RuntimeError(u"FBX 裡沒有骨架")
    times = cmds.keyframe(mjoints, q=True, tc=True) or []
    if not times:
        raise RuntimeError(u"FBX 裡沒有動畫")
    start, end = round(min(times)), round(max(times))
    cmds.currentTime(-1)
    if source == "standard":  # older name
        source = "mixamo"
    sources = list_sources()
    found, score = detect_source(ns, sources)
    if source == "auto":
        src = found
        if score < 8:
            raise RuntimeError(u"認不出這個骨架是哪個來源，請手動選「來源」")
        log(cb, u"    來源（自動判斷）：%s" % src.label)
    else:
        src = next((x for x in sources if x.key == source), None) or get_source(source)
        if found and found.key != src.key:
            log(cb, u"    注意：選的是「%s」，但這個 FBX 看起來像「%s」" % (src.label, found.label))
    standard = src
    hips = _find_mocap(ns, src.name("Root_M"))
    if not hips:
        raise RuntimeError(u"在 FBX 裡找不到「%s」的 Root（%s）" % (src.label, src.name("Root_M")))
    # some exports have an extra pelvis under the mapped one (pelvis > "Bip001 Pelvis" > spine_01 / thighs) that holds
    # a fixed rotation. The hips' real orientation is that deeper joint's: drive Root_M from the lowest joint that is
    # the parent of both the spine and the legs, as long as it is not itself a mapped bone.
    lca = _hips_joint(ns, src, hips)
    if lca:
        src = Source(src.key, src.label, src.foreign, src.mapping, src.side)
        src.override = {"Root_M": lca.split("|")[-1].split(":")[-1]}
        standard = src
        log(cb, u"    骨盆：用 %s（脊椎和大腿真正的上一層），不用 %s" % (src.override["Root_M"], hips.split("|")[-1].split(":")[-1]))
        hips = lca
    # clip range = keys of the body bones only: helper nodes (Bip001 Footsteps, a root, props) can carry keys outside
    # the take (e.g. a take 86-127 whose helpers are keyed from 0)
    body = [b for b in (_find_mocap(ns, src.name(j)) for j in _DETECT) if b]
    btimes = cmds.keyframe(body, q=True, tc=True) or [] if body else []
    if btimes and (round(min(btimes)), round(max(btimes))) != (start, end):
        log(cb, u"    動作範圍：%d-%d（骨架 key 的範圍；檔案裡其他輔助節點的 %d-%d 不算）" % (round(min(btimes)), round(max(btimes)), start, end))
        start, end = round(min(btimes)), round(max(btimes))
    if existing:   # partial retarget over an existing motion: keep its range too
        lo, hi = min(start, old_range[0]), max(end, old_range[1])
        cmds.playbackOptions(min=lo, max=hi, ast=lo, aet=hi)
        # the constraints take their offsets at frame -1: make sure -1 is the bind pose on every animated control
        key_bind_pose(existing, -1)
        log(cb, u"    只套用 %d 根骨頭，其他部位保留原本的動畫" % len(parts))
    else:
        cmds.playbackOptions(min=start, max=end, ast=start, aet=end)
        if parts is not None:
            log(cb, u"    只套用 %d 根骨頭" % len(parts))

    cmds.currentTime(-1)
    # channels without animation (e.g. a Biped pelvis: its motion lives on Bip001 above it) would keep the
    # rest-pose edits made at frame -1 for the whole clip -> key their own values at the start first
    _key_static_channels(hips, start)
    ref_pose = capture_ref_pose(ns, standard, start) if src.foreign else None
    # another AS rig's skeleton with its skinned mesh: the skin's bind pose is that character's true rest pose (feet
    # flat). Use it instead of guessing the flat foot from a planted frame, which copies that frame's small tilt
    # (the source is itself a retarget) onto every frame
    src_bind = _source_skin_bind(ns, hips) if src.key == "AdvancedSkeleton" else None
    foot_pitch = flat_foot_pitch(ns, standard, start, end) if src.foreign and not src_bind else None
    if src_bind:
        foot_pitch = _bind_foot_pitch(ns, standard, src_bind)
    elif foot_pitch:
        foot_pitch["toes"] = {}
        for side, fr in foot_pitch.get("frames", {}).items():
            fa = _find_mocap(ns, source_name("Ankle_" + side, standard))
            fb = _find_mocap(ns, source_name("Toes_" + side, standard))
            if fa and fb:
                cmds.currentTime(fr)
                foot_pitch["toes"][side] = (cmds.xform(fa, q=True, ws=True, m=True), cmds.xform(fb, q=True, ws=True, m=True))
    # In Place only after the planted feet were found: with the travel removed a planted foot slides backwards, its
    # frames no longer count as planted, and the flat-foot slope came out wrong (feet tilted for the whole clip)
    cmds.currentTime(-1)
    if in_place:
        dx, dz = make_in_place(hips, start, end)
        log(cb, u"    In Place：去掉位移 X %.1f、Z %.1f（來源單位）" % (dx, dz) if (dx or dz) else u"    In Place：本來就在原地")
        cmds.currentTime(-1)
    del _TWIST_FIXED[:]
    cmds.currentTime(-1)
    if src.foreign:
        zero_out_mocap(ns, zero_top_translate=False, from_node=hips)
        _pose_world(src_bind)
    else:
        zero_out_mocap(ns)
    scale = 1.0
    if src.foreign:
        align_rest_pose(ns, standard, ref_pose, foot_pitch)
        scale = body_scale(ns, standard)
        # put the source's rest pose where the rig stands: horizontally under the rig's root (in source size),
        # height so its ankles are at the source's own ground-contact height (lowest ankle height in the clip)
        # -> a planted source foot maps to the rig's ankle at its bind height, i.e. on the ground
        root = _ws("Root_M")
        cur = _ws(hips)
        feet = [f for f in (_find_mocap(ns, src.name("Ankle_L")), _find_mocap(ns, src.name("Ankle_R"))) if f]
        dy = 0.0
        if feet:
            rest_ank = sum(_ws(f)[1] for f in feet) / len(feet)
            ground = None
            for fr in range(int(start), int(end) + 1):
                cmds.currentTime(fr)
                low = min(_ws(f)[1] for f in feet)
                ground = low if ground is None else min(ground, low)
            cmds.currentTime(-1)
            zero_out_mocap(ns, zero_top_translate=False, from_node=hips)
            _pose_world(src_bind)
            align_rest_pose(ns, standard, ref_pose, foot_pitch)
            cur = _ws(hips)
            rest_ank = sum(_ws(f)[1] for f in feet) / len(feet)
            dy = ground - rest_ank
        cmds.xform(hips, ws=True, t=[root[0] / scale, cur[1] + dy, root[2] / scale])
        log(cb, u"    已對齊成 rig 的 bind pose，比例 x%.3f" % scale)
        if src_bind:
            log(cb, u"    來源是 AS 角色：用它模型綁定時的姿勢（bind pose）當基準，它的平腳對應到 rig 的平腳")
        elif foot_pitch and foot_pitch.get("L") is not None:
            log(cb, u"    腳掌：來源踩平時腳踝→腳趾斜 %.0f°，對應到 rig 的平腳（踩地時 IK 腳控制器會是平的）" % foot_pitch["L"])
        elif foot_pitch is not None:
            log(cb, u"    腳掌：動作裡沒有踩地的格數，腳掌照骨頭方向對齊")
        if _TWIST_FIXED:
            log(cb, u"    扭轉修正（零姿勢與動作差超過 90°）：%s" % ", ".join(sorted(set(_TWIST_FIXED))))
    dests, connected, missing = connect_mocap(ns, cb, standard, scale, parts)
    if not dests:
        disconnect_mocap()
        cmds.namespace(removeNamespace=ns, deleteNamespaceContent=True)
        raise RuntimeError(u"選取的部位在這個 rig 或動作檔裡都沒有對應的骨頭")
    log(cb, u"    連上 %d 根骨頭，控制器 %d 個%s" % (connected, len(dests),
            (u"，動作檔缺: " + ", ".join(missing)) if missing else ""))

    cmds.bakeResults(dests, simulation=True, t=(start, end), sampleBy=1, disableImplicitControl=True,
                     preserveOutsideKeys=parts is not None, sparseAnimCurveBake=False, removeBakedAttributeFromLayer=False,
                     bakeOnOverrideLayer=False, controlPoints=False, shape=False)
    disconnect_mocap()
    cmds.namespace(removeNamespace=ns, deleteNamespaceContent=True)

    toes_only_bend(dests, start, end)
    nb = key_bind_pose(dests, -1)
    if two_hand:
        two_hand_grip(start, end, cb)
    curves = anim_curves_of(dests)
    if euler:
        rot = [c for c in curves if cmds.nodeType(c) == "animCurveTA"]
        if rot:
            cmds.filterCurve(rot, filter="euler")
    kb, ka = key_reduce(curves, precision, precision_mode) if reduce else (0, 0)
    cmds.select(dests)
    cmds.delete(staticChannels=True, unitlessAnimationCurves=False, hierarchy="none", controlPoints=False, shape=True)
    cmds.select(clear=True)
    cmds.currentTime(start)
    return {"standard": src.foreign, "source": src.key, "sourceLabel": src.label, "scale": round(scale, 4), "start": start, "end": end, "connected": connected,
            "controls": len(dests), "missing": missing, "bindKeys": nb, "keysBefore": kb, "keysAfter": ka}


def retarget_motion(rig, fbx, out, reduce=True, precision=3.0, precision_mode=1, euler=True, cb=None, source="auto",
                    in_place=False, two_hand=False, parts=None):
    """Open the rig file, apply the motion, save as `out` (the rig file itself is never written)."""
    if os.path.normcase(os.path.abspath(out)) == os.path.normcase(os.path.abspath(rig)):
        raise RuntimeError("output equals rig file")
    load_fbx()
    cmds.file(rig, open=True, force=True, prompt=False)
    r = apply_motion(fbx, reduce, precision, precision_mode, euler, cb, source, in_place, two_hand, parts)
    if os.path.normcase(os.path.abspath(out)) == os.path.normcase(os.path.abspath(rig)):
        raise RuntimeError("output equals rig file")
    if not os.path.isdir(os.path.dirname(out)):
        os.makedirs(os.path.dirname(out))
    cmds.file(rename=out)
    cmds.file(save=True, type="mayaBinary" if out.lower().endswith(".mb") else "mayaAscii", force=True)
    return r


# ======================================================================================= 3. Go to Build Pose
def _build_pose_nodes(namespace=None):
    if namespace is not None:
        ns = namespace.rstrip(":")
        n = (ns + ":buildPose") if ns else "buildPose"
        return [n] if cmds.objExists(n) else []
    return [n for n in (cmds.ls("buildPose") or []) + (cmds.ls("*:buildPose", recursive=True) or [])]


def go_to_build_pose(namespace=None, keep_main=False, cb=None):
    """Same as AdvancedSkeleton's 'Go to Build Pose', without needing AS installed: the rig stores its build pose
    as setAttr/xform commands on the 'buildPose' node; replay them (with the rig's namespace added).
    namespace=None: every AS rig in the scene (or only the rig of the selected controls, if any are selected).
    keep_main=True: leave Main where it is (like Ctrl+click in AS)."""
    if namespace is None:
        sel = cmds.ls(selection=True) or []
        spaces = sorted(set(s.rpartition(":")[0] for s in sel)) if sel else None
        nodes = []
        for sp in (spaces or [None]):
            nodes += _build_pose_nodes(sp)
        nodes = sorted(set(nodes))
    else:
        nodes = _build_pose_nodes(namespace)
    if not nodes:
        raise RuntimeError(u"找不到 buildPose（這不是 AdvancedSkeleton 的 rig？）")
    done, failed = 0, []
    cmds.undoInfo(openChunk=True, chunkName="goToBuildPose")
    try:
        for node in nodes:
            ns = node.rpartition(":")[0]
            ns = ns + ":" if ns else ""
            text = cmds.getAttr(node + ".udAttr") or ""
            if cmds.attributeQuery("udExtraAttr", node=node, exists=True):
                text += cmds.getAttr(node + ".udExtraAttr") or ""
            for c in text.split(";"):
                c = c.strip()
                if not c:
                    continue
                tok = c.split()
                k = len(tok) - 1 if tok[0] == "xform" else 1
                if ns:
                    tok[k] = ns + tok[k]
                if keep_main and re.match(r"^(.*:)?Main(\.|$)", tok[k]):
                    continue
                try:
                    mel.eval(" ".join(tok))
                    done += 1
                except Exception:
                    failed.append(" ".join(tok))
    finally:
        cmds.undoInfo(closeChunk=True)
    log(cb, u"Build Pose：%d 個指令%s" % (done, (u"，%d 個失敗" % len(failed)) if failed else ""))
    return done, failed



# ======================================================================================= 4. left hand follows the gun
def toggle_follow_gun(side="L", value=None, key=True):
    """Switch IKArm_L.followGun on the current frame without the hand jumping (the IK control is put back where the
    hand was and keyed). followGun 1 = the hand rides along with the gun's sway; its own animation still works."""
    ik = "IKArm_" + side
    if not (cmds.objExists(ik) and cmds.attributeQuery("followGun", node=ik, exists=True)):
        raise RuntimeError(u"%s 沒有 followGun（這個 rig 沒有槍道具）" % ik)
    cur = cmds.getAttr(ik + ".followGun")
    new = (0.0 if cur > 0.5 else 1.0) if value is None else float(value)
    m = cmds.xform(ik, q=True, ws=True, m=True)
    t = cmds.currentTime(q=True)
    cmds.undoInfo(openChunk=True, chunkName="toggleFollowGun")
    try:
        if key:
            cmds.setKeyframe(ik, attribute="followGun", time=t - 1, value=cur)
        cmds.setAttr(ik + ".followGun", new)
        if key:
            cmds.setKeyframe(ik, attribute="followGun", time=t, value=new)
            cmds.keyTangent(ik, attribute="followGun", time=(t - 1, t), outTangentType="step")
        cmds.xform(ik, ws=True, m=m)
        if key:
            cmds.setKeyframe(ik, attribute=["translate", "rotate"], time=t)
    finally:
        cmds.undoInfo(closeChunk=True)
    return new
