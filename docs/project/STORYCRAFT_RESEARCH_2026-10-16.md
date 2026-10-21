# Storycraft research, 2026-10-16

The Owner ran `/deep-research` on 2026-10-16 with this question: how does a short video story get
written so that a stranger understands it and watches to the end? It covered the factual shorts
(60-180 s), the narrated office serial (90-180 s), the vertical grammar of 4-second AI shots and
the craft playbooks that measurably improve a language model's writing.

The workflow ran 104 agents and read 22 sources. It extracted 109 claims and verified 25, each
with three adversarial votes. 17 survived and 8 were refused. This note keeps what survived,
says what it changes for the studio, and lists what the research could not answer.

The raw report is in the session's scratchpad, not in the repository. This note is the record.

## What survived, by role

### Showrunner (the serial)

- **The narrator orients and jokes at once.** In *Arrested Development*, the voice in off and a
  cutaway recall what happened before and make a joke in the same breath (Mittell, *Complex
  Television*, NYU Press 2015, pp. 184-185; vote 3-0). The serial's v8 opening narrator
  (2026-10-16) can do the same: say where we are and what is at stake, and be funny doing it.
  The source's example is a recap in the middle of an episode. Using it at the opening is our
  design inference.
- **Without craft scaffolding, a model stays far below professional level.** On 14 binary craft
  tests (TTCW), stories written by 2023 models passed 3 to 10 times fewer tests than *New Yorker*
  stories (Chakrabarty et al., CHI 2024; vote 3-0). A newer paper (arXiv 2510.13939) finds that
  ordinary readers can prefer prompted model text even while experts do not. The studio's
  audience is ordinary readers, so the judge must be calibrated on that audience.

### Script writers (Showrunner, factual ScriptWriter, Kael's prompts)

- **A prohibition in the writing prompt does not stop clichés.** GPT-4o, Claude 3.5 Sonnet and
  Llama 3.1 70B all produced clichés although the prompt explicitly told them not to (LAMP,
  CHI 2025; vote 3-0). In a single-model preprint, a "do not use X" instruction is broken more
  often the more strongly the context invites X (arXiv 2601.08070; vote 2-1).
- **A targeted edit pass measurably improves the text.** The method has two steps. First, mark the
  weak passages using a 7-category craft taxonomy:
  1. cliché;
  2. unnecessary exposition;
  3. purple prose;
  4. poor sentence structure;
  5. lack of specificity;
  6. awkward word choice;
  7. tense inconsistency.

  Then rewrite only those passages. Experts ranked the LLM-edited text clearly above the raw text
  (Wilcoxon p = 2.8e-13). Passages detected automatically worked almost as well as passages marked
  by experts (LAMP; vote 3-0). Experts agreed on *which* passages were weak (precision 0.57) far
  more than on *what kind* of defect they had (0.23).
- **"Slop" can be measured.** Compare the frequency of words, bigrams and trigrams in the
  model's text with a human corpus of the same genre. Some patterns appear more than 1,000 times
  more often in model text (Antislop, arXiv 2510.15061; vote 3-0). The fingerprints depend on
  the domain, so they must be profiled on the studio's own texts.

### The Director as judge

- **An uncalibrated LLM judge does not match experts.** On TTCW, the 2023 judges' agreement with
  the expert majority was practically zero (mean Cohen's kappa 0.016 / 0.035 / -0.006). A few
  examples in the prompt did not help much (vote 3-0). Newer work agrees: zero-shot judges were
  near chance on writing quality, and judges trained on human labels reached about 74%
  (arXiv 2504.07532). **Her agreement with the Owner must be measured, not assumed.**
- **Thinking step by step does not automatically help a writing judge.** It can lower accuracy:
  78% fell to 72% in LitBench (EACL 2026; vote 3-0). Measure it before relying on it.
- **A robust rubric is binary tests with a short justification, summed, with no single veto.**
  Experts agreed moderately on single tests (Fleiss kappa 0.41) and strongly on the total
  (Pearson 0.69). Not even the *New Yorker* stories passed every test (TTCW; vote 3-0).
- **Order changes scores.** The order of the criteria and of the score options moves a judge's
  marks. Averaging over 3 balanced permutations recovers 70% of the correlation gain of 10
  orderings, and 5 permutations recover 87%. Repeating the same order recovers 8% (Xu et al.,
  Findings EMNLP 2026; vote 3-0). The absolute gains are small.
- **A pairwise judge must see both orders.** Judges flip their preference when the order of the
  two options is swapped: GPT-4 in 25% of cases, GPT-3.5 in 58% (arXiv 2404.13076; vote 2-1).
  Run both orders. Treat a preference that flips as a tie, as MT-Bench does.

## What the research refused

These claims were refused, so they stay design hypotheses, not facts:

- the callback as the basis of a running gag (0-3);
- the "pink elephant" effect as proof that positive examples beat prohibition lists (1-2);
- a judge preferring its own text, and author labels changing verdicts (0-3).

"Positive examples instead of prohibitions" is therefore suggested by the sources, not proved.
The studio should A/B test it.

## What the research could not answer

No claim survived about:

- the hook;
- orienting the viewer in the first 8-10 s;
- retention;
- the end loop;
- the vertical montage grammar of 4-second AI shots: wide-medium-close order, reaction shots,
  continuity, camera moves.

The Video Editor's craft, and half of the shorts writer's, have no verified basis here. The
studio's own **YouTube retention curves** are the better source for these, once they can be read.

## What it changes in the plan

1. **Playbooks describe what to do**, with worked positive examples and category-level rules.
   Lists of forbidden words move from the writing prompt to a check after writing (the lint
   and the judge).
2. **The Director marks passages, then the writer rewrites only those.** This is the LAMP edit
   pass, using its 7 categories. It replaces whole-script rewrites driven by a score.
3. **The editorial rubric becomes yes/no tests, each with a one-to-three-sentence
   justification, summed.** The rubric covers the hook, clarity, the moment, the punchline and
   the follow. No single criterion vetoes a script, except the hard rules the Owner set: the 180 s
   wall, faceless, no duplicate subject.
4. **Calibration before trust.** Freeze a set of past scripts with the Owner's verdicts, measure
   the judge's agreement with him, and permute the criteria order 3 times. A pairwise comparison
   runs in both orders.
5. **A slop profile of the studio's own texts** gives the lint a measured list instead of a
   guessed one.
6. **Retention from YouTube Analytics** answers the hook and pacing questions with the studio's
   own data. It needs the Owner's authorisation of the analytics scope.

## Sources (primary unless marked)

- Mittell, *Complex Television* (NYU Press, 2015), excerpt:
  https://scalar.usc.edu/works/complex-television/arrested-development-uses-voiceover-and-cutaways-to-both-manage-memory-and-create-humor
- Chakrabarty et al., *Art or Artifice?* (CHI 2024): https://arxiv.org/abs/2309.14556
- Chakrabarty, Laban, Wu, *LAMP* (CHI 2025): https://arxiv.org/abs/2409.14509
- *Semantic Gravity Wells* (preprint, single author, single model): https://arxiv.org/abs/2601.08070
- Paech et al., *Antislop* (preprint): https://arxiv.org/abs/2510.15061
- Fein et al., *LitBench* (EACL 2026): https://arxiv.org/abs/2507.00769
- Xu et al., criteria and option order in rubric judging (Findings EMNLP 2026):
  https://arxiv.org/abs/2602.02219
- Panickssery, Bowman, Feng (2024), position bias: https://arxiv.org/pdf/2404.13076
- Zheng et al., MT-Bench (2023): https://arxiv.org/pdf/2306.05685
