"""Portable JSON provenance with explicit secret and path guards."""
from __future__ import annotations

from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path
import re
import subprocess

def digest(data: bytes) -> str:
    """SHA-256 of exact stored bytes."""
    return hashlib.sha256(data).hexdigest()

def file_digest(path: Path) -> str:
    """Stream a file checksum without loading it into memory."""
    with path.open("rb") as handle:
        return hashlib.file_digest(handle, "sha256").hexdigest()

def json_bytes(value) -> bytes:
    """Stable canonical JSON; non-finite numbers are prohibited."""
    return (json.dumps(value, sort_keys=True, separators=(",", ":"),
                       ensure_ascii=False, allow_nan=False) + "\n").encode("utf-8")

def timestamp(value: datetime) -> str:
    """Require explicit timezone and serialize UTC."""
    if not isinstance(value, datetime) or value.tzinfo is None or value.utcoffset() is None:
        raise ValueError("timestamp requires a timezone")
    return value.astimezone(timezone.utc).isoformat()

def component(value: str) -> str:
    """Validate an identifier safe for one directory component."""
    if not isinstance(value, str) or not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9_.-]{0,127}", value):
        raise ValueError("invalid path identifier")
    if value.endswith(".") or value.upper().split(".")[0] in {
        "CON", "PRN", "AUX", "NUL", *[f"COM{i}" for i in range(10)],
        *[f"LPT{i}" for i in range(10)]}:
        raise ValueError("reserved path identifier")
    return value

def safe_metadata(value):
    """Reject credential-shaped keys/values and personal filesystem paths."""
    if isinstance(value, dict):
        for key, item in value.items():
            if not isinstance(key, str):
                raise ValueError("metadata keys must be strings")
            if re.search(r"(?i)(secret|password|token|credential|authorization|api.?key|cookie)", key):
                raise ValueError("credential metadata is prohibited")
            safe_metadata(item)
    elif isinstance(value, list):
        for item in value:
            safe_metadata(item)
    elif isinstance(value, str):
        if re.search(r"(?i)(bearer\s|gh[pousr]_|github_pat_|-----BEGIN.*PRIVATE KEY|"
                     r"[?&](token|key|api.?key|secret)=|://[^/]*@)", value):
            raise ValueError("credential value is prohibited")
        if re.search(r"(?i)([a-z]:[\\/]|\\\\|/(Users|home)/)", value):
            raise ValueError("personal absolute paths are prohibited in metadata")
    elif value is not None and not isinstance(value, (bool, int, float)):
        raise ValueError("metadata must be JSON-compatible")
    json_bytes(value)
    return value

REQUEST_KEYS = {"endpoint", "symbol", "symbols", "underlying", "expiration",
    "start_date", "end_date", "max_dte", "interval", "format", "source_timezone",
    "observation_date_policy", "multiplier_source"}

def safe_request(request: dict) -> dict:
    """Only request fields useful for reproducing historical retrieval are stored."""
    safe_metadata(request)
    if set(request) - REQUEST_KEYS:
        raise ValueError("unknown request metadata fields")
    endpoint = request.get("endpoint")
    if endpoint is not None and (not endpoint.startswith("/") or "?" in endpoint
                                 or "#" in endpoint or "://" in endpoint):
        raise ValueError("endpoint must be an API path without query or host")
    return request

def code_revision(repo: Path | None = None) -> dict:
    """Capture commit, dirty state, tracked diff hash and lock hash; never a path."""
    repo = repo or Path(__file__).resolve().parents[4]
    base = ["git", "-c", f"safe.directory={repo.as_posix()}", "-C", str(repo)]
    def git(*args):
        return subprocess.run(base+list(args), capture_output=True, check=True).stdout
    try:
        commit = git("rev-parse", "HEAD").decode().strip()
        dirty = bool(git("status", "--porcelain"))
        diff_hash = digest(git("diff", "--binary", "HEAD", "--"))
        error = None
    except (OSError, subprocess.CalledProcessError):
        commit, dirty, diff_hash, error = None, None, None, "git_revision_unavailable"
    lock = repo / "uv.lock"
    return dict(commit=commit, dirty=dirty, tracked_diff_sha256=diff_hash,
        lock_sha256=file_digest(lock) if lock.exists() else None, status=error or "available")

def seal(value: dict) -> dict:
    """Embed a manifest checksum over all fields except the checksum itself."""
    safe_metadata(value)
    return value | {"manifest_sha256": digest(json_bytes(value))}

def load_sealed(path: Path) -> dict:
    """Reject a modified or incomplete manifest."""
    value = json.loads(path.read_text(encoding="utf-8"))
    stored = value.pop("manifest_sha256", None)
    if stored != digest(json_bytes(value)):
        raise ValueError("manifest checksum mismatch")
    value["manifest_sha256"] = stored
    return value
