"""Build prediction-only inputs plus deterministic reference catalogs."""

from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[4]
sys.path.insert(0, str(ROOT / "skills/jobra/scripts"))
from match_opportunities import build_reference_catalog
from local_storage import write_private_json_atomic

CHALLENGE = Path(__file__).resolve().parents[1]


def build_package():
    dataset = json.loads((CHALLENGE / "inputs.v2.json").read_text(encoding="utf-8"))
    opportunities = {item["id"]: item for item in dataset["opportunities"]["opportunities"]}
    cases = []
    for case in dataset["cases"]:
        profile = dataset["candidates"][case["candidate"]]
        preferences = dataset["preferences"][case["preferences"]]
        opportunity = opportunities[case["opportunity"]]
        document = {"schema_version": "1", "opportunities": [opportunity]}
        catalog = build_reference_catalog(profile, preferences, document)
        cases.append({"case_id": case["id"], "candidate_profile": profile,
                      "search_preferences": preferences, "opportunity": opportunity,
                      "reference_catalog": catalog})
    return {"package_version": "matching-prediction-package-v2.2",
            "benchmark_version": dataset["dataset_version"], "cases": cases}


def main():
    parser = argparse.ArgumentParser(description="Create blind matching prediction inputs and catalogs")
    parser.add_argument("--workspace", type=Path, default=ROOT)
    args = parser.parse_args()
    try:
        package = build_package()
        encoded = (json.dumps(package, ensure_ascii=False, indent=2) + "\n").encode("utf-8")
        digest = hashlib.sha256(encoded).hexdigest()
        path = write_private_json_atomic(args.workspace, "evaluations",
            f"matching-v2.2-prediction-inputs-{digest[:12]}.json", package)
    except (OSError, UnicodeError, ValueError, KeyError):
        parser.exit(1, "prediction package failed: invalid_input_or_storage\n")
    print(json.dumps({"status": "built", "case_count": len(package["cases"]),
                      "package": str(path.relative_to(args.workspace)),
                      "sha256": hashlib.sha256(path.read_bytes()).hexdigest(),
                      "bytes": len(encoded)}))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
