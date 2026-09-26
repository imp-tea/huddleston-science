"""Build and serve the isolated visual prototype from authoritative content.

No Django/database access, accounts, answer keys, or external dependencies.
Only generated preview assets are served, on loopback by default.
"""
import argparse
import html
import json
import shutil
from functools import partial
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
SOURCE = Path(__file__).resolve().parent
OUTPUT = ROOT / ".local" / "scholars-preview"


def build():
    taxonomy = json.loads((ROOT / "data/taxonomy.json").read_text())
    topics = json.loads((ROOT / "data/topics.json").read_text())
    content = json.loads((ROOT / "data/content.json").read_text())
    catalog = {"categories": [c["primary_category"] for c in taxonomy["categories"]],
               "subcategories": taxonomy["subcategories"], "topics": []}
    for topic in topics:
        study = content.get(topic["study_topic_id"], {})
        source = study.get("source", {})
        catalog["topics"].append({
            "id": topic["study_topic_id"], "title": topic["topic"],
            "category": topic["primary_category"], "subcategories": topic["subcategory_ids"],
            "description": topic["description"], "overview": study.get("overview", []),
            "facts": study.get("key_facts", []),
            "references": source.get("references", [source] if source else []),
        })
    OUTPUT.mkdir(parents=True, exist_ok=True)
    for name in ("index.html", "preview.css", "preview.js"):
        shutil.copyfile(SOURCE / name, OUTPUT / name)
    (OUTPUT / "catalog.json").write_text(json.dumps(catalog, ensure_ascii=False))
    credits = html.escape((ROOT / "ATTRIBUTION.md").read_text())
    (OUTPUT / "attribution.html").write_text(
        '<!doctype html><html lang="en"><meta charset="utf-8">'
        '<meta name="viewport" content="width=device-width,initial-scale=1">'
        '<title>Content attribution</title><link rel="stylesheet" href="preview.css">'
        '<main class="attribution"><a href="/">← Scholars Bowl preview</a>'
        '<h1>Content attribution</h1><pre style="white-space:pre-wrap;font:inherit">'
        + credits + '</pre></main></html>')
    print(f"Built preview: {len(topics):,} topics → {OUTPUT}", flush=True)


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--port", type=int, default=8877)
    parser.add_argument("--build-only", action="store_true")
    args = parser.parse_args()
    build()
    if not args.build_only:
        server = ThreadingHTTPServer(("127.0.0.1", args.port),
                                     partial(SimpleHTTPRequestHandler, directory=str(OUTPUT)))
        print(f"Preview: http://127.0.0.1:{args.port}", flush=True)
        try:
            server.serve_forever()
        except KeyboardInterrupt:
            server.server_close()
