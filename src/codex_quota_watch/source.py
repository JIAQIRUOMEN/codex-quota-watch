from __future__ import annotations

import json
import subprocess
from typing import Any, Sequence


def unwrap_posts(value: Any) -> list[dict[str, Any]]:
    """Accept common OpenCLI JSON envelopes without interpreting post text as commands."""
    if isinstance(value, list):
        items = value
    elif isinstance(value, dict):
        items = None
        if any(key in value for key in ("id", "rest_id", "post_id")):
            items = [value]
        for key in ("data", "posts", "items", "results", "tweets"):
            if items is not None:
                break
            if key in value:
                nested = value[key]
                if isinstance(nested, dict):
                    for subkey in ("posts", "items", "results", "tweets"):
                        if isinstance(nested.get(subkey), list):
                            nested = nested[subkey]
                            break
                if isinstance(nested, list):
                    items = nested
                    break
        if items is None:
            # Also accept a keyed collection of post objects from simple OpenCLI adapters.
            values = list(value.values())
            if values and all(isinstance(item, dict) and any(key in item for key in ("id", "rest_id", "post_id")) for item in values):
                items = values
            else:
                raise ValueError("JSON must be an array or contain post objects in a common envelope")
    else:
        raise ValueError("JSON source must be an array or object")
    if not all(isinstance(item, dict) for item in items):
        raise ValueError("every source item must be an object")
    return items


def run_source(argv: Sequence[str], timeout: float = 30) -> list[dict[str, Any]]:
    """Run a configured argv command without a shell and parse its JSON stdout."""
    if not argv or not all(isinstance(part, str) and part for part in argv):
        raise ValueError("source command must be a non-empty argv array of strings")
    if timeout <= 0:
        raise ValueError("timeout must be positive")
    try:
        result = subprocess.run(list(argv), shell=False, capture_output=True, text=True, timeout=timeout, check=False)
    except subprocess.TimeoutExpired as exc:
        raise RuntimeError(f"source command timed out after {timeout:g}s") from exc
    if result.returncode:
        raise RuntimeError(f"source command exited with status {result.returncode}; stderr was suppressed")
    try:
        decoded = json.loads(result.stdout)
    except json.JSONDecodeError as exc:
        raise ValueError(f"source command did not return valid JSON: {exc}") from exc
    return unwrap_posts(decoded)
