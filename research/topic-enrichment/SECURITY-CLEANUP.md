# Research artifact credential cleanup — September 24, 2026

GitHub reported AWS access-key IDs after commit `be0b1d185782` was pushed.
Investigation found **45 access-key-ID occurrences in 40 saved response files**,
all within web-search result URLs at `response.output[].action.sources[].url`.
There were 37 distinct IDs: the occurrences comprised 34 temporary-key prefixes
and 11 ordinary access-key prefixes. No credential values are reproduced here.

The signed URLs refer to third-party S3 or CloudFront source downloads. This
location supports that origin; it does not independently establish ownership of
each signing key. No AWS secret-access-key fields or access-key-ID patterns
outside those URLs were found in the tracked research. The local OpenAI API key
was also absent from all 1,210 files tracked at the start of the check, and the
local `.env` was untracked.

All 45 links containing key IDs had parseable configured expiration times in the
past when checked at **2026-09-24 19:27 UTC**. Their latest configured expiry was
August 7, 2026. This establishes link expiry, not revocation of the underlying
credentials. No signed URL was fetched and no credential was used during this
investigation. AWS documents these links as time-limited bearer URLs whose
validity also depends on the signing credentials:
[S3 presigned URLs](https://docs.aws.amazon.com/AmazonS3/latest/userguide/using-presigned-url.html).

The previous completion check searched for the personal OpenAI key only. It did
not establish the absence of other credentials, and missed these signed URLs.

## Local changes

The cleanup removed AWS signing parameters from **46 URLs in 41 response files**.
The additional file contained a signed URL without an access-key-ID pattern.
The retained trace keeps ordinary URL components but no longer represents a
usable authenticated download URL. None of these changes affected generated
topic content or the URLs actually cited by the accepted study pages.

The original and sanitized artifact hashes are retained in
[the cleanup ledger](security-cleanup-2026-09-24.json). All matching hashes in
the normalized snapshots and queue have been reconciled, with explicit
redaction provenance. Topic content, usage records, questions, and student data
were not modified. No new API generation was performed.

The writer now sanitizes the entire API record before saving and returning it,
including nested search results and embedded structured output. Normalization
and integration reject unsanitized records. If generated content or citations
are altered by redaction, acceptance requires source repair instead of treating
the stripped URL as a verified citation. A read-only repository scanner reports
paths and counts without exposing secret values.

Validation: the working-file scanner reports zero findings; all 39 Python,
9 Node, and 11 Django tests pass. The integration dry run confirms all 939
previously accepted Luna topics still validate with matching response hashes.
Fresh normalization reproduces the same accepted topic content and research.
All site data files are unchanged from the pushed commit, and all 41 sanitized
response hashes match the cleanup ledger.

## Published history

Only the latest commit contained access-key-ID matches among the five reachable
commits checked locally. The user authorized replacing that latest published
commit with the cleaned version and force-pushing `main` with an explicit lease
against `be0b1d185782591d0643438119b85c115e026a96`. The replacement preserves
the original parent and enrichment changes. Push success and the resulting
remote commit must be verified separately; creating the local replacement
commit alone does not confirm publication. Even rewriting a branch cannot
remove other clones or guarantee deletion of cached GitHub copies; see
[GitHub's removal guidance](https://docs.github.com/en/authentication/keeping-your-account-and-data-secure/removing-sensitive-data-from-a-repository).
