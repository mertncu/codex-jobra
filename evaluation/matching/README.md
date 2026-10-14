# Matching evaluation

The latest blind semantic challenge is documented in
[`challenge_v3/v2.3.1-semantic/README.md`](challenge_v3/v2.3.1-semantic/README.md).
The first V2.3 freeze is retained as an aborted audit record in
[`challenge_v3/v2.3-semantic/ABORTED.md`](challenge_v3/v2.3-semantic/ABORTED.md):
its reference catalog exposed metadata as requirement slots, so no scores were
produced. V2.3.1 fixes that catalog defect and uses new hashes and clean
projectless prediction sessions. The source-first golden labels have not
received independent human adjudication.
The review packet for V2.2 `case_07`, `case_11`, and six ambiguous support
judgments remains pending at
[`human-review-packet.v2.3.md`](challenge_v3/v2.3-semantic/human-review-packet.v2.3.md).
The V2.3.1 report and failure register record the new blind run.

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
references all exist and link to accepted records, with candidate references
consistent with the outcome (for example, `not_evidenced` has no candidate
references). Evidence-support accuracy is a
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

V2.3.1 reached 7/13 exact classifications on non-ambiguous requirements,
5/13 adjudicated evidence-support judgments, and 4/9 precision for positive
support claims. Five unsupported positive inferences drove most semantic
errors. Hard-filter execution and correctness were 18/18. One of 18 assessments
failed aggregation because a cited candidate evidence item was not linked to a
record, and one case emitted an extra requirement slot. The run was blinded at
prediction time, but the small source-first label set and rationales still need
human adjudication. See its report and failure register before using these
figures to guide further changes.
