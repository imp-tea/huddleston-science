"""Offline checks for pilot constraints; no API calls or production imports."""
import copy
import json
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'scripts'))
import typed_question_pilot as p


class TypedQuestionPilotTests(unittest.TestCase):
    def test_v5_readable_context_preserves_sources_and_same_sample(self):
        with tempfile.TemporaryDirectory() as d:
            previous = p.initialize(Path(d) / 'v4', 'v4')
            current = p.initialize(Path(d) / 'v5', 'v5')
            self.assertEqual(current['population_questions'], 15947)
            self.assertEqual(sum(e['context']['requested_question_count'] for e in current['topics']), 201)
            for a, b in zip(previous['topics'], current['topics']):
                self.assertEqual(a['context'], b['context'])
                c = b['context']
                request = p.read(Path(d) / 'v5/requests' / (c['study_topic_id'] + '.json'))
                supplied = (Path(d) / 'v5/supplied-context' / (c['study_topic_id'] + '.txt')).read_text()
                prompt, actual = request['input'].split('\n\n---\n\n', 1)
                self.assertEqual(actual, supplied)
                self.assertEqual(prompt, p.PROMPT_V5.read_text().strip().replace('{count}', str(c['requested_question_count'])))
                self.assertIn(c['description'], supplied)
                for block in (c['study_content'] or {}).get('overview', []) + (c['study_content'] or {}).get('key_facts', []):
                    self.assertIn(block['text'], supplied)
                for source in c['source_questions']:
                    for part in source['parts']:
                        self.assertIn(part['question'], supplied)
                        if part['answer']:
                            self.assertIn('Answer: ' + part['answer'], supplied)
                self.assertNotIn('evidence_map', supplied)
                self.assertNotIn('study_topic_id', supplied)
                self.assertEqual(request['reasoning'], {'effort': 'xhigh'})
                self.assertEqual(request['text']['format']['schema'], p.SCHEMA_V4)
            pi = p.readable_context(current['topics'][28]['context'])
            self.assertTrue(pi.startswith('Topic: Pi\n'))
            for label in ('Question 7:', 'Question 7A:', 'Question 7B:', 'Question 7C:'):
                self.assertIn(label, pi)

    def test_v5_title_and_answer_length_are_not_hard_constraints(self):
        self.assertEqual(p.natural_topic_name('Pi (constant and notation)'), 'Pi')
        self.assertEqual(p.natural_topic_name('The Count of Monte Cristo'), 'The Count of Monte Cristo')
        context = {'requested_question_count': 1, 'topic': 'Night (memoir)'}
        self.assertTrue(p.validate({'questions': [{'question': 'Name this work.', 'answer': 'Night'}]}, context, 'v5')['valid'])
        self.assertTrue(p.validate({'questions': [{'question': 'Name this work.', 'answer': 'The Count of Monte Cristo'}]}, context, 'v5')['valid'])

    def test_v4_exact_prompt_minimal_output_and_xhigh(self):
        context = {'topic': 'Example', 'requested_question_count': 2}
        request = p.make_request(context, p.PROMPT_V4.read_text(), 'v4')
        prompt, supplied = request['input'].split('\n\n', 1)
        self.assertEqual(prompt, p.PROMPT_V4.read_text().strip().replace('{count}', '2'))
        self.assertEqual(json.loads(supplied), context)
        self.assertNotIn('instructions', request)
        self.assertEqual(request['model'], 'gpt-6-luna')
        self.assertEqual(request['reasoning']['effort'], 'xhigh')
        self.assertEqual(request['max_output_tokens'], 16000)
        schema = request['text']['format']['schema']
        self.assertEqual(set(schema['properties']), {'questions'})
        self.assertEqual(set(schema['properties']['questions']['items']['properties']), {'question', 'answer'})
        result = {'questions': [{'question': 'Name a concept.', 'answer': 'Example'},
                                {'question': 'Name a second concept.', 'answer': 'Other'}]}
        self.assertTrue(p.validate(result, context, 'v4')['valid'])
        result['questions'][0]['accepted_answers'] = []
        self.assertFalse(p.validate(result, context, 'v4')['valid'])

    def test_v4_same_sample_full_context_and_new_quota(self):
        with tempfile.TemporaryDirectory() as d:
            old = p.initialize(Path(d) / 'v2', 'v2')
            new = p.initialize(Path(d) / 'v4', 'v4')
            self.assertEqual(new['population_questions'], 15947)
            self.assertEqual(sum(e['context']['requested_question_count'] for e in new['topics']), 201)
            self.assertEqual(sum(e['context']['requested_question_count'] * e['population_weight'] for e in new['topics']), 15947)
            self.assertIsNone(new['examples_sha256'])
            for a, b in zip(old['topics'], new['topics']):
                expected = {**a['context'], 'requested_question_count': max(2, a['context']['requested_question_count'])}
                self.assertEqual(b['context'], expected)
                self.assertTrue(2 <= b['context']['requested_question_count'] <= 5)

    def setUp(self):
        self.context = {'study_topic_id': 'test', 'topic': 'John Steinbeck',
                        'aliases': ['Steinbeck'], 'source_question_count': 1,
                        'requested_question_count': 1,
                        'evidence_map': {'description': 'The Joads appear in The Grapes of Wrath.'}}
        self.question = {'slot': 1, 'status': 'ready',
                         'question': 'Which novel follows the Joad family?',
                         'canonical_answer': 'The Grapes of Wrath', 'accepted_answers': [],
                         'prompt_answers': [], 'rejected_answers': [],
                         'answer_relation': 'related', 'difficulty': 'easy',
                         'explanation': 'The Joad family appears in this novel.',
                         'evidence': [{'claim': 'The novel follows the Joads.', 'evidence_ids': ['description']}],
                         'concerns': []}

    def result(self, question=None):
        return {'study_topic_id': 'test', 'questions': [question or self.question]}

    def test_single_source_alias_even_if_mislabeled_is_rejected(self):
        q = copy.deepcopy(self.question)
        q['canonical_answer'] = 'Steinbeck'
        self.assertIn('slot 1: Single-source topic answer prohibited', p.validate(self.result(q), self.context)['errors'])
        self.assertTrue(p.validate(self.result(), self.context)['valid'])

    def test_unknown_evidence_and_conflicting_answers_rejected(self):
        q = copy.deepcopy(self.question)
        q['evidence'][0]['evidence_ids'] = ['invented']
        q['prompt_answers'] = ['Grapes of Wrath']
        errors = p.validate(self.result(q), self.context)['errors']
        self.assertIn('slot 1: Missing or unknown evidence', errors)
        self.assertIn('slot 1: Conflicting answer policy', errors)

    def test_full_bonus_is_one_source_and_leadin_preserved(self):
        t = {'study_topic_id': 'test', 'topic': 'T', 'description': 'D',
             'primary_category': 'C', 'source_ids': ['s1', 's1'], 'subcategory_ids': ['sub']}
        source = {'parts': [{'label': label, 'question': 'Context ' + label, 'answer': ''}
                            for label in ['L', 'A', 'B', 'C']]}
        context = p.topic_context(t, {}, {'s1': source}, {'sub': {'label': 'subcategory'}})
        self.assertEqual(context['requested_question_count'], 1)
        self.assertEqual(context['source_question_count'], 1)
        self.assertIn('s1:L', context['evidence_map'])
        self.assertEqual(context['source_questions'], [source])

    def test_manifest_covers_population_and_preserves_all_data(self):
        before = p.data_hashes()
        with tempfile.TemporaryDirectory() as d:
            run = Path(d)
            manifest = p.initialize(run)
            self.assertEqual(len(manifest['topics']), 69)
            self.assertEqual(sum(e['population_weight'] for e in manifest['topics']), 7072)
            self.assertEqual(sum(e['context']['requested_question_count'] for e in manifest['topics']), 177)
            self.assertEqual(sum(e['context']['requested_question_count'] * e['population_weight']
                                 for e in manifest['topics']), 10976)
            self.assertEqual(p.initialize(run), manifest)
            for e in manifest['topics']:
                body = p.read(run / 'requests' / (e['context']['study_topic_id'] + '.json'))
                self.assertEqual(body['model'], 'gpt-6-luna')
                self.assertNotIn('tools', body)
                self.assertEqual(p.digest(body), e['request_sha256'])
        self.assertEqual(before, p.data_hashes())

    def test_saved_response_never_reissued(self):
        with tempfile.TemporaryDirectory() as d:
            run = Path(d)
            record = {'status': 'completed'}
            p.write(run / 'responses/test.json', record)
            with patch.object(p, 'urlopen', side_effect=AssertionError('Must not call API')):
                self.assertEqual(p.run_one(run, {'context': self.context}, 'unused'), record)

    def test_v2_allows_single_source_title_and_rejects_duplicate_concepts_by_alias(self):
        q = copy.deepcopy(self.question)
        q['canonical_answer'] = 'John Steinbeck'
        q['accepted_answers'] = ['Steinbeck']
        q['answer_relation'] = 'topic'
        self.assertTrue(p.validate(self.result(q), self.context, 'v2')['valid'])
        context = {**self.context, 'requested_question_count': 2, 'source_question_count': 2}
        other = {**copy.deepcopy(q), 'slot': 2, 'canonical_answer': 'Steinbeck',
                 'accepted_answers': [], 'question': 'Name the author of another novel.'}
        report = p.validate({'study_topic_id': 'test', 'questions': [q, other]}, context, 'v2')
        self.assertIn('slot 2: Duplicate question or target answer', report['errors'])

    def test_v2_few_shot_pairs_and_high_reasoning_are_in_the_request(self):
        examples = p.read(p.EXAMPLES_V2)
        for example in examples:
            self.assertTrue(p.validate(example['output'], example['input'], 'v2')['valid'])
        request = p.make_request(self.context, p.PROMPT_V2.read_text(), 'v2')
        self.assertEqual(request['reasoning'], {'effort': 'high'})
        self.assertEqual(request['max_output_tokens'], 12000)
        self.assertEqual(len(request['input']), 2 * len(examples) + 1)
        self.assertEqual(json.loads(request['input'][-1]['content']), self.context)
        self.assertEqual(request['input'][1]['role'], 'assistant')

    def test_v2_keeps_same_sample_and_freezes_examples(self):
        with tempfile.TemporaryDirectory() as d:
            a = p.initialize(Path(d) / 'v1')
            b = p.initialize(Path(d) / 'v2', 'v2')
            self.assertEqual([e['context'] for e in a['topics']], [e['context'] for e in b['topics']])
            self.assertEqual(b['examples_sha256'], p.digest(p.read(p.EXAMPLES_V2)))
            with self.assertRaises(ValueError):
                p.initialize(Path(d) / 'v2', 'v1')

    def test_v3_changes_only_model_in_live_request(self):
        a = p.make_request(self.context, p.PROMPT_V2.read_text(), 'v2')
        b = p.make_request(self.context, p.PROMPT_V2.read_text(), 'v3')
        self.assertEqual(b.pop('model'), 'gpt-5.6-luna')
        a.pop('model')
        self.assertEqual(a, b)

    def test_v3_allows_shared_accepted_strings_but_not_duplicate_stems(self):
        context = {**self.context, 'requested_question_count': 2}
        other = {**copy.deepcopy(self.question), 'slot': 2,
                 'question': 'Name the work about the Joads.'}
        result = {'study_topic_id': 'test', 'questions': [self.question, other]}
        self.assertTrue(p.validate(result, context, 'v3')['valid'])
        other['question'] = self.question['question']
        self.assertFalse(p.validate(result, context, 'v3')['valid'])

    def test_v3_prices_usage_without_double_counting_reasoning(self):
        response = {'usage': {'input_tokens': 1000, 'output_tokens': 2000,
                              'input_tokens_details': {'cached_tokens': 300, 'cache_write_tokens': 200},
                              'output_tokens_details': {'reasoning_tokens': 1500}}}
        result = p.request_cost(response, 'gpt-5.6-luna')
        self.assertAlmostEqual(result['estimated_usd'], .002556)
        self.assertEqual(result['reasoning_tokens'], 1500)

    def test_v3_manifest_and_contexts_match_comparison(self):
        with tempfile.TemporaryDirectory() as d:
            a = p.initialize(Path(d) / 'v2', 'v2')
            b = p.initialize(Path(d) / 'v3', 'v3')
            self.assertEqual([e['context'] for e in a['topics']], [e['context'] for e in b['topics']])
            self.assertEqual(b['model'], 'gpt-5.6-luna')
            self.assertEqual(b['pricing_usd_per_million']['output'], 1.2)
            self.assertEqual(a['prompt_sha256'], b['prompt_sha256'])
            self.assertEqual(a['examples_sha256'], b['examples_sha256'])


if __name__ == '__main__':
    unittest.main()
