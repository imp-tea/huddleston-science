"""HTML views expose reading snapshots and question text, never grading payloads."""
import uuid
from math import ceil

from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.core.exceptions import ValidationError
from django.db import transaction
from django.http import HttpResponseBadRequest
from django.shortcuts import get_object_or_404, redirect, render
from django.views.decorators.http import require_GET, require_POST, require_http_methods

from .typed_answers import for_item
from .forms import InterestsForm, ReadingMoveForm, StudyAnswerForm, StudyStartForm
from .models import Category, StudyAnswer, StudyPreferences, StudySession, Topic
from .study import (abandon_study, active_session, move_reading, picker, preferences_ready,
                    reading_topics, question_groups, retry_pool, save_interests, start_study, submit_answer)


@login_required
@require_GET
def home(request):
    if not preferences_ready(request.user):
        return redirect("scholars:interests")
    return render(request, "scholars/study/home.html")


def interests_form(user, data=None):
    preferences = StudyPreferences.objects.filter(user=user).first()
    selected = list(preferences.categories.values_list("pk", flat=True)) if preferences else []
    return InterestsForm(data, initial={"categories": selected})


@login_required
@require_http_methods(["GET", "POST"])
def interests(request):
    form = interests_form(request.user, request.POST if request.method == "POST" else None)
    if request.method == "POST" and form.is_valid():
        try:
            save_interests(request.user, form.cleaned_data["categories"])
        except ValidationError as exc:
            form.add_error(None, exc)
        else:
            messages.success(request, "Interests saved. They apply to your next study selection.")
            return redirect("account" if request.POST.get("return_to") == "account" else "scholars:dashboard")
    return render(request, "scholars/study/interests.html", {
        "interests_form": form, "has_categories": Category.objects.filter(active=True).exists(),
        "onboarding": not preferences_ready(request.user), "return_to": request.POST.get("return_to", ""),
    }, status=400 if request.method == "POST" else 200)


@login_required
@require_GET
def study(request):
    current = active_session(request.user)
    if current:
        return render(request, "scholars/study/resume.html", {"session": current})
    if not preferences_ready(request.user):
        return redirect("scholars:interests")
    previous = request.session.get("study_choices", [])
    choices = picker(request.user, previous)
    request.session["study_choices"] = [s.pk for s in choices]
    return render(request, "scholars/study/picker.html", {"choices": choices, "request_key": uuid.uuid4(),
        "interest_count": Category.objects.filter(active=True, studypreferences__user=request.user).count(),
        "has_study_topics": Topic.objects.filter(active=True, category__active=True,
            category__studypreferences__user=request.user, subcategories__active=True).exists()})


@login_required
@require_POST
def start(request):
    form = StudyStartForm(request.POST)
    if not form.is_valid():
        return HttpResponseBadRequest("Invalid study request. Return to Study and choose a subject.")
    try:
        session = start_study(request.user, form.cleaned_data["request_key"], form.cleaned_data["subcategory"])
    except ValidationError as exc:
        messages.error(request, "; ".join(exc.messages))
        return redirect("scholars:study")
    return redirect("scholars:study_session", pk=session.pk)


def owned_session(request, pk, *, lock=False):
    sessions = StudySession.objects.select_for_update() if lock else StudySession.objects.all()
    return get_object_or_404(sessions, pk=pk, user=request.user)


def session_context(session):
    context = {"session": session}
    topics = list(session.topics.all())
    context["topic_count"] = len(topics)
    context["quiz_size"] = 2 * len(topics)
    attempt = session.attempts.order_by("-number").first()
    if session.phase == StudySession.Phase.READING:
        context["quiz_size"] = min(context["quiz_size"], len(question_groups(session)))
    elif session.phase == StudySession.Phase.QUIZ:
        context["quiz_size"] = attempt.answers.count()
    elif session.phase == StudySession.Phase.REVIEW:
        misses, unused = retry_pool(session)
        context["quiz_size"] = min(context["quiz_size"], len(misses) + len(unused))
    context["passing_score"] = ceil(context["quiz_size"] * .9)
    if attempt and attempt.completed_at:
        context["result"] = {"number": attempt.number, "score": attempt.score, "total": attempt.answers.count()}
        context["resolved_earlier"] = (session.phase == StudySession.Phase.PASSED and
            attempt.score < ceil(context["result"]["total"] * .9))
    if session.phase == StudySession.Phase.PASSED and attempt:
        missed_ids = set(attempt.answers.filter(is_correct=False).values_list("question__session_topic__topic_id", flat=True))
        context["optional_review"] = [{"id": topic.topic_id, "title": topic.content["title"]}
                                      for topic in topics if topic.topic_id in missed_ids]
    if session.phase in {StudySession.Phase.READING, StudySession.Phase.REVIEW}:
        reading = reading_topics(session)
        context.update(card=reading[session.reading_position].content, position=session.reading_position + 1,
                       reading_count=len(reading), last=session.reading_position == len(reading) - 1,
                       reading_percent=(session.reading_position + 1) * 100 // len(reading))
        if session.phase == StudySession.Phase.REVIEW:
            context["missed_topics"] = [t.content["title"] for t in reading]
    elif session.phase == StudySession.Phase.QUIZ:
        answer = attempt.answers.filter(answered_at__isnull=True).select_related("question__revision", "question__answer_bank").first()
        # Restore the pinned category suggestion view, without a marked correct answer.
        suggestions = for_item(answer.question)
        context.update(question_text=answer.question.revision.payload["question"], answer_id=answer.pk,
                       question_position=answer.position, attempt_number=attempt.number,
                       answered_percent=(answer.position - 1) * 100 // context["quiz_size"], form=StudyAnswerForm(),
                       suggestion_data={"index": [{key: row[key] for key in ("text", "key", "parts")}
                                                   for row in suggestions["index"]]})
    return context


@login_required
@require_GET
@transaction.atomic
def session_view(request, pk):
    # Keep the phase and its attempt/reading position consistent during rendering.
    # This read takes only the session lock and never acquires an account lock.
    session = owned_session(request, pk, lock=True)
    return render(request, "scholars/study/session.html", session_context(session))


@login_required
@require_GET
def passed_review(request, pk, topic_id):
    session = get_object_or_404(StudySession, pk=pk, user=request.user, phase=StudySession.Phase.PASSED)
    attempt = session.attempts.order_by("-number").first()
    missed = attempt.answers.filter(is_correct=False).values("question__session_topic_id")
    topic = get_object_or_404(session.topics, topic_id=topic_id, pk__in=missed)
    return render(request, "scholars/study/passed_review.html", {"session": session, "card": topic.content})


@login_required
@require_POST
def read(request, pk):
    owned_session(request, pk)
    form = ReadingMoveForm(request.POST)
    if not form.is_valid():
        return HttpResponseBadRequest("Invalid reading request.")
    try:
        move_reading(request.user, pk, form.cleaned_data["version"], form.cleaned_data["direction"])
    except ValidationError as exc:
        messages.error(request, "; ".join(exc.messages))
    return redirect("scholars:study_session", pk=pk)


@login_required
@require_POST
@transaction.atomic
def answer(request, pk, answer_id):
    session = owned_session(request, pk)
    get_object_or_404(StudyAnswer, pk=answer_id, attempt__session=session)
    form = StudyAnswerForm(request.POST)
    if form.is_valid():
        try:
            session, prompted = submit_answer(request.user, pk, answer_id, form.cleaned_data["typed_answer"],
                                               skip=form.cleaned_data["action"] == "skip")
        except ValidationError as exc:
            messages.error(request, "; ".join(exc.messages))
            return redirect("scholars:study_session", pk=pk)
        if not prompted:
            return redirect("scholars:study_feedback", pk=pk, answer_id=answer_id)
    else:
        prompted = False
    session = owned_session(request, pk, lock=True)
    if session.phase != StudySession.Phase.QUIZ:
        return redirect("scholars:study_session", pk=pk)
    context = session_context(session)
    if context["answer_id"] != answer_id:
        return redirect("scholars:study_session", pk=pk)
    context.update(form=form, prompted=prompted)
    return render(request, "scholars/study/session.html", context, status=200 if prompted else 400)


@login_required
@require_GET
def feedback(request, pk, answer_id):
    # Use the saved result, including on duplicate POSTs. Never send the question,
    # canonical answer, submitted text, bank, or explanation to this page.
    answer = get_object_or_404(StudyAnswer.objects.only("is_correct", "skipped", "position"),
                              pk=answer_id, attempt__session_id=pk,
                              attempt__session__user=request.user, answered_at__isnull=False)
    return render(request, "scholars/study/feedback.html", {
        "session_id": pk, "correct": answer.is_correct, "skipped": answer.skipped,
        "position": answer.position,
    })


@login_required
@require_POST
def restart(request, pk):
    owned_session(request, pk)
    abandon_study(request.user, pk)
    return redirect("scholars:study")
