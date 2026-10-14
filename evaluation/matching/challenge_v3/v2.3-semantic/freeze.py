"""Freeze V0.2.3 inputs, independent labels, and prediction-only package."""

from __future__ import annotations

from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path
from uuid import uuid4

ROOT = Path(__file__).resolve().parents[4]
RUN_DIR = Path(__file__).resolve().parent


def sha(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def freeze(package_path: Path, run_id: str | None = None):
    inputs = RUN_DIR / "inputs.v2.3.json"
    golden = RUN_DIR / "golden.v2.3.json"
    paths = {
        "build_inputs.py": RUN_DIR / "build_inputs.py",
        "build_prediction_package.py": RUN_DIR / "build_prediction_package.py",
        "freeze.py": RUN_DIR / "freeze.py",
        "score_v2.3.py": RUN_DIR / "score_v2.3.py",
        "evaluate_matching.py": ROOT / "evaluation/evaluate_matching.py",
        "match_opportunities.py": ROOT / "skills/jobra/scripts/match_opportunities.py",
        "matching-assessment.schema.json": ROOT / "skills/jobra/references/matching-assessment.schema.json",
        "opportunity-matching.md": ROOT / "docs/opportunity-matching.md",
        "matching-evidence-policy.md": ROOT / "docs/matching-evidence-policy.md",
    }
    data = json.loads(inputs.read_text(encoding="utf-8"))
    payload = {"freeze_version": "matching-semantic-freeze-v2.3",
        "benchmark_version": data["dataset_version"], "gold_version": json.loads(golden.read_text(encoding="utf-8"))["gold_version"],
        "prediction_run_id": run_id,
        "frozen_at_utc": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "case_count": len(data["cases"]), "input_sha256": sha(inputs),
        "golden_sha256": sha(golden), "package_sha256": sha(package_path),
        "implementation_sha256": {name: sha(path) for name, path in paths.items()}}
    target = RUN_DIR / "freeze.v2.3.json"
    if target.exists():
        existing = json.loads(target.read_text(encoding="utf-8"))
        immutable = ("benchmark_version", "gold_version", "input_sha256", "golden_sha256", "package_sha256", "implementation_sha256")
        if any(existing.get(key) != payload.get(key) for key in immutable):
            raise RuntimeError("frozen_benchmark_changed")
        if run_id and existing.get("prediction_run_id") != run_id:
            raise RuntimeError("prediction_run_id_mismatch")
        return existing
    payload["prediction_run_id"] = run_id or uuid4().hex
    with target.open("x", encoding="utf-8") as stream:
        stream.write(json.dumps(payload, indent=2) + "\n")
    return payload


if __name__ == "__main__":
    import argparse
    parser = argparse.ArgumentParser(description="Freeze V0.2.3 semantic challenge")
    parser.add_argument("--package", type=Path, required=True)
    args = parser.parse_args()
    print(json.dumps(freeze(args.package), indent=2))
