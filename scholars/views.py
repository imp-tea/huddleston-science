import uuid
from django.conf import settings
from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.core.exceptions import ValidationError
from django.core.paginator import Paginator
from django.http import HttpResponseBadRequest
from django.shortcuts import get_object_or_404, redirect, render
from django.views.decorators.http import require_POST
from .forms import AnswerForm, StartForm
from .models import Category, PracticeSession, Source, Subcategory, Topic, TopicRedirect
from .services import answer_question, start_session


def start_form(**scope):
    return StartForm(initial={"request_key": uuid.uuid4(), **scope})


@login_required
def dashboard(request):
    return render(request, "scholars/dashboard.html", {"start_form": start_form(),
        "sessions": request.user.practice_sessions.order_by("-started_at")[:5],
        "has_content": Topic.objects.filter(active=True).exists()})


@login_required
def library(request):
    topics = Topic.objects.filter(active=True).order_by("title", "pk")
    category = request.GET.get("category", "")
    subcategory = request.GET.get("subcategory", "")
    query = request.GET.get("q", "")[:100]
    if category:
        get_object_or_404(Category, pk=category, active=True)
        topics = topics.filter(category_id=category)
    subs = Subcategory.objects.filter(active=True).order_by("id")
    if category:
        subs = subs.filter(category_id=category)
    if subcategory:
        if subs.filter(pk=subcategory).exists():
            topics = topics.filter(subcategories=subcategory)
        else:
            subcategory = ""
    if query:
        topics = topics.filter(title__icontains=query)
    query_params = request.GET.copy()
    query_params.pop("page", None)
    query_params["subcategory"] = subcategory
    return render(request, "scholars/library.html", {"topics": Paginator(topics, 30).get_page(request.GET.get("page")),
        "categories": Category.objects.filter(active=True).order_by("id"), "subcategories": subs,
        "category": category, "subcategory": subcategory, "query": query, "query_params": query_params.urlencode(),
        "start_form": start_form(category=category, subcategory=subcategory)})


def citations(study_content):
    source = study_content.get("source", {})
    return source.get("references", [source]) if source else []


@login_required
def topic(request, pk):
    old = TopicRedirect.objects.filter(pk=pk, active=True).first()
    if old:
        return redirect("scholars:topic", pk=old.topic_id, permanent=True)
    entry = get_object_or_404(Topic, pk=pk)
    return render(request, "scholars/topic.html", {"topic": entry, "study": entry.study_content,
        "citations": citations(entry.study_content), "sources": Source.objects.filter(pk__in=entry.payload["source_ids"]),
        "start_form": start_form(topic=entry.pk)})


@login_required
@require_POST
def start(request):
    form = StartForm(request.POST)
    if not form.is_valid():
        return HttpResponseBadRequest("Invalid practice request. Return to Scholars Bowl and try again.")
    scope = {k: form.cleaned_data[k] for k in ("category", "subcategory", "topic") if form.cleaned_data[k]}
    try:
        session = start_session(request.user, form.cleaned_data["request_key"], scope)
    except ValidationError as exc:
        messages.error(request, "; ".join(exc.messages))
        return redirect("scholars:dashboard")
    return redirect("scholars:session", pk=session.pk)


def visible_session(request, pk, allow_admin=False):
    sessions = PracticeSession.objects.all()
    if not (allow_admin and request.user.is_admin):
        sessions = sessions.filter(user=request.user)
    return get_object_or_404(sessions, pk=pk)


@login_required
def session_view(request, pk):
    session = visible_session(request, pk)
    if session.completed_at:
        return redirect("scholars:results", pk=pk)
    item = session.items.filter(answered_at__isnull=True).select_related("revision").first()
    form = AnswerForm(item.choices)
    return render(request, "scholars/question.html", {"session": session, "item": item, "form": form})


@login_required
@require_POST
def answer(request, pk, position):
    session = visible_session(request, pk)
    item = get_object_or_404(session.items.select_related("revision"), position=position)
    form = AnswerForm(item.choices, request.POST)
    if form.is_valid():
        try:
            answer_question(request.user, pk, position, form.cleaned_data["selected"])
        except ValidationError as exc:
            form.add_error(None, exc)
        else:
            return redirect("scholars:feedback", pk=pk, position=position)
    return render(request, "scholars/question.html", {"session": session, "item": item, "form": form}, status=400)


@login_required
def feedback(request, pk, position):
    session = visible_session(request, pk)
    item = get_object_or_404(session.items.select_related("revision"), position=position, answered_at__isnull=False)
    return render(request, "scholars/feedback.html", {"session": session, "item": item})


@login_required
def history(request):
    return render(request, "scholars/history.html", {"sessions": Paginator(
        request.user.practice_sessions.order_by("-started_at"), 25).get_page(request.GET.get("page"))})


@login_required
def results(request, pk):
    session = visible_session(request, pk, allow_admin=True)
    return render(request, "scholars/results.html", {"session": session,
        "items": session.items.filter(answered_at__isnull=False).select_related("revision"),
        "start_form": start_form(**session.scope)})


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
