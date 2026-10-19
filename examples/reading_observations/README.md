# 通用阅读观察：离线接续示例 / Offline reading continuity

从仓库根目录执行：

```powershell
python -S -B -X utf8 examples/reading_observations/demo.py
```

示例在仓库外创建临时项目，也可用 `--output` 指定仓库外的新目录或空目录。
它使用 Python 标准库，通过公开 CLI 导入三个编写的阅读观察、比较两篇教学论文，
再补读第二篇并沿用同一个 ResearchQuestion。导入 JSON 随后移位，独立 CLI 进程仍可恢复
判断及生成报告；旧报告和记录哈希保持不变。输出目录含 `demo-result.json` 及 `reports/research.md`。

所有论文、页码和段落均为教学编写；没有真实 PDF 或网页读取，也没有科学验证。
示例不安装或调用阅读器、Zotero、网络服务、模型或求解器。

The example uses authored synthetic observations, not real publications. It records a
local-PDF-style observation and a web-article-style observation, continues one question
with additional coverage, and regenerates a report from persisted records after moving
the import files. The CLI subprocesses run with `-S` and require only the standard library.
No source reader, network connection, model, or solver is invoked.

使用指南：[中文](../../docs/READING_OBSERVATIONS.zh-CN.md) / [English](../../docs/READING_OBSERVATIONS.md)。
