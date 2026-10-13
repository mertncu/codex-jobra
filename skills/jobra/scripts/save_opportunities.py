"""Validate and atomically create an opportunity snapshot; never fetch or execute content."""

import argparse
import json
from pathlib import Path
from uuid import uuid4

from local_storage import StorageError, write_private_json_atomic
from validate_opportunities import validate_opportunities


class OpportunityError(Exception):
    """Fixed privacy-safe failure code."""


def save_opportunities(document, workspace):
    if validate_opportunities(document):
        raise OpportunityError("invalid_opportunities")
    return write_private_json_atomic(workspace, "opportunities",
                                     f"snapshot-{uuid4().hex}.json", document)


def main():
    parser = argparse.ArgumentParser(description="Validate and save local opportunity JSON")
    parser.add_argument("document", type=Path)
    parser.add_argument("--workspace", type=Path, default=Path.cwd())
    args = parser.parse_args()
    try:
        document = json.loads(args.document.read_text(encoding="utf-8"))
        output = save_opportunities(document, args.workspace)
    except (OSError, UnicodeError, ValueError, OpportunityError, StorageError):
        parser.exit(1, "opportunity save failed: invalid_input_or_storage\n")
    print(json.dumps({"status": "saved", "output": str(output.relative_to(args.workspace))}))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
