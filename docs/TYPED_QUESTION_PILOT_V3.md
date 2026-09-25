# Typed-question pilot v3: GPT-5.6 Luna vs GPT-6 Luna

September 25, 2026. **This trial does not show a quality advantage for GPT-5.6 Luna.**
It completed the same 69-topic, 177-question pilot faster, at about 20 cents, but
the editorial screen found more answer giveaways and more questions needing attention.
There are useful improvements in individual sets, so this is a sample-level result,
not a claim that one model is universally better.

## Controlled comparison

All 69 saved API requests are identical to v2 **except for `model`**, now
`gpt-5.6-luna`. Both runs used high reasoning, 12,000 maximum output tokens, the
same five complete input/output demonstration pairs, the same JSON schema, and
exactly the same topic/source contexts. Both used direct Responses requests,
standard processing, and eight workers after a one-topic smoke check. No generation
web tools, automatic retries, or full Batch job were used.

The unchanged [v2 prompt](TYPED_QUESTION_PROMPT_V2.md) and
[examples](TYPED_QUESTION_EXAMPLES_V2.json) make this a model comparison rather than
another prompt revision. The prompt still encourages distinct answer concepts;
its wording was frozen to isolate the model change.

The user clarified that **shared canonical or accepted answers are not defects**
in the site's typed-answer/autocomplete workflow. The current review and v3 validator
do not penalize these overlaps. The earlier Frankenstein collision finding was
removed from the comparison baseline, changing v2's attention count from 30 to 29.
The original v2 audit is preserved, with an adjusted copy stored alongside v3.
V3's two Winnie-the-Pooh questions therefore receive no duplicate-answer penalty,
even though the model disregarded the frozen prompt's distinct-concept instruction.

## Results

| Measure | GPT-6 Luna, v2 | GPT-5.6 Luna, v3 |
|---|---:|---:|
| Requests completed | 69/69 | 69/69 |
| Questions generated | 177 | 177 |
| Questions flagged, shared answers allowed | **29** | **38** |
| Of those, answer-policy findings only | 12 | 15 |
| Other question problems | **17** | **23** |
| Questions with answer-leakage findings | **6** | **14** |
| No blocking issue noted | 148 | 139 |
| Median request time | 18.4 sec | **11.8 sec** |
| Maximum output tokens actually used | 5,158 | 3,515 |
| Input tokens | 413,908 | 413,908 |
| Output tokens, including reasoning | 134,324 | 102,415 |
| Reasoning tokens | 104,495 | 68,679 |
| Estimated pilot cost | **$0.1059** | $0.2004 |
| Projected full-generation Batch cost | **$3.66** | $6.97 |

The quality categories overlap except for the explicit split between answer-policy-only
and other question problems. Some answer-policy findings are small improvements to
accepted variants that autocomplete may mitigate; others are substantive, such as
explicitly rejecting a valid answer. These numbers are not student grading error rates.

All v3 outputs passed the revised structural checks. Structural checks cannot establish
factual accuracy, sound clues, or good learning targets. The original v2 structural
count was 67/69 because its old checker rejected the Frankenstein overlap and collapsed
uppercase Π and lowercase π. Those checks are not evidence of a v3 quality advantage.

High reasoning is a requested effort setting, not a fixed reasoning-token allocation
across models. GPT-5.6 Luna used fewer reasoning tokens despite both requests specifying
high. Neither run was constrained by the 12,000-token limit.

## Where GPT-5.6 Luna helped

- **Mesopotamia:** Tigris, cuneiform, Sumer, and Sargon are useful associated targets.
  This set avoids v2's question that effectively concatenates “Tigris–Euphrates river
  system” and its broad regional-label question.
- **Phillips curve:** inflation and unemployment are more conventional learning targets
  than v2's long phrase “short-run inflation-unemployment tradeoff.”
- **Standalone context:** the Harlem migration question names Harlem. The September 11
  set names the event when asking about associated concepts, avoiding v2's orphaned
  reference to “the attacks.”
- **Some answer variants:** de Armas, F for fluorine, and For You/FYP appear naturally.
  GPT-5.6 Luna also detected the erroneous source definition of cosine, as v2 did.

## Where it regressed

**Answer giveaways were more frequent.** Olympus Mons 44.3 explicitly says “shield
variety” before asking for Shield volcano. Keats 23.5 supplies two titles containing
“Ode” before asking for the poetic form. Bucky Barnes 32.2 supplies Steve Rogers while
also accepting Steve Rogers. The January 6 and September 11 event questions give the
full dates and practically spell out their requested event names. In contrast, v2
used event clues without naming the dates in those two stems.

**Answer policies sometimes contradict the question.** Hanukkah 39.1 explicitly
rejects Festival of Lights even though the stem clearly identifies the Jewish holiday.
That name is supported by [Chabad's Hanukkah explanation](https://www.chabad.org/holidays/chanukah/article_cdo/aid/102911/jewish/What-Is-Hanukkah.htm).
Cosine 28.4 asks for the function whose negative is the derivative, then requires a
negative sign and rejects sine. A direct derivative question would avoid the conflict.
Heracles 40.1 asks specifically for the Greek name while accepting Hercules; the
simple repair is to remove the unnecessary Greek-name restriction.

**Source mistakes still propagate.** Hydra 40.5 assigns burning the neck stumps to
Heracles; [Apollodorus 2.5.2](https://www.theoi.com/Text/Apollodorus2.html) assigns the
action to Iolaus. TikTok 33.1 treats Douyin as another name for the same product,
whereas [ByteDance describes separate China/global products](https://www.bytedance.com/?lang=en).
The IPA question again blurs standardized transcription with standardized pronunciation.
The tennis question should distinguish challenge-based review from live calling:
[Hawk-Eye itself supplies live electronic line calling](https://www.hawkeyeinnovations.com/).

**Some targets remain underdetermined.** Self-portrait 6.4 asks which artist made an
unusually large number of painted and printed self-portraits, without distinguishing
Rembrandt. Historical materialism again lacks clues separating it from broader Marxism
or conflict theory. Autocomplete cannot supply missing conceptual discrimination.

The flagged questions remain unedited in the review page. Each has a separate note,
and source passages can be expanded for inspection.

## Review scope and interpretation

The root assistant read all 177 new stems and canonical/accepted/prompt/rejected answer
lists. Nineteen selected questions were compared against supplied evidence, and selected
concerns were externally checked. V2's rejected-answer lists were also screened for
comparability; only one was nonempty, with no new issue found. The same broad editorial
criteria were applied, with the shared-answer correction described above.

This was an **unblinded, qualitative screen**, not an exhaustive factual audit, blind
solving test, student trial, or statistical benchmark. One generation per model on a
previously used development sample cannot establish a precise model quality difference.
The 139 v3 items with no blocking issue noted are candidates for review, not certified
publication-ready questions. Autocomplete source code was inspected, but the pilot
questions were not imported or tested in the production grading workflow.

For the next generation stage, GPT-6 Luna remains the better-supported choice from
these trials: fewer observed clue problems and lower cost. Both models still need
editorial review and repair. The highest-value next improvement is detecting answer
giveaways and competing valid targets, rather than increasing an already ample token
budget. Future prompts can soften the distinct-concept instruction to encourage variety
without treating shared answer text as an error.

## Cost, artifacts, and verification

[Official GPT-5.6 Luna documentation](https://developers.openai.com/api/docs/models/gpt-5.6-luna)
confirms high reasoning and standard short-context input/cached/output rates of
$0.20/$0.02/$1.20 per million tokens. The run records $0.25 per million cache-write
tokens from [official pricing](https://developers.openai.com/es-419/api/docs/pricing).
Cache reads and writes are charged separately from uncached input; reasoning is already
included in output and is not counted twice.

The estimated cost is **$0.20035533**, versus $0.105890665 for v2. Population-weighted
generation is estimated at **$13.93 standard / $6.97 Batch** for 7,072 topics and
10,976 questions. The Batch projection assumes half the standard rates and the observed
token/cache mix. Estimates exclude review, repairs, retries, and future price changes;
they are not invoices or tight confidence intervals. The largest corpus contexts remain
outside this 69-topic sample.

Artifacts are in `research/typed-questions/pilot-2026-09-25-v3/`: frozen requests,
responses, prompt and examples; usage summary; `editorial-review.json`;
`v2-editorial-review-adjusted.json`; `comparison.json`; `questions.md`; and `review.html`.
The directory is ignored by Git, as are earlier pilot artifacts.

Twenty offline pilot tests passed, including model-only request changes, model-specific
cost accounting, unchanged sampling, and shared-answer acceptance. The saved requests
were separately compared with all 69 v2 requests. Source-data hashes remain unchanged.
All original multiple-choice questions and prior pilot outputs are retained. No live
application changes or full Batch submission were made.
