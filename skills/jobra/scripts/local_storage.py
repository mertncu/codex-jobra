"""Private, create-only JSON storage in a working project's ignored .jobra/."""

from __future__ import annotations

import json
import os
from pathlib import Path
import tempfile


class StorageError(Exception):
    """A fixed, privacy-safe storage failure code."""


def write_private_json(workspace: Path, category: str, filename: str, data: object) -> Path:
    """Create a private JSON file; never replace an existing path or follow directory links."""
    if category not in ("ingested", "profiles") or "/" in filename or ".." in filename:
        raise StorageError("invalid_destination")
    root = Path(workspace)
    if not root.is_dir():
        raise StorageError("invalid_workspace")
    private = root / ".jobra"
    category_dir = private / category
    for directory in (private, category_dir):
        if directory.is_symlink():
            raise StorageError("unsafe_destination")
        try:
            directory.mkdir(mode=0o700, exist_ok=True)
        except OSError:
            raise StorageError("unwritable_destination") from None
        if not directory.is_dir():
            raise StorageError("unsafe_destination")
    target = category_dir / filename
    try:
        with target.open("x", encoding="utf-8") as stream:
            os.chmod(target, 0o600)
            json.dump(data, stream, ensure_ascii=False, indent=2)
            stream.write("\n")
    except FileExistsError:
        raise StorageError("output_exists") from None
    except OSError:
        raise StorageError("unwritable_destination") from None
    return target


def write_private_json_atomic(workspace: Path, category: str, filename: str, data: object) -> Path:
    """Publish a complete private JSON snapshot without replacing an existing file."""
    if category not in ("profiles", "evaluations", "opportunities", "discovery", "matches") or not filename.endswith(".json") or "/" in filename or ".." in filename:
        raise StorageError("invalid_destination")
    root = Path(workspace)
    if not root.is_dir():
        raise StorageError("invalid_workspace")
    private = root / ".jobra"
    directory = private / category
    for part in (private, directory):
        if part.is_symlink():
            raise StorageError("unsafe_destination")
        try:
            part.mkdir(mode=0o700, exist_ok=True)
        except OSError:
            raise StorageError("unwritable_destination") from None
        if not part.is_dir():
            raise StorageError("unsafe_destination")
    target = directory / filename
    temporary = None
    try:
        with tempfile.NamedTemporaryFile(mode="w", encoding="utf-8", dir=directory,
                                         prefix=".pending-", suffix=".json", delete=False) as stream:
            temporary = Path(stream.name)
            os.chmod(temporary, 0o600)
            json.dump(data, stream, ensure_ascii=False, indent=2)
            stream.write("\n")
            stream.flush()
            os.fsync(stream.fileno())
        os.link(temporary, target)  # Exclusive publish: existing snapshots are immutable.
    except FileExistsError:
        raise StorageError("output_exists") from None
    except (OSError, TypeError, ValueError):
        raise StorageError("unwritable_destination") from None
    finally:
        if temporary is not None:
            temporary.unlink(missing_ok=True)
    return target
