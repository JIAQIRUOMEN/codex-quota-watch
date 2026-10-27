from __future__ import annotations

import json
import os
import subprocess
import sys
import tempfile
from pathlib import Path
from typing import Any, Callable


def write_event(alert: dict[str, Any], event_dir: str | Path) -> Path:
    """Validate and atomically save portable event JSON for the Windows UI."""
    if not isinstance(alert, dict):
        raise ValueError("alert event must be an object")
    required = ("id", "receipt_nonce", "title", "message", "ack_label", "url", "timing")
    if any(not isinstance(alert.get(key), str) or not alert[key].strip() for key in required[:-1]):
        raise ValueError("alert event is missing required text fields")
    if len(alert["id"]) > 100 or any(ch not in "ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz0123456789_-" for ch in alert["id"]):
        raise ValueError("invalid event id")
    timing = alert["timing"]
    if not isinstance(alert["receipt_nonce"], str) or len(alert["receipt_nonce"]) != 32 or any(ch not in "0123456789abcdef" for ch in alert["receipt_nonce"]):
        raise ValueError("invalid receipt nonce")
    def validate_timing(value: Any, label: str, strict: bool = True) -> None:
        if not isinstance(value, dict) or value.get("kind") not in {"explicit", "estimated", "unknown"}:
            raise ValueError(f"invalid {label} timing data")
        fields = ("published_text", "text", "basis", "confidence") if strict else ("published_text", "text")
        for field in fields:
            item = value.get(field)
            if not isinstance(item, str) or len(item) > 350:
                raise ValueError(f"invalid {label} timing {field}")
        if not value["published_text"].strip() or not value["text"].strip():
            raise ValueError(f"{label} timing text is required")
        basis = value.get("basis", "")
        if value["kind"] == "estimated" and (not isinstance(basis, str) or not basis.strip()):
            raise ValueError(f"{label} estimated timing requires evidence basis")

    validate_timing(timing, "event", strict=False)
    for field in ("basis", "confidence"):
        value = timing.get(field)
        if value is not None and (not isinstance(value, str) or len(value) > 350):
            raise ValueError(f"invalid event timing {field}")
    if len(alert["title"]) > 120 or len(alert["message"]) > 2000 or len(alert["url"]) > 2000:
        raise ValueError("alert text exceeds UI limits")
    translations = alert.get("translations")
    if translations is not None:
        if not isinstance(translations, dict) or set(translations) != {"zh-CN", "en"}:
            raise ValueError("translations must contain zh-CN and en")
        for language, translated in translations.items():
            if not isinstance(translated, dict):
                raise ValueError(f"invalid {language} translation")
            for field, limit in (("title", 120), ("message", 2000), ("ack_label", 120)):
                item = translated.get(field)
                if not isinstance(item, str) or not item.strip() or len(item) > limit:
                    raise ValueError(f"invalid {language} translation {field}")
            validate_timing(translated.get("timing"), f"{language} translation")
            if translated["timing"]["kind"] != timing["kind"]:
                raise ValueError(f"{language} translation timing kind must match event")
    directory = Path(event_dir)
    directory.mkdir(parents=True, exist_ok=True)
    path = directory / f"{alert['id']}.json"
    payload = json.dumps(alert, ensure_ascii=False, indent=2)
    temp_name = None
    try:
        with tempfile.NamedTemporaryFile("w", encoding="utf-8", dir=directory, prefix=f".{alert['id']}.", suffix=".tmp", delete=False) as temp:
            temp_name = temp.name
            temp.write(payload)
        os.replace(temp_name, path)
    finally:
        if temp_name and Path(temp_name).exists():
            Path(temp_name).unlink(missing_ok=True)
    return path


def launch_windows_alert(alert: dict[str, Any], receipt_dir: str | Path, script_dir: str | Path | None = None, dry_run: bool = False) -> dict[str, Any]:
    """Launch the fixed bundled PowerShell renderer; never interpolate content into a shell."""
    event_dir = Path(receipt_dir).parent / "events"
    event_path = write_event(alert, event_dir)
    if dry_run:
        return {"status": "dry_run", "event": str(event_path)}
    if sys.platform != "win32":
        return {"status": "failed", "error": "WPF alerts are available only on Windows"}
    if script_dir:
        script = Path(script_dir) / "Show-CodexQuotaAlert.ps1"
    else:
        packaged = Path(__file__).resolve().parent / "windows" / "Show-CodexQuotaAlert.ps1"
        source_tree = Path(__file__).resolve().parents[2] / "windows" / "Show-CodexQuotaAlert.ps1"
        script = packaged if packaged.is_file() else source_tree
    if not script.is_file():
        return {"status": "failed", "error": f"missing notifier script: {script}"}
    receipt_path = Path(receipt_dir)
    receipt_path.mkdir(parents=True, exist_ok=True)
    system_root = Path(os.environ.get("SystemRoot", r"C:\Windows"))
    powershell = system_root / "System32" / "WindowsPowerShell" / "v1.0" / "powershell.exe"
    if not powershell.is_file():
        return {"status": "failed", "error": "Windows PowerShell is unavailable"}
    try:
        proc = subprocess.Popen([str(powershell), "-NoProfile", "-STA", "-File", str(script), "-EventPath", str(event_path), "-ReceiptDirectory", str(receipt_path)], shell=False, close_fds=True, creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0), stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        return {"status": "launched", "pid": proc.pid, "event": str(event_path)}
    except OSError as exc:
        return {"status": "failed", "error": str(exc)}


def dispatch_pending(store: Any, receipt_dir: str | Path, notifier: Callable[[dict[str, Any], str | Path], Any] | None = None) -> list[dict[str, Any]]:
    """Notify for each pending event; display/dismiss/failure never acknowledges it."""
    sync_ack_receipts(store, receipt_dir)
    notify = notifier or (lambda alert, path: launch_windows_alert(alert, path))
    outcomes = []
    for alert in store.pending():
        try:
            result = notify(alert, receipt_dir)
            outcomes.append({"id": alert["id"], "result": result})
        except Exception as exc:  # retain pending state for the next poll
            outcomes.append({"id": alert["id"], "result": {"status": "failed", "error": str(exc)}})
    return outcomes


def sync_ack_receipts(store: Any, receipt_dir: str | Path) -> list[str]:
    """Treat only a matching acknowledged UI receipt as an explicit user ack."""
    directory = Path(receipt_dir)
    if not directory.is_dir():
        return []
    acknowledged: list[str] = []
    for receipt in directory.glob("*.json"):
        try:
            data = json.loads(receipt.read_text(encoding="utf-8"))
            alert_id = data.get("event_id")
            receipt_nonce = data.get("receipt_nonce", data.get("nonce", ""))
            if data.get("status") == "acknowledged" and alert_id == receipt.stem and store.ack_with_nonce(alert_id, receipt_nonce):
                acknowledged.append(alert_id)
        except (OSError, ValueError, AttributeError):
            continue
    return acknowledged
