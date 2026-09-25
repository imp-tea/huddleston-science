import copy
import json
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import patch
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'scripts'))
import typed_question_full as f


class FullRunTests(unittest.TestCase):
    def test_followup_replays_complete_response_output_and_settings(self):
        request={'model':'gpt-6-luna','store':False,'reasoning':{'effort':'xhigh'},'max_output_tokens':16000,'input':'original prompt and context','text':{'format':{'schema':f.p.SCHEMA_V4}}}
        response={'output':[{'type':'reasoning','id':'r','encrypted_content':'opaque'},
                            {'type':'message','role':'assistant','phase':'final_answer','content':[{'type':'output_text','text':'{}'}]}]}
        original=copy.deepcopy(request);flags=[{'slot':1,'reasons':[{'matched_text':'drake'}]}]
        corrected=f.correction_request(request,response,flags,'Review {flags}')
        self.assertEqual(corrected['input'][1:-1],response['output'])
        self.assertEqual(corrected['input'][0],{'role':'user','content':'original prompt and context'})
        self.assertIn('drake',corrected['input'][-1]['content'])
        self.assertEqual(corrected['reasoning'],{'effort':'xhigh'})
        self.assertEqual(request,original)
        self.assertEqual(corrected['text'],request['text'])

    def test_only_flagged_stems_change_and_answers_are_preserved(self):
        original={'questions':[{'question':'Old one','answer':'One'},{'question':'Old two','answer':'Two'}]}
        corrected={'questions':[{'question':'New one','answer':'One'},{'question':'Unrequested change','answer':'Two'}]}
        merged,ignored=f.merge_correction(original,corrected,[{'slot':1}])
        self.assertEqual(merged['questions'][0]['question'],'New one')
        self.assertEqual(merged['questions'][1],original['questions'][1])
        self.assertEqual(ignored,[2])
        corrected['questions'][0]['answer']='Different'
        with self.assertRaises(ValueError):f.merge_correction(original,corrected,[{'slot':1}])

    def test_harmless_match_can_remain_unchanged(self):
        original={'questions':[{'question':'What color is described?','answer':'Blue'}]}
        merged,ignored=f.merge_correction(original,copy.deepcopy(original),[{'slot':1}])
        self.assertEqual(merged,original);self.assertEqual(ignored,[])

    def test_known_pilot_flags_are_detected(self):
        cases=f.p.read(Path(__file__).parent/'fixtures/typed-giveaways.json')
        for case in cases:
            with self.subTest(answer=case['answer']):
                self.assertTrue(f.g.detect(case['question'],case['answer'],case['topic'],case['slot']))

    def test_completed_outcome_is_not_redispatched(self):
        with tempfile.TemporaryDirectory() as d:
            run=Path(d);o={'status':'completed'};f.p.write(run/'outcomes/test.json',o)
            with patch.object(f,'stage_call',side_effect=AssertionError('No dispatch')):
                self.assertEqual(f.process_topic(run,{'context':{'study_topic_id':'test'}},'unused'),o)

    def test_nontransient_errors_are_not_retried(self):
        with tempfile.TemporaryDirectory() as d:
            run=Path(d);entry={'context':{'study_topic_id':'test'}}
            with patch.object(f.p,'run_one',return_value={'status':'http_error','http_status':401}) as call:
                record,attempts=f.stage_call(run,'generation',entry,{},'unused')
                self.assertEqual(call.call_count,1);self.assertEqual(len(attempts),1)


if __name__=='__main__':unittest.main()
