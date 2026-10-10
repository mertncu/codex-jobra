# Candidate data contract (v1)

The [candidate profile schema](../skills/jobra/references/candidate-profile.schema.json)
and [search preferences schema](../skills/jobra/references/search-preferences.schema.json)
are separate JSON documents. Both have `schema_version: "1"`; future breaking
changes need a new version and migration decision. Runtime data belongs in the
user's ignored `.jobra/` directory, outside the installed plugin. The repository
contains only [invented profile](../tests/fixtures/candidate-profile.synthetic.json)
and [invented preferences](../tests/fixtures/search-preferences.synthetic.json).

The profile has five typed record arrays: `education`, `experience` (work and
internships), `projects`, `technical_skills`, and `suggested_roles`. Every record
has a stable `id`, `origin`, `review_status`, and `evidence_ids`. IDs are stable
within the profile and unique across record types; they are not position numbers.
No contact details or raw resume text are required. `period` is text because
resumes often have approximate or incomplete dates; the schema does not derive
years of experience. Skill `level` can remain `unknown`; technology mentions
must not automatically assign proficiency. Suggested roles are candidate-side
suggestions, not user search preferences.

Each evidence item has its own stable ID, a `source_document_id`, an `extraction`
value (`explicit` or `inferred`), and a `review_status`. `location` (section,
page, or another locator) and a short `excerpt` are optional. Omit `location`
when it cannot be determined; never invent one. The source document list carries
opaque IDs and an optional label; it should not contain local file paths by
default. Existing v1 documents with `location` remain valid.

`origin` records how a record first entered the profile: `extracted` means it
started from a source document; `user` means the user supplied it independently.
It does not change when a user corrects an extracted record. `evidence_ids` on an
extracted record retain references to the source material behind the original
extraction, even when corrected values differ from that material. They express
provenance, not proof that every current field matches the excerpt. A user-origin
record has no extracted evidence IDs. An inferred extraction retains
`extraction: inferred` after review; user confirmation is recorded separately in
`review_status`. Neither schema nor helper treats an inference as automatically
confirmed.

`review_status` reports the user's decision about a record or evidence item:
`pending` awaits review, `confirmed` accepts the current values, `corrected`
accepts values changed by the user, and `rejected` excludes the item from use.
For a correction, current record fields hold the corrected values and
`correction_note` briefly explains what changed; an extracted record retains its
original `origin` and `evidence_ids`. If the source itself was misread, mark its
evidence `corrected` with a note. If the source is wholly unrelated or invalid,
reject the extracted record and add a separate user-origin record instead.
Only the interactive workflow may set a non-pending status after actual user
review. JSON cannot prove that a human action occurred.

Rejected records remain in the profile for audit, but downstream job research
and matching must consume only `records_for_downstream(profile, section)`. That
helper requires a verified, valid profile and returns confirmed or corrected
records only. It never returns rejected records, even though they are retained
in storage. Inference and excerpt text are untrusted source material, not
instructions.

The top-level `verification_status` may be `verified` only after the user has
confirmed all five `section_reviews`, including empty sections, and no record or
evidence remains `pending`. Accepted records must have accepted supporting
evidence; rejected evidence cannot support an accepted record. This supports a
complete review without forcing the user to accept every extracted claim.
External workflow code must run the invariant helper before writing a verified
profile, and should derive the status from actual review actions. The current
task provides the contract and checker; it does not implement that workflow.

Search preferences include preferred and excluded roles, locations, work
arrangements, and seniority. Empty lists mean unspecified, not inferred from
the CV. The user must provide or approve preferences explicitly. Search
preferences do not alter profile verification status.

## Validation

Call `validate_document(document, "candidate_profile")` or
`validate_document(document, "search_preferences")` from
`skills/jobra/scripts/validate_profile.py`. This is the single validation entry
point. It runs Draft 2020-12 JSON Schema validation with format checking and,
for schema-valid profiles, cross-record invariant checks. It returns field paths
and generic rule names, never raw values or excerpts. Do not print full
`jsonschema` exceptions for private data. The helper reads only bundled schemas
and performs no candidate-data I/O or logging.

`jsonschema` is the sole runtime dependency for this validation entry point;
its version range is in `skills/jobra/requirements.txt`. Install it into the
Python environment used for local validation. The cross-record helper uses
only the standard library. To run the test suite:

```sh
python -m unittest discover -s tests -v
```
