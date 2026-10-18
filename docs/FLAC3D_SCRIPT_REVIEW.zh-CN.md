# FLAC3D 局部脚本审阅

**简体中文** | [English](FLAC3D_SCRIPT_REVIEW.md) · [首页](../README.md)

这个入口把选定脚本的行号、文件版本、已读官方文档和 Agent 撰写的发现保存在同一任务中。下一次会话可以恢复当时读过什么、结论是什么、哪些条件尚未检查。轻量项目可以在需要这些记录时才启用，无需改变原有目录。

可以直接告诉 Agent：

> 对照 FLAC3D 9.6.44 官方资料，审阅这个脚本第 10–20 行中的 `zone cmodel assign`。保存文件版本、文档依据和未检查项，下次从这里继续。

用户决定问题、交付范围与后续行动。Agent 负责阅读和解释；程序检查行号、引用与来源版本的关联，不能认证解释正确。

## 本批支持的范围

只选一个文件中的有限行段，关注完整、字面书写的单行 `zone cmodel assign`。这不是完整 FLAC3D 解析器：FISH、Python、调用的文件、续行、表达式、range 的含义和执行上下文均不能由这个入口推断。遇到不确定的上下文，缩小范围或记录缺口。

当前原文件上限为 2 MiB，选中范围最多 200 行、32,000 个字符。超过范围时需选择更小的输入；不能据此声称大文件的其他部分已审阅。

生产审阅需要已读取、产品和版本匹配的**官方本地文档段落**。仅有命令名称检查、搜索结果或社区 MCP 语料不能代替这一依据。文档登记与正文读取沿用[文档阅读指南](ITASCA_READING.md)。合成资料只能用于明确标记的合成任务。

发现由 Agent 或用户撰写，每项必须引用捕获范围内的相关命令行和选定文档 Evidence。引用检查只验证来源关联，不能证明该段文字支持结论。判断保持暂定并带有缺口。此流程不运行 FLAC3D，不修改源脚本，也不产生 Run 或 Verification；原有生产 `static_check` 仍未实现。

## Agent 操作步骤

以下命令从代码仓库运行。替换路径、版本、行号与问题；项目资料放在自己的项目目录。已启用研究记录的项目无需再次启用。

```powershell
$projectRoot = 'D:\replace-with-user-chosen\existing-study'
$registration = 'D:\replace-with-host-selected\documentation.local.json'
python -B -X utf8 mining_kernel.py enable-research --project-root $projectRoot --project-id study-01
python -B -X utf8 mining_kernel.py documentation-read --project-root $projectRoot --task-id assign-doc-01 --question "官方如何解释弹性本构赋值？" --registration $registration --page flac3d/zone/doc/manual/zone_manual/zone_commands/cmd_zone.cmodel.html --anchor kwd:zone.cmodel.assign.elastic --product flac3d --product-version 9.6.44
```

先阅读返回的实际段落与覆盖限制，再把回执中的 Asset ID 传给审阅入口。此处的页码路径和锚点是示例，必须存在于所选官方版本的登记中。

```powershell
$docAsset = '<documentation-read 返回的 Asset ID>'
python -B -X utf8 mining_kernel.py script-review-start --project-root $projectRoot --task-id assign-review-01 --question "选中行的本构赋值与已读说明有什么关系？" --script work/model.dat --start-line 10 --end-line 20 --product-version 9.6.44 --documentation-asset-ref $docAsset
```

`--script` 可选项目相对路径，或用户明确提供的外部文件绝对路径。外部文件留在原位，持久记录仅保存受控标签。默认严格按 `utf-8-sig` 解码；确知其他编码时显式传 `--encoding`。文件哈希绑定完整原文件，快照仅保存选定行。不要把含敏感信息的脚本片段放进公开项目记录。

Agent 查看返回的捕获行、文档出处与审阅模板，撰写 JSON 文件，例如：

```json
{
  "summary": "仅对选中赋值行与已读弹性模型说明作初步对照。",
  "findings": [
    {
      "start_line": 12,
      "end_line": 12,
      "statement": "该行写为 zone cmodel assign elastic；已读段落说明该关键词对应弹性本构赋值。参数和适用性仍未检查。",
      "documentation_evidence_refs": ["<选定官方段落的 Evidence ID>"]
    }
  ],
  "gaps": ["尚未检查材料参数、选区和前置状态。"],
  "next_action": "由用户决定是否继续检查参数与选区。"
}
```

这里的第 12 行只是格式示例，实际必须引用捕获到的命令。不能直接照抄解释而不读原文。

```powershell
python -B -X utf8 mining_kernel.py script-review-record --project-root $projectRoot --task-id assign-review-01 --operation-id assign-note-01 --review-file 'D:\replace-with-user-chosen\assign-review.json'
python -B -X utf8 mining_kernel.py script-review-report --project-root $projectRoot --task-id assign-review-01 --output reports/assign-review-01.md
```

报告从持久记录生成，写入保护与现有研究报告相同：不能覆盖项目入口、登记材料或其他手写文件。更新判断应写入记录；不要让手工修改的报告成为另一份当前状态。

## 下一次会话

在项目 `START.md` 简短写明约定范围、任务 ID、报告位置与待决定事项，再使用：

```powershell
python -B -X utf8 mining_kernel.py script-review-progress --project-root $projectRoot --task-id assign-review-01
python -B -X utf8 mining_kernel.py script-review-progress --project-root $projectRoot --task-id assign-review-01 --script work/model.dat
python -B -X utf8 mining_kernel.py script-review-report --project-root $projectRoot --task-id assign-review-01
```

第一条恢复历史快照与判断，不重新读取原脚本或文档；第二条才只读比较明确指定的当前文件哈希。未比较不能称为“当前文件未变”。文件改变或丢失时，旧发现仍只针对原哈希的行段；新的文件版本或问题使用新任务 ID，重新选择证据。重复相同请求是恢复已存任务，不能用来刷新来源。

没有官方资料时，可运行[离线合成示例](../examples/script_review/README.md)了解整个记录与接续流程；教学片段不构成真实模型核查。
