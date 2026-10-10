# Human adjudication of Candidate Intelligence evaluation

The original five-run benchmark remains unchanged: golden labels, saved
predictions, and the strict report are read-only inputs. The adjudication tool
recomputes the strict report and refuses to prepare or score a packet if it no
longer matches. Review packets, decisions, and adjusted reports belong only in
ignored local `.jobra/evaluations/` storage. They must not be committed with
personal profile data. No external service is called.

## Prepare the review packet

After running the real-agent evaluation, use its saved predictions and report:

```sh
.venv/bin/python skills/jobra/scripts/adjudicate_evaluation.py prepare \
  --predictions .jobra/evaluations/<run-id>/predictions \
  --baseline-report .jobra/evaluations/<strict-report>.json \
  --workspace .
```

The packet contains one item for each source-grounded unmatched claim and each
strict evidence mismatch. It includes the predicted field and value, cited
evidence, original source segment, and, for evidence mismatches, the golden
reference. It assigns **no** judgment. Item IDs and file hashes link the packet
to the exact baseline and predictions. A reviewer should inspect the original
synthetic resume and unchanged prediction as well as the packet. A cited excerpt
being present is not, by itself, proof of a claim.

## Record independent judgments

An independent human reviewer creates a separate JSON file in `.jobra/`:

```json
{
  "packet_id": "<packet_id from review packet>",
  "reviewer_type": "human",
  "reviewer": "<reviewer identifier>",
  "reviewed_at": "YYYY-MM-DD",
  "judgments": []
}
```

For each reviewed item, add an object with `item_id`, `category`, `rationale`,
and `source_ref`. `source_ref` must be a `ref` listed in that packet item's
`sources` array. Use `no_source` only when that array is empty. The rationale
must explain how the cited source supports or contradicts the **specific**
claim. The script rejects missing rationales, unknown references, duplicate
items, and categories inappropriate for the item type. Reviewer identity is an
attestation; the script cannot authenticate it. Codex may prepare the packet
but must not fill in human judgments on its own.

For an unmatched claim, choose exactly one:

| Category | Meaning |
| --- | --- |
| `valid_extra` | A true, source-supported candidate fact omitted from the selective gold labels. |
| `unsupported` | The source does not support the asserted fact. |
| `incorrect` | The source supports a different fact; extraction misread it. |
| `ambiguous` | The available text cannot resolve the claim confidently. |

For a strict evidence mismatch, choose exactly one:

| Category | Meaning |
| --- | --- |
| `sufficient_support` | The cited excerpt itself contains enough context to justify the specific claim. |
| `insufficient_support` | The cited excerpt lacks necessary context or contradicts the claim. |
| `ambiguous` | Sufficiency cannot be determined confidently from the source. |

A same-location, shorter excerpt may be sufficient or insufficient. Inspect
the excerpt's actual wording and its relationship to the claim; do not infer
sufficiency solely from location or substring overlap.

## Score reviewed decisions

```sh
.venv/bin/python skills/jobra/scripts/adjudicate_evaluation.py score \
  --packet .jobra/evaluations/<packet>.json \
  --judgments .jobra/evaluations/<decisions>.json \
  --predictions .jobra/evaluations/<run-id>/predictions \
  --baseline-report .jobra/evaluations/<strict-report>.json \
  --workspace .
```

Omit `--judgments` to generate an explicit pending report with zero decisions.
The score command regenerates the packet from the original inputs before
accepting judgments. It writes a new create-only report and never edits the
strict report, predictions, golden labels, packet, or decision file.

The report carries the **original strict metrics** separately from the
**review-adjusted lower bounds**. Adjusted precision is
`(strict matched claims + reviewed valid_extra claims) / all predicted claims`.
Adjusted evidence accuracy is
`(strict grounded matches + reviewed sufficient_support mismatches) /
strict matched claims`. This evidence denominator deliberately excludes newly
accepted `valid_extra` claims because their evidence is not independently
scored here. Unreviewed and `ambiguous` items never receive credit. The report
counts both as unresolved, while preserving counts for explicit `incorrect`,
`unsupported`, and `insufficient_support` decisions.

For the 2026-10-10 baseline, the packet contains 33 unmatched claims and 14
evidence mismatches. No independent reviewer has adjudicated them yet, so the
pending report has 0 adjudicated and 47 unresolved items. Its adjusted lower
bounds remain 34/67 precision and 20/34 evidence accuracy. These are **not**
human-confirmed adjusted outcomes. The original 34/34 recall, 0/67 conservative
unsupported rate, and 5/5 schema/invariant pass rate remain in the strict
section. Source text and predicted values appear only in the ignored packet,
not the shareable documentation or summary report.
