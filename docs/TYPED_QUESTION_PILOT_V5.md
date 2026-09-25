# Typed-question pilot v5: readable context and distinct targets

September 25, 2026. **The revised prompt improved target selection in this sample.**
All 69 requests completed and produced the requested 201 question/answer pairs.
The assistant's editorial pass found **8 questions worth revising**, all for giving
away their answers. No blocking ambiguity, weak-target, or missing-context problem
was identified in this pass. This is a qualitative screen, not proof that every
question has a unique answer or that all facts are correct.

[Browse the original outputs](http://127.0.0.1:8775/review.html).
The complete supplied context on this page is the frozen readable text actually
sent to the model. Generated questions remain unedited; editorial notes are separate.

## What changed

The [v5 prompt](TYPED_QUESTION_PROMPT_V5.md) retains the user's short trivia prompt,
with three adjustments:

- Answers identify one specific entity or concept and use a name or brief term.
  Longer established names and titles are allowed; sentence answers are discouraged.
- The first question targets the topic using its natural name, without a parenthetical
  category label. It need not copy the database title exactly.
- Two sentences address ambiguity: “Use concrete clues that distinguish the intended
  answer from other plausible answers. If several different answers fit the clues
  equally well, add a distinguishing clue or choose a different target.”

The input now uses Topic, Category, Subcategories, Description, Overview, Key Facts,
and Source Questions headings. Trailing title disambiguators are removed from the
Topic heading. All description, overview, key-fact, source-question, and source-answer
text is preserved, including complete bonus lead-ins and parts. No summarization or
source truncation is applied. IDs, provenance metadata, alias lists, taxonomy definitions,
and the duplicate evidence map are omitted. Source answer lines retain their original
accept/prompt annotations; the model is not asked to generate such annotations.

Everything else is unchanged from v4: the same 69 topics and source material, the
2–5 question quota, `gpt-6-luna`, `xhigh` reasoning, 16,000 maximum output tokens,
and strict output containing only `question` and `answer`. Requests use the direct
Responses API with standard processing. No few-shot examples, generation web tools,
automatic retries, production imports, or Batch job were added.

## Quality observations

Several targeted improvements are concrete:

- **Birds 45.3:** Archaeopteryx now has Late Jurassic Solnhofen fossils, feathers,
  teeth, and a long bony tail as clues, instead of just an extinct avialan genus.
- **Athlete 53.2:** asks for A. E. Housman using his elegy, replacing the loose
  synonym question whose answer was Sportsperson.
- **Self-portrait 6.4–6.5:** asks for The Two Fridas and Triple Self-Portrait using
  recognizable details, replacing the arbitrary Baroque-period cutoff.
- **Polynomial 26.2:** asks for Degree using the largest exponent in an example,
  without first saying “degree.”
- **Pi 29.1:** asks for Pi, with circumference/diameter and decimal-expansion clues,
  instead of asking for the study-topic title.
- Longer answers such as **Ode on a Grecian Urn**, **Law of the excluded middle**,
  and **United Airlines Flight 93** now fit naturally.

There are no parenthetical labels in the returned answers and no repeated exact
answer strings within a topic. Eleven answers exceed three whitespace-separated
words; none was flagged for length. All answers remain names, terms, or notation,
rather than explanatory sentences. The January 6 event name is naturally rephrased.

**Giveaways remain the main weakness.** TikTok 33.3 literally supplies ByteDance
while asking for ByteDance. Other flags supply the distinctive names in Baker-Miller
pink, Jake from State Farm, Drake equation, Donner Party, Hastings Cutoff, and Aten,
or give the full date and location of the January 6 attack.

Minor factual precision was not used as a rejection criterion, following the user's
stated tolerance. A few wording notes are advisory, including “natural name” echoed
in stems and “according to the supplied account” in the Article 5 question. That
phrase is unnecessary, but the Article 5 clues are independently sufficient.

For a closer comparison with v4, exclude its five factual-only revision flags:

| Editorial concern | v4 | v5 |
|---|---:|---:|
| Ambiguous/weak targets, hidden context, or study-title questions | 5 | 0 |
| Answer giveaways | 4 | 8 |
| Total priority revision flags | 9 | 8 |

The original v4 review remains unchanged. This comparison aligns broad priorities,
but remains an unblinded assistant judgment on a repeatedly used development sample.
Prompt and presentation changed together, and there is only one generation per topic;
the experiment does not isolate either change or establish a precise error rate.

## Cost and execution

| Measure | v4 | v5 |
|---|---:|---:|
| Questions | 201 | 201 |
| Input tokens | 183,882 | 69,154 |
| Output tokens, including reasoning | 55,161 | 62,093 |
| Reasoning tokens, included in output | 44,955 | 50,553 |
| Estimated pilot cost | $0.050518 | **$0.038996** |
| Median request time | 8.6 sec | 8.4 sec |
| Largest output token usage | 2,242 | 2,475 |
| Weighted full-corpus Batch generation estimate | $1.84 | **$1.65** |

Input tokens fell **62.4%**, and total estimated pilot cost fell **22.8%** despite
slightly higher output/reasoning usage. V5 had no cached-input hits and 41,344
cache-write input tokens, included in its input total. Estimates apply the documented
[GPT-6 Luna rates](https://developers.openai.com/api/docs/models/gpt-6-luna), including
cache writes and reasoning in output billing.

The full-run projection covers 15,947 questions across 7,072 topics, weighting sample
costs by category/source-count strata. It is a rough generation-only estimate, excludes
review and repairs, and is not a billing invoice or confidence interval. Standard
processing for the same corpus projects to $3.31.

## Assessment and verification

Keep the readable context, flexible answer length, and distinguishing-clue instruction.
They address the requested concerns without returning to a large prompt. The remaining
repair work is chiefly removing unnecessary names or dates that reveal answers, rather
than redesigning targets. No further prompt changes or regenerations were applied after
this pilot's outputs were reviewed.

The 24 offline pilot tests passed, including source-text preservation, bonus grouping,
quota consistency, exact supplied context, and the absence of hard title/length rules.
Saved requests, model settings, minimal output fields, and unchanged production-data
hashes were verified. The review page's filters, answer toggle, and readable context
were checked in the browser.

Artifacts are under `research/typed-questions/pilot-2026-09-25-v5/`, including saved
requests/responses, frozen supplied text, manifest, prompt, metrics, editorial notes,
verification, `review.html`, and `questions.md`. Existing multiple-choice questions
and the live application were not modified.
