# 离线匿名CSV结果比较示例

[中文指南](../../docs/RESULT_COMPARISON.zh-CN.md) · [English guide](../../docs/RESULT_COMPARISON.md)

This standard-library example uses authored CSV values and synthetic script/documentation context. It aligns selected point IDs, retains missing data and recovers a report in a fresh process. No data were produced by a solver, and the associated script does not establish CSV provenance.

示例先复用已有合成脚本审阅，再创建两份匿名编写的结果表。对照表的测点顺序不同，并故意缺少P3；只选P1、P2、P3，不能把P4自动纳入比较，也不能把缺失值填零。

| 测点 | 基准值 | 对照值 | 对照值 − 基准值 |
|---|---:|---:|---:|
| P1 | -12.5 | -10.0 | 2.5 |
| P2 | -8.0 | -7.0 | 1.0 |
| P3 | 空值 | 缺少该测点 | 不足，不计算 |

单位标签为编写的 `mm`，工况也为合成说明。差值只演示算术，不能据此推断支护改善或工程适用性。

从仓库根目录运行，选择仓库外的新目录或空目录：

```powershell
$exampleRoot = 'D:\replace-with-user-chosen\csv-result-demo'
python -S -B -X utf8 examples/result_comparison/demo.py $exampleRoot
python -S -B -X utf8 mining_kernel.py result-progress --project-root $exampleRoot --task-id synthetic-result-comparison
python -S -B -X utf8 mining_kernel.py result-report --project-root $exampleRoot --task-id synthetic-result-comparison
```

生成的项目入口记录任务ID与报告链接；报告位于 `reports/result-comparison.md`，关联此前合成脚本与文档的历史版本。恢复命令从记录读取，默认不重新打开源CSV。

演示生成器拒绝覆盖非空目录。已有演示用恢复或报告命令继续查看；真实项目按指南读取已导出的CSV，不把这些教学数据换成生产证据。
