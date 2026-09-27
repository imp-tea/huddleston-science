import uuid

from django.contrib import messages
from django.core.exceptions import ValidationError
from django.core.paginator import Paginator
from django.db.models import Count, Max, Prefetch, Q
from django.shortcuts import get_object_or_404, redirect, render
from django.urls import reverse
from django.views.decorators.http import require_GET, require_http_methods

from accounts.models import User
from accounts.views import administrator_required
from .models import Question, SavedQuiz, StudyAnswer, Topic
from .discovery import calendar_progress, coverage_rows
from .teacher_progress import practice_history, study_history
from .question_authoring import StaleQuestion, change_question_status, create_question, edit_question
from .teacher_forms import QuestionActionForm, QuestionCreateForm, QuestionEditForm


def selected_student(pk):
    return get_object_or_404(User, pk=pk, is_admin=False)


@administrator_required
@require_GET
def home(request):
    return render(request, 'scholars/teacher/home.html', {'teacher_tools': True})


@administrator_required
@require_GET
def students(request):
    query = request.GET.get('q', '').strip()[:100]
    roster = User.objects.filter(is_admin=False)
    if query:
        roster = roster.filter(username__icontains=query)
    roster = roster.annotate(last_study_at=Max('study_sessions__started_at')).order_by('username', 'pk')
    return render(request, 'scholars/teacher/students.html', {'teacher_tools': True, 'query': query,
        'students': Paginator(roster, 30).get_page(request.GET.get('page'))})


@administrator_required
@require_GET
def student_progress(request, pk):
    student = selected_student(pk)
    return render(request, 'scholars/study/progress.html', {'teacher_tools': True, 'student': student,
        'coverage': coverage_rows(student), 'weekly': calendar_progress(student),
        'study_sessions': study_history(student)[:5], 'practice_sessions': practice_history(student)[:5]})


@administrator_required
@require_GET
def student_history(request, pk):
    student = selected_student(pk)
    return render(request, 'scholars/teacher/history.html', {'teacher_tools': True, 'student': student,
        'study_sessions': Paginator(study_history(student), 20).get_page(request.GET.get('study_page')),
        'practice_sessions': Paginator(practice_history(student), 25).get_page(request.GET.get('practice_page'))})


@administrator_required
@require_GET
def study_detail(request, pk, session_id):
    student = selected_student(pk)
    session = get_object_or_404(student.study_sessions, pk=session_id)
    attempts = session.attempts.order_by('-number').annotate(
        total_answers=Count('answers'), answered_count=Count('answers', filter=Q(answers__answered_at__isnull=False)))
    page = Paginator(attempts, 5).get_page(request.GET.get('page'))
    # Only prefetch this page, and avoid loading entire tournament-source contexts.
    page.object_list = list(page.object_list.prefetch_related(Prefetch('answers', queryset=StudyAnswer.objects
        .select_related('question__revision').defer('question__revision__context').order_by('position'))))
    return render(request, 'scholars/teacher/study_detail.html', {'teacher_tools': True, 'student': student,
        'session': session, 'attempts': page, 'topics': session.topics.order_by('position')})


@administrator_required
@require_GET
def practice_detail(request, pk, session_id):
    student = selected_student(pk)
    session = get_object_or_404(practice_history(student), pk=session_id)
    return render(request, 'scholars/teacher/practice_detail.html', {'teacher_tools': True, 'student': student,
        'session': session, 'items': session.items.select_related('revision').defer('revision__context').order_by('position')})


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
    return_quiz = None
    try:
        quiz_id = uuid.UUID(request.POST.get('return_quiz', '') if request.method == 'POST' else request.GET.get('quiz', ''))
    except (ValueError, TypeError):
        pass
    else:
        return_quiz = SavedQuiz.objects.filter(pk=quiz_id, owner=request.user, items__question=question).first()
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
            if return_quiz:
                return redirect('scholars:quiz_detail', pk=return_quiz.pk)
            return redirect(topic_destination(question.topic_id))
    return render(request, 'scholars/teacher/question_form.html',
        {'form': form, 'topic': question.topic, 'question': question, 'heading': 'Edit Question', 'return_quiz': return_quiz}, status=status)


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
