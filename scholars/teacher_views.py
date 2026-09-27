import uuid

from django.contrib import messages
from django.core.exceptions import ValidationError
from django.shortcuts import get_object_or_404, redirect, render
from django.urls import reverse
from django.views.decorators.http import require_http_methods

from accounts.views import administrator_required
from .models import Question, Topic
from .question_authoring import StaleQuestion, change_question_status, create_question, edit_question
from .teacher_forms import QuestionActionForm, QuestionCreateForm, QuestionEditForm


def topic_destination(topic_id):
    return reverse('scholars:topic', args=[topic_id]) + '?questions=1#teacher-questions'


@administrator_required
@require_http_methods(['GET', 'POST'])
def question_create(request, topic_id):
    topic = get_object_or_404(Topic, pk=topic_id, active=True, category__active=True)
    form = QuestionCreateForm(request.POST if request.method == 'POST' else None,
                              initial={'request_key': uuid.uuid4()})
    if request.method == 'POST' and form.is_valid():
        try:
            create_question(request.user, topic.pk, form.cleaned_data['request_key'], request.POST)
        except ValidationError as exc:
            form.add_error(None, exc)
        else:
            messages.success(request, 'Question created. It is available to future Study sessions.')
            return redirect(topic_destination(topic.pk))
    return render(request, 'scholars/teacher/question_form.html',
        {'form': form, 'topic': topic, 'heading': 'Add New Question'},
        status=400 if request.method == 'POST' else 200)


@administrator_required
@require_http_methods(['GET', 'POST'])
def question_edit(request, question_id):
    question = get_object_or_404(Question.objects.select_related('topic', 'current_revision', 'imported_revision'),
                                pk=question_id, active=True, topic__active=True, topic__category__active=True)
    initial = dict(question.current_revision.payload)
    initial.update(version=question.edit_version, distractors='\n'.join(initial.get('distractors', [])))
    form = QuestionEditForm(request.POST if request.method == 'POST' else None,
        initial=initial, question_format=question.format)
    status = 400 if request.method == 'POST' else 200
    if request.method == 'POST' and form.is_valid():
        try:
            edit_question(request.user, question.pk, form.cleaned_data['version'], request.POST)
        except ValidationError as exc:
            form.add_error(None, exc)
            if isinstance(exc, StaleQuestion):
                status = 409
        else:
            messages.success(request, 'Question saved. Existing sessions keep their original version.')
            return redirect(topic_destination(question.topic_id))
    return render(request, 'scholars/teacher/question_form.html',
        {'form': form, 'topic': question.topic, 'question': question, 'heading': 'Edit Question'}, status=status)


@administrator_required
@require_http_methods(['GET', 'POST'])
def question_action(request, question_id, action):
    question = get_object_or_404(Question.objects.select_related('topic', 'current_revision', 'imported_revision'),
                                pk=question_id, topic__active=True, topic__category__active=True)
    available = ({'archive': 'Archive Question'} if question.active else {'reactivate': 'Restore Question'}) if question.origin == 'teacher' else (
        {'restore_imported': 'Restore Imported Version'} if question.active and question.override_revision_id else {})
    if action not in available:
        from django.http import Http404
        raise Http404
    form = QuestionActionForm(request.POST if request.method == 'POST' else None,
                              initial={'version': question.edit_version, 'action': action})
    status = 400 if request.method == 'POST' else 200
    if request.method == 'POST' and form.is_valid():
        if form.cleaned_data['action'] != action:
            form.add_error(None, 'The requested action changed. Reload and try again.')
        else:
            try:
                change_question_status(request.user, question.pk, form.cleaned_data['version'], action)
            except ValidationError as exc:
                form.add_error(None, exc)
                if isinstance(exc, StaleQuestion):
                    status = 409
            else:
                messages.success(request, 'Question updated. Saved sessions and results are preserved.')
                return redirect(topic_destination(question.topic_id))
    return render(request, 'scholars/teacher/question_action.html', {'form': form, 'question': question,
        'topic': question.topic, 'heading': available[action], 'action': action}, status=status)
