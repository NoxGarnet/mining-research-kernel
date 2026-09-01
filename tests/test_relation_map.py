import csv, json, tempfile, unittest
from pathlib import Path
from relation_map import build_mapping, combine_snapshots, norm_title, write_artifacts

class RelationMapTests(unittest.TestCase):
    def setUp(self):
        self.td=tempfile.TemporaryDirectory(); self.root=Path(self.td.name)
        self.manifest=self.root/'source_manifest.csv'; self.ris=self.root/'x.ris'; self.md=self.root/'md'; self.md.mkdir()
        with self.manifest.open('w',encoding='utf-8',newline='') as f:
            w=csv.DictWriter(f,fieldnames=['source_relative_path','title_key','source_sha256','md_relative_path']); w.writeheader(); w.writerows([
                {'source_relative_path':'raw/A.pdf','title_key':'甲_研究','source_sha256':'A'*64,'md_relative_path':'md/甲_研究.md'},
                {'source_relative_path':'raw/B.pdf','title_key':'乙研究','source_sha256':'B'*64,'md_relative_path':'md/乙研究.md'},
                {'source_relative_path':'raw/B-copy.pdf','title_key':'乙研究','source_sha256':'B'*64,'md_relative_path':'md/乙研究.md'}])
        (self.md/'甲_研究.md').write_text('ignored',encoding='utf-8'); (self.md/'乙研究.md').write_text('ignored',encoding='utf-8')
        self.ris.write_text('TY  - JOUR\nTI  - 甲_研究\nDO  - 10.X/Y\nER  -\n',encoding='utf-8')
    def tearDown(self): self.td.cleanup()
    def snap(self): return {'schema_version':1,'snapshot_type':'zotero_filtered_metadata','instance_id':'a'*16,'exported_at':'x','library':{'version':'0'},'items':[
        {'item_key':'Z1','version':1,'item_type':'attachment','title':'甲 研究','collections':[],'tags':[],'attachments':[]},
        {'item_key':'Z2','version':1,'item_type':'attachment','title':'乙研究','collections':[],'tags':[],'attachments':[]},
        {'item_key':'Z3','version':1,'item_type':'journalArticle','title':'未登记','collections':[],'tags':[],'attachments':[]}]}
    def test_mapping_counts_duplicate_orphan_and_rebuild(self):
        result=build_mapping(self.snap(),self.manifest,self.ris,self.md)
        self.assertEqual(result['summary']['manifest_rows'],3); self.assertEqual(result['summary']['unique_title_keys'],2)
        self.assertEqual(result['summary']['exact_complete_matches'],0); self.assertEqual(result['duplicates'][0]['manifest_rows'],2)
        self.assertEqual(result['duplicates'][0]['kind'],'same_hash_shared_target')
        self.assertEqual(result['markdown_reconciliation']['shared'][0]['manifest_rows'],2)
        self.assertEqual(result['orphans'][0]['zotero_item_key'],'Z3')
        out=self.root/'out'; write_artifacts(result,out); first=(out/'relation_map.json').read_bytes(); write_artifacts(build_mapping(self.snap(),self.manifest,self.ris,self.md),out)
        self.assertEqual(first,(out/'relation_map.json').read_bytes()); self.assertTrue((out/'rebuild_report.json').exists())
    def test_ambiguous_not_bound(self):
        snap=self.snap(); snap['items'].append(dict(snap['items'][1],item_key='Z4'))
        result=build_mapping(snap,self.manifest,self.ris,self.md)
        self.assertIsNone(result['relations'][1]['zotero_attachment_item_key']); self.assertTrue(result['ambiguities'])

    def test_exact_three_layer_relation_and_snapshot_combine(self):
        self.manifest.write_text(
            'source_relative_path,title_key,source_sha256,md_relative_path,md_exists\n'
            'raw/A.pdf,甲研究_甲,' + 'A'*64 + ',md/甲研究_甲.md,True\n', encoding='utf-8')
        (self.md/'甲研究_甲.md').write_text('ignored',encoding='utf-8')
        self.ris.write_text('TY  - THES\nTI  - 甲研究\nAU  - 甲\nER  -\n',encoding='utf-8')
        self.ris.write_text('TY  - THES\nTI  - 甲研究\nAU  - 甲\nDO  - 10.1234/alpha\nER  -\n',encoding='utf-8')
        attachment=dict(self.snap(),items=[dict(self.snap()['items'][0],item_key='A1',item_type='attachment',title='甲研究_甲')])
        parent=dict(self.snap(),items=[dict(self.snap()['items'][0],item_key='P1',item_type='thesis',title='甲研究',doi='10.1234/alpha')])
        combined=combine_snapshots([attachment,parent])
        result=build_mapping(combined,self.manifest,self.ris,self.md)
        relation=result['relations'][0]
        self.assertEqual(result['summary']['exact_complete_matches'],1)
        self.assertEqual(relation['zotero_attachment_item_key'],'A1')
        self.assertEqual(relation['zotero_bibliographic_item_key'],'P1')
        self.assertEqual(relation['match_evidence']['manifest_to_ris'],'exact_title_plus_first_author')
        self.assertEqual(relation['match_evidence']['ris_to_zotero_parent'],'exact_doi')
        self.assertTrue(relation['match_evidence']['doi_compared'])
        self.assertTrue(relation['match_evidence']['doi_match'])
        changed=dict(parent,instance_id='b'*16)
        with self.assertRaises(ValueError): combine_snapshots([attachment,changed])

    def test_markdown_collision_and_missing_are_reported(self):
        (self.md/'甲-研究.md').write_text('ignored',encoding='utf-8')
        result=build_mapping(self.snap(),self.manifest,self.ris,self.md)
        self.assertTrue(result['markdown_reconciliation']['collision'])
        self.assertEqual(result['markdown_reconciliation']['missing'],[])
        self.assertEqual(result['relations'][0]['markdown_status'],'collision')

    def test_conflicting_duplicate_is_distinguished(self):
        text=self.manifest.read_text(encoding='utf-8').replace('B'*64,'C'*64,1)
        self.manifest.write_text(text,encoding='utf-8')
        result=build_mapping(self.snap(),self.manifest,self.ris,self.md)
        self.assertEqual(result['duplicates'][0]['kind'],'conflicting_duplicate')
    def test_normalization_and_path_guard(self):
        self.assertEqual(norm_title('A_研究.pdf'),norm_title('A 研究'))
        text=self.manifest.read_text(encoding='utf-8').replace('raw/A.pdf','../A.pdf')
        self.manifest.write_text(text,encoding='utf-8')
        with self.assertRaises(ValueError): build_mapping(self.snap(),self.manifest,self.ris,self.md)

if __name__=='__main__': unittest.main()
