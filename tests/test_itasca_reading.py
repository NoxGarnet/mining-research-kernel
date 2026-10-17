from __future__ import annotations
import unittest
import sys
import json
import tempfile
from pathlib import Path
from unittest.mock import patch
from providers.itasca import MCPHostError, load_registration, query_itasca
from mining_research_kernel.documentation_reading import record_documentation_reading
from research_project import enable_research

PROFILE={"schema_version":1,"kind":"itasca_stdio","instance_id":"a"*24,"command":sys.executable,"args":[]}
REPO=Path(__file__).resolve().parents[1]

class ItascaReadingTests(unittest.TestCase):
 def response(self,version="9.6"):
  return {"structuredContent":{"ok":True,"data":{"source":"commands","action":"browse","version":version,"software":"FLAC3D","entries":[{"category":"model","command":"model save","version":version,"doc":{"source":"https://docs.example.invalid/model-save","description":"Saves the current model.","syntax":"model save file-name","keywords":["model"],"versions":[version]}}],"summary":{"count":1,"version":version,"software":"FLAC3D"}}}}
 @patch("providers.itasca.call_tool")
 def test_reads_community_content_and_retains_mismatch(self,call):
  call.return_value=self.response()
  result=query_itasca(PROFILE,operation="itasca_browse_commands",software="FLAC3D",version="9.6",command="model save")
  self.assertEqual("READ_WITH_LIMITS",result["status"]); self.assertEqual("community_mcp",result["citation"]["trust_class"])
  self.assertFalse(result["citation"]["official_source_verified"])
  self.assertEqual("https://docs.example.invalid/model-save",result["passages"][0]["upstream_source"])
  self.assertFalse(result["passages"][0]["upstream_source_verified"])
  call.return_value=self.response("9.0")
  mismatch=query_itasca(PROFILE,operation="itasca_browse_commands",software="FLAC3D",version="9.6",command="model save")
  self.assertIn("mcp_version_unverified",mismatch["uncovered"]); self.assertEqual("9.0",mismatch["citation"]["returned_version"])
 @patch("providers.itasca.call_tool")
 def test_only_allowlisted_read_operations(self,call):
  result=query_itasca(PROFILE,operation="itasca_execute_code",software="FLAC3D",version="9.6")
  call.assert_not_called(); self.assertEqual("operation_not_allowed",result["stop_reason"])
 @patch("providers.itasca.call_tool")
 def test_search_and_reference_applicability_are_not_promoted(self,call):
  call.return_value=self.response()
  discovery=query_itasca(PROFILE,operation="itasca_query_command",software="FLAC3D",version="9.6",query="model save")
  self.assertEqual("DISCOVERY_ONLY",discovery["status"])
  call.return_value={"structuredContent":{"ok":True,"data":{"source":"reference","action":"browse","entries":[{"category":"constitutive-models","doc":{"description":"Model properties"}}],"summary":{"count":1,"version":"9.6"}}}}
  reference=query_itasca(PROFILE,operation="itasca_browse_reference",software="FLAC3D",version="9.6",topic="constitutive-models")
  self.assertIn("reference_version_applicability_unverified",reference["uncovered"])
  self.assertEqual("INSUFFICIENT",reference["applicability_status"])
 @patch("providers.itasca.call_tool")
 def test_tool_errors_and_empty_docs_never_become_read_passages(self,call):
  call.return_value={"isError":True,"content":[{"text":"sensitive upstream detail"}]}
  failed=query_itasca(PROFILE,operation="itasca_browse_commands",software="FLAC3D",version="9.6",command="model save")
  self.assertEqual("CANNOT_READ",failed["status"]); self.assertEqual("mcp_tool_error",failed["stop_reason"])
  call.return_value={"structuredContent":{"ok":True,"data":{"entries":[{"command":"model save","doc":{}}],"summary":{"version":"9.6","software":"FLAC3D"}}}}
  empty=query_itasca(PROFILE,operation="itasca_browse_commands",software="FLAC3D",version="9.6",command="model save")
  self.assertEqual("CANNOT_READ",empty["status"]); self.assertEqual([],empty["passages"])
 @patch("providers.itasca.call_tool")
 def test_failure_is_sanitized_and_version_required(self,call):
  call.side_effect=MCPHostError("host_timeout")
  failed=query_itasca(PROFILE,operation="itasca_browse_reference",software="PFC",version="9.6",topic="save")
  self.assertEqual("host_timeout",failed["stop_reason"])
  missing=query_itasca(PROFILE,operation="itasca_query_command",software="PFC",version="")
  self.assertEqual("version_required",missing["stop_reason"])
  oversized={**PROFILE,"args":["a"*33000]}
  with self.assertRaisesRegex(ValueError,"registration_too_large"):
   load_registration(oversized)

 def test_stdio_profile_paginates_allowlists_and_replays_without_launch(self):
  with tempfile.TemporaryDirectory(dir=REPO/"tests") as temp:
   root=Path(temp); server=root/"fake_itasca_mcp.py"; profile=root/"itasca-registration.json"
   project=root/"project"; project.mkdir(); enable_research(project,"itasca.project")
   server.write_text((REPO/"tests/fixtures/itasca_fake_mcp.py").read_text(encoding="utf8"),encoding="utf8")
   profile.write_text(json.dumps({**PROFILE,"args":["-B",str(server)]}),encoding="utf8")
   args={"task_id":"itasca-read","question":"What does model save do?","registration":profile,
         "provider":"itasca","operation":"itasca_browse_commands","software":"FLAC3D",
         "version":"9.6","command":"model save"}
   first=record_documentation_reading(project,**args)
   self.assertTrue(first["query_performed"]); self.assertTrue(first["source_read_performed"])
   self.assertEqual("PROVISIONAL_WITH_GAPS",first["task_packet"]["research_judgment_status"])
   self.assertEqual("NOT_VERIFIED",first["task_packet"]["material_reads"][0]["verification_status"])
   server.unlink()
   replay=record_documentation_reading(project,**args)
   self.assertTrue(replay["replayed"]); self.assertFalse(replay["query_performed"])

if __name__=="__main__": unittest.main()
