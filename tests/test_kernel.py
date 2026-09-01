import json, sys, tempfile, unittest, subprocess
from unittest.mock import patch
from pathlib import Path
sys.path.insert(0, str(Path(__file__).parents[1]))
from mining_kernel import validate_record, safe_path, discover_all
import mining_kernel
import run_ledger
from zotero_snapshot import SnapshotError, load_snapshot, snapshot_to_assets
from zotero_export import ensure_loopback, NoRedirect, export_snapshot
from run_ledger import BUNDLE_FILES, RunLedgerError, create_run, inspect_run, record_stage, validate_bundle
from support import make_synthetic_workspace

class KernelTests(unittest.TestCase):
    def test_fixtures_and_version(self):
        for p in (Path(__file__).parents[1]/"fixtures").glob("*.json"):
            data=json.loads(p.read_text(encoding="utf-8"))
            if p.name.startswith("zotero_"): continue
            self.assertEqual([], validate_record(data, "Project"))
        self.assertTrue(validate_record({"schema_version":99}, "Project"))
    def test_discovery(self):
        with tempfile.TemporaryDirectory() as td:
            result=discover_all(make_synthetic_workspace(td))
        self.assertEqual({"flac3d_coal_roadway","ceramsite_research"},{x["project_id"] for x in result})
        self.assertTrue(all("assets" in x for x in result))
    def test_path_safety(self):
        with self.assertRaises(ValueError): safe_path(Path("."), "../outside")
    def test_source_unchanged(self):
        with tempfile.TemporaryDirectory() as td:
            root=make_synthetic_workspace(td); target=root/"projects/flac3D/START.md"; before=target.read_bytes()
            discover_all(root); self.assertEqual(before,target.read_bytes())
    def test_fixture_structure_and_missing_index(self):
        fixture=json.loads((Path(__file__).parents[1]/"fixtures/flac3d_coal_roadway.json").read_text(encoding="utf-8"))
        with tempfile.TemporaryDirectory() as td:
            root=make_synthetic_workspace(td)
            self.assertEqual([], validate_record(fixture, "Project", root))
            broken=dict(fixture); broken["source_paths"]=["../escape"]; broken["verification_gates"]=[{"gate_id":"x"}]
            errors=validate_record(broken, "Project", root)
            self.assertTrue(any("unsafe" in e for e in errors)); self.assertTrue(any("missing status" in e for e in errors))
        with tempfile.TemporaryDirectory() as td:
            temp=Path(td); result=discover_all(temp)
            self.assertTrue(all(any("missing project index" in d for d in x["diagnostics"]) for x in result))
    def test_zotero_snapshot_contract_and_idempotence(self):
        fixture=Path(__file__).parents[1]/"fixtures/zotero_snapshot.example.json"
        data=load_snapshot(fixture); first=snapshot_to_assets(data); second=snapshot_to_assets(data)
        self.assertEqual(first, second); self.assertEqual(["zotero:0123456789abcdef0123456789abcdef:SYNTH001","zotero:0123456789abcdef0123456789abcdef:SYNTH002"],[x["asset_id"] for x in first])
        self.assertEqual("10.1000/synthetic-mine-ventilation", first[0]["doi"])
    def test_zotero_snapshot_rejections(self):
        fixture=json.loads((Path(__file__).parents[1]/"fixtures/zotero_snapshot.example.json").read_text(encoding="utf-8"))
        for mutate in (
            lambda x: x["items"].append(dict(x["items"][0])),
            lambda x: x["items"][0].update({"localPath":"C:\\synthetic\\x.pdf"}),
            lambda x: x.update({"schema_version":99}),
        ):
            broken=json.loads(json.dumps(fixture)); mutate(broken)
            with self.assertRaises(SnapshotError): load_snapshot_from_object(broken)
        adversarial=[
            lambda x: x.update({"rootExtra":1}),
            lambda x: x["items"][0].update({"clientSecret":"x"}),
            lambda x: x["items"][0].update({"title":3}),
            lambda x: x["items"][0].update({"doi":"not-a-doi"}),
            lambda x: x["items"][0].update({"collections":[3]}),
            lambda x: x["items"][0].update({"tags":["  C:\\x"]}),
            lambda x: x["items"][0]["attachments"][0].update({"filename":"../x.pdf"}),
        ]
        for mutate in adversarial:
            broken=json.loads(json.dumps(fixture)); mutate(broken)
            with self.assertRaises(SnapshotError): load_snapshot_from_object(broken)
        for value in (" file:/tmp/x", "FILE:C:/x", " C:Users\\name", "C:folder/file", "\\\\Users\\name"):
            broken=json.loads(json.dumps(fixture)); broken["items"][0]["title"]=value
            with self.assertRaises(SnapshotError): load_snapshot_from_object(broken)
        broken=json.loads(json.dumps(fixture)); broken["library"]["version"]="C:\\Users\\name"
        with self.assertRaises(SnapshotError): load_snapshot_from_object(broken)
        for value in ("A: study of mine ventilation", "R: A language for data analysis"):
            broken=json.loads(json.dumps(fixture)); broken["items"][0]["title"]=value
            self.assertIsNotNone(load_snapshot_from_object(broken))
        broken=json.loads(json.dumps(fixture)); broken["items"][0]["attachments"].append(dict(broken["items"][0]["attachments"][0]))
        with self.assertRaises(SnapshotError): load_snapshot_from_object(broken)
        broken=json.loads(json.dumps(fixture)); broken["items"][0]["attachments"][0]["item_key"]=" "
        with self.assertRaises(SnapshotError): load_snapshot_from_object(broken)
    def test_exporter_rejects_non_loopback_before_network(self):
        with self.assertRaises(ValueError): ensure_loopback("https://example.invalid/api")
        with self.assertRaises(ValueError): ensure_loopback("http://192.0.2.1:23119/api")
        for url in ("https://127.0.0.1:23119/api","http://127.0.0.1:9999/api","http://127.0.0.1:23119/api/../items","http://u:p@127.0.0.1:23119/api?x=1","http://127.0.0.1:23119/api#x","http://127.0.0.1/api"):
            with self.assertRaises(ValueError): ensure_loopback(url)
        with self.assertRaises(ValueError): NoRedirect().redirect_request(None,"http://127.0.0.1:23119/api",None)
        with self.assertRaises(ValueError): export_snapshot(collection_key=" ", all_library=False, instance_seed="stable")
        with self.assertRaises(ValueError): export_snapshot(collection_key="ABC", all_library=True, instance_seed="stable")
    def test_exporter_mock_pagination_parent_aggregation_and_limits(self):
        first=[]
        for i in range(99): first.append({"key":f"P{i}","version":1,"data":{"key":f"P{i}","version":1,"itemType":"journalArticle","title":f"T{i}","collections":[],"tags":[]}})
        first.append({"key":"ATT1","version":2,"data":{"key":"ATT1","version":2,"itemType":"attachment","parentItem":"P0","filename":"paper.pdf","contentType":"application/pdf"}})
        second=[{"key":"P99","version":1,"data":{"key":"P99","version":1,"itemType":"report","title":"Last","collections":[],"tags":[]}}]
        def fake_get(base,path):
            page=first if "start=0" in path else second
            return page,{"Last-Modified-Version":"7","Total-Results":"101"}
        with patch("zotero_export.get_json",side_effect=fake_get):
            result=export_snapshot(collection_key="ABC",instance_seed="stable")
        self.assertEqual("7",result["library"]["version"])
        parent=next(x for x in result["items"] if x["item_key"]=="P0")
        self.assertEqual("ATT1",parent["attachments"][0]["item_key"])
        self.assertEqual(100,len(result["items"]))
        with patch("zotero_export.get_json",return_value=(first,{"Last-Modified-Version":"7","Total-Results":"200"})):
            with self.assertRaises(ValueError): export_snapshot(collection_key="ABC",instance_seed="stable")
        with patch("zotero_export.MAX_PAGES",1), patch("zotero_export.get_json",side_effect=fake_get):
            with self.assertRaises(ValueError): export_snapshot(collection_key="ABC",instance_seed="stable")
        orphan_page=first[:99]+[{"key":"ATTORPHAN","version":1,"data":{"key":"ATTORPHAN","version":1,"itemType":"attachment","parentItem":"MISSING","filename":"x.pdf","contentType":"application/pdf"}}]
        with patch("zotero_export.get_json",side_effect=lambda b,p: (orphan_page if "start=0" in p else [],{"Last-Modified-Version":"7","Total-Results":"100"})):
            with self.assertRaises(ValueError): export_snapshot(collection_key="ABC",instance_seed="stable")
    def test_exporter_zotero9_paths_headers_and_untitled_items(self):
        calls=[]
        page=[{"key":"N1","version":0,"data":{"key":"N1","version":0,"itemType":"note","title":"","DOI":"10.1000/TEST-DOI","collections":[],"tags":[]}}]
        def fake_get(base,path):
            calls.append(path)
            return page,{"Last-Modified-Version":"0","Total-Results":"1","Link":"<ignored>; rel=\"last\""}
        with patch("zotero_export.get_json",side_effect=fake_get):
            result=export_snapshot(all_library=True,instance_seed="ephemeral")
        self.assertEqual(["users/0/items?format=json&limit=100&start=0"],calls)
        self.assertEqual("[untitled note]",result["items"][0]["title"])
        self.assertEqual("10.1000/test-doi",result["items"][0]["doi"])
        self.assertEqual("0",result["library"]["version"])
    def test_cli_invalid_snapshot_nonzero_and_validate_routes(self):
        root=Path(__file__).parents[1]; cli=root/"mining_kernel.py"; fixture=root/"fixtures/zotero_snapshot.example.json"
        with tempfile.TemporaryDirectory() as td:
            workspace=make_synthetic_workspace(td)
            good=subprocess.run([sys.executable,str(cli),"validate-zotero-snapshot",str(fixture)],capture_output=True,text=True,cwd=str(root))
            self.assertEqual(0,good.returncode)
            self.assertEqual(0,mining_kernel.main(["--workspace",str(workspace),"validate"]))
        with tempfile.TemporaryDirectory() as td:
            bad=Path(td)/"bad.json"; data=json.loads(fixture.read_text(encoding="utf-8")); data["schema_version"]=99; bad.write_text(json.dumps(data),encoding="utf-8")
            result=subprocess.run([sys.executable,str(cli),"validate-zotero-snapshot",str(bad)],capture_output=True,text=True,cwd=str(root))
            self.assertNotEqual(0,result.returncode)
    def test_snapshot_schema_minlength_alignment(self):
        schema=json.loads((Path(__file__).parents[1]/"schemas/zotero_snapshot.schema.json").read_text(encoding="utf-8"))
        props=schema["properties"]
        self.assertEqual(1,props["exported_at"]["minLength"])
        self.assertEqual(1,props["library"]["properties"]["collection_key"]["minLength"])
        item_props=props["items"]["items"]["properties"]
        self.assertEqual(1,item_props["item_type"]["minLength"])
        attachment_props=item_props["attachments"]["items"]["properties"]
        self.assertEqual(1,attachment_props["content_type"]["minLength"])

    def test_run_ledger_normal_flow_and_fixed_bundle(self):
        with tempfile.TemporaryDirectory() as td:
            root=Path(td)/"allowed-runs"
            manifest=create_run(root,"run-001",request={"goal":"test"},inputs={"input_hashes":["sha256:abc"]})
            self.assertEqual("exploration",manifest["current_stage"])
            self.assertEqual(set(BUNDLE_FILES),{p.name for p in (root/"run-001").iterdir()})
            for stage,role,data in (
                ("exploration","sol",{"findings":[]}),
                ("plan","sol",{"steps":[],"risks":[]}),
                ("execution","execution_agent",{"commands":[],"return_codes":[],"output_paths":[]}),
                ("test","execution_agent",{"test_results":[]}),
                ("acceptance","sol",{"verdict":"PASS","test_evidence":["test_report.json#attempt-1"],"unresolved_risks":[]}),
            ):
                manifest=record_stage(root,"run-001",stage,role,"completed",data,model="test-model",inputs=[],outputs=data)
            self.assertEqual("accepted",manifest["status"])
            self.assertIsNone(manifest["current_stage"])
            self.assertEqual([],validate_bundle(root,"run-001"))
            self.assertEqual("accepted",inspect_run(root,"run-001")["status"])

    def test_run_ledger_role_skip_waiting_and_retry(self):
        with tempfile.TemporaryDirectory() as td:
            root=Path(td)
            create_run(root,"run-a")
            with self.assertRaises(RunLedgerError): record_stage(root,"run-a","exploration","execution_agent","completed",{},model="test-model")
            with self.assertRaises(RunLedgerError): record_stage(root,"run-a","plan","sol","completed",{},model="test-model")
            waiting=record_stage(root,"run-a","exploration","sol","waiting_for_human",{"question":"scope?"},model="test-model")
            self.assertEqual("waiting_for_human",waiting["status"])
            resumed=record_stage(root,"run-a","exploration","sol","completed",{"answer":"bounded"},model="test-model")
            self.assertEqual("plan",resumed["current_stage"])
            attempts=json.loads((root/"run-a"/"exploration.yaml").read_text(encoding="utf-8"))["attempts"]
            self.assertEqual([1,2],[x["attempt"] for x in attempts])
            failed=record_stage(root,"run-a","plan","sol","failed",{"error":"blocked"},model="test-model")
            self.assertEqual("failed",failed["status"])
            resumed=record_stage(root,"run-a","plan","sol","completed",{"steps":[],"risks":[]},model="test-model")
            self.assertEqual("execution",resumed["current_stage"])

    def test_run_ledger_acceptance_rejection_returns_and_preserves_history(self):
        with tempfile.TemporaryDirectory() as td:
            root=Path(td); create_run(root,"run-b")
            completed_data={"exploration":{},"plan":{"steps":[],"risks":[]},"execution":{"commands":[],"return_codes":[],"output_paths":[]},"test":{"test_results":[]}}
            for stage,role in (("exploration","sol"),("plan","sol"),("execution","execution_agent"),("test","execution_agent")):
                record_stage(root,"run-b",stage,role,"completed",completed_data[stage],model="test-model")
            with self.assertRaises(RunLedgerError):
                record_stage(root,"run-b","acceptance","execution_agent","completed",{"verdict":"PASS","test_evidence":["x"],"unresolved_risks":[]},model="test-model")
            with self.assertRaises(RunLedgerError):
                record_stage(root,"run-b","acceptance","sol","completed",{"verdict":"PASS","unresolved_risks":[]},model="test-model")
            with self.assertRaises(RunLedgerError):
                record_stage(root,"run-b","acceptance","sol","failed",{},model="test-model")
            rejected=record_stage(root,"run-b","acceptance","sol","completed",{"verdict":"FAIL","return_to":"test","test_evidence":["test_report.json#attempt-1"],"unresolved_risks":["known"]},model="test-model")
            self.assertEqual("rejected",rejected["status"]); self.assertEqual("test",rejected["current_stage"])
            record_stage(root,"run-b","test","execution_agent","completed",{"test_results":[{"result":"PASS"}]},model="test-model")
            accepted=record_stage(root,"run-b","acceptance","sol","completed",{"verdict":"PASS","test_evidence":["test_report.json#attempt-2"],"unresolved_risks":[]},model="test-model")
            self.assertEqual("accepted",accepted["status"])
            attempts=json.loads((root/"run-b"/"acceptance.json").read_text(encoding="utf-8"))["attempts"]
            self.assertEqual(["FAIL","PASS"],[x["data"]["verdict"] for x in attempts])
            with self.assertRaises(RunLedgerError):
                create_run(root,"../escape")

    def test_run_ledger_rejects_corruption_missing_unknown_version_and_duplicate_active(self):
        with tempfile.TemporaryDirectory() as td:
            root=Path(td); create_run(root,"run-c"); run=root/"run-c"
            manifest=json.loads((run/"manifest.json").read_text(encoding="utf-8"))
            manifest["stages"]["plan"]["status"]="active"
            (run/"manifest.json").write_text(json.dumps(manifest),encoding="utf-8")
            self.assertTrue(any("multiple active" in e for e in validate_bundle(root,"run-c")))
            manifest["schema_version"]=99
            (run/"manifest.json").write_text(json.dumps(manifest),encoding="utf-8")
            self.assertTrue(any("unsupported schema_version" in e for e in validate_bundle(root,"run-c")))
            (run/"inputs.json").unlink()
            self.assertTrue(any("missing bundle file" in e for e in validate_bundle(root,"run-c")))
            (run/"request.yaml").write_text("{broken",encoding="utf-8")
            self.assertTrue(any("cannot read request.yaml" in e for e in validate_bundle(root,"run-c")))

    def test_run_completed_evidence_contract_rejections(self):
        with tempfile.TemporaryDirectory() as td:
            root=Path(td)
            with self.assertRaises(RunLedgerError): create_run(root,"bad-inputs",inputs={})
            with self.assertRaises(RunLedgerError): create_run(root,"bad-input-type",inputs={"input_hashes":[3]})
            create_run(root,"evidence")
            record_stage(root,"evidence","exploration","sol","completed",{},model="m")
            with self.assertRaises(RunLedgerError): record_stage(root,"evidence","plan","sol","completed",{"steps":[]},model="m")
            record_stage(root,"evidence","plan","sol","completed",{"steps":[],"risks":[]},model="m")
            for broken in (
                {},
                {"commands":["x"],"return_codes":[0,1],"output_paths":[]},
                {"commands":["x"],"return_codes":["0"],"output_paths":[]},
                {"commands":[3],"return_codes":[0],"output_paths":[]},
            ):
                with self.assertRaises(RunLedgerError): record_stage(root,"evidence","execution","execution_agent","completed",broken,model="m")
            record_stage(root,"evidence","execution","execution_agent","completed",{"commands":[],"return_codes":[],"output_paths":[]},model="m")
            with self.assertRaises(RunLedgerError): record_stage(root,"evidence","test","execution_agent","completed",{},model="m")
            record_stage(root,"evidence","test","execution_agent","completed",{"test_results":[]},model="m")
            with self.assertRaises(RunLedgerError): record_stage(root,"evidence","acceptance","sol","completed",{"verdict":"FAIL","return_to":"test","unresolved_risks":[]},model="m")
            with self.assertRaises(RunLedgerError): record_stage(root,"evidence","acceptance","sol","completed",{"verdict":"PASS","test_evidence":["x"]},model="m")

    def test_validate_rejects_forged_accepted_with_pending_stage(self):
        with tempfile.TemporaryDirectory() as td:
            root=Path(td); create_run(root,"forged"); run=root/"forged"
            manifest=json.loads((run/"manifest.json").read_text(encoding="utf-8"))
            manifest["status"]="accepted"; manifest["current_stage"]=None
            manifest["stages"]["exploration"]["status"]="pending"
            acceptance=json.loads((run/"acceptance.json").read_text(encoding="utf-8"))
            acceptance["attempts"]=[{"attempt":1,"at":"now","role":"sol","model":"m","status":"completed","inputs":None,"outputs":None,"data":{"verdict":"PASS","test_evidence":["x"],"unresolved_risks":[]}}]
            manifest["stages"]["acceptance"]["attempt_count"]=1
            (run/"acceptance.json").write_text(json.dumps(acceptance),encoding="utf-8")
            (run/"manifest.json").write_text(json.dumps(manifest),encoding="utf-8")
            self.assertTrue(any("all stages completed" in error for error in validate_bundle(root,"forged")))

    def test_validate_rejects_tampered_evidence_contracts(self):
        with tempfile.TemporaryDirectory() as td:
            root=Path(td); create_run(root,"tampered"); run=root/"tampered"
            inputs=json.loads((run/"inputs.json").read_text(encoding="utf-8")); inputs["inputs"]={}
            (run/"inputs.json").write_text(json.dumps(inputs),encoding="utf-8")
            self.assertTrue(any("input_hashes" in error for error in validate_bundle(root,"tampered")))
            acceptance=json.loads((run/"acceptance.json").read_text(encoding="utf-8"))
            acceptance["attempts"]=[{"attempt":1,"at":"now","role":"sol","model":"m","status":"failed","inputs":None,"outputs":None,"data":{}}]
            manifest=json.loads((run/"manifest.json").read_text(encoding="utf-8")); manifest["stages"]["acceptance"]["attempt_count"]=1
            (run/"acceptance.json").write_text(json.dumps(acceptance),encoding="utf-8")
            (run/"manifest.json").write_text(json.dumps(manifest),encoding="utf-8")
            self.assertTrue(any("does not allow failed" in error for error in validate_bundle(root,"tampered")))

    def test_manifest_atomic_write_failure_preserves_previous_bytes(self):
        with tempfile.TemporaryDirectory() as td:
            path=Path(td)/"manifest.json"; path.write_text('{"old":true}\n',encoding="utf-8")
            before=path.read_bytes()
            with patch("run_ledger.os.replace",side_effect=OSError("synthetic replace failure")):
                with self.assertRaises(OSError): run_ledger._atomic_write(path,{"new":True})
            self.assertEqual(before,path.read_bytes())
            self.assertEqual([],list(Path(td).glob(".manifest.json.*.tmp")))

    def test_run_cli_nonzero_json_error(self):
        root=Path(__file__).parents[1]; cli=root/"mining_kernel.py"
        with tempfile.TemporaryDirectory() as td:
            result=subprocess.run([sys.executable,str(cli),"run-create","--runs-root",td,"../escape"],capture_output=True,text=True,cwd=str(root))
            self.assertEqual(2,result.returncode)
            self.assertIn("error",json.loads(result.stdout))
            result=subprocess.run([sys.executable,str(cli),"run-validate","--runs-root",td,"missing"],capture_output=True,text=True,cwd=str(Path(__file__).parents[3]))
            self.assertEqual(2,result.returncode)
            self.assertFalse(json.loads(result.stdout)["valid"])

def load_snapshot_from_object(data):
    from zotero_snapshot import validate_snapshot
    return validate_snapshot(data)

if __name__ == "__main__": unittest.main()
