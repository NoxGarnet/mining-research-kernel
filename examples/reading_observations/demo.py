"""Offline teaching observations through the public CLI; no source reader."""
from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path
import subprocess
import sys
import tempfile

REPO = Path(__file__).resolve().parents[2]
QUESTION = "How are parameter sources and validation described in these teaching observations?"


def observation(source_id, *, extra=False):
    """Authored fixture, not a reading of a real paper or PDF."""
    a = source_id == "teaching-a"
    text = ("The teaching example attributes parameters to laboratory measurements."
            if a else "The teaching example describes a model, but the selected introduction omits parameter sources.")
    passages = [{"locator": {"kind": "pdf_pages", "value": "PDF page 1", "start_page": 1, "end_page": 1}
                 if a else {"kind": "section", "value": "Introduction"},
                 "status": "read", "text_sha256": hashlib.sha256(text.encode()).hexdigest(),
                 "excerpt": text, "limitations": ["Authored teaching content; no experiment was performed."]}]
    if extra:
        text = "The teaching methods section attributes parameters to an earlier publication; independent validation is not specified."
        passages.append({"locator": {"kind": "section", "value": "Methods"}, "status": "read",
                         "text_sha256": hashlib.sha256(text.encode()).hexdigest(), "excerpt": text,
                         "limitations": ["This authored section does not establish independent validation."]})
    return {"schema_version": 1, "kind": "reading_observation", "origin": "synthetic",
            "captured_at": "2026-10-19T00:00:00Z",
            "source": {"source_id": source_id, "title": "Teaching paper " + source_id,
                       "doi": None, "url": None if a else "https://example.invalid/teaching-b",
                       "version": None, "source_kind": "local_pdf" if a else "web_article",
                       "source_sha256": None, "authority": "derived"},
            "reader": {"tool": "offline teaching fixture", "method": "text"},
            "passages": passages,
            "limitations": ["Synthetic teaching observation; no real paper was read.",
                            "Original-source version and file digest are unknown."]}


def run_demo(project):
    project = Path(project).resolve()
    if project.exists() and any(project.iterdir()):
        raise ValueError("choose a new or empty directory outside the code repository")
    if project == REPO or REPO in project.parents:
        raise ValueError("example output must stay outside the code repository")
    project.mkdir(parents=True, exist_ok=True)
    inputs = project / "inputs"
    inputs.mkdir()
    calls = []

    def write(name, data):
        path = inputs / name
        path.write_text(json.dumps(data, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
        return path

    def cli(*args, markdown=False):
        command = [sys.executable, "-S", "-B", "-X", "utf8", str(REPO / "mining_kernel.py"), *map(str, args)]
        result = subprocess.run(command, cwd=REPO, text=True, encoding="utf-8", capture_output=True)
        calls.append({"args": list(map(str, args)), "returncode": result.returncode})
        (project / "cli-calls.json").write_text(json.dumps(calls, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
        if result.returncode:
            raise RuntimeError(result.stdout + result.stderr)
        return result.stdout if markdown else json.loads(result.stdout)

    cli("enable-research", "--project-root", project, "--project-id", "reading.observation.demo")
    assets = []
    for name, source, extra in (("a", "teaching-a", False), ("b", "teaching-b", False), ("b-more", "teaching-b", True)):
        path = write(name + ".json", observation(source, extra=extra))
        result = cli("reading-record", "--project-root", project, "--observation-id", name, "--observation", path,
                     "--task-context", "synthetic")
        assets.append(result["asset_ref"])

    def comparison(started, *, more):
        value = started["comparison_template"]
        value["summary"] = ("The additional methods observation distinguishes measured inputs from literature inputs; validation remains unspecified."
                            if more else "A reports laboratory inputs; B's selected introduction leaves parameter provenance unknown.")
        value["limitations"] = ["Authored synthetic materials only; no scientific validation.",
                                "All claims are limited to the selected saved observations."]
        value["next"] = "The user can decide whether another reading is useful."
        for index, source in enumerate(started["sources"]):
            if index == 1 and not more:
                continue
            locator = "PDF page 1" if index == 0 else "Methods"
            value["sources"][index]["dimensions"]["methods"] = {
                "status": "reported", "value": "laboratory inputs" if index == 0 else "literature inputs",
                "interpretation": "Interpretation of this authored teaching passage.",
                "citations": [{"evidence_id": source["evidence_refs"][0], "locator": locator}]}
        return value

    first = cli("research-begin", "--project-root", project, "--task-id", "first",
                "--question", QUESTION, "--asset-ref", assets[0], "--asset-ref", assets[1],
                "--dimension", "methods", "--task-context", "synthetic")
    first_input = write("first-comparison.json", comparison(first, more=False))
    cli("literature-review", "--project-root", project, "--task-id", "first", "--operation-id", "first-review",
        "--comparison-file", first_input)
    historical = cli("research-report", "--project-root", project, "--task-id", "first", markdown=True)
    second = cli("research-continue", "--project-root", project, "--from-task", "first", "--task-id", "second",
                 "--asset-ref", assets[0], "--asset-ref", assets[2], "--reason", "Add the authored methods observation for paper B.")
    second_input = write("second-comparison.json", comparison(second, more=True))
    cli("literature-review", "--project-root", project, "--task-id", "second", "--operation-id", "second-review",
        "--comparison-file", second_input)
    record_files = list((project / "research" / "records").glob("*.json"))
    before = {p.name: hashlib.sha256(p.read_bytes()).hexdigest() for p in record_files}
    # Import files are no longer at their original paths; recovery uses saved records.
    inputs.rename(project / "recorded-inputs")
    progress = cli("research-progress", "--project-root", project, "--task-id", "second")
    cli("resume", "--project-root", project, "--task-id", "second")
    cli("research-report", "--project-root", project, "--task-id", "second", "--output", "reports/research.md")
    assert historical == cli("research-report", "--project-root", project, "--task-id", "first", markdown=True)
    assert before == {p.name: hashlib.sha256(p.read_bytes()).hexdigest() for p in record_files}
    assert first["question_id"] == second["question_id"] == progress["question_id"]
    assert len(progress["steps"]) == 2
    summary = {"project": str(project), "question_id": progress["question_id"], "steps": len(progress["steps"]),
               "historical_report_unchanged": True, "records_unchanged_during_recovery": True,
               "import_files_available_at_original_paths": False,
               "report": "reports/research.md", "source_queries_performed": False,
               "run_created": False, "verification_created": False, "context": "synthetic"}
    (project / "demo-result.json").write_text(json.dumps(summary, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    return summary


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path)
    args = parser.parse_args()
    target = args.output if args.output else Path(tempfile.mkdtemp(prefix="reading-observation-demo-"))
    print(json.dumps(run_demo(target), ensure_ascii=False, indent=2))
