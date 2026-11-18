# ASR Tools

ASR = **A**dvanced**S**keleton + **R**etarget。Maya 2025 用的動作套用工具：把 Mixamo、3ds Max Biped、Unreal、Rokoko 等動作庫的 FBX，套到 [AdvancedSkeleton](https://www.animationstudios.com.au) 綁好的角色上。

> 本工具**不包含** AdvancedSkeleton，也不會修改它的任何檔案。套動作不需要安裝 AS；綁骨、改 rig 才需要（商業專案需 AS 的 Studio License）。

## 安裝

1. 到 [Releases](../../releases) 下載最新的 `ASR_Tools_vX.Y.Z.zip`，解壓縮
2. 開 Maya 2025，把 `install.py` **拖到 viewport**
3. 工具架會多三個按鈕：**ASR Tools**、**WeightTransfer**、**BuildPose**

## 更新／退回舊版

- 工具視窗右上角 **版本／更新**：有新版時按鈕會變綠色
- 或在工具架 **ASR Tools** 按鈕上 **按右鍵 → 版本管理／更新**（就算某一版的工具打不開，這裡還是能用）
- 版本清單裡可以看每一版的更新內容，**任何一版都能裝**：裝舊版就是退回
- 每次安裝都會先備份目前的版本（保留最近 5 份，在 `文件\maya\2025\scripts\asMixamoTool_backup_日期時間`）

## 功能

| 分頁 | 用途 |
|---|---|
| Retarget | 把一個動作 FBX 套到目前場景的 AS rig（可只套部分部位） |
| AS Retarget | 把另一個 AS 動作檔的動畫或 Anim Layer 搬到目前場景 |
| 批量 Retarget | 一次把多個動作套到 rig，各自另存新檔（背景處理，Maya 可繼續用） |
| 雙手武器骨架 | 幫 rig 加一把雙手持握的槍（右手持槍、左手 IK 握點、可匯出的武器骨頭） |
| 模型更新 | 把修好權重的 rig 的 skin 權重換進舊的動作檔 |
| 錄影 | 錄 viewport 成 MP4／GIF／PNG |

另有 **Go to Build Pose**（不用裝 AS）與 **WeightTransfer**（權重轉移）。

### 支援的動作來源（全部內建，自動判斷）

Mixamo 預設角色（Y Bot／X Bot）、自己上傳到 Mixamo 的角色、3ds Max Biped（Bip001）、Unreal（pelvis／spine_01）、Rokoko、Character Creator／ActorCore、MotionBuilder（HIK）、DeepMotion、Move AI、Plask、HY-Motion、MotionMaker、iPi Soft。

### 套動作時自動處理

- 依骨架比例對齊 bind pose、縮放移動距離，Q 版（大頭、短腿、寬胯）也能用
- 踩地時腳是平的（IK 腳控制器 rotateX/Z = 0）；腳趾只繞 Z 彎、不超過 ±90°
- 骨盆有兩層、零姿勢側躺、骨頭扭轉反向的骨架（常見於 3ds Max 匯出）會自動修正
- 動作範圍只看骨架的 key；套用時自動關閉 Auto Key，結束後恢復
- 失敗時不會在場景留下匯入的骨架

## 需求

- Maya 2025（PySide6）、Windows
- 角色用 AdvancedSkeleton 綁定（控制器命名 `RootX_M`、`FK*`、`IK*`、`Pole*`）

## 注意

- 「雙手武器骨架」需要一個開槍／瞄準動作當參考姿勢，例如 Mixamo 免費的 **Firing Rifle**。Mixamo 的動作檔不能隨工具散佈，請自己下載一次，在工具裡選它（會記住）
- 動作庫的授權請自行確認是否可商用

詳細流程見 [docs/工作流程.md](docs/工作流程.md)。
