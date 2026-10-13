# Candidate Intelligence evaluation v1

This dataset contains five fictional Markdown resumes and independently authored
golden fact labels. The cases cover a new graduate, an experienced engineer, a
career changer, missing dates, and a resume with an instruction that must be
ignored. The gold file is `golden.v1.json`; each label names a literal profile
field and a supporting source location and quote. Gold labels are reviewed
against the resume text by the evaluator. They were written from the resumes,
not copied from Jobra predictions.

## Run the actual Jobra setup workflow

Use a clean workspace for each case. Copy only `resumes/<case-id>.md` into that
workspace. Install or expose the local Jobra skill using the procedure in
`../README.md` and `../docs/validation.md`. Do **not** copy or open
`golden.v1.json` in the extraction workspace, give it to Codex, or include it in
the setup prompt. A separate workspace prevents accidental gold-label leakage.

For each of the five resume paths, invoke the `jobra` skill with `setup` and
tell Codex to analyze only that local resume, produce an evidence-backed
**draft**, validate it, and save it with the existing safe draft mechanism.
Supply no expected facts. Do not ask the user to verify the profile during this
evaluation. The profile and every extracted record/evidence item must stay
`pending`; the profile status must stay `draft`. Inspect the saved draft path and
copy the JSON, unchanged, to an ignored prediction directory in this repo:

```text
.jobra/evaluations/<run-id>/predictions/<case-id>.json
```

Use one independent setup run per resume. Record the Codex model, skill/package
revision, and prompt separately in the ignored run directory. The evaluator
does not invoke Codex or prepare predictions. Do not use a fixture-building
helper or the gold labels as an input to extraction. Repeat a case with a new
run ID to assess agent consistency; compare the resulting reports and claims
manually. Profiles are not sent to any external job service by these scripts.

After all predictions are saved, run:

```sh
.venv/bin/python skills/jobra/scripts/evaluate_candidate.py \
  --predictions .jobra/evaluations/<run-id>/predictions \
  --workspace . --date YYYY-MM-DD
```

The command prints only a new report path and a count. Reports are private,
create-only JSON files under `.jobra/evaluations/`. They contain counts,
categories, and golden claim IDs, never resume excerpts or predicted values.
Use `python -m unittest discover -s tests -v` with the project environment for
the deterministic test suite.

## Scoring rules

Scored fields are education `institution`, `credential`, `field`, `period`;
experience `organization`, `role`, `kind`, `period`; project `name`, `url`; and
technical skill `name`. Record IDs, review metadata, unknown skill levels,
free-text summaries, and suggested roles are not scored as literal facts.
Rejected records are omitted. A profile must pass the existing JSON Schema
and invariant validator before claim scoring. The existing draft/source
validator is also run and reported separately.

Matching is one-to-one on section, field, and value after Unicode casefolding
and whitespace collapse. No fuzzy matching occurs. Gold labels may list
explicit `aliases` for reviewed equivalent wording; none are assumed. A
source-grounded unmatched prediction is **not** silently counted correct or
called unsupported: it is `unmatched_for_review`. Missing gold IDs and evidence
failures are reported for review. An exact match counts toward precision and
recall even if its evidence is wrong, while evidence accuracy records that
failure separately.

Evidence attribution is correct only when a cited evidence item has the
ingested resume's source-document ID, the same source segment location as a
gold reference, a literal excerpt at that location, and an excerpt containing
the gold quote. A shorter or paraphrased excerpt may be valid but requires
human review; it receives no automatic evidence credit. An unmatched claim is
definitely unsupported only when it matches an explicitly forbidden label or
has no valid source-grounded evidence. The reported unsupported rate is thus
a conservative lower bound. A matching source quote alone does not prove a
semantic claim; review remaining unmatched claims manually.

Every ratio includes numerator and denominator. Precision is matched/predicted
claims; recall is matched/gold claims; evidence accuracy is grounded/matched;
unsupported rate is definitely unsupported/predicted. Schema/invariant and
draft/source pass rates use attempted predictions as denominator. Invalid
profiles are counted in pass rates but excluded from claim metrics. Missing
predictions have no accuracy metrics. A zero denominator produces `null`, not
zero. The per-case report includes failure categories and counts, without
private candidate content.

## Limits

For independent review of source-grounded unmatched claims and shorter
evidence excerpts, see [human adjudication](adjudication.md). It keeps reviewer
decisions separate from the golden labels and original predictions.

This dataset is intentionally small and synthetic; it cannot estimate
real-world performance or bias. Gold covers selected literal facts, not every
possible valid claim, and strict text matching undercredits paraphrases. Some
unsupported or inferred claims require human judgment. Prompt injection is
tested by a forbidden skill label and draft-state check; broader attack
resistance remains unmeasured. The deterministic suite tests the evaluator and
existing validators, not Codex's semantic extraction quality. Installed skill
discovery on this host remains unverified until the manual acceptance procedure
is observed.

For candidate–opportunity matching evaluation, see the separate [synthetic
benchmark, scoring methodology, and example reports](matching/README.md). It
does not use the Candidate Intelligence golden labels or private pilot files.
