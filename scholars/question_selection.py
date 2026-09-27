"""Shared identity rules for Study and teacher-generated quizzes."""
from collections import defaultdict

from .typed_answers import search_key


def group_questions(questions, payload_for):
    """Connected components of equal normalized prompts OR answers."""
    questions = list(questions)
    parents = list(range(len(questions)))

    def root(i):
        while parents[i] != i:
            parents[i] = parents[parents[i]]
            i = parents[i]
        return i

    keys = {}
    for i, question in enumerate(questions):
        payload = payload_for(question)
        for kind, text in [('prompt', payload['question']), ('answer', payload['correct_answer'])]:
            key = (kind, search_key(text))
            if key in keys:
                parents[root(i)] = root(keys[key])
            else:
                keys[key] = i
    groups = defaultdict(list)
    for i, question in enumerate(questions):
        groups[root(i)].append(question)
    return list(groups.values())
