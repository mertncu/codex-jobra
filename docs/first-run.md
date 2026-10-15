# First run with Jobra

Jobra keeps runtime files in the `.jobra/` directory of the workspace selected
in Codex. Choose a private local workspace before handling a resume. The plugin
package and the Python environment are separate: installing the plugin does
not install Python dependencies.

## Prerequisites

- Codex CLI `0.162.1`, the version used to verify the local-marketplace method.
- Python 3 and `rsync`. Python 3.9.6 was used for current local tests; the
  minimum supported Python version has not been declared.
- Network access and an authenticated Codex session for Codex reasoning and
  live web tools. Python utilities do not make web requests.

From the repository root, create a local Python environment for Jobra's
deterministic utilities:

```sh
python3 -m venv .venv
.venv/bin/python -m pip install -r skills/jobra/requirements.txt
```

The requirements are `jsonschema`, `pypdf`, and `python-docx`. Resume ingestion
supports text-based PDF, DOCX, Markdown, and UTF-8 TXT; OCR is unavailable.

## Install with the local marketplace

Run these commands from the cloned `codex-jobra` repository. They copy only
`plugin.json` and `skills/` into a persistent local marketplace; no CV or
`.jobra/` data is copied. The `test` guard stops if the destination already
exists, so inspect it before choosing a different path or retrying.

```sh
JOBRA_MARKETPLACE="$HOME/.local/share/jobra-marketplace"
test ! -e "$JOBRA_MARKETPLACE" || { echo "Marketplace path already exists; inspect it first."; exit 1; }
mkdir -p "$JOBRA_MARKETPLACE/.agents/plugins" "$JOBRA_MARKETPLACE/plugins/jobra"
rsync -a --exclude='__pycache__/' --exclude='*.pyc' plugin.json skills "$JOBRA_MARKETPLACE/plugins/jobra/"

cat > "$JOBRA_MARKETPLACE/.agents/plugins/marketplace.json" <<'JSON'
{
  "name": "jobra-first-run",
  "plugins": [
    {
      "name": "jobra",
      "source": { "source": "local", "path": "./plugins/jobra" },
      "policy": { "installation": "AVAILABLE", "authentication": "ON_INSTALL" },
      "category": "Productivity"
    }
  ]
}
JSON

codex plugin marketplace add "$JOBRA_MARKETPLACE"
codex plugin add jobra@jobra-first-run
codex plugin list --json
```

In the JSON output, confirm Jobra is in `installed` with `installed: true` and
`enabled: true`. To refresh this package after repository changes, sync the
current `plugin.json` and `skills/` into the marketplace copy, then remove and
re-add only Jobra with `codex plugin remove jobra@jobra-first-run` and
`codex plugin add jobra@jobra-first-run`. Do not remove other plugins to
resolve a Jobra issue.

The CLI installation and installed package were verified. The installed
`SKILL.md` was manually accessible. Automatic skill discovery and invocation
have not been conclusively verified. Start a fresh Codex CLI session and check
whether the `jobra` skill is available before relying on it. If it is absent,
stop and report that instead of imitating its workflow. Desktop compatibility
has not been tested; for Desktop, restart the app after adding a local
marketplace and use a new conversation.

## Prepare and verify a candidate profile

When the skill is available, ask it to set up a profile from a local resume.
For example: “Jobra, help me create a candidate profile from my resume.” Give
the resume path only after approving that source and purpose. The workflow
extracts text locally, asks Codex to draft evidence-backed claims, and stores
new files under `.jobra/ingested/` and `.jobra/profiles/`. It does not parse
scanned images or run OCR.

The deterministic ingestion utility can also be run from the repository root:

```sh
.venv/bin/python skills/jobra/scripts/ingest_resume.py \
  /absolute/path/to/resume.pdf --workspace /absolute/path/to/private-workspace
```

Use the skill's `profile` workflow to review every record and evidence item,
including empty sections. Confirm, correct, or reject claims explicitly. A
separate final approval is required to create a verified profile. Drafts must
not be used for discovery or matching.

## Create search preferences and discover opportunities

Provide preferred and excluded roles, locations, work arrangements, and
seniority directly. Jobra stores these separately from the candidate profile
under `.jobra/discovery/`; it never derives them from the resume. Preferences
must match
[`search-preferences.schema.json`](../skills/jobra/references/search-preferences.schema.json).
The discovery planner validates both the selected verified profile and
preferences before writing a private plan:

```sh
.venv/bin/python skills/jobra/scripts/plan_discovery.py \
  .jobra/profiles/<verified-profile>.json \
  .jobra/discovery/<preferences>.json --workspace .
```

With the skill available, request a bounded discovery from Codex, for example:
“Jobra, find relevant opportunities using my saved preferences.” Review the
proposed queries and explicitly approve sending those search terms to web
services. Jobra does not send the full CV to job sites. Discovery can return no
results or partial results; an accessible posting does not prove that
applications are open.

## Review results and apply manually

For new discoveries, ask Jobra to continue the discovery run into matching
results. For previously saved opportunities, ask it to review saved listings
against the verified profile and preferences. Codex interprets the evidence;
Python validates references, applies explicit user constraints, aggregates
assessments, and renders a private shortlist. Matching quality has not been
independently established. Review supported evidence, unknowns, exclusions,
freshness, and application-status warnings yourself.

Private files are stored under the selected workspace's ignored `.jobra/`
directories, including `profiles/`, `discovery/`, `opportunities/`, and
`matches/`. Inspect only the paths reported by the workflow. Jobra never submits
applications; users decide whether and how to apply.

## Development checks

From the repository root:

```sh
.venv/bin/python -m unittest discover -s tests -v
python /path/to/skill-creator/scripts/quick_validate.py skills/jobra
git diff --check
```

The skill validator path depends on the installed OpenAI Skill Creator location.
See [validation notes](validation.md) for the recorded environment results and
known discovery limitations.
