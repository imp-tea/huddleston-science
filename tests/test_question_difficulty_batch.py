import json
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import Mock, patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'scripts'))
import question_difficulty_batch as batch


class DifficultyBatchTests(unittest.TestCase):
    def setUp(self):
        self.questions = [{'question_id': 'a', 'source_sha256': 'hash-a'},
                          {'question_id': 'b', 'source_sha256': 'hash-b'}]

    def output(self, qid, label='Easy', status='completed'):
        return json.dumps({'custom_id': qid, 'error': None, 'response': {
            'status_code': 200, 'body': {'id': 'response-' + qid, 'status': status,
            'model': 'gpt-6-sol', 'output': [{'content': [{'type': 'output_text', 'text': label}]}],
            'usage': {'input_tokens': 100, 'output_tokens': 8}}}})

    def test_outputs_join_by_id_not_file_order(self):
        results, failures, missing, usage = batch.parse_outputs(
            [self.output('b', 'Hard'), self.output('a')], self.questions)
        self.assertEqual(results['a']['difficulty'], 'easy')
        self.assertEqual(results['b']['source_sha256'], 'hash-b')
        self.assertEqual(results['b']['difficulty'], 'hard')
        self.assertEqual((failures, missing), ([], []))
        self.assertEqual(usage['input_tokens'], 200)

    def test_duplicate_and_unknown_ids_are_rejected(self):
        for lines in ([self.output('a'), self.output('a')], [self.output('other')]):
            with self.assertRaises(ValueError):
                batch.parse_outputs(lines, self.questions)

    def test_missing_invalid_and_incomplete_are_not_accepted(self):
        for label, status in [('Very easy', 'completed'), ('Easy', 'incomplete')]:
            results, failures, missing, _ = batch.parse_outputs(
                [self.output('a', label, status)], self.questions)
            self.assertFalse(results)
            self.assertEqual(len(failures), 1)
            self.assertEqual(missing, ['b'])

    def test_publish_rejects_stale_question_before_writing(self):
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            batch.write(root / 'summary.json', {'failed': 0, 'missing': 0})
            batch.write(root / 'annotations.json', {'questions': {
                q['question_id']: {'source_sha256': q['source_sha256'], 'difficulty': 'easy'}
                for q in self.questions}})
            changed = [self.questions[0], {**self.questions[1], 'source_sha256': 'new-hash'}]
            with patch.object(batch, 'ROOT', root), patch.object(batch, 'source_questions', return_value=changed):
                with self.assertRaises(ValueError):
                    batch.publish(root, {'questions': self.questions})
            self.assertFalse((root / 'data/question-difficulty.json').exists())

    def test_interrupted_submission_reconciles_without_new_paid_request(self):
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            batch.write(root / 'submission-pending.json', {})
            api = Mock()
            remote = {'id': 'batch-existing', 'metadata': {'run_id': 'our-run'}}
            api.call.return_value = {'data': [remote], 'has_more': False}
            with patch.object(batch, 'validate_input'):
                result = batch.submit(root, {'run_id': 'our-run'}, api)
            self.assertEqual(result['id'], 'batch-existing')
            api.call.assert_called_once_with('/batches?limit=100')
            api.upload.assert_not_called()

    def test_unknown_submission_outcome_does_not_resubmit(self):
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            batch.write(root / 'submission-pending.json', {})
            api = Mock()
            api.call.return_value = {'data': [], 'has_more': False}
            with patch.object(batch, 'validate_input'), self.assertRaises(ValueError):
                batch.submit(root, {'run_id': 'our-run'}, api)
            api.call.assert_called_once_with('/batches?limit=100')
            api.upload.assert_not_called()

    def test_split_preserves_submitted_part_and_exact_request_bytes(self):
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            batch.write(root / 'parts.json', ['submitted', 'pending'])
            full = b''
            for name in ('submitted', 'pending'):
                folder = root / name
                folder.mkdir()
                text = ''.join(json.dumps({'id': name + str(i)}) + '\n' for i in range(1000))
                (folder / 'input.jsonl').write_text(text)
                import hashlib
                batch.write(folder / 'manifest.json', {
                    'questions': [{'format': 'typed'} for _ in range(1000)],
                    'input_sha256': hashlib.sha256(text.encode()).hexdigest()})
                full += text.encode()
            batch.write(root / 'submitted/submission-pending.json', {})
            (root / 'input.jsonl').write_bytes(full)
            result = batch.split_pending(root, {})
            self.assertEqual(result['parts'], ['submitted', 'pending-1', 'pending-2'])
            self.assertEqual(b''.join((root / p / 'input.jsonl').read_bytes() for p in result['parts']), full)


if __name__ == '__main__':
    unittest.main()
