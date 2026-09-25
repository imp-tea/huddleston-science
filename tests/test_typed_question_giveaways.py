import sys
from pathlib import Path
import unittest
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'scripts'))
from typed_question_giveaways import detect


class GiveawayTests(unittest.TestCase):
    def test_real_pilot_giveaways(self):
        cases = [
            ('This company began as ByteDance.', 'ByteDance'),
            ('The directors were Baker and Miller.', 'Baker-Miller pink'),
            ('An agent played by Jake Stone works for State Farm.', 'Jake from State Farm'),
            ('Frank Drake formulated this expression.', 'Drake equation'),
            ('Led by George Donner and James Reed.', 'Donner Party'),
            ('Promoted by Lansford Hastings.', 'Hastings Cutoff'),
            ('On January 6, 2021 a crowd entered the Capitol.', 'January 6, 2021 attack on the U.S. Capitol'),
            ('Which deity is central to Atenism?', 'Aten'),
        ]
        for stem, answer in cases:
            with self.subTest(answer=answer):
                self.assertTrue(detect(stem, answer))

    def test_boundaries_diacritics_and_punctuation(self):
        self.assertFalse(detect('There were a hundred objects.', 'Red'))
        self.assertTrue(detect('It was called CUCUTA.', 'Cúcuta'))
        self.assertTrue(detect('A portrait by Van-Eyck.', 'Jan van Eyck'))
        self.assertFalse(detect('It became famous.', 'It'))

    def test_required_topic_overlap_and_generic_terms_are_not_enough(self):
        self.assertFalse(detect('Cosine supplies the relation c² = a² + b² − 2ab cos C. Which theorem?', 'Law of Cosines', 'Cosine function', 2))
        self.assertFalse(detect('What is the classification system?', 'Dewey Decimal Classification', 'Dewey Decimal Classification', 1))
        self.assertFalse(detect('What is this poem?', 'Ode to a Nightingale'))
        self.assertTrue(detect('The Law of Cosines supplies this relation. Name it.', 'Law of Cosines', 'Cosine function', 2))


if __name__ == '__main__':
    unittest.main()
