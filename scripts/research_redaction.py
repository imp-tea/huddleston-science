"""Remove web-result signing credentials before research records reach disk.

The sanitizer is deterministic and leaves records with no signing material
unchanged. It preserves ordinary URL host, path, fragment, and query fields.
"""

import json
import re
from urllib.parse import unquote_plus, urlsplit, urlunsplit


POLICY = "aws-research-url-v1"
URL = re.compile(r"https?://[^\s<>\"'\\]+", re.I)
# Constructed from pieces to avoid checking a live-looking credential into code.
ACCESS_KEY = re.compile(r"(?:" + "|".join(("AK" + "IA", "AS" + "IA", "AG" + "PA",
                                           "AI" + "DA", "AN" + "PA", "AN" + "VA",
                                           "AI" + "PA", "AR" + "OA")) + r")[A-Z0-9]{16}")
SENSITIVE_FIELDS = {"authorization", "api_key", "apikey", "access_token", "id_token",
                    "session_token", "security_token", "secret_access_key", "awsaccesskeyid",
                    "aws_secret_access_key", "aws_session_token", "x-amz-credential",
                    "x-amz-security-token"}
LEGACY_SIGNING = {"awsaccesskeyid", "securitytoken", "security-token", "signature", "expires"}


def _query_key(part):
    key = unquote_plus(part.split("=", 1)[0]).lower()
    return key.removeprefix("amp;")


def _sensitive_field(key, item, path):
    name = str(key).lower()
    if name not in SENSITIVE_FIELDS or item in (None, "", "[REDACTED_SECRET]"):
        return False
    if name == "authorization":
        header = path and path[-1].lower() in ("headers", "http_headers")
        scheme = isinstance(item, str) and re.match(r"^(?:Bearer|Basic|AWS4-HMAC-SHA256|AWS|Token)\s", item, re.I)
        return bool(header or scheme)
    return True


def _clean_url(url):
    parsed = urlsplit(url)
    if not parsed.query:
        return url, False
    parts = parsed.query.split("&")
    keys = [_query_key(part) for part in parts]
    host = (parsed.hostname or "").lower()
    aws_signed = any(key.startswith("x-amz-") or key in ("awsaccesskeyid", "securitytoken",
                                                       "security-token") for key in keys)
    aws_signed |= ("amazonaws.com" in host or "cloudfront.net" in host) and any(
        key in ("signature", "expires", "key-pair-id", "policy") for key in keys)
    if not aws_signed:
        return url, False
    retained = [part for part, key in zip(parts, keys) if not (
        key.startswith("x-amz-") or key in LEGACY_SIGNING or
        ("cloudfront.net" in host and key in ("key-pair-id", "policy")))]
    cleaned = urlunsplit((parsed.scheme, parsed.netloc, parsed.path, "&".join(retained), parsed.fragment))
    return cleaned, cleaned != url


def _clean_string(value, path, report):
    # Some API fields contain structured JSON as a string (notably output_text).
    stripped = value.lstrip()
    if stripped.startswith(("{", "[")):
        try:
            embedded = json.loads(value)
        except ValueError:
            embedded = None
        if isinstance(embedded, (dict, list)):
            cleaned = _walk(embedded, path, report)
            if cleaned != embedded:
                return json.dumps(cleaned, ensure_ascii=False)

    def replace_url(match):
        candidate = match.group()
        # Keep punctuation adjacent to a URL in prose outside the URL itself.
        tail = candidate[len(candidate.rstrip(".,;!)]}")) :]
        core = candidate[:-len(tail)] if tail else candidate
        cleaned, changed = _clean_url(core)
        if changed:
            report["signed_urls_redacted"] += 1
        return cleaned + tail

    cleaned = URL.sub(replace_url, value)
    cleaned, count = ACCESS_KEY.subn("[REDACTED_ACCESS_KEY]", cleaned)
    report["access_key_ids_redacted"] += count
    if cleaned != value:
        report["changed_fields"] += 1
        if path and path[0] == "result":
            report["result_changed"] = True
            if "source_urls" in path or ("sources" in path and "url" in path):
                report["citation_urls_changed"] = True
    return cleaned


def _walk(value, path, report):
    if isinstance(value, dict):
        result = {}
        for key, item in value.items():
            child = path + (str(key),)
            if _sensitive_field(key, item, path):
                result[key] = "[REDACTED_SECRET]"
                report["sensitive_fields_redacted"] += 1
                report["changed_fields"] += 1
                if path and path[0] == "result":
                    report["result_changed"] = True
            else:
                result[key] = _walk(item, child, report)
        return result
    if isinstance(value, list):
        return [_walk(item, path + (str(index),), report) for index, item in enumerate(value)]
    if isinstance(value, str):
        return _clean_string(value, path, report)
    return value


def sanitize_value(value):
    """Return a redacted deep copy and non-secret redaction counts."""
    report = {"changed_fields": 0, "signed_urls_redacted": 0, "access_key_ids_redacted": 0,
              "sensitive_fields_redacted": 0, "result_changed": False,
              "citation_urls_changed": False}
    return _walk(value, (), report), report


def sanitize_record(record):
    """Sanitize a saved research record and mark changed generated content for repair."""
    clean, report = sanitize_value(record)
    if report["changed_fields"]:
        clean["redaction"] = {"policy": POLICY, **report}
        if report["result_changed"]:
            validation = clean.setdefault("validation", {"valid": False, "errors": [], "warnings": []})
            validation["valid"] = False
            errors = validation.setdefault("errors", [])
            message = "Generated result contained redacted credential material; verify stable sources/content before acceptance"
            if message not in errors:
                errors.append(message)
    return clean
