# Remaining two-source topics — Luna API run

On September 24, 2026 the user accepted the 100-topic pilot's observed quality
and authorized the same process for all other unenriched topics with at least
two distinct original tournament source IDs. The fixed manifest selects **839**
new topics and excludes the **100** completed pilot drafts. These are 939 topics
in total; the separate one-source backlog is outside this API authorization.

The existing ignored local `.env` key is reused under the user's continuing
authorization. The personal API key is not saved in artifacts or printed. AWS
signing parameters found later in third-party search URLs were removed; the
writer now sanitizes such material before persistence. See
[the cleanup report](../SECURITY-CLEANUP.md). The model is
exactly `gpt-6-luna`, with the pilot's same prompt, medium reasoning, web search,
structured output, 12-tool-call limit and 6,000-output-token limit. Each request
researches one topic with fresh context. Up to 20 requests run concurrently.

At the pilot's observed average, new generation is estimated at about $19.06.
The runner reserves an estimated $0.25 per in-flight request against a $40 local
dispatch guardrail; this is not a server-enforced billing cap. Actual returned
usage and recorded search actions determine the final estimate. No additional
full factual audit is planned: researcher self-checks and automatic validation
implement the user's accepted lighter policy, with targeted attention to reported
concerns or concrete failures.

## Resume safely

`scripts/luna_topic_batch.py` holds `.run.lock`, persists each completed response,
and writes a dispatch marker before each request. Read `summary.json` while it
runs. Existing response files are skipped, including unsuccessful records. An
interrupted dispatch with no saved response requires reconciliation before
resuming, so a possibly billed request is not silently repeated. Any HTTP error
or unknown transport outcome stops new dispatch while existing requests finish.

```sh
.venv/bin/python scripts/luna_topic_batch.py status
.venv/bin/python scripts/luna_topic_batch.py run --workers 20
```

Only run these commands when the current process has finished. A held lock is
evidence of an active generator, not a reason to delete its lock file or markers.
Do not remove response files to force paid retries. Any explicit repairs must
retain their original response and account for additional cost.

## Normalize and integrate

The baseline research requirement is at least one actual search and one direct
source open per topic. Per-reference open-action gaps from the stricter pilot
check are informational under the accepted policy. Format checks still require
the assigned ID/model, a paragraph, four to six facts, references and evidence
notes, and a completed researcher self-check. The normalizer uses recorded API
request timestamps, canonicalizes equivalent citation URLs and removes an
unlisted extra citation only where another listed supporting URL remains. All
adjustments and raw response hashes are retained; unsupported blocks are flagged.

Known pilot corrections are applied to import copies using explicit patches;
generated pilot and new research content remains unchanged. Saved response
traces have a documented security redaction of signed URL parameters, with
artifact hashes reconciled in the cleanup ledger. Researcher caveats are recorded
and considered on their merits, not automatically equated with factual errors.
Conservative source-word warnings count whole blocks against each cited source
and may overcount actual source dependence.

The normalized pilot and new content are combined for validated local acceptance.
The integration helper preserves all original 1,006 pages and existing 390 Sol
enrichments, reconciles only the accepted topic IDs in pending queue batches,
and leaves other topics claimable. It must not modify IDs, questions or student
history. Run repository validation/tests, rebuild the static output and use the
existing local Django importer after successful acceptance. Do not deploy.

The Sol heartbeat remains paused to prevent overlapping work while this run is
active. Do not restart it blindly after integration: report completion of this
authorized API subset and leave the one-source backlog for the user's next choice.

## Generation and acceptance status

Generation finished for **839 of 839** new topics in **24 minutes 43 seconds**.
Additional API usage is estimated at **$18.34100109**; the combined estimate
including the pilot is **$20.637613635**. These are usage-derived estimates,
not invoice amounts. The 839 new drafts and corrected pilot 100 have been
accepted into site data, bringing accepted Luna topics to **939** and detailed
study pages to **2,335**. The **4,737** remaining unenriched topics each have
one original tournament source. The local Django import, static rebuild, and
all 50 tests passed. Existing pages, question text, historical revisions, and
student history were preserved. See [the completion report](REPORT.md) and
[verification results](verification.json). Nothing has been deployed, and the
Sol heartbeat remains paused.
