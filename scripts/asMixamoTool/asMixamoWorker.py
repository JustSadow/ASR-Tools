# -*- coding: utf-8 -*-
"""Background worker, run by mayapy:  mayapy asMixamoWorker.py <job.json>
Prints one line per event:  @@{"type": ..., ...}  (the window reads these)."""
import json
import os
import sys
import traceback

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)


def emit(**kw):
    sys.stdout.write("@@" + json.dumps(kw, ensure_ascii=False) + "\n")
    sys.stdout.flush()


def main():
    job = json.load(open(sys.argv[1], encoding="utf-8"))
    if job["mode"] == "gif":   # no Maya needed: numpy + Qt image loading only
        import shutil
        import asMixamoGif as gif
        try:
            emit(type="log", msg=u"轉 GIF（%d 格，%s fps）…" % (len(job["pngs"]), job["fps"]))
            r = gif.pngs_to_gif(job["pngs"], job["out"], job["fps"],
                                progress=lambda n, t: emit(type="progress", n=n, total=t))
            emit(type="gif", ok=True, path=job["out"], size=os.path.getsize(job["out"]), frames=r["frames"])
        except Exception as e:
            emit(type="gif", ok=False, error=str(e))
            emit(type="log", msg=traceback.format_exc())
        if job.get("cleanup"):
            shutil.rmtree(job["cleanup"], ignore_errors=True)
        emit(type="finished")
        return
    emit(type="log", msg=u"啟動 Maya（背景）...")
    import maya.standalone
    maya.standalone.initialize(name="python")
    import asMixamoCore as core

    def cb(msg):
        emit(type="log", msg=msg)

    if job["mode"] == "convert":
        emit(type="log", msg=u"轉換 " + job["src"])
        try:
            r = core.convert_rig_fbx(job["src"], job["dst"], fix_fingers=job.get("fixFingers", True), cb=cb)
            emit(type="convert", ok=r["ok"], problems=r["problems"], dst=job["dst"])
        except Exception as e:
            emit(type="convert", ok=False, problems=[str(e)], dst=job["dst"])
            emit(type="log", msg=traceback.format_exc())

    elif job["mode"] == "gun":
        import asMixamoGun as gun
        items = job["items"]
        for i, it in enumerate(items):
            emit(type="item", index=i, state="running")
            if os.path.exists(it["out"]) and not job.get("overwrite"):
                emit(type="item", index=i, state="skipped", msg=u"已存在，略過")
                continue
            emit(type="log", msg=u"[%d/%d] %s" % (i + 1, len(items), os.path.basename(it["rig"])))
            try:
                r = gun.add_gun_to_rig(it["rig"], it["out"], job["ref"], frame=job.get("frame", 30),
                                       model=job.get("model") or None, autoscale=job.get("autoscale", True), cb=cb)
                emit(type="item", index=i, state="done", msg=u"槍長約 %.0f cm → %s" % (r["length"], os.path.basename(r["out"])))
            except Exception as e:
                emit(type="item", index=i, state="error", msg=str(e))
                emit(type="log", msg=traceback.format_exc())

    elif job["mode"] == "weights":
        import asMixamoWeights as wt
        items = job["items"]
        try:
            data = wt.read_file(job["rig"], cb=cb)
        except Exception as e:
            data = None
            emit(type="log", msg=traceback.format_exc())
            for i in range(len(items)):
                emit(type="item", index=i, state="error", msg=u"讀不到 rig 的權重：%s" % e)
        for i, it in enumerate(items if data else []):
            emit(type="item", index=i, state="running")
            if not job.get("overwrite") and os.path.exists(it["out"]):
                emit(type="item", index=i, state="skipped", msg=u"輸出檔已存在，略過")
                continue
            emit(type="log", msg=u"[%d/%d] %s" % (i + 1, len(items), os.path.basename(it["src"])))
            try:
                r = wt.swap_file(it["src"], it["out"], data, overwrite=job.get("overwrite", False), cb=cb)
                msg = u"換了 %d 個模型" % len(r["done"])
                added = sorted({a for d in r["done"] for a in d["added"]})
                if added:
                    msg += u"，補上骨頭 %s" % ", ".join(added)
                if r["skipped"]:
                    msg += u"，略過 %s" % ", ".join(x[0] for x in r["skipped"])
                msg += u"；動作沒變（%d 個 key）" % r["keys"]
                if r.get("backup"):
                    msg += u"，原檔備份在 _weights_backup"
                emit(type="item", index=i, state="done", msg=msg)
            except Exception as e:
                emit(type="item", index=i, state="error", msg=str(e))
                emit(type="log", msg=traceback.format_exc())

    elif job["mode"] == "export":
        import asMixamoExport as ex
        try:
            r = ex.export_rig_fbx(job["scene"], job["out"], anim=job.get("anim", True), gun=job.get("gun", True),
                                  start=job.get("start"), end=job.get("end"), cb=cb, weapon=job.get("weapon", True))
            msg = u"%d 根骨頭、模型 %s" % (r["joints"], u"、".join(r["meshes"]))
            msg += (u"、動畫 %d-%d" % r["range"]) if r["anim"] else u"、不含動畫（bind pose）"
            msg += u"、含槍" if r["gun"] else ""
            msg += u"、含武器" if r["weapon"] else ""
            emit(type="export", ok=True, out=r["out"], msg=msg, size=r["size"])
        except Exception as e:
            emit(type="export", ok=False, msg=str(e))
            emit(type="log", msg=traceback.format_exc())
        finally:
            try:
                os.remove(job["scene"])
            except OSError:
                pass

    elif job["mode"] == "batch":
        items = job["items"]
        for i, it in enumerate(items):
            emit(type="item", index=i, state="running")
            if os.path.exists(it["out"]) and not job.get("overwrite"):
                emit(type="item", index=i, state="skipped", msg=u"已存在，略過")
                continue
            emit(type="log", msg=u"[%d/%d] %s -> %s" % (i + 1, len(items), os.path.basename(it["fbx"]), os.path.basename(it["out"])))
            try:
                r = core.retarget_motion(job["rig"], it["fbx"], it["out"], reduce=job.get("reduce", True),
                                         precision=job.get("precision", 3.0), precision_mode=1,
                                         euler=job.get("euler", True), cb=cb,
                                         source=job.get("source", "auto"),
                                         in_place=job.get("inPlace", False),
                                         two_hand=job.get("twoHand", False),
                                         parts=job.get("parts"))
                msg = u"影格 %d-%d，連上 %d 根" % (r["start"], r["end"], r["connected"])
                msg = u"%s，" % r.get("sourceLabel", "") + (u"比例 x%.3f，" % r["scale"] if r.get("standard") else u"") + msg
                if job.get("reduce", True):
                    msg += u"，key %d→%d" % (r["keysBefore"], r["keysAfter"])
                if r["missing"]:
                    msg += u"，動作檔缺 %s" % ", ".join(r["missing"])
                emit(type="item", index=i, state="done", msg=msg)
            except Exception as e:
                emit(type="item", index=i, state="error", msg=str(e))
                emit(type="log", msg=traceback.format_exc())
    emit(type="finished")
    maya.standalone.uninitialize()


if __name__ == "__main__":
    main()
