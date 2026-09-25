# Repository and production release boundaries

The repository contains application source plus development and operational
tools. The preferred production workflow uses a permanent Git checkout; see
[the update guide](../UPDATE_DEPLOYMENT.md). The optional
`scripts/package_release.py` creates the explicit runtime subset described below.

| Files | Keep in Git | Include in release package | Purpose |
| --- | --- | --- | --- |
| `classroom/`, `accounts/`, `scholars/` runtime Python and migrations | Yes | Yes | Django application, database schema, administrative commands |
| `templates/`, `static/` | Yes | Yes | Current classroom interface |
| `data/` | Yes | Yes | Authoritative educational content and repeatable imports |
| `manage.py`, requirements files, `deploy/` | Yes | Yes | Runtime dependencies, server configuration, backup/housekeeping tools |
| `scripts/build.py`, `scripts/typed_content.py`, `ATTRIBUTION.md`, deployment guides | Yes | Yes | Import validation, attribution page, operator instructions |
| Tests, test settings, fixtures, benchmarks | Yes | No | Regression checks on development machines/CI |
| Research, normalization, and credential-scanning scripts | Yes | No | Maintain future content safely |
| `src/`, `public/`, `scripts/serve.py`, `package.json` | Yes | No | Preserved static preview and JavaScript development tooling |
| README, planning, first-installation, and maintenance docs | Yes | No | Project development and deployment preparation |
| `research/` | No; local copies retained | No | Queues, drafts, API responses, review history, costs |
| `.env`, `.venv/`, `.local/`, `dist/`, `staticfiles/` | No | No | Local secrets, dependencies, database, generated output |

Tests and migration history serve different purposes: migrations are necessary
to create and upgrade the production database, so they remain in every release.
The server also needs `scripts/build.py` and `scripts/typed_content.py` because the content importer calls its
validator, even though the legacy static site itself is not deployed.

## Create a release

Commit the reviewed changes first. The packager reads a committed Git revision,
not unstaged or untracked files:

```sh
release_id=$(git rev-parse --short=12 HEAD)
python3 scripts/package_release.py --ref HEAD \
  --output ".local/releases/huddleston-$release_id.tar.gz"
```

An existing output file is never overwritten. Reuse a previously verified archive
or choose a different filename. `--ref` can select a reviewed tag or commit.

The archive contains regular files only and includes `RELEASE.json` with the
source commit and SHA-256 for every packaged file. It preserves executable bits
for the production management wrapper. It excludes Git history, research, test
code, development settings, local environments, credentials, and the legacy UI.
It also refuses a release missing required runtime dependencies. New runtime
file types or entry points need a reviewed allowlist update.

The package is ready to extract into a new versioned release directory; follow
[first installation](../FIRST_DEPLOYMENT.md) or
[updates and rollback](../DEPLOYMENT.md). Production secrets, the PostgreSQL
database, backups, and collected static files stay outside release archives.
Packaging performs no deployment, migrations, database import, or remote writes.

Validation on September 24, 2026: 42 Python tests passed in a clean source copy
without `research/`; 9 JavaScript and 15 Django importer/production tests passed.
A package of the current committed application contained 108 source files and
was about 5.9 MB compressed. In isolation it passed Django production checks
(only the two already documented HSTS warnings), collected all three static
assets, loaded migration modules, and validated all 7,072 topics, 2,335 detailed
pages, and 10,976 questions without the development or research directories.
