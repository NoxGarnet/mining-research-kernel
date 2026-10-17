"""Exercise direct source reads and a cited Markdown synthesis as CLI clients."""
import hashlib
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest

from test_r1_documentation import html_page, PAGE


REPO = Path(__file__).resolve().parents[1]
SERVER = r'''
import json,sys
for line in sys.stdin:
    req=json.loads(line); method=req.get('method'); ident=req.get('id')
    if ident is None: continue
    if method=='initialize':
        result={'protocolVersion':'2025-03-26','capabilities':{'tools':{}},'serverInfo':{'name':'synthetic-reader','version':'1'}}
    elif method=='tools/list':
        result={'tools':[{'name':name,'inputSchema':{'type':'object'}} for name in (
            'zotero_get_collections','zotero_get_collection_items','zotero_get_item_metadata',
            'zotero_get_item_children','zotero_get_item_fulltext','zotero_search_items','zotero_read_pdf_pages')]}
    else:
        name=req['params']['name']; args=req['params'].get('arguments',{})
        if name=='zotero_get_item_metadata':
            key=args['item_key']; data={'key':key,'version':0,'title':'Authored synthetic paper','itemType':'journalArticle','collections':['COLLECT1']}
            if key=='ATTACH01': data.update(parentItem='PAPER001',itemType='attachment',contentType='application/pdf')
            text=json.dumps({'key':key,'version':0,'library':{'id':0,'type':'user'},'data':data})
        elif name=='zotero_read_pdf_pages':
            text=chr(10).join(['# PDF Pages 1-1 of PDF','**Item Key:** ATTACH01','**Total pages in PDF:** 1','','## Page 1',('Fabricated page body for software acceptance. '*80)])
        elif name=='zotero_get_collections': text=chr(10).join(['# Zotero Collections','- Synthetic (Key: COLLECT1)'])
        elif name=='zotero_search_items': text=chr(10).join(['# Search Results','Synthetic paper (Key: PAPER001)'])
        else: text='No items.'
        result={'content':[{'type':'text','text':text}],'isError':False}
    print(json.dumps({'jsonrpc':'2.0','id':ident,'result':result}),flush=True)
'''


class ResearchSourceCLITests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(prefix="source-cli-", dir=REPO / "tests")
        self.addCleanup(self.temp.cleanup)
        self.base = Path(self.temp.name)
        self.project = self.base / "研究 study"
        self.project.mkdir()
        self.entry = self.project / "START.md"
        self.entry.write_text("# Existing study\n", encoding="utf-8")
        self.server = self.base / "reader.py"
        # SERVER is Python source; literal escaped newlines remain intentional.
        self.server.write_text(SERVER, encoding="utf-8")
        self.profile = self.base / "host-reader.json"
        self.profile.write_text(json.dumps({"schema_version": 1, "kind": "zotero_stdio",
            "instance_id": "a" * 32, "library_id": "users/0", "command": sys.executable,
            "args": ["-B", "-X", "utf8", str(self.server)], "cwd": str(self.base),
            "timeout_seconds": 3}), encoding="utf-8")
        self.cli("enable-research", "--project-root", str(self.project), "--project-id", "source-study")

    def cli(self, *args, expected=0):
        run = subprocess.run([sys.executable, "-B", "-X", "utf8", str(REPO / "mining_kernel.py"), *args],
            cwd=self.base, env={**os.environ, "TEMP": str(self.base), "TMP": str(self.base), "TMPDIR": str(self.base)},
            capture_output=True, text=True, encoding="utf-8", timeout=30)
        self.assertEqual(expected, run.returncode, run.stdout + run.stderr)
        return json.loads(run.stdout)

    def read(self):
        return self.cli("zotero-read", "--project-root", str(self.project), "--registration", str(self.profile),
            "--task-id", "paper-01", "--question", "What is captured on the selected page?", "--item-key", "PAPER001",
            "--pdf-key", "ATTACH01", "--pages", "1", "--collection-key", "COLLECT1", "--task-context", "synthetic")

    def docs(self):
        path = self.base / "official-docs" / PAGE
        path.parent.mkdir(parents=True)
        body = html_page()
        path.write_bytes(body)
        registration = self.base / "documentation.json"
        registration.write_text(json.dumps({"schema_version": 1, "source_id": "example.docs.synthetic",
            "root": str(self.base / "official-docs"), "product": "flac3d", "document_family": "9.6",
            "document_build": "9.6.44", "trust_class": "synthetic", "product_subdir": "flac3d",
            "pages": {PAGE: hashlib.sha256(body).hexdigest()}}), encoding="utf-8")
        return self.cli("documentation-record", "--project-root", str(self.project), "--task-id", "docs-01",
            "--question", "Is the command documented?", "--registration", str(registration), "--page", PAGE,
            "--command", "zone list", "--product", "flac3d", "--product-version", "9.6.44", "--task-context", "synthetic")

    def test_direct_read_search_and_replay_without_running_source(self):
        original = self.entry.read_bytes()
        search = self.cli("zotero-search", "--registration", str(self.profile), "--query", "Synthetic",
                          "--collection-key", "COLLECT1", "--limit", "2")
        self.assertEqual("PASS", search["status"])
        fresh = self.read()
        self.assertTrue(fresh["source_read_performed"])
        self.assertTrue(fresh["query_performed"])
        self.assertGreater(len(fresh["reading_texts"][0]["text"]), 1000)
        self.server.unlink()
        replay = self.read()
        self.assertTrue(replay["replayed"])
        self.assertFalse(replay["source_read_performed"])
        self.assertEqual([], replay["reading_texts"])
        records = "".join(p.read_text(encoding="utf-8") for p in (self.project / "research/records").glob("*.json"))
        self.assertNotIn(str(self.server).replace("\\", "\\\\"), records)
        self.assertNotIn("Fabricated page body for software acceptance. " * 80, records)
        self.assertEqual(original, self.entry.read_bytes())

    def test_sources_to_markdown_review_and_process_recovery(self):
        paper, docs = self.read(), self.docs()
        argv = ["research-start", "--project-root", str(self.project), "--task-id", "combined-01",
            "--question", "What do these distinct sources establish and leave open?", "--task-context", "synthetic"]
        for asset in paper["asset_refs"] + docs["asset_refs"]:
            argv.extend(["--asset-ref", asset])
        started = self.cli(*argv)
        self.assertEqual(2, len(started["sources"]))
        self.assertIn("## Findings", started["review_template"])
        citations = " ".join("[evidence:" + ref + "]" for ref in started["evidence_refs"])
        note = ("## Summary\nThe sources address different scopes.\n\n## Findings\n"
                "- The paper text and syntax observation do not validate a model. " + citations +
                "\n\n## Gaps\n- Original sources were not revalidated in this review.\n\n"
                "## Next\nConsider checking conditions required by the user.\n")
        file = self.project / "review.md"
        file.write_text(note, encoding="utf-8")
        command = ["research-review", "--project-root", str(self.project), "--task-id", "combined-01",
                   "--operation-id", "review-01", "--review-file", str(file)]
        receipt = self.cli(*command)
        self.assertEqual("PROVISIONAL_WITH_GAPS", receipt["research_judgment_status"])
        self.assertEqual(receipt["decision_id"], self.cli(*command)["decision_id"])
        self.assertIn("combined-01", json.dumps(self.cli("resume", "--project-root", str(self.project), "--task", "combined-01")))
        assessment = self.cli("show", "--project-root", str(self.project), "--record-id", receipt["decision_id"], "--section", "assessment")
        self.assertIn("The sources address different scopes", json.dumps(assessment))
        self.assertTrue(self.cli(*argv)["replayed"])
        self.assertFalse((self.project / "runs").exists())


if __name__ == "__main__":
    unittest.main()
