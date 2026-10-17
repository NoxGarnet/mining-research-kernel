from __future__ import annotations
import hashlib,json,tempfile,unittest
from pathlib import Path
import jsonschema
from providers.documentation import load_registration
from providers.documentation import read_local_documentation
from mining_research_kernel.documentation_reading import record_documentation_reading
from mining_research_kernel.records import ResearchStore
from research_project import enable_research

REPO=Path(__file__).resolve().parents[1]
PAGE="flac3d/zone/doc/manual/zone_commands/itasca_reading_fixture.html"
FIXTURE=(REPO/"tests/fixtures/itasca_manual.html").read_bytes()

class DocumentationReadingTests(unittest.TestCase):
 def setUp(self):
  self.temp=tempfile.TemporaryDirectory(dir=REPO/"tests"); self.base=Path(self.temp.name)
  self.docs=self.base/"docs"; self.path=self.docs/PAGE; self.path.parent.mkdir(parents=True); self.path.write_bytes(FIXTURE)
  self.reg=self.base/"registration.json"; self.project=self.base/"project"; self.project.mkdir(); enable_research(self.project,"reading.project")
  self.register()
 def tearDown(self): self.temp.cleanup()
 def register(self,trust="official_local",digest=None):
  self.reg.write_text(json.dumps({"schema_version":1,"source_id":"example.docs.local","root":str(self.docs),"product":"flac3d","document_family":"9.6","document_build":"9.6.44","trust_class":trust,"product_subdir":"flac3d","pages":{PAGE:digest or hashlib.sha256(self.path.read_bytes()).hexdigest()}}),encoding="utf8")
 def test_reads_anchor_and_caps_persisted_text(self):
  result=read_local_documentation(load_registration(self.reg),page=PAGE,product="flac3d",product_version="9.6",anchor="model-save",max_reading_chars=12000)
  self.assertEqual("READ_WITH_LIMITS",result["status"]); self.assertIn("restoration", " ".join(x["text"] for x in result["reading_texts"]))
  self.assertNotIn("Navigation-only", " ".join(x["text"] for x in result["reading_texts"]))
  self.assertNotIn("Footer-only", " ".join(x["text"] for x in result["reading_texts"]))
  self.assertEqual("Saving a model",result["passages"][0]["heading"])
  self.assertEqual("model-save",result["passages"][0]["locator"])
  self.assertLessEqual(sum(len(p["text"]) for p in result["passages"]),2000)
  signature=read_local_documentation(load_registration(self.reg),page=PAGE,product="flac3d",product_version="9.6.44",anchor="kwd:zone.cmodel.assign.elastic")
  self.assertEqual("kwd:zone.cmodel.assign.elastic",signature["passages"][0]["locator"])
  self.assertIn("constitutive model", " ".join(x["text"] for x in signature["reading_texts"]))
  self.assertEqual("kwd:zone.cmodel.assign.elastic",signature["reading_texts"][0]["locator"])
  self.assertEqual("anchor_not_found",read_local_documentation(load_registration(self.reg),page=PAGE,product="flac3d",product_version="9.6",anchor="absent")["stop_reason"])
 def test_version_hash_and_synthetic_gates(self):
  src=load_registration(self.reg)
  self.assertEqual("target_product_version_mismatch",read_local_documentation(src,page=PAGE,product="flac3d",product_version="9.0")["stop_reason"])
  self.register(digest="0"*64)
  drift=read_local_documentation(load_registration(self.reg),page=PAGE,product="flac3d",product_version="9.6")
  self.assertEqual("page_hash_drift",drift["stop_reason"])
  recorded=record_documentation_reading(self.project,task_id="drift-read",question="q",registration=self.reg,page=PAGE,product="flac3d",product_version="9.6")
  self.assertTrue(recorded["query_performed"]); self.assertFalse(recorded["source_read_performed"])
  self.register(trust="synthetic")
  self.assertEqual("synthetic_source_not_for_production",read_local_documentation(load_registration(self.reg),page=PAGE,product="flac3d",product_version="9.6")["stop_reason"])
 def test_invalid_task_context_does_not_write(self):
  with self.assertRaisesRegex(ValueError,"task_context"):
   record_documentation_reading(self.project,task_id="bad-context",question="q",registration=self.reg,page=PAGE,product="flac3d",product_version="9.6",task_context="unknown")
  self.assertEqual([],ResearchStore(self.project).list_transactions())
 def test_durable_snapshot_and_replay_without_read(self):
  args=dict(task_id="read-task",question="What is the save procedure?",registration=self.reg,provider="local",page=PAGE,product="flac3d",product_version="9.6",anchor="model-save")
  first=record_documentation_reading(self.project,**args)
  self.assertTrue(first["source_read_performed"]); self.assertTrue(first["reading_texts"])
  store=ResearchStore(self.project); rows=store.list_transactions()[0]["records"]
  asset=next(x for x in rows if x["type"]=="Asset")
  self.assertEqual("documentation_query_snapshot",asset["asset_kind"])
  self.assertEqual("documentation_query_observation",asset["payload"]["kind"])
  self.assertNotIn(str(self.docs),json.dumps(rows)); self.assertNotIn(FIXTURE.decode(),json.dumps(rows))
  schema=json.loads((REPO/"schemas/task_packet.schema.json").read_text()); jsonschema.Draft202012Validator(schema).validate(first["task_packet"])
  self.path.unlink()
  replay=record_documentation_reading(self.project,**args)
  self.assertTrue(replay["replayed"]); self.assertFalse(replay["source_read_performed"]); self.assertEqual([],replay["reading_texts"])

if __name__=="__main__": unittest.main()
