"""Convert saved one-topic Luna responses to the site enrichment schema.

This is an offline, structural conversion. It does not decide whether prose is
factually correct, edit raw responses, import site data, or call the API.
"""

import argparse
from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path
import re
from urllib.parse import parse_qsl, urlsplit

from research_redaction import sanitize_value


ROOT = Path(__file__).resolve().parents[1]
PILOT = ROOT / "research/topic-enrichment/luna-pilot-2026-09-24"
CONCERN_LANGUAGE = re.compile(
    r"\b(?:unresolved|unsupported|uncertain|inaccessible|unverified|not verified|"
    r"could not be verified|conflicting|contradictory|disputed)\b", re.I)


def utc_time(value):
    """Return a recorded ISO time as UTC, or None if it is unusable."""
    if not isinstance(value, str):
        return None
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
        if parsed.tzinfo is None:
            return None
        return parsed.astimezone(timezone.utc).isoformat()
    except ValueError:
        return None


def explicit_utc_time(value):
    """Accept only a supplied timezone-aware UTC time for a later-added source."""
    if not isinstance(value, str):
        return None
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
        if parsed.tzinfo is None or parsed.utcoffset().total_seconds() != 0:
            return None
        return parsed.astimezone(timezone.utc).isoformat()
    except ValueError:
        return None


def canonical_url(value):
    """Conservative equivalence for URL spelling, never discarding content query keys."""
    if not isinstance(value, str):
        return None
    try:
        parsed = urlsplit(value)
        if parsed.scheme.lower() not in ("http", "https") or not parsed.hostname:
            return None
        host = parsed.hostname.lower().removeprefix("www.")
        port = f":{parsed.port}" if parsed.port else ""
        path = parsed.path.rstrip("/") or "/"
        query = tuple(sorted((key, val) for key, val in parse_qsl(parsed.query, keep_blank_values=True)
                             if not key.lower().startswith("utm_")))
        return (parsed.scheme.lower(), host + port, path, query)
    except ValueError:
        return None


def request_time(record):
    """Use the actual timestamp saved in the API request; never fabricate a read time."""
    request = record.get("request") or {}
    supplied = request.get("input")
    if isinstance(supplied, str):
        try:
            supplied = json.loads(supplied)
        except json.JSONDecodeError:
            supplied = None
    if isinstance(supplied, dict):
        stamp = utc_time(supplied.get("current_utc"))
        if stamp:
            return stamp, "request.input.current_utc"
    stamp = utc_time(record.get("started_at"))
    if stamp:
        return stamp, "started_at"
    return None, None


def web_actions(record):
    response = record.get("response") or {}
    actions = [item.get("action") or {} for item in response.get("output", [])
               if item.get("type") == "web_search_call"]
    return sum(a.get("type") == "search" for a in actions), sum(a.get("type") == "open_page" for a in actions)


def _block(block, block_id, references, adjustments, problems):
    if not isinstance(block, dict) or not isinstance(block.get("text"), str) or not block["text"].strip():
        problems.append(f"{block_id}: missing text")
        return None
    listed = {ref["url"] for ref in references}
    by_canonical = {}
    for url in listed:
        by_canonical.setdefault(canonical_url(url), []).append(url)
    raw_urls = block.get("source_urls")
    if not isinstance(raw_urls, list) or not raw_urls:
        problems.append(f"{block_id}: missing citations")
        return None
    resolved, unlisted = [], []
    for url in raw_urls:
        if url in listed:
            selected = url
        else:
            matches = by_canonical.get(canonical_url(url), [])
            selected = matches[0] if len(matches) == 1 else None
            if selected:
                adjustments.append({"kind": "canonicalized_citation", "block_id": block_id,
                                    "from": url, "to": selected})
        if selected:
            if selected not in resolved:
                resolved.append(selected)
        else:
            unlisted.append(url)
    if unlisted and resolved:
        adjustments.append({"kind": "removed_unlisted_citation", "block_id": block_id,
                            "urls": unlisted, "retained_urls": resolved})
    elif unlisted:
        problems.append(f"{block_id}: no listed supporting reference; unlisted URLs: {unlisted}")
    if not resolved:
        problems.append(f"{block_id}: no usable citations")
    return {"id": block_id, "text": block["text"], "source_urls": resolved}


def normalize_record(record, raw_sha256, response_path, assigned):
    """Return (site topic, research, provenance, reasons); reasons block integration."""
    if sanitize_value(record)[1]["changed_fields"]:
        raise ValueError("Unsanitized credential material in saved response")
    problems, adjustments, notes = [], [], []
    redaction = record.get("redaction")
    if redaction is not None and not isinstance(redaction, dict):
        problems.append("Malformed redaction metadata")
        redaction = {}
    if redaction and (redaction.get("result_changed") or redaction.get("citation_urls_changed")):
        problems.append("Redacted generated result requires reviewed stable-source repair")
    result = record.get("result")
    if not isinstance(result, dict):
        result = {}
        problems.append("Missing parsed result")
    topic_id = assigned.get("study_topic_id")
    if record.get("topic_id") != topic_id or result.get("study_topic_id") != topic_id:
        problems.append("Topic ID mismatch")
    if record.get("topic") != assigned.get("topic") or record.get("category") != assigned.get("primary_category"):
        problems.append("Topic name/category mismatch")
    model = (record.get("response") or {}).get("model")
    requested = record.get("model_requested")
    if not (isinstance(model, str) and model.startswith("gpt-6-luna") and requested == "gpt-6-luna"):
        problems.append("Model mismatch: expected GPT-6 Luna")
    if record.get("status") != "completed":
        problems.append("Response not completed")
    search_count, open_count = web_actions(record)
    if search_count < 1 or open_count < 1:
        problems.append("Requires at least one search and one direct open_page action")
    stamp, stamp_origin = request_time(record)
    if stamp is None:
        problems.append("No recorded UTC request time")

    references = []
    seen_urls = set()
    raw_references = result.get("sources")
    if not isinstance(raw_references, list) or not raw_references:
        problems.append("Missing sources")
        raw_references = []
    for index, item in enumerate(raw_references, 1):
        if not isinstance(item, dict):
            problems.append(f"Reference {index} is not an object")
            continue
        url = item.get("url")
        if canonical_url(url) is None or url in seen_urls:
            problems.append(f"Reference {index} has invalid or duplicate URL")
            continue
        seen_urls.add(url)
        if not all(isinstance(item.get(k), str) and item[k].strip() for k in ("title", "publisher", "supports")):
            problems.append(f"Reference {index} lacks title, publisher, or evidence note")
        old_stamp = utc_time(item.get("retrieved_at"))
        if old_stamp != stamp:
            adjustments.append({"kind": "normalized_retrieval_timestamp", "url": url,
                                "from": item.get("retrieved_at"), "to": stamp,
                                "basis": stamp_origin})
        references.append({"title": item.get("title", ""), "url": url,
                           "publisher": item.get("publisher", ""), "retrieved_at": stamp})

    overview = _block(result.get("overview"), "o1", references, adjustments, problems)
    count = len(overview["text"].split()) if overview else 0
    if not 80 <= count <= 130:
        problems.append(f"Overview has {count} words; expected 80–130")
    raw_facts = result.get("key_facts")
    if not isinstance(raw_facts, list) or not 4 <= len(raw_facts) <= 6:
        problems.append("Expected 4–6 facts")
        raw_facts = raw_facts if isinstance(raw_facts, list) else []
    facts = [_block(fact, f"f{i}", references, adjustments, problems)
             for i, fact in enumerate(raw_facts, 1)]
    if any(fact is None for fact in facts):
        problems.append("Incomplete fact block")
    queries = result.get("research_queries")
    if not isinstance(queries, list) or not queries or not all(isinstance(q, str) and q.strip() for q in queries):
        problems.append("Missing or invalid research queries")
        queries = []
    self_check = result.get("self_check_complete") is True
    if not self_check:
        problems.append("Researcher self-check incomplete")
    if isinstance(result.get("notes"), str) and result["notes"].strip():
        notes.append(result["notes"].strip())
    caveats = result.get("unresolved_concerns") or []
    if caveats:
        notes.append("Researcher caveats: " + "; ".join(str(x) for x in caveats))
    # A caveat calls for targeted attention, but is not proof of a factual error.
    research = {"queries": queries,
                "sources": [{"url": ref.get("url", ""), "supports": ref.get("supports", "")}
                            for ref in raw_references if isinstance(ref, dict)],
                "notes": "\n".join(notes)}
    topic = {"overview": [overview] if overview else [],
             "key_facts": [fact for fact in facts if fact],
             "source": {"references": references}}
    raw_block_urls = {"o1": (result.get("overview") or {}).get("source_urls")}
    raw_block_urls.update({f"f{i}": fact.get("source_urls") if isinstance(fact, dict) else None
                           for i, fact in enumerate(raw_facts, 1)})
    # raw_sha256 identifies the persisted response artifact, which may have
    # been sanitized after capture; it is not a hash of unredacted API bytes.
    provenance = {"raw_sha256": raw_sha256, "response_path": str(response_path),
                  "model": model, "request_time": stamp, "request_time_basis": stamp_origin,
                  "self_check_complete": self_check,
                  "automatic_validation_passed": not problems,
                  "web_actions": {"search": search_count, "open_page": open_count},
                  "adjustments": adjustments, "validation_notes": notes,
                  "raw_block_source_urls": raw_block_urls,
                  "original_pilot_validation": record.get("validation")}
    if redaction:
        provenance["response_redaction"] = redaction
    return topic, research, provenance, problems


def _source_budget_warnings(topic):
    """Conservatively credit each cited source with its entire cited blocks."""
    blocks = topic["overview"] + topic["key_facts"]
    warnings = []
    for ref in topic["source"]["references"]:
        url = ref["url"]
        attributed = sum(len(block["text"].split()) for block in blocks
                         if url in block["source_urls"])
        if attributed > 200:
            warnings.append({"url": url, "conservative_attributed_words": attributed,
                             "limit": 200, "block_ids": [block["id"] for block in blocks
                                                       if url in block["source_urls"]]})
    return warnings


def _apply_corrections(output, corrections_path):
    """Apply reviewed exact-match patches to normalized copies only."""
    raw = Path(corrections_path).read_bytes()
    corrections = json.loads(raw).get("corrections")
    if not isinstance(corrections, list):
        raise ValueError("Corrections file must contain a corrections array")
    correction_hash = hashlib.sha256(raw).hexdigest()
    for index, patch in enumerate(corrections, 1):
        if not isinstance(patch, dict):
            raise ValueError(f"Correction {index} is not an object")
        topic_id, block_id = patch.get("topic_id"), patch.get("block_id")
        if topic_id not in output["topics"]:
            output["blocked_topics"].setdefault(topic_id, []).append(
                f"Correction {index} targets a topic unavailable for patching")
            continue
        topic = output["topics"][topic_id]
        blocks = topic["overview"] + topic["key_facts"]
        matches = [block for block in blocks if block["id"] == block_id]
        if len(matches) != 1 or matches[0]["text"] != patch.get("old_text"):
            output["blocked_topics"].setdefault(topic_id, []).append(
                f"Correction {index} did not match {block_id} exact old text")
            continue
        block = matches[0]
        old_citations = output["provenance"][topic_id]["raw_block_source_urls"].get(block_id)
        if "old_source_urls" in patch and old_citations != patch["old_source_urls"]:
            output["blocked_topics"].setdefault(topic_id, []).append(
                f"Correction {index} did not match {block_id} exact old citations")
            continue
        new_text = patch.get("new_text")
        if not isinstance(new_text, str) or not new_text.strip():
            output["blocked_topics"].setdefault(topic_id, []).append(
                f"Correction {index} has empty new text")
            continue
        additions = patch.get("reference_additions") or []
        if not isinstance(additions, list):
            output["blocked_topics"].setdefault(topic_id, []).append(
                f"Correction {index} reference additions are invalid")
            continue
        existing = {r["url"] for r in topic["source"]["references"]}
        prepared = []
        for ref in additions:
            if not isinstance(ref, dict) or canonical_url(ref.get("url")) is None or not all(
                isinstance(ref.get(key), str) and ref[key].strip()
                for key in ("title", "url", "publisher", "supports")):
                prepared = None
                break
            if ref["url"] not in existing:
                retrieved_at = explicit_utc_time(ref.get("retrieved_at"))
                if retrieved_at is None:
                    output["blocked_topics"].setdefault(topic_id, []).append(
                        f"Correction {index} added reference lacks an explicit valid UTC retrieved_at: {ref['url']}")
                    prepared = None
                    break
                prepared.append({**ref, "retrieved_at": retrieved_at})
                existing.add(ref["url"])
        new_urls = patch.get("new_source_urls", block["source_urls"])
        if prepared is None or not isinstance(new_urls, list) or not new_urls or not set(new_urls) <= existing:
            output["blocked_topics"].setdefault(topic_id, []).append(
                f"Correction {index} has invalid or unlisted new citations")
            continue
        if block_id == "o1" and not 80 <= len(new_text.split()) <= 130:
            output["blocked_topics"].setdefault(topic_id, []).append(
                f"Correction {index} makes overview length invalid")
            continue
        for ref in prepared:
            topic["source"]["references"].append({"title": ref["title"], "url": ref["url"],
                                                   "publisher": ref["publisher"],
                                                   "retrieved_at": ref["retrieved_at"]})
            output["research"][topic_id]["sources"].append({"url": ref["url"],
                                                                "supports": ref["supports"]})
        block["text"] = new_text
        block["source_urls"] = list(dict.fromkeys(new_urls))
        removals = patch.get("reference_removals") or []
        if not isinstance(removals, list) or not all(isinstance(url, str) for url in removals):
            output["blocked_topics"].setdefault(topic_id, []).append(
                f"Correction {index} reference_removals must be a list of URLs")
            continue
        if len(removals) != len(set(removals)):
            output["blocked_topics"].setdefault(topic_id, []).append(
                f"Correction {index} has duplicate reference removals")
            continue
        for removed_url in removals:
            refs = topic["source"]["references"]
            evidence = output["research"][topic_id]["sources"]
            if not any(ref["url"] == removed_url for ref in refs):
                output["blocked_topics"].setdefault(topic_id, []).append(
                    f"Correction {index} cannot remove nonexistent reference {removed_url}")
                continue
            if not any(source["url"] == removed_url for source in evidence):
                output["blocked_topics"].setdefault(topic_id, []).append(
                    f"Correction {index} cannot remove reference without matching research evidence {removed_url}")
                continue
            if any(removed_url in other["source_urls"] for other in blocks):
                output["blocked_topics"].setdefault(topic_id, []).append(
                    f"Correction {index} cannot remove cited reference {removed_url}")
                continue
            topic["source"]["references"] = [ref for ref in refs if ref["url"] != removed_url]
            output["research"][topic_id]["sources"] = [source for source in evidence
                                                          if source["url"] != removed_url]
            output["provenance"][topic_id]["adjustments"].append({
                "kind": "reviewed_reference_removal", "correction_index": index,
                "url": removed_url, "corrections_sha256": correction_hash})
        output["provenance"][topic_id]["adjustments"].append({
            "kind": "reviewed_correction", "block_id": block_id,
            "correction_index": index, "corrections_sha256": correction_hash,
            "old_text": patch["old_text"], "new_text": new_text,
            "evidence_urls": patch.get("evidence_urls", []),
            "added_reference_urls": [ref["url"] for ref in prepared]})
def normalize(manifest_path, responses_dir, corrections_path=None):
    manifest = json.loads(Path(manifest_path).read_text())
    topic_defs = manifest.get("topics") or []
    output = {"batch_id": "luna-normalized", "model": "gpt-6-luna", "topics": {}, "research": {},
              "provenance": {}, "blocked_topics": {}, "researcher_concerns": {},
              "source_budget_warnings": {}}
    for assigned in topic_defs:
        topic_id = assigned["study_topic_id"]
        path = Path(responses_dir) / f"{topic_id}.json"
        if not path.exists():
            output["blocked_topics"][topic_id] = ["Missing saved response"]
            continue
        raw = path.read_bytes()
        try:
            record = json.loads(raw)
        except (ValueError, UnicodeDecodeError):
            output["blocked_topics"][topic_id] = ["Saved response is invalid JSON"]
            continue
        if sanitize_value(record)[1]["changed_fields"]:
            output["blocked_topics"][topic_id] = ["Unsanitized credential material in saved response"]
            continue
        topic, research, provenance, problems = normalize_record(
            record, hashlib.sha256(raw).hexdigest(), path, assigned)
        output["provenance"][topic_id] = provenance
        result = record.get("result") or {}
        caveats = result.get("unresolved_concerns") or []
        note = result.get("notes") or ""
        if caveats or (isinstance(note, str) and CONCERN_LANGUAGE.search(note)):
            output["researcher_concerns"][topic_id] = {
                "unresolved_concerns": caveats,
                "flagged_note": note if isinstance(note, str) and CONCERN_LANGUAGE.search(note) else ""}
        output["topics"][topic_id] = topic
        output["research"][topic_id] = research
        if problems:
            output["blocked_topics"][topic_id] = problems
    if corrections_path:
        _apply_corrections(output, corrections_path)
        # A reviewed citation correction can repair an initially unlisted sole URL.
        for topic_id in list(output["blocked_topics"]):
            if topic_id not in output["topics"]:
                continue
            topic = output["topics"][topic_id]
            cited = {r["url"] for r in topic["source"]["references"]}
            blocks = topic["overview"] + topic["key_facts"]
            if all(b["source_urls"] and set(b["source_urls"]) <= cited for b in blocks):
                remaining = [p for p in output["blocked_topics"][topic_id] if not re.match(
                    r"^(?:o1|f\d+): (?:missing citations|no listed supporting reference|no usable citations)", p)]
                if not remaining:
                    output["blocked_topics"].pop(topic_id)
                    output["provenance"][topic_id]["automatic_validation_passed"] = True
                else:
                    output["blocked_topics"][topic_id] = remaining
    if sanitize_value(output)[1]["changed_fields"]:
        raise ValueError("Unsanitized credential material in normalized output")
    for topic_id in output["blocked_topics"]:
        output["topics"].pop(topic_id, None)
        output["research"].pop(topic_id, None)
        if topic_id in output["provenance"]:
            output["provenance"][topic_id]["automatic_validation_passed"] = False
    for topic_id, topic in output["topics"].items():
        warnings = _source_budget_warnings(topic)
        if warnings:
            output["source_budget_warnings"][topic_id] = warnings
    output["counts"] = {"assigned": len(topic_defs), "ready": len(output["topics"]),
                        "blocked": len(output["blocked_topics"])}
    return output


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--manifest", type=Path, default=PILOT / "manifest.json")
    parser.add_argument("--responses-dir", type=Path, default=PILOT / "responses")
    parser.add_argument("--corrections", type=Path, help="Optional reviewed exact-match corrections JSON")
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    output = normalize(args.manifest, args.responses_dir, args.corrections)
    args.output.parent.mkdir(parents=True, exist_ok=True)
    temporary = args.output.with_suffix(args.output.suffix + ".tmp")
    temporary.write_text(json.dumps(output, ensure_ascii=False, indent=2) + "\n")
    temporary.replace(args.output)
    print(json.dumps({"output": str(args.output), **output["counts"]}))


if __name__ == "__main__":
    main()
