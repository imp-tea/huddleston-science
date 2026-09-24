#!/usr/bin/env python3
"""Render the Luna topic pilot's saved results as a standalone review page."""

from __future__ import annotations

import argparse
import html
import json
from pathlib import Path
from urllib.parse import urlsplit


DEFAULT_RUN = Path(__file__).resolve().parents[1] / "research/topic-enrichment/luna-pilot-2026-09-24"


def read_json(path: Path, default: object) -> object:
    if not path.exists():
        return default
    with path.open(encoding="utf-8") as stream:
        return json.load(stream)


def esc(value: object) -> str:
    return html.escape(str(value if value is not None else ""), quote=True)


def safe_url(value: object) -> str | None:
    if not isinstance(value, str) or any(ord(char) < 33 for char in value):
        return None
    try:
        parsed = urlsplit(value)
        if parsed.scheme.lower() not in {"http", "https"} or not parsed.hostname:
            return None
        if parsed.username or parsed.password:
            return None
    except ValueError:
        return None
    return value


def link(value: object, label: object | None = None) -> str:
    url = safe_url(value)
    display = esc(label if label is not None else value)
    if url is None:
        return f'<span class="unsafe-url" title="Link omitted: invalid or non-HTTP URL">{display}</span>'
    return f'<a href="{esc(url)}" target="_blank" rel="noopener noreferrer">{display}</a>'


def citations(urls: object) -> str:
    if not isinstance(urls, list) or not urls:
        return '<span class="missing">No supporting URLs supplied</span>'
    unique = list(dict.fromkeys(str(url) for url in urls))
    return '<span class="citations">Sources: ' + ", ".join(link(url) for url in unique) + "</span>"


def messages(items: object, css_class: str) -> str:
    if not isinstance(items, list) or not items:
        return ""
    return f'<ul class="{css_class}">' + "".join(f"<li>{esc(item)}</li>" for item in items) + "</ul>"


def money(value: object) -> str:
    try:
        return f"${float(value):,.4f}"
    except (TypeError, ValueError):
        return "unknown"


def render(run: Path) -> Path:
    manifest = read_json(run / "manifest.json", {})
    summary = read_json(run / "summary.json", {})
    if not isinstance(manifest, dict) or not isinstance(manifest.get("topics"), list):
        raise ValueError("manifest.json must contain a topics list")
    if not isinstance(summary, dict):
        summary = {}

    topics = [topic for topic in manifest["topics"] if isinstance(topic, dict)]
    records: dict[str, dict] = {}
    for path in sorted((run / "responses").glob("*.json")):
        try:
            record = read_json(path, {})
        except (OSError, json.JSONDecodeError):
            continue  # A concurrently written response can be rendered on the next run.
        if isinstance(record, dict) and isinstance(record.get("topic_id"), str):
            records[record["topic_id"]] = record

    selected_records = [records[t["study_topic_id"]] for t in topics if t.get("study_topic_id") in records]
    valid = sum(record.get("validation", {}).get("valid") is True for record in selected_records)
    finished = len(selected_records)
    pending = len(topics) - finished
    failed = finished - valid
    # The summary is written by the runner after responses. Prefer it when current;
    # otherwise sum the saved response estimates so this page remains useful mid-run.
    totals = summary.get("totals", {}) if summary.get("requests_finished") == finished else {}
    if not isinstance(totals, dict) or not totals:
        cost = sum(float(record.get("usage_cost", {}).get("estimated_usd") or 0) for record in selected_records)
    else:
        cost = totals.get("estimated_usd")
    categories = sorted({str(topic.get("primary_category") or "Uncategorized") for topic in topics})
    grouped = {category: [] for category in categories}
    for number, topic in enumerate(topics, 1):
        grouped[str(topic.get("primary_category") or "Uncategorized")].append((number, topic))

    parts = ["""<!doctype html>
<html lang="en"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<title>Luna topic pilot review</title>
<style>
:root{color-scheme:light;font:16px/1.55 system-ui,-apple-system,BlinkMacSystemFont,"Segoe UI",sans-serif;color:#182236;background:#f4f6f9}
*{box-sizing:border-box}body{margin:0}header{background:#172b47;color:#fff;padding:2rem max(1.5rem,calc((100vw - 1080px)/2))}header h1{margin:0 0 .35rem;font-size:2rem}header p{margin:.3rem 0;color:#d9e4f2}
main{max-width:1080px;margin:0 auto;padding:1.5rem}.notice{background:#fff1cb;border-left:4px solid #c68700;padding:.8rem 1rem;margin:1rem 0}.stats{display:grid;grid-template-columns:repeat(auto-fit,minmax(130px,1fr));gap:.7rem;margin:1.3rem 0}.stat{background:#fff;border:1px solid #dbe2ea;border-radius:8px;padding:.8rem}.stat strong{display:block;font-size:1.5rem}.stat span{color:#526077}
nav,.topic{background:#fff;border:1px solid #dbe2ea;border-radius:8px;margin:1rem 0;padding:1.1rem 1.3rem}nav h2{margin-top:0}nav ul{columns:2;padding-left:1.2rem}nav li{break-inside:avoid;margin-bottom:.22rem}a{color:#0756a5;overflow-wrap:anywhere}a:hover{text-decoration-thickness:2px}.category{margin-top:2.1rem;border-bottom:2px solid #bdcddd;padding-bottom:.25rem}.topic h3{display:inline;margin-right:.5rem}.topic .description{color:#47556b;margin:.45rem 0 1rem}.badge{display:inline-block;border-radius:999px;padding:.12rem .55rem;font-size:.78rem;font-weight:700;vertical-align:middle}.valid{background:#def4e6;color:#146036}.invalid{background:#ffe0de;color:#96352d}.pending{background:#e8edf4;color:#4c5b70}.overview{font-size:1.06rem}.citations{display:block;font-size:.81rem;color:#526077;margin:.3rem 0 .8rem;overflow-wrap:anywhere}.facts li{margin-bottom:.7rem}.facts .citations{margin:.1rem 0 .4rem}.errors{color:#8c251e}.warnings,.concerns{color:#815400}.missing,.unsafe-url{color:#9a3d28}.meta{color:#526077;font-size:.9rem}details{margin:.8rem 0}summary{cursor:pointer;font-weight:600}input[type=search]{width:100%;padding:.7rem;border:1px solid #aab9cb;border-radius:6px;font:inherit}footer{padding:2rem 0;color:#526077}.empty{color:#526077;font-style:italic}@media(max-width:650px){nav ul{columns:1}header{padding:1.5rem}main{padding:1rem}}
</style></head><body><header><h1>Luna topic pilot review</h1><p>Draft research for human review · Not imported into the site</p></header><main>"""]
    parts.append('<p class="notice"><strong>Pilot drafts only.</strong> The entries below come from saved model responses and have not been imported. Cost is an estimate from API usage and pricing, not an invoice.</p>')
    parts.append('<p class="meta">Automatic checks include a recorded page-open action for every cited source, a stricter rule than the regular queue’s minimum of one directly read source per topic. A flag is not proof of a factual error. See <a href="REPORT.md">the pilot report</a> for the separate factual sample and cost breakdown.</p>')
    parts.append('<div class="stats" aria-label="Pilot status">')
    for label, value in (("Selected", len(topics)), ("Finished", finished), ("Checks passed", valid), ("Needs review", failed), ("Pending", pending), ("Estimated cost", money(cost))):
        parts.append(f'<div class="stat"><strong>{esc(value)}</strong><span>{esc(label)}</span></div>')
    parts.append('</div>')
    parts.append(f'<p class="meta">Requested model: {esc(manifest.get("model", summary.get("model_requested", "unknown")))} · Updated: {esc(summary.get("updated_at", "pending"))}</p>')
    if finished != summary.get("requests_finished") and summary:
        parts.append('<p class="meta">The summary is behind the saved responses; counts and cost shown here use the response files.</p>')
    if summary.get("failures") or summary.get("warnings"):
        parts.append('<details><summary>Runner-wide validation messages</summary>')
        for name in ("failures", "warnings"):
            for item in summary.get(name, []):
                parts.append(f'<p><strong>{esc(name[:-1].title())}:</strong> {esc(json.dumps(item, ensure_ascii=False) if isinstance(item, (dict, list)) else item)}</p>')
        parts.append('</details>')

    parts.append('<nav aria-label="Topic index"><h2>Topics by category</h2><label for="search">Find a topic</label><input id="search" type="search" placeholder="Search title, category, or description" autocomplete="off">')
    for category, entries in grouped.items():
        parts.append(f'<h3>{esc(category)} <small>({len(entries)})</small></h3><ul>')
        for number, topic in entries:
            tid = topic.get("study_topic_id", "")
            record = records.get(tid)
            state = "Pending" if record is None else ("Checks passed" if record.get("validation", {}).get("valid") is True else "Needs review")
            parts.append(f'<li class="index-item" data-topic="{esc((str(topic.get("topic", "")) + " " + category + " " + str(topic.get("description", ""))).lower())}"><a href="#topic-{number}">{esc(topic.get("topic", "Untitled"))}</a> <small>({esc(state)})</small></li>')
        parts.append('</ul>')
    parts.append('</nav>')

    for category, entries in grouped.items():
        parts.append(f'<h2 class="category">{esc(category)}</h2>')
        for number, topic in entries:
            tid = str(topic.get("study_topic_id", ""))
            record = records.get(tid)
            validation = record.get("validation", {}) if record else {}
            if not isinstance(validation, dict):
                validation = {}
            state = "Pending" if record is None else ("Checks passed" if validation.get("valid") is True else "Needs review")
            badge = "pending" if record is None else ("valid" if validation.get("valid") is True else "invalid")
            parts.append(f'<article id="topic-{number}" class="topic" data-topic="{esc((str(topic.get("topic", "")) + " " + category + " " + str(topic.get("description", ""))).lower())}"><h3>{esc(topic.get("topic", "Untitled"))}</h3><span class="badge {badge}">{state}</span>')
            parts.append(f'<p class="description"><strong>Original description:</strong> {esc(topic.get("description", ""))}</p>')
            if record is None:
                parts.append('<p class="empty">No response saved yet.</p></article>')
                continue
            parts.append(f'<p class="meta">Status: {esc(record.get("status", "unknown"))} · Topic ID: {esc(tid)} · Estimated cost: {money(record.get("usage_cost", {}).get("estimated_usd"))}</p>')
            result = record.get("result")
            if isinstance(result, dict):
                overview = result.get("overview")
                if isinstance(overview, dict):
                    parts.append(f'<h4>Overview</h4><p class="overview">{esc(overview.get("text", ""))}</p>{citations(overview.get("source_urls"))}')
                facts = result.get("key_facts")
                if isinstance(facts, list) and facts:
                    parts.append('<h4>Key facts</h4><ol class="facts">')
                    for fact in facts:
                        if isinstance(fact, dict):
                            parts.append(f'<li>{esc(fact.get("text", ""))}{citations(fact.get("source_urls"))}</li>')
                    parts.append('</ol>')
                concerns = result.get("unresolved_concerns")
                if isinstance(concerns, list) and concerns:
                    parts.append('<h4>Model-reported concerns</h4>' + messages(concerns, "concerns"))
                sources = result.get("sources")
                if isinstance(sources, list) and sources:
                    parts.append('<details><summary>Source reference details</summary><ul>')
                    for source in sources:
                        if isinstance(source, dict):
                            parts.append(f'<li>{link(source.get("url"), source.get("title") or source.get("url"))} — {esc(source.get("publisher", ""))}<br><small>{esc(source.get("supports", ""))}</small></li>')
                    parts.append('</ul></details>')
            else:
                parts.append('<p class="empty">No structured draft was saved for this response.</p>')
            if validation.get("errors"):
                parts.append('<h4>Validation errors</h4>' + messages(validation["errors"], "errors"))
            if validation.get("warnings"):
                parts.append('<h4>Validation warnings</h4>' + messages(validation["warnings"], "warnings"))
            parts.append('</article>')
    parts.append('''<footer>Review page generated from pilot files. The source links open their original websites; saved API response metadata is not shown here.</footer></main>
<script>
const search=document.getElementById('search');
search.addEventListener('input',()=>{const q=search.value.trim().toLowerCase();for(const item of document.querySelectorAll('[data-topic]'))item.hidden=!item.dataset.topic.includes(q)});
</script></body></html>''')
    output = run / "review.html"
    output.write_text("\n".join(parts), encoding="utf-8")
    return output


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--run-dir", type=Path, default=DEFAULT_RUN)
    args = parser.parse_args()
    print(render(args.run_dir))
