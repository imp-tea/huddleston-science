# Huddleston Science website plan

Status: Overall direction approved by the repository owner. Milestone 1 is implemented and validated locally; deployment remains deferred.
Date: September 22, 2026

## Purpose

Build an engaging, personalized study platform for students participating in Scholars Bowl, emphasizing recognition and recall of basic facts and associations across broad subjects.

This repository will eventually support other classroom courses, clubs, activities, simulations, and educational resources. Build shared accounts, navigation, and styling now, while keeping Scholars Bowl functionality in its own module. Do not build empty course sections or a general-purpose learning management system.

The owner has a DigitalOcean droplet reserved for the site and has pointed `huddleston.science` at it. The repository has not yet been pulled onto the droplet. Develop and validate locally before deployment; do not assume server credentials, operating system, or capacity.

## Owner requirements

- Exactly one administrator account; only that administrator creates student accounts.
- No public registration page or public account-creation endpoint.
- The administrator manually supplies usernames and initial passwords.
- Students can change their usernames and passwords.
- No email, Google/social login, names, birth dates, or other requested identity fields.
- Persistent individual study history, quiz results, and category/subcategory progress.
- A satisfying, game-like Scholars Bowl experience.
- Navigation and application structure that can accommodate future sections.

Accounts and learning records are pseudonymous, not literally data-free. Keep them private to their owner and the administrator. Any mapping from accounts to real student names stays outside the site. Avoid unnecessary analytics and sensitive request logging.

## Existing repository baseline

The current site is static: plain JavaScript, HTML, CSS, and Python build/validation scripts. There is no backend, database, or authentication.

- `src/app.js`: category/subcategory/topic navigation using URL hashes.
- `src/topic.js`: topic descriptions, detailed study content, and source questions.
- `src/quiz.js`: random selection and choice shuffling.
- `src/quiz-dialog.js`: quiz interface and transient scoring.
- `data/`: authoritative educational content, taxonomy, questions, and attribution.
- `scripts/build.py`: validation and generated static output.
- `tests/`: content/build integrity and JavaScript quiz tests.
- `dist/`: generated, ignored output; never use it as the authoritative source.

Verified inventory at planning time:

- 12 primary categories and 355 subcategories.
- 7,072 category-specific topic pages representing 6,906 shared subjects.
- 1,006 detailed study pages.
- 10,976 practice questions; every topic has at least one.
- 4,971 topics have only one practice question.

Current quizzes randomly select up to ten questions, shuffle choices, show brief correct/incorrect feedback, and discard results. The interface does not display the explanations already present in the question data. Individual topic pages do not currently offer quizzes.

Preserve stable `study_topic_id`, `subject_id`, `question_id`, subcategory IDs, source references, redirects, and attribution. Question-local IDs such as `q1` are not globally unique; use `question_id` for persistence. Shared subjects and category-specific study topics are distinct concepts.

## Student experience

After login, make Scholars Bowl immediately accessible. Its dashboard provides:

1. **Start practice:** A short session mixing new material, weaker questions, and scheduled reviews.
2. **Explore topics:** Search/browse categories and subcategories and choose study material freely.
3. **My progress:** Study history, recent results, personal bests, and topics to revisit.

Offer a concrete next action rather than presenting thousands of topics without guidance. Students can always choose their own study scope; recommendations do not restrict access.

Core loop: learn a few associations, answer questions, understand mistakes, see progress, and return for review.

### Practice modes

- **Recognition:** Multiple choice using the existing question bank. Implement first.
- **Recall:** Hide choices, let the student think, reveal the answer, and record self-assessment separately from objectively scored results.
- **Challenge:** A scored set within a category, subcategory, or mixed selection, with comparable personal bests.

Typed-answer grading is deferred. It needs an explicit approach to spelling, aliases, surnames, and alternate answers; topic aliases alone are insufficient.

During feedback, retain the question, identify the correct answer, display its explanation, and provide an explicit Continue action. Include a route to the relevant study page. Do not force the student to read explanations on a one- or two-second timer.

Provide clear empty/loading/error states, keyboard navigation, visible focus, mobile layouts, accessible feedback, and reduced-motion support. Sound is optional and controllable.

## Progress and learning model

Keep these measures separate:

| Measure | Records and meaning |
| --- | --- |
| Study history | Opened topics, explicitly marked-studied topics, last visit |
| Practice results | Individual answers, session scores, dates, scope, mode, personal bests |
| Review readiness | Evidence of recall across separate sessions and next review timing |

Suggested topic labels: New, Studied, Practicing, Remembered across reviews. Review due is a separate scheduling indicator. Opening a page never establishes mastery.

Category/subcategory summaries show studied/practiced coverage, recent accuracy with sample size, comparable personal bests, and review counts. Display scores with denominators and modes. A 3/3 result must not automatically outrank 9/10. A perfect sampled quiz must not mark a whole category mastered.

Most topics currently have one question. Repeating that question demonstrates recall of its association, not broad mastery of the subject. Use honest labels and leave room for future question variety. Do not automatically award progress on every related category page merely because it shares a `subject_id`.

Start review scheduling with an understandable, deterministic rule: successful reviews on separate days extend intervals; mistakes shorten them. Immediate retries are useful practice but not independent evidence of lasting recall. Document exact intervals and thresholds when implemented; no particular algorithm or interval sequence has been approved yet.

Track enough information to distinguish first attempts, retries, recognition, self-assessed recall, completed challenges, and abandoned sessions. Version relevant content so edits do not silently change the meaning of historical results. Aggregate overlapping subcategories without double-counting the same answer in a category total.

## Game-like feedback

Default to private individual progress until the owner chooses otherwise. Student age range, expected account count, and appetite for competition remain unspecified; these need not block foundational implementation.

Initial features:

- Consistent category colors/icons and a polished visual identity.
- Responsive answer feedback and restrained celebrations.
- Visible session progress and a clear finish line.
- Personal best celebrations and useful summaries such as previously missed answers remembered.
- Category badges tied to breadth and successful reviews.
- Flexible weekly practice goals.
- A small XP system rewarding new learning and useful review, with reduced rewards for repeated farming of the same question.

XP reflects participation; learning indicators reflect demonstrated recall. Keep all educational content accessible regardless of XP. Persist reward events safely so refreshes/retries cannot award duplicates.

Defer public leaderboards, competitive multiplayer, complex currencies, elaborate unlock systems, and punitive daily streak mechanics until the core experience has been tried by students.

## Accounts and administration

- Bootstrap one administrator through a documented setup command, with no committed credentials or default public password.
- Enforce the single-administrator requirement beyond merely hiding promotion controls.
- Administrator creates students with unique temporary passwords and can reset, disable, or delete their accounts.
- Require a password change at first login and following an administrator reset.
- Students can change their own username and password; username changes preserve all progress through an immutable internal account ID.
- Provide a stable, non-identifying account code for administrator recognition after username changes.
- Forgotten credentials are recovered through the administrator, without email or security questions.
- Administrator can inspect student progress; students can only access their own records.
- Document administrator recovery through server access.

Use established framework password hashing and authentication, secure HttpOnly cookie sessions, CSRF protection, HTTPS in production, login throttling, and server-side authorization. Do not trust client-supplied scores, account IDs, roles, or XP totals. Invalidate relevant sessions on reset/disable. Never store readable passwords or put session tokens in localStorage.

## Site structure

| Route | Purpose |
| --- | --- |
| `/` | Classroom home and section navigation |
| `/login/` | Login |
| `/account/` | Username and password settings |
| `/scholars-bowl/` | Dashboard, library, practice, and progress |
| `/admin/` | Administrator account/progress tools |

Initially show Home, Scholars Bowl, and Account, plus Admin for the administrator. Add future sections only when useful content exists. Use login-required student experiences by default; whether the educational library should also have public read-only access remains an optional future decision.

## Recommended architecture

Use Django with PostgreSQL, keeping useful existing JavaScript and the educational content pipeline. Django supplies established authentication, password handling, permissions, migrations, and administration. Define a custom user model at the start that omits unnecessary identity fields. No separate frontend framework or API service is required merely to add accounts.

Keep the educational JSON files authoritative initially. Implement a repeatable, validated import into database models, preserving stable IDs and attribution. Importing updated content must not erase student history; retire or version removed/changed content deliberately. Avoid two independent content editing sources.

Separate shared accounts/site functionality from the Scholars Bowl module. Anticipated records include users, topics/questions and revisions, study events or state, practice sessions, answer attempts, review state, and reward events. Exact schema and framework version are implementation decisions; use a supported release and record dependency versions.

The server selects/records scored sessions and determines correctness and rewards. Save answers as they happen. Make writes idempotent so retries, double clicks, or multiple tabs cannot double-count results. Distinguish incomplete sessions from completed personal-best candidates. Persist progress across browser sessions and devices.

Do not add AI generation services, third-party identity providers, or external tracking. They are not required for this plan.

## Implementation sequence

### Milestone 1: Foundation and one complete student journey

**Implementation status — September 22, 2026:** Implemented locally with Django 5.2.17 LTS and PostgreSQL. The authoritative data and original static implementation remain intact. See `README.md` for reproducible setup, import, administrator bootstrap/recovery, and validation commands.

Implemented:

- Shared Home, Scholars Bowl, Account, and administrator navigation with responsive server-rendered pages.
- Custom UUID accounts with only pseudonymous usernames, credentials, status, and account metadata; no email or personal identity fields and no public registration.
- Administrator bootstrap/recovery commands; database uniqueness and a PostgreSQL trigger enforce one administrator after bootstrap and prevent deletion, demotion, or disabling. Student account creation, resets, disabling/re-enabling, confirmed deletion, and result inspection are available through `/admin/`.
- Unique temporary passwords, enforced first-login/reset password replacement, student username/password settings, immutable account codes, session invalidation, CSRF protection, private-page cache controls, and database-backed login throttling.
- Atomic, validated, repeatable imports preserving all original content payloads, IDs, shared subject identities, memberships, sources, redirects, attribution, and revision metadata. Destructive omissions require explicit `--allow-retire`; retirement never deletes results. Question revisions include study/source context and remain pinned to existing sessions.
- Server-selected and server-scored recognition quizzes for mixed/category/subcategory/topic scopes. Up to ten distinct questions, saved shuffled choices, per-answer persistence, completion timestamps, idempotent starts and answers, resumable unfinished sessions, and owner/administrator result access.
- Explanations remain visible until Continue, with current study-page links and historical source snapshots. A minimal searchable library and results list support the first journey; these intentionally bring forward just the navigation/feedback needed from Milestone 2.

Validated:

- PostgreSQL migrations and Django system checks; no pending model changes.
- Backend tests exercise authorization, single-administrator database protection, first-login enforcement, resets/disabling, username continuity, session invalidation, CSRF, throttling, server scoring, cross-device persistence, interrupted sessions, small pools, duplicate and concurrent submissions, import validation/rollback, revision safety, and retirement.
- Full-dataset import run twice in tests, checking exact content and attribution preservation, taxonomy and membership equality, and original counts: 12 categories, 355 subcategories, 7,072 topics / 6,906 subjects, 1,006 detailed pages, 10,976 questions, 4,383 source units, and 13 redirects.
- Original static build/content and JavaScript quiz tests are retained and pass. Final test totals and browser verification are recorded in the milestone validation note below.

Deferred:

- Study visit/marked-studied tracking, category/subcategory progress aggregates, personal bests, review readiness/scheduling, recall mode, rewards/XP/badges/goals, and richer game feedback. No mastery inference or rewards are applied to these recognition results.
- Incomplete sessions are retained as resumable sessions; explicit abandonment/expiry policy remains deferred. Each new session is separate, without yet interpreting repeated questions as scheduled recall evidence.
- DigitalOcean deployment, HTTPS/proxy configuration, production request throttling tuning, operational housekeeping scheduling, backup/restore verification, and a student pilot. Secure-cookie/HTTPS defaults exist, but no production launch is claimed.

No implementation blocker remains for local Milestone 1. The administrator must choose their own credentials using the setup command; no live classroom credentials are seeded.

**Final local validation:** 45 Django/PostgreSQL tests, 5 original Python content/build tests, and 3 original JavaScript tests passed. Django system checks, migration drift checks, and `git diff --check` passed. Validation ran with Python 3.14.6 and PostgreSQL 17.11. Headless Chrome exercised account creation → temporary-password replacement → ten-question completion → username change → logout → the same saved results on a separate mobile browser context. Additional keyboard checks passed with JavaScript disabled, reduced motion enabled, and a 320px viewport. Desktop/mobile screenshots were visually inspected. Browser-test accounts and their separate database were removed afterward; the main local database retains the imported corpus and no seeded accounts.

Deliver shared navigation, backend/database setup, custom accounts, administrator tools, content import, and persistent multiple-choice quiz history.

The first vertical slice must work end to end:

> Administrator creates account → student logs in → student changes temporary password → student completes quiz → saved results remain available after logout and from another browser session/device.

Acceptance checks:

- No public registration or unauthorized account creation.
- One administrator; student privilege escalation and cross-account reads/writes are rejected server-side.
- Username changes preserve history; reset/disable behavior works.
- Existing content IDs, counts, references, and attribution survive import.
- Import is repeatable without duplicate content or lost progress.
- Quiz selection and scoring work for both ten-question and smaller pools.
- Duplicate submissions do not duplicate answers or rewards; interrupted quizzes preserve completed answers.
- Local setup, migrations, import, administrator bootstrap, and test commands are documented and reproducible.

### Milestone 2: Engaging practice

Deliver the dashboard, searchable/browsable library, explicit study markers, better feedback, progress summaries, comparable personal bests, and initial visual/reward polish.

Acceptance checks:

- Students can immediately identify a next action and freely select another scope.
- Explanations remain readable until the student continues.
- Studied status, quiz accuracy, and XP are distinct.
- Short quizzes and differing modes are not misleadingly compared.
- Core flows work on narrow screens and using a keyboard; animations respect reduced motion.

### Milestone 3: Personalization and launch preparation

Deliver review scheduling, self-assessed recall mode, more informative progress summaries, deployment configuration/documentation, and a small student pilot when the owner is ready.

Acceptance checks:

- Review scheduling behaves predictably across days and repeated attempts.
- Self-assessed recall does not inflate objectively scored personal bests.
- Content revisions and overlapping classifications do not corrupt progress.
- Production settings, HTTPS, migrations, persistent storage, backups, and restore procedure are documented and verified as appropriate to the available environment.
- Update and rollback instructions distinguish application releases from persistent student data.

The droplet can run the application and PostgreSQL behind an HTTPS reverse proxy. Keep database/secrets outside generated output and Git. Include automated backups and a restore check before depending on the site for student history. Obtain actual server details when deployment becomes the active task; do not invent them or claim deployment has occurred.

## Guidance for implementation agents

Read this plan, `README.md`, and applicable `AGENTS.md` instructions before changes. Inspect the repository rather than assuming the planning baseline is still current. Preserve unrelated work.

Begin with Milestone 1. Complete and test the vertical slice before spreading effort across rewards, dashboards, and review algorithms. Avoid a wholesale rewrite of educational content or unrelated tooling. Make ordinary implementation choices autonomously and document material deviations or blockers.

Retain appropriate existing tests and add meaningful coverage for authentication/authorization, persistence, import safety, scoring, and duplicate submissions. Run the relevant checks and report actual results. Update `README.md` to replace obsolete static-only setup claims once the backend exists. Update milestone status in this document as work lands, explicitly distinguishing implemented, tested, and deferred features.

## Technical references

- Django authentication: https://docs.djangoproject.com/en/5.2/topics/auth/default/
- Django custom authentication/user models: https://docs.djangoproject.com/en/5.2/topics/auth/customizing/
- OWASP authentication guidance: https://cheatsheetseries.owasp.org/cheatsheets/Authentication_Cheat_Sheet.html

These informed the architecture discussion; select and verify the supported dependency versions at implementation time rather than treating the reference URLs as a version pin.
