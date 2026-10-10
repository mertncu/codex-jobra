# Profile review operations

Each private request file contains either one operation object or an object
with a nonempty ordered `operations` array. Supply it and the latest profile
snapshot to `review_profile.py`; one successful request produces one new
immutable snapshot. Values below are synthetic. Record IDs and evidence IDs
come from the profile.

```json
{"action":"review_evidence","evidence_id":"ev_school","decision":"confirmed"}
```

`decision` may be `confirmed`, `corrected`, or `rejected`. A correction requires
`correction_note` and may include `changes` to `location`, `excerpt`, or
`extraction`; `remove_fields` may remove an unsupported `location` or `excerpt`.
Do not fabricate a location. Evidence can transition from
`pending` only once; if an accepted source later proves invalid, stop and create
a new reviewed draft rather than silently rewriting its history.

```json
{"action":"confirm_record","section":"education","record_id":"edu_1"}
{"action":"correct_record","section":"education","record_id":"edu_1","changes":{"institution":"Corrected Synthetic College"},"correction_note":"User corrected school name"}
{"action":"reject_record","section":"education","record_id":"edu_1"}
{"action":"add_record","section":"projects","record":{"id":"proj_added","name":"User-supplied project"}}
{"action":"confirm_section","section":"education"}
{"action":"finalize","approved":true}
```

Only user-supplied facts belong in `add_record`. It creates a `user`-origin,
`pending` record with no extracted evidence; confirm it separately. A correction
retains an extracted record's original `origin` and `evidence_ids`; the note
explains why accepted values differ from the source. For an unrelated or invalid
source, reject the extracted record and add a user-origin record. Section
confirmation includes empty sections. Finalization requires all five sections
confirmed, no pending record or evidence, valid evidence relationships, and a
separate explicit final user approval. The `approved` flag records that decision
for the operation; it is not an identity or consent proof.

`correct_record` also supports `remove_fields` for optional section fields, such
as an unsupported `period`; required fields cannot be removed. Correction fields
must be explicitly supplied by the user, never invented from resume text.

For multiple decisions already made by the user, batch them in dependency
order. The same operations and invariants apply to each item:

```json
{
  "operations": [
    {"action":"review_evidence","evidence_id":"ev_school","decision":"confirmed"},
    {"action":"confirm_record","section":"education","record_id":"edu_1"},
    {"action":"confirm_section","section":"education"}
  ]
}
```

The complete batch is validated in memory before a single atomic snapshot is
published. If any operation fails, the whole request fails and no snapshot is
created. The original and all historical snapshots remain untouched. A batch
cannot contain `finalize`, even with `approved: true`; finalization is a
separate, explicitly approved single operation after the review summary.
