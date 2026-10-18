# Mining Research Kernel · 矿业研究内核

**简体中文** | [English](README.en.md)

本介绍页以及“建立轻量工作区”“持续研究”“FLAC3D 局部脚本审阅”和“已有CSV结果比较”指南均可切换中英文。其余指南目前主要为英文，部分示例使用中文。

一个基于本地文件的轻量工作区与可选研究内核，用于协助 Agent 开展矿业研究。
先用少量 Markdown 文件组织项目；需要时，再启用持久研究记录和领域工作流。
运行时与离线示例使用 Python 标准库。

## 开始或接续项目

- [建立轻量工作区](docs/START_WORKSPACE.zh-CN.md)：创建三个入口文件，从一个实际研究问题开始。
- [接入已有项目](docs/EXISTING_PROJECT.md)：保留资料原有位置，只补齐必要入口，明确本次协助任务。
- [接续已有项目](docs/PROJECT_CONTEXT.md)：查找项目入口、判断和资料位置，无需先创建任务或读取原始材料。
- [按需启用研究记录](docs/OPTIONAL_RESEARCH.md)：为已有项目增加持久记录，保存本地资料查询的依据和限制。
- [围绕同一问题持续研究](docs/CONTINUING_RESEARCH.zh-CN.md)：恢复原判断，补读选定材料，生成包含变化与缺口的报告。
- [阅读软件文档段落](docs/ITASCA_READING.md)：读取已登记的官方本地 HTML，或查询已有 Itasca MCP 文档连接，并保留不同来源的出处。
- [围绕问题比较文献](docs/LITERATURE_COMPARISON.md)：按选定维度比较论文与可选软件说明，保留页码引用和缺失信息。
- [FLAC3D 核查工作流](docs/FLAC3D_FIRST_TASK.md)：定位输入、确认软件版本、查阅适用的官方说明，并保存可接续的核查结果。
- [FLAC3D 局部脚本审阅](docs/FLAC3D_SCRIPT_REVIEW.zh-CN.md)：捕获选定行和文件哈希，关联已读官方段落，保存带行号与引用的发现；首批关注 `zone cmodel assign`。
- [已有CSV结果比较](docs/RESULT_COMPARISON.zh-CN.md)：保存已导出结果的来源、单位与工况，按选定测点比较两组数值，关联已有研究并恢复报告。

可以直接告诉 Agent 你的问题和材料位置，例如：

> 比较这两篇文献已读部分的试验条件和方法，结合对应版本官方说明，记录依据、缺口和下一步建议。

Agent 按对应指南，在约定范围内启用需要的记录或资料连接。项目仍以原来的轻量入口为起点。

没有资料库连接或现有模型时，可以先运行[两次会话的合成研究示例](examples/continuing_research/README.md)。
示例保留首轮判断，再围绕同一问题补充阅读，演示进度恢复和报告生成。
其中的论文页面与解释均为编写的教学材料。

PowerShell 示例：

```powershell
$starterRoot = 'D:\replace-with-user-chosen\mining'
python -B -X utf8 .\mining_kernel.py init-workspace $starterRoot --project-id roadway-support --question "核查现有巷道支护模型的安装时序"
python -B -X utf8 .\mining_kernel.py workspace-context --workspace-root $starterRoot
```

请把示例路径替换为你选定的、代码仓库外的新目录或空目录。
研究输入与生成的项目文件保存在自己的项目目录中。

轻量入口不会配置模型或创建运行账本，也不能证明 FLAC3D、PFC、AE 或其他外部工具已经安装并可用。
软件版本、输入和核查状态需要实际确认。

也可以查看[匿名 FLAC3D 只读核查示例](examples/flac3d_review/README.md)，了解项目入口、有限范围的来源核查和交接方式。
其中的教学脚本不是工程模型，也不是求解结果。

## 为什么做这个项目

研究自动化需要区分原始资料、派生产物和验证结论。本项目把这些边界写入记录与操作流程，
发现兼容工作区、报告依据，并保留可恢复的研究状态。
它不会把元数据当成实验结论，也不会静默改写研究文件。

这是供不同 Agent 调用的早期矿业研究基础设施，把研究问题、任务路线、证据、失败和接续记录保存在对话之外。
FLAC3D 是当前首个领域入口：根据项目版本选择适用文档，记录已知、缺失和受阻的条件。
研究解释与工程判断仍需要相应的阅读、审查和验证，不能由记录完成状态替代。

## 内核机制示例

[离线合成工作流](docs/R5_QUICKSTART.md)用固定样例演示任务、证据、恢复和记录机制。
其中的执行是合成演示，不是真实 FLAC3D、PFC 或 AE 任务。

按实际需要选择入口：

- [查找项目入口、已保存判断和材料位置](docs/PROJECT_CONTEXT.md)。
- [对照适用官方文档核查 FLAC3D 命令名称](docs/R1_DOCUMENTATION.md)。
- [记录任务、证据和有限范围运行](docs/R2_QUICKSTART.md)。
- [比较有限任务路线并保留失败](docs/R3_QUICKSTART.md)。
- [审查 Cognition 提案并恢复相关失败信息](docs/R4_QUICKSTART.md)。
- [了解公开验收范围](docs/ACCEPTANCE_SUMMARY.md)。

R0–R8 是历史实现与验收阶段的名称，保留在[完成状态](docs/COMPLETION_STATUS.md)中。
日常使用可以直接从任务指南进入。

## 仓库目录

用户从上面的指南开始即可。开发者可查看 CLI 入口 [mining_kernel.py](mining_kernel.py)。

| 路径 | 用途 |
|---|---|
| [docs/](docs/) | 使用指南、接口约定、限制和验收说明。 |
| [examples/](examples/) | 可运行示例与合成工作区。 |
| [mining_research_kernel/](mining_research_kernel/) | 任务、路线、研究记录和 Cognition 服务。 |
| [workflows/](workflows/) | 领域工作流与能力声明。 |
| [adapters/](adapters/) | 项目和资料来源的发现、检查适配器。 |
| [providers/](providers/) | 文档与执行提供方，包括停用的执行边界和合成执行。 |
| [schemas/](schemas/) | 请求、记录与派生视图的 JSON 接口约定。 |
| [tests/](tests/) | 面向开发者的自动检查。 |
| [fixtures/](fixtures/) | 测试使用的固定合成材料，不含私人研究文件。 |

其他顶层 Python 文件提供 CLI 支持、项目初始化、扩展注册、Run Ledger 和 Zotero 快照工具。
普通研究任务不要求运行测试套件；请把自己的研究输入与生成记录放在独立项目目录。

## Agent 与内核的分工

Agent 阅读问题和材料，解释备选方案，选择有明确范围的操作，并提出解释。
内核校验请求，记录 Task / Route / Claim / Evidence / Run / Verification 关联，
执行相应检查关卡与预算约束，保留失败，并向后续进程提供可恢复状态。
Agent 通过 CLI 或公开 Python API 调用内核；模型、宿主应用与用户资料位于仓库之外。

任务或 Run 完成，只表示声明的工作范围完成，不能证明研究假设为真或工程方案适用。
模型和会话标识可用于记录来源与比较；更换模型或会话本身不构成独立审查。

## 当前能力

- 已有CSV结果的只读捕获与两组有限比较：保留原值、物理行号、单位/指标/工况声明与质量诊断，按选定测点计算有符号差值，关联历史脚本/文档背景并生成可恢复报告；见[结果比较指南](docs/RESULT_COMPARISON.zh-CN.md)。
- 可持久恢复的 FLAC3D 局部脚本审阅：记录选定行、文件哈希、匹配版本的官方段落与人工撰写的发现，按需只读比较当前文件是否变化；不执行脚本或认证模型正确性，见[审阅指南](docs/FLAC3D_SCRIPT_REVIEW.zh-CN.md)。
- 在同一个 ResearchQuestion 下接续资料研究，保留历史任务和判断修订，提供只读进度恢复及可重建的 Markdown 报告；见[持续研究指南](docs/CONTINUING_RESEARCH.zh-CN.md)。
- 简短恢复视图区分待分析任务与继承的历史判断，可展开准确历史版本，并为兼容的资料研究任务提供进展和报告入口。
- 在明确范围内检索 Zotero、读取选定页面、综合带引用的资料并恢复研究；见[资料研究工作流](docs/RESEARCH_SOURCES.md)。
- 通过明确的宿主登记读取官方本地 HTML 段落，或查询仅用于文档的 Itasca MCP。MCP 语料内容保留为派生阅读来源；见[文档阅读](docs/ITASCA_READING.md)。
- 围绕问题按选定维度比较不同论文，引用限制在已保存阅读页面内，适用性判断保持暂定；见[文献比较](docs/LITERATURE_COMPARISON.md)。
- 可移植的空白 FLAC3D 项目初始化与配置驱动的发现机制。
- 两个面向兼容矿业研究工作区的只读项目适配器。
- 明确绑定来源与版本的本地 HTML 命令名称检查；见[文档核查指南](docs/R1_DOCUMENTATION.md)。
- 声明并执行 FLAC3D `static_check` 关卡约束；真实实现尚未提供，生产任务以 `static_check_unimplemented` 阻塞，合成测试路径仍可使用。
- TaskPacket、持久 TaskState、有限合成执行、RunReference / Verification 记录、Zotero 合成证据与确定性 Research Map 重建；见[任务与证据指南](docs/R2_QUICKSTART.md)。
- 有限多路线探索，包括每条路线的预算、持久预留、写入集合冲突阻塞、父级与替代关系及确定性比较归档；见[路线指南](docs/R3_QUICKSTART.md)。
- 基于文件的 Core Cognition，包括可程序核查的证据、有限暂定采纳、依赖失效、限定范围的结构化冲突、去重审查队列和过滤后的失败恢复；见[Cognition 指南](docs/R4_QUICKSTART.md)。
- 新用户子进程验收和第二领域的合成工作流，复用 TaskEngine、ResearchStore、Run Ledger、Verification 与视图重建；见[新用户指南](docs/R5_QUICKSTART.md)。
- 持久化的 `task-complete` 操作，在当前 Route、RunReference / Run、Verification、输出和 Evidence 记录通过关联检查后，关闭声明的任务范围。
- 仅具备 `discover`、`inspect` 和 `read_only` 能力的静态 `kind=source` Zotero 适配器。
- 脱敏 Zotero 快照校验，以及集合、条目、附件的关系摘要。
- `relation_map.py` 优先使用规范化 DOI 匹配，再回退到标题和作者匹配。
- 基于文件的五阶段 Run Ledger，提供确定性校验和稳定性诊断。
- 有明确范围的本地材料登记：计算哈希并创建 Asset / Evidence 记录，不复制来源字节，区分原始材料、项目记录和派生阅读笔记。
- 只读证据审查任务：将登记的 Asset / Evidence 关联到 TaskPacket 阅读，检测项目内来源变化，并区分登记、阅读与验证状态。
- 面向持久状态的简短只读 `resume` 视图和定向 `show` 展开，同时保留完整 `task-inspect` TaskPacket。
- 可选的中性项目配置，复用同一个 ResearchStore 和只读证据审查工作流，保留现有文件与旧项目兼容性。
- 明确的 `documentation-record` 操作：查询已登记的本地 HTML，并以原子操作关联研究问题、派生快照、证据与暂定 Decision，不创建求解器 Run。
- 有明确范围的增量判断更新：继承已有材料阅读，检查 Decision 修订和 Evidence 引用，保留旧 Decision，不创建执行或 Verification 记录。
- 不依赖第三方包的完整合成工作区示例；完整测试与 schema 检查需要 `jsonschema`。

扩展的 v0.1.0 路线与认知循环已实现至 R5。具体已验收阶段和限制见[完成状态](docs/COMPLETION_STATUS.md)。
上述内核机制是真实的文件与记录操作。合成执行和合成静态检查用于演示，不能证明 FLAC3D 行为。
生产环境中的命令名称检查需要用户提供适用的 Itasca 本地文档登记，范围限定为 `command_name_only`，
不验证参数、完整脚本、数值有效性或工程适用性。生产 FLAC3D 静态检查与真实执行尚未实现。

可选外部 `itasca-mcp` 文档连接使用宿主选择的已有 stdio 运行时，只调用文档检索和浏览工具。
本仓库不包含该运行时，也不通过此连接执行模型或连接引擎桥。
社区语料输出不能独立证明官方页面身份或精确构建版本；执行连接属于单独的后续工作。

## 能力分类

| 分类 | 范围 |
|---|---|
| 已实现的内核机制 | ResearchStore、TaskState、路线、Run Ledger、Evidence / Verification、Research Map、Cognition 视图与完成条件检查。 |
| 合成演示 | 固定样例项目、确定性的模拟执行与合成静态检查。 |
| 用户提供的资源 | 版本适用的 Itasca 本地文档及登记、已有 Itasca 文档 MCP 运行时、脱敏 Zotero 快照、调用方注入的只读读取器，或经宿主登记选择的已有 Zotero stdio 运行时。 |
| 尚未实现 | 生产 FLAC3D `static_check`、真实 FLAC3D 执行和 Itasca 执行连接。 |

[公开验收摘要](docs/ACCEPTANCE_SUMMARY.md)记录了对应版本的代码基线，并区分这些能力与验证结论。

## Cognition 与研究依据

Core Cognition 是对持久观察、提案、失败和关系的可重建视图。
只有白名单内、具有定位依据的少数可程序核查事实，才可被暂定采纳为 `provisional`。
Agent 申请的状态、角色名称或自由文本解释不能自行提升结论地位。
其他解释仍是提案，直到受信宿主审查提供所需证据、范围和决定。

CLI 尚未提供完整的状态提升流程；系统不承诺自主理解或自我进化。
失败、有争议、过期和缺少依据的状态都会保留，并仅对相关工作形成约束。

## 环境与依赖

本候选已在 Windows / Python 3.14.2 环境验证；未承诺更低或更高 Python 版本的兼容范围，其他版本需要另行核验。

仅运行时的路径不会导入测试用的 schema 校验器，可以用隔离解释器检查：

```powershell
python -S -B mining_kernel.py --workspace examples/synthetic_workspace discover
python -S -B mining_kernel.py --workspace examples/synthetic_workspace validate
```

完整测试会直接导入 `jsonschema`，执行 Draft 2020-12 校验。使用将运行测试的 Python 准备依赖：

```powershell
python -m pip install -r requirements-test.txt
python -m unittest discover -s tests -v
```

缺少 `jsonschema` 时，仓库不会静默跳过 schema 测试。
schema 文件解析、运行时输出校验与科学或工程有效性是不同层面的检查；本轮文档改动未安装依赖。

## 快速体验

从仓库根目录运行：

```powershell
python mining_kernel.py --workspace examples/synthetic_workspace discover
python mining_kernel.py --workspace examples/synthetic_workspace inspect flac3d_coal_roadway
python mining_kernel.py --workspace examples/synthetic_workspace discover-sources
python mining_kernel.py --workspace examples/synthetic_workspace inspect-source zotero_mcp_readonly --operation zotero_get_collections
python mining_kernel.py --workspace examples/synthetic_workspace validate
```

最后一条来源检查预期返回 `CANNOT_VERIFY`，因为示例没有提供外部 Zotero 读取器。
兼容宿主应用可针对一项允许操作注入读取器。

已发布版本说明见 [RELEASE_NOTES.md](RELEASE_NOTES.md) 和 [v0.1.0 GitHub Release](https://github.com/NoxGarnet/mining-research-kernel/releases/tag/v0.1.0)。
发布前的候选草稿归档于 [docs/archive/v0.1.0-release-candidate.md](docs/archive/v0.1.0-release-candidate.md)。

## 开发者验证

准备 `requirements-test.txt` 中的依赖后，在仓库根目录运行完整测试：

```powershell
python -m unittest discover -s tests -v
```

这是使用第三方 schema 校验器的开发检查，与上面的标准库运行示例分开。

针对用户选定的空项目目录：

```powershell
python mining_kernel.py init-flac3d-project path/to/new-project --project-id demo_project
python mining_kernel.py --workspace path/to/new-project discover
python mining_kernel.py documentation-check --help
```

初始化器拒绝非空目录。使用前请配置项目实际版本和输入；空白基线不是可直接计算的模型。
文档命令需要指南中说明的独立、明确选择的宿主来源登记，不把元数据索引或注入回调当作充分的官方依据。

完整的合成任务、证据和重建流程见 [R5 快速入门](docs/R5_QUICKSTART.md)。
第二领域可以通过独立、可移植的合成项目复用内核：

```powershell
python mining_kernel.py init-synthetic-project path/to/synthetic-project --project-id synthetic_demo
```

合成执行与合成静态检查是确定性样例，不运行 FLAC3D、不验证数值或工程行为，也不包含或启用 `itasca-mcp`。
生产 FLAC3D `static_check` 仍是适用但待完成的关卡，真实实现提供或登记前保持阻塞。

若要持久记录已有任务完成，需要提供其 TaskPacket 内每条路线及证明其完成的当前记录。
这是独立操作，不是合成示例的自动收尾步骤。下面的 ID 必须来自该项目中实际检查过的记录，不能编造：

```powershell
python mining_kernel.py task-complete --project-root path/to/project task-id `
  --operation-id complete-1 --completion-json '@completion.json'
```

完成请求 JSON 必须包含 `route_ids`、`run_reference_ids`、`verification_ids`、
`verification_gate_coverage`、`evidence_refs` 和 `output_refs`，适用时按路线组织。
`verification_gate_coverage` 须逐条列出当前适用的 TaskPacket 关卡，并映射到相应 Verification ID；
每条路线的 `verification_ids` 必须与这些覆盖项的引用并集完全一致。
覆盖项中的 `verification_gate_id` 是当前 Verification `gate_id` 的冗余副本，两者都必须等于 TaskPacket 的关卡键。

操作会先检查当前 Route / RunReference / Run、Verification、ResearchStore 关系与 Run Ledger，再追加 TaskState 修订。
后续有效的 `PASS` / `PASS_WITH_NOTES` Verification 可在记录和关系足以证明覆盖时，解决此前待定或失败的关卡。
操作拒绝不完整或无关依据，不会改变 Cognition，也不会将命令名称检查提升为数值、物理或工程验证。

仅处理快照时：

```powershell
python mining_kernel.py validate-zotero-snapshot path/to/snapshot.json
python mining_kernel.py inspect-zotero-snapshot path/to/snapshot.json
```

明确选择本地文件时，只登记获准使用的材料：

```powershell
python mining_kernel.py register-local-material --project-root path/to/project path/to/decision.md --material-kind project_record --source-documents-claim claim-id
python mining_kernel.py register-local-material --project-root path/to/project path/to/reading-card.md --material-kind derived_reading_note
```

命令读取文件以计算 SHA-256，只写入 Asset、Evidence 与来源记录，不复制或编辑原文件。
材料种类决定其权威属性：派生笔记始终保留 `authority=derived`，调用方提供更强标签也不会改变这一点。
相对路径必须位于项目内部；外部文件须明确提供绝对调用路径，持久记录保存调用方标签，不保存绝对路径。
这些记录描述来源，不证明科学、数值或工程有效性。完全相同的请求可幂等重放，修改引用或 Claim 元数据则构成明确的操作冲突。

## 工作区约定

`--workspace` 指向用户自己的兼容工作区。
当前项目适配器预期在该根目录下使用相对路径，包括小型导航文件 `Workspace_Index/project_index.yaml` 及适配器对应的项目路径。
仓库只提供该布局的合成版本，不包含私人工作区或研究材料。

## Zotero 只读边界

Zotero 集成提供资料读取能力，不提供写入能力。
适配器不含 CREATE、UPDATE、DELETE 或 MERGE 操作，也不保存 MCP 凭据。
脱敏快照是本地输入，实时读取器是由调用方另行提供的能力；读取器缺失或失败时返回明确诊断。

允许的操作为：

```text
zotero_get_collections
zotero_get_collection_items
zotero_get_item_metadata
zotero_get_item_children
zotero_get_item_fulltext
zotero_search_items
zotero_read_pdf_pages
```

[资料研究工作流](docs/RESEARCH_SOURCES.md)通过明确登记的宿主 stdio 连接提供 `zotero-search` / `zotero-read`，
再用 `research-start` / `research-review` 对选定文献和文档观察形成带引用的 Markdown 分析。
它复用既有研究记录，区分资料覆盖范围与研究结论。

[Zotero 阅读工作流](docs/ZOTERO_READING.md)提供限定范围的外部元数据、页面读取结果及其向可选研究记录的明确写回。
`zotero-record` 导入来源身份、版本、页面覆盖和可选解释，不连接 Zotero，也不能证明来源刚被重新核验。
外部读取器仍由宿主提供；参见[离线合成示例](examples/zotero_reading/README.md)。

原始 PDF 和其他一手来源保留原始资料地位。
Zotero 元数据、快照、OCR、Markdown 和 MCP 响应是可重建的关联或阅读层，不能单独作为实验验证。

快照中的 `doi` 可选。导出的 DOI 会规范化为小写、无前缀形式；关系映射优先使用 DOI，再回退到标题和作者匹配。
DOI 属于元数据依据，不能证明来源身份、页面级支持或科学有效性。

## 安全与限制

- 仓库不含 Zotero 凭据、资料库数据库、全文正文、私人条目键或附件绝对路径。
- 公开快照与工作区是合成材料，不是整库示例。
- Zotero 适配器不提供网关、后台服务、下载器或全文索引。
- 仓库不分发 FLAC3D / Itasca 或其他专有软件，也不授予这些软件的许可。
- Schema 与 API 接口约定为版本 1，未来版本可能调整。

单独授权的 Zotero 写入提供方、自动发现或下载、OpenAlex / OAResolver、Docling、PaperQA2 和服务化等方向，
不属于本次发布范围，需要另行明确工作范围和验收记录。

## 许可证

Mining Research Kernel 使用 Apache License 2.0。
许可仅适用于本仓库有权发布的代码和文档。
Zotero、FLAC3D / Itasca 及其他第三方产品保留各自许可，本仓库不包含这些产品。
