# Matching Evaluation matching-benchmark-v1

Date: 2026-10-13 · Cases: 8
Agent context: executed_unblinded_same_codex_context

| Metric | Result |
|---|---:|
| Exact requirement classification | 13/13 (1.000) |
| Supported match precision | 7/7 (1.000) |
| Supported match recall | 7/7 (1.000) |
| Evidence reference validity | 8/8 (1.000) |
| Adjudicated evidence support accuracy | 11/11 (1.000) |
| Hard-filter correctness | 8/8 (1.000) |
| False unsupported-match rate | 0/7 (0.000) |
| Not-evidenced handling recall | 4/4 (1.000) |
| Explanation completeness (structural) | 8/8 (1.000) |
| Schema/invariant compliance | 8/8 (1.000) |
| Aggregation reproducibility | 8/8 (1.000) |

Ambiguous evidence judgments excluded: 2

| Case | Status | Exact labels | Hard filter | Uncertainty omissions |
|---|---|---:|---|---:|
| direct_and_not_evidenced | evaluated | 2/2 | True | 0 |
| inferred_language | evaluated | 1/1 | True | 0 |
| explicit_contradiction | evaluated | 1/1 | True | 0 |
| explicit_hard_filter | evaluated | 1/1 | True | 0 |
| conflict_stale_ambiguous | evaluated | 2/2 | True | 0 |
| career_aligned_with_gap | evaluated | 2/2 | True | 0 |
| high_evidence_low_career_alignment | evaluated | 2/2 | True | 0 |
| prompt_injection | evaluated | 2/2 | True | 0 |

## Limitations

- Small synthetic benchmark; no real-world performance claim.
- Evidence support accuracy excludes ambiguous judgments.
- The agent assessment was not independently blinded.
- Explanations are checked for required structure, not semantic quality.
