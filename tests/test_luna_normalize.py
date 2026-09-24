"""Offline checks for Luna response normalization and repair flags."""

import json
from pathlib import Path
import sys
import tempfile
import unittest


sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))
from normalize_luna_topics import normalize, normalize_record  # noqa: E402
from research_redaction import sanitize_record  # noqa: E402


TOPIC = {"study_topic_id": "study-example", "topic": "Example", "primary_category": "Mathematics"}
URL = "https://example.edu/topic"
STAMP = "2026-09-24T17:18:34+00:00"


def record():
    overview = " ".join(["This example explains a mathematical idea and its classroom uses."] * 9)
    return {
        "topic_id": TOPIC["study_topic_id"], "topic": TOPIC["topic"],
        "category": TOPIC["primary_category"], "model_requested": "gpt-6-luna",
        "started_at": STAMP, "status": "completed",
        "request": {"input": json.dumps({"current_utc": STAMP, "assigned_topic": TOPIC})},
        "response": {"model": "gpt-6-luna", "output": [
            {"type": "web_search_call", "action": {"type": "search"}},
            {"type": "web_search_call", "action": {"type": "open_page", "url": URL}},
        ]},
        "result": {
            "study_topic_id": TOPIC["study_topic_id"],
            "overview": {"text": overview, "source_urls": [URL]},
            "key_facts": [{"text": f"Fact {i} explains the idea.", "source_urls": [URL]} for i in range(4)],
            "sources": [{"title": "Example Topic", "url": URL, "publisher": "Example University",
                         "retrieved_at": "2026-01-01T00:00:00Z", "supports": "Definition and uses."}],
            "research_queries": ["example mathematical idea"], "notes": "A historical caveat.",
            "unresolved_concerns": ["A claim may need further reading."],
            "self_check_complete": True,
        },
    }


class NormalizeTests(unittest.TestCase):
    def test_signed_web_trace_requires_sanitized_raw_record(self):
        raw = record()
        signed = URL + '?X-Amz-' + 'Credential=' + ('AK' + 'IA' + 'A' * 16)
        raw['response']['output'][1]['action']['sources'] = [{'url': signed}]
        with self.assertRaisesRegex(ValueError, 'Unsanitized credential material'):
            normalize_record(raw, 'abc', 'raw.json', TOPIC)
        clean = sanitize_record(raw)
        self.assertFalse(clean['redaction']['result_changed'])
        _, _, provenance, problems = normalize_record(clean, 'abc', 'raw.json', TOPIC)
        self.assertEqual([], problems)
        self.assertTrue(provenance['automatic_validation_passed'])
        self.assertEqual(clean['redaction'], provenance['response_redaction'])

    def test_redacted_result_citation_blocks_even_with_stable_looking_url(self):
        raw = record()
        raw['result']['key_facts'][0]['source_urls'] = [URL + '?X-Amz-' + 'Signature=synthetic']
        clean = sanitize_record(raw)
        self.assertTrue(clean['redaction']['citation_urls_changed'])
        self.assertEqual([URL], clean['result']['key_facts'][0]['source_urls'])
        _, _, provenance, problems = normalize_record(clean, 'abc', 'raw.json', TOPIC)
        self.assertTrue(any('stable-source repair' in reason for reason in problems))
        self.assertFalse(provenance['automatic_validation_passed'])

    def test_site_shape_timestamp_and_caveat(self):
        raw = record()
        topic, research, provenance, problems = normalize_record(raw, "abc", "raw.json", TOPIC)
        self.assertEqual([], problems)
        self.assertEqual("o1", topic["overview"][0]["id"])
        self.assertEqual(["f1", "f2", "f3", "f4"], [f["id"] for f in topic["key_facts"]])
        self.assertEqual(STAMP, topic["source"]["references"][0]["retrieved_at"])
        self.assertIn("Researcher caveats", research["notes"])
        self.assertTrue(provenance["automatic_validation_passed"])
        self.assertEqual("abc", provenance["raw_sha256"])
        self.assertEqual("normalized_retrieval_timestamp", provenance["adjustments"][0]["kind"])

    def test_equivalent_url_and_surplus_citation(self):
        raw = record()
        raw["result"]["overview"]["source_urls"] = ["https://www.example.edu/topic/?utm_source=quiz", "https://other.edu/missing"]
        topic, _, provenance, problems = normalize_record(raw, "abc", "raw.json", TOPIC)
        self.assertEqual([], problems)
        self.assertEqual([URL], topic["overview"][0]["source_urls"])
        kinds = [a["kind"] for a in provenance["adjustments"]]
        self.assertIn("canonicalized_citation", kinds)
        self.assertIn("removed_unlisted_citation", kinds)

    def test_sole_unlisted_citation_blocks(self):
        raw = record()
        raw["result"]["key_facts"][0]["source_urls"] = ["https://other.edu/not-in-references"]
        _, _, provenance, problems = normalize_record(raw, "abc", "raw.json", TOPIC)
        self.assertTrue(any("f1: no listed supporting reference" in p for p in problems))
        self.assertFalse(provenance["automatic_validation_passed"])

    def test_minimum_web_trace_not_every_reference_open(self):
        raw = record()
        raw["result"]["sources"].append({"title": "Second", "url": "https://museum.org/a",
            "publisher": "Museum", "retrieved_at": STAMP, "supports": "Extra evidence."})
        raw["result"]["key_facts"][1]["source_urls"] = ["https://museum.org/a"]
        _, _, provenance, problems = normalize_record(raw, "abc", "raw.json", TOPIC)
        self.assertEqual([], problems)
        self.assertTrue(provenance["automatic_validation_passed"])
        raw["response"]["output"] = raw["response"]["output"][:1]
        _, _, _, problems = normalize_record(raw, "abc", "raw.json", TOPIC)
        self.assertTrue(any("direct open_page" in p for p in problems))

    def test_directory_run_preserves_raw_and_blocks_missing(self):
        with tempfile.TemporaryDirectory() as temporary:
            base = Path(temporary)
            responses = base / "responses"
            responses.mkdir()
            raw_path = responses / "study-example.json"
            raw_bytes = json.dumps(record()).encode()
            raw_path.write_bytes(raw_bytes)
            manifest = base / "manifest.json"
            manifest.write_text(json.dumps({"topics": [TOPIC, {**TOPIC, "study_topic_id": "study-missing"}]}))
            output = normalize(manifest, responses)
            self.assertEqual({"assigned": 2, "ready": 1, "blocked": 1}, output["counts"])
            self.assertEqual(raw_bytes, raw_path.read_bytes())
            self.assertIn("study-missing", output["blocked_topics"])

    def test_concerns_and_conservative_source_budget(self):
        with tempfile.TemporaryDirectory() as temporary:
            base = Path(temporary)
            responses = base / "responses"
            responses.mkdir()
            raw = record()
            raw["result"]["overview"]["text"] = " ".join(["An original explanation uses accessible examples for students today."] * 12)
            raw["result"]["key_facts"] = [
                {"text": " ".join([f"Fact {i} explains a long, useful distinction."] * 5),
                 "source_urls": [URL]} for i in range(4)]
            (responses / "study-example.json").write_text(json.dumps(raw))
            manifest = base / "manifest.json"
            manifest.write_text(json.dumps({"topics": [TOPIC]}))
            output = normalize(manifest, responses)
            self.assertIn("study-example", output["researcher_concerns"])
            self.assertIn("A claim may need further reading.", output["researcher_concerns"]["study-example"]["unresolved_concerns"])
            self.assertGreater(output["source_budget_warnings"]["study-example"][0]["conservative_attributed_words"], 200)

    def test_exact_correction_changes_copy_not_raw(self):
        with tempfile.TemporaryDirectory() as temporary:
            base = Path(temporary)
            responses = base / "responses"
            responses.mkdir()
            raw = record()
            raw_path = responses / "study-example.json"
            original = json.dumps(raw).encode()
            raw_path.write_bytes(original)
            manifest = base / "manifest.json"
            manifest.write_text(json.dumps({"topics": [TOPIC]}))
            correction = base / "corrections.json"
            correction.write_text(json.dumps({"corrections": [{
                "topic_id": "study-example", "block_id": "f1",
                "old_text": "Fact 0 explains the idea.", "new_text": "Corrected fact explains the idea.",
                "evidence_urls": [URL]}]}))
            output = normalize(manifest, responses, correction)
            self.assertEqual("Corrected fact explains the idea.", output["topics"]["study-example"]["key_facts"][0]["text"])
            self.assertEqual("reviewed_correction", output["provenance"]["study-example"]["adjustments"][-1]["kind"])
            self.assertEqual(original, raw_path.read_bytes())
            correction.write_text(json.dumps({"corrections": [{
                "topic_id": "study-example", "block_id": "f1",
                "old_text": "Wrong old text", "new_text": "Corrected fact explains the idea."}]}))
            output = normalize(manifest, responses, correction)
            self.assertIn("study-example", output["blocked_topics"])
            self.assertNotIn("study-example", output["topics"])

    def test_correction_repairs_sole_unlisted_citation(self):
        with tempfile.TemporaryDirectory() as temporary:
            base = Path(temporary)
            responses = base / "responses"
            responses.mkdir()
            raw = record()
            bad_url = "https://example.edu/wrong-slug"
            raw["result"]["key_facts"][0]["source_urls"] = [bad_url]
            (responses / "study-example.json").write_text(json.dumps(raw))
            manifest = base / "manifest.json"
            manifest.write_text(json.dumps({"topics": [TOPIC]}))
            correction = base / "corrections.json"
            correction.write_text(json.dumps({"corrections": [{
                "topic_id": "study-example", "block_id": "f1",
                "old_text": "Fact 0 explains the idea.", "new_text": "Fact 0 explains the idea.",
                "old_source_urls": [bad_url], "new_source_urls": [URL],
                "evidence_urls": [URL]}]}))
            output = normalize(manifest, responses, correction)
            self.assertEqual(1, output["counts"]["ready"])
            self.assertEqual([URL], output["topics"]["study-example"]["key_facts"][0]["source_urls"])
            self.assertTrue(output["provenance"]["study-example"]["automatic_validation_passed"])

    def test_reference_removal_requires_unused_existing_url(self):
        with tempfile.TemporaryDirectory() as temporary:
            base = Path(temporary)
            responses = base / "responses"
            responses.mkdir()
            raw = record()
            unused = "https://example.edu/broken"
            raw["result"]["sources"].append({"title": "Broken", "url": unused,
                "publisher": "Example University", "retrieved_at": STAMP,
                "supports": "A claim no longer used after correction."})
            (responses / "study-example.json").write_text(json.dumps(raw))
            manifest = base / "manifest.json"
            manifest.write_text(json.dumps({"topics": [TOPIC]}))
            patch = {"topic_id": "study-example", "block_id": "f1",
                     "old_text": "Fact 0 explains the idea.", "new_text": "Fact 0 explains the idea.",
                     "reference_removals": [unused]}
            correction = base / "corrections.json"
            correction.write_text(json.dumps({"corrections": [patch]}))
            output = normalize(manifest, responses, correction)
            self.assertEqual(1, output["counts"]["ready"])
            self.assertNotIn(unused, [r["url"] for r in output["topics"]["study-example"]["source"]["references"]])
            self.assertNotIn(unused, [s["url"] for s in output["research"]["study-example"]["sources"]])
            self.assertTrue(any(a["kind"] == "reviewed_reference_removal"
                                for a in output["provenance"]["study-example"]["adjustments"]))
            patch["reference_removals"] = [URL]
            correction.write_text(json.dumps({"corrections": [patch]}))
            output = normalize(manifest, responses, correction)
            self.assertIn("study-example", output["blocked_topics"])
            self.assertTrue(any("cannot remove cited reference" in reason
                                for reason in output["blocked_topics"]["study-example"]))

    def test_added_reference_keeps_review_time_and_requires_explicit_utc(self):
        with tempfile.TemporaryDirectory() as temporary:
            base = Path(temporary)
            responses = base / "responses"
            responses.mkdir()
            (responses / "study-example.json").write_text(json.dumps(record()))
            manifest = base / "manifest.json"
            manifest.write_text(json.dumps({"topics": [TOPIC]}))
            later_url = "https://museum.org/later-review"
            later_time = "2026-09-25T13:45:00Z"
            addition = {"title": "Later source", "url": later_url, "publisher": "Museum",
                        "supports": "A directly reviewed detail.", "retrieved_at": later_time}
            patch = {"topic_id": "study-example", "block_id": "f1",
                     "old_text": "Fact 0 explains the idea.", "new_text": "Fact 0 explains the idea.",
                     "new_source_urls": [URL, later_url], "reference_additions": [addition]}
            correction = base / "corrections.json"
            correction.write_text(json.dumps({"corrections": [patch]}))
            output = normalize(manifest, responses, correction)
            refs = output["topics"]["study-example"]["source"]["references"]
            self.assertEqual("2026-09-25T13:45:00+00:00", next(r["retrieved_at"] for r in refs
                                                                  if r["url"] == later_url))
            self.assertNotEqual(STAMP, next(r["retrieved_at"] for r in refs if r["url"] == later_url))
            self.assertIn(later_url, [s["url"] for s in output["research"]["study-example"]["sources"]])
            addition.pop("retrieved_at")
            correction.write_text(json.dumps({"corrections": [patch]}))
            output = normalize(manifest, responses, correction)
            self.assertIn("study-example", output["blocked_topics"])
            self.assertTrue(any("explicit valid UTC retrieved_at" in reason
                                for reason in output["blocked_topics"]["study-example"]))


if __name__ == "__main__":
    unittest.main()
