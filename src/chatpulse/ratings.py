"""Tiny local-only digest ratings. Never store chats, media or model output."""
from __future__ import annotations

from datetime import datetime, timezone
import json
import os
from pathlib import Path
import secrets


class RatingError(RuntimeError):
    """Public errors must not include stored content or filesystem secrets."""


def rating_file_path() -> Path:
    return Path.home() / ".chatpulse" / "ratings.json"


def _read(path: Path) -> dict:
    if path.is_symlink() or path.parent.is_symlink():
        raise RatingError("Unsafe feedback path")
    try:
        contents = path.read_text(encoding="utf-8")
    except FileNotFoundError:
        return {"version": 1, "runs": []}
    except (OSError, UnicodeError):
        raise RatingError("Cannot read local ratings") from None
    try:
        result = json.loads(contents)
    except ValueError:
        raise RatingError("Invalid local ratings file") from None
    if (not isinstance(result, dict) or result.get("version") != 1
            or not isinstance(result.get("runs"), list)
            or len(result["runs"]) > 100):
        raise RatingError("Invalid local ratings format")
    return result


def _write(path: Path, data: dict) -> None:
    if path.is_symlink() or path.parent.is_symlink():
        raise RatingError("Unsafe feedback path")
    try:
        path.parent.mkdir(mode=0o700, parents=True, exist_ok=True)
        if os.name != "nt":
            path.parent.chmod(0o700)
        tmp = path.with_name(path.name + "." + secrets.token_hex(6) + ".tmp")
        fd = os.open(str(tmp), os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
        try:
            with os.fdopen(fd, "w", encoding="utf-8") as out:
                json.dump(data, out, ensure_ascii=False, separators=(",", ":"))
                out.write("\n")
                out.flush()
                os.fsync(out.fileno())
            os.replace(tmp, path)
            if os.name != "nt":
                path.chmod(0o600)
        finally:
            if tmp.exists():
                tmp.unlink()
    except (OSError, ValueError):
        raise RatingError("Cannot write local ratings") from None


def record_digest(*, model: str, count: int, chunks: int, seconds: int,
                  has_vision: bool, sample: bool) -> str:
    """Register only metadata from a successful inference, never its text."""
    if (not isinstance(model, str) or not model or len(model) > 128
            or type(count) is not int or count < 1
            or type(chunks) is not int or chunks < 1
            or type(seconds) is not int or seconds < 0):
        raise RatingError("Invalid digest rating metadata")
    path = rating_file_path()
    data = _read(path)
    run_id = secrets.token_hex(6)
    data["runs"].append({
        "id": run_id,
        "created_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "model": model,
        "messages": count,
        "chunks": chunks,
        "generation_seconds": seconds,
        "vision": bool(has_vision),
        "sample": bool(sample),
        "score": None,
    })
    data["runs"] = data["runs"][-100:]
    _write(path, data)
    return run_id


def rate_last(score: int) -> str:
    """Rate most recent digest once, using 1 (bad) ... 5 (excellent)."""
    if type(score) is not int or not 1 <= score <= 5:
        raise RatingError("Rating must be an integer from 1 to 5")
    path = rating_file_path()
    data = _read(path)
    if not data["runs"]:
        raise RatingError("No digest available to rate")
    last = data["runs"][-1]
    if not isinstance(last, dict) or not isinstance(last.get("id"), str):
        raise RatingError("Invalid rating record")
    if last.get("score") is not None:
        raise RatingError("The most recent digest was already rated")
    last["score"] = score
    _write(path, data)
    return last["id"]
