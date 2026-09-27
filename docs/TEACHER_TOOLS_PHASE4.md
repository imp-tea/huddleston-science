# Live quizzes — Phase 4

Implemented locally September 26, 2026. Not deployed to the production droplet.

## Available workflow

**Teacher Tools → Host a Quiz** selects a saved quiz and opens a waiting room.
Hosting validates the quiz's current review status and freezes its title, order,
question revisions, topic/category context, autocomplete banks, and grading version.
Only one waiting/running game can exist site-wide, enforced by PostgreSQL. Teacher
Tools changes to **Hosting Live Quiz** until that game ends or is cancelled.

Signed-in students see **Join the Live Quiz!** above the other Scholars Bowl cards.
Already-open home pages discover the invitation automatically. Students can reach
the home page and live quiz before selecting individual Study interests; the Study
entry point still requires interest setup.

The live page joins through a CSRF-protected POST, with a separate connection token
per page. The waiting room shows the quiz name, question count, and present students.
**Start the Quiz!** captures the present roster and locks admission. Original roster
members can return after a refresh, connection loss, or deliberate departure using
**Return to your live quiz**. Other students cannot join after Start.

The host sees the current question, answered/skipped count, still-unanswered count,
and per-player presence/response status. **Next Question** advances whenever the
teacher chooses; **Finish Quiz** closes the final question. **End Quiz Early** and
**Cancel Quiz** require explicit in-page confirmation. Host absence never advances
or closes the quiz automatically.

Students get the shared Study autocomplete widget, keyboard/IME handling, grading,
and spelling/specificity prompt. A prompt permits another attempt. Correct,
incorrect, or skipped finalizes the response once and displays feedback while
waiting for the teacher. Advancing records unanswered responses distinctly from
skips. No speed scoring or timers are added.

Finished games show a basic private score and team-coverage summary, including a
presented-question denominator for early endings. Detailed question review and
persistent report/history navigation remain Phase 5. The game and all response
records already persist for that work. Live play does not grant Study completions
or count toward the weekly Study goal.

## Synchronization, presence, and privacy

- State polls approximately every 2 seconds, invitation discovery every 5 seconds,
  with jitter, single-flight requests, request timeouts, and bounded retry backoff.
- Heartbeats run every 5 seconds. Presence expires after 20 seconds without renewal;
  players are shown as connected, away/reconnecting, or deliberately left.
- Explicit Leave waits for a POST; browser exits/navigation send a best-effort
  beacon. Tab visibility alone does not mean leave. Closing one tab does not
  disconnect another. Browser back/forward cache recovery reloads a fresh page
  connection. Presence is a lease, not a guarantee of instantaneous tab detection.
- Answers, admission, deliberate leave, and host transitions serialize on the game
  row. Writes lock the active account first; hosting additionally takes the content
  lock before quiz/game creation. Routine polls and heartbeats do not lock games.
- Host transitions require an expected version, question position, and durable
  request ID. Double clicks/retries cannot skip questions. First finalized response
  wins across tabs. A submit racing Next is either accepted before closure or
  rejected after it; old questions cannot be answered later.
- Clients reject older state versions and delayed answer feedback for old questions.
  Suggestion banks load only when an eligible student's current question changes.
- Student state excludes future prompts, canonical answer fields, explanations,
  grading metadata, and other students' responses. Suggestions are unmarked
  candidates, as in Study. The host's default projected page also omits answers.
- Disabled/reset accounts cannot renew presence or submit; account deletion cascades
  personal membership, connection, and response records. No username snapshots
  bypass deletion. Coverage summaries recalculate from remaining records.

## Deployment

Apply migration `0010_live_quizzes`, collect static files, and restart the application
through the normal deployment process after a full PostgreSQL backup. This uses the
existing Django/PostgreSQL stack: no Redis, WebSocket server, worker, package, or
hardware change is required by this implementation. Caddy/Gunicorn need no new
transport configuration. Hosting capacity on the 1-vCPU/1-GB droplet still needs the
Phase 6 load test and classroom pilot; local correctness tests are not capacity
certification.

Back up all live tables with the existing full-database backup. Do not reverse
migration 0010 to roll back application code: doing so deletes games and responses.
A server restart preserves the game position, snapshots, roster, and responses;
connections recover through the same polling/heartbeat flow.

## Verification

- Full Django suite: all 225 tests passed, including 19 new live-game tests.
- System checks, migration drift check, and `git diff --check` pass.
- Focused live-game and teacher-progress tests: 30 passed, including concurrent
  join/Start, submit/Next, duplicate Host, and duplicate Next races.
- All 14 JavaScript tests passed, including existing autocomplete keyboard/IME
  tests, grading parity, delayed-state guards, and bounded backoff.
- Tests cover snapshot stability, one-open-game constraint, permissions/CSRF,
  read-only GETs, frozen rosters, multiple tabs, expiry/reconnection, answer
  idempotency, unanswered closure, private payloads/current-only suggestions,
  cancelled/partial/full endings, and disabled/reset accounts.
- Browser validation uses separate host/student sessions on the isolated
  `huddleston_authoring_preview` database: hosting/joining, autocomplete, correct
  and skipped responses, manual advancement, refresh recovery, explicit leave and
  rejoin, a server restart during play, normal finish, and a 390px mobile viewport.

No production data or server configuration was changed.
