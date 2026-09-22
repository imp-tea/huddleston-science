import json
from pathlib import Path
from django.conf import settings


def small_dataset(path):
    """A representative subset of real content, including multi-membership topics."""
    root = settings.BASE_DIR / "data"
    all_topics = json.loads((root / "topics.json").read_text())
    questions = [q for p in sorted((root / "practice").glob("*.json")) for q in json.loads(p.read_text())]
    ids = list(dict.fromkeys(q["study_topic_id"] for q in questions))[:8]
    topics = [t for t in all_topics if t["study_topic_id"] in ids]
    content = json.loads((root / "content.json").read_text())
    sources = json.loads((root / "sources.json").read_text())
    source_ids = {sid for t in topics for sid in t["source_ids"]}
    values = {"taxonomy.json": json.loads((root / "taxonomy.json").read_text()), "topics.json": topics,
              "content.json": {k: v for k, v in content.items() if k in ids},
              "sources.json": {k: v for k, v in sources.items() if k in source_ids},
              "topic-redirects.json": {"legacy-topic": ids[0]},
              "practice/01.json": [q for q in questions if q["study_topic_id"] in ids]}
    for name, value in values.items():
        dest = Path(path) / name
        dest.parent.mkdir(parents=True, exist_ok=True)
        dest.write_text(json.dumps(value))
    return values
