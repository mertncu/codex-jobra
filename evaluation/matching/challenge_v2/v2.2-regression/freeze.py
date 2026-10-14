"""Freeze the 18-case regression inputs and matching implementation hashes."""

from __future__ import annotations

import argparse
from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path
from uuid import uuid4

ROOT = Path(__file__).resolve().parents[4]
CHALLENGE = Path(__file__).resolve().parents[1]
OUTPUT = Path(__file__).resolve().parent / "freeze.v2.2.json"


def sha256(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def freeze(package_path):
    baseline = json.loads((CHALLENGE / "freeze.v2.json").read_text(encoding="utf-8"))
    files = {
        "match_opportunities.py": ROOT / "skills/jobra/scripts/match_opportunities.py",
        "prepare_matching.py": ROOT / "skills/jobra/scripts/prepare_matching.py",
        "matching-assessment.schema.json": ROOT / "skills/jobra/references/matching-assessment.schema.json",
        "evaluate_matching.py": ROOT / "evaluation/evaluate_matching.py",
        "opportunity-matching.md": ROOT / "docs/opportunity-matching.md",
        "build_prediction_package.py": Path(__file__).resolve().parent / "build_prediction_package.py",
        "score_v2.2.py": Path(__file__).resolve().parent / "score_v2.2.py",
    }
    return {
        "freeze_version": "matching-regression-freeze-v2.2",
        "benchmark_version": baseline["benchmark_version"],
        "prediction_run_id": uuid4().hex,
        "frozen_at_utc": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "case_count": baseline["case_count"],
        "input_sha256": baseline["input_sha256"],
        "labels_sha256": baseline["labels_sha256"],
        "prediction_package_sha256": sha256(package_path),
        "implementation_sha256": {name: sha256(path) for name, path in files.items()},
    }


def main():
    parser = argparse.ArgumentParser(description="Freeze matching v2.2 regression before blind predictions")
    parser.add_argument("--package", type=Path, required=True)
    args = parser.parse_args()
    if OUTPUT.exists():
        parser.exit(1, "freeze already exists; refusing to replace it\n")
    document = freeze(args.package)
    with OUTPUT.open("x", encoding="utf-8") as stream:
        stream.write(json.dumps(document, indent=2) + "\n")
    print(json.dumps({"status": "frozen", "path": str(OUTPUT),
                      "prediction_run_id": document["prediction_run_id"],
                      "package_sha256": document["prediction_package_sha256"]}))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
