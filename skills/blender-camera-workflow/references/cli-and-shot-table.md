# CLI 操作、镜头表与现场预演

本页整理相机工作流的命令行入口、镜头表读写、保存副本事务、现场视口预演和剪辑切点交接做法。动手前先运行 `discover --product camera` 确认当前宿主的精确子命令与参数说明。

## 一、先查目录再开工

新建批次目录存放 `jobs` 与参数 JSON，计算已保存源工程的小写 SHA256，全程在独立工作副本上操作，源工程留着对照。

```powershell
$ctl = './blenderctl.ps1'
& $ctl discover --product camera
& $ctl camera shot-table --help
& $ctl camera copy --help
& $ctl camera framing-check --help
& $ctl camera session-live --help
```

后台命令读取的是磁盘上已经保存的 `.blend`。窗口里刚做完的手调，先保存或通过现场交接入口落盘，再计算新 SHA256 往下传。每次新请求建独立作业目录，拿到终态回执后再进入下一步。

## 二、读写镜头表主档（`camera shot-table`）

镜头表是全片的时间主档，记录镜头编号、绑定相机、包含在镜头内的首帧和末帧以及来源模式（`SCENE` 或 `SEQUENCE`）。参数全部写进 UTF-8 JSON，必带 `file`、`expected_sha256`、`scene` 和 `operation`。只读操作省略 `--output`，写入操作附带 `--output NEW.blend` 输出新副本。

| `operation` | 额外字段 | 作用与注意事项 |
|---|---|---|
| `inspect` | 无 | 读取 `data.table.rows`、`source_mode`、`table_sha256` 与 `qualification.downstream_eligible`。目标场景可以是保存时的非活动场景。 |
| `add` | 无 | 按原生面板规则追加占位镜头，附 `--output` 生成新副本。 |
| `remove` | `shot`、`expected`（含 `name, camera, first, last`） | 按完整预期行删除目标镜头，防止误删错行。 |
| `rename` / `camera` / `first` / `last` | `shot`、`expected`、`value` | 修改单个字段。把回执里读出的完整行原样填入 `expected` 作锁行核验。 |
| `move-cut` | `left`、`right`、`expected_left`、`expected_right`、`frame` | 原子移动相邻两镜的切点。`frame` 填后镜新首帧，前镜末帧自动收在 `frame - 1`。 |
| `source-mode` | `expected`、`value`（均为 `SCENE` 或 `SEQUENCE`） | 切换相机来源模式，导出候选前先切到 `SEQUENCE`。 |
| `export-candidate` | 无 | 在 `SEQUENCE` 模式且表资格通过时，导出绑定源 SHA 的 `artifacts.table_candidate` JSON。 |
| `review-candidate` | `candidate: {file, expected_sha256}` | 在同源 `.blend` 上比对候选表与原表的逐行差异与涉及机位，只读返回摘要。 |
| `adopt-candidate` | `candidate: {file, expected_sha256}` | 将已选候选落盘为新 `.blend`（附 `--output`），并同步导出新副本的验证基线 JSON。 |

发现 `downstream_eligible` 为假（例如缺机位、重名、帧段重叠或断档）时，按 `reason` 逐项修通草稿再交下游。

## 三、保存副本的六类原生编辑（`camera copy` 与 `framing-check`）

对已保存工程做机位、焦距、焦点、缓动或摄影组改时，统一走 `check` → `apply` → `result` 三段事务。`check` 只做预检与资格核对，确认回执里的摘要与预期变化后，再用同一作业目录和 `check_sha` 执行 `apply` 写出新副本，最后用 `result` 核对终稿并独立冷重开。

### 六类请求版本

| 请求版本 | 覆盖操作 | 保护与前置条件 |
|---|---|---|
| 版本 1 | 静态焦距与局部坐标偏移 | 目标相机与 Camera Data 独占，无动画、驱动、NLA、父级约束或景深依赖；静态属性作用于该相机覆盖的全部帧。 |
| 版本 2 | 相邻切点调整 | 只改相邻两行边界，其余镜头与演员时间保持原样。 |
| 版本 3 | 对指定骨骼拉焦 | 明确指定目标骨架与骨骼，保持绑定位姿与网格求值一致。 |
| 版本 4 | 运镜缓动 | 作用于已有合格两端位置曲线的整数共同区间与独占 Action，调整起停缓动形态。 |
| 版本 5 | 焦点改时 | 调整已有焦点助手关键帧的转交起点，新起点落在锁定起点与到达帧之间。 |
| 版本 6 | 摄影组整体改时 | 以半开区间重映射摄影集合及点名相机动作与标记，演员表演与场景资产保留原场景时间。 |

### 构图诊断与建议回送

1. **运行构图诊断**：调用 `camera copy --operation diagnose --params $reqJson`（传入 `{request, job}`），显式列出采样帧、主体网格、画面中心、占比、视线留白、轴线例外和允许遮挡项。
2. **回送可行建议**：诊断报告给出调整建议后，用 `camera framing-check --params $pJson --evidence-dir $eDir`（或 `camera copy --operation framing-check`）传入 `{report: {file, sha256}, case, job}`，直接把建议送入同版 `check`。
3. **核对后提交或取消**：审核 `READY` 摘要后，用同一 `job` 与 `check_sha` 调 `camera copy --operation apply` 生成新副本；发现冲突或放弃修改时调 `--operation cancel` 结束作业。
4. **同窗打开验证副本**：在原窗口完成原生检查与生成后，先附接原 GUI 会话，再运行 `camera copy --operation open`（传入 `session_dir`、`attach_id`、`expected_context` 与稳定 `request_id`）加载已验证副本。

### 共享数据与独占保护

修改相机前先核对 Camera Object、Camera Data、Action、父级、约束、路径、驱动、NLA 和景深目标的引用关系。名称相同并无独占保障；需要单改一台相机时先复制出独立数据块再编辑。门禁提示存在动画、约束或共享引用时，排查真实依赖并按对应动态入口处理，保持原有绑定与动画关系完好。

## 四、现场 3D 视口预演与 A/B 比较（`camera session-live`）

需要实时看遮挡、构图留白与运镜节奏时，在已打开的工作副本窗口里显式附接现场会话，再通过 `camera session-live` 驱动真实 View3D：

```powershell
# 先查视口身份、上下文指纹、候选与租约状态
& $ctl camera session-live --session-dir $sDir --attach-id $attachId --operation status
```

每次操作附带 `--request-id`（UUID），把 `area_id`、`expected_context` 和动作参数写进 `--params` JSON；超时或中断时复用同一个 `--request-id` 调 `--operation result` 回收结果。

| `operation` | 做什么 |
|---|---|
| `status` | 获取当前 View3D 的 `area_id`、`expected_context`、候选状态、租约 ID 与 `copy_preflight_id`。 |
| `load` / `clear` | 载入同源候选表 JSON 进行对比，或清空已载入候选。 |
| `compare` | 在指定关键帧切换 A/B 候选机位，同构图同画幅直接对照。 |
| `play` / `start` | 按实体模式（`SOLID`）连续播放全场景、预览帧域、自定义帧域或按镜头表顺序播放；需要看材质与景深时在支持材质预览的候选配置下切换 `MATERIAL` 模式对照。 |
| `stop` / `restore` / `release` | 暂停播放、将视口与时间线恢复到预演前状态、释放控制租约。 |
| `open` | 在原窗口打开已验证的 `camera copy` 副本（传作业目录、`terminal_sha256`、`output_sha256`、`window_id`）。 |
| `cancel-copy-preflight` | 用 `status` 返回的 `copy_preflight_id` 取消未提交的预检。 |

注意检查场景时间线：若存在绑定到相机的原生时间线标记，先在工作副本上整理为标准镜头表再启动现场预演。预演结束后按 `stop` → `restore` → `release` 收尾，保持窗口处于干净状态。

## 五、与独立剪辑工具的切点协同

需要在不启动 Blender 的情况下快速试切点或换机位候选时，按下面五步闭环：

1. 在 `SEQUENCE` 模式的已保存工作副本上运行 `camera shot-table` 的 `export-candidate`，取得源绑定基线 JSON。
2. 用独立镜头表脚本（`discover --product camera` 可查其准确路径）运行 `move-cut` 调相邻切点，或运行 `choose-camera` 替换某行机位，每步生成全新的候选 JSON 并用 `validate` 核对结构与源 SHA。
3. 回到同源 `.blend` 上跑 `camera shot-table` 的 `review-candidate` 查看变更行与受影响机位。
4. 在打开的窗口用 `camera session-live` 载入候选，定帧 `compare` 加全段 `play` 对比 A/B 效果。
5. 拍板后用 `camera shot-table` 的 `adopt-candidate --output NEW.blend` 写出正式工作副本，另起进程冷重开核对，连同新 `.blend`、SHA256 与基线 JSON 交给灯光、批渲染或剪辑部门。
