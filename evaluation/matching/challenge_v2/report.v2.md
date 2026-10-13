# Blinded Matching Evaluation — V0.2.1

Dataset: `matching-challenge-v2` · cases: 18 · date: 2026-10-13
Prediction run: `a9f657cb474e452b978366b77a18f2ee` · session: `01a13583-8203-71d1-82c4-a883017c9739`
Frozen: 2026-10-13T13:45:08+00:00 · predicted: 2026-10-13T13:48:26+00:00 · evaluated: 2026-10-13T14:05:12+00:00
Hashes:
- Input SHA-256: `1d97e3443e933a14bf0932eeb92ca5198273eeaa0ce7a708f72a9445a61c2cf3`
- Golden SHA-256: `26de98f623b833df4434531be618a84c3fe89319cd3fa89cd031f2acc684d4a3`
- Prediction SHA-256: `290bcdf9f6b8a360a22dc54dae41a7aee9494cc5f16bd43e1fab9a2c3a54150e`

Predictions came from a separate clean projectless Codex task. It received only synthetic inputs and the matching contract; golden labels, prior reports, and evaluator output were not in its context.

## Metrics

| Measure | Numerator / denominator | Rate |
|---|---:|---:|
| Requirement classification exact accuracy | 11/12 | 0.917 |
| Supported-match precision | 5/5 | 1.000 |
| Supported-match recall | 5/5 | 1.000 |
| Evidence-reference integrity (assessment level) | 10/18 | 0.556 |
| Semantic evidence support (adjudicated only) | 3/12 | 0.250 |
| Hard-filter end-to-end success | 4/18 | 0.222 |
| Hard-filter correctness when aggregation ran | 4/4 | 1.000 |
| Explicit exclusion end-to-end success | 0/2 | 0.000 |
| Explicit exclusion case coverage | 0/2 | 0.000 |
| Explicit exclusion accuracy when scored | 0/0 | n/a |
| False unsupported-match rate | 0/5 | 0.000 |
| Not-evidenced handling recall | 6/6 | 1.000 |
| Explanation completeness (structural) | 4/18 | 0.222 |
| Schema/invariant compliance | 4/18 | 0.222 |
| Deterministic aggregation reproducibility | 4/18 | 0.222 |

Ambiguous evidence-support labels excluded from classification/support accuracy: 6.
Ambiguous support judgments: 6. Unmatched requirement predictions: 2, including 1 positive prediction(s) left unadjudicated.
Hard-filter end-to-end success counts invalid assessments as unsuccessful because deterministic filtering could not produce a result. The conditional metric shows only cases where aggregation completed.

### Per-class precision and recall

| Class | Precision | Recall |
|---|---:|---:|
| matched | 4/4 (1.000) | 4/5 (0.800) |
| inferred_support | 0/1 (0.000) | n/a |
| not_evidenced | 6/6 (1.000) | 6/6 (1.000) |
| contradicted | 1/1 (1.000) | 1/1 (1.000) |
| cannot_assess | n/a | n/a |

### Confusion matrix (ambiguous expected labels excluded)

| Expected \ Predicted | matched | inferred_support | not_evidenced | contradicted | cannot_assess | missing |
|---|---:|---:|---:|---:|---:|---:|
| matched | 4 | 1 | 0 | 0 | 0 | 0 |
| inferred_support | 0 | 0 | 0 | 0 | 0 | 0 |
| not_evidenced | 0 | 0 | 6 | 0 | 0 | 0 |
| contradicted | 0 | 0 | 0 | 1 | 0 | 0 |
| cannot_assess | 0 | 0 | 0 | 0 | 0 | 0 |

## Per-case results

| Case | Status | Exact category | Hard filter checked | Failure codes |
|---|---|---:|---|---|
| case_01 | evaluated | 1/1 | True | — |
| case_02 | invalid_prediction | 1/1 | False | schema_or_invariant_failure:not_evidenced_requirement_has_candidate_reference |
| case_03 | evaluated | 1/1 | True | — |
| case_04 | invalid_prediction | 0/0 | False | schema_or_invariant_failure:not_evidenced_requirement_has_candidate_reference |
| case_05 | invalid_prediction | 1/1 | False | schema_or_invariant_failure:unknown_preference_reference, required_uncertainty_warning_missing |
| case_06 | invalid_prediction | 0/0 | False | schema_or_invariant_failure:unknown_preference_reference, required_uncertainty_warning_missing |
| case_07 | invalid_prediction | 0/1 | False | schema_or_invariant_failure:unknown_preference_reference |
| case_08 | invalid_prediction | 1/1 | False | schema_or_invariant_failure:unknown_preference_reference, required_uncertainty_warning_missing |
| case_09 | invalid_prediction | 0/0 | False | schema_or_invariant_failure:unknown_preference_reference, required_uncertainty_warning_missing |
| case_10 | evaluated | 1/1 | True | — |
| case_11 | invalid_prediction | 0/0 | False | schema_or_invariant_failure:unknown_preference_reference, required_uncertainty_warning_missing |
| case_12 | evaluated | 1/1 | True | — |
| case_13 | invalid_prediction | 0/0 | False | schema_or_invariant_failure:unknown_preference_reference |
| case_14 | invalid_prediction | 1/1 | False | schema_or_invariant_failure:not_evidenced_requirement_has_candidate_reference |
| case_15 | invalid_prediction | 1/1 | False | schema_or_invariant_failure:unknown_preference_reference |
| case_16 | invalid_prediction | 1/1 | False | schema_or_invariant_failure:unknown_preference_reference |
| case_17 | invalid_prediction | 1/1 | False | schema_or_invariant_failure:unknown_preference_reference |
| case_18 | invalid_prediction | 0/0 | False | schema_or_invariant_failure:unknown_preference_reference, required_uncertainty_warning_missing |

## Failure register

See [failure-register.v2.md](failure-register.v2.md) for expected behavior, observed behavior, severity, root-cause hypotheses, and regression proposals.

## Repeatability

Six selected cases were assessed in another clean task: category agreement 6/6; candidate evidence-reference agreement 3/6; schema-valid outputs 1/6 primary and 2/6 repeat.
Agreement is consistency only. One earlier repeat task was unscorable because its prompt did not include the requested output schema; it is recorded in the repeatability artifact.

## Limits

Golden labels were frozen before predictions and authored from synthetic source records without using matcher predictions. They have not received independent human adjudication. The benchmark is small and synthetic; these results are not production readiness or real-world accuracy claims.
The earlier eight-opportunity pilot remains observational only: 12 saved requirements were partial summaries, not ground truth. No private profile or historical opportunity snapshot was used.
