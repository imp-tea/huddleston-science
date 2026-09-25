"""Conservative lexical signals for model review, not semantic error verdicts."""
import re
import unicodedata

VERSION = 'lexical-v1'
STOP = set('a an the of for from to in on at by with and or as is it its this that these those be are was were has have had do does not no one two three what which who how when where why'.split())
GENERIC = set('cloth dance chapel pope aircraft navy union crisis theater strait gulf forest matrix mathematical circle identity product properties decimal curve syllable airline flight operation classification person people place name title work book novel poem play story song film movie series character man woman king queen emperor president saint st sir dr lord lady city town country state states united river lake sea ocean mountain mount island islands war battle attack attacks party act law theorem equation theory principle rule model scale system function number constant property process effect period era age movement school empire republic kingdom language family church god goddess religion first second third fourth fifth i ii iii iv v vi vii viii ix x saint'.split()).union(STOP)
SUFFIXES = ('s', 'es', 'ism', 'ist', 'ists', 'ian', 'ians', 'an', 'al', 'ic', 'ical', 'ity', 'ous', 'ing', 'ed', 'ation')


def tokens(text):
    value = ''.join(c for c in unicodedata.normalize('NFKD', text) if not unicodedata.combining(c))
    return re.findall(r"[^\W_]+", value.casefold(), re.UNICODE)


def related(a, b):
    return a == b or (len(a) >= 4 and any(b == a + s or a == b + s for s in SUFFIXES))


def detect(question, answer, topic='', slot=1):
    stem, target, topic_tokens = tokens(question), tokens(answer), tokens(topic)
    if not target:
        return []
    reasons = []
    phrase = ' '.join(target)
    if any(len(t) >= 2 and t not in STOP for t in target) and (' ' + phrase + ' ') in (' ' + ' '.join(stem) + ' '):
        reasons.append({'kind': 'exact_answer', 'answer_text': answer,
                        'matched_text': phrase, 'note': 'The full normalized answer appears in the question.'})
        return reasons
    meaningful = [t for t in target if len(t) >= 4 and t not in GENERIC and not t.isdigit()]
    for t in dict.fromkeys(meaningful):
        # Later questions must name the topic. Do not flag only that required overlap.
        if slot > 1 and any(related(t, w) for w in topic_tokens):
            continue
        matches = [w for w in dict.fromkeys(stem) if related(t, w)]
        if matches:
            reasons.append({'kind': 'answer_word' if t in matches else 'derived_word',
                            'answer_text': t, 'matched_text': ', '.join(matches),
                            'note': 'A potentially identifying answer word or close word form occurs in the clues.'})
    return reasons


def scan(result, topic):
    return [{'slot': slot, 'reasons': reasons}
            for slot, q in enumerate(result['questions'], 1)
            if (reasons := detect(q['question'], q['answer'], topic, slot))]
