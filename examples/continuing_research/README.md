# 同一问题下继续研究：合成示例

这个小示例演示两次独立会话：先保存一个证据不足的比较判断，之后补读一页、保留首轮判断并为同一个 ResearchQuestion 记录新判断，再从记录生成报告。所有论文标题、页面文字、来源、方法描述和结论都是编造的教学材料；它们不代表真实 AE 研究。

需要 Python 标准库。无需安装依赖、联网、配置密钥、连接 Zotero 或运行 Itasca 求解器。项目数据写进你指定的仓库外目录；不要把目录选在代码仓库里。

在 repo 根目录打开 PowerShell，先选择一个尚不存在或空的外部目录：

```powershell
$repoRoot = (Resolve-Path '.')
$project = Join-Path ([Environment]::GetFolderPath('MyDocuments')) 'MRK持续研究 demo'
& python -B -X utf8 (Join-Path $repoRoot '.\examples\continuing_research\demo.py') first --project-root $project
```

稍后在 repo 根目录开启一个新终端或新会话，重新设置相同路径，再续接并生成报告：

```powershell
$repoRoot = (Resolve-Path '.')
$project = Join-Path ([Environment]::GetFolderPath('MyDocuments')) 'MRK持续研究 demo'
& python -B -X utf8 (Join-Path $repoRoot '.\examples\continuing_research\demo.py') continue --project-root $project
```

报告和记录都在项目目录中。也可用现有 CLI 恢复过程、查看判断：

```powershell
& python -B -X utf8 (Join-Path $repoRoot '.\mining_kernel.py') research-progress --project-root $project --task-id synthetic-review-02
& python -B -X utf8 (Join-Path $repoRoot '.\mining_kernel.py') resume --project-root $project --task-id synthetic-review-02
```

如果首轮选了其他项目路径，后续继续使用那个路径。若从其他当前目录运行，先把 `$repoRoot` 设为本机 repo 根目录的绝对路径；随后仍用上面的 `Join-Path` 命令。

脚本可从其它当前工作目录调用。`first` 仅接受空目录；`continue` 只接受本示例固定的项目 ID、问题、任务和首轮记录，因此不能把普通研究项目传给它。重复 `continue` 会重放相同输入，不增加交易记录；报告由 `research-report --output` 从权威记录重建，报告本身是派生文件。

改用真实资料时，请从项目现有入口和用户授权开始，按[继续同一研究问题](../../docs/CONTINUING_RESEARCH.zh-CN.md)、[Zotero 页面阅读](../../docs/RESEARCH_SOURCES.md)及[文献比较](../../docs/LITERATURE_COMPARISON.md)流程读取并选择真实页面，再用返回的 Asset ID 开始或续接。不要把本例的合成 capture、ID 或结论当作真实来源记录。
