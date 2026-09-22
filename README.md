# Huddleston Science — quiz bowl study site

A self-contained static website for browsing quiz bowl topics and practicing recall. No API key, database, account system, package installation, or generation service is required.

## Run locally

Requires Python 3.10 or newer:

```sh
python3 scripts/serve.py
```

Open http://127.0.0.1:8766. The preview serves only the generated `dist/` directory and binds to localhost. Re-run after editing data or website files; refresh the browser. Use `--port 8767` to choose another port.

## Build and host

```sh
python3 scripts/build.py
```

Publish the **contents of `dist/`** to a static host. This directory is the complete website; the repository root is not the deployment directory. The site uses relative asset URLs and hash navigation, so it also works under a repository subpath without server-side route rewrites. `.nojekyll` is included for GitHub Pages compatibility. No hosting service or deployment workflow is configured yet.

`dist/` is generated and ignored by Git. Category detail, practice, and source files have content hashes in their filenames. The browse index identifies the matching files for that build. Deploy the directory as one complete snapshot.

## Repository layout

- `src/`: browser interface, topic rendering, data loading, and quiz modules; plain JavaScript, HTML, and CSS.
- `data/topics.json`: topic identity, aliases, descriptions, memberships, source IDs and counts, and school-level metadata.
- `data/taxonomy.json`: primary categories and subcategory definitions. Counts are computed at build time.
- `data/content.json`: overview and key-fact blocks, keyed by topic ID, with source attribution and revision metadata.
- `data/practice/`: final corrected questions, grouped by primary category. Includes explanations, evidence references, and canonical answer identities. Display choices already have type labels removed.
- `data/sources.json`: tournament source units, preserving complete bonus lead-ins and parts.
- `data/topic-redirects.json`: older topic IDs mapped to current identities.
- `data/import-manifest.json`: initial migration counts and hashes, for provenance; not a runtime dependency.
- `scripts/`: validation, static build, and local preview only.
- `tests/`: dataset integrity, export preservation, scoped selection, choice shuffling, and lazy-loading tests.
- `public/`: additional files copied into the deployable site.

## Data and editing

The initial transfer contains 12 primary categories, 355 subcategories, 7,072 category-specific topics representing 6,906 shared subjects, 1,006 detailed study pages, 10,976 practice questions, and 4,383 tournament source units. Topics in different primary categories remain separate study pages; shared `subject_id` values connect them.

Edit the authoritative files under `data/`, then rebuild. Preserve existing topic, question, source, and subcategory IDs. Topic `source_ids` refer to keys in `sources.json`; practice `study_topic_id` refers to a topic. Practice `evidence_ids` refer to `description`, a source-question ID, or an overview/key-fact block ID on that topic. No reference requires access to the former processing project. The build rejects broken references, invalid category membership, incomplete bonus groups, duplicate choices, and invalid question counts.

The initial import stripped redundant subcategory names, processing statuses, run names, old CSV filenames, and internal extraction-evidence markers from study prose. It preserved prose, citations, metadata, question IDs, explanations, evidence links, and canonical/display answers. The original processing archive remains separate and unchanged.

Startup loads a roughly 1.66 MB browsing index. Topic details load by category when a topic is opened; source questions load in small ID-prefix shards on demand. Quizzes fetch only relevant category files, except an all-category quiz, which uses all question files.

## Quizzes

**Quiz Me!** appears on the overview, primary categories, and subcategories, but not individual topic pages. Each quiz samples up to ten distinct questions with independently shuffled choices. Correct/incorrect feedback precedes the next question, then the score appears. Smaller pools use all available questions and their actual denominator. Close or Escape cancels; Quiz again starts fresh. Scores are not stored.

## Tests

Python tests rebuild the deployable site. JavaScript tests require Node.js 18 or newer and no installed packages:

```sh
python3 -m unittest discover -s tests
node --test tests/quiz.test.js
```

The initial-count regression test uses `data/import-manifest.json`; when intentionally expanding the dataset, update that expectation rather than silently accepting accidental losses. `dist/build-info.json` reports the latest build's counts.

## Attribution

See [ATTRIBUTION.md](ATTRIBUTION.md) and the source links displayed on individual topic pages. Source-specific license information remains with the data. No blanket license is asserted for third-party tournament questions.

Credentials, original CSV inputs, model prompts, API requests/responses, processing programs, logs, and intermediate review artifacts are intentionally excluded. `.gitignore` protects local environment files and generated output.
