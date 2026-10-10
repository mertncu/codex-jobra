# Example evaluation report (template; no agent run)

- Dataset version: `1.0.0`
- Evaluation date: `YYYY-MM-DD`
- Resumes: `5`
- Predictions supplied: `0/5` in this example
- Agent model and skill revision: record with the private run metadata

| Metric | Numerator / denominator | Value |
| --- | ---: | ---: |
| Claim precision | 0 / 0 | N/A |
| Claim recall | 0 / 0 | N/A |
| Evidence attribution accuracy | 0 / 0 | N/A |
| Unsupported claim rate | 0 / 0 | N/A |
| Schema and invariant pass rate | 0 / 0 | N/A |
| Draft/source pass rate | 0 / 0 | N/A |

Per-case results: all five cases are `missing_prediction`. Failure categories:
none observed because no actual profile was evaluated. This is a format example,
**not an accuracy result**. When predictions exist, use the generated JSON
report for exact denominators, per-case counts, missing gold IDs, incorrect
evidence IDs, forbidden categories, and validation failures. Review
`unmatched_for_review` claims manually before drawing semantic conclusions.

Known limitations: strict literal matching; selected fields only; synthetic
sample size; manual judgment needed for paraphrases, summaries, inferred roles,
and unsupported claims with plausible source quotes.

Reproduce with the isolated setup steps and evaluator command in
`evaluation/README.md`. Keep predictions and reports under ignored `.jobra/`.
