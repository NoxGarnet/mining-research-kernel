"""Offline, explicitly synthetic script-review example; never executes FLAC3D."""
from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path
import subprocess
import sys

REPO = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO))

from mining_research_kernel.artifacts import _absolute_without_follow, _reject_reparse_chain
from mining_research_kernel.documentation_reading import record_documentation_reading
from mining_research_kernel.script_review import start_script_review, record_script_review
from research_project import enable_research

PAGE = "flac3d/script-review-teaching.html"
TASK = "synthetic-script-review-01"
SCRIPT = "; Synthetic teaching excerpt; never executed.\n; No mesh or material properties supplied.\nzone cmodel assign elastic\n"
HTML = """<!doctype html><html><head><title>Synthetic fixture: Itasca Software 9.6 documentation</title>
<script>DOCUMENTATION_OPTIONS = {VERSION: '9.6.44'};</script></head>
<body><main><section id="assign-elastic">
<h1>Synthetic assignment explanation</h1><p>This authored teaching paragraph
describes zone cmodel assign elastic as selecting an elastic constitutive model.
It is not an official manual or evidence of a valid numerical model.</p>
</section></main></body></html>"""


def run_demo(value: str) -> dict:
    root = _absolute_without_follow(Path(value).expanduser())
    _reject_reparse_chain(root, "demo directory")
    resolved, repo = root.resolve(), REPO.resolve()
    if resolved == repo or repo in resolved.parents or resolved in repo.parents:
        raise ValueError("choose a new or empty directory outside the code repository")
    if root.exists() and (not root.is_dir() or any(root.iterdir())):
        raise ValueError("demo directory must be new or empty; existing materials are never replaced")
    root.mkdir(parents=True, exist_ok=True)
    enable_research(root, "script-review-synthetic-demo")
    (root / "START.md").write_text(
        "# 合成脚本审阅示例\n\n仅演示记录，不运行 FLAC3D。\n\n"
        f"任务：`{TASK}`；范围：`work/example.dat` 第3行。\n\n"
        "报告：[审阅记录](reports/script-review.md)。\n\n"
        "接续：使用 script-review-progress 恢复该任务；用户决定后续范围。\n",
        encoding="utf-8")
    script = root / "work/example.dat"
    script.parent.mkdir()
    script.write_text(SCRIPT, encoding="utf-8")
    original_hash = hashlib.sha256(script.read_bytes()).hexdigest()
    document = root / "teaching-docs" / PAGE
    document.parent.mkdir(parents=True)
    document.write_text(HTML, encoding="utf-8")
    registration = root / "teaching-registration.local.json"
    registration.write_text(json.dumps({
        "schema_version": 1, "source_id": "synthetic.script.review.docs",
        "root": str(root / "teaching-docs"), "product": "flac3d",
        "document_family": "9.6", "document_build": "9.6.44", "trust_class": "synthetic",
        "product_subdir": "flac3d", "pages": {PAGE: hashlib.sha256(document.read_bytes()).hexdigest()},
    }), encoding="utf-8")
    reading = record_documentation_reading(
        root, task_id="synthetic-assignment-reading", question="Read the authored teaching paragraph.",
        registration=registration, page=PAGE, anchor="assign-elastic", product="flac3d",
        product_version="9.6.44", task_context="synthetic")
    packet = reading["task_packet"]
    start_script_review(root, task_id=TASK, question="Compare the selected teaching line and paragraph.",
                        script="work/example.dat", start_line=3, end_line=3, product_version="9.6.44",
                        documentation_asset_refs=packet["asset_refs"], task_context="synthetic")
    record_script_review(root, task_id=TASK, operation_id="synthetic-script-note", review={
        "summary": "合成片段与教学段落的有限对照；没有运行模型。",
        "findings": [{"start_line": 3, "end_line": 3,
                      "statement": "第3行使用 zone cmodel assign elastic；教学段落给出相应的弹性赋值解释。",
                      "documentation_evidence_refs": packet["evidence_refs"]}],
        "gaps": ["资料为编写的合成教学内容，不能证明官方语法或工程适用性。", "未检查参数、选区或模型上下文。"],
        "next_action": "用户决定是否另建真实项目，选取匹配版本的官方资料开展审阅。"})
    # A new CLI process recovers solely from persisted records.
    common = [sys.executable, "-S", "-B", "-X", "utf8", str(REPO / "mining_kernel.py")]
    recovered = subprocess.run(common + ["script-review-progress", "--project-root", str(root),
                                         "--task-id", TASK], capture_output=True, text=True,
                               encoding="utf-8", check=True)
    json.loads(recovered.stdout)
    subprocess.run(common + ["script-review-report", "--project-root", str(root), "--task-id", TASK,
                              "--output", "reports/script-review.md"], capture_output=True, text=True,
                   encoding="utf-8", check=True)
    if hashlib.sha256(script.read_bytes()).hexdigest() != original_hash:
        raise RuntimeError("source script changed unexpectedly")
    return {"task_id": TASK, "project": str(root), "report": "reports/script-review.md",
            "synthetic": True, "source_unchanged": True, "fresh_process_recovery": True,
            "run_created": False, "verification_created": False}


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("project_root", help="new or empty directory outside the code repository")
    args = parser.parse_args()
    try:
        print(json.dumps(run_demo(args.project_root), ensure_ascii=False, indent=2))
    except (OSError, ValueError, subprocess.CalledProcessError) as exc:
        parser.exit(2, f"{exc}\n")
