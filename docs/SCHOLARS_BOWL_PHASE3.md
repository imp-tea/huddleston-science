# Progress and Explore implementation

Phase three connects the approved design to the persisted Study data. It requires
phase two's migration `0007`; there are no additional schema changes.

## Progress

`scholars/discovery.py` computes current coverage from active topic IDs and
`TopicCompletion`, including all active categories regardless of interests.
Multiple subcategory memberships contribute to each subcategory but only once to
the category and overall count. Distinct records sharing a subject ID remain
separate. Retired content drops out of current coverage; completion records and
historical session snapshots remain intact and reappear if the topic is restored.
Legacy manual study markers and practice answers do not count as completions.

The weekly goal is fixed at five passed Study sessions, including shorter
sessions. Boundaries are Monday midnight through the following Monday midnight
in `America/Chicago`, including daylight-saving changes. Counts come from passed
sessions, not attempts or activity-event counts. The displayed count and percent
can exceed the goal; the visual bar stops at 100%.

The activity calendar contains the current Monday–Sunday week and four preceding
weeks (35 dates). Reading, quiz activity, and passes use distinct shades; passes
also have a checkmark. Every square has a date/activity label and a tooltip on
hover or keyboard focus. Future days are outlined. Reading or failed quizzes
never advance the weekly goal. Aggregations use five queries independent of the
number of categories, subcategories, or events.

## Explore and navigation

`/scholars-bowl/library/` now presents categories, subcategories, and paginated
lists of active topics (40 per page). Search matches titles, descriptions, and
aliases within the current scope. Search results across categories include the
category label. Pagination preserves the scope and search query.

Topic pages use the same whitelisted reading snapshot and card as Study.
Subcategory links retain the entry subcategory in the URL and breadcrumbs;
an unrelated subcategory is rejected. Legacy topic redirects preserve this
context. Retired topics are unavailable in Explore; their original reading
content remains available in historical Study sessions. Browsing does not write
activity, manual study markers, or completions.

The shared shell includes Study, Progress, and Explore navigation. Account keeps
the category selector implemented in phase two. Study history now paginates all
sessions, with older practice results and statistics accessible separately.
Legacy statistics and filtered library routes remain under `/practice/`; the
administrator's existing student statistics remain legacy practice statistics.

## Validation and preview

Tests cover completion identity and memberships, interest changes, retirement
and restoration, weekly boundaries and both daylight-saving transitions, goal
overflow, activity deduplication, privacy, query count, hierarchical navigation,
search/pagination, breadcrumbs, redirects, read-only browsing, history, and empty
states. Existing legacy tests use their retained statistics routes.

The functional local preview uses the isolated `huddleston_study_preview`
database on port 8878. Port 8877 is still the static phase-one prototype and will
not show these persisted-data features. No production deployment is performed.
Phase four remains the final validation and polish pass.

Validation on September 25, 2026: the 143-test Django run passed 142 tests and
identified one legacy test still expecting Explore to record visits. That test
was updated for read-only browsing; the subsequent 45-test regression run
(Discovery, legacy Progress, and Practice) passed in full. Django system checks,
migration drift checks, and whitespace checks passed. Browser verification covered
320px, 390px, and 1440px layouts, keyboard disclosure controls, search, hierarchical
navigation, and reading breadcrumbs with the full library. Local rendering used
two queries for Explore categories and five for Progress, without per-row queries.
