# Foundation validation

Validated on 2026-10-10 with Codex CLI `0.162.0-alpha.2`.

## Format and tooling

The [official packaging guide](https://developers.openai.com/plugins/build/plugins)
supports a root portable `plugin.json` and automatic discovery of `skills/`.
The manifest uses only `$schema`, `name`, `version`, and `description`.
Plugin and skill names are both `jobra`.

The available OpenAI `skill-creator` skill provides `quick_validate.py`.
The separate `plugin-creator` skill was not available in this environment;
the documented manual portable layout was used instead. The installed
`codex plugin --help` exposes no standalone package-validation command.

## Checks and results

| Check | Result |
| --- | --- |
| Manifest against published Agent Plugins 1.0.0 JSON Schema | PASS |
| OpenAI skill-creator `quick_validate.py skills/jobra` | PASS: `Skill is valid!` |
| Plugin and skill names, root layout, workflow scope, privacy boundaries | PASS: manual review |
| Representative CV, profile, research, result, secret and Python paths ignored | PASS: `git check-ignore` |
| Whitespace errors | PASS: `git diff --check` |
| Desktop installation and fresh/existing-chat skill discovery | Not run |

Schema validation used the published
[plugin schema](https://agent-plugins.org/schemas/1.0.0/plugin.schema.json),
downloaded outside the repository. A temporary Python environment provided
PyYAML 6.0.3 and jsonschema 4.25.1; these are validation dependencies, not plugin
runtime dependencies.

## Reproduce

Use a Python environment with PyYAML and jsonschema. Download the schema to a
temporary location and validate from the repository root:

```sh
curl -fsSL https://agent-plugins.org/schemas/1.0.0/plugin.schema.json -o /tmp/jobra-plugin.schema.json
python -c 'import json, jsonschema; jsonschema.validate(json.load(open("plugin.json")), json.load(open("/tmp/jobra-plugin.schema.json"))); print("Manifest valid")'
```

Run `python /path/to/skill-creator/scripts/quick_validate.py skills/jobra`,
substituting the actual installed OpenAI skill-creator path. That validator
checks skill frontmatter, naming and unfinished scaffold markers; it is not
a behavioral or full plugin-installation test.

```sh
git diff --check
git check-ignore .jobra/cv.txt resumes/candidate.pdf profiles/candidate.json research/jobs.json results/report.md .env .env.production secrets/token.txt .venv/bin/python __pycache__/a.pyc
```

## Task 3.1 package and discovery check

After adding batch review, the portable manifest again passed the cached
published Agent Plugins 1.0.0 JSON Schema, and OpenAI `skill-creator`'s
`quick_validate.py skills/jobra` returned `Skill is valid!`. The root
`plugin.json` and `skills/jobra/SKILL.md` match the current
[official packaging guide](https://developers.openai.com/plugins/build/plugins):
portable packages discover skills from root `skills/` without a manifest
`skills` field. All profile workflow references and scripts are packaged under
that directory. These checks establish package structure, not runtime discovery.

A clean temporary Git workspace was populated with only `plugin.json`,
`skills/`, and a repo-scoped `.agents/plugins/marketplace.json` pointing to the
local copy. `codex plugin marketplace list` in that workspace showed only the
host's globally configured marketplaces; `codex plugin list` did not show
Jobra. The host did not expose an isolated install destination, so no plugin
was installed into the user's global cache or settings. **Installation, skill
discovery, and `$jobra` invocation remain unverified.** The earlier real-user
test followed repository skill instructions directly; it did not prove
installed-skill activation.

## Manual installation acceptance

The [official local marketplace procedure](https://developers.openai.com/plugins/build/plugins)
and [complete-plugin test guidance](https://developers.openai.com/plugins/deploy/connect-chatgpt)
require an installed plugin and a new conversation for behavioral verification:

1. Create a clean local test Git workspace. Copy only this repository's
   `plugin.json` and `skills/` to `plugins/jobra/` in that workspace. Do not copy
   `.jobra/`, real CVs, or private operation files.
2. Add the README's `jobra-dev` catalog at
   `.agents/plugins/marketplace.json`, with source path `./plugins/jobra`.
   Restart the desktop app, open the test workspace, choose `jobra-dev` in the
   Plugins Directory, and install Jobra. Verify that the installed plugin lists
   one `jobra` skill.
3. Start a **new conversation** in that workspace. Select or invoke `$jobra`
   with `setup` and a synthetic local TXT resume. Confirm that it asks for the
   resume path and access approval, saves an unverified draft under ignored
   `.jobra/`, and never transmits the file to a job platform.
4. Invoke `$jobra profile` on that draft. Confirm that it shows evidence and
   review states, supports a multi-decision batch yielding one snapshot, and
   leaves the profile draft until a **separate** explicit final approval.
   Confirm that `research` reports its current unimplemented status rather than
   running job discovery.
5. Repeat the `setup` and `profile` checks in an existing conversation after
   installation. Record the desktop/CLI version, marketplace visibility,
   installed plugin and skill visibility, invocation result, and any errors.
   Claim discovery only after observing it in the skill picker or invocation.

No user settings were modified during this Task 3.1 check. If a supported host
cannot load the portable package, investigate that exact failure before adding
a compatibility manifest.

Older clients and public-directory submission are not validated. A compatibility
overlay should be added only if a supported host actually requires it. Public
release also needs a license; structural validation does not establish
public-directory acceptance.
