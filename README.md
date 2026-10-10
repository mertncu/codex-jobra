# Jobra

CV-aware job opportunity research, built as a Codex-native, skill-only plugin.
Jobra aims to turn a user-verified candidate profile into evidence-based,
explainable opportunity recommendations. Users review opportunities and apply
themselves; Jobra must never automatically submit applications.

**Status: repository foundation (`0.0.1`).** Candidate analysis,
research, matching, and saved results are not implemented.

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
`profile`, `research`, or `results` as task text. These are intended skill
arguments, not shell commands or separate skills. This version explains the
development status rather than executing those workflows.

Marketplace availability varies by host. Older hosts may need a compatibility
manifest; support for them is not claimed. Installation and fresh-chat discovery
still need a host smoke test. This setup does not change user plugin settings.

## Privacy and development

Reserve `.jobra/` in the working project for private CVs, profiles, research, and
results. It is ignored and is not created yet. Never put personal data in the
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
when they contain useful material. No placeholder implementations are included.

The project is intended for open-source release. A license must be selected and
added before release; this version does not declare one.
