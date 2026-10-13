# Matching evaluation

`benchmark.v1.json` contains synthetic, versioned candidate profiles, explicit
search preferences, opportunity snapshots, and source evidence. The separately
authored `golden.v1.json` records expected requirement classifications,
evidence references and support judgments, hard-filter outcomes, and required
uncertainty warnings. Golden labels are never matching inputs.

## Reproduction

Regenerate only the benchmark inputs with:

```sh
.venv/bin/python evaluation/matching/build_benchmark.py
```

For an agent evaluation, give Codex the benchmark inputs and matching
instructions in a fresh context, one or more cases at a time. Do not include,
mount, or refer to `golden.v1.json` or previous predictions in that context.
Save each interpretation and deterministic result as a case JSON under
ignored `.jobra/evaluations/matching/<run-id>/predictions/`; run the normal
matching validator and result builder before saving. Then, in a separate
evaluation context, run:

```sh
.venv/bin/python evaluation/evaluate_matching.py \
  --predictions .jobra/evaluations/matching/<run-id>/predictions \
  --workspace . --date YYYY-MM-DD
```

The runner reads the benchmark and golden labels, writes create-only JSON and
Markdown reports under ignored `.jobra/evaluations/`, and does not modify
predictions or fixtures. Prediction files have this shape: `case_id`,
`assessment`, and `result` (the result emitted by Jobra's deterministic
aggregator). The CLI exits only after completing the report; validation
failures are represented in the report with privacy-safe categories.

## Metrics and limits

Classification accuracy uses all golden requirements as its denominator;
missing predicted requirements count as errors. Precision/recall treat
`matched` and `inferred_support` as positive, with inferred support kept
separate in the confusion matrix. Evidence-reference validity is the fraction
of attempted assessment cases whose requirement, experience, and career
references all exist and link to accepted records. Evidence-support accuracy is a
separate strict check against independently specified expected candidate
evidence IDs; ambiguous gold support is excluded and counted separately.
Missing benchmark predictions appear as a `missing_prediction` confusion column.
Unmatched predicted requirement IDs are listed per case and remain unadjudicated;
the scorer does not assume they are correct extras or unsupported claims.
Hard-filter correctness evaluates deterministic aggregation of explicit user
constraints. Explanation completeness checks required fields and warning
presence, not semantic persuasiveness. Schema compliance validates the
interpretation, not the quality of Codex's semantic judgment.

The public example report is a deterministic demonstration over synthetic
predictions. It is not evidence of an independently blinded agent evaluation.
Task 5's local run was prepared in one Codex context after it had inspected the
benchmark source, so it is explicitly marked unblinded; do not report it as an
independent agent benchmark. The golden labels were authored from the source
facts rather than copied from matching-engine output, but no external human
adjudicator reviewed them. This small fixture suite is not a production
readiness or real-world accuracy claim.

## Reliability coverage

Automated tests exercise stable repeated aggregation, invalid evidence
references, missing requirements, incomplete profile evidence, injection text
as untrusted data, create-only snapshots, and input immutability. They test
deterministic contracts; they do not establish that Codex's semantic
interpretation is correct.

## Previous live pilot: observational case study

The earlier local pilot assessed eight opportunities using 12 stored
requirements. Those records were partial requirement summaries, not necessarily
complete job descriptions, and are not ground truth. The profile's proficiency
levels and several job details were unknown. The local result had seven direct
evidence matches, two inference-dependent matches, and three not-evidenced
requirements; these are descriptive output counts only.

Human review is particularly useful for inferred technology equivalence,
country eligibility for worldwide remote roles, conflicting experience
language, unknown work arrangement/seniority, and inaccessible or stale source
pages. No pilot result is scored here because no independent requirement labels
exist. Historical snapshots and private profile files are not read by the
benchmark runner.

## Observations and next improvements

The current synthetic run had no classification, reference, hard-filter,
uncertainty-warning, or deterministic aggregation failures. That result is
weak evidence because the run was unblinded, the benchmark is small, and its
labels were not independently adjudicated. The useful next steps are to repeat
the predictions in a fresh Codex context that cannot access the golden file,
have a human review the golden labels and evidence-support judgments, and add
more cases with long postings, multiple equivalent-but-not-identical evidence
references, and conflicts between candidate evidence records. These improve
measurement coverage rather than tuning a single aggregate score.
