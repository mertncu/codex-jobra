# Jobra V2.3 human adjudication packet

Source challenge: `matching-challenge-v2`. Golden labels modified: `False`. Independent human review performed: `False`.

Inspect the synthetic source excerpts and job requirement. Choose a decision and evidence-support label, then fill reviewer_rationale. Do not resolve uncertainty in Jobra's favor by default.

## case_04_r1

Question: The frozen support label is ambiguous. Review whether the cited candidate evidence semantically supports the exact qualification and whether the existing classification expresses that relationship.

Frozen expectation: `inferred_support`; support `ambiguous`; refs `['ev_skill']`.

Agent prediction: `not_evidenced`; quality `insufficient`; refs `[]`.

Agent rationale: The supplied evidence does not establish Kotlin production experience.

Candidate evidence:
- `ev_skill` (cand_change_resume / Skills): Java
Job evidence:
- `job_04_evidence_01` (Requirements 1): Kotlin production experience is required.

Available classification decisions: `matched`, `inferred_support`, `not_evidenced`, `contradicted`, `cannot_assess`.
Available evidence-support decisions: `supported`, `unsupported`, `ambiguous`.
Reviewer classification: **pending**
Reviewer evidence support: **pending**
Reviewer rationale: **required; not supplied**

## case_06_r1

Question: The frozen support label is ambiguous. Review whether the cited candidate evidence semantically supports the exact qualification and whether the existing classification expresses that relationship.

Frozen expectation: `cannot_assess`; support `ambiguous`; refs `[]`.

Agent prediction: `not_evidenced`; quality `insufficient`; refs `[]`.

Agent rationale: Customer support work is documented, but no dates or duration establish the required two years.

Candidate evidence:
Job evidence:
- `job_06_evidence_01` (Requirements 1): At least two years of customer support experience is required.

Available classification decisions: `matched`, `inferred_support`, `not_evidenced`, `contradicted`, `cannot_assess`.
Available evidence-support decisions: `supported`, `unsupported`, `ambiguous`.
Reviewer classification: **pending**
Reviewer evidence support: **pending**
Reviewer rationale: **required; not supplied**

## case_07_r1

Question: The candidate has explicit Python skill and a Python project, but no evidence of giving product demonstrations. Decide whether the whole compound requirement is directly matched, only analogously supported, or undocumented in its product-demonstration facet.

Frozen expectation: `matched`; support `supported`; refs `['ev_skill']`.

Agent prediction: `inferred_support`; quality `analogous_uncertain`; refs `['ev_project']`.

Agent rationale: Building a sample Python task tracker provides analogous technical experience, but does not establish experience delivering product demonstrations.

Candidate evidence:
- `ev_project` (cand_grad_resume / Projects): Built a sample task tracker with Python
- `ev_skill` (cand_grad_resume / Skills): Python
Job evidence:
- `job_07_evidence_01` (Requirements 1): Python product demonstrations are required.

Available classification decisions: `matched`, `inferred_support`, `not_evidenced`, `contradicted`, `cannot_assess`.
Available evidence-support decisions: `supported`, `unsupported`, `ambiguous`.
Reviewer classification: **pending**
Reviewer evidence support: **pending**
Reviewer rationale: **required; not supplied**

## case_09_r1

Question: The frozen support label is ambiguous. Review whether the cited candidate evidence semantically supports the exact qualification and whether the existing classification expresses that relationship.

Frozen expectation: `cannot_assess`; support `ambiguous`; refs `[]`.

Agent prediction: `cannot_assess`; quality `conflicting`; refs `['ev_intern']`.

Agent rationale: The candidate has software engineering work dated 2020–2025, but the posting contradicts its five-year requirement by stating that no previous experience is needed.

Candidate evidence:
- `ev_intern` (cand_senior_resume / Experience): Software Engineer at Example Systems, 2020-2025
Job evidence:
- `job_09_evidence_01` (Requirements 1): Five years of experience are required.
- `job_09_evidence_02` (Requirements 2): No previous experience is needed; new graduates are welcome.

Available classification decisions: `matched`, `inferred_support`, `not_evidenced`, `contradicted`, `cannot_assess`.
Available evidence-support decisions: `supported`, `unsupported`, `ambiguous`.
Reviewer classification: **pending**
Reviewer evidence support: **pending**
Reviewer rationale: **required; not supplied**

## case_11_r1

Question: AWS is listed and software employment is dated, but no cloud-operation duties are documented. Decide whether this is not_evidenced or cannot_assess; separately review the missing seniority/experience uncertainty warning.

Frozen expectation: `cannot_assess`; support `ambiguous`; refs `['ev_aws']`.

Agent prediction: `not_evidenced`; quality `insufficient`; refs `[]`.

Agent rationale: Listing AWS and holding a software engineering role do not establish commercial experience operating cloud platforms.

Candidate evidence:
- `ev_aws` (cand_senior_resume / Skills): AWS
Job evidence:
- `job_11_evidence_01` (Requirements 1): Commercial experience operating cloud platforms is expected.

Available classification decisions: `matched`, `inferred_support`, `not_evidenced`, `contradicted`, `cannot_assess`.
Available evidence-support decisions: `supported`, `unsupported`, `ambiguous`.
Reviewer classification: **pending**
Reviewer evidence support: **pending**
Reviewer rationale: **required; not supplied**

## case_13_r1

Question: The frozen support label is ambiguous. Review whether the cited candidate evidence semantically supports the exact qualification and whether the existing classification expresses that relationship.

Frozen expectation: `cannot_assess`; support `ambiguous`; refs `[]`.

Agent prediction: `cannot_assess`; quality `conflicting`; refs `[]`.

Agent rationale: The posting sources disagree on whether Ruby is required or experience in any language suffices; neither source is established as authoritative.

Candidate evidence:
Job evidence:
- `job_13_conflict` (Required qualifications): Ruby is not required; experience in any language is acceptable.
- `job_13_evidence_01` (Requirements 1): Ruby experience is required.

Available classification decisions: `matched`, `inferred_support`, `not_evidenced`, `contradicted`, `cannot_assess`.
Available evidence-support decisions: `supported`, `unsupported`, `ambiguous`.
Reviewer classification: **pending**
Reviewer evidence support: **pending**
Reviewer rationale: **required; not supplied**

## case_18_r1

Question: The frozen support label is ambiguous. Review whether the cited candidate evidence semantically supports the exact qualification and whether the existing classification expresses that relationship.

Frozen expectation: `cannot_assess`; support `ambiguous`; refs `[]`.

Agent prediction: `not_evidenced`; quality `insufficient`; refs `[]`.

Agent rationale: The software internship has no evidenced duration, and the demo project does not establish one year of professional software experience.

Candidate evidence:
Job evidence:
- `job_18_evidence_01` (Requirements 1): At least one year of professional software experience is required.

Available classification decisions: `matched`, `inferred_support`, `not_evidenced`, `contradicted`, `cannot_assess`.
Available evidence-support decisions: `supported`, `unsupported`, `ambiguous`.
Reviewer classification: **pending**
Reviewer evidence support: **pending**
Reviewer rationale: **required; not supplied**

