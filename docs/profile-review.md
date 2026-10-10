# Human profile review

Use the Jobra skill's `profile` task argument to review a draft. Codex shows
candidate records by section with evidence, extraction type, and review state;
asks the user to confirm, correct, or reject each claim; and asks about missing
facts and empty sections. It must obtain a separate final approval before
verification. No pending claim or evidence is accepted by default. The
[skill workflow](../skills/jobra/references/profile-workflow.md) and
[operation reference](../skills/jobra/references/profile-review-operations.md)
specify the conversation and operation JSON.

The deterministic entry point is `skills/jobra/scripts/review_profile.py`:

```sh
.venv/bin/python skills/jobra/scripts/review_profile.py \
  .jobra/profiles/draft-EXAMPLE.json .jobra/review-operation.json \
  --workspace .
```

The request file must live under the ignored `.jobra/` directory. It may hold
one legacy operation or a nonempty ordered `{"operations": [...]}` batch. The
script validates the input, applies each decision to an in-memory copy using
the existing JSON Schema and cross-record checks, and validates the final
result before atomically publishing **one** private `.jobra/profiles/` snapshot
per successful request. A failed decision rejects the whole batch: no partial
profile update or output snapshot is written. It never overwrites or deletes an
existing file. Its terminal output contains only a status and relative path;
errors are fixed codes without CV text. Keep private request files local and
manage historical snapshots according to your own retention preference.

`origin: extracted` and evidence references survive a user correction. A
user-added fact has `origin: user`, no extracted evidence, and begins `pending`.
Reviewing evidence is separate from reviewing the record it supports. Rejected
records remain in snapshots for audit, while `records_for_downstream` excludes
them from the verified candidate view. A change to a section reopens its review.
All five sections require explicit confirmation, including empty ones.

Batch requests cannot contain `finalize` and cannot substitute for final user
approval. Final approval is represented by the user's explicit answer in the Codex
conversation and the `{"action":"finalize","approved":true}` operation that
produces a verified snapshot. The profile schema does not store an approver
identity or an approval transcript; the local script cannot authenticate a
human response. Codex must not create that operation from silence, inferred
intent, or a prior `setup` request. Verified snapshots are locked; the utility
cannot modify or replace them. Resume excerpts remain untrusted data. No
external API, database, server, or job application action is part of review.
