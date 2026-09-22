import json
import sys
import unittest
from pathlib import Path

ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT/'scripts'))
from build import build, load_and_validate, OUT

class BuildTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.stats=build()
        cls.index=json.loads((OUT/'data/index.json').read_text())
        cls.taxonomy,cls.topics,cls.content,cls.sources,cls.practice,cls.redirects=load_and_validate()

    def asset(self,path):
        self.assertTrue(path.startswith('data/'))
        self.assertNotIn('..',path)
        return json.loads((OUT/path).read_text())

    def test_migration_counts(self):
        expected=json.loads((ROOT/'data/import-manifest.json').read_text())['counts']
        self.assertEqual({k:self.stats[k] for k in expected},expected)

    def test_topic_and_practice_exports_preserve_final_data(self):
        details={};questions=[]
        for group in self.index['assets'].values():
            details.update(self.asset(group['details']))
            questions.extend(self.asset(group['practice']))
        self.assertEqual({q['question_id']:q for q in questions},{q['question_id']:q for q in self.practice})
        expected={t['study_topic_id']:{**t,**({'study_content':self.content[t['study_topic_id']]} if t['study_topic_id'] in self.content else {})} for t in self.topics}
        self.assertEqual(details,expected)

    def test_source_shards_preserve_complete_bonus_sets(self):
        sources={}
        for shard in self.index['source_shards'].values():
            sources.update(self.asset(shard))
        self.assertEqual(sources,self.sources)

    def test_index_defers_detail_payloads(self):
        self.assertEqual(len(self.index['topics']),len(self.topics))
        for t in self.index['topics']:
            self.assertNotIn('study_content',t)
            self.assertNotIn('source_ids',t)
            self.assertNotIn('description',t)
        self.assertLess(self.stats['browse_index_bytes'],2_000_000)

    def test_deployment_contains_only_public_files(self):
        self.assertTrue((OUT/'.nojekyll').exists())
        self.assertFalse((OUT/'.git').exists())
        self.assertFalse((OUT/'scripts').exists())
        for p in OUT.rglob('*'):
            self.assertFalse(p.name.startswith('.env'))
        html=(OUT/'index.html').read_text()
        self.assertIn('type="module"',html)
        self.assertIn('src="app.js"',html)
        self.assertNotIn('http://127.0.0.1',html)

if __name__=='__main__':unittest.main()
