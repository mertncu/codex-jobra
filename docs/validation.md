# Packaging and validation status

This page separates local structure checks from installed runtime behavior.
Manifest validity and an installed plugin entry do not prove that Codex loaded
or invoked the skill.

## Package structure

The repository uses a portable root `plugin.json` and `skills/jobra/SKILL.md`.
The manifest and skill names are both `jobra`. The portable layout and manifest
passed manual inspection and local JSON/frontmatter parsing. OpenAI's
`skill-creator` `quick_validate.py skills/jobra` reported `Skill is valid!`.
The OpenAI interface metadata points both the marketplace logo and composer
icon to the bundled square asset at `assets/jobra-icon.png`.
The published plugin JSON Schema was validated on 2026-10-10 using Codex CLI
`0.162.0-alpha.2`; that external schema check has not been repeated in this
installation task.

The skill validator checks frontmatter, names, and scaffold markers. It does
not test plugin installation, automatic discovery, or invocation. To repeat
the local checks, use the `quick_validate.py` command in
[the first-run guide](first-run.md) and run `git diff --check`.

## Continuous integration

GitHub Actions runs on pull requests and pushes to `main` with read-only
repository contents permission. It installs the bounded runtime requirements
and the pinned PyYAML dependency needed by OpenAI Skill Creator's validator,
runs the full deterministic test suite, validates the plugin and bundled JSON
files, compiles the Python scripts, checks changed-file whitespace, and runs
the official `quick_validate.py` from the pinned `openai/skills` revision
`49f948faa9258a0c61caceaf225e179651397431`. CI does not access `.jobra/`, use
Codex credentials, run live discovery, or evaluate model semantics. Local
success does not establish that the workflow has passed on GitHub; that is only
known after a push or pull request triggers Actions.

## CLI installation and discovery status

On 2026-10-15, Codex CLI `0.162.1` installed Jobra from a local marketplace.
`codex plugin list --json` showed `jobra@jobra-local` with `installed: true`
and `enabled: true`. The installed package contained `plugin.json` and the
`skills/jobra/` package. The installed `SKILL.md` was manually accessible and
readable.

**Automatic skill discovery and invocation are not conclusively verified.** A
minimal `codex exec` attempt in the earlier isolated installation environment
could not authenticate, so it did not produce a skill-recognition result. The
normal authenticated CLI environment now has Jobra installed and enabled, but a
fresh-session invocation has not yet been observed. Follow the
[first-run guide](first-run.md) to start a fresh session and check the skill
picker or explicit invocation. If Jobra is not available, report that outcome;
do not simulate activation from repository files.

**Codex Desktop installation, discovery, and invocation remain untested.** For
a local marketplace in Desktop, the official plugin guide calls for restarting
the app after adding a marketplace and testing the installed plugin in a new
conversation. A successful CLI install does not establish Desktop behavior.

The CLI commands used for local installation are:

```sh
codex plugin marketplace add "$JOBRA_MARKETPLACE"
codex plugin add jobra@jobra-first-run
codex plugin list --json
```

The marketplace directory and catalog format are created in
[the first-run guide](first-run.md). The tested CLI installation used a local
marketplace copy of `plugin.json` and `skills/`; the current README does not
claim that other installation paths are verified.

## Historical validation notes

The initial foundation check on 2026-10-10 recorded the manifest schema,
skill-validator, ignore-rule, and whitespace checks. A separate clean-workspace
attempt at that time did not expose Jobra in the host marketplace listing; no
global installation was performed then. The later V0.4 CLI installation above
supersedes that old installation status, but not the still-unverified runtime
discovery or Desktop status.

For the manifest schema check, the earlier procedure downloaded the published
schema and validated `plugin.json` with `jsonschema`. Network access and the
external schema itself are not required by Jobra's runtime scripts.
