# 通用阅读观察与持续研究

**简体中文** | [English](READING_OBSERVATIONS.md) · [首页](../README.md)

可以直接告诉 Agent：

> 用你现有的工具读取本地论文第 5–8 页，以及这篇网页论文的方法段落。记录来源和读取限制，比较参数来源；下次补读验证部分时保留旧判断。

Agent 选择已有的浏览器、PDF、图像或 OCR 工具，实际阅读、解释并准备有限观察。
内核接收这些观察，检查结构和引用关联，保存版本及判断历史，再提供同一问题的接续与报告。
它不下载或解析论文，不运行 OCR，也不通过记录证明 Agent 确实读过、来源真实或解释正确。
已有 [Zotero 读取](RESEARCH_SOURCES.md)和[软件文档读取](ITASCA_READING.md)仍可使用。

## 哪些信息会被保留

- 来源：调用方稳定 `source_id`、标题、可选 DOI/网页 URL、`local_pdf` / `web_article` / `local_text`、可选版本及原文件哈希。
- 读取：工具名称、`text` / `visual` / `ocr` / `mixed` 方法、观察时间、有限段落及其成功/失败状态。
- 定位：PDF 的 1-based 页码范围，或明确的段落、图、表、行标签。每个定位标签在一份观察内唯一。
- 局限：来源或文本哈希未知、未核对图表、OCR 误差、只读部分页面等；未知不会自动补成已核验。

来源声明为 `original_publication` 只说明调用方如何描述来源；保存的阅读观察始终是派生层。
原文件 SHA-256、读取文本 SHA-256和内核嵌入观察 SHA-256是不同对象。内核不会因三者存在而认证来源或科学结论。
宿主文件绝对路径不进入观察；实际文件由 Agent 的读取工具访问，持久身份使用稳定非路径标签。

## Agent 接口

先实际阅读，再填写 JSON。下面只有结构示例，不能当成真实论文的读取证据。
必填字段和限制以 [schema](../schemas/reading_observation.schema.json)及运行时校验为准。

```json
{
  "schema_version": 1,
  "kind": "reading_observation",
  "origin": "agent_supplied",
  "captured_at": "2026-10-19T00:00:00Z",
  "source": {
    "source_id": "selected-paper-a",
    "title": "实际读取的论文标题",
    "doi": null,
    "url": null,
    "version": null,
    "source_kind": "local_pdf",
    "source_sha256": null,
    "authority": "original_publication"
  },
  "reader": {"tool": "宿主已有 PDF 工具", "method": "text"},
  "passages": [{
    "locator": {"kind": "pdf_pages", "value": "PDF pages 5-8", "start_page": 5, "end_page": 8},
    "status": "read",
    "text_sha256": null,
    "excerpt": "填写实际读取到的有限原文，不在这里生成未经阅读的内容。",
    "limitations": ["原文件版本和哈希、读取文本哈希未知；图表尚未视觉核对。"]
  }],
  "limitations": ["仅记录限定阅读；来源身份、实际阅读行为及科学结论未独立验证。"]
}
```

时间替换为实际观察时间，未知版本和哈希保持 `null`，不能照抄示例时间或捏造哈希。
HTML 没有可靠 PDF 页码时，用例如 `{"kind":"section","value":"Methods / Parameter calibration"}`。
OCR、图像或派生转换保留相应方法和局限；不从网页顺序推造 PDF 页码。
失败段落用 `status: "unavailable"`、空 `excerpt` 和空哈希，说明失败；它不能支持引用。
匿名编写的教学数据必须使用 `origin: "synthetic"` 和合成上下文，不能用于生产研究。

从代码仓库运行，项目及观察 JSON 留在用户项目中：

```powershell
python -B -X utf8 mining_kernel.py enable-research --project-root path/to/study --project-id study
python -B -X utf8 mining_kernel.py validate-reading-observation path/to/observation.json
python -B -X utf8 mining_kernel.py reading-record --project-root path/to/study --observation-id paper-a-read-01 --observation path/to/observation.json
```

保存回执返回 `asset_ref` 与 `evidence_ref`；只写一组观察记录，不自动创建研究判断。
`query_performed=false`、`source_revalidated=false` 表示本次导入没有查询或重新核验原来源。
同一观察 ID、同一请求可幂等重放；改变来源、覆盖或解释前使用新的观察 ID，保留旧记录。

## 比较、补读与恢复

取得两篇不同论文观察的 Asset ID 后：

```powershell
python -B -X utf8 mining_kernel.py research-begin --project-root path/to/study --task-id compare-01 --question "参数来源与验证用途如何交代？" --asset-ref <paper-a-asset> --asset-ref <paper-b-asset> --dimension parameters --dimension validation
```

填写返回的 `comparison_template`，通过 `literature-review --comparison-file` 保存。
通用观察的引用形如 `{"evidence_id":"<该来源Evidence>","locator":"PDF pages 5-8"}`：
定位必须准确匹配该观察中成功读取的标签，不能引用未读或失败段落。
Zotero 继续使用其附件与页码引用，软件文档保留自己的定位方式。
同一 DOI 的重复观察，包括 Zotero 与通用观察的组合，不能充当两篇不同论文。
无 DOI 的来源依赖调用方身份声明，仍需 Agent 核对实际是否为不同论文。

单份来源或非表格式的解释可使用 `research-begin --mode sources`，再用 `research-review` 保存带 Evidence 引用的 Markdown。
此模式的引用检查在 Evidence 层面，不提供文献比较模式的逐定位单元格约束；研究者仍须说明准确范围。

补读由 Agent 使用已有工具完成，然后用新观察 ID 保存并明确选择本轮全部有效来源：

```powershell
python -B -X utf8 mining_kernel.py research-continue --project-root path/to/study --from-task compare-01 --task-id compare-02 --asset-ref <paper-a-asset> --asset-ref <paper-b-new-asset> --reason "补读验证部分并保留旧判断"
python -B -X utf8 mining_kernel.py research-progress --project-root path/to/study --task-id compare-02
python -B -X utf8 mining_kernel.py research-report --project-root path/to/study --task-id compare-02 --output reports/research.md
```

接续沿用同一个 ResearchQuestion，绑定前一 TaskState/Decision 的准确修订。
恢复和报告从已保存记录读取，不需要原始导入 JSON、原论文或读取工具；也不意味着网页或文件当前未变。
报告是可重建的派生视图，包含来源、方法、覆盖、局限及修订关系，不是论文全文备份。
本流程不创建求解器 Run 或工程 Verification，研究判断保留暂定或不足状态。

无需论文或工具连接即可运行[离线合成示例](../examples/reading_observations/README.md)。
