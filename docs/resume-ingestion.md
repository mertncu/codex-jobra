# Resume ingestion and draft storage

The local [ingestion utility](../skills/jobra/scripts/ingest_resume.py) accepts
PDF, DOCX, Markdown, and UTF-8 TXT files up to 10 MiB. It uses
[`pypdf`](https://pypdf.readthedocs.io/en/stable/user/extract-text.html) for PDF
text and [`python-docx`](https://python-docx.readthedocs.io/en/latest/api/document.html)
for DOCX paragraphs and table cells. There is no OCR, network request, LLM API,
or semantic extraction in Python. Install the dependencies in
[`skills/jobra/requirements.txt`](../skills/jobra/requirements.txt) into the
Python environment used by the scripts.

```sh
python skills/jobra/scripts/ingest_resume.py /absolute/path/to/resume.pdf --workspace /absolute/path/to/project
```

The script creates `.jobra/ingested/resume_<digest>.json` in the working
project. It prints metadata only, never resume text. The JSON has
`schema_version`, an opaque `source_document` ID, `format`, and ordered
`segments`. Each segment has `text`, an actual source `location` (PDF page,
DOCX paragraph or table cell, or text line range), and `section` where a
Markdown or DOCX heading is available. The source path is not stored. The ID
is derived from file bytes and is stable for the same input. Existing output
files are never replaced.

Codex interprets the private segments under the
[setup instructions](../skills/jobra/references/setup-workflow.md). It writes
a proposed profile JSON in `.jobra/`, then runs:

```sh
python skills/jobra/scripts/save_profile_draft.py /absolute/path/to/proposal.json /absolute/path/to/ingested.json --workspace /absolute/path/to/project
```

The save utility validates the existing v1 profile schema and invariants,
requires a draft with all reviews pending, and confirms evidence excerpts at
their claimed segment locations. It creates a new file in `.jobra/profiles/`
without replacing an existing draft or verified profile. Validation and
ingestion failures report generic codes; private text is not included in
errors. Only synthetic examples belong in this repository.

Limitations: scanned PDFs without a text layer cannot be read; PDF page text
may be out of visual order; DOCX text in text boxes, shapes, headers, or footers
may be omitted. UTF-8 is required for plain text. The 10 MiB limit bounds input
size, not all PDF decompression costs. A user must later review and verify the
draft; this task does not implement that interaction.
