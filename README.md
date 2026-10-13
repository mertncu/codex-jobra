# Jobra

CV-aware job opportunity research, built as a Codex-native, skill-only plugin.
Jobra aims to turn a user-verified candidate profile into evidence-based,
explainable opportunity recommendations. Users review opportunities and apply
themselves; Jobra must never automatically submit applications.

**Status: early development (`0.0.1`).** Local resume extraction, candidate
drafts, batched human profile review, and an agent-driven discovery workflow
are available. Discovery requires approved preferences and live Codex web tools;
candidate matching is not implemented.

## Design

- Use Codex's existing reasoning and tools; no standalone backend, web server,
  mandatory external LLM API keys, agent framework, database, or MCP server.
- Store candidate data locally, with human review before a draft is verified.
- Support claims with resume evidence; distinguish inference and missing data.
- Add small, testable Python utilities only when a workflow needs them.

## Install for local development

This repository is the plugin root. It follows the current
[official portable plugin format](https://developers.openai.com/plugins/build/plugins):
root `plugin.json` and `skills/jobra/SKILL.md`, without a compatibility overlay.

For a local test, use the documented repo marketplace flow in a separate test
workspace. Copy only `plugin.json` and `skills/` into `plugins/jobra/` there.
Add this catalog at `.agents/plugins/marketplace.json` in that workspace
(merge the entry if a catalog already exists):

```json
{
  "name": "jobra-dev",
  "plugins": [
    {
      "name": "jobra",
      "source": { "source": "local", "path": "./plugins/jobra" },
      "policy": { "installation": "AVAILABLE", "authentication": "ON_INSTALL" },
      "category": "Productivity"
    }
  ]
}
```

Restart the desktop app, open that workspace, select `jobra-dev` in the Plugins
Directory, and install Jobra. Select its `jobra` skill and supply `setup`,
`profile`, `discover`, `research`, or `results` as task text. These are intended skill
arguments, not shell commands or separate skills. `setup` creates an unverified
draft, and `profile` guides human verification. `research` and `results` remain
planned.

Marketplace availability varies by host. The package and skill structure pass
local validation, but installation, fresh-chat skill discovery, and skill
invocation remain unverified on this host. Follow the
[manual installation acceptance test](docs/validation.md#manual-installation-acceptance)
before claiming the installed plugin works. Older hosts may need a compatibility
manifest; add one only after observing a specific failure.

## Privacy and development

Use `.jobra/` in the working project for private ingestion output and profiles;
the local scripts create it when needed. Never put personal data in the
plugin package, examples, or test fixtures. Use synthetic fixtures when tests
are introduced. `.gitignore` is an accident guard, not access control, and cannot
protect already tracked files.

Before collecting or reading a CV, obtain explicit approval for the source and
purpose. Before sending CV or profile data to an external service (including a
search query), obtain approval for the data, destination, and purpose. Local
storage does not imply offline inference: content supplied to Codex is processed
under the user's Codex configuration and service settings.

See [validation notes](docs/validation.md). Future utilities belong in
`skills/jobra/scripts/`, workflow references in `skills/jobra/references/`, tests
in `tests/`, and synthetic examples in `examples/`; create those directories
when they contain useful material. The [candidate data contract](docs/candidate-data-contract.md)
defines profile and preference documents. [Resume ingestion](docs/resume-ingestion.md)
documents the local extraction and draft workflow.

See [profile review](docs/profile-review.md) for batch operations, atomicity,
privacy, and verified-profile immutability. The project is intended for
open-source release. A license must be selected and added before release; this
version does not declare one.

Candidate Intelligence evaluation is available as a small, synthetic golden
dataset and deterministic scorer. See [the evaluation workflow](evaluation/README.md)
and its [example report](evaluation/example-report.md). No Codex extraction
accuracy is claimed until independently generated predictions are evaluated.

Explainable matching also has a synthetic benchmark and deterministic
evaluation runner. See [matching evaluation methodology](evaluation/matching/README.md)
and its [machine-readable](evaluation/matching/example-report.v1.json) and
[human-readable](evaluation/matching/example-report.v1.md) example reports.
The included Task 5 semantic run was unblinded within one Codex context and is
not an independent agent-accuracy result. The frozen [V0.2.1 challenge and
blind-run procedure](evaluation/matching/challenge_v2/README.md) uses a
separate projectless Codex task and preserves the V1 baseline. Its [blind
results](evaluation/matching/challenge_v2/report.v2.md) and [failure
register](evaluation/matching/challenge_v2/failure-register.v2.md) are available.

The [opportunity data contract](docs/opportunity-data-contract.md) supports
validation and atomic local snapshots of sourced job listings. The
[discover workflow](docs/opportunity-discovery.md) uses Codex web tools with
approved preferences. Evidence-grounded matching uses a local interpretation
packet and creates private, immutable results; see
[the matching workflow](docs/opportunity-matching.md).
