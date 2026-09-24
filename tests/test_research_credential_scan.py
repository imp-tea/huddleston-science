import json
from pathlib import Path
import sys
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))
from scan_research_credentials import inspect_bytes


class CredentialScanTests(unittest.TestCase):
    def test_signed_url_is_detected_without_returning_secret_values(self):
        key = "AS" + "IA" + "X" * 16
        signature = "synthetic-sensitive-signature"
        url = "https://example.s3.amazonaws.com/file.pdf" + "?" + f"AWSAccessKeyId={key}&Signature={signature}&Expires=1"
        finding = inspect_bytes(json.dumps({"response": {"url": url}}).encode())
        self.assertEqual(finding["signed_urls_redacted"], 1)
        self.assertNotIn(key, json.dumps(finding))
        self.assertNotIn(signature, json.dumps(finding))

    def test_ordinary_authorization_notes_and_urls_are_unchanged(self):
        value = {"authorization": "User authorized this research batch.",
                 "url": "https://example.org/article?id=5&language=en"}
        self.assertIsNone(inspect_bytes(json.dumps(value).encode()))

    def test_bare_access_key_is_detected(self):
        key = "AK" + "IA" + "Z" * 16
        self.assertEqual(inspect_bytes(("credential: " + key).encode())["access_key_ids_redacted"], 1)


if __name__ == "__main__":
    unittest.main()
