"""Mode-specific current banks. Existing sessions keep their pinned revisions."""
from .models import Question


def question_format(mode):
    if mode != 'recognition' and Question.objects.filter(format='typed', active=True, topic__active=True).exists():
        return 'typed'
    return 'multiple_choice'


def current_questions(mode):
    return Question.objects.filter(format=question_format(mode), active=True,
                                   topic__active=True, current_revision__isnull=False)
