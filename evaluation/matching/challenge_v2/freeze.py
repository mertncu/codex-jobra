"""Freeze challenge input and label hashes before any blind prediction run."""

from __future__ import annotations

from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path
from uuid import uuid4

ROOT = Path(__file__).resolve().parents[3]
BASE = Path(__file__).resolve().parent


def sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def freeze(run_id: str | None = None) -> dict:
    inputs = BASE / "inputs.v2.json"
    labels = BASE / "labels.v2.json"
    payload = {"benchmark_version": "matching-challenge-v2",
               "prediction_run_id": run_id or uuid4().hex,
               "frozen_at_utc": datetime.now(timezone.utc).isoformat(timespec="seconds"),
               "input_sha256": sha256(inputs), "labels_sha256": sha256(labels),
               "case_count": len(json.loads(inputs.read_text(encoding="utf-8"))["cases"])}
    target = BASE / "freeze.v2.json"
    if target.exists():
        existing = json.loads(target.read_text(encoding="utf-8"))
        if existing.get("input_sha256") != payload["input_sha256"] or existing.get("labels_sha256") != payload["labels_sha256"]:
            raise RuntimeError("frozen_benchmark_changed")
        return existing
    target.write_text(json.dumps(payload, indent=2) + "\n", encoding="utf-8")
    return payload


if __name__ == "__main__":
    print(json.dumps(freeze(), indent=2))
