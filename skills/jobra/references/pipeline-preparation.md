# Prepare a private pipeline run

`prepare_pipeline.py prepare` validates local inputs and creates a bounded,
offline discovery plan. It does not contact the web, inspect job pages, or
perform candidate matching.

From the repository root:

```sh
.venv/bin/python skills/jobra/scripts/prepare_pipeline.py prepare --workspace .
```

The command looks for verified profile files named `verified-*.json` and
preference files named `preferences-*.json`; it selects only a single candidate
path and validates its contents. A saved opportunity snapshot is optional;
when there is exactly one `snapshot-*.json`, it is validated and referenced for
a future comparison. If multiple candidate paths exist, the command reports an
ambiguity and instructs you to pass the intended private path, for example:

```sh
.venv/bin/python skills/jobra/scripts/prepare_pipeline.py prepare \
  --workspace . \
  --profile .jobra/profiles/verified-<id>.json \
  --preferences .jobra/discovery/preferences-<id>.json \
  --opportunity-snapshot .jobra/opportunities/snapshot-<id>.json
```

Defaults are 10 discovery queries, 10 postings to discover, 10 opportunities
to assess, and one retry per stage. Limits can be set with
`--max-discovery-queries`, `--max-opportunities-to-discover`,
`--max-opportunities-to-assess`, and `--max-retries`. A plan exceeding the
query limit is recorded as partial and is not published as an executable query
plan. A query limit bounds requests; it does not guarantee search coverage.

The command prints the run ID, status, private manifest path, and (when
prepared) plan path and query count. Manifests use
`skills/jobra/references/run-manifest.schema.json`; they contain local input
paths and hashes, limits, stage states, fixed error/reason codes, and artifact
references, not a copy of candidate profile data. Run revisions are private,
atomic, mode-0600, and create-only files in `.jobra/discovery/`.

Inspect a manifest or plan only from the printed paths. Future workflow stages
advance a manifest explicitly, producing a new immutable revision. For example,
marking discovery as interrupted preserves the unfinished state:

```sh
.venv/bin/python skills/jobra/scripts/prepare_pipeline.py transition \
  --workspace . --manifest .jobra/discovery/run_<id>-r0002.json \
  --stage live_discovery --status running

.venv/bin/python skills/jobra/scripts/prepare_pipeline.py transition \
  --workspace . --manifest .jobra/discovery/run_<id>-r0003.json \
  --stage live_discovery --status partial --reason interrupted
```

Use `--error-code <snake_case_code>` for a failed stage and `--reason
<snake_case_code>` for a partial or skipped stage. Arbitrary free-text error
details are not accepted, to keep private content out of logs and manifests.
A partial or failed stage can be explicitly retried within the manifest's
`max_retries` budget; earlier error and interruption codes remain in its audit
history.
