# -*- coding: utf-8 -*-
"""AS Retarget: copy controller animation from another file of the SAME AdvancedSkeleton rig (same control names)
onto the rig in the current scene. Optional: only some body parts, and/or onto a new (override) animation layer.

The source file is imported into a temporary namespace (script nodes not executed), its time-based anim curves are
duplicated onto the controls with the same names, then the imported nodes are deleted again."""
import os
import re

import maya.cmds as cmds

from . import asMixamoCore as core

ARM = ("Shoulder", "Elbow", "Wrist")
LEG = ("Hip", "Knee", "Ankle", "Toes")
ARM_IK = ("IKArm", "PoleArm", "FKIKArm", "IKExtraArm", "PoleExtraArm")
LEG_IK = ("IKLeg", "PoleLeg", "FKIKLeg", "IKExtraLeg", "PoleExtraLeg", "RollHeel", "RollToesEnd", "RollToes",
          "RollAnkle", "IKToes", "IKLegHeel", "IKLegToe", "IKLegBall")
SPINE_IK = ("IKSpine", "FKIKSpine", "IKhybridSpine", "IKExtraSpine")
TIME_CURVES = ("animCurveTL", "animCurveTA", "animCurveTU", "animCurveTT")


def log(cb, msg):
    if cb:
        cb(msg)
    else:
        print(msg)


def pickable_bones():
    """Deform joints of the scene's rig whose controls can be picked: the retarget bones plus the palm cup (Cup_L/R,
    on rigs that have one: no motion file has a cup, but another file of the same rig does)."""
    return core.retarget_bones() + [c for c in ("Cup_L", "Cup_R") if cmds.objExists(c) and cmds.objExists("FK" + c)]


def control_bones(ctrl, rig_bones):
    """Deform joints that a controller moves, or None if it isn't a body control (Main, props, hat, face...)."""
    side = ctrl[-2:] if ctrl[-2:] in ("_R", "_L", "_M") else ""
    if ctrl.startswith(("RootX", "HipSwinger")):
        return {"Root_M"}
    if side and ctrl.startswith(ARM_IK):
        return {b + side for b in ARM}
    if side and ctrl.startswith(LEG_IK):
        return {b + side for b in LEG}
    if ctrl.startswith(SPINE_IK):
        return {b for b in rig_bones if b.startswith(("Spine", "Chest"))} or None
    if ctrl.startswith("FK") and ctrl[2:] in rig_bones:
        return {ctrl[2:]}
    return None


def _source_curves(ns):
    """{dest plug (no namespace): source anim curve} for time-based curves driving controls in `ns`."""
    out, layered = {}, False
    for node in cmds.ls(ns + ":*", type="transform") or []:
        pairs = cmds.listConnections(node, s=True, d=False, connections=True, plugs=True, skipConversionNodes=True) or []
        for dst, srcp in zip(pairs[::2], pairs[1::2]):
            src = srcp.split(".")[0]
            typ = cmds.nodeType(src)
            if typ.startswith("animBlendNode"):
                layered = True
            elif typ in TIME_CURVES and not cmds.listConnections(src + ".input", s=True, d=False):
                out[dst.split(":")[-1]] = src
    return out, layered


def _other_character(ns):
    """Largest bone-length difference (percent) between the rig in the scene and the imported source rig, when it is
    over 3% (= another character); else 0. Bone lengths don't depend on the pose."""
    worst = 0.0
    for a, b in (("Root_M", "Neck_M"), ("Shoulder_L", "Elbow_L"), ("Elbow_L", "Wrist_L"), ("Hip_L", "Knee_L"),
                 ("Knee_L", "Ankle_L")):
        sa, sb = cmds.ls("%s:%s" % (ns, a)), cmds.ls("%s:%s" % (ns, b))
        if not (cmds.objExists(a) and cmds.objExists(b) and sa and sb):
            continue
        d = lambda x, y: sum((p - q) ** 2 for p, q in zip(cmds.xform(x, q=True, ws=True, t=True),
                                                           cmds.xform(y, q=True, ws=True, t=True))) ** 0.5
        here, there = d(a, b), d(sa[0], sb[0])
        if here > 1e-6:
            worst = max(worst, abs(there - here) / here * 100.0)
    return int(round(worst)) if worst > 3.0 else 0


def _bake_source_layers(ns, cb):
    """The source file uses animation layers: bake what they add up to onto its controls (one key per frame),
    so the copy is the motion you actually see in the source."""
    plugs, times = set(), []
    for lay in cmds.ls(ns + ":*", type="animLayer") or []:
        for c in cmds.animLayer(lay, q=True, animCurves=True) or []:
            times += cmds.keyframe(c, q=True, tc=True) or []
        for p in cmds.animLayer(lay, q=True, attribute=True) or []:
            node = p.split(".")[0]
            if cmds.objExists(node) and cmds.objectType(node, isAType="transform"):
                plugs.add(p)
    if not plugs:
        return
    # the range is every key in the file, not only the layers' keys: a correction layer often has a single key
    # (a constant offset for the whole clip), and baking only that frame dropped the correction everywhere else
    for c in cmds.ls(ns + ":*", type=TIME_CURVES) or []:
        times += cmds.keyframe(c, q=True, tc=True) or []
    if not times:
        return
    s, e = min(times), max(times)
    log(cb, u"來源檔有 Anim Layer：先把各層加起來的結果烘成 key（%g-%g，每格一個 key）" % (s, e))
    cur = cmds.namespaceInfo(currentNamespace=True, absoluteName=True)
    cmds.namespace(set=":" + ns)          # baked curves are created in the temp namespace, deleted with it
    try:
        cmds.bakeResults(sorted(plugs), time=(s, e), simulation=False, sampleBy=1, preserveOutsideKeys=True,
                         sparseAnimCurveBake=False, removeBakedAttributeFromLayer=True, removeBakedAnimFromLayer=False,
                         bakeOnOverrideLayer=False, minimizeRotation=True, disableImplicitControl=True)
    finally:
        cmds.namespace(set=cur)


def _free(plug):
    """Can we drive this plug with a curve? (exists, not locked, not driven by something other than an anim curve)"""
    node, attr = plug.split(".", 1)
    if not cmds.objExists(node) or not cmds.attributeQuery(attr.split("[")[0], node=node, exists=True):
        return False
    if cmds.getAttr(plug, lock=True):
        return False
    src = cmds.listConnections(plug, s=True, d=False, skipConversionNodes=True) or []
    return all(cmds.nodeType(s).startswith(("animCurve", "animBlendNode", "pairBlend")) for s in src)


def file_time_unit(path):
    """Time unit saved in a .ma/.mb (e.g. 'ntsc', 'film', '60fps') without opening it; None if not found."""
    try:
        with open(path, "rb") as f:
            head = f.read(1 << 16)
    except Exception:
        return None
    if path.lower().endswith(".ma"):
        m = re.search(rb"currentUnit[^;]*-t\s+([A-Za-z0-9]+)", head)
    else:
        m = re.search(rb"TUNI.{0,12}?(ntscf|ntsc|film|game|palf|pal|show|\d+(?:\.\d+)?fps|millisec|sec|min|hour)", head, re.S)
    return m.group(1).decode() if m else None


class _NoUndo(object):
    """Import / temp-namespace work stays out of the undo queue (Ctrl+Z only removes the retarget itself)."""
    def __enter__(self):
        self.state = cmds.undoInfo(q=True, stateWithoutFlush=True)
        cmds.undoInfo(stateWithoutFlush=False)

    def __exit__(self, *a):
        cmds.undoInfo(stateWithoutFlush=self.state)


def _unique_layer(name):
    name = re.sub(r"[^A-Za-z0-9_]", "_", name) or "AS_Retarget"
    if name[0].isdigit():
        name = "L_" + name
    base, i = name, 1
    while cmds.objExists(name):
        i += 1
        name = "%s%d" % (base, i)
    return name


def _scene_base_layer():
    """The scene's own root animation layer (BaseAnimation), created if the scene has no layers yet. New layers must be
    parented to it explicitly: otherwise, while the source file is imported, Maya hangs them under the IMPORTED
    BaseAnimation and they lose their effect when the temp namespace is deleted."""
    def roots():
        return [l for l in cmds.ls(type="animLayer") or [] if ":" not in l and not cmds.animLayer(l, q=True, parent=True)]
    r = roots()
    if not r:
        tmp = cmds.animLayer("asTmpLayer")
        r = roots()
        cmds.delete(tmp)
    return r[0] if r else None


def _import_file(src, ns):
    """Import quietly: a rig read into a namespace prints harmless node errors (e.g. AS's IKCurveInfoSpine_M
    'No valid NURBS curve') that look like the tool failed."""
    state = None
    try:
        state = (cmds.scriptEditorInfo(q=True, suppressErrors=True), cmds.scriptEditorInfo(q=True, suppressWarnings=True))
        cmds.scriptEditorInfo(e=True, suppressErrors=True, suppressWarnings=True)
    except Exception:
        pass
    try:
        cmds.file(src, i=True, namespace=ns, ignoreVersion=True, executeScriptNodes=False, preserveReferences=False,
                  mergeNamespacesOnClash=False, loadReferenceDepth="none")
    finally:
        if state:
            try:
                cmds.scriptEditorInfo(e=True, suppressErrors=state[0], suppressWarnings=state[1])
            except Exception:
                pass


def as_retarget(src, parts=None, layer=None, others=True, cb=None):
    """Copy the controller animation of `src` (.ma/.mb of the same AS rig) onto the current scene.
    parts: deform joint names (e.g. ['Shoulder_R']); None = all.  others: also controls that aren't body bones
    (Main, weapon, hat...).  layer: None = replace the curves on the controls; a name = put the keys on a new
    override animation layer with that name (base animation untouched)."""
    if not core.is_as_rig():
        raise RuntimeError(u"目前場景不是 AdvancedSkeleton 的 rig（找不到 DeformationSystem / RootX_M）")
    src = os.path.abspath(src)
    if not os.path.isfile(src):
        raise RuntimeError(u"找不到來源檔：%s" % src)
    cur = cmds.file(q=True, sceneName=True)
    if cur and os.path.normcase(os.path.abspath(cur)) == os.path.normcase(src):
        raise RuntimeError(u"來源檔就是目前打開的檔案")
    if parts is not None:
        parts = set(parts)
        if not parts:
            raise RuntimeError(u"沒有選任何部位")
    rig_bones = set(pickable_bones())
    old_range = (cmds.playbackOptions(q=True, min=True), cmds.playbackOptions(q=True, max=True))

    ns, i = "asRetargetSrc", 1
    while cmds.namespace(exists=ns):
        i += 1
        ns = "asRetargetSrc%d" % i
    base = _scene_base_layer() if layer else None
    log(cb, u"讀取來源：%s" % os.path.basename(src))
    unit, src_unit = cmds.currentUnit(q=True, time=True), file_time_unit(src)
    if src_unit and src_unit != unit:
        log(cb, u"來源是 %s、目前場景是 %s：照影格號碼搬（不換算成秒數）" % (src_unit, unit))
    with _NoUndo():
        if src_unit and src_unit != unit:      # import in the source's unit so key frame numbers stay as they are
            cmds.currentUnit(time=src_unit, updateAnimation=False)
        try:
            _import_file(src, ns)
        finally:
            if src_unit and src_unit != unit:
                cmds.currentUnit(time=unit, updateAnimation=False)
    result = {"curves": 0, "controls": set(), "skipped": [], "layer": None, "start": None, "end": None}
    diff = _other_character(ns)
    if diff:
        result["otherCharacter"] = diff
        log(cb, u"⚠ 來源和目前場景看起來不是同一隻角色（骨頭長度差 %d%%）：這裡是照抄控制器數值，"
                u"兩隻的 bind pose 不同（例如 A-pose 和 T-pose）時手腳會整段偏掉。"
                u"換角色請用「Retarget」分頁：在來源檔用「匯出 FBX」導出，再套到這隻角色。" % diff)
    try:
        with _NoUndo():
            curves, layered = _source_curves(ns)
            if layered:
                _bake_source_layers(ns, cb)
                curves, layered = _source_curves(ns)
        if not curves:
            raise RuntimeError(u"來源檔的控制器上沒有動畫")
        picked = {}
        for plug, c in curves.items():
            ctrl = plug.split(".")[0]
            if parts is not None:
                bones = control_bones(ctrl, rig_bones)
                if bones is None and not others:
                    continue
                if bones is not None and not (bones & parts):
                    continue
            elif not others and control_bones(ctrl, rig_bones) is None:
                continue
            if not _free(plug):
                result["skipped"].append(plug)
                continue
            picked[plug] = c
        if not picked:
            raise RuntimeError(u"選的部位在來源檔裡沒有動畫")
        times = cmds.keyframe(list(set(picked.values())), q=True, tc=True) or [0]
        result["start"], result["end"] = min(times), max(times)

        if layer:
            name = _unique_layer(layer)
            cmds.animLayer(name, override=True, parent=base) if base else cmds.animLayer(name, override=True)
            cmds.animLayer(name, e=True, attribute=sorted(picked))
            result["layer"] = name
            log(cb, u"建立 Anim Layer：%s（Override）" % name)
            for plug, c in sorted(picked.items()):
                cmds.copyKey(c)
                cmds.pasteKey(plug, animLayer=name, option="replaceCompletely")
                _copy_curve_settings(c, plug, name)
                result["curves"] += 1
                result["controls"].add(plug.split(".")[0])
        else:
            on_layers = []
            for plug, c in sorted(picked.items()):
                blend = [s for s in cmds.listConnections(plug, s=True, d=False) or []
                         if cmds.nodeType(s).startswith("animBlendNode")]
                if blend:      # the scene's own layers drive this attribute: replace its BaseAnimation curve only
                    cmds.copyKey(c)
                    cmds.pasteKey(plug, animLayer="BaseAnimation", option="replaceCompletely")
                    on_layers.append(plug.split(".")[0])
                else:
                    for old in cmds.listConnections(plug, s=True, d=False, type="animCurve") or []:
                        cmds.delete(old)
                    new = cmds.duplicate(c, name=":" + plug.replace(".", "_"))[0]
                    cmds.connectAttr(new + ".output", plug, force=True)
                result["curves"] += 1
                result["controls"].add(plug.split(".")[0])
            if on_layers:
                result["sceneLayers"] = sorted(set(on_layers))
                log(cb, u"⚠ 目前場景有 Anim Layer 也在控制 %d 個控制器：已換掉它們 Base Animation 的 key，"
                        u"但那些 layer 還是會疊上去。要完全照來源的動作，請勾「放在新的 Anim Layer」。" % len(set(on_layers)))
    finally:
        with _NoUndo():
            try:
                cmds.namespace(removeNamespace=ns, deleteNamespaceContent=True)
            except Exception as e:
                log(cb, u"清除暫存節點失敗：%s" % e)

    s, e = result["start"], result["end"]
    if parts is None and not layer:
        cmds.playbackOptions(min=s, max=e, animationStartTime=s, animationEndTime=e)
    else:
        s2, e2 = min(s, old_range[0]), max(e, old_range[1])
        cmds.playbackOptions(min=s2, max=e2, animationStartTime=min(s2, cmds.playbackOptions(q=True, ast=True)),
                             animationEndTime=max(e2, cmds.playbackOptions(q=True, aet=True)))
    result["controls"] = sorted(result["controls"])
    log(cb, u"完成：%d 個控制器、%d 條曲線，影格 %g-%g%s" % (len(result["controls"]), result["curves"], s, e,
                                                      (u"，放在 Layer「%s」" % result["layer"]) if result["layer"] else ""))
    if result["skipped"]:
        log(cb, u"略過（目前場景鎖住或被其他東西控制）：%s" % ", ".join(result["skipped"][:20]))
    return result


# ------------------------------------------------------------------------------- copy correction layers as layers
def _import_src(src, cb=None):
    """Import `src` into a fresh temp namespace (out of the undo queue, frame numbers kept). Returns the namespace."""
    ns, i = "asLayerSrc", 1
    while cmds.namespace(exists=ns):
        i += 1
        ns = "asLayerSrc%d" % i
    unit, src_unit = cmds.currentUnit(q=True, time=True), file_time_unit(src)
    with _NoUndo():
        if src_unit and src_unit != unit:
            cmds.currentUnit(time=src_unit, updateAnimation=False)
        try:
            _import_file(src, ns)
        finally:
            if src_unit and src_unit != unit:
                cmds.currentUnit(time=unit, updateAnimation=False)
    return ns


def _drop_ns(ns, cb=None):
    with _NoUndo():
        try:
            cmds.namespace(removeNamespace=ns, deleteNamespaceContent=True)
        except Exception as e:
            log(cb, u"清除暫存節點失敗：%s" % e)


def _layer_order(ns):
    """Animation layers of the namespace, bottom -> top (BaseAnimation excluded)."""
    # when the scene already has layers, Maya hangs the imported ones under the scene's own BaseAnimation, so walk
    # the whole layer tree and keep the ones from the namespace
    mine = set(cmds.ls(ns + ":*", type="animLayer") or [])
    roots = [l for l in cmds.ls(type="animLayer") or [] if not cmds.animLayer(l, q=True, parent=True)]
    out = []

    def walk(l):
        for c in cmds.animLayer(l, q=True, children=True) or []:
            if c in mine and not c.endswith((":BaseAnimation", ":AnimLayerRoot")) and cmds.animLayer(c, q=True, attribute=True):
                out.append(c)
            walk(c)
    for r in roots:
        walk(r)
    return out


def _layer_info(l):
    curves = cmds.animLayer(l, q=True, animCurves=True) or []
    times = cmds.keyframe(curves, q=True, tc=True) if curves else None
    return {"name": l.split(":")[-1], "override": bool(cmds.animLayer(l, q=True, override=True)),
            "weight": cmds.animLayer(l, q=True, weight=True), "mute": bool(cmds.animLayer(l, q=True, mute=True)),
            "attrs": len(cmds.animLayer(l, q=True, attribute=True) or []),
            "range": (min(times), max(times)) if times else None}


def _static_offsets(layer, plugs):
    """Additive layer attributes without a curve: their offset = value with the layer on - value with it muted."""
    if not plugs:
        return []
    out = []
    with _NoUndo():
        on = [cmds.getAttr(p) for p, _ in plugs]
        was = cmds.animLayer(layer, q=True, mute=True)
        cmds.animLayer(layer, e=True, mute=True)
        try:
            off = [cmds.getAttr(p) for p, _ in plugs]
        finally:
            cmds.animLayer(layer, e=True, mute=was)
    for (p, d), a, b in zip(plugs, on, off):
        if isinstance(a, (int, float)) and abs(a - b) > 1e-5:
            out.append((d, a - b))
    return out


COMPOUND = {"translate": ("translateX", "translateY", "translateZ"), "rotate": ("rotateX", "rotateY", "rotateZ"),
            "scale": ("scaleX", "scaleY", "scaleZ")}


def _anim_plugs(ns):
    """Animated plugs (base curves or layer blends) of the transforms in `ns`, without the namespace."""
    out = set()
    for node in cmds.ls(ns + ":*", type="transform") or []:
        pairs = cmds.listConnections(node, s=True, d=False, connections=True, plugs=True, skipConversionNodes=True) or []
        for dst, srcp in zip(pairs[::2], pairs[1::2]):
            typ = cmds.nodeType(srcp.split(".")[0])
            if not (typ in TIME_CURVES or typ.startswith("animBlendNode")):
                continue
            n, a = dst.split(":")[-1].split(".", 1)
            for ch in COMPOUND.get(a, (a,)):
                out.add(n + "." + ch)
    return out


def _static_ctrl_plugs(ns, skip):
    """Keyable channels of the controls (transforms with a NURBS-curve shape) in `ns` that have no animation, e.g. a
    Gun_Ctrl that was posed without a key: they can differ from the current scene too."""
    out = set()
    for node in cmds.ls(ns + ":*", type="transform") or []:
        if not cmds.listRelatives(node, shapes=True, type="nurbsCurve"):
            continue
        short = node.split(":")[-1]
        for a in cmds.listAttr(node, keyable=True, scalar=True) or []:
            p = short + "." + a
            if p not in skip and not cmds.listConnections(node + "." + a, s=True, d=False):
                out.add(p)
    return out


class _Muted(object):
    """Temporarily mute animation layers (out of the undo queue)."""
    def __init__(self, layers):
        self.layers = [l for l in layers if cmds.objExists(l)]

    def __enter__(self):
        self.state = cmds.undoInfo(q=True, stateWithoutFlush=True)
        cmds.undoInfo(stateWithoutFlush=False)
        self.was = [(l, cmds.animLayer(l, q=True, mute=True)) for l in self.layers]
        for l in self.layers:
            cmds.animLayer(l, e=True, mute=True)

    def __exit__(self, *a):
        for l, m in self.was:
            cmds.animLayer(l, e=True, mute=m)
        cmds.undoInfo(stateWithoutFlush=self.state)


def _scene_layers():
    return [l for l in cmds.ls(type="animLayer") or [] if ":" not in l and cmds.animLayer(l, q=True, parent=True)]


def _src_range(ns):
    t = cmds.keyframe(cmds.ls(ns + ":*", type=TIME_CURVES) or [], q=True, tc=True) or [0]
    return int(round(min(t))), int(round(max(t)))


def scan_source(src, cb=None):
    """What `src` holds compared with the current scene: its animation layers, and the controls whose BASE animation
    differs from the current scene's base (fixes made directly on the base, e.g. Gun_Ctrl, a scapula offset).
    {layers: [...], base: [{ctrl, plugs, max}], range: (start, end)}"""
    src = os.path.abspath(src)
    if not os.path.isfile(src):
        raise RuntimeError(u"找不到來源檔：%s" % src)
    ns = _import_src(src, cb)
    try:
        order = _layer_order(ns)
        layers = [_layer_info(l) for l in order]
        s, e = _src_range(ns)
        step = max(1, (e - s) // 24)
        frames = sorted(set(list(range(s, e + 1, step)) + [e]))
        diffs = {}
        animated = _anim_plugs(ns)
        with _Muted(order + _scene_layers()):
            for p in sorted(animated | _static_ctrl_plugs(ns, animated)):
                node, attr = p.split(".", 1)
                if not cmds.objExists(node) or not cmds.attributeQuery(attr, node=node, exists=True):
                    continue
                try:
                    d = max(abs(cmds.getAttr(ns + ":" + p, time=f) - cmds.getAttr(p, time=f)) for f in frames)
                except Exception:
                    continue
                if d > 0.01:
                    c = diffs.setdefault(node, {"ctrl": node, "plugs": [], "max": 0.0})
                    c["plugs"].append(p)
                    c["max"] = max(c["max"], d)
        base = sorted(diffs.values(), key=lambda c: -c["max"])
        return {"layers": layers, "base": base, "range": (s, e)}
    finally:
        _drop_ns(ns, cb)


def _copy_base_fixes(ns, src_layers, plugs, base, name, cb=None):
    """Override layer `name` holding the SOURCE base animation of `plugs` (one key per frame of the source range)."""
    plugs = [p for p in plugs if _free(p) and cmds.objExists(ns + ":" + p.split(".")[0])]
    if not plugs:
        return None
    s, e = _src_range(ns)
    vals = {}
    with _Muted(src_layers):
        for p in plugs:
            vals[p] = [(f, cmds.getAttr(ns + ":" + p, time=f)) for f in range(s, e + 1)]
    layer = _unique_layer(name)
    if base:
        cmds.animLayer(layer, override=True, parent=base)
    else:
        cmds.animLayer(layer, override=True)
    cmds.animLayer(layer, e=True, attribute=plugs)
    for p, kv in vals.items():
        if all(abs(v - kv[0][1]) < 1e-6 for _, v in kv):        # constant (e.g. posed without keys): one key
            kv = kv[:1]
        for f, v in kv:
            cmds.setKeyframe(p, animLayer=layer, time=f, value=v)
    log(cb, u"Base 上的修改 → Override Layer「%s」（%d 個控制器、%d 條曲線，影格 %d-%d）" % (
        layer, len({p.split(".")[0] for p in plugs}), len(plugs), s, e))
    return layer


def list_layers(src, cb=None):
    """Animation layers saved in `src` (bottom -> top): [{name, override, weight, mute, attrs, range}]."""
    src = os.path.abspath(src)
    if not os.path.isfile(src):
        raise RuntimeError(u"找不到來源檔：%s" % src)
    ns = _import_src(src, cb)
    try:
        return [_layer_info(l) for l in _layer_order(ns)]
    finally:
        _drop_ns(ns, cb)


def copy_layers(src, names, parts=None, others=True, cb=None, base_plugs=None):
    """Copy the animation layers `names` of `src` onto the current scene AS LAYERS (same mode, weight, rotation
    accumulation, keys), on top of the existing ones, keeping their order. Only plugs of the chosen body parts
    (parts=None: all). The base animation of the current scene is not touched."""
    if not core.is_as_rig():
        raise RuntimeError(u"目前場景不是 AdvancedSkeleton 的 rig（找不到 DeformationSystem / RootX_M）")
    src = os.path.abspath(src)
    if not names and not base_plugs:
        raise RuntimeError(u"沒有選任何 Anim Layer 或 Base 修改")
    if parts is not None:
        parts = set(parts)
        if not parts:
            raise RuntimeError(u"沒有選任何部位")
    rig_bones = set(pickable_bones())
    base = _scene_base_layer()
    log(cb, u"讀取來源：%s" % os.path.basename(src))
    ns = _import_src(src, cb)
    done = []
    try:
        names = names or []
        order = [l for l in _layer_order(ns) if l.split(":")[-1] in names]
        # base fixes first: an Override layer BELOW the copied (additive) layers, so their offsets still add on top
        if base_plugs:
            fix = _copy_base_fixes(ns, _layer_order(ns), base_plugs, base,
                                   "BaseFix_" + re.sub(r"[^A-Za-z0-9_]", "_", os.path.splitext(os.path.basename(src))[0]), cb)
            if fix:
                done.append({"layer": fix, "source": "base", "curves": len(base_plugs)})
        missing = set(names) - {l.split(":")[-1] for l in order}
        if missing:
            raise RuntimeError(u"來源檔找不到這些 layer：%s" % ", ".join(sorted(missing)))
        for l in order:
            info = _layer_info(l)
            plugs = []
            skipped, nocurve = [], []
            for p in cmds.animLayer(l, q=True, attribute=True) or []:
                dst = p.split(":")[-1] if ":" in p else p
                ctrl = dst.split(".")[0]
                if parts is not None:
                    bones = control_bones(ctrl, rig_bones)
                    if (bones is None and not others) or (bones is not None and not (bones & parts)):
                        continue
                if not _free(dst):
                    skipped.append(dst)
                    continue
                c = cmds.animLayer(l, q=True, findCurveForPlug=p) or []
                if not c:
                    nocurve.append((p, dst))
                    continue
                plugs.append((dst, c[0]))
            statics = _static_offsets(l, nocurve) if not info["override"] else []
            if not plugs and not statics:
                log(cb, u"略過「%s」：選的部位在這層沒有 key" % info["name"])
                continue
            new = _unique_layer(info["name"])
            if base:
                cmds.animLayer(new, override=info["override"], parent=base)
            else:
                cmds.animLayer(new, override=info["override"])
            for a in ("rotationAccumulationMode", "scaleAccumulationMode"):
                try:
                    cmds.setAttr(new + "." + a, cmds.getAttr(l + "." + a))
                except Exception:
                    pass
            cmds.animLayer(new, e=True, attribute=[d for d, _ in plugs] + [d for d, _ in statics])
            for d, c in plugs:
                cmds.copyKey(c)
                cmds.pasteKey(d, animLayer=new, option="replaceCompletely")
                _copy_curve_settings(c, d, new)
            for d, val in statics:                 # layer offsets that were set without a key: one key holds them
                cmds.setKeyframe(d, animLayer=new, value=val, time=cmds.currentTime(q=True))
            cmds.animLayer(new, e=True, weight=info["weight"])
            if info["mute"]:
                cmds.animLayer(new, e=True, mute=True)
            done.append({"layer": new, "source": info["name"], "curves": len(plugs),
                         "controls": len({d.split(".")[0] for d, _ in plugs}), "override": info["override"],
                         "range": info["range"]})
            log(cb, u"搬好「%s」→ Layer「%s」（%s，權重 %.2f，%d 個控制器、%d 條曲線%s）" % (
                info["name"], new, u"Override" if info["override"] else u"Additive", info["weight"],
                done[-1]["controls"], len(plugs), (u"，影格 %g-%g" % info["range"]) if info["range"] else ""))
            if skipped:
                log(cb, u"    略過（目前場景鎖住或被其他東西控制）：%s" % ", ".join(skipped[:15]))
            if statics:
                log(cb, u"    另外 %d 個屬性在這層只有固定偏移（沒打 key），已用一個 key 搬過來" % len(statics))
    finally:
        _drop_ns(ns, cb)
    if not done:
        raise RuntimeError(u"沒有搬到任何東西（選的部位在這些 layer 裡都沒有 key）")
    return done


def _copy_curve_settings(src_curve, plug, layer):
    """pasteKey keeps keys/tangents; also carry the curve's infinity and weighted-tangent setting."""
    try:
        dst = cmds.animLayer(layer, q=True, findCurveForPlug=plug) or []
        for d in dst:
            cmds.setAttr(d + ".preInfinity", cmds.getAttr(src_curve + ".preInfinity"))
            cmds.setAttr(d + ".postInfinity", cmds.getAttr(src_curve + ".postInfinity"))
    except Exception:
        pass
