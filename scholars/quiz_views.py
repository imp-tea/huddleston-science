import uuid

from django.contrib import messages
from django.core import signing
from django.core.exceptions import ValidationError
from django.core.paginator import Paginator
from django.db.models import Count
from django.shortcuts import get_object_or_404, redirect, render
from django.views.decorators.http import require_http_methods, require_POST

from accounts.views import administrator_required
from .models import SavedQuiz
from .quiz_forms import QuizActionForm, QuizCreateForm, RandomQuizForm
from .quiz_generation import generate
from .quiz_lists import (StaleQuiz, add_question, available_questions, create_quiz,
                         quiz_items, update_quiz)

PREVIEW_SALT = 'teacher-quiz-preview-v1'


def context(**values):
    return {'teacher_tools': True, **values}


@administrator_required
@require_http_methods(['GET', 'POST'])
def index(request):
    form = QuizCreateForm(request.POST if request.method == 'POST' else None,
                          initial={'request_key': uuid.uuid4()})
    if request.method == 'POST' and form.is_valid():
        try:
            quiz = create_quiz(request.user, **form.cleaned_data)
        except ValidationError as exc:
            form.add_error(None, exc)
        else:
            messages.success(request, 'Quiz created. Add questions from Explore or use random generation.')
            return redirect('scholars:quiz_detail', pk=quiz.pk)
    archived = request.GET.get('archived') == '1'
    quizzes = SavedQuiz.objects.filter(owner=request.user, archived=archived).annotate(question_count=Count('items')).order_by('-updated_at', '-pk')
    return render(request, 'scholars/teacher/quizzes.html', context(form=form, archived=archived,
        quizzes=Paginator(quizzes, 20).get_page(request.GET.get('page'))), status=400 if request.method == 'POST' else 200)


@administrator_required
@require_http_methods(['GET', 'POST'])
def detail(request, pk):
    quiz = get_object_or_404(SavedQuiz, pk=pk, owner=request.user)
    error = None
    status = 200
    if request.method == 'POST':
        form = QuizActionForm(request.POST)
        if form.is_valid():
            try:
                result = update_quiz(request.user, pk, **form.cleaned_data)
            except ValidationError as exc:
                error = exc.messages
                status = 409 if isinstance(exc, StaleQuiz) else 400
            else:
                messages.success(request, 'Quiz updated.' if result.pk == pk else 'Quiz duplicated.')
                return redirect('scholars:quiz_detail', pk=result.pk)
        else:
            error, status = [form.errors.as_text()], 400
        quiz.refresh_from_db()
    items = quiz_items(quiz)
    return render(request, 'scholars/teacher/quiz_detail.html', context(quiz=quiz, items=items,
        error=error, duplicate_key=uuid.uuid4(), needs_review=any(i.changed or not i.available for i in items)), status=status)


@administrator_required
@require_http_methods(['GET', 'POST'])
def add(request, question_id):
    question = get_object_or_404(available_questions().select_related('topic', 'current_revision'), pk=question_id)
    error, status = None, 200
    if request.method == 'POST':
        try:
            quiz_id = uuid.UUID(request.POST.get('quiz_id', ''))
            version = int(request.POST.get('version', ''))
            revision_id = int(request.POST.get('revision_id', ''))
        except (ValueError, TypeError):
            error, status = ['Invalid selection. Reload this page and choose a quiz.'], 400
        else:
            try:
                quiz, added = add_question(request.user, quiz_id, version, question_id, revision_id)
            except ValidationError as exc:
                error, status = exc.messages, 409 if isinstance(exc, StaleQuiz) else 400
            else:
                messages.success(request, f'Question added to “{quiz.name}”.' if added else f'This question is already in “{quiz.name}”.')
                return redirect('scholars:quiz_detail', pk=quiz.pk)
    quizzes = SavedQuiz.objects.filter(owner=request.user, archived=False).annotate(question_count=Count('items')).order_by('-updated_at', '-pk')
    return render(request, 'scholars/teacher/quiz_add.html', context(question=question, error=error,
        quizzes=Paginator(quizzes, 20).get_page(request.GET.get('page'))), status=status)


@administrator_required
@require_http_methods(['GET', 'POST'])
def random_quiz(request):
    form = RandomQuizForm(request.POST if request.method == 'POST' else None)
    preview = None
    token = None
    if request.method == 'POST' and form.is_valid():
        try:
            preview = generate(form.cleaned_data)
        except ValidationError as exc:
            form.add_error(None, exc)
        else:
            token = signing.dumps({'owner': str(request.user.pk), 'key': str(uuid.uuid4()),
                'name': form.cleaned_data['name'], 'settings': preview['settings'],
                'selected': [[q.pk, q.current_revision_id] for q in preview['questions']]}, salt=PREVIEW_SALT, compress=True)
    return render(request, 'scholars/teacher/quiz_random.html', context(form=form, preview=preview, token=token),
                  status=400 if request.method == 'POST' and preview is None else 200)


@administrator_required
@require_POST
def save_preview(request):
    try:
        token = request.POST.get('preview', '')
        if len(token) > 30000:
            raise signing.BadSignature()
        data = signing.loads(token, salt=PREVIEW_SALT, max_age=3600)
        if data['owner'] != str(request.user.pk):
            raise signing.BadSignature()
        quiz = create_quiz(request.user, data['name'], data['key'], selected=data['selected'], settings=data['settings'])
    except signing.BadSignature:
        error = 'This preview expired or could not be verified. Generate a new preview.'
    except ValidationError as exc:
        error = ' '.join(exc.messages)
    else:
        messages.success(request, 'Preview saved as an editable quiz.')
        return redirect('scholars:quiz_detail', pk=quiz.pk)
    return render(request, 'scholars/teacher/quiz_preview_error.html', context(error=error), status=409)
