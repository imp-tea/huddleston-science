"""Offline checks for protecting paid requests during interruption/resumption."""
import json
from pathlib import Path
import sys
from tempfile import TemporaryDirectory
import unittest
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'scripts'))
import luna_topic_batch as batch


class BatchSafetyTests(unittest.TestCase):
    def test_interrupted_request_keeps_reconciliation_marker(self):
        with TemporaryDirectory() as directory:
            run = Path(directory)
            topic = {'study_topic_id': 'study-test'}
            with patch.object(batch, 'RUN', run), patch.object(batch.pilot, 'run_one', side_effect=RuntimeError):
                with self.assertRaises(RuntimeError):
                    batch.run_recorded(topic, {}, 'test-token')
            marker = json.loads((run / 'inflight/study-test.json').read_text())
            self.assertEqual(marker['topic_id'], 'study-test')
            self.assertNotIn('test-token', json.dumps(marker))

    def test_completed_response_clears_dispatch_marker(self):
        with TemporaryDirectory() as directory:
            run = Path(directory)
            topic = {'study_topic_id': 'study-test'}
            result = {'topic_id': 'study-test', 'status': 'completed'}

            def finish(*args):
                self.assertTrue((run / 'inflight/study-test.json').exists())
                return result

            with patch.object(batch, 'RUN', run), patch.object(batch.pilot, 'run_one', side_effect=finish):
                self.assertEqual(batch.run_recorded(topic, {}, 'test-token'), result)
            self.assertFalse((run / 'inflight/study-test.json').exists())

    def test_guardrail_accounts_for_inflight_requests(self):
        self.assertTrue(batch.can_dispatch(34.75, 20, 40))
        self.assertFalse(batch.can_dispatch(35, 20, 40))
        self.assertFalse(batch.can_dispatch(39.80, 0, 40))


if __name__ == '__main__':
    unittest.main()
