# 离线合成脚本审阅示例

[中文指南](../../docs/FLAC3D_SCRIPT_REVIEW.zh-CN.md) · [English guide](../../docs/FLAC3D_SCRIPT_REVIEW.md)

This offline example uses an authored script and synthetic documentation. It demonstrates persisted line citations, review recording and recovery in a fresh CLI process. It never executes FLAC3D and does not validate a real model.

示例编写一个只有三行的教学脚本和一段**合成说明**，使用 `synthetic` 来源与任务标记。它演示如何捕获第3行、绑定文档 Evidence、记录发现和缺口，再由独立 CLI 进程恢复并生成 Markdown 报告。无需 FLAC3D、官方文档、MCP 或第三方 Python 包。

从仓库根目录运行，选择代码仓库外的新目录或空目录：

```powershell
$exampleRoot = 'D:\replace-with-user-chosen\script-review-demo'
python -S -B -X utf8 examples/script_review/demo.py $exampleRoot
python -S -B -X utf8 mining_kernel.py script-review-progress --project-root $exampleRoot --task-id synthetic-script-review-01
python -S -B -X utf8 mining_kernel.py script-review-progress --project-root $exampleRoot --task-id synthetic-script-review-01 --script work/example.dat
```

报告位于所选项目的 `reports/script-review.md`；项目入口记录任务与报告位置。重复查看用 `script-review-progress` 或 `script-review-report`；演示生成器要求目录为空，避免覆盖已有材料。

该示例不能作为官方语法、数值有效性或工程适用性的证据。真实项目按指南登记并读取对应版本官方资料，用户决定具体问题及后续工作。
