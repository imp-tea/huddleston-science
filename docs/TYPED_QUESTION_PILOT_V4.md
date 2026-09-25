# Typed-question pilot v4: simplified prompt

September 25, 2026. The simplified prompt produced **201 question/answer pairs across
69 topics for an estimated $0.0505**. This is the most promising direction from the
pilots so far in my qualitative reading: answers are compact, associated questions
usually supply their own context, and there is much less elaborate answer handling.
An assistant editorial screen found **14 questions worth revising**, with no blocking
issue noted in the other 187. This is not an exhaustive factual audit or measured
student success rate.

[Browse the unedited questions](http://127.0.0.1:8774/review.html).
The page includes separate editorial notes and the complete supplied JSON context.
Original multiple-choice questions and all application data remain unchanged.

## Exact experiment

- Model: `gpt-6-luna`; reasoning: `xhigh`; maximum output tokens: **16,000**.
- Direct Responses API, standard processing; no Batch job and no automatic retries.
- The user's [exact prompt](TYPED_QUESTION_PROMPT_V4.md), substituting only the number
  of questions, followed by the full formatted topic JSON in one user input.
- No added system instructions, few-shot examples, web tools, or editorial feedback.
- Strict structured output: `{"questions":[{"question":"…","answer":"…"}]}`.
  No model-generated aliases, prompt answers, rejected answers, citations, explanations,
  IDs, difficulty labels, or confidence fields. IDs and review metadata are local.
- Quota: `max(2, min(5, distinct source question count))`. A bonus remains one source,
  regardless of how many parts it contains.
- Same 69 seeded topics across 12 categories as earlier pilots. The 24 single-source
  topics each gained one question, raising the total from 177 to 201. Input context
  is identical to v2 except for these requested counts.

The full current corpus has **7,072 topics and 15,947 requested questions** under this
rule, up from 10,976 questions under the old one-question minimum.

## Results and cost

| Measure | Result |
|---|---:|
| Completed requests / structurally valid outputs | 69 / 69 |
| Generated / requested questions | 201 / 201 |
| Input tokens | 183,882 |
| Cached input tokens | 0 |
| Cache-write input tokens (included in input total) | 181,970 |
| Output tokens, including reasoning | 55,161 |
| Reasoning tokens (included in output total) | 44,955 |
| Median request time | 8.6 seconds |
| Largest output token usage | 2,242 |
| Estimated pilot cost | $0.050518 |
| Weighted full-corpus standard generation estimate | $3.67 |
| Weighted full-corpus Batch generation estimate | **$1.84** |

The cost calculation uses returned usage and the current
[GPT-6 Luna rates](https://developers.openai.com/api/docs/models/gpt-6-luna), including
cache writes and reasoning within output billing. The full-run estimate weights each
sample topic by its category/source-count stratum and applies the Batch discount.
It excludes review, repairs, retries, and future pricing changes. One observation per
stratum gives only a rough planning estimate, not a confidence interval or invoice.

The previous GPT-6 Luna pilot cost $0.1059 for 177 questions. V4 costs less despite
xhigh reasoning and more questions because it sends less prompt material and requests
much less output. Xhigh is an effort setting, not a fixed token expenditure.

## What worked and what remains

The Weaving set cleanly identifies **Weaving**, then asks for the **Loom** while naming
the topic. Heracles yields **Heracles, Zeus, Eurystheus, Nemean Lion, Cerberus**.
Mesopotamia yields **Mesopotamia, Tigris River, Euphrates River, Iraq, Persian Gulf**.
These are concrete targets that fit the desired autocomplete workflow. Some questions
are easy or have only one sentence; that is not automatically a defect under this prompt.

The 14 revision flags comprise five factual problems, four giveaways, two weak targets,
one ambiguous target, one reference to hidden context, and one question about the
study-topic title itself. Examples:

- **Polynomial 26.2:** gives “highest degree,” then asks for **Degree**.
- **Bleeding Kansas 62.4:** places Harpers Ferry four years after 1856; the raid was
  in [1859](https://home.nps.gov/articles/john-browns-raid.htm).
- **Liszt 4.2:** says Ligeti was born in Hungary;
  [his biography identifies Romania](https://en.gyorgy-ligeti.com/biography).
- **Birds 45.4:** “extinct genus” and “primitive avialan relative” do not uniquely
  identify Archaeopteryx.
- **Athlete 53.2:** asks for a synonym, Sportsperson, instead of a distinct useful
  trivia target. This is not a penalty for shared answer strings.
- **Electronegativity 46.4:** refers to “the provided range,” which students cannot see.

Some factual simplifications were inherited from supplied study text. For example,
Night's opening is compressed into the ghetto/deportation, and Life conflates biological
life with the communicating civilizations estimated by the
[Drake equation](https://www.seti.org/research/seti-101/drake-equation/).
Simple prompting cannot guarantee that imperfect source summaries are corrected.

## The one instruction conflict to resolve

Five first answers exceed three words because their topic titles do: Pi (constant and
notation), Jake from State Farm, The Myth of Sisyphus, January 6, 2021 United States
Capitol attack, and Ferdinand II of Aragon. **842 corpus titles** exceed three
whitespace-separated words, so this will recur at scale. The model prioritized exact
titles; these conflicts were logged separately rather than counted as bad trivia.

68 of 69 first answers exactly match their topic titles. The remaining answer is
“Night” rather than “Night (memoir).” Every later question names the recognizable topic;
five omit only its parenthetical disambiguation. No exact answer string repeats within
a topic. Some other questions mechanically copy parentheticals, and Pi 29.1 actually
asks for the database topic title.

My recommendation is to retain this short prompt. Before a full run, make just one
small clarification: allow longer established names/titles, and use natural topic
names without database disambiguation. That change was **not** applied to this pilot.

## Review limits and reproducibility

The assistant read all 201 pairs and compared selected issues with source context and
external references. This is an unblinded development-sample review, not a blind test,
independent human review, or exhaustive fact check. V4 changes prompt, schema, reasoning,
and quotas together, so it does not isolate which change helped. Earlier headline flag
counts included answer-policy issues that cannot arise in this schema; they should not
be compared directly with v4's 14 flags.

Artifacts are in `research/typed-questions/pilot-2026-09-25-v4/`: immutable request and
response JSON, manifest, prompt, summary, metrics, editorial review, and rendered pages.
The runner's 22 offline tests passed. Saved request hashes, exact prompt text, model,
reasoning, quotas, output fields, unchanged input context, and production data hashes
were checked. The browser's filter and answer toggle were exercised successfully.
