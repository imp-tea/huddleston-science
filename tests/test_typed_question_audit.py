import sys
from pathlib import Path
import tempfile
import unittest
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'scripts'))
import audit_typed_question_full as a
import repair_typed_question_full as r


class AuditTests(unittest.TestCase):
    def test_topic_mentions_allow_plurals_but_not_substrings(self):
        self.assertTrue(a.contains_topic('The rule describes how eggs are cracked.','Egg'))
        self.assertTrue(a.contains_topic('Among self-portraits, this work is well known.','Self-portrait'))
        self.assertTrue(a.contains_topic('In this story about fasting, identify the writer.','Fasting (practice)'))
        self.assertFalse(a.contains_topic('These are not relevant thoughts.','Ant'))
        self.assertFalse(a.contains_topic('Which landmark is in Delhi?','Minaret'))

    def test_repairs_cannot_overwrite_outcomes_during_active_generation(self):
        with tempfile.TemporaryDirectory() as directory:
            run=Path(directory);a.f.p.write(run/'summary.json',{'running':True})
            with self.assertRaises(SystemExit):r.apply(run)
            self.assertFalse((run/'outcomes').exists())


if __name__=='__main__':unittest.main()
