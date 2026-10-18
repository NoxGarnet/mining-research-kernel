"""Offline teaching data: CSV results, script context and recoverable comparison."""
from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path
import subprocess
import sys

REPO = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO))

from examples.script_review.demo import run_demo as create_script_context
from mining_research_kernel.result_comparison import import_result_csv, compare_results

TASK = "synthetic-result-comparison"
BASELINE = "point_id,value\nP1,-12.5\nP2,-8.0\nP3,\n"
CANDIDATE = "point_id,value\nP2,-7.0\nP1,-10.0\nP4,-6.0\n"


def metadata(case_id: str) -> dict:
    return {"case_id": case_id, "quantity": "displacement_y", "unit": "mm",
            "column_meanings": {"point_id": "Invented shared point label", "value": "Invented signed displacement"},
            "point_basis": "Authored teaching points; no actual monitoring location is represented",
            "conditions": {"stage": "synthetic post-excavation", "coordinate_frame": "synthetic y-positive convention",
                           "scheme": case_id}, "origin": "synthetic"}


def cli(root: Path, *args) -> str:
    result = subprocess.run([sys.executable, "-S", "-B", "-X", "utf8", str(REPO / "mining_kernel.py"),
                             *args, "--project-root", str(root)], capture_output=True, text=True,
                            encoding="utf-8", check=True)
    return result.stdout


def run_demo(value: str) -> dict:
    # Reuse the bounded script example's new/empty, external-directory guard.
    context = create_script_context(value)
    root = Path(context["project"])
    exports = root / "exports"
    exports.mkdir()
    paths = []
    for name, text in (("baseline", BASELINE), ("candidate", CANDIDATE)):
        source = exports / f"{name}.csv"
        source.write_text(text, encoding="utf-8")
        paths.append(source)
        (exports / f"{name}-metadata.json").write_text(
            json.dumps(metadata(name), ensure_ascii=False, indent=2), encoding="utf-8")
    protected = [*paths, root / "work/example.dat", root / "teaching-docs/flac3d/script-review-teaching.html"]
    before = {str(path): hashlib.sha256(path.read_bytes()).hexdigest() for path in protected}
    captures = []
    for name in ("baseline", "candidate"):
        result = import_result_csv(root, task_id=f"synthetic-result-{name}",
            question=f"Read authored {name} point values", csv_path=f"exports/{name}.csv",
            metadata=metadata(name), task_context="synthetic")
        captures.append(result["asset_refs"][0])
    compare_results(root, task_id=TASK, question="所选教学测点的两组数值相差多少？",
        baseline_asset_ref=captures[0], candidate_asset_ref=captures[1], point_ids=["P1", "P2", "P3"],
        comparability_note="仅按编写的点标签比较；这些CSV不是脚本或求解器的输出。",
        related_task_ids=["synthetic-script-review-01", "synthetic-assignment-reading"],
        next_action="由用户决定是否另选真实导出表，补充测点与工况依据。", task_context="synthetic")
    progress = json.loads(cli(root, "result-progress", "--task-id", TASK))
    if progress.get("task_packet", {}).get("task_id") != TASK:
        raise RuntimeError("fresh-process recovery returned a different task")
    cli(root, "result-report", "--task-id", TASK, "--output", "reports/result-comparison.md")
    if before != {str(path): hashlib.sha256(path.read_bytes()).hexdigest() for path in protected}:
        raise RuntimeError("an input changed during the example")
    with (root / "START.md").open("a", encoding="utf-8") as stream:
        stream.write(f"\n## 合成结果比较\n\n任务：`{TASK}`；仅选P1、P2、P3。\n\n"
                     "报告：[数值比较](reports/result-comparison.md)。\n\n"
                     "P1与P2可作教学算术对照，P3保持不足；背景关联不能证明CSV由脚本产生。\n\n"
                     "接续：使用 result-progress 恢复该任务。用户决定后续范围。\n")
    return {"task_id": TASK, "project": str(root), "report": "reports/result-comparison.md",
            "capture_asset_refs": captures, "synthetic": True, "source_unchanged": True,
            "fresh_process_recovery": True, "run_created": False, "verification_created": False}


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("project_root", help="new or empty directory outside the repository")
    args = parser.parse_args()
    try:
        print(json.dumps(run_demo(args.project_root), ensure_ascii=False, indent=2))
    except (OSError, ValueError, subprocess.CalledProcessError) as exc:
        parser.exit(2, f"{exc}\n")
