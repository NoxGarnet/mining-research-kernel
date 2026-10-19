# Itasca 外部执行观察与恢复

**简体中文** | [English](ITASCA_EXECUTION.md) · [首页](../README.md)

可以告诉 Agent：

> 保存这次 FLAC3D 任务的脚本版本、执行范围和停止条件。用现有 MCP 提交，记录返回的任务 ID、状态和有限日志；捕获选定 CSV，下次继续时恢复记录。

Agent 选择并调用已有 Itasca 工具，负责运行授权、版本核对、隔离会话和实际执行。
内核保存有限脚本快照、外部任务观察、输出关联与可重建报告；本页命令不会调用引擎。
它们不启用生产 `static_check`，也不把任务完成当成数值、物理或工程验证。

## 准备一次有边界的任务

先在已有项目中启用研究记录，选择项目相对路径的 UTF-8 Python 入口脚本。
准备元数据 JSON，例如：

```json
{
  "software": "flac3d",
  "product_version": "9.6.44",
  "purpose": "填写本次检查的问题与实际范围。",
  "stop_conditions": ["填写循环、时间、输出与异常停止条件。"],
  "output_root": "outputs/selected-run",
  "engine_session": "host-selected-session",
  "origin": "provided_script"
}
```

软件版本必须来自实际核对；示例版本不是自动选择。`engine_session` 是宿主给会话的稳定标签，
不认证引擎身份。可选 `question_id` 关联项目中已有 ResearchQuestion；未提供时建立本次运行问题。
准备记录只覆盖入口脚本，依赖文件和模型状态须由 Agent 在适用范围内另行核查。

```powershell
python -B -X utf8 mining_kernel.py enable-research --project-root path/to/study --project-id study
python -B -X utf8 mining_kernel.py itasca-run-prepare --project-root path/to/study --run-id selected-run --script scripts/selected.py --metadata-file path/to/plan.json
```

入口脚本最多 256 KiB，输出目录须在项目内；路径逃逸和链接不被接受。
回执中的 `run_ref.id` 是本地 RunReference，外部 MCP `task_id` 是另一种身份。
准备成功不等于授权执行、完整静态检查通过或引擎已准备好。

## 记录实际工具响应

Agent 按项目授权，通过已有 `itasca_execute_task` 提交选定入口文件，再将实际返回的内层
`ok/data` 或 `ok/error` 对象放入观察 JSON。下面的任务 ID 与路径只是格式说明，不能作为真实证据：

```json
{
  "schema_version": 1,
  "kind": "itasca_execution_observation",
  "origin": "agent_supplied",
  "captured_at": "2026-10-19T00:00:00Z",
  "phase": "submission",
  "tool_result": {
    "ok": true,
    "data": {
      "task_id": "actual-id",
      "task_status": "pending",
      "entry_script": "replace-with-actual-absolute-entry-path",
      "description": "实际工具返回的描述"
    }
  }
}
```

时间和工具响应都应替换为实际观察。记录成功的 submission 时检查入口路径和当前字节哈希。
状态查询使用 `phase: "status"`，保留工具返回的 `task_id`、`task_status`、`output` 与
`pagination` 等字段；仅保存有界输出页，不保证日志完整。

```powershell
python -B -X utf8 mining_kernel.py itasca-run-record --project-root path/to/study --run-id selected-run --operation-id submitted-01 --observation path/to/submission.json
python -B -X utf8 mining_kernel.py itasca-run-record --project-root path/to/study --run-id selected-run --operation-id status-01 --observation path/to/status.json
```

同一 operation ID 和同一请求可重放，改变请求须使用新 ID。错误任务 ID、跨运行错绑、终态倒退和
并发修订会被拒绝；提交结果未知时保留 `submission_unknown`，不能通过自动重提假装恢复。
工具调用超时不证明任务没有启动。断网后的恢复仅恢复已存观察，不自动恢复、重启或中断求解器。
CLI 返回成功表示记录已保存，运行状态仍须读取回执；`completed` 不等于工程验收通过。

## 捕获输出并接入 CSV 比较

RunReference 到达 completed、failed 或 interrupted 后，可有限捕获输出目录中的 UTF-8 日志或文本。
CSV 只接受 completed 状态；失败或中断任务的文本输出保持诊断用途。匹配 CSV 可通过 `--run-ref` 关联结果导入。
每个文件最多 1 MiB，快照保存原字节及哈希，不导入 SAV 等二进制文件。

```powershell
python -B -X utf8 mining_kernel.py itasca-output-import --project-root path/to/study --run-id selected-run --operation-id capture-csv-01 --path outputs/selected-run/values.csv --kind csv
python -B -X utf8 mining_kernel.py result-import --project-root path/to/study --task-id values-01 --question "这次导出的指标是什么？" --csv path/to/study/outputs/selected-run/values.csv --metadata-file path/to/result-metadata.json --run-ref <run_ref.id>
```

`result-import` 沿用[已有 CSV 契约](RESULT_COMPARISON.zh-CN.md)：固定 `point_id,value`、显式单位与工况。
关联时检查已捕获输出的路径、字节哈希、RunReference 和上下文；文件名相同不足以建立关联。
这些检查不能独立证明输出确由指定脚本生成，调用方关联及其限制会继续保留。
不带 `--run-ref` 的原有 CSV 导入保持可用。

## 恢复与报告

```powershell
python -B -X utf8 mining_kernel.py itasca-run-progress --project-root path/to/study --run-id selected-run
python -B -X utf8 mining_kernel.py itasca-run-report --project-root path/to/study --run-id selected-run --output reports/execution.md
```

恢复从 ResearchStore 读取，不查询引擎，也不重开原始脚本或输出。报告使用已存观察，保留来源、状态历史、
分页范围、缺口和输出引用；项目入口与研究原始材料受到报告写出保护。
`project-context` 提供外部运行导航；RunReference 与原生五阶段 Run Ledger 的完整求解器验收分开。
本流程不自动产生代表工程有效性的 Verification，也不允许其绕过既有任务完成关卡。

匿名教学必须同时使用 `origin: "synthetic"` 与 synthetic 上下文，不能作为生产执行或生产 CSV 依据。
无需 Itasca 即可运行[离线合成示例](../examples/itasca_execution/README.md)。
