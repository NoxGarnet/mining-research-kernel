import hashlib, json, tempfile, unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch
from stability import STABILITY_ROOT, _REGISTERED_STABILITY_CHECKS, diagnose, canonical, host_capabilities, ledger_metrics, run_command

class StabilityTests(unittest.TestCase):
    def base(self, root):
        p = root / "source.txt"; p.write_text("ok", encoding="utf-8")
        return {"schema_version": 1, "type": "Project", "project_id": "p", "status": "ready",
                "assets": [{"asset_id": "a", "path": "source.txt", "sha256": hashlib.sha256(b"ok").hexdigest()}]}
    def test_golden_and_clean(self):
        root = Path(tempfile.mkdtemp()); self.assertTrue(diagnose([self.base(root)], root)["valid"])
    def test_duplicate_drift_missing_conflict_and_unknown(self):
        root = Path(tempfile.mkdtemp()); a=self.base(root); b=json.loads(json.dumps(a)); b["status"]="other"; b["assets"][0]["sha256"]="0"; b["assets"].append({"asset_id":"missing","path":"missing.txt"}); b["schema_version"]=9
        codes={e["code"] for e in diagnose([a,b], root)["errors"]}
        for code in ("duplicate_asset_id","duplicate_asset_path","registered_hash_drift","missing_source_or_attachment","project_status_conflict","unknown_schema_version"): self.assertIn(code,codes)
    def test_canonical_removes_only_volatile(self):
        self.assertEqual(canonical({"at": 1, "x": {"updated_at": 2, "v": 3}}), {"x": {"v": 3}})
    def test_host_isolation(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td) / "current-workspace"; root.mkdir()
            other = Path(td) / "other-workspace"
            inv = Path(td) / "hosts.yaml"
            inv.write_text(f"hosts:\n  current_host:\n    workspace_root_observed: '{root.as_posix()}'\n  other_host:\n    workspace_root_observed: '{other.as_posix()}'\n", encoding="utf-8")
            report=host_capabilities(root, inv)
        self.assertEqual(report["hosts"]["current_host"]["status"], "current_verified")
        self.assertEqual(report["hosts"]["other_host"]["status"], "historical_unverified")
        self.assertIn("credentials", report["nonportable_local_state"])
    def test_host_matching_and_unknown(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            a = root / "workspace-a"; b = root / "workspace-b"; a.mkdir(); b.mkdir()
            inv = root / "host.yaml"
            inv.write_text(f"hosts:\n  host_a:\n    workspace_root_observed: '{a.as_posix()}'\n  host_b:\n    workspace_root_observed: '{b.as_posix()}'\n", encoding='utf-8')
            self.assertEqual(host_capabilities(a,inv)['current_host'],'host_a')
            self.assertEqual(host_capabilities(b,inv)['current_host'],'host_b')
            self.assertEqual(host_capabilities(root / 'unknown',inv)['current_host'],'unknown_current_host')
    def test_ledger_metrics_from_synthetic_history(self):
        with tempfile.TemporaryDirectory() as td:
            run = Path(td) / 'synthetic-run'; run.mkdir()
            files = {'exploration': ('exploration.yaml', 1), 'plan': ('plan.yaml', 2), 'execution': ('execution.json', 3), 'test': ('test_report.json', 1), 'acceptance': ('acceptance.json', 2)}
            for stage, (filename, count) in files.items():
                attempts = []
                for index in range(count):
                    data = {'verdict': 'FAIL'} if stage == 'acceptance' and index == count - 1 else {}
                    attempts.append({'status': 'waiting_for_human' if stage == 'plan' and index == 1 else 'completed', 'data': data})
                (run / filename).write_text(json.dumps({'attempts': attempts}), encoding='utf-8')
            metrics = ledger_metrics(td, ['synthetic-run'])
            self.assertEqual([metrics['runs']['synthetic-run']['stages'][s]['attempt_count'] for s in ('exploration','plan','execution','test','acceptance')], [1,2,3,1,2])
            self.assertEqual(metrics['totals']['attempt_count'], 9)
            self.assertEqual(metrics['totals']['additional_attempts'], 4)
            self.assertEqual(metrics['totals']['acceptance_failures'], 1)
            self.assertEqual(metrics['totals']['waiting_events'], 1)
    def test_diagnose_does_not_modify_source(self):
        root=Path(tempfile.mkdtemp()); a=self.base(root); before=(root/'source.txt').read_bytes(); diagnose([a],root); self.assertEqual(before,(root/'source.txt').read_bytes())

    def test_run_command_only_accepts_registered_check_with_controls(self):
        argv=list(_REGISTERED_STABILITY_CHECKS[0])
        with patch("stability.subprocess.run", return_value=SimpleNamespace(returncode=0, stdout="ok", stderr="")) as runner:
            result=run_command(argv, STABILITY_ROOT, timeout=12)
        runner.assert_called_once_with(argv, cwd=str(STABILITY_ROOT), capture_output=True, text=True, shell=False, timeout=12.0, check=False)
        self.assertEqual(0, result["return_code"])

    def test_run_command_rejects_unregistered_argv_and_uncontrolled_inputs(self):
        argv=list(_REGISTERED_STABILITY_CHECKS[0])
        with self.assertRaises(ValueError): run_command([argv[0], "-c", "print('arbitrary')"], STABILITY_ROOT)
        with self.assertRaises(ValueError): run_command(tuple(argv), STABILITY_ROOT)
        with self.assertRaises(ValueError): run_command(argv, STABILITY_ROOT.parent)
        with self.assertRaises(ValueError): run_command(argv, STABILITY_ROOT, timeout=0)

if __name__ == "__main__": unittest.main()
