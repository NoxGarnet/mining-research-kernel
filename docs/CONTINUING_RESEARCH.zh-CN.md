# 围绕同一个问题持续研究

**简体中文** | [English](CONTINUING_RESEARCH.md) · [返回首页](../README.md)

本指南提供中英文版本；链接到的其他指南目前主要为英文。

把问题和材料位置交给 Agent，或指定已有任务。例如：

> 继续上次的 AE 方法比较，补读第二篇的方法部分。保留原判断，说明新增依据改变了什么，并生成一份能继续使用的 Markdown 报告。

Agent 在用户约定的范围内执行下面的流程，用户不需要准备 CLI 命令或比较用 JSON。
普通 Markdown 项目仍可沿用原有入口；只有持久记录对任务有帮助时才启用。

首次离线体验可使用[两次会话的合成示例](../examples/continuing_research/README.md)。
它提供少量编写的论文页面，演示完整流程，无需安装资料连接或准备比较 JSON。

## Agent 工作流程

1. 恢复研究问题、选定任务和最新已记录判断。先查看项目入口与已有授权，只询问影响工作的关键待决定事项。目标、边界和完成条件由用户决定。
2. 确定具体的依据缺口，通过已有的 [Zotero 阅读](RESEARCH_SOURCES.md)或[软件文档阅读](ITASCA_READING.md)读取所需页面或段落。保留读取失败和版本未知信息；继承的观察不是本次新读取的来源。
3. 从指定的、已有判断的任务续接，选定本轮全部有效来源，包括新增读取结果和仍相关的旧观察。同一论文的新 capture 可以替换本轮选中的旧 capture，旧任务仍保留原来的记录。
4. 阅读返回的来源，写出比较或带引用的解释，通过已有审查命令保存。保留当前阅读范围内的未知条件及科学、工程限制。新摘要应依据实际证据解释判断变化，不能假定多读几页就必然得到更强结论。
5. 从已保存记录生成可读报告。项目入口保持简短，链接当前任务和派生报告。下一步在用户选择或已有授权覆盖之前，仍然是建议。

## Agent 调用示例

下面的命令是 Agent 的工具接口。资料读取配置见相应指南；本流程不会安装运行时、配置模型或执行求解器。

使用实际读取命令返回的 Asset ID 开始一次比较：

```powershell
$projectRoot = 'D:\replace-with-user-chosen\study'
python -B -X utf8 mining_kernel.py research-begin --project-root $projectRoot --task-id ae-step-01 --question "Which methods and conditions are reported in these selected readings?" --asset-ref paper-a.asset.1 --asset-ref paper-b.asset.1 --dimension conditions --dimension methods
```

`research-begin` 默认进行至少两篇不同论文的[文献比较](LITERATURE_COMPARISON.md)。
如果要对一份或多份已选论文、文档观察形成带引用的 Markdown 分析，可选 `--mode sources`。
返回结果包含来源概览和相应审查模板；Agent 按实际阅读填写，再用 `literature-review` 或 `research-review` 保存。

保存首轮判断后，通过 `zotero-read` 在新的阅读任务 ID 下补读页面，再继续比较：

```powershell
python -B -X utf8 mining_kernel.py research-continue --project-root $projectRoot --from-task ae-step-01 --task-id ae-step-02 --asset-ref paper-a.asset.1 --asset-ref paper-b-more.asset.1 --reason "补读第二篇方法页，核查上轮缺失的方法和试验条件"
```

请把示例 ID 替换为实际选定的记录。省略 `--asset-ref` 时，复用此前选定的来源，不重新读取。
研究问题、审查模式、比较维度和上下文会被继承；问题改变时，应另起一个研究问题。
此前通过 `literature-start` 或 `research-start` 建立的兼容任务也可以续接。

后续任务共用原 ResearchQuestion，绑定前一个 TaskState / Decision 的准确修订，并保留历史记录。
重复同一请求只会恢复任务，不会重置已完成的审查；在同一任务 ID 下改变输入则构成冲突。
审查本身仍须明确执行，并使用项目内唯一的操作 ID。

## 恢复进展与生成报告

开启新会话时，把项目路径和指定任务交给 Agent。
它可以先用 `project-context` 和 `resume` 恢复信息，再按返回的 argv 展开指定问题的进展或生成报告。
待分析的续接任务还没有新的当前判断；继承的 Decision 明确标记为历史上下文，并绑定续接创建时的准确修订。
之后独立增加的父 Decision 修订不会替换这份历史上下文。
来源读取观察和兄弟研究任务，也不会只因为被新任务引用就变成相互冲突的当前判断。

Agent 提出下一步前，应展开继承判断的范围与缺口。
建议补读某份资料，不代表用户已同意新任务；一次资料审查完成，也不代表整个研究项目完成。

```powershell
python -B -X utf8 mining_kernel.py research-progress --project-root $projectRoot --task-id ae-step-02
python -B -X utf8 mining_kernel.py research-report --project-root $projectRoot --task-id ae-step-02
python -B -X utf8 mining_kernel.py research-report --project-root $projectRoot --task-id ae-step-02 --output results/ae-research.md
```

进展恢复与报告生成只读取已保存记录，不连接来源，也不创建新事务。
指定任务决定读取哪一条历史分支；不会静默把兄弟续接任务选为最新结论。
待分析步骤会明确显示为待分析，并与之前已记录的判断区分。

Markdown 报告包含研究问题、有范围限定的判断、比较结果、来源引用与阅读覆盖、剩余缺口、历史变化及待用户决定事项。
新增或移除来源 ID 属于记录层面可直接观察的变化；Agent 对其研究意义的解释仍是暂定判断。
报告保留官方本地文档、社区 MCP 语料和论文实际已读页面之间的区别。

不带 `--output` 时，Markdown 输出到标准输出。
明确指定输出时，必须选择项目内独立的 Markdown 文件；写入器会保护已有项目入口、登记材料和不属于本任务生成的文件。
再次导出到本任务自己的生成文件时，会从记录重新生成派生视图。
后续更新应写入权威记录，不把手工编辑的报告作为另一份当前判断。
本流程不创建求解器 Run，也不创建工程 Verification。
