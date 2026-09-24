"""Synthetic, offline regression checks for web-result credential redaction."""

import io
import json
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import patch


sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))
import luna_topic_pilot as pilot  # noqa: E402
from research_redaction import sanitize_record, sanitize_value  # noqa: E402


def fake_key():
    # Never check a literal credential-looking token into the repository.
    return "AS" + "IA" + "Q" * 16


def signed_url():
    base = "https://research.example.edu/document.pdf"
    query = "&".join(("article=42", "X-Amz-Algorithm=AWS4-HMAC-SHA256",
                      "X-Amz-Credential=" + fake_key() + "%2Fdate%2Fregion%2Fs3%2Faws4_request",
                      "X-Amz-Signature=synthetic-signature",
                      "X-Amz-Security-Token=synthetic-token"))
    return base + "?" + query


class FakeHTTPResponse(io.BytesIO):
    headers = {"x-request-id": "request-test"}


class ResearchRedactionTests(unittest.TestCase):
    def test_recursive_signed_url_and_json_string(self):
        url = signed_url()
        value = {"output": [{"action": {"sources": [{"url": url}]}}],
                 "output_text": json.dumps({"source_urls": [url]}),
                 "note": "See " + url + " for details.",
                 "authorization": "The authorization of a museum exhibit is historical prose.",
                 "headers": {"Authorization": "Bearer synthetic-secret"},
                 "aws_secret_access_key": "synthetic-secret-value"}
        clean, report = sanitize_value(value)
        serialized = json.dumps(clean)
        self.assertNotIn(fake_key(), serialized)
        self.assertNotIn("synthetic-signature", serialized)
        self.assertNotIn("synthetic-secret-value", serialized)
        self.assertNotIn("Bearer synthetic-secret", serialized)
        self.assertIn("article=42", serialized)
        self.assertIn("https://research.example.edu/document.pdf", serialized)
        self.assertEqual(value["authorization"], clean["authorization"])
        self.assertGreater(report["signed_urls_redacted"], 0)
        again, second = sanitize_value(clean)
        self.assertEqual(clean, again)
        self.assertEqual(0, second["changed_fields"])

    def test_result_change_blocks_acceptance_and_is_idempotent(self):
        record = {"result": {"sources": [{"url": signed_url()}],
                             "overview": {"source_urls": [signed_url()]}},
                  "validation": {"valid": True, "errors": [], "warnings": []}}
        clean = sanitize_record(record)
        self.assertFalse(clean["validation"]["valid"])
        self.assertTrue(clean["redaction"]["citation_urls_changed"])
        self.assertEqual(2, clean["redaction"]["signed_urls_redacted"])
        self.assertEqual(clean, sanitize_record(clean))

    def test_run_one_persists_and_returns_only_sanitized_record(self):
        stable = "https://museum.example.edu/topic?item=7"
        result = {"study_topic_id": "study-test", "overview": {
            "text": " ".join(["The exhibit documents a well studied subject and its classroom context."] * 9),
            "source_urls": [stable]},
            "key_facts": [{"text": f"Useful fact {i}.", "source_urls": [stable]} for i in range(4)],
            "sources": [{"title": "Museum Topic", "url": stable, "publisher": "Museum",
                         "retrieved_at": "2026-09-24T17:00:00Z", "supports": "Definition and facts."}],
            "research_queries": ["museum topic"], "notes": "", "unresolved_concerns": [],
            "self_check_complete": True}
        response = {"id": "resp-test", "model": "gpt-6-luna", "status": "completed", "usage": {},
                    "output": [{"type": "web_search_call", "action": {
                        "type": "search", "sources": [{"url": signed_url()}]}},
                        {"type": "web_search_call", "action": {"type": "open_page", "url": stable}},
                        {"type": "message", "content": [{"type": "output_text",
                                                           "text": json.dumps(result)}]}]}
        with tempfile.TemporaryDirectory() as temporary:
            target = Path(temporary)
            def fake_open(*_args, **_kwargs):
                return FakeHTTPResponse(json.dumps(response).encode())
            with patch.object(pilot, "RUN", target), patch.object(pilot, "urlopen", fake_open):
                returned = pilot.run_one({"study_topic_id": "study-test", "topic": "Topic",
                                          "primary_category": "Mathematics"},
                                         {"reasoning_effort": "medium", "max_tool_calls": 4,
                                          "max_output_tokens": 3000}, "synthetic-api-key")
            raw = (target / "responses" / "study-test.json").read_text()
            saved = json.loads(raw)
            self.assertEqual(returned, saved)
            self.assertNotIn(fake_key(), raw)
            self.assertNotIn("synthetic-signature", raw)
            self.assertIn("article=42", raw)
            self.assertTrue(saved["validation"]["valid"])
            self.assertFalse(saved["redaction"]["result_changed"])


if __name__ == "__main__":
    unittest.main()
