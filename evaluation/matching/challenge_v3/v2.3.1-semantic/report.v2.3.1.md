# Matching Evaluation matching-challenge-v2.3.1-semantic

Date: 2026-10-14 · Cases: 18
Agent context: separate_clean_projectless_codex_tasks

| Metric | Result |
|---|---:|
| Exact requirement classification | 7/13 (0.538) |
| Supported match precision | 4/9 (0.444) |
| Supported match recall | 4/4 (1.000) |
| Evidence reference validity | 17/18 (0.944) |
| Adjudicated evidence support accuracy | 5/13 (0.385) |
| Hard-filter execution | 18/18 (1.000) |
| Hard-filter correctness | 18/18 (1.000) |
| False unsupported-match rate | 5/9 (0.556) |
| Not-evidenced handling recall | 3/8 (0.375) |
| Explanation completeness (structural) | 17/18 (0.944) |
| First-pass schema/invariant validity | 17/18 (0.944) |
| Post-repair schema/invariant validity | 17/18 (0.944) |
| Schema/invariant compliance | 17/18 (0.944) |
| End-to-end aggregation success | 17/18 (0.944) |
| Aggregation reproducibility | 18/18 (1.000) |

Ambiguous evidence judgments excluded: 5

| Case | Status | Exact labels | Hard filter | Uncertainty omissions |
|---|---|---:|---|---:|
| case_01 | evaluated | 1/1 | True | 0 |
| case_02 | evaluated | 0/1 | True | 0 |
| case_03 | evaluated | 0/1 | True | 0 |
| case_04 | evaluated | 0/0 | True | 0 |
| case_05 | evaluated | 0/1 | True | 0 |
| case_06 | evaluated | 0/1 | True | 0 |
| case_07 | evaluated | 1/1 | True | 0 |
| case_08 | evaluated | 0/1 | True | 0 |
| case_09 | evaluated | 1/1 | True | 0 |
| case_10 | evaluated | 0/1 | True | 0 |
| case_11 | evaluated | 0/0 | True | 0 |
| case_12 | evaluated | 0/0 | True | 0 |
| case_13 | evaluated | 1/1 | True | 0 |
| case_14 | evaluated | 0/0 | True | 0 |
| case_15 | evaluated | 1/1 | True | 0 |
| case_16 | invalid_prediction | 0/0 | True | 0 |
| case_17 | evaluated | 1/1 | True | 0 |
| case_18 | evaluated | 1/1 | True | 0 |

## Limitations

- Small synthetic benchmark; no real-world performance claim.
- Evidence support accuracy excludes ambiguous judgments.
- Predictions came from six separate clean projectless Codex tasks; no task received golden labels, prior reports, or predictions.
- Golden labels have not received independent human adjudication.
- Explanations are checked for required structure, not semantic quality.

## Semantic explanation review

No explanation received independent human adjudication; 18 requirement explanations remain unresolved. The structural explanation-completeness rate is reported separately.

## Classification detail

| Gold class | Precision | Recall |
|---|---:|---:|
| matched | 3/3 | 3/4 |
| inferred_support | 0/6 | n/a (0 gold items) |
| not_evidenced | 3/3 | 3/8 |
| contradicted | 1/1 | 1/1 |
| cannot_assess | n/a (0 scorable gold items) | n/a |

The non-ambiguous confusion counts were: expected `matched` → predicted `matched` 3 and `inferred_support` 1; expected `not_evidenced` → predicted `inferred_support` 5 and `not_evidenced` 3; expected `contradicted` → predicted `contradicted` 1. Five ambiguous requirement labels were excluded. Four uncertainty warnings were expected and none were omitted (4/4). `not_evidenced` recall was 3/8.

No repair attempt was run: first-pass and post-repair validity both report the unchanged 17/18 result, and case_16 remains structurally invalid.

## Observed semantic failures

The five source-first unsupported-positive cases were case_02 (Spring Boot coursework vs production architecture ownership), case_03 (academic TensorFlow vs professional duration), case_05 (one tool call vs agent architecture), case_06 (supplied RAG package vs system design), and case_08 (API consumption vs API implementation). The opposite error occurred in case_10: explicit production RAG design and operation was downgraded to inference. These are benchmark-relative judgments; golden-label adjudication is still pending.

case_16 did not aggregate because a contradictory candidate evidence item was not linked to the cited candidate record. case_12 emitted a second requirement slot for a second conflicting source; whether that is an extraction error or a benchmark granularity disagreement remains unresolved. No automated repair was attempted. See the failure register for proposed regression coverage.

Prediction session IDs: 01a13b47-13df-7c82-8801-bdd283564f17, 01a13b47-1c1c-7f60-84ac-8edb48088c8e, 01a13b47-209b-7050-8a2f-e36c0c99ae3f, 01a13b47-23bb-78f2-a2f2-1dae28bea9b4, 01a13b47-26ea-73c1-81b0-d8e6637698e7, 01a13b47-29eb-7a70-815c-fa042b35ed45. Golden labels were not included in any prediction task. The first frozen V2.3 run was aborted before scoring after its metadata-as-requirement catalog flaw was found.
