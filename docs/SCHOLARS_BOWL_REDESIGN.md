# Scholars Bowl redesign

Approved direction: September 25, 2026. This document is the durable plan for
future implementation. It supersedes conflicting student-experience guidance
in WEBSITE_PLAN.md and the existing README (including the old minimal styling,
immediate answer feedback, manually marked study state, XP, and question goals).

## Product direction

Make Scholars Bowl fun, visually expressive, and simple. Use a modern academic
design: warm charcoal background, light paper cards, muted gold accents, serif headings,
subtle category colors and motifs, and purposeful motion. Keep page copy
functional: no hero sections, slogans, or decorative taglines. The header brand
is `huddleston.science`. Clear keyboard focus, readable text,
mobile layouts, and reduced-motion support are required throughout.

The landing page has three large cards, with these exact labels and subtitles:

- **Study** — Learn a few random topics and take a quiz!
- **Progress** — See your learning progress!
- **Explore** — Freely explore the full data set!

Typed answers are confirmed. Existing short topic descriptions are accepted
as-is; the owner will expand them separately. Content enrichment must NOT block
this redesign, exclude short-description topics, or become an implicit task.

## Preferences and onboarding

- First Scholars Bowl visit asks which of the 12 primary categories interest
  the student. Require at least one; provide Select all.
- Account contains the same category selector for later changes.
- Selected categories determine future personalized study choices. Explore
  always contains the full dataset.
- Changing interests preserves completed topics and the current session;
  updated interests apply to the next selection.
- Preferences and onboarding completion eventually persist on the account,
  across browsers/devices. Browser-only prototype state is not the final model.

## Study flow

1. If a session is unfinished, offer Resume Previous Session or Start New
   Session. Explain that starting over clears only that unfinished session's
   progress, not previously earned topic completions. Abandon the old session
   atomically; prevent stale tabs from continuing it.
2. Otherwise ask: **What do you want to learn about today?**
3. Show ten random, distinct subcategories from selected primary categories,
   excluding those with no remaining topics. Each card shows its parent category,
   title, completion percentage, and proportional visual fill.
4. A Reroll control above the subcategory cards supplies ten new choices. Avoid immediately repeated
   choices where the pool permits; show fewer cards when fewer are available.
5. Choose five distinct, random, uncompleted topics from the chosen subcategory.
6. Read one topic card at a time, with overview/key facts where available and the
   existing short description otherwise. No tournament source questions on cards.
   Keep content attribution accessible through a secondary link.
7. Show Topic 1 of 5 and progress; allow back navigation. Persist position.
8. Take a ten-question typed quiz, aiming for two questions per topic. Deduplicate
   normalized prompts and answers across topics; fill overlaps with other unique
   pinned questions, or shorten the quiz if too few unique questions exist. Restore
   fuzzy autocomplete from the pinned category bank, with arrow keys and Tab/Enter
   completion. Suggestion candidates may be sent to the browser, but no candidate
   is labeled as the correct answer and grading stays on the server.
   Briefly show Correct or Incorrect after each finalized response, then advance.
   Incorrect feedback and results never reveal the correct answer. Close-answer
   prompts allow another try before scoring. (Updated by the owner after phase four.)
9. Below 90%, show score and the deduplicated list of topics behind missed
   questions; reread those topics before the next quiz.
10. Retry question priority: misses from the immediately preceding attempt, then
    unseen questions from the original topic set, up to the original quiz size.
    Never repeat a question or duplicate variant answered correctly earlier in this study session.
    Shuffle without duplicates; allow fewer than ten when the eligible pool is
    smaller. The 90% passing threshold rounds up using the actual attempt size.
    This owner-requested refinement replaces backfilling with correct questions.
11. Repeat without an attempt limit. At 9/10 or better, mark all five topics
    completed (including the topic behind any remaining miss, per the agreed
    session-level rule), timestamp completion, and count one completed session.
12. Show a brief completion celebration and a clear next action. List any topics
    behind remaining misses with optional rereading, preserving the pass without
    requiring another quiz.

Recommended/accepted edge behavior: when fewer than five unfinished topics
remain (including intrinsically small subcategories), offer a labeled shorter
session. Use two questions per topic, with 90% rounded up as the passing score.
Count a passed shorter session as one completed study session. Never fabricate
questions, duplicate topics, or quietly mix in another subcategory.

When all selected content is complete, celebrate and offer editing interests
or Explore. Do not automatically start spaced repetition; revisit-old-topics
is a future feature enabled by completion timestamps.

## Completion identity and progress

- Store completion once per student and stable topic ID. A topic in multiple
  subcategories contributes to every associated subcategory automatically.
- Category and overall totals deduplicate topic IDs. Separate category-specific
  records sharing a subject ID stay separate unless explicitly changed later.
- Percentage = distinct completed active topics / distinct active topics in
  that scope. Reading, opening, or old manual studied markers are not completion.
- Keep current content coverage distinct from immutable historical session
  evidence, including after imports or retirements.
- Top of Progress: five successfully completed sessions per Monday–Sunday week,
  using America/Chicago. Show count and percent; cap visual fill at 100% while
  retaining the actual count. Retries count only once after the session passes.
- Show roughly a month of activity as 35 day squares (five calendar weeks).
  Reading/quiz activity may shade squares; only passes advance the weekly goal.
  Provide accessible date/activity labels and a legend.
- Show categories with expandable subcategory progress, including categories
  outside current interests. Prior achievements persist when interests change.
- Retain historical practice results through a secondary entry point. Do not
  retroactively convert existing question results into new topic completions.

## Explore

Twelve category cards → subcategory cards → topic links → topic page.
Clickable breadcrumbs preserve the entry subcategory for multi-membership
topics. Reuse the reading-card component. A discreet topic search is useful,
but hierarchy remains the primary navigation. All content is freely explorable
within the existing authenticated site; browsing does not grant completion.

## Visual system

Muted black-and-gold theme inspired by the school colors: warm charcoal canvas
(`#1c1a17`), light paper cards (`#f3f1e7`) with dark ink text, muted gold
(`#bfb07a`), and soft beige (`#d3c9a4`) highlights. Text on the dark shell stays ivory. Serif headings and clean
sans-serif body/control text. Category accents remain subtle, with readable
dark labels and pale tinted fills on paper cards; motifs stay subordinate to content.

Show the three landing cards directly, without a hero or slogans. Use compact,
functional headings elsewhere and retain the Study question. Show ten Study
choices in two rows of five on wide screens, with two columns on smaller screens.
Use `huddleston.science` in the header without a subtitle. These changes were
requested during first-pass review on September 25, 2026. Follow-up review
restored light paper cards against the dark background across all preview pages.

Motion: small hover lifts, animated progress fills, brief card entrances and
reshuffles, restrained completion celebration. No constant animation. Support
reduced motion, touch, keyboard, high contrast text, and non-color status cues.
Apply the shared shell/style to Home and Account during production integration.

## Implementation passes

### 1. Visual prototype (complete)

- Save this plan and build a clickable, local preview of the landing page,
  ten-card picker, and topic reader with real dataset content.
- Include interest selection and supporting Progress/Explore visual previews
  to judge the design in context. Clearly identify sample progress and temporary
  preview state; no real student data or question answers are included.
- Keep current Django student flows operational while design is reviewed.
- Inspect desktop/mobile rendering and exercise interactions.

Source: `prototypes/scholars-bowl/`. Run:

```sh
python3 prototypes/scholars-bowl/serve.py
```

Build-only output: `.local/scholars-preview/`; use `--build-only`.

Status (September 25, 2026): implemented and checked; ready for visual review.
The interrupted first pass was recovered and finished. Desktop and mobile
layouts (down to 320px), keyboard navigation, reduced motion, interest filtering,
reshuffling, reading navigation, in-page resume/restart, short sessions, Explore
breadcrumbs/search, and sample Progress interactions have been exercised.
The activity preview uses Chicago calendar dates, including across week boundaries.
All 7,072 current topics are included; no quiz or grading payload is exported.
The static preview resets on refresh and stops before the quiz. Account
persistence, automatic first-visit onboarding, and the learning engine are
implemented separately in Django in pass two below.

### 2. Preferences and complete study loop (implemented)

- Add account category preferences/onboarding state, dedicated study sessions,
  pinned topic content/question revisions, reading state, quiz attempts, and
  unique topic completion records. Reuse accounts and server-side typed grading.
- Implement every state transition, resume/start-over behavior, review cycle,
  content import stability, short sessions, and atomic completion.
- Server enforces ownership, grading, selected scope, idempotency, and one
  active session. Client UI must not receive a marked answer key; category autocomplete candidates
  are permitted by the subsequent owner-requested refinement.
- Integrate approved visual components with Django templates and assets.

Status (September 25, 2026): implemented in Django with migration `0007`.
Interests and onboarding persist on accounts. Study sessions pin reading content,
question revisions, and grading banks; reading, quiz answers, and targeted retries
resume across devices. Account locks, a database constraint, and reading versions
protect restart, concurrent starts, and duplicate submissions. Successful sessions
create topic completions and activity events atomically. New question views expose
only prompt text, and legacy pages no longer send canonical answers, explanations,
or autocomplete banks. Legacy recognition/recall displays are retired while their
stored results remain available. See [phase-two notes](SCHOLARS_BOWL_PHASE2.md).

### 3. Progress and Explore (implemented)

- Connect actual completion totals, weekly session goal, activity events and
  category/subcategory expansion. Build hierarchical Explore and breadcrumbs.
- Update Account and shared navigation; preserve historical results.

Status (September 25, 2026): implemented in Django. Progress uses saved topic
completions, a five-session Chicago weekly goal, and 35 calendar-day activity
squares. Explore provides category/subcategory navigation, scoped search, paginated
topic lists, and shared reading cards with entry-context breadcrumbs. Browsing
does not grant completion. Study history and older practice statistics remain
accessible. See [phase-three notes](SCHOLARS_BOWL_PHASE3.md).

### 4. Validation and polish (complete)

- Verify resume at every stage, restart invalidation, answer secrecy across
  legacy/new endpoints, retry composition, small pools, completion identity,
  duplicate submissions/multiple tabs, week boundaries, and content imports.
- Check mobile, keyboard/focus, reduced motion, empty/all-complete states,
  contrast, and performance with the full library.
- Update README/operator guidance to match the final experience. Existing
  short descriptions are valid content and not a release blocker.

Status (September 25, 2026): all 147 Django, 69 content, and 9 JavaScript tests
passed. Completed the isolated PostgreSQL backup/restore drill (33 matching
tables), mobile/keyboard review, loaded reduced-motion rule verification, and
full-library checks. Fixed empty-content messaging and resuming sessions after
interest retirement; improved form accessibility and replaced obsolete operator
instructions. See [phase-four validation notes](SCHOLARS_BOWL_PHASE4.md).
Production deployment and the classroom pilot remain separate operator actions.

## Dataset observed during planning

7,072 topic records, 355 subcategories, 12 categories, 15,947 typed questions.
Every topic currently has at least two typed questions; 6,082 have exactly two.
2,335 topics have detailed study content and 4,737 have short descriptions.
Six subcategories have fewer than five topics. 4,580 topics belong to more than
one subcategory. These are observations, not hard-coded runtime assumptions.
