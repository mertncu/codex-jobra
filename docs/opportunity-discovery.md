# Opportunity discovery pilot

Use Jobra `discover` with an approved, verified local profile and separate
search preferences. Follow the [skill workflow](../skills/jobra/references/discover-workflow.md).
Codex uses its available web search/browser tools to inspect original employer
or ATS postings and interpret evidence. Python performs no network requests.

The offline planner validates profile and preference contracts, refuses missing
essential preferences, excludes rejected/inferred records from local factual
context, and builds queries from user preferences only. Suggested roles never
become preferred roles automatically. The helper does not grant transmission
approval: the skill must obtain explicit user consent for query data and purpose.

```sh
.venv/bin/python skills/jobra/scripts/plan_discovery.py \
  .jobra/profiles/<verified-profile>.json \
  .jobra/discovery/<confirmed-preferences>.json --workspace .
```

The plan is a new private atomic file in `.jobra/discovery/`. Existing profiles
and preferences are read-only. New pilot input may record preferences supplied
by the user when no preference document exists. Queries may be refined by Codex
within approved scope; record the queries actually executed, not just the plan.
Remote eligibility must be checked in each posting; a remote keyword is not
proof that the user may work from their location.

Keep an ignored run journal with preferences, query approval, actual queries,
tools used, observation timestamps, lead URLs, original-page inspection
outcomes, duplicate decisions, validation failures and the final snapshot path.
An accessible page is not proof of an open job. Refuse bypasses of access
controls; report inaccessible leads separately. Do not score candidate fit.

The pilot aims for up to ten distinct valid postings, not a guaranteed count.
Report potential listings found, original postings inspected, saved records,
rejections/access failures, source domains/platforms, unknown fields and limits.
Only actual web calls and inspected source pages establish a live pilot.
Offline tests establish deterministic planning/storage behavior only.
