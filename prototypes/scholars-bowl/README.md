# Scholars Bowl visual preview

First pass of the [approved redesign](../../docs/SCHOLARS_BOWL_REDESIGN.md).
Run from the repository root:

```sh
python3 prototypes/scholars-bowl/serve.py
```

Open http://127.0.0.1:8877. Choose another port with `--port 8878` or build without
serving with `--build-only`. Output is generated under `.local/scholars-preview/`.
Restart the command to rebuild after editing source files or content.

The preview includes the three-card landing, interest-selection dialog, random
ten-subcategory picker, reshuffle, five-topic reader, same-page resume/start-over,
sample Progress dashboard, and full hierarchical Explore with breadcrumbs and
title search. All 7,072 current topics are available, including short descriptions.
Source content stays in `data/`; do not edit generated catalog files.

The preview strip explicitly identifies example completion percentages and
activity. Interests and reading position live only in page memory and reset on
reload. This is intentionally not account persistence or the completed learning
engine. The reading flow ends with a clear preview boundary before the quiz.
Account onboarding, typed quizzes/retries, actual completions, and database-backed
resume belong to pass two. The preference dialog previews the onboarding controls
but opens on demand so the landing design is visible immediately.

No external fonts, libraries, network services, credentials, or database writes
are required. Inline SVG illustrations and CSS colors/motion are reusable in the
future Django templates. The server binds only to loopback and serves only the
generated preview directory. Attribution is included alongside source links.

## Review checkpoint

Pass one is ready for design review as of September 25, 2026. Browser checks
passed for interest selection (including the empty-selection guard), ten unique
choices, reshuffling without immediate repeats, reading/back/resume/restart,
short sessions, Explore hierarchy/search/breadcrumbs, expandable category progress,
and short-description content. Layouts were checked at 320, 390, 768, and 1440px,
with keyboard navigation and reduced motion. The 35-day activity calendar also
passed a Chicago Sunday/Monday boundary check from a browser in another timezone.

To review: open Study and reshuffle, edit interests, read through a session, then
return to Study to try resume/restart. Check Progress and expand a category; in
Explore, browse to a topic and use its breadcrumbs to return. Refresh resets the
preview. Short sessions are labeled on the picker before selection.

The reviewed direction uses a charcoal background, light paper cards, muted gold
accents, compact functional headings,
no hero or slogan copy, and the `huddleston.science` header. The ten-choice Study
picker uses five columns on wide screens and two on smaller screens.
