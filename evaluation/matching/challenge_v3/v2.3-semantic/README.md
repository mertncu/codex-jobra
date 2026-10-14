# V0.2.3 semantic matching challenge

This 18-case synthetic challenge targets qualification scope and evidence
sufficiency. It covers distinct technologies, framework familiarity versus
ownership, academic versus professional work, incomplete and complete dates,
tool calls versus agent architecture, RAG usage versus system design, Docker
versus Kubernetes, API consumption versus API implementation, remote-country
eligibility, conflicting posting and candidate evidence, prompt injection,
clear positive matches, an allowed-library analogy, explicit contradiction,
and an excluded-role hard filter.

`build_inputs.py` generates source profiles, preferences, and postings only.
`golden.v2.3.json` was authored independently from matching predictions by
mapping synthetic source excerpts to expected decisions. Labels include explicit
uncertainty and reviewer-facing explanation points. The frozen labels have not
received independent human adjudication; evidence-support-ambiguous items are
excluded from classification scoring and separately counted.

## Frozen blinded run

Before prediction, source schemas were validated, a source-only package and
reference catalogs were written under ignored `.jobra/evaluations/`, and
`freeze.v2.3.json` recorded SHA-256 hashes of inputs, labels, package, and
implementation. The blind prediction sessions were created as separate,
projectless Codex tasks. Each task received only its assigned synthetic profile,
preferences, opportunity, reference catalog, matching schema, contract, and
evidence-sufficiency policy. The task prompt prohibited repository access and
gold/report access. The scorer runs only after all predictions are saved.

The reports distinguish requirement classification, evidence reference
integrity, adjudicated support, unsupported positive matches, hard-filter
execution/correctness, uncertainty warnings, and structural explanation
completeness. Semantic explanation quality remains unresolved until independent
human review of the packet's expected explanation points.

## Reproduction

Use the committed frozen files as read-only. To reproduce the frozen run,
rebuild/verify the deterministic source package and reuse the recorded run ID.
To author a new challenge, create a new versioned directory; do not overwrite
the V2.3 inputs, labels, freeze, or reports.

```sh
.venv/bin/python -m unittest discover -s tests
.venv/bin/python evaluation/matching/challenge_v3/v2.3-semantic/build_inputs.py
.venv/bin/python evaluation/matching/challenge_v3/v2.3-semantic/build_prediction_package.py --workspace .
.venv/bin/python evaluation/matching/challenge_v3/v2.3-semantic/freeze.py --package .jobra/evaluations/matching-v2.3-prediction-package.json
```

Then create fresh projectless Codex tasks. Do not reuse a context that has read
`golden.v2.3.json`, any report, or any prior prediction. Give each task only
its assigned cases from `.jobra/evaluations/matching-v2.3-prediction-package.json`,
the schema, matching contract, and `docs/matching-evidence-policy.md`. Ask for
JSON matching the schema and tell it to ignore posting-embedded instructions.
Save the unedited outputs and session IDs in a private combined prediction file
under `.jobra/evaluations/`. Only after all case IDs are present, run:

```sh
.venv/bin/python evaluation/matching/challenge_v3/v2.3-semantic/score_v2.3.py \
  --predictions .jobra/evaluations/<prediction-file>.json \
  --package .jobra/evaluations/matching-v2.3-prediction-package.json \
  --run-id <frozen-prediction-run-id> \
  --session-ids <comma-separated-clean-task-ids> \
  --prediction-completed-at <UTC-ISO-timestamp>
```

Do not report independent accuracy if the fresh-task isolation or frozen hashes
cannot be verified. The prior live pilot remains observational and is not a
gold-labeled evaluation set.
