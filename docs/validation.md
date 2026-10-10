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

## Remaining compatibility work

Follow the README's documented local marketplace flow and test installation and
skill discovery in fresh and existing chats on each supported host. Confirm each
task argument reports its foundation-only status without accessing personal data
or performing research. No user settings were modified and no plugin was installed
as part of this setup.

Older clients and public-directory submission are not validated. A compatibility
overlay should be added only if a supported host actually requires it. Public
release also needs a license; structural validation does not establish
public-directory acceptance.
