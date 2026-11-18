# -*- coding: utf-8 -*-
"""權重轉移 Weight Transfer (Maya 2022+)

把「來源」(模型或選取的面) 的 skin 權重，依位置轉移到「目標」(模型或選取的面)。
來源與目標可以是不同模型，也可以是同一個模型的不同部位 (例如披風外層 -> 內層)。

安裝：把本檔放到 文件\\maya\\<版本>\\scripts\\ ，工具架按鈕指令：
    import weightTransfer; weightTransfer.show()

用法：
  快速：先選來源 (模型或面)，再 Shift 加選目標模型 (或目標的面)，按「一鍵轉移」。
  同一個模型的兩個部位：選來源的面按「設定來源」，選目標的面按「設定目標」，再按「一鍵轉移」。
整次轉移可以用一次 Ctrl+Z 復原。
"""
__version__ = "1.0.0"

import re
import maya.cmds as cmds
import maya.api.OpenMaya as om
import maya.api.OpenMayaAnim as oma

WIN = "weightTransferWin"
_state = {"source": None, "target": None}
_ui = {}


# ---------------------------------------------------------------- helpers
def _transform_of(node):
    if cmds.nodeType(node) == "mesh":
        node = cmds.listRelatives(node, parent=True, fullPath=True)[0]
    node = cmds.ls(node, long=True)[0]
    shapes = cmds.listRelatives(node, shapes=True, noIntermediate=True, type="mesh", fullPath=True)
    return node if shapes else None


def _parse_selection(items):
    """-> ordered list of (transform, [component strings] or None for whole object)"""
    groups = []
    for it in items:
        tr = _transform_of(it.split(".")[0])
        if tr is None:
            continue
        comp = it.split(".", 1)[1] if "." in it else None
        for g in groups:
            if g[0] == tr:
                if comp is None:
                    g[1] = None
                elif g[1] is not None:
                    g[1].append(comp)
                break
        else:
            groups.append([tr, None if comp is None else [comp]])
    return [tuple(g) for g in groups]


def _indices(tr, comps, kind):
    """kind 'f' or 'vtx': indices of that kind covered by the selection (faces need to be fully selected)."""
    if comps is None:
        n = cmds.polyEvaluate(tr, face=True) if kind == "f" else cmds.polyEvaluate(tr, vertex=True)
        return list(range(n))
    full = ["%s.%s" % (tr, c) for c in comps]
    if kind == "f":
        conv = cmds.polyListComponentConversion(full, toFace=True, internal=True) or []
    else:
        conv = cmds.polyListComponentConversion(full, toVertex=True) or []
    out = set()
    for c in cmds.ls(conv, flatten=True):
        m = re.search(r"\[(\d+)\]$", c)
        if m:
            out.add(int(m.group(1)))
    return sorted(out)


def _skin_of(tr):
    for n in cmds.listHistory(tr, pruneDagObjects=True) or []:
        if cmds.nodeType(n) == "skinCluster":
            return n
    return None


def _dag(tr):
    sel = om.MSelectionList()
    sel.add(tr)
    d = sel.getDagPath(0)
    d.extendToShape()
    return d


def _skin_fn(sc):
    sel = om.MSelectionList()
    sel.add(sc)
    return oma.MFnSkinCluster(sel.getDependNode(0))


def _all_weights(sc, dag):
    fn = _skin_fn(sc)
    comp = om.MFnSingleIndexedComponent()
    co = comp.create(om.MFn.kMeshVertComponent)
    comp.setCompleteData(om.MFnMesh(dag).numVertices)
    w, ni = fn.getWeights(dag, co)
    infs = [p.fullPathName() for p in fn.influenceObjects()]
    return w, ni, infs


def _describe(sel):
    tr, comps = sel
    short = tr.split("|")[-1]
    if comps is None:
        return u"%s（整個模型）" % short
    return u"%s：%d 個面 / %d 個頂點" % (short, len(_indices(tr, comps, "f")), len(_indices(tr, comps, "vtx")))


def _bary(p, a, b, c):
    v0, v1, v2 = b - a, c - a, p - a
    d00, d01, d11 = v0 * v0, v0 * v1, v1 * v1
    d20, d21 = v2 * v0, v2 * v1
    den = d00 * d11 - d01 * d01
    if abs(den) < 1e-12:
        return (1.0, 0.0, 0.0)
    v = (d11 * d20 - d01 * d21) / den
    w = (d00 * d21 - d01 * d20) / den
    u = 1.0 - v - w
    bc = [max(0.0, x) for x in (u, v, w)]
    s = sum(bc) or 1.0
    return tuple(x / s for x in bc)


# ---------------------------------------------------------------- core
def transfer(source, target, mode="interp", auto_bind=True):
    """source / target: (transform, [components] or None). mode: 'interp' | 'nearest'.
    Returns a short report string."""
    src_tr, src_comps = source
    tgt_tr, tgt_comps = target
    src_sc = _skin_of(src_tr)
    if not src_sc:
        raise RuntimeError(u"來源 %s 沒有綁 skin" % src_tr.split("|")[-1])
    src_dag = _dag(src_tr)
    sw, sni, src_infs = _all_weights(src_sc, src_dag)

    # --- source triangles -> in-memory mesh for closest-point queries
    src_fn = om.MFnMesh(src_dag)
    spts = src_fn.getPoints(om.MSpace.kWorld)
    faces = set(_indices(src_tr, src_comps, "f"))
    tri_counts, tri_verts = src_fn.getTriangles()
    tris, k = [], 0
    for f, cnt in enumerate(tri_counts):
        for t in range(cnt):
            if f in faces:
                tris.append((tri_verts[k], tri_verts[k + 1], tri_verts[k + 2]))
            k += 3
    src_vtx = _indices(src_tr, src_comps, "vtx")
    if not tris and not src_vtx:
        raise RuntimeError(u"來源沒有選到任何面或頂點")

    inter = None
    if tris:
        uniq = sorted({v for t in tris for v in t})
        loc = {v: i for i, v in enumerate(uniq)}
        data = om.MFnMeshData().create()
        om.MFnMesh().create([spts[v] for v in uniq], [3] * len(tris),
                            [loc[v] for t in tris for v in t], parent=data)
        inter = om.MMeshIntersector()
        inter.create(data, om.MMatrix())

    # --- target skin (bind if needed) and influences
    tgt_sc = _skin_of(tgt_tr)
    if not tgt_sc:
        if not auto_bind:
            raise RuntimeError(u"目標 %s 沒有綁 skin" % tgt_tr.split("|")[-1])
        tgt_sc = cmds.skinCluster(src_infs, tgt_tr, toSelectedBones=True, normalizeWeights=1,
                                  maximumInfluences=cmds.getAttr(src_sc + ".maxInfluences"),
                                  name=tgt_tr.split("|")[-1] + "_skinCluster")[0]
    tgt_infs = [cmds.ls(i, long=True)[0] for i in cmds.skinCluster(tgt_sc, q=True, influence=True)]
    added = []
    for j in src_infs:
        if j not in tgt_infs:
            cmds.skinCluster(tgt_sc, e=True, addInfluence=j, lockWeights=True, weight=0)
            added.append(j)

    tgt_dag = _dag(tgt_tr)
    tpts = om.MFnMesh(tgt_dag).getPoints(om.MSpace.kWorld)
    tw, tni, tgt_infs = _all_weights(tgt_sc, tgt_dag)
    tidx = {j: i for i, j in enumerate(tgt_infs)}
    tgt_vtx = _indices(tgt_tr, tgt_comps, "vtx")
    same_mesh = src_tr == tgt_tr

    # --- exact-position matches: when source vertices sit exactly where the target vertex is (e.g. a duplicate,
    # or a cape edge welded onto the body), pick the one whose normal agrees, instead of an arbitrary triangle.
    EPS = 1e-3
    snrm = src_fn.getVertexNormals(False, om.MSpace.kWorld)
    tnrm = om.MFnMesh(tgt_dag).getVertexNormals(False, om.MSpace.kWorld)
    grid = {}
    for s in src_vtx:
        q = spts[s]
        grid.setdefault((int(round(q.x / EPS)), int(round(q.y / EPS)), int(round(q.z / EPS))), []).append(s)

    def _exact(p, n):
        kx, ky, kz = int(round(p.x / EPS)), int(round(p.y / EPS)), int(round(p.z / EPS))
        cands = [s for dx in (-1, 0, 1) for dy in (-1, 0, 1) for dz in (-1, 0, 1)
                 for s in grid.get((kx + dx, ky + dy, kz + dz), ()) if (spts[s] - p).length() < EPS]
        if not cands:
            return None
        return max(cands, key=lambda s: om.MVector(snrm[s]) * om.MVector(n))

    # --- new weights per target vertex
    new = {}
    maxdist = 0.0
    for v in tgt_vtx:
        p = tpts[v]
        ex = _exact(p, tnrm[v])
        if ex is not None and not (same_mesh and ex == v):
            contrib = [(ex, 1.0)]
        elif inter is not None:
            pom = inter.getClosestPoint(p)
            tri = tris[pom.face]
            cp = om.MPoint(pom.point)
            maxdist = max(maxdist, (cp - p).length())
            bc = _bary(om.MVector(cp), om.MVector(spts[tri[0]]), om.MVector(spts[tri[1]]), om.MVector(spts[tri[2]]))
            if mode == "nearest":
                pick = max(range(3), key=lambda i: bc[i])
                contrib = [(tri[pick], 1.0)]
            else:
                contrib = [(tri[i], bc[i]) for i in range(3) if bc[i] > 1e-9]
        else:
            u = min(src_vtx, key=lambda s: (spts[s] - p).length())
            maxdist = max(maxdist, (spts[u] - p).length())
            contrib = [(u, 1.0)]
        acc = {}
        for sv, f in contrib:
            base = sv * sni
            for i in range(sni):
                x = sw[base + i]
                if x > 1e-7:
                    acc[src_infs[i]] = acc.get(src_infs[i], 0.0) + x * f
        new[v] = acc

    # --- write (one undo chunk)
    cmds.undoInfo(openChunk=True, chunkName="weightTransfer")
    try:
        locks = {j: cmds.getAttr(j + ".liw") for j in tgt_infs if cmds.attributeQuery("liw", node=j, exists=True)}
        for j in locks:
            cmds.setAttr(j + ".liw", 0)
        short_tgt = tgt_tr
        for v, acc in new.items():
            pairs = {}
            base = v * tni
            for i in range(tni):
                if tw[base + i] > 1e-7:
                    pairs[tgt_infs[i]] = 0.0
            s = sum(acc.values()) or 1.0
            for j, x in acc.items():
                pairs[j] = x / s
            cmds.skinPercent(tgt_sc, "%s.vtx[%d]" % (short_tgt, v),
                             transformValue=[(j, x) for j, x in pairs.items()], normalize=True)
        for j, lk in locks.items():
            cmds.setAttr(j + ".liw", 0 if j in added else lk)
    finally:
        cmds.undoInfo(closeChunk=True)

    msg = u"完成：%d 個頂點 從 %s → %s（%s）" % (
        len(new), source[0].split("|")[-1], tgt_tr.split("|")[-1], u"位置內插" if mode == "interp" else u"最近頂點")
    if added:
        msg += u"，目標新增了 %d 根骨頭" % len(added)
    if maxdist > 1.0:
        msg += u"；注意：最遠的點離來源 %.1f 公分，位置可能沒對齊" % maxdist
    return msg


# ---------------------------------------------------------------- UI
def _set(which):
    sel = _parse_selection(cmds.ls(orderedSelection=True) or cmds.ls(selection=True))
    if len(sel) != 1:
        cmds.warning(u"請只選一個模型（或同一個模型的面）")
        return
    _state[which] = sel[0]
    cmds.textField(_ui[which], e=True, text=_describe(sel[0]))


def _clear(*_):
    _state["source"] = _state["target"] = None
    for k in ("source", "target"):
        cmds.textField(_ui[k], e=True, text="")


def _run(*_):
    sel = _parse_selection(cmds.ls(orderedSelection=True) or [])
    if len(sel) == 2:
        src, tgt = sel
    elif _state["source"] and _state["target"]:
        src, tgt = _state["source"], _state["target"]
    else:
        cmds.warning(u"請先選來源、再 Shift 加選目標模型；同一個模型請用「設定來源 / 設定目標」")
        return
    mode = "interp" if cmds.radioButtonGrp(_ui["mode"], q=True, select=True) == 1 else "nearest"
    try:
        msg = transfer(src, tgt, mode, cmds.checkBox(_ui["bind"], q=True, value=True))
    except Exception as e:
        cmds.text(_ui["status"], e=True, label=u"失敗：%s" % e)
        raise
    cmds.text(_ui["status"], e=True, label=msg)
    print(msg)


def add_shelf_button():
    """Adds a button (icon weightTransfer.png from prefs/icons) to the shelf tab that is open now."""
    import maya.mel as mel
    shelf = cmds.tabLayout(mel.eval("$tmp=$gShelfTopLevel"), q=True, selectTab=True)
    cmds.shelfButton(parent=shelf, image="weightTransfer.png", image1="weightTransfer.png",
                     label="WeightTransfer", annotation=u"權重轉移 Weight Transfer",
                     command="import weightTransfer; weightTransfer.show()", sourceType="python")
    print(u"已加到工具架：%s" % shelf)


def show():
    cmds.selectPref(trackSelectionOrder=True)
    if cmds.window(WIN, exists=True):
        cmds.deleteUI(WIN)
    cmds.window(WIN, title=u"權重轉移 Weight Transfer v" + __version__, widthHeight=(430, 300), sizeable=True)
    cmds.columnLayout(adjustableColumn=True, rowSpacing=6, columnAttach=("both", 10))
    cmds.separator(height=6, style="none")
    cmds.text(label=u"快速：先選來源（模型或面），再 Shift 加選目標，按「一鍵轉移」", align="left")
    cmds.text(label=u"同一個模型的兩個部位：用下面兩個按鈕分別設定", align="left")
    cmds.separator(height=8)
    cmds.rowLayout(numberOfColumns=2, adjustableColumn=2, columnWidth2=(90, 300))
    cmds.button(label=u"設定來源", width=85, command=lambda *_: _set("source"))
    _ui["source"] = cmds.textField(editable=False, placeholderText=u"要的權重")
    cmds.setParent("..")
    cmds.rowLayout(numberOfColumns=2, adjustableColumn=2, columnWidth2=(90, 300))
    cmds.button(label=u"設定目標", width=85, command=lambda *_: _set("target"))
    _ui["target"] = cmds.textField(editable=False, placeholderText=u"要被覆蓋的")
    cmds.setParent("..")
    _ui["mode"] = cmds.radioButtonGrp(label=u"方式", labelArray2=[u"位置內插（推薦）", u"最近頂點"],
                                      numberOfRadioButtons=2, select=1, columnWidth3=(40, 140, 100))
    _ui["bind"] = cmds.checkBox(label=u"目標沒綁 skin 時，自動綁到來源的骨頭", value=True)
    cmds.button(label=u"一鍵轉移", height=42, backgroundColor=(0.35, 0.55, 0.35), command=_run)
    cmds.button(label=u"清除設定", height=22, command=_clear)
    _ui["status"] = cmds.text(label=u"", align="left", wordWrap=True)
    cmds.showWindow(WIN)
