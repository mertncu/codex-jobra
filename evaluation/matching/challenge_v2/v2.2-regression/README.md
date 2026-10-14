# Matching reliability regression — V0.2.2

This run reuses the frozen V0.2.1 18-case synthetic inputs and labels. It does
not modify `inputs.v2.json`, `labels.v2.json`, the V1 unblinded baseline, or the
V0.2.1 blind report. The clean prediction task receives only the 18 synthetic
profiles, preferences, opportunities, source evidence, deterministic reference
catalogs, and the documented matching contract/schema. It does not receive the
labels, previous predictions, reports, or evaluator.

## Root causes addressed

- Candidate record/evidence references were left to free-form agent output. The
  earlier run attached candidate evidence to `not_evidenced` claims and selected
  unrelated but valid references. Jobra now generates a provenance-preserving
  catalog of eligible record/evidence IDs; the validator rejects unknown,
  unaccepted, unlinked, and obviously irrelevant direct references.
- Career alignment used free-form preference terms, so locations, seniority,
  work arrangements, and excluded roles were mistakenly submitted as preferred
  careers. The catalog gives stable field-qualified preference refs, and Python
  resolves only preferred-role references.
- Requirement IDs had no deterministic source. The catalog now assigns `r1`,
  `r2`, … from description evidence order. The validator rejects IDs outside
  those slots; the evaluator aligns labels to outputs by source evidence IDs.
- Hard filters ran only after the entire semantic assessment passed. The new
  pipeline validates source inputs first, calculates explicit exclusions
  independently for every opportunity, and reports semantic failure separately.
- There was no controlled repair route. The pipeline supports at most one
  repair document, keeps each original assessment and its path/code diagnostics
  in the private immutable output, and never substitutes references or changes
  classifications on its own.

## Reproduce

1. Run all tests and skill validation before freezing.
2. Build the local prediction-only package and freeze it:

   ```sh
   .venv/bin/python evaluation/matching/challenge_v2/v2.2-regression/build_prediction_package.py --workspace .
   .venv/bin/python evaluation/matching/challenge_v2/v2.2-regression/freeze.py \
     --package <exact-package-path-printed-above>
   ```

3. In a new projectless Codex task, provide the package, `matching-assessment`
   schema, and matching contract only. Ask for one JSON prediction per opaque
   case. Use only requirement slots and catalog references; do not read the
   challenge label file or any report. Store primary predictions locally.
4. If performing repair, supply the exact fixed validator paths/codes and same
   catalog to Codex once. Store repaired outputs separately; never replace the
   primary prediction.
5. After predictions are frozen, run `score_v2.2.py`; it checks frozen hashes,
   scores labels separately, and emits private machine/human reports. Publish
   only the reviewed synthetic report and failure register.

The report gives first-pass validity, post-repair validity, end-to-end
aggregation, evidence-reference integrity, independently labeled support,
hard-filter execution/correctness, and classification separately with exact
denominators. Reference existence is not semantic sufficiency. Ambiguous
golden support labels remain excluded and separately counted. A passing
structure score is not evidence of semantic accuracy.

The run reuses the existing synthetic challenge rather than adding labels
optimized against prior predictions. New unseen challenge cases are deferred;
the regression goal here is comparable measurement on the frozen case set.


## Observed run

The frozen 18-case run completed in six separate projectless Codex tasks. A selected `case_01` repeat in a separate task matched the primary requirement classification and candidate evidence references (1/1 selected cases). One earlier repeat attempt was excluded because the prompt did not include the exact assessment schema; the corrected repeat passed aggregation. This small repeat is descriptive, not an accuracy estimate. See `report.v2.2.md` for the recorded task IDs and metrics.
