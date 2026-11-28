# 来源与证据追溯

本页保留镜头与相机工作流的知识来源、50 项外部文献索引指针，以及项目内 CLI 契约与验收回执的查阅路径，方便后续核对出处与定点复查。

## 一、摄影与导演方法来源

- **《专业运镜知识与导演方法手册 v1.0》**（53 页，正文 16 章及附录 A/B/C，源 PDF SHA-256：`19a9938ef66faa2e1df208d7c43759b25b18fae077b0361a76d56e7362ad129f`）：
  - 第 1、3、13、16 章与工作表（pp.4–5、9–10、32–37、40–41）→ 整合至 [导演决策与镜头设计](director-and-shot-design.md)。
  - 第 2、4–8 章、透视图解及附录 A 47 项术语（pp.6–8、11–22、42–44）→ 整合至 [运动几何与术语速查](motion-geometry.md)。
  - 第 8–10、13、15 章及审看工作表（pp.21–26、32–33、38–41）→ 整合至 [连续性、可读性与审看排查](continuity-and-review.md)。
  - 第 6–7、11–14 章及题材与案例（pp.17–20、27–37）→ 整合至 [题材、媒介与支撑特征](contexts-and-media.md)。
  - 附录 C 共 50 项外部参考条目（R01–R11、T01–T22、N01–N17，pp.47–53）→ 机器可读完整账册保留在 [external-source-ledger.json](external-source-ledger.json)，包含每条文献的原始链接、采用要点与适用条件。

## 二、项目内公共 CLI 契约与实测记录

查看当前宿主支持的精确版本、动作入口与实测回执，先运行 `./blenderctl.ps1 discover --product camera`，并按需查阅以下项目文档与审计目录：

- 镜头表、切点改时与现场预演总交接文档：[shot-timing.md](../../../../docs/cli/workflows/shot-timing.md)
- 相机部门动作清单与范围说明：`work/audit/<batch>/`
- 原生副本事务、构图诊断与同窗复开回执：`work/audit/<batch>/`、`work/audit/<batch>/`
- 公共镜头表读写、切点移动、来源切换与候选采用回执：`work/audit/<batch>/`、`work/audit/<batch>/`、`work/audit/<batch>/`
- 现场 3D 视口 SOLID 预览、候选 A/B 比较与恢复回执：`work/audit/<batch>/`、`work/audit/<batch>/`、`work/audit/<batch>/`
- 材质与景深视口对照及本地候选验证：`work/audit/<batch>/`、`work/audit/<batch>/`、`work/audit/<batch>/`、`work/audit/<batch>/`

## 三、维护与更新约定

1. 业务正文与五份主题参考只写当下直接能用的做法；具体版本号、日期、批次号和审计证据统一沉淀在本页或通过 `discover` 实时查询。
2. 保留 [external-source-ledger.json](external-source-ledger.json) 原样不动，新增外部文献或实测记录时同步补充条目并标明核验范围。
3. 修改本技能后，使用 PowerShell 扫描全目录 `.md` 与 `.yaml`，确认正面表达与内部链接完整有效。
