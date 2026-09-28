# Database-owned question bank

Questions now belong to PostgreSQL. The repository holds application code,
initial seed data, and reproducible analysis artifacts. A normal `import_content`
updates study material and taxonomy only; it never inserts, edits, archives,
reactivates, or changes a question revision. It also refuses to retire a topic
with active questions, even with `--allow-retire`. Archive its questions explicitly
before retiring that topic. Original tournament sources remain repository-managed.

Migration `0012_database_owned_questions` removes the three imported/override
pointers while retaining every current revision, historical revision, stable ID,
active state, and existing session/list reference. The old pointer relationships
are copied into audit history before the columns are removed. Origin remains provenance only.
It adds indexed difficulty (`easy`, `medium`, `hard`, or unrated), assessment
provenance, and a question-change audit table. Content revisions remain immutable.
Changing a stem or answer in the site editor clears the previous rating; save
wording first, then assign a new rating. All questions support archive/restore.

Difficulty is stored and displayed in teacher tools. Quiz Creator's random
generator now offers a draggable Easy/Medium/Hard triangle, initially an equal
split, plus numeric weights. Whole-question targets use largest-remainder
rounding. Generation first satisfies the requested count and existing
category/topic/duplicate constraints, then improves the difficulty mix through
valid question exchanges. This is a best-effort target, not a guarantee of the
closest mathematically possible mix. Balanced category shares take priority;
choose whole-pool sampling to remove that restriction. Unrated questions may
fill remaining places and appear separately in the preview. The preview shows
target and actual difficulty counts. Study quiz selection is unchanged.

The generator's subcategory checklist follows selected categories and clears
selections when their category is unchecked. This generator update needs no new
database migration: deploy the code, collect static files, and restart normally;
do not reapply the one-time difficulty import.

## Existing-server cutover

Do this once during maintenance after committing/pushing this release. Use the
existing `UPDATE_DEPLOYMENT.md` backup and checkout procedure. Stop the application
before migrating and keep it stopped through verification. Take a full database
backup and retain the matching pre-upgrade application commit. This is a forward
cutover: do not run the old application/importer against the new schema or reverse
the migration to roll back. Restore the matched database/application backup if a
rollback is necessary.

From `/srv/huddleston/app`, using the existing deployment environment wrapper:

```sh
sudo -u huddleston ./deploy/manage migrate --plan
sudo -u huddleston ./deploy/manage migrate --noinput
sudo -u huddleston ./deploy/manage adopt_question_bank
```

The last command is a **read-only preview**. It checks every assessment's frozen
question/answer fingerprint. It accepts the exact known old I. M. Pei wording and
plans a new corrected revision before matching that assessment. No other wording
is replaced from the repository. Missing identities, changed content, or a
conflicting existing rating abort the whole operation. Extra database questions
are reported and left unrated; site-authored questions are never deleted.

For the expected existing full bank, the preview reviews 26,923 assessments. It
plans one Pei correction if the server still has the old wording (zero if already
fixed), and 26,923 rating changes on the first application. Then run:

```sh
sudo -u huddleston ./deploy/manage adopt_question_bank --apply
sudo -u huddleston ./deploy/manage adopt_question_bank
sudo -u huddleston ./deploy/manage import_content
sudo -u huddleston ./deploy/manage check
sudo -u huddleston ./deploy/manage collectstatic --noinput
```

The second preview must show **zero changes**, no conflicts, and the same assessed
count. A conflict requires inspection; do not work around it by reseeding or
replacing the database. Restart using the existing deployment instructions.
Verify administrator editing, difficulty display, archive/restore, an existing
saved quiz/report, an unfinished session, and a new Study session. Existing
sessions continue to use their original questions and grading banks.

## New installations

Bootstrap an empty bank explicitly, then load the checked classifications:

```sh
python manage.py migrate
python manage.py import_content --seed-questions
python manage.py adopt_question_bank
python manage.py adopt_question_bank --apply
```

Seeding refuses a nonempty bank. Ordinary deployments run only `import_content`
without `--seed-questions`. The repository's question JSON files can be retained
as seed/reference artifacts; they are not a synchronization source.

## Local analysis and bulk editing

Export the current server bank to a new private file:

```sh
sudo -u huddleston ./deploy/manage export_question_bank /path/to/new-bank.json
```

Use `--history` to include all revision context and change history. The old
`export_teacher_questions` command remains an alias for a **complete** export
with history. Neither export includes student records; full database backups
remain the recovery mechanism. Copy the export to your local analysis workspace
with your normal secure transfer process. Keep downloaded bank snapshots and
raw analysis in ignored `research/`, not as a second authoritative source.

Each exported question contains `question_id`, `edit_version`, `source_sha256`,
`question`, `answer`, `difficulty`, active state, category, and its full payload.
Prepare a separate patch file. Use IDs, versions, and hashes from that export:

```json
{
  "schema_version": 1,
  "updates": [
    {
      "question_id": "ID_FROM_EXPORT",
      "edit_version": 3,
      "source_sha256": "HASH_FROM_EXPORT",
      "difficulty": "hard"
    }
  ]
}
```

Only supplied fields change. Supported changes are `difficulty`, `active`,
`question`, `answer`, and (for multiple-choice questions) `distractors` as a list
and `explanation`. A difficulty supplied alongside new wording explicitly rates
that new wording; otherwise changed wording/answers clear the old assessment.
Identity, topic, and format cannot be changed through this patch format. New
questions are created through the site's authoring tools.

Copy the patch back to the server and preview it as an existing administrator:

```sh
sudo -u huddleston ./deploy/manage apply_question_updates /path/to/patch.json --author ADMIN_USERNAME
sudo -u huddleston ./deploy/manage apply_question_updates /path/to/patch.json --author ADMIN_USERNAME --apply
```

Preview reports the change count and up to 20 before/after examples. It performs
all validation without writes. Apply repeats the checks in one transaction under
the same lock as site editing. One stale version, source mismatch, duplicate ID,
or invalid value rejects the entire patch. Export again and review conflicts;
do not replace version/hash tokens blindly. Successful writes retain an audit
record and preserve historical session evidence. Replaying an old applied patch
is rejected as stale, preventing accidental overwrites.

## Local validation (2026-09-27)

The complete Django suite passed: 249 tests across `accounts`, `scholars`, and
`classroom`. This includes a full 26,923-question seed and difficulty adoption,
read-only preview, repeat application with zero changes, preservation of session
references, and migration of an edited archived question with its old provenance.
The nine focused ownership tests passed again after expanding bulk previews to
show answer changes. Django system checks, migration consistency checks, and
`git diff --check` passed.

The separate offline research suite ran 77 tests with three failures and one
error. All four were reproduced with the committed code: enrichment recovery
expects unfinished enrichment, and three typed-pilot assertions expect the older
partially enriched dataset's sample sizes. These existing failures are unrelated
to the database cutover. Production migration and smoke checks remain deployment
steps; no server changes were made during preparation.
