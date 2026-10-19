# 已有CSV结果的只读接入与比较

**简体中文** | [English](RESULT_COMPARISON.md) · [首页](../README.md)

这个入口读取已有导出的结果表，保存来源版本与阅读范围，按选定测点比较两组数值，并让后续会话恢复同一份比较。它复用可选研究记录，原文件留在原位。

可以直接告诉 Agent：

> 比较这两份位移导出表中的 P1、P2 和 P3，记录单位、工况、差值与缺失信息，并关联已有脚本审阅。保存报告，下次继续。

用户决定问题、选取范围和后续行动。Agent 从已有材料与用户已确认的信息补齐说明；未知信息保留为缺口，不要求用户重复填表，也不能自行猜单位。

## 当前格式与解释范围

首版是一份文件对应一个工况、一个指标的逗号分隔CSV，恰有 `point_id,value` 两列，列顺序可交换。例如：

```csv
point_id,value
P1,-12.5
P2,-8.0
P3,
```

每个文件最多2 MiB、2,000条数据记录；每次明确比较最多100个测点。默认严格按 `utf-8-sig` 读取，接受UTF-8 BOM；确知其他编码时显式指定。表头、列数或CSV结构不符合时拒绝导入；空值、非法数值、非有限值和重复测点保留诊断，不自动填零或去重。若原软件导出格式不同，需要另行保留有来源说明的转换副本，本入口不会改写原表。

单位、指标、列含义、测点依据与工况说明随导入记录保存。它们是调用方的声明，不能证明软件版本、导出过程或模型状态已经核实。

差值固定为 **对照工况值 − 基准工况值**，按选定 `point_id` 对齐，与行排序无关。指标或单位未知、标签不一致，以及测点缺失、重复或数值不可用时，相应差值不能成立。首版不自动换算单位、不计算改善率，也不从正负差值推断支护效果。工况或测点依据的差异与未知仍须出现在缺口中。

## Agent 操作步骤

从仓库运行命令，把材料和生成记录留在用户自己的项目中。已有研究记录时跳过启用步骤：

```powershell
$projectRoot = 'D:\replace-with-user-chosen\existing-study'
python -B -X utf8 mining_kernel.py enable-research --project-root $projectRoot --project-id study-01
```

为每份表准备小型JSON说明文件，例如基准工况：

```json
{
  "case_id": "baseline",
  "quantity": "displacement_y",
  "unit": "mm",
  "column_meanings": {"point_id": "用户选定的监测点标识", "value": "按所述方向记录的位移"},
  "point_basis": "两组数据使用相同的监测点定义；依据见项目记录",
  "conditions": {"stage": "用户已确认的施工阶段", "coordinate_frame": "用户已确认的坐标与正负约定"},
  "origin": "provided_export"
}
```

这里只展示格式，不能把示例中的声明照搬为项目事实。未知字段用 `null` 或省略；`case_id` 必须明确。匿名编写的教学数据用 `origin: synthetic` 和 `--task-context synthetic`，不能混入生产比较。

```powershell
python -B -X utf8 mining_kernel.py result-import --project-root $projectRoot --task-id baseline-read-01 --question "记录基准工况已导出的位移表" --csv exports/baseline.csv --metadata-file 'D:\replace-with-user-chosen\baseline-metadata.json'
python -B -X utf8 mining_kernel.py result-import --project-root $projectRoot --task-id candidate-read-01 --question "记录对照工况已导出的位移表" --csv exports/candidate.csv --metadata-file 'D:\replace-with-user-chosen\candidate-metadata.json'
```

回执返回可比较的捕获Asset ID。文件可以使用项目相对路径或用户明确提供的外部绝对路径；持久记录不自动暴露外部宿主路径。保存完整文件哈希、所选两列的原值、物理行号和诊断，恢复时不依赖原表仍然存在。

```powershell
$baselineAsset = '<基准导入回执的捕获 Asset ID>'
$candidateAsset = '<对照导入回执的捕获 Asset ID>'
python -B -X utf8 mining_kernel.py result-compare --project-root $projectRoot --task-id displacement-compare-01 --question "指定测点的两组位移数值相差多少？" --baseline-asset-ref $baselineAsset --candidate-asset-ref $candidateAsset --point P1 --point P2 --point P3 --comparability-note "仅比较用户指定标签；物理可比条件仍以记录和缺口为准" --related-task '<已有脚本审阅任务 ID>' --next-action "由用户决定是否补查工况或增加其他测点"
python -B -X utf8 mining_kernel.py result-report --project-root $projectRoot --task-id displacement-compare-01 --output reports/displacement-comparison.md
```

`--related-task` 可省略或重复使用，关联已有脚本审阅、文档阅读或研究任务。报告保留关联时的准确版本、任务上下文与文档来源类别；生产比较拒绝关联合成任务。**背景关联不能证明CSV由该脚本计算得到**。已有求解器运行的真实性与结果来源需要另有证据。本流程不启动求解器，不创建Run或工程Verification。

新比较只要任一来源已通过 `--run-ref` 关联运行，记录中的说明就限定为“比较操作不执行求解器”，不否认来源曾被外部求解，也不认证该运行确实产生了 CSV。历史任务仍重放当时保存的判断和措辞，恢复不会改写旧账本；完全未关联运行的 CSV 比较保持原有行为。

## 恢复与来源变化

```powershell
python -B -X utf8 mining_kernel.py result-progress --project-root $projectRoot --task-id displacement-compare-01
python -B -X utf8 mining_kernel.py result-report --project-root $projectRoot --task-id displacement-compare-01
```

默认恢复历史捕获、判断、缺口和后续建议，不重读CSV、脚本或文档。若需比较当前文件，明确提供一个JSON映射文件（捕获Asset ID → 当前文件路径），再给 `result-progress` 传 `--source-paths-file`。未检查、未变、已变、缺失或读取失败分别报告，不能以恢复成功代替文件未变。

相同任务和参数只重放已存记录；新的文件版本、说明或比较范围使用新的任务ID，保留旧结果。命令成功表示处理或记录完成，判断仍可能为 `INSUFFICIENT`。在项目 `START.md` 简短写回问题、任务ID、报告位置和待决定事项，避免重复保存整份结果。报告是可重建的派生文件，写入器保护项目入口、登记材料和其他已有手写文件。

没有现成结果时，可以运行[离线匿名合成示例](../examples/result_comparison/README.md)，查看乱序测点、缺失数据、脚本/文档背景和跨会话恢复如何保存。它不能作为真实模拟结果。
