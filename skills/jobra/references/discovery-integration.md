# Integrate observed discovery results

`integrate_discovery.py` is the deterministic handoff from Codex research to
the opportunity catalog. It does not perform network requests. Codex supplies
observed source facts and evidence; Python validates each record, retains every
submitted observation in a private audit, applies the existing conservative
deduplication rules, and creates immutable snapshots.

## Input contract

Prepare a run first with `prepare_pipeline.py prepare`. Follow the discovery
workflow's explicit approval rule before sending approved query terms to a web
search provider. After research, write the actual observed material to a local
JSON file with this structure:

```json
{
  "schema_version": "1",
  "execution_status": "completed",
  "queries_executed": ["an exact query from the prepared plan"],
  "observations": [
    {"observation_id": "obs_2", "outcome": "inaccessible", "source_url": "https://jobs.example.test/posting", "reason_code": "source_inaccessible"},
    {"observation_id": "obs_3", "outcome": "rejected", "reason_code": "not_a_job_posting"}
  ]
}
```

For an `opportunity` outcome, include the complete current opportunity object
in its `opportunity` field. Rejected outcomes may include the submitted object
for private audit purposes.

`execution_status` is `completed`, `partial`, or `interrupted`. The exact
executed queries must be unique members of the prepared plan. Opportunity
records use `opportunities.schema.json`; source records must include the
observed source URL, platform, access result, and timestamp. Unknown application
status remains unknown even when the page was reachable.

Run the handoff with:

```sh
.venv/bin/python skills/jobra/scripts/integrate_discovery.py \
  --workspace . \
  --manifest .jobra/discovery/run_<id>-rNNNN.json \
  --observations /path/to/local-observations.json
```

The query count and total submitted observations are bounded by the prepared
manifest. A budget or contract failure is recorded against the live discovery
stage. Each accepted opportunity is validated independently, so one malformed
record does not discard other valid records. Inaccessible sources, explicit
rejections, invalid records, and possible duplicates remain in the audit with
fixed reason codes and their private submitted material.

Exact canonical URLs or matching explicit posting IDs can be merged using
`opportunity_lifecycle.py`, preserving source and evidence provenance in a new
snapshot. A lifecycle conflict is retained for review. Similar employer/title
records are kept separate and flagged as possible duplicates; they are never
automatically merged. Freshness is recorded from source observations, and
accessibility is not interpreted as an open application state.

The script writes the raw observations, audit, and any usable opportunity
snapshot under ignored `.jobra/` storage with atomic create-only writes and
restrictive permissions. It then advances the manifest through immutable
revisions. A mixed usable batch ends partial; no valid opportunity fails the
validation stage while preserving its audit. An interrupted discovery remains
marked partial. A failed run is never automatically retried.

The command output contains status, counts, and private artifact paths only; it
does not print job-description text. The original historical opportunity
snapshot is read-only. This interface is deterministic and does not establish
semantic truth beyond source-backed contract validation; Codex remains
responsible for interpreting external pages as untrusted content.
