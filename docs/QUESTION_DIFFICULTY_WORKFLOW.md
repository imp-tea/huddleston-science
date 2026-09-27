# Question difficulty analysis

Difficulty estimates use GPT-6 Sol at low reasoning with
`QUESTION_DIFFICULTY_PROMPT_V2.md`. The rubric targets typical high school
students' knowledge without special quiz preparation. The model receives only
the question and answer, including for multiple-choice questions; this estimates
knowledge difficulty rather than the benefit of recognizing an answer choice.

The two pilots each used the same 120 typed questions, ten per category. The
first produced 41 Easy / 55 Medium / 24 Hard; v2 produced 39 / 46 / 35. These are
category-balanced review samples, not estimates of the full bank's distribution.
The full run includes all 26,923 questions (15,947 typed and 10,976 multiple-choice),
including fresh assessments of the pilot questions. Before freezing the full
run, the I. M. Pei question was corrected to remove his spelled-out name.

## Batch lifecycle

From the repository root, use the existing virtual environment and authorized
`OPENAI_API_KEY` in the ignored `.env`:

```sh
.venv/bin/python scripts/question_difficulty_batch.py prepare
.venv/bin/python scripts/question_difficulty_batch.py submit
.venv/bin/python scripts/question_difficulty_batch.py collect
.venv/bin/python scripts/question_difficulty_batch.py publish
```

The full request file was initially partitioned into seven batches of at most
4,000 questions after the initial 61 MB upload timed out before batch creation.
Further transport resets required halving the unsent parts; only directories in
`parts.json` are active. Concatenating their input files reproduces the original
request file exactly. The uploader uses curl with HTTP/1.1, passing authorization
through stdin rather than command arguments or a file.
The default run directory is
`research/question-difficulty/full-batch-2026-09-27/`. It retains the exact
question snapshot, prompt, input JSONL and checksum, uploaded file ID, batch ID,
raw output/error files, usage summary, failures, and validated annotations.
`parts.json` lists the batch directories; `batches.json` records their latest
API states. Each part has its own durable upload/submission records. A failed
upload can be retried by running `submit` again; already-created batches are
reused. `split-pending` halves only parts with no attempted batch submission,
preserving all accepted or uncertain submissions and the exact original inputs.
The aggregate annotations list every contributing batch ID.
The model is called through the Batch API only, with a 24-hour completion
window. `submit` reuses its saved batch; interrupted submissions are reconciled
against remote batch metadata rather than blindly resubmitted. No paid retries
are automatic. Review failures or expired batches before preparing retries.

`collect` can be repeated safely. It downloads terminal batch outputs, joins
them by stable question ID (not response order), and validates each label and
completion status. Output for a live batch is its status and request counts.
`publish` requires complete successful coverage and unchanged question/answer
fingerprints. It writes `data/question-difficulty.json`, a versioned sidecar
containing labels, fingerprints, and model/prompt/batch provenance. It does not
change question text, the server database, or quiz-generation behavior. The
sidecar can be consumed during the subsequent database-ownership migration.

If there are missing, invalid, duplicated, unknown, or stale results, resolve
them before publishing. Do not remove submission markers to bypass an uncertain
remote outcome. Raw research files are ignored by Git; accepted annotations,
prompts, scripts, and this document can be versioned.

## Validation

```sh
.venv/bin/python -m unittest discover -s tests -p test_question_difficulty_batch.py
```

Tests cover unordered outputs, duplicate/unknown identities, invalid/incomplete
responses, and stale source protection. The full source bank is validated with
the existing build and typed-content validators before submission.

## Full-run submission record

Completed September 27, 2026: all 11 Batch API jobs finished and all 26,923 labels passed structural validation, with zero failed or missing results. Source fingerprints matched the current question bank before saving `data/question-difficulty.json`. The completion heartbeat is now paused. These are model difficulty estimates, not a human factual audit; server data and quiz-generation behavior were not changed.

| Part | Questions | Batch ID |
|---|---:|---|
| part-01 | 4000 | `batch_6ab9731d7d4481908819efc2f0fc803e` |
| part-02 | 4000 | `batch_6ab9738de41881909e0b39433eab573c` |
| part-03-1 | 2000 | `batch_6ab975dc3c8881909b2ce0068f5fb135` |
| part-03-2 | 2000 | `batch_6ab975adfe9c81909a2dbaa682ef64e4` |
| part-04-1 | 2000 | `batch_6ab975e5b7f48190a1e1f829b8ded6fd` |
| part-04-2 | 2000 | `batch_6ab9760db0188190a570db23b86b62e6` |
| part-05-1 | 2000 | `batch_6ab9765a804881908d4ac0a728a32eb1` |
| part-05-2 | 2000 | `batch_6ab976c7a8348190904165e008e08136` |
| part-06-1 | 2000 | `batch_6ab97673ac68819090660d5635ebd7d4` |
| part-06-2 | 2000 | `batch_6ab976832c1c8190be9b96f7e0cc6347` |
| part-07 | 2923 | `batch_6ab974ca176881908337e79e022c810f` |

## Final results

| Question bank | Easy | Medium | Hard | Total |
|---|---:|---:|---:|---:|
| Typed | 3,694 | 6,460 | 5,793 | 15,947 |
| Multiple-choice | 3,141 | 4,603 | 3,232 | 10,976 |
| All questions | 6,835 | 11,063 | 9,025 | 26,923 |

Estimated Batch cost from returned API usage: **$14.365984** ($14.37 rounded), based on 10,983,874 input tokens, no cached input tokens, and 676,422 output tokens, including reasoning. This is a usage-based estimate, not an invoice. Rates recorded with the run are $1 per million input tokens and $5 per million output tokens.

Labels, source fingerprints, and model/prompt/batch provenance are saved in `data/question-difficulty.json`. Raw output files, the aggregate `summary.json`, and the empty `failures.json` remain under the frozen research run directory. The I. M. Pei wording fix is preserved. No paid retries, deployment, or server migration were performed during collection.
