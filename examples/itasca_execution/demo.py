"""Authored external-task observations; does not import or call an Itasca engine."""
from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path
import subprocess
import sys

REPO = Path(__file__).resolve().parents[2]


def run_demo(project):
    root = Path(project).resolve()
    if root == REPO or REPO in root.parents or (root.exists() and any(root.iterdir())):
        raise ValueError("choose a new or empty output directory outside the code repository")
    inputs, outputs = root / "inputs", root / "outputs"
    inputs.mkdir(parents=True)
    outputs.mkdir()
    calls = []

    def write(name, value):
        path = inputs / name
        path.write_text(json.dumps(value, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
        return path

    def cli(*args, markdown=False):
        command = [sys.executable, "-S", "-B", "-X", "utf8", str(REPO / "mining_kernel.py"), *map(str, args)]
        result = subprocess.run(command, cwd=REPO, capture_output=True, text=True, encoding="utf-8")
        calls.append({"args": list(map(str, args)), "exit_code": result.returncode})
        (root / "cli-calls.json").write_text(json.dumps(calls, indent=2) + "\n", encoding="utf-8")
        if result.returncode:
            raise RuntimeError(result.stdout + result.stderr)
        return result.stdout if markdown else json.loads(result.stdout)

    cli("enable-research", "--project-root", root, "--project-id", "itasca.teaching")
    script = inputs / "fixture.py"
    script.write_text("print('Authored teaching fixture; no engine was invoked.')\n", encoding="utf-8")
    plan = write("plan.json", {
        "software": "flac3d", "product_version": "9.6.44", "purpose": "Authored external-task teaching example.",
        "stop_conditions": ["Synthetic inputs and responses only; never submit this teaching task."],
        "output_root": "outputs", "engine_session": "offline-teaching-session", "origin": "synthetic"})
    prepared = cli("itasca-run-prepare", "--project-root", root, "--run-id", "teaching",
                   "--script", "inputs/fixture.py", "--metadata-file", plan, "--task-context", "synthetic")
    run_ref = prepared["run_ref"]["id"]

    def observe(name, phase, status):
        return write(name + ".json", {
            "schema_version": 1, "kind": "itasca_execution_observation", "origin": "synthetic",
            "captured_at": "2026-10-19T00:00:00Z", "phase": phase,
            "tool_result": {"ok": True, "data": {
                "task_id": "a1b2c3", "task_status": status, "entry_script": script.as_posix(),
                "description": "Authored offline teaching response.",
                "output": "Synthetic teaching log; no model was run.",
                "pagination": {"total_lines": 1, "line_range": "1-1"}}}})

    for name, phase, status in (("submission", "submission", "pending"), ("finished", "status", "completed")):
        path = observe(name, phase, status)
        cli("itasca-run-record", "--project-root", root, "--run-id", "teaching",
            "--operation-id", name, "--observation", path)
    imported = []
    for name, value in (("baseline", 1), ("candidate", 2)):
        path = outputs / (name + ".csv")
        path.write_bytes(f"point_id,value\ntotal,{value}\n".encode())
        cli("itasca-output-import", "--project-root", root, "--run-id", "teaching",
            "--operation-id", "capture-" + name, "--path", "outputs/" + path.name, "--kind", "csv")
        metadata = write(name + "-metadata.json", {
            "case_id": name, "quantity": "authored count", "unit": "1", "point_basis": "authored same teaching point",
            "column_meanings": {"point_id": "teaching point label", "value": "authored count"},
            "conditions": {"scope": "synthetic teaching only"}, "origin": "synthetic"})
        imported.append(cli("result-import", "--project-root", root, "--task-id", name,
            "--question", "Capture authored teaching CSV", "--csv", path, "--metadata-file", metadata,
            "--run-ref", run_ref, "--task-context", "synthetic"))
    # The existing result workflow remains the comparison authority.
    cli("result-compare", "--project-root", root, "--task-id", "compare", "--question", "Compare authored counts",
        "--baseline-asset-ref", imported[0]["asset_refs"][0], "--candidate-asset-ref", imported[1]["asset_refs"][0],
        "--point", "total", "--comparability-note", "Identical authored entity and declared unit; synthetic only.",
        "--task-context", "synthetic")
    report = cli("itasca-run-report", "--project-root", root, "--run-id", "teaching", markdown=True)
    records = root / "research" / "records"
    digests = lambda: {p.name: hashlib.sha256(p.read_bytes()).hexdigest() for p in records.glob("*.json")}
    before = digests()
    inputs.rename(root / "archived-inputs")
    outputs.rename(root / "archived-outputs")
    progress = cli("itasca-run-progress", "--project-root", root, "--run-id", "teaching")
    assert report == cli("itasca-run-report", "--project-root", root, "--run-id", "teaching", markdown=True)
    cli("itasca-run-report", "--project-root", root, "--run-id", "teaching", "--output", "reports/execution.md")
    cli("result-report", "--project-root", root, "--task-id", "compare", "--output", "reports/comparison.md")
    assert before == digests()
    result = {"context": "synthetic", "run_ref": run_ref, "status": progress["status"],
              "engine_called": False, "fresh_process_recovery_after_inputs_and_outputs_move": True,
              "ledger_unchanged_during_recovery": True, "reports": ["reports/execution.md", "reports/comparison.md"]}
    (root / "demo-result.json").write_text(json.dumps(result, indent=2) + "\n", encoding="utf-8")
    return result


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", required=True, type=Path)
    print(json.dumps(run_demo(parser.parse_args().output), indent=2))
