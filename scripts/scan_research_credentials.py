"""Check versioned/staged files for credential material without printing values.

Run before committing research artifacts. Exit 1 means cleanup is required;
this scans the current files or index, not the repository's historical commits.
"""
import argparse
import json
from pathlib import Path
import subprocess

from research_redaction import sanitize_value

ROOT = Path(__file__).resolve().parents[1]


def inspect_bytes(raw):
    try:
        text = raw.decode("utf-8")
    except UnicodeDecodeError:
        return None
    try:
        value = json.loads(text)
    except ValueError:
        value = text
    clean, report = sanitize_value(value)
    if clean == value:
        return None
    return {key: report[key] for key in (
        "changed_fields", "signed_urls_redacted", "access_key_ids_redacted",
        "sensitive_fields_redacted")}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--staged", action="store_true", help="Scan the Git index instead of working files")
    args = parser.parse_args()
    command = ["git", "ls-files", "-z", "--cached"]
    if not args.staged:
        command += ["--others", "--exclude-standard"]
    paths = sorted(set(filter(None, subprocess.check_output(command, cwd=ROOT).decode().split("\0"))))
    findings = []
    checked = 0
    for relative in paths:
        path = ROOT / relative
        if args.staged:
            raw = subprocess.check_output(["git", "show", ":" + relative], cwd=ROOT)
        else:
            if not path.is_file() or path.is_symlink():
                continue
            raw = path.read_bytes()
        checked += 1
        result = inspect_bytes(raw)
        if result:
            findings.append({"path": relative, **result})
    print(json.dumps({"files_checked": checked, "affected_files": len(findings),
                      "findings": findings}, indent=2))
    raise SystemExit(bool(findings))


if __name__ == "__main__":
    main()
