# Failure register — V0.2.2

These are two mismatches against frozen labels. The notes below are hypotheses; no golden label was changed and no independent human adjudication was performed.

## case_07 — medium

Expected: `{"requirement_outcomes": {"r1": "matched"}, "hard_filter_violations": ["Sales Engineer"], "required_uncertainties": []}`

Observed: `{"status": "evaluated", "requirement_outcomes": {"r1": "inferred_support"}, "candidate_evidence_refs": {"r1": ["ev_project"]}, "hard_filter_violations": ["Sales Engineer"], "diagnostics": []}`

Hypothesis: The requirement combines explicit Python capability with product-demonstration activity. The resume directly supports Python and a Python project, but does not document demonstrations; the model preserved that distinction by returning inferred_support. The frozen expected matched label may be broader than the evidence, so this is not yet a confirmed model error.

Recommended follow-up: Request independent human review of the frozen label and requirement granularity. Keep the label unchanged for this run; future benchmarks should separate the tool requirement from the activity requirement.

Regression proposal: Add a synthetic multi-part requirement where one component is directly supported and another is not; require the assessment to state the boundary and avoid an unqualified direct match.

## case_11 — medium

Expected: `{"requirement_outcomes": {"r1": "cannot_assess"}, "hard_filter_violations": [], "required_uncertainties": ["seniority_or_experience_alignment_uncertain"]}`

Observed: `{"status": "evaluated", "requirement_outcomes": {}, "candidate_evidence_refs": {"r1": []}, "hard_filter_violations": [], "diagnostics": ["required_uncertainty_warning_missing"]}`

Hypothesis: The model used a five-year role date span to call mid-level alignment aligned, while the expected uncertainty warning asks it to account for the missing employer threshold and unverified scope of cloud-operations work. It also chose not_evidenced for commercial cloud operation where the benchmark expects cannot_assess, exposing an unclear category boundary.

Recommended follow-up: Keep experience duration and role seniority as separate evidence dimensions; require a caveat when no explicit employer threshold or responsibility evidence is available. Human-review the not_evidenced versus cannot_assess label boundary before changing the frozen gold.

Regression proposal: Add a synthetic case with dated software employment, a mid-level posting, and a cloud skill mention without operational duties; assert explicit uncertainty for seniority and no direct match for commercial operations.
