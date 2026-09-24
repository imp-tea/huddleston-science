"""Offline contract tests for the one-topic Luna research pilot."""

import json
from pathlib import Path
import sys
import unittest


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'scripts'))
import luna_topic_pilot as pilot


TOPIC = {
    'study_topic_id': 'study-test-one',
    'topic': 'Test topic',
    'primary_category': 'World History',
    'description': 'Disambiguating context only',
    'source_questions': [{'question': 'A question about the test topic'}],
}
SECOND_TOPIC = {'study_topic_id': 'study-test-two', 'topic': 'Other topic'}
URL = 'https://museum.example.org/test-topic'
STAMP = '2026-09-24T16:00:00Z'


def valid_result():
    return {
        'study_topic_id': TOPIC['study_topic_id'],
        'overview': {
            'text': ' '.join(['An original researched sentence about the assigned historical topic.'] * 10),
            'source_urls': [URL],
        },
        'key_facts': [
            {'text': f'Useful independently checked fact {i}.', 'source_urls': [URL]}
            for i in range(1, 5)
        ],
        'sources': [{
            'title': 'Test topic collection page', 'url': URL, 'publisher': 'Example Museum',
            'retrieved_at': STAMP, 'supports': 'Identity, context, and four facts.',
        }],
        'research_queries': ['test topic museum history'],
        'notes': '', 'unresolved_concerns': [], 'self_check_complete': True,
    }


def trace(*actions):
    return {
        'model': pilot.MODEL,
        'output': [
            {'type': 'web_search_call', 'action': {
                'type': action,
                **({'url': URL} if action == 'open_page' else {}),
            }}
            for action in actions
        ],
    }


class LunaPilotOfflineTests(unittest.TestCase):
    def test_cost_separates_uncached_cached_and_cache_write_tokens(self):
        response = {
            'usage': {
                'input_tokens': 1_000_000,
                'input_tokens_details': {'cached_tokens': 200_000, 'cache_write_tokens': 100_000},
                'output_tokens': 300_000,
                'output_tokens_details': {'reasoning_tokens': 120_000},
            },
            'output': [
                {'type': 'web_search_call', 'action': {'type': 'search'}},
                {'type': 'web_search_call', 'action': {'type': 'open_page'}},
                {'type': 'web_search_call', 'action': {'type': 'search'}},
                {'type': 'message', 'content': []},
            ],
        }
        got = pilot.cost(response)
        self.assertEqual(got['input_tokens'], 1_000_000)
        self.assertEqual(got['cached_input_tokens'], 200_000)
        self.assertEqual(got['cache_write_input_tokens'], 100_000)
        self.assertEqual(got['output_tokens'], 300_000)
        self.assertEqual(got['reasoning_tokens'], 120_000)
        self.assertEqual(got['search_calls'], 2)
        self.assertAlmostEqual(got['token_usd'], 0.2345)
        self.assertAlmostEqual(got['search_usd'], 0.02)
        self.assertAlmostEqual(got['estimated_usd'], 0.2545)

    def test_request_is_for_one_topic_with_fixed_model_and_web_tool(self):
        manifest = {'reasoning_effort': 'medium', 'max_tool_calls': 12, 'max_output_tokens': 6000,
                    'topics': [TOPIC, SECOND_TOPIC]}
        request = pilot.make_request(TOPIC, manifest)
        prompt_data = json.loads(request['input'])
        self.assertEqual(request['model'], 'gpt-6-luna')
        self.assertEqual(request['tools'], [{'type': 'web_search'}])
        self.assertEqual(request['tool_choice'], 'required')
        self.assertFalse(request['store'])
        self.assertEqual(prompt_data['assigned_topic'], TOPIC)
        self.assertNotIn(SECOND_TOPIC['study_topic_id'], request['input'])
        self.assertEqual(request['max_tool_calls'], 12)
        self.assertEqual(request['max_output_tokens'], 6000)
        self.assertEqual(request['text']['format']['schema'], pilot.SCHEMA)

    def test_validation_requires_both_real_search_and_open_actions(self):
        value = valid_result()
        self.assertTrue(pilot.validate(value, TOPIC, trace('search', 'open_page'))['valid'])
        for actions, expected in [
            ((), 'No search action in API trace'),
            (('open_page',), 'No search action in API trace'),
            (('search',), 'No direct source-open action in API trace'),
        ]:
            with self.subTest(actions=actions):
                report = pilot.validate(value, TOPIC, trace(*actions))
                self.assertFalse(report['valid'])
                self.assertIn(expected, report['errors'])

    def test_validation_rejects_wrong_topic_and_unlisted_or_missing_citation(self):
        response = trace('search', 'open_page')
        wrong = valid_result()
        wrong['study_topic_id'] = SECOND_TOPIC['study_topic_id']
        self.assertIn('Topic ID mismatch', pilot.validate(wrong, TOPIC, response)['errors'])
        for bad_urls in ([], ['https://other.example.org/unlisted']):
            with self.subTest(urls=bad_urls):
                value = valid_result()
                value['key_facts'][0]['source_urls'] = bad_urls
                report = pilot.validate(value, TOPIC, response)
                self.assertFalse(report['valid'])
                self.assertIn('Unknown/missing block citation', report['errors'])

    def test_validation_rejects_wrong_returned_model(self):
        response = trace('search', 'open_page')
        response['model'] = 'gpt-6-sol'
        report = pilot.validate(valid_result(), TOPIC, response)
        self.assertFalse(report['valid'])
        self.assertIn('Returned model differs from GPT-6 Luna', report['errors'])

    def test_validation_rejects_citation_that_was_listed_but_not_opened(self):
        response = trace('search', 'open_page')
        response['output'][1]['action']['url'] = 'https://museum.example.org/other-page'
        report = pilot.validate(valid_result(), TOPIC, response)
        self.assertFalse(report['valid'])
        self.assertIn(f'Cited source has no matching open_page action: {URL}', report['errors'])

    def test_validation_accepts_normalized_opened_url(self):
        response = trace('search', 'open_page')
        response['output'][1]['action']['url'] = 'https://www.museum.example.org/test-topic/?utm_source=pilot#section'
        self.assertTrue(pilot.validate(valid_result(), TOPIC, response)['valid'])

    def test_validation_rejects_missing_reference_metadata_and_unresolved_concerns(self):
        value = valid_result()
        value['sources'][0]['supports'] = ''
        value['unresolved_concerns'] = ['An important claim could not be checked']
        report = pilot.validate(value, TOPIC, trace('search', 'open_page'))
        self.assertFalse(report['valid'])
        self.assertIn('Incomplete reference', report['errors'])
        self.assertIn('Researcher reported unresolved concerns', report['errors'])


if __name__ == '__main__':
    unittest.main()
