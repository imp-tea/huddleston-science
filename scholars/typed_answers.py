"""Typed matching ported from the quiz-bowl explorer; no semantic/phonetic aliases.

NFD deliberately preserves superscripts. Bank indexes and question views are
bounded, process-local caches keyed by immutable bank content, never current IDs.
"""
from functools import lru_cache
import json
import re
import unicodedata

VERSION = "typed-v1"
FILLER = set('a an the of in on at to for and or with from by as is it its this that'.split())


def is_letter(c):
    return unicodedata.category(c).startswith('L')


def is_number(c):
    return unicodedata.category(c).startswith('N')


def runs(text, predicate):
    return re.findall(r'[^\x00]+', ''.join(c if predicate(c) else '\x00' for c in text))


def answer_key(value):
    value = ''.join(c for c in unicodedata.normalize('NFD', value) if not unicodedata.category(c).startswith('M'))
    return ' '.join(value.lower().translate(str.maketrans('’‘“”–—−', '\'\'""---')).split())


def search_key(value):
    return ' '.join(''.join(c if is_letter(c) or is_number(c) or c in '+#/=<>%^*.-' else ' ' for c in answer_key(value)).split())


def number_tokens(text, decimals=False):
    result, i = [], 0
    while i < len(text):
        start = i
        if text[i] in '+-' and i + 1 < len(text) and is_number(text[i + 1]):
            i += 1
        if is_number(text[i]):
            i += 1
            while i < len(text) and (is_number(text[i]) or (decimals and text[i] in '.,' and i + 1 < len(text) and is_number(text[i + 1]))):
                i += 1
            result.append((start, text[start:i]))
        else:
            i += 1
    return result


def wording_key(value):
    key = answer_key(value)
    if any(unicodedata.category(c).startswith('S') or c in '#/%^*' for c in key):
        return None
    numbers = [token for _, token in number_tokens(key, True)]
    key = re.sub(r"(.)'s(?![a-z0-9_])", lambda m: m[1] if is_letter(m[1]) else m[0], key)
    words = runs(key, lambda c: is_letter(c) or is_number(c))
    if words and words[0] in ('a', 'an', 'the') and (len(words) < 2 or words[1] not in ('major', 'minor')):
        words.pop(0)
    content = sorted(w for w in words if w not in ('the', 'of'))
    return json.dumps([numbers, content], ensure_ascii=False, separators=(',', ':')) if content else None


def answer_index(answers):
    index = []
    for text in answers:
        key = search_key(text)
        words = key.split(' ')
        index.append(dict(text=text, key=key, wording=wording_key(text),
                          parts=[' '.join(words[i:]) for i in range(len(words))]))
    return index


@lru_cache(maxsize=24)
def bank_index(version, answers):
    return answer_index(answers)


def question_bank(index, correct_answer):
    expected, wording = answer_key(correct_answer), wording_key(correct_answer)
    filtered, suppressed, found = [], set(), False
    for entry in index:
        text = entry['text']
        if answer_key(text) == expected:
            found = True
            text = correct_answer
        elif wording is not None and entry['wording'] == wording:
            suppressed.add(answer_key(text))
            text = correct_answer
        filtered.append({**entry, 'text': text})
    if not found:
        filtered.extend(answer_index([correct_answer]))
    return dict(index=filtered, suppressedAnswers=suppressed)


@lru_cache(maxsize=32)
def prepared_bank(version, answers, correct_answer):
    return question_bank(bank_index(version, answers), correct_answer)


def for_item(item):
    bank = item.answer_bank
    return prepared_bank(bank.pk, tuple(bank.answers), item.revision.payload['correct_answer'])


def distance(a, b, min_prefix=None):
    previous, before = list(range(len(b) + 1)), None
    for i in range(1, len(a) + 1):
        row = [i]
        for j in range(1, len(b) + 1):
            value = min(previous[j] + 1, row[j - 1] + 1, previous[j - 1] + (a[i - 1] != b[j - 1]))
            if i > 1 and j > 1 and a[i - 1] == b[j - 2] and a[i - 2] == b[j - 1]:
                value = min(value, before[j - 2] + 1)
            row.append(value)
        before, previous = previous, row
    return previous[-1] if min_prefix is None else min(previous[min_prefix:])


def significant(text):
    tokens = number_tokens(text)
    tokens.extend((i, c) for i, c in enumerate(text) if c in '+#/=<>%^*' and not (c == '+' and i + 1 < len(text) and is_number(text[i + 1])))
    tokens.extend((m.start(), m[0]) for m in re.finditer(r'\b[ivx]+\b', text, re.ASCII))
    return '|'.join(token for _, token in sorted(tokens))


def grade(answer, correct_answer, allow_prompt=True, suppressed_answers=()):
    if answer is None:
        return 'skipped'
    given, expected = answer_key(answer), answer_key(correct_answer)
    if given == expected:
        return 'correct'
    if allow_prompt and given in suppressed_answers:
        return 'prompt'
    if not allow_prompt or len(given) < 4 or len(given) > 240:
        return 'incorrect'
    if not any(len(word) >= 4 and word not in FILLER for word in runs(given, is_letter)):
        return 'incorrect'
    given_symbols, expected_symbols = significant(given), significant(expected)
    if given_symbols and given_symbols != expected_symbols:
        return 'incorrect'
    start = expected.find(given)
    while start != -1:
        if start == 0 or not (is_letter(expected[start - 1]) or is_number(expected[start - 1])):
            return 'prompt'
        start = expected.find(given, start + 1)
    if given_symbols != expected_symbols:
        return 'incorrect'
    length = max(len(given), len(expected))
    if abs(len(given) - len(expected)) > length * .15:
        return 'incorrect'
    return 'prompt' if 1 - distance(given, expected) / length >= .85 else 'incorrect'


def rebuild_banks():
    """Called under the import lock; old banks remain protected by session items."""
    from .models import AnswerBank, Category, Question
    from .importer import digest
    banks = {}
    for category, payload in Question.objects.filter(active=True, topic__active=True, current_revision__isnull=False).order_by('pk').values_list('topic__category_id', 'current_revision__payload'):
        bank = banks.setdefault(category, {})
        for answer in [payload['correct_answer'], *payload['distractors']]:
            bank.setdefault(answer_key(answer), answer.strip())
    for category in Category.objects.all():
        bank = banks.get(category.pk, {})
        answers = [bank[key] for key in sorted(bank)]
        version = digest([VERSION, category.pk, answers])
        AnswerBank.objects.get_or_create(pk=version, defaults=dict(category=category.pk, answers=answers))
        Category.objects.filter(pk=category.pk).update(typed_bank_id=version)
