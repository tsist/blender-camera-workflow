---
name: blender-camera-workflow
description: 排定全片镜头表、架设机位焦段与构图、编排运镜焦点、组织候选 A/B 实体分镜预演并完成剪辑切点协同。接到叙事、动作、产品展示、建筑漫游或二维三维虚拟摄影的镜头设计与交付任务时使用。
metadata:
  version: "1.0.0"
---

# 镜头与相机工作流

本技能管排定全片镜头表、架设机位焦段与运镜焦点、做构图诊断和候选 A/B 比较，并在实体视口连续播放分镜预演。归属[镜头与灯光部门](https://github.com/tsist/blender-ai-workflow/blob/main/skills/blender-work-methodology/references/departments/camera-lighting.md)；跨部门排期看[项目协作方法](https://github.com/tsist/blender-ai-workflow/blob/main/skills/blender-work-methodology/SKILL.md)，命令行与副本规范看[Blender CLI 手册](https://github.com/tsist/blenderctl/blob/main/skills/blender-cli/SKILL.md)。

## 怎么做

### 第一步：读清场景参数与观看任务

先在独立工作副本上读取场景的实际帧率（`fps / fps_base`）、单位、画幅比例、已有相机与主体位置。保留已有场景设置；新建空白示例时按 24fps、16:9 起步。

再写清这一镜的观看任务：观众要读清什么、谁在看、关键事件落在哪一帧、落幅交给下一镜什么状态。把世界方向、人物自身左右和画面左右分开记，把相机位移和演员走位分开规划。有重大构图取舍时给两三个可同条件对比的方向；方向已定直接推进。设计卡与方案比较表见[导演决策与镜头设计](references/director-and-shot-design.md)。

动手前先查当前可用入口与参数：

```powershell
$ctl = './blenderctl.ps1'
& $ctl discover --product camera
& $ctl camera shot-table --help
& $ctl camera copy --help
& $ctl camera session-live --help
```

### 第二步：立好镜头表主档

镜头表是全片时间主档，记清镜头编号、绑定相机与起止帧。先只读摸清表结构，再新增、换机位或调切点：

```powershell
# UTF-8 参数 JSON 含 file、expected_sha256、scene、operation
& $ctl --jobs-dir $jobs camera shot-table --params $inspectJson
```

1. **读表查资格**：从回执读出 `data.table.rows`、`source_mode`、`table_sha256` 与 `downstream_eligible`。出现缺相机、重名、帧段重叠或断档时，先把草稿修通再交下游。
2. **改字段写新副本**：新增用 `add`，删改用 `remove`、`rename`、`camera`、`first`、`last`，附 `--output` 指向新 `.blend`，源工程留着对照。
3. **调切点用原子移动**：调相邻两镜切点时走 `move-cut`，一次提交左右两镜的完整预期行与后镜新首帧 `frame`，两行自动严丝合缝。
4. **切到序列模式再导出**：需要交给剪辑或做 A/B 比较时，先用 `source-mode` 切到 `SEQUENCE`，再跑 `export-candidate` 导出源绑定候选 JSON。

### 第三步：架机位、定焦段与构图诊断

把相机、演员、道具、固定光源和背景地标摆在同一张场景平面图上走台，逐一核对起幅、最大动作伸展帧、遮挡峰值帧和落幅，确保关键接触全程可读。

1. **核对相机独占与依赖**：改机位前先查 Camera Object 与 Camera Data 的共享引用、父级、约束、路径、驱动、NLA 与景深目标。单改一台镜头相机时先独立出独占数据块。
2. **静态机位与焦距改副本**：运行 `camera copy --operation check --params $reqJson` 到新作业目录，核对摘要后带同一作业目录和 `check_sha` 执行 `apply` 写出副本，再用 `result` 核对终稿并独立重开。
3. **构图诊断与建议回送**：运行 `camera copy --operation diagnose`，核对主体中心、占比、视线留白与允许遮挡项。报告给出可行建议时，用 `camera framing-check` 直接送入同版 `check`，审核通过再 `apply`。
4. **分清距离与焦距**：改远近透视靠移机，改取景宽窄靠调焦距与画幅。同构图联合调整时同时记录两项变量。运动几何与 34 项方法见[运动几何与术语速查](references/motion-geometry.md)。

### 第四步：编排运镜、焦点与摄影组改时

先读演员动作的刺激帧、反应帧和峰值帧，再定相机起止时刻与景深落点。

- **六类原生保存编辑**：通过 `camera copy` 的 `check` → `apply` → `result` 事务，依次支持静态焦距与局部偏移、相邻切点、对骨骼拉焦、运镜缓动、焦点改时与摄影组整体改时，凭 `check_sha` 与 `terminal_sha` 追踪回执。
- **区分缓动与路径准备**：运镜缓动调已有合格位置曲线的起停节奏；新建轨迹、改启动帧或做推拉变焦时，先在原生工作副本备好曲线，再接续缓动或焦点事务。
- **分清跟焦与拉焦**：持续跟同一主体靠跟焦，注意力转交靠拉焦；两人同需看清时直接放大景深范围。
- **摄影时长与表演分开**：挪切点或给摄影组改时，先确认演员动作是否同步改；连带调表演节拍交给动画部门走事件改时。

### 第五步：组织候选 A/B 与现场实体预演

构图或切点有取舍时，在同源工程上产出 A/B 候选，在同画幅、同帧段、同显示模式下直接对比。

1. **生成与审查候选表**：从 `SEQUENCE` 模式源工程跑 `export-candidate`，用独立镜头表脚本生成切点或换机位候选 JSON，再跑 `review-candidate` 核对变更行。
2. **附接现场窗口实体预演**：在打开的工作副本窗口附接会话，用 `camera session-live` 驱动真实 View3D：
   - 跑 `status` 取 `area_id`、`expected_context`、候选状态与租约 ID。
   - 跑 `load` 载入同源候选表，在关键帧用 `compare` 切换 A/B，用 `play` 或 `start` 按实体模式（`SOLID`）连续播放全段或单镜。
   - 播完依次跑 `stop`、`restore`、`release`、`clear` 还原视口与时间线。
3. **采用候选并冷重开**：选定胜出方案后，跑 `camera shot-table` 的 `adopt-candidate` 写出新 `.blend` 与验证基线，另起进程冷重开核对机位、镜头表与外部依赖。命令细节见[CLI 操作、镜头表与现场预演](references/cli-and-shot-table.md)。

### 第六步：三遍审看与切点协同

审看按三遍走：第一遍原速通看全段，判断视线引导、方向与节奏；第二遍停在问题窗口逐帧查遮挡、出框、穿模、脱焦与顿挫；第三遍放回前后镜头原速复看，核对动作相位、余势与眼线承接。完整排查表见[连续性、可读性与审看排查](references/continuity-and-review.md)；题材与媒介转译见[题材、媒介与支撑特征](references/contexts-and-media.md)。

## 交给下游

把下面四样交齐给下游部门（灯光、批渲染或剪辑）和用户审看：

1. **镜头表主档**：含稳定镜头编号、绑定相机、起止帧、焦段、来源模式与切点版本，`downstream_eligible` 为真。
2. **冷重开验证过的副本**：提供新 `.blend` 绝对路径、小写 SHA256 与回执路径，源工程保持完好。
3. **实体分镜预演与对照图**：单镜头委托交实体连续预演供用户审看①拍板；多镜成片交剪辑拼粗剪。有 A/B 取舍时附同帧同条件对照图。
4. **有效出口与待验清单**：写清末帧人物状态、运动趋势与下镜接点；实体预览阶段把材质高光、最终景深与渲染模糊列为灯光与渲染待验项。

下游先核工程 SHA 与 `camera shot-table` 的 `inspect` 回执，再按表布光、批渲染或在剪辑线原位换片。剪辑要改时长或切点时，先回本环节更新镜头表主档再同步下游。

## 例子：双人对白四镜头的切点优化与 A/B 预演

接到委托：「给 12 秒（288 帧、24fps）双人对白定四镜头表，乙反应镜提前半秒切入，做 A/B 预演给用户拍板后交灯光与剪辑。」

1. **摸清源表**：建 `work/audit/<batch>/`，算源工程 SHA256，跑 `camera shot-table` 的 `inspect` 读出四镜与 109/144 帧切点，确认 `source_mode` 为 `SEQUENCE` 且表资格通过。
2. **构图诊断与局部修正**：对乙反应机位跑 `camera copy --operation diagnose`，发现前景甲肩部略挡乙手势。用 `camera framing-check` 送入同版 `check`，确认无冲突后 `apply` 生成副本并冷重开核对留白。
3. **生成切点候选**：从新副本跑 `export-candidate` 导出基线 JSON，把甲说到乙反应的切点从 144 帧前移至 132 帧（总长仍 288 帧），跑 `review-candidate` 核对变更只落相邻两行。
4. **现场 A/B 实体预演**：在打开的工作副本窗口附接会话，跑 `camera session-live` 的 `status` 后 `load` 候选；第 138 帧 `compare` 对照 A/B，再分别 `play` 1–288 帧实体预演录制对照，确认 132 帧切入让听者反应更清楚。完成后 `restore` 并 `release`。
5. **采用候选并交接**：用户选定 B 方案。跑 `adopt-candidate --output work/dialogue/cam-final.blend` 落地正式副本并冷重开核验，把副本路径、SHA256、基线 JSON 和预演视频交给灯光部门与剪辑部门。

## 参考

- [CLI 操作、镜头表与现场预演](references/cli-and-shot-table.md)
- [导演决策与镜头设计](references/director-and-shot-design.md)
- [运动几何与术语速查](references/motion-geometry.md)
- [连续性、可读性与审看排查](references/continuity-and-review.md)
- [题材、媒介与支撑特征](references/contexts-and-media.md)
- [来源与证据追溯](references/sources.md)
