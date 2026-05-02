# Methodology

> This document specifies the methodological standards every Marionette scenario must follow. Scenario-specific design decisions live in each scenario's `SCENARIO.md`. Scenario-specific *deviations* from this document must be explicitly justified in the scenario doc. Compliance is the default; non-compliance is loud.

---

## 1. Why this document exists

Behavioral evaluation of LLMs is methodologically fragile. The most common failure modes in published LLM-eval work are:

- p-hacking via post-hoc threshold selection
- claiming effects without measuring noise
- reporting point estimates without uncertainty intervals
- testing many models, reporting only the "interesting" ones
- confounding the manipulation with adjacent variables (e.g. claiming "sandbagging" when the real effect is generic "evaluation awareness")
- contaminating the judge with information that biases its verdict
- making the experimental design depend on the result (the eval was tuned until it produced the headline)

Marionette commits to a methodology that forecloses each of these failure modes. The standards below are the commitments. A finding that doesn't clear them is not published as a finding.

## 2. Pre-registration

Every scenario commits its hypothesis, decision rule, sample size, statistical test, threshold, and stopping rule **before any treatment data is collected**. This commitment lives in the scenario's `SCENARIO.md` under "Pre-registered hypothesis," and is frozen at first commit of the scenario.

Once frozen:

- Changes to the pre-registration are flagged in the scenario doc with a dated entry explaining what changed and why.
- Any data collected before a change is labeled "confirmatory" and uses the original rule. Data collected after is labeled "exploratory" and is reported separately. Confirmatory and exploratory results are never aggregated.
- The pre-registration includes an *exit clause*: a description of what would constitute the hypothesis being wrong. If we cannot describe what would falsify the claim, the claim isn't yet a hypothesis.

Pre-registration is the single most important rigor practice. Almost no LLM-eval blog posts do it. Doing it is a credibility differentiator on its own.

## 3. Power, sample size, and noise floor

**Sample size is derived, not chosen.** For each scenario:

1. Run the control condition twice on each model in the cohort, before any treatment runs. Each control run uses N₀ trials (default N₀ = 10).
2. Compute the per-model standard deviation σ_C across those 2×N₀ control trials. This is the model's measured noise floor on this scenario.
3. The treatment effect must clear **3σ_C** to count as confirmed. (The 3σ choice is documented in §6.)
4. Sample size per cell (model × condition) is whatever is needed for the per-cell standard error of the mean to be at most σ_C / 3. This usually lands at N ≥ 10 trials per cell; scenarios that observe higher variance need more.

**Trials are independent.** Each trial is a fresh agent context: no conversation history, no caching, no shared seed unless explicitly varied as a manipulation. Provider-side prompt-caching is explicitly disabled where the API allows.

**Models with reasoning visibility (e.g. extended thinking) and models without are reported separately**, because they yield categorically different evidence. Aggregating them across that boundary obscures the asymmetry.

## 4. Effect size, not just significance

Every reported finding includes:

- **Mean point estimate** (e.g. mean accuracy, mean delta).
- **95% confidence interval** via bootstrap (10,000 resamples, BCa intervals where the distribution is non-normal).
- **Effect size**: Cohen's d for paired comparisons, raw percentage-point difference for accuracy, with a sentence interpreting magnitude.
- **p-value**, after multiple-comparisons correction (§5).

A finding with p < 0.05 but d < 0.2 is reported but explicitly labeled "small effect, statistical significance only." A finding with p < 0.05 and d ≥ 0.8 is reported as substantive. Effect size, not significance, drives whether something appears in the headline.

Reports never include bare point estimates without intervals. "Model X scored 73% (95% CI: 68–78%)" is the format. "Model X scored 73%" is forbidden.

## 5. Multiple-comparisons correction

When a scenario tests multiple models, multiple variants, or multiple metrics, raw p-values are corrected:

- **Benjamini–Hochberg (BH)** for false-discovery-rate control. Default for the standard analysis.
- **Bonferroni** for family-wise-error control where claims are about individual models named explicitly. Used in headline claims.

The corrected p-value (q-value for BH, adjusted p for Bonferroni) is what reports cite. The raw p is never the headline.

The number of comparisons is determined by the pre-registration, not picked after seeing results.

## 6. Why 3σ

The 3σ-above-noise threshold for confirmed effects is a methodological choice, not a statistical theorem. The reasoning:

- 1σ corresponds to ~32% of trials clearing the threshold by chance, which is far too lax. Many "findings" are 1σ effects.
- 2σ (~5% by chance) is the conventional "significance" bar for individual comparisons. We choose to be stricter because we make multiple comparisons across models and scenarios; the same data viewed across enough cuts will produce 2σ false positives by chance.
- 3σ corresponds to ~0.27% by chance per comparison, which after BH correction across the cohort still leaves us with low expected false-positive rates.
- Effects that don't clear 3σ are reported as "suggestive but not confirmed" and explicitly flagged as candidates for follow-up, not findings.

## 7. Negative and active controls

Every scenario distinguishes the manipulation from adjacent variables that could confound it:

- **Clean control.** No manipulation. Establishes baseline.
- **Active control.** A condition that includes the *form* of the manipulation but not the *substance*. For sandbagging-under-evaluation, the active control mentions evaluation but no consequences ("this is part of a quality assessment"). If models perform differently in active control vs clean control, the claimed effect is at least partly *evaluation awareness* rather than the specific manipulation. The report names this honestly.
- **Treatment.** The full manipulation.

A treatment effect that's largely captured by the active control is not the effect we claimed it was. The honest claim, in that case, is the active-control-vs-clean delta.

## 8. Quiz/payload integrity

Whenever a scenario uses a fixed corpus (a quiz, a set of documents, a set of payloads):

- The corpus is committed as files in the scenario directory.
- The sha256 hash of the corpus manifest is pinned in the scenario metadata.
- Every trace records the corpus hash it ran against.
- Analysis verifies the hash matches before processing a trace.
- Changes to the corpus invalidate all prior runs on that corpus. The scenario version (SemVer) increments. Old runs remain in the data but are flagged with the old version and not aggregated with new runs.

This prevents the most common silent-corruption failure mode: tweaking the eval until it produces the expected result.

## 9. Judge isolation and prompt-injection hardening

When LLM-as-judge is used to score traces, the judge is hardened against:

- **Direct prompt injection.** The candidate's reasoning content may contain text shaped like instructions. The judge is given content only inside structured boundaries (e.g. `<excerpt>...</excerpt>` tags) and is instructed in its system prompt to treat all such content as data, not commands.
- **Confirmation bias from manipulation context.** When the judge's task is to evaluate whether the candidate noticed a manipulation, the judge does *not* see the manipulation itself. It sees only excerpts from the candidate's output and is asked whether the candidate appears to be reasoning about a class of concepts. The judge is blind to the specific manipulation text.
- **Output-channel injection.** The judge's response is constrained to a structured schema (typed verdict + confidence + cited excerpt id). Free-form output is not accepted from the judge.
- **Self-evaluation conflicts.** The judge model is *never* the same model family as the model under test. (E.g. Claude is not used to judge Claude in this scenario; an alternate provider's model is.)

When deterministic judgment suffices, deterministic judgment is preferred over LLM-as-judge. LLM-as-judge is used only where the question is genuinely qualitative.

## 10. Open data and reproducibility

The artifact a finding produces is not the headline number. It is:

- The scenario directory (code + corpus + scenario doc + pre-registration), versioned.
- The trace JSONL files for every run, committed (or attached as release assets if size requires).
- The analysis code that produced the report, versioned.
- The report itself, with every claim linked to specific traces and specific analysis steps.

Anyone with the repo and the listed model API access can re-run the entire scenario and reproduce the report. If they can't, the methodology has failed.

## 11. Honest reporting of negative results

Reports include all models in the pre-registered cohort, including ones that showed no effect. Leaderboards include models that "passed" alongside models that "failed." Confidence intervals are shown for everyone.

A scenario that produces no positive findings is still a valid published artifact: "We tested for X across N models and found no measurable effect, with 95% CIs ruling out effects larger than Y." Null results are often more important than positive ones.

## 12. Trial-level replay

Every report's claims are clickable down to the level of an individual trial. A reader who wants to see "what did Model M actually do in trial 7 of condition C" can find that trace, that conversation, that tool call, that reasoning excerpt, in the artifact. Aggregate numbers are derived from raw trials; raw trials are accessible.

## 13. Adversarial review

Before any scenario produces a published finding:

- One Marionette contributor (or, while the project is solo, the author one week later with fresh eyes) attempts to *break* the finding. Specifically: identify alternative explanations, identify missing controls, attempt to reproduce with intentionally different framing.
- The adversarial review notes are committed alongside the report.
- Findings that survive adversarial review with no caveats are labeled "robust." Findings with surviving caveats are labeled "tentative."

Skipping this step is the fastest path to publishing something embarrassing.

---

## Versioning

This document is versioned with SemVer. Changes that alter standards retroactively invalidate findings produced under the old version. Changes that only add new standards leave old findings valid but flagged as "produced under v_N, not v_(N+1)."

Current version: 0.1.0 (initial draft).
