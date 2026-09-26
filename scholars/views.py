import uuid
from django.conf import settings
from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.core.exceptions import ValidationError
from django.core.paginator import Paginator
from django.db.models import Sum
from django.http import HttpResponseBadRequest
from django.shortcuts import get_object_or_404, redirect, render
from django.views.decorators.http import require_POST
from accounts.models import User
from accounts.views import administrator_required
from .catalog import describe_scope, topic_pool
from .forms import AnswerForm, RecallForm, TypedAnswerForm, GoalForm, SCOPE_FIELDS, StartForm
from .models import Category, PracticeSession, RewardEvent, Source, StudyPreferences, StudyState, Subcategory, Topic, TopicRedirect
from .progress import coverage, missed_topics, participation, personal_bests, session_totals
from .reviews import review_summary
from .services import abandon_session, answer_question, mark_studied, record_visit, start_session


def start_form(**scope):
    return StartForm(initial={"request_key": uuid.uuid4(), **scope})


@login_required
def dashboard(request):
    sessions = session_totals(request.user.practice_sessions).order_by("-started_at")
    return render(request, "scholars/dashboard.html", {"start_form": start_form(selection="personalized"),
        "reviews": review_summary(request.user),
        "sessions": sessions[:5], "resume": sessions.filter(completed_at__isnull=True, abandoned_at__isnull=True).first(),
        "participation": participation(request.user), "missed_topics": missed_topics(request.user),
        "has_content": Topic.objects.filter(active=True).exists()})


@login_required
def library(request):
    category = request.GET.get("category", "")
    subcategory = request.GET.get("subcategory", "")
    query = request.GET.get("q", "")[:100].strip()
    status = request.GET.get("status", "")
    if status not in {"studied", "unstudied", "practiced"}:
        status = ""
    if category:
        get_object_or_404(Category, pk=category, active=True)
    subs = Subcategory.objects.filter(active=True).order_by("id")
    if category:
        subs = subs.filter(category_id=category)
    if subcategory and not subs.filter(pk=subcategory).exists():
        subcategory = ""
    scope = {k: v for k, v in dict(category=category, subcategory=subcategory, q=query, status=status).items() if v}
    topics = topic_pool(request.user, scope).order_by("title", "pk")
    query_params = request.GET.copy()
    query_params.pop("page", None)
    query_params["subcategory"] = subcategory
    return render(request, "scholars/library.html", {"topics": Paginator(topics, 30).get_page(request.GET.get("page")),
        "categories": Category.objects.filter(active=True).order_by("id"), "subcategories": subs,
        "category": category, "subcategory": subcategory, "query": query, "query_params": query_params.urlencode(),
        "status": status, "scope_label": describe_scope(scope), "start_form": start_form(**scope)})


def citations(study_content):
    source = study_content.get("source", {})
    return source.get("references", [source]) if source else []


@login_required
def topic(request, pk):
    old = TopicRedirect.objects.filter(pk=pk, active=True).first()
    if old:
        return redirect("scholars:topic", pk=old.topic_id, permanent=True)
    entry = get_object_or_404(Topic, pk=pk)
    state = record_visit(request.user, entry) if request.method == "GET" else StudyState.objects.filter(user=request.user, topic=entry).first()
    return render(request, "scholars/topic.html", {"topic": entry, "study": entry.study_content,
        "study_state": state, "reviews": review_summary(request.user, topic=entry.pk),
        "citations": citations(entry.study_content), "sources": Source.objects.filter(pk__in=entry.payload["source_ids"]),
        "start_form": start_form(topic=entry.pk)})


@login_required
@require_POST
def start(request):
    form = StartForm(request.POST)
    if not form.is_valid():
        return HttpResponseBadRequest("Invalid practice request. Return to Scholars Bowl and try again.")
    scope = {k: form.cleaned_data[k] for k in SCOPE_FIELDS if form.cleaned_data[k]}
    try:
        session = start_session(request.user, form.cleaned_data["request_key"], scope,
                                mode=form.cleaned_data["mode"] or "typed", selection=form.cleaned_data["selection"] or "random")
    except ValidationError as exc:
        messages.error(request, "; ".join(exc.messages))
        return redirect("scholars:dashboard")
    return redirect("scholars:session", pk=session.pk)


def visible_session(request, pk, allow_admin=False):
    sessions = PracticeSession.objects.all()
    if not (allow_admin and request.user.is_admin):
        sessions = sessions.filter(user=request.user)
    return get_object_or_404(sessions, pk=pk)


def question_form(session, item, data=None):
    if session.mode == "typed":
        return TypedAnswerForm(data)
    return RecallForm(data) if session.mode == "recall" else AnswerForm(item.choices, data)


def render_question(request, session, item, form, *, prompt=False, status=200):
    context = {"session": session, "item": item, "form": form, "prompt": prompt}
    if session.mode != "typed":
        return render(request, "scholars/legacy_format.html", context, status=status)
    return render(request, "scholars/question.html", context, status=status)


@login_required
def session_view(request, pk):
    session = visible_session(request, pk)
    if session.completed_at or session.abandoned_at:
        return redirect("scholars:results", pk=pk)
    item = session.items.filter(answered_at__isnull=True).select_related("revision", "answer_bank").first()
    form = question_form(session, item)
    return render_question(request, session, item, form)


@login_required
@require_POST
def answer(request, pk, position):
    session = visible_session(request, pk)
    item = get_object_or_404(session.items.select_related("revision", "answer_bank"), position=position)
    if item.answered_at:
        return redirect("scholars:feedback", pk=pk, position=position)
    form = question_form(session, item, request.POST)
    if form.is_valid():
        try:
            if session.mode == "typed":
                saved = answer_question(request.user, pk, position, typed_answer=form.cleaned_data["typed_answer"],
                                        skip=form.cleaned_data["action"] == "skip")
                if saved.answered_at is None:
                    return render_question(request, session, item, form, prompt=True)
            elif session.mode == "recall":
                answer_question(request.user, pk, position, self_assessment=form.cleaned_data["self_assessment"])
            else:
                answer_question(request.user, pk, position, form.cleaned_data["selected"])
        except ValidationError as exc:
            form.add_error(None, exc)
        else:
            return redirect("scholars:feedback", pk=pk, position=position)
    return render_question(request, session, item, form, status=400)


@login_required
def feedback(request, pk, position):
    session = visible_session(request, pk)
    item = get_object_or_404(session.items.select_related("revision"), position=position, answered_at__isnull=False)
    return render(request, "scholars/feedback.html", {"session": session, "item": item})


@login_required
def history(request):
    return render(request, "scholars/history.html", {"sessions": Paginator(
        session_totals(request.user.practice_sessions).order_by("-started_at"), 25).get_page(request.GET.get("page")),
        "study_sessions": Paginator(request.user.study_sessions.order_by("-started_at", "-pk"), 20).get_page(request.GET.get("study_page"))})


@login_required
def results(request, pk):
    session = visible_session(request, pk, allow_admin=True)
    best = None
    if session.mode in {"typed", "recognition"} and session.completed_at and session.comparison_key:
        best = session_totals(PracticeSession.objects.filter(user=session.user, mode=session.mode, comparison_key=session.comparison_key,
            completed_at__isnull=False)).filter(total_count=session.total).order_by("-score_count", "completed_at").first()
    return render(request, "scholars/results.html", {"session": session,
        "best": best, "corrected_count": session.items.filter(corrected_previous_miss=True).count(),
        "earned_xp": RewardEvent.objects.filter(answer__session=session).aggregate(total=Sum("points"))["total"] or 0,
        "items": session.items.filter(answered_at__isnull=False).select_related("revision"),
        "start_form": start_form(**session.scope, mode=session.mode, selection=session.selection)})


@login_required
def evidence(request, pk, position):
    session = visible_session(request, pk, allow_admin=True)
    item = get_object_or_404(session.items.select_related("revision"), position=position, answered_at__isnull=False)
    context = item.revision.context
    return render(request, "scholars/evidence.html", {"item": item, "session": session, "context": context,
        "citations": citations(context["study_content"])})


@login_required
def attribution(request):
    text = (settings.BASE_DIR / "ATTRIBUTION.md").read_text()
    return render(request, "scholars/attribution.html", {"paragraphs": text.split("\n\n")[1:]})


@login_required
@require_POST
def studied(request, pk):
    entry = get_object_or_404(Topic, pk=pk, active=True)
    if request.POST.get("studied") not in {"yes", "no"}:
        return HttpResponseBadRequest("Invalid study marker.")
    mark_studied(request.user, entry, request.POST["studied"] == "yes")
    return redirect("scholars:topic", pk=pk)


def progress_context(user, params):
    category = params.get("category", "")
    if category:
        get_object_or_404(Category, pk=category, active=True)
    query_params = params.copy()
    query_params.pop("page", None)
    return {"progress_owner": user, "category": category, "query_params": query_params.urlencode() if hasattr(query_params, "urlencode") else "",
            "categories": Category.objects.filter(active=True).order_by("id"),
            "reviews": review_summary(user, category),
            "coverage": coverage(user, category), "participation": participation(user),
            "bests": Paginator(personal_bests(user), 20).get_page(params.get("page")),
            "studies": StudyState.objects.filter(user=user).select_related("topic").order_by("-last_opened_at")[:10]}


@login_required
def progress(request):
    context = progress_context(request.user, request.GET)
    context["goal_form"] = GoalForm(initial={"weekly_goal": context["participation"]["weekly_goal"]})
    return render(request, "scholars/progress.html", context)


@administrator_required
def student_progress(request, pk):
    student = get_object_or_404(User, pk=pk, is_admin=False)
    return render(request, "scholars/progress.html", progress_context(student, request.GET))


@login_required
@require_POST
def goal(request):
    form = GoalForm(request.POST)
    if form.is_valid():
        StudyPreferences.objects.update_or_create(user=request.user, defaults=form.cleaned_data)
        return redirect("scholars:legacy_progress")
    context = progress_context(request.user, {})
    context["goal_form"] = form
    return render(request, "scholars/progress.html", context, status=400)


@login_required
@require_POST
def reveal(request, pk, position):
    session = visible_session(request, pk)
    get_object_or_404(session.items, position=position)
    return HttpResponseBadRequest("Answer reveals are no longer available. Use Study for typed quizzes.")


@login_required
@require_POST
def abandon(request, pk):
    visible_session(request, pk)
    abandon_session(request.user, pk)
    return redirect("scholars:results", pk=pk)
