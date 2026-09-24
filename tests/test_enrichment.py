import copy
import hashlib
import json
from pathlib import Path
import shutil
import sys
import tempfile
import unittest
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'scripts'))
import enrich_topics as enrichment
import integrate_luna_topics as luna_integration
from research_redaction import sanitize_record


class EnrichmentTests(unittest.TestCase):
    def test_luna_provenance_rejects_dirty_raw_and_redacted_result(self):
        with tempfile.TemporaryDirectory() as directory:
            raw_path = Path(directory) / 'raw.json'
            raw = {'response': {'output': [{'action': {'sources': [{
                'url': 'https://example.org/source' + '?' + 'X-Amz-' + 'Signature=synthetic'}]}}]}}
            def provenance():
                value = {'raw_sha256': hashlib.sha256(raw_path.read_bytes()).hexdigest(),
                        'response_path': str(raw_path), 'model': 'gpt-6-luna',
                        'request_time': '2026-09-24T00:00:00+00:00',
                        'self_check_complete': True, 'automatic_validation_passed': True}
                saved = json.loads(raw_path.read_text())
                if 'redaction' in saved:
                    value['response_redaction'] = saved['redaction']
                return value
            raw_path.write_text(json.dumps(raw))
            with self.assertRaisesRegex(ValueError, 'unsanitized credential material'):
                luna_integration.validate_provenance('study-example', provenance())
            clean = sanitize_record(raw)
            raw_path.write_text(json.dumps(clean))
            luna_integration.validate_provenance('study-example', provenance())
            clean['redaction']['result_changed'] = True
            raw_path.write_text(json.dumps(clean))
            with self.assertRaisesRegex(ValueError, 'stable-source repair'):
                luna_integration.validate_provenance('study-example', provenance())

    def test_queue_covers_missing_topics_once_and_preserves_original_notes(self):
        queue = enrichment.read(enrichment.QUEUE)
        topics = enrichment.read(ROOT / 'data/topics.json')
        content = enrichment.read(ROOT / 'data/content.json')
        original = [tid for batch in queue['batches']
                    for tid in batch.get('original_topic_ids', batch['topic_ids'])]
        queued = [tid for batch in queue['batches'] for tid in batch['topic_ids']]
        external = queue.get('external_acceptances', {})
        self.assertEqual(len(original), len(set(original)))
        self.assertEqual(set(original), {t['study_topic_id'] for t in topics} - set(queue['baseline_content']))
        self.assertEqual(len(queued), len(set(queued)))
        self.assertFalse(set(queued) & set(external))
        self.assertEqual(set(queued) | set(external), set(original))
        for tid, expected in queue['baseline_content'].items():
            self.assertEqual(enrichment.digest(content[tid]), expected)
        for batch in queue['batches']:
            self.assertEqual(batch['status'] == 'absorbed', not bool(batch['topic_ids']))
            if batch['status'] == 'accepted':
                result = enrichment.validate_result(batch)
                self.assertEqual(enrichment.digest(result), batch['result_sha256'])
                for tid, value in result['topics'].items():
                    self.assertEqual(content[tid], value)
        for tid, record in external.items():
            self.assertIn(record['status'], ('prepared', 'accepted'))
            if record['status'] == 'accepted':
                self.assertEqual(enrichment.digest(content[tid]), record['topic_sha256'])
            if tid in content:
                self.assertEqual(enrichment.digest(content[tid]), record['topic_sha256'])

    def test_selection_requires_explicit_unique_ids(self):
        class Args:
            topic_id = []
            ids_file = None
        with self.assertRaisesRegex(ValueError, 'Select IDs'):
            luna_integration.selected_ids(Args())
        Args.topic_id = ['study-one', 'study-one']
        with self.assertRaisesRegex(ValueError, 'Duplicate selected'):
            luna_integration.selected_ids(Args())

    def test_external_import_is_idempotent_and_recovers_prepared_state(self):
        queue = enrichment.read(enrichment.QUEUE)
        batch = next(b for b in queue['batches'] if b['status'] == 'pending' and len(b['topic_ids']) > 1)
        tid = batch['topic_ids'][0]
        url = 'https://example.org/source'
        overview = ' '.join(['A sourced study paragraph explains this topic with careful historical context.'] * 9)
        topic = {
            'overview': [{'id': 'o1', 'text': overview, 'source_urls': [url]}],
            'key_facts': [{'id': f'f{i}', 'text': f'Sourced fact {i}.', 'source_urls': [url]}
                          for i in range(1, 5)],
            'source': {'references': [{'title': 'Example source', 'url': url,
                                      'publisher': 'Example publisher',
                                      'retrieved_at': '2026-09-24T00:00:00+00:00'}]},
        }
        research = {'queries': ['example topic source'],
                    'sources': [{'url': url, 'supports': 'The cited overview and facts.'}],
                    'notes': ''}
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            data = root / 'data'
            run = root / 'run'
            data.mkdir()
            run.mkdir()
            for path in (ROOT / 'data').iterdir():
                if path.name == 'content.json':
                    shutil.copy2(path, data / path.name)
                else:
                    (data / path.name).symlink_to(path, target_is_directory=path.is_dir())
            shutil.copy2(enrichment.QUEUE, run / 'queue.json')
            raw_path = root / 'raw.json'
            raw_path.write_text('{}')
            normalized = {
                'batch_id': 'luna-normalized', 'model': 'gpt-6-luna',
                'topics': {tid: topic}, 'research': {tid: research}, 'blocked_topics': {},
                'provenance': {tid: {
                    'raw_sha256': hashlib.sha256(raw_path.read_bytes()).hexdigest(),
                    'response_path': str(raw_path), 'model': 'gpt-6-luna',
                    'request_time': '2026-09-24T00:00:00+00:00',
                    'self_check_complete': True, 'automatic_validation_passed': True}},
            }
            input_path = root / 'normalized.json'
            enrichment.write(input_path, normalized)
            with patch.object(enrichment, 'ROOT', root), patch.object(enrichment, 'RUN', run), \
                    patch.object(enrichment, 'QUEUE', run / 'queue.json'):
                self.assertEqual(luna_integration.integrate(input_path, [tid])['new'], 1)
                self.assertEqual(luna_integration.integrate(input_path, [tid])['already_accepted'], 1)
                saved_queue = enrichment.read(run / 'queue.json')
                saved_batch = next(b for b in saved_queue['batches'] if b['batch_id'] == batch['batch_id'])
                self.assertIn(tid, saved_batch['original_topic_ids'])
                self.assertNotIn(tid, saved_batch['topic_ids'])
                self.assertEqual(saved_batch['status'], 'pending')
                # Simulate a crash after queue reservation, before content write.
                saved_queue['external_acceptances'][tid]['status'] = 'prepared'
                enrichment.write(run / 'queue.json', saved_queue)
                saved_content = enrichment.read(data / 'content.json')
                del saved_content[tid]
                enrichment.write(data / 'content.json', saved_content)
                self.assertEqual(luna_integration.integrate(input_path, [tid])['resumed'], 1)
                self.assertEqual(enrichment.read(data / 'content.json')[tid], topic)

    def test_batch_with_unlisted_citation_is_rejected(self):
        queue = enrichment.read(enrichment.QUEUE)
        batch = next(b for b in queue['batches'] if (enrichment.RUN / f"{b['batch_id']}-results.json").exists())
        result = copy.deepcopy(enrichment.validate_result(batch))
        next(iter(result['topics'].values()))['key_facts'][0]['source_urls'] = ['https://example.org/unlisted']
        with tempfile.TemporaryDirectory() as directory, patch.object(enrichment, 'RUN', Path(directory)):
            enrichment.write(Path(directory) / f"{batch['batch_id']}-results.json", result)
            with self.assertRaisesRegex(ValueError, 'missing/unknown citation'):
                enrichment.validate_result(batch)


if __name__ == '__main__':
    unittest.main()
