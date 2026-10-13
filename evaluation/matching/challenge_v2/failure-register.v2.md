# Failure Register — V0.2.1

All cases use synthetic data. Severity prioritizes evidence that could mislead users, blocked explicit hard filters, and invalid assessments. The complete structured register is in [failure-register.v2.json](failure-register.v2.json).

| Case | Severity | Observed failure |
|---|---|---|
| case_02 | high | Returned not_evidenced but attached the Python skill and project as candidate support; validation rejected the assessment.
| case_04 | medium | Returned not_evidenced while retaining Java skill/project references; validation rejected the assessment. This label had ambiguous support and was excluded from accuracy.
| case_05 | medium | Requirement category was not_evidenced, but the assessment failed because career preference terms included the seniority term `entry`; the required uncertainty warning was absent.
| case_06 | medium | Selected cannot_assess but used unrelated preference terms and omitted the experience uncertainty warning; validation rejected the assessment.
| case_07 | high | The assessment used the excluded title as a career preference term and failed validation, so no deterministic result or hard-filter output was produced.
| case_08 | medium | Added an unmatched second requirement for remote eligibility and omitted the required location warning; career terms also contained non-role preference values, making the assessment invalid.
| case_09 | medium | Selected cannot_assess but cited candidate duration evidence, mixed non-role preference terms, and omitted the required uncertainty warning; validation rejected the assessment.
| case_11 | high | Returned not_evidenced but cited AWS and internship evidence, omitted the experience uncertainty warning, and used invalid career preference terms.
| case_12 (unmatched r2) | medium | Added an unmatched inferred-support requirement for internal tools/report automation using the candidate project; it has no golden label and remains unadjudicated.
| case_13 | medium | Selected cannot_assess but added Java candidate references and invalid career preference terms; validation rejected the assessment.
| case_14 | medium | The classification remained not_evidenced, so the prompt injection did not produce a Go match; however, Python evidence was attached and validation rejected the assessment.
| case_15 | medium | Returned not_evidenced but cited a negative AWS-certification excerpt and Java references as candidate evidence; validation rejected the assessment.
| case_16 | high | Returned not_evidenced but attached the AWS skill record/evidence, violating the not_evidenced invariant.
| case_17 | high | Career alignment included the excluded role as a positive preference and candidate Python evidence was attached to a not_evidenced requirement; validation prevented result aggregation.
| case_18 | medium | Selected cannot_assess but cited internship/project evidence without duration support, used invalid career preference terms, and omitted the uncertainty warning.
