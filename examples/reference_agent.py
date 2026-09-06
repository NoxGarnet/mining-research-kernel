"""Small SDK-free R2 reference agent.

It calls the public Python services directly.  The end-to-end test invokes
the CLI in a second process to demonstrate that task-inspect does not depend
on this process' memory.
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from mining_research_kernel.r2_workflow import research_map_rebuild, task_run_fake, task_start


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description="SDK-free Mining Research Kernel reference agent")
    parser.add_argument("--project-root", required=True)
    parser.add_argument("--task-id", default="reference-task")
    parser.add_argument("--fixture-id", default="reference-fixture")
    parser.add_argument("--question", default="Does the synthetic fixture complete the bounded workflow?")
    parser.add_argument("--claim", default="The synthetic fixture completes the kernel workflow mechanics.")
    args = parser.parse_args(argv)
    request = {
        "task_id": args.task_id,
        "question_statement": args.question,
        "claim_statement": args.claim,
        "task_type": "mining_research_kernel.task.fake_execution",
        "maturity": "exploratory",
        "max_runs": 1,
        "task_context": "synthetic",
    }
    packet = task_start(args.project_root, request)
    run = task_run_fake(args.project_root, args.task_id, "reference-run", args.fixture_id)
    view = research_map_rebuild(args.project_root)
    print(json.dumps({"task_packet": packet, "fake_run": run, "research_map": view},
                     ensure_ascii=False, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
