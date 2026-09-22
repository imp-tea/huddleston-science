"""The library and practice use the same scope filters."""
from django.db.models import Exists, OuterRef, Q
from .models import SessionQuestion, StudyState, Subcategory, Topic


def topic_pool(user, scope):
    topics = Topic.objects.filter(active=True)
    if scope.get("topic"):
        topics = topics.filter(pk=scope["topic"])
    if scope.get("category"):
        topics = topics.filter(category_id=scope["category"])
    if scope.get("subcategory"):
        topics = topics.filter(subcategories=scope["subcategory"])
    if scope.get("q"):
        topics = topics.filter(Q(title__icontains=scope["q"]) | Q(payload__aliases__icontains=scope["q"]))
    topics = topics.annotate(
        studied=Exists(StudyState.objects.filter(user=user, topic_id=OuterRef("pk"), studied_at__isnull=False)),
        practiced=Exists(SessionQuestion.objects.filter(session__user=user, revision__question__topic_id=OuterRef("pk"), answered_at__isnull=False)),
    )
    status = scope.get("status")
    if status == "studied":
        topics = topics.filter(studied=True)
    elif status == "unstudied":
        topics = topics.filter(studied=False)
    elif status == "practiced":
        topics = topics.filter(practiced=True)
    return topics


def describe_scope(scope):
    if scope.get("topic"):
        title = Topic.objects.get(pk=scope["topic"]).title
    elif scope.get("subcategory"):
        sub = Subcategory.objects.get(pk=scope["subcategory"])
        title = f"{sub.category_id} / {sub.payload['label']}"
    else:
        title = scope.get("category", "All topics")
    if scope.get("q"):
        title += f" · Search: {scope['q']}"
    if scope.get("status"):
        title += f" · {scope['status'].capitalize()}"
    return title[:500]
