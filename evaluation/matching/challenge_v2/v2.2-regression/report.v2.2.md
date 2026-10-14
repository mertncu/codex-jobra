# Matching Evaluation matching-challenge-v2

Date: 2026-10-14 · Cases: 18
Agent context: separate_clean_projectless_codex_task

| Metric | Result |
|---|---:|
| Exact requirement classification | 11/12 (0.917) |
| Supported match precision | 5/5 (1.000) |
| Supported match recall | 5/5 (1.000) |
| Evidence reference validity | 18/18 (1.000) |
| Adjudicated evidence support accuracy | 8/12 (0.667) |
| Hard-filter execution | 18/18 (1.000) |
| Hard-filter correctness | 18/18 (1.000) |
| False unsupported-match rate | 0/5 (0.000) |
| Not-evidenced handling recall | 6/6 (1.000) |
| Explanation completeness (structural) | 18/18 (1.000) |
| First-pass schema/invariant validity | 18/18 (1.000) |
| Post-repair schema/invariant validity | 18/18 (1.000) |
| Schema/invariant compliance | 18/18 (1.000) |
| End-to-end aggregation success | 18/18 (1.000) |
| Deterministic aggregation reproducibility | 0/0 (n/a) |

Ambiguous evidence judgments excluded: 6

## Selected clean-session repeat

A second isolated Codex task repeated `case_01`. The first repeat attempt was excluded because its prompt omitted the exact JSON schema and the response did not conform. After supplying the exact schema and contract in a new clean task, the output passed schema/invariant validation and aggregation. Its requirement outcome (`matched`) and candidate evidence references (`ev_skill`, `ev_project`) exactly matched the primary run. This is one descriptive case comparison, not a broader reliability estimate.

| Case | Status | Exact labels | Hard filter | Uncertainty omissions |
|---|---|---:|---|---:|
| case_01 | evaluated | 1/1 | True | 0 |
| case_02 | evaluated | 1/1 | True | 0 |
| case_03 | evaluated | 1/1 | True | 0 |
| case_04 | evaluated | 0/0 | True | 0 |
| case_05 | evaluated | 1/1 | True | 0 |
| case_06 | evaluated | 0/0 | True | 0 |
| case_07 | evaluated | 0/1 | True | 0 |
| case_08 | evaluated | 1/1 | True | 0 |
| case_09 | evaluated | 0/0 | True | 0 |
| case_10 | evaluated | 1/1 | True | 0 |
| case_11 | evaluated | 0/0 | True | 1 |
| case_12 | evaluated | 1/1 | True | 0 |
| case_13 | evaluated | 0/0 | True | 0 |
| case_14 | evaluated | 1/1 | True | 0 |
| case_15 | evaluated | 1/1 | True | 0 |
| case_16 | evaluated | 1/1 | True | 0 |
| case_17 | evaluated | 1/1 | True | 0 |
| case_18 | evaluated | 0/0 | True | 0 |

## Limitations

- Small synthetic regression set; no real-world performance or production-readiness claim.
- The same frozen 18 cases are used for regression comparability; no new unseen challenge cases were added.
- Golden labels are unchanged and have not received independent human adjudication.
- Evidence sufficiency is semantic; deterministic checks establish reference validity and catch only obvious lexical mismatch.
- Ambiguous evidence-support judgments are excluded and reported separately.
- The prior eight-opportunity live pilot remains observational only.
