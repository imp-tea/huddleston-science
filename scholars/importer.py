"""Import study material; questions are database-owned after explicit empty-bank seeding."""
import hashlib
import json
from django.core.exceptions import ValidationError
from django.db import connection, transaction
from scripts.build import load_and_validate
from scripts.typed_content import load_typed_questions
from django.conf import settings
from .models import Category, ContentImport, Question, QuestionRevision, Source, Subcategory, Topic, TopicRedirect

CONTENT_LOCK = 740291


def digest(value):
    return hashlib.sha256(json.dumps(value, sort_keys=True, ensure_ascii=False, separators=(",", ":")).encode()).hexdigest()


def upsert(model, rows, fields):
    model.objects.bulk_create(rows, batch_size=250, update_conflicts=True, unique_fields=["pk"], update_fields=fields)


def import_content(data_dir=None, allow_retire=False, *, seed_questions=False):
    # All validation precedes any database write, using the existing build validator.
    data = load_and_validate(data_dir, include_questions=seed_questions)
    taxonomy, topics, content, sources, practice, redirects = data
    typed = load_typed_questions(data_dir or settings.BASE_DIR / 'data', topics, practice) if seed_questions else []
    multiple_choice_count = len(practice)
    practice = practice + typed
    if not topics or (seed_questions and not practice):
        raise ValidationError("Empty content imports are not allowed.")
    counts = dict(categories=len(taxonomy["categories"]), subcategories=len(taxonomy["subcategories"]),
                  topics=len(topics), subjects=len({t["subject_id"] for t in topics}), detailed_pages=len(content),
                  practice_questions=len(practice), multiple_choice_questions=multiple_choice_count,
                  typed_questions=len(typed), source_questions=len(sources), redirects=len(redirects))
    topic_map = {t["study_topic_id"]: t for t in topics}
    incoming = [(Category, {c["primary_category"] for c in taxonomy["categories"]}),
                (Subcategory, {s["subcategory_id"] for s in taxonomy["subcategories"]}),
                (Source, set(sources)), (Topic, set(topic_map)),
                (TopicRedirect, set(redirects))]
    with transaction.atomic():
        # Serialize imports; quiz creation takes a shared lock on this same key.
        with connection.cursor() as cursor:
            cursor.execute("SELECT pg_advisory_xact_lock(%s)", [CONTENT_LOCK])
        if seed_questions and Question.objects.exists():
            raise ValidationError("Question seeding requires an empty bank. Use export_question_bank and apply_question_updates for existing questions.")
        if Question.objects.filter(active=True).exclude(topic_id__in=topic_map).exists():
            raise ValidationError("Cannot retire topics with active database-owned questions. Archive those questions explicitly first.")
        for model, ids in incoming:
            missing = model.objects.filter(active=True).exclude(pk__in=ids)
            if missing.exists() and not allow_retire:
                raise ValidationError(f"Import removes {model.__name__} records. Review the source, then use --allow-retire.")
        for tid, subject in Topic.objects.values_list("id", "subject_id"):
            if tid in topic_map and topic_map[tid]["subject_id"] != subject:
                raise ValidationError(f"Cannot reuse topic identity {tid} for a different subject.")
        upsert(Category, [Category(id=c["primary_category"], payload=c) for c in taxonomy["categories"]], ["payload", "active"])
        upsert(Subcategory, [Subcategory(id=s["subcategory_id"], category_id=s["primary_category"], payload=s)
                            for s in taxonomy["subcategories"]], ["category", "payload", "active"])
        upsert(Source, [Source(id=sid, payload=s) for sid, s in sources.items()], ["payload", "active"])
        upsert(Topic, [Topic(id=t["study_topic_id"], subject_id=t["subject_id"], title=t["topic"],
                            category_id=t["primary_category"], payload=t, study_content=content.get(t["study_topic_id"], {}))
                       for t in topics], ["subject_id", "title", "category", "payload", "study_content", "active"])
        # Memberships are a current-content index. Historical classifications live in revision.context.
        Topic.subcategories.through.objects.all().delete()
        Topic.subcategories.through.objects.bulk_create([
            Topic.subcategories.through(topic_id=t["study_topic_id"], subcategory_id=sid)
            for t in topics for sid in t["subcategory_ids"]], batch_size=500)
        upsert(TopicRedirect, [TopicRedirect(id=old, topic_id=target) for old, target in redirects.items()], ["topic", "active"])
        if seed_questions:
            Question.objects.bulk_create([Question(id=q['question_id'], topic_id=q['study_topic_id'],
                format=q.get('format', 'multiple_choice')) for q in practice], batch_size=500)
            contexts = {tid: {'topic': t, 'study_content': content.get(tid, {}),
                              'sources': {sid: sources[sid] for sid in t['source_ids']}}
                        for tid, t in topic_map.items()}
            revisions = [QuestionRevision(question_id=q['question_id'], payload=q,
                context=contexts[q['study_topic_id']], digest=digest([q, contexts[q['study_topic_id']]])) for q in practice]
            QuestionRevision.objects.bulk_create(revisions, batch_size=250)
            questions = {q.pk: q for q in Question.objects.all()}
            for revision in revisions:
                questions[revision.question_id].current_revision = revision
            Question.objects.bulk_update(list(questions.values()), ['current_revision'], batch_size=500)
        for model, ids in incoming:
            model.objects.exclude(pk__in=ids).update(active=False)
        counts.update(practice_questions=Question.objects.count(),
                      multiple_choice_questions=Question.objects.filter(format='multiple_choice').count(),
                      typed_questions=Question.objects.filter(format='typed').count())
        from .typed_answers import rebuild_banks
        rebuild_banks()
        ContentImport.objects.create(digest=digest([data, typed]), counts=counts)
    return counts
