"""Build blind source-only matching inputs plus deterministic reference catalogs."""

from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[4]
RUN_DIR = Path(__file__).resolve().parent
sys.path.insert(0, str(ROOT / "skills/jobra/scripts"))
from local_storage import write_private_json_atomic
from local_storage import StorageError
from match_opportunities import build_reference_catalog


def build_package():
    dataset = json.loads((RUN_DIR / "inputs.v2.3.1.json").read_text(encoding="utf-8"))
    opportunity_map = {item["id"]: item for item in dataset["opportunities"]["opportunities"]}
    cases = []
    for item in dataset["cases"]:
        profile = dataset["candidates"][item["candidate"]]
        preferences = dataset["preferences"][item["preferences"]]
        opportunity = opportunity_map[item["opportunity"]]
        opportunity_doc = {"schema_version": "1", "opportunities": [opportunity]}
        catalog = build_reference_catalog(profile, preferences, opportunity_doc)
        cases.append({"case_id": item["id"], "candidate_profile": profile,
            "search_preferences": preferences, "opportunity": opportunity,
            "reference_catalog": catalog})
    return {"package_version": "matching-prediction-package-v2.3.1",
            "benchmark_version": dataset["dataset_version"], "cases": cases}


def main():
    parser = argparse.ArgumentParser(description="Build blind V0.2.3.1 prediction inputs")
    parser.add_argument("--workspace", type=Path, default=ROOT)
    args = parser.parse_args()
    try:
        package = build_package()
        path = args.workspace / ".jobra/evaluations/matching-v2.3.1-prediction-package.json"
        if path.exists():
            if json.loads(path.read_text(encoding="utf-8")) != package:
                raise StorageError("output_exists")
        else:
            path = write_private_json_atomic(args.workspace, "evaluations",
                "matching-v2.3.1-prediction-package.json", package)
    except (OSError, UnicodeError, ValueError, KeyError, StorageError):
        parser.exit(1, "prediction package failed: invalid_input_or_storage\n")
    digest = hashlib.sha256(path.read_bytes()).hexdigest()
    print(json.dumps({"status": "built", "cases": len(package["cases"]),
        "path": str(path.relative_to(args.workspace)), "sha256": digest}))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
