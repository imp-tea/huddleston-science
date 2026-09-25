# Typed-question pilot v2 — September 25, 2026

The second direct-API pilot generated **177 questions for the same 69 topics**.
The revised package looks better: the editorial screen flagged **30 questions**
for attention, versus 55 in v1. Generation cost increased from **$0.0743 to
$0.1059**. This supports continuing with the new approach, with a separate review
and repair stage before publication.

## What changed

| Setting or result | Pilot v1 | Pilot v2 |
|---|---:|---:|
| Model | GPT-6 Luna | GPT-6 Luna |
| Reasoning effort | medium | **high** |
| Maximum output tokens per topic | 6,500 | **12,000** |
| Complete demonstration pairs | 0 | **5** |
| Restrictions on topic-name answers | Single-source forbidden; multi-source limited | **None** |
| Questions generated | 177 | 177 |
| Questions flagged for attention | 55 | **30** |
| No blocking issue noted | 122 | **147** |
| Questions identifying the topic itself | 6 | **64** |
| Input tokens | 245,272 | 413,908 |
| Output tokens, including reasoning | 107,845 | 134,324 |
| Reasoning tokens | 67,536 | 104,495 |
| Estimated direct API cost | $0.0743 | **$0.1059** |
| Weighted full-generation Batch estimate | $2.64 | **$3.66** |

The first prompt had short examples of question form, but no complete input/output
demonstrations. V2 supplies five complete pairs, covering Photosynthesis, Jane Austen,
Lake Baikal, Arithmetic mean, and an unidentified literary work. These demonstrate
eight usable questions and one insufficient-evidence slot, including topic-name
answers, distinct targets, fair aliases, and numerical answers. None of those example
topics is in the pilot sample.

The executed [prompt](TYPED_QUESTION_PROMPT_V2.md) and
[demonstrations](TYPED_QUESTION_EXAMPLES_V2.json) are retained separately from v1.
Each live request included the complete examples as alternating user/assistant
messages, followed by its actual topic context. All 69 requests used
`reasoning.effort: high` and `max_output_tokens: 12000`.

The prompt also strengthens standalone context, category fit, useful learning
targets, answer leakage checks, acceptable short answers, and source-error handling.
It requires a different answer concept in each slot and explicitly says that an
alias or renaming is not a new concept. No cross-topic uniqueness rule applies.

## Experiment and limits

The 69 topic contexts are exactly equal to v1, with the same source material,
source-count quotas, and 12-category stratification. See
[the first report](TYPED_QUESTION_PILOT.md) for sampling populations and limitations.
This compares the whole revised package: it does **not** isolate the effects of
high reasoning, examples, or removing the topic-name restriction. It is also a
development sample already used to improve the prompt, not a held-out evaluation.

All 69 API requests completed, with no incomplete responses or blocked slots.
Median request duration was 18.4 seconds; the slowest took 57.4 seconds. Maximum
output usage was 5,158 tokens, comfortably below 12,000. The larger limit was not
needed by any observed request, but leaves room for harder topics. Output usage
includes reasoning; reasoning tokens must not be added again to the cost.

The same root assistant screened all 177 stems, canonical answers, accepted-answer
lists, and prompt-answer lists. Eighteen selected questions were additionally
compared with their supplied evidence; selected concerns received external checks.
The 30 flagged items include small wording and answer-bank repairs as well as
substantive question problems. The remaining 147 are **not factually certified or
ready-to-publish by this count alone**. There was no blind solving pass, exhaustive
fact/alias audit, human review, or student trial. Missing aliases are answer-bank
findings, not demonstrated failures of the site's fuzzy matcher. The attention
rate fell from 31.1% to 16.9% in this sample; it is not a population error estimate.

## What improved

- Sparse topics can now ask their natural question. Kareem Abdul-Jabbar is identified
  from his basketball career, and Michael Dukakis from his political career, without
  forcing an incidental associated answer.
- The Sistine Chapel questions now identify the chapel when asking about Michelangelo
  or *The Last Judgment*. The clarinet inventor question no longer names its answer
  in the clue. The castling questions no longer give away the requested piece.
- Several answer policies are more generous: “Mogul” is accepted for Project Mogul,
  and “93” for United Airlines Flight 93. Nearly all prompt lists are empty.
- The Birds set now stays within biology. The writer again noticed the erroneous
  source definition of cosine and avoided using it.

## Remaining issues and concrete examples

**Choose a recognizable target, not an arbitrary phrase.** Self-portrait 6.4 asks
what a studio portrait can demonstrate, expecting “artistic skill.” Talent,
technique, style, and likeness are all plausible responses. Night 22.4 expects
“loss of faith” after describing erosion of religious belief. Phillips curve 50.2
asks for a long paraphrase of the same relationship tested by the preceding item.
These should be rewritten around distinct, conventionally named targets.

**Compare actual accepted answers across the set.** Victor Frankenstein 21.1 and
the novel in 21.2 are different concepts, but both accept “Frankenstein.” Replace
one target rather than reject a valid short answer. Mere string difference between
canonical answers is not enough. Historical materialism 52.2 also remains weakly
distinguished from broader Marxism or conflict theory.

**Remove answer leakage, including aliases.** Makeup accepts the word “cosmetics”
already supplied in its stem. The law-of-cosines question supplies and accepts
“Al-Kashi theorem.” The d20 question describes a twenty-sided die and accepts that
description despite asking for shorthand. Mesopotamia 17.2 effectively asks students
to concatenate “Tigris,” “Euphrates,” and “river system.”

**Finish the answer policies and standalone context.** Examples include missing
“de Armas,” “Ferdinand II,” and the chemical symbol F. September 11 question 63.5
still says only “the attacks” before asking which country was invaded. These
repairs are generally smaller than the target-selection problems.

**Source grounding does not guarantee correctness.** TikTok 33.1 treats Douyin as
an alias, although ByteDance describes separate global and China-market products.
The clues also need better discrimination between video platforms.
[ByteDance history](https://www.bytedance.com/?lang=en).
The Vowels question repeats source language saying the IPA standardizes pronunciation;
it should refer to representation of speech sounds, consistent with the IPA's
cross-language materials. [IPA handbook materials](https://www.internationalphoneticassociation.org/node/125).
Phillips 50.3 needs to distinguish the original wage-change relationship from later
price-inflation formulations. [Federal Reserve research](https://www.federalreserve.gov/econres/feds/the-wage-curve-and-the-phillips-curve.htm).

The automatic validator accepted 67/69 topic outputs. One failure is the genuine
Frankenstein accepted-answer collision. The other is a **checker false positive**:
case-folding collapses uppercase Π (product notation) into lowercase π (the circle
constant). Those targets are mathematically distinct. Raw validation results were
preserved; symbol-sensitive handling needs repair before using this checker as an
automatic publication gate. The Pi question also has a separate answer-policy issue
with accepting the generic phrase “product symbol.”

## Cost and next step

At the recorded [GPT-6 Luna prices](https://developers.openai.com/api/docs/models/gpt-6-luna),
the pilot cost an estimated **10.59¢**, 42.6% more than v1, or **3.16¢ extra**.
The stratified full-generation projection is **$7.32 standard / $3.66 Batch** for
7,072 topics and 10,976 questions. These are usage-based estimates, not invoices;
the Batch projection assumes the applicable discount and observed token/cache mix.
They exclude independent review, repair, retries, and any future pricing changes.
One topic per stratum does not support a tight cost confidence interval; the rare
largest source contexts remain untested.

Keep high reasoning and the demonstrations. Before scaling, add examples explicitly
contrasting a named concept with an arbitrary prose answer, and a set with different
canonical names that nevertheless share an accepted answer. Use an independent
review/repair pass to inspect standalone answerability, alternate valid answers,
source support, and semantic duplicates. Check the next prompt on fresh held-out
topics, including the longest source contexts. More generation tokens alone are
unlikely to fix these editorial problems: none of this run's responses hit its limit.

## Artifacts and verification

Original v2 outputs, frozen request bodies, examples, prompt, usage, hashes, the
per-question editorial ledger, and the comparison metrics are in the ignored local
directory `research/typed-questions/pilot-2026-09-25-v2/`. The review page is
`review.html`; a text rendition is `questions.md`. Generated questions were not
silently edited to improve the results. V1 artifacts were retained.

Run the existing review renderer with:

```sh
python3 scripts/render_typed_question_pilot.py --run-dir research/typed-questions/pilot-2026-09-25-v2
```

The generator supports separate `--version v1` / `--version v2` manifests and checks
frozen prompt, examples, schema, and source-data hashes before a run. Pilot tests
cover preserved sampling, the relaxed topic-name rule, duplicate alias rejection,
and the actual few-shot request shape and high-reasoning settings.

All original multiple-choice questions and authoritative `data/` JSON files remain
unchanged. No application behavior was changed and no full Batch run was submitted.
