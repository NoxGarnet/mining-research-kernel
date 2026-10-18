# 建立轻量工作区

**简体中文** | [English](START_WORKSPACE.md) · [返回首页](../README.md)

本指南提供中英文版本；链接到的其他指南目前主要为英文。

从一个实际研究问题开始，选择仓库外的新目录或空目录。
初始化命令只创建 `AGENTS.md`、`INDEX.md` 和 `projects/<ID>/START.md` 三个文件。

```powershell
$starterRoot = 'D:\replace-with-user-chosen\mining'
python -B -X utf8 .\mining_kernel.py init-workspace $starterRoot --project-id roadway-support --question "核查现有巷道支护模型的安装时序"
python -B -X utf8 .\mining_kernel.py workspace-context --workspace-root $starterRoot
```

请把示例路径替换为你自己选定的、代码仓库外的新目录或空目录，不要指向已有研究材料。
如果项目已经存在，请使用[已有项目接入指南](EXISTING_PROJECT.md)，保留现有文件，只补齐缺失的接续说明。

创建新项目时，`--project-id` 是长度为 2–64 个字符的小写标识，例如 `flac3d`、`pfc` 或 `ae`。
这条创建规则不限制已有项目的文件夹名称：`workspace-context` 也支持安全的 `PFC`、`AE`、中文名称和带空格名称。

初始入口只把研究问题记为文本。软件及版本仍未知，输入尚未定位；命令和模板都不代表已经分析过资料。
`workspace-context` 只读取有大小上限的根索引，报告识别出的项目候选，并为每个项目返回 `project-context` 参数数组（argv）。
用户选择项目后，再运行对应入口，例如：

```powershell
python -B -X utf8 .\mining_kernel.py project-context --project-root (Join-Path $starterRoot 'projects\roadway-support')
```

本次任务交付什么、边界在哪里、何时完成或交接，由用户决定。
先从对话和项目入口恢复已经明确的决定。只有影响当前工作的关键事项不清楚时，才简短询问，
例如“这次希望交付什么？”或“有哪些内容明确不在本次范围内？”。
完成标准可以在推进中补充，不要求用户先填完整表格，也不重复确认已经决定的事项。
不依赖这些待决定事项的已授权工作应继续进行。

需要时，在 `START.md` 中用普通文本区分用户已确认的决定、Agent 建议和待决定问题。
只记录与项目相关的内容；它们不是必填字段，也不是调用 CLI 的前置条件。
例如，用户已确认一次有限范围核查后，可以写成：

```markdown
## 范围与决定（按需）
用户已确认：交付所提供脚本的支护安装时序核查报告，列出依据与限制。
本次工作范围是文件和文档核查。
Agent 建议：如果后续有帮助，可另外做求解结果比较。
待决定：是否开展该比较；它不阻塞本次核查报告。
```

Agent 可以提出下一步并执行已授权工作，但建议本身不是用户决定。
用户之后调整目标时，应记录调整，并按双方约定的范围判断任务是否完成。
范围之外或用户明确推迟的事项可以留在交接说明中；发现这些事项不会自动扩大任务或增加完成要求。
如果缺口会阻止约定交付，则仍须保留并报告。

完成已授权工作后，把有实质变化的内容写回该项目的 `START.md`，例如：

```markdown
## 当前理解
所提供模型的安装时序记录在 `model/main.dat` 中（尚未独立核查）。

## 缺口与下一步
FLAC3D 版本未知。在约定的核查范围内，先从已提供文件识别版本，
或询问用户，再对照对应版本官方文档检查相关命令及参数。
```

已有项目可以按需直接编辑入口，采用这些说明。
重新运行 `init-workspace` 不是更新或迁移已有项目的方式。

普通查阅没有实质变化时，不必为此新建研究记录或写回文件。
已有用户授权在其原定范围内继续有效。只有确实出现更多项目或知识入口时，才增加相应链接。
索引用于导航，项目状态和证据留在项目内。

需要持久保存问题与判断时，可[明确启用研究记录](OPTIONAL_RESEARCH.md)；普通 Markdown 项目不要求这一步。
现有 FLAC3D 内核配置仍可使用，无需迁移。
需要围绕同一问题补读、更新判断和生成报告时，参见[持续研究指南](CONTINUING_RESEARCH.zh-CN.md)。
合成工作流只演示内核机制，不是 PFC、AE 或真实 FLAC3D 求解。
