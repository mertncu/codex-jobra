"""Build a private deterministic reference catalog for Codex matching."""

from __future__ import annotations

import argparse
import json
from pathlib import Path

from local_storage import StorageError, write_private_json_atomic
from match_opportunities import (MatchError, build_reference_catalog,
                                 explicit_exclusion_decisions,
                                 select_opportunity_document)


def main():
    parser = argparse.ArgumentParser(description="Prepare a local catalog of allowed matching references")
    parser.add_argument("profile", type=Path)
    parser.add_argument("preferences", type=Path)
    parser.add_argument("opportunities", type=Path)
    parser.add_argument("--workspace", type=Path, default=Path.cwd())
    parser.add_argument("--opportunity-id", action="append", dest="opportunity_ids",
                        help="limit the catalog to this saved opportunity; repeat to select several")
    args = parser.parse_args()
    try:
        documents = [json.loads(path.read_text(encoding="utf-8")) for path in
                     (args.profile, args.preferences, args.opportunities)]
        catalog = build_reference_catalog(documents[0], documents[1], documents[2],
                                          selected_ids=args.opportunity_ids)
        selected = select_opportunity_document(documents[2], args.opportunity_ids)
        hard_filtered = explicit_exclusion_decisions(selected, documents[1])
        path = write_private_json_atomic(args.workspace, "matches",
            f"catalog-{__import__('uuid').uuid4().hex}.json", catalog)
    except MatchError as exc:
        parser.exit(1, f"matching preparation failed: {exc}\n")
    except (OSError, UnicodeError, ValueError, StorageError):
        parser.exit(1, "matching preparation failed: invalid_input_or_storage\n")
    print(json.dumps({"status": "prepared", "catalog": str(path.relative_to(args.workspace)),
                      "candidate_evidence_count": len(catalog["candidate_evidence"]),
                      "opportunity_count": len(catalog["opportunities"]),
                      "selected_opportunity_ids": [item["opportunity_id"] for item in catalog["opportunities"]],
                      "hard_filtered_opportunities": hard_filtered,
                      "preference_reference_count": len(catalog["preferences"])}))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
