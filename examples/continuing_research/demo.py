"""Two-session, synthetic continuing-research example for Mining Research Kernel."""
from __future__ import annotations

import argparse
import hashlib
from pathlib import Path
import subprocess
import sys

REPO = Path(__file__).resolve().parents[2]
if str(REPO) not in sys.path:
    sys.path.insert(0, str(REPO))

from mining_research_kernel.literature_comparison import record_literature_comparison
from mining_research_kernel.records import ResearchStore
from mining_research_kernel.research_continuation import begin_research, continue_research
from mining_research_kernel.zotero_records import record_zotero_reading
from mining_research_kernel.artifacts import _absolute_without_follow, _reject_reparse_chain
from research_project import enable_research, load_config

PROJECT_ID = "continuing-research-synthetic-demo"
QUESTION = "在已读页面范围内，两项合成 AE 研究报告了哪些方法与试验条件？"
FIRST_TASK = "synthetic-review-01"
NEXT_TASK = "synthetic-review-02"
FIRST_ASSET_TASKS = ("synthetic-paper-01", "synthetic-paper-02")
MORE_TASK = "synthetic-paper-02-methods"
REPORT = "reports/continuing-research.md"


def _safe_root(value: str) -> Path:
    root = _absolute_without_follow(Path(value).expanduser())
    _reject_reparse_chain(root, "demo project root")
    repo = REPO.resolve()
    resolved = root.resolve(strict=False)
    if resolved == repo or repo in resolved.parents or resolved in repo.parents:
        raise ValueError("choose a project directory outside the repository")
    return resolved


def _capture(number: int, *, methods_page: bool = False) -> dict:
    page_text = (
        "Synthetic page: an invented AE method uses a two-sensor arrangement; "
        "test conditions are not specified."
        if methods_page else
        f"Synthetic page: invented mining AE study {number}; methods and conditions are not reported here."
    )
    key = f"SYN{number:05d}"
    attachment = f"ATT{number:05d}"
    page = 14 if methods_page else 3
    return {
        "schema_version": 1, "kind": "zotero_reading_capture", "origin": "synthetic",
        "instance_id": "0123456789abcdef0123456789abcdef", "library_id": "users/12345",
        "captured_at": "2026-10-18T00:00:00Z",
        "item": {"key": key, "version": None, "title": f"合成 AE 研究示例 {number}",
                 "item_type": "journalArticle", "doi": None},
        "collection_key": None, "metadata_status": "read",
        "pages": [{"attachment_key": attachment, "attachment_version": 2 if methods_page else 1,
                    "start_page": page, "end_page": page, "status": "read",
                    "text_sha256": hashlib.sha256(page_text.encode("utf-8")).hexdigest(),
                    "excerpt": page_text}],
        "diagnostics": [],
    }


def _asset_for(root: Path, task_id: str) -> str:
    state = ResearchStore(root).latest_record(task_id, "TaskState")
    refs = state.get("packet", {}).get("asset_refs", []) if state else []
    if len(refs) != 1:
        raise ValueError(f"expected one saved synthetic Asset for {task_id}")
    return refs[0]


def _record_reading(root: Path, task_id: str, number: int, *, methods_page: bool = False) -> str:
    result = record_zotero_reading(root, task_id=task_id,
        question="合成教学材料：仅记录本页 capture 的内容。", capture=_capture(number, methods_page=methods_page),
        task_context="synthetic")
    return result["task_packet"]["asset_refs"][0]


def _comparison(started: dict, *, continued: bool) -> dict:
    comparison = started["comparison_template"]
    comparison["summary"] = (
        "合成补读页描述了一个双传感器 AE 方法；本页仍未给出试验条件。"
        if continued else
        "两篇合成页面都没有报告方法或试验条件，当前比较不足以形成具体结论。"
    )
    comparison["next"] = "用户可选择读取更多合成页面；本示例不代表真实文献结论。"
    comparison["limitations"] = ["材料、页面与解释均为合成教学内容。", "仅覆盖已保存页面；科学结论未核验。"]
    if continued:
        row = next(row for row in comparison["sources"] if row["asset_ref"] == started["task_packet"]["asset_refs"][1])
        evidence = next(source["evidence_refs"][0] for source in started["sources"]
                        if source["asset_ref"] == row["asset_ref"])
        row["dimensions"]["methods"] = {
            "status": "reported", "value": "合成页面描述双传感器布置。",
            "interpretation": "该描述仅是虚构页面中的读法，未作外部核验。",
            "citations": [{"evidence_id": evidence, "attachment_key": "ATT00002",
                           "page_range": {"start_page": 14, "end_page": 14}}],
        }
        comparison["summary_cells"] = [{"asset_ref": row["asset_ref"], "dimension": "methods"}]
    return comparison


def _check_demo_project(root: Path) -> None:
    config = load_config(root)
    if config.get("project_id") != PROJECT_ID:
        raise ValueError("project_id does not identify this synthetic demo project")
    store = ResearchStore(root)
    state = store.latest_record(FIRST_TASK, "TaskState")
    if not state:
        raise ValueError("the first demo session is missing; run 'first' on a new project directory")
    packet = state.get("packet", {})
    question_id = packet.get("input", {}).get("research_question_id")
    question = store.latest_record(question_id, "ResearchQuestion") if question_id else None
    if (question is None or question.get("statement") != QUESTION
            or packet.get("task_context") != "synthetic"
            or packet.get("input", {}).get("review_mode") != "literature_comparison"
            or packet.get("input", {}).get("review_question") != QUESTION
            or packet.get("input", {}).get("dimensions") != ["methods", "conditions"]
            or len(packet.get("asset_refs", [])) != 2
            or state.get("state") != "completed"):
        raise ValueError("saved first session does not match this demo's task, question and inputs")
    for index, task_id in enumerate(FIRST_ASSET_TASKS, 1):
        asset_ref = _asset_for(root, task_id)
        asset = store.latest_record(asset_ref, "Asset")
        capture = (asset or {}).get("payload", {}).get("request", {}).get("capture")
        if asset_ref != packet["asset_refs"][index - 1] or capture != _capture(index):
            raise ValueError("saved source captures do not match this demo's synthetic inputs")
    decision = store.latest_record(packet.get("review_record_ref"), "Decision")
    comparison = (decision or {}).get("assessment", {}).get("literature_comparison", {})
    if (not decision or decision.get("judgment", {}).get("status") != "INSUFFICIENT"
            or comparison.get("summary") != "两篇合成页面都没有报告方法或试验条件，当前比较不足以形成具体结论。"
            or any(cell.get("status") != "not_reported_in_read_scope"
                   for row in comparison.get("sources", [])
                   for cell in row.get("dimensions", {}).values())):
        raise ValueError("saved first session lacks this demo's expected insufficient judgment")


def _write_entry(root: Path) -> None:
    content = f"""# 合成持续研究示例

本项目的论文页面、来源和结论全部是编造的教学材料，不代表真实研究。首轮任务 `{FIRST_TASK}` 保存了“{QUESTION}”的证据不足判断。

在 MRK repo 根目录开启后续会话，将 `$project` 设置为本项目目录，再运行：

```powershell
python -B -X utf8 .\\examples\\continuing_research\\demo.py continue --project-root $project
```

续接后从记录恢复进度：

```powershell
python -B -X utf8 .\\mining_kernel.py research-progress --project-root $project --task-id {NEXT_TASK}
python -B -X utf8 .\\mining_kernel.py research-report --project-root $project --task-id {NEXT_TASK}
```

记录是权威来源；`{REPORT}` 是可从记录重建的派生报告。
"""
    with (root / "START.md").open("x", encoding="utf-8", newline="\n") as stream:
        stream.write(content)


def first(root: Path) -> None:
    if root.exists():
        if not root.is_dir() or any(root.iterdir()):
            raise ValueError("first session requires a new or empty project directory")
    else:
        root.mkdir(parents=True)
    _write_entry(root)
    enable_research(root, PROJECT_ID)
    assets = [_record_reading(root, task, index) for index, task in enumerate(FIRST_ASSET_TASKS, 1)]
    started = begin_research(root, task_id=FIRST_TASK, question=QUESTION, asset_refs=assets,
                             dimensions=["methods", "conditions"], task_context="synthetic")
    record_literature_comparison(root, task_id=FIRST_TASK, operation_id="synthetic-review-01.record",
                                 comparison=_comparison(started, continued=False), judgment_status="INSUFFICIENT")
    print(f"首轮合成判断已保存：{FIRST_TASK}（INSUFFICIENT）。\n下一会话运行 continue --project-root \"{root}\"。")


def continue_demo(root: Path) -> None:
    if not root.is_dir():
        raise ValueError("project directory does not exist; run 'first' first")
    _check_demo_project(root)
    extra = _record_reading(root, MORE_TASK, 2, methods_page=True)
    original = [_asset_for(root, task) for task in FIRST_ASSET_TASKS]
    selected = [original[0], extra]
    started = continue_research(root, task_id=NEXT_TASK, from_task_id=FIRST_TASK, asset_refs=selected,
                                reason="补读第二项合成研究的方法页，保留首轮判断并更新同一问题。")
    record_literature_comparison(root, task_id=NEXT_TASK, operation_id="synthetic-review-02.record",
                                 comparison=_comparison(started, continued=True))
    command = [sys.executable, "-B", "-X", "utf8", str(REPO / "mining_kernel.py"),
               "research-report", "--project-root", str(root), "--task-id", NEXT_TASK,
               "--output", REPORT]
    subprocess.run(command, cwd=Path.cwd(), check=True)
    print(f"同一问题的合成续接已保存：{NEXT_TASK}。报告：{root / REPORT}")


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("stage", choices=("first", "continue"))
    parser.add_argument("--project-root", required=True, help="用户选择的仓库外项目目录")
    args = parser.parse_args(argv)
    try:
        root = _safe_root(args.project_root)
        if args.stage == "first":
            first(root)
        else:
            continue_demo(root)
    except (OSError, ValueError, subprocess.CalledProcessError) as exc:
        parser.exit(2, f"拒绝或失败：{exc}\n")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
