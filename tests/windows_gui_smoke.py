"""Optional Windows popup smoke test; never run by unittest discovery."""

from __future__ import annotations

import argparse
import json
import os
import secrets
import subprocess
import sys
import tempfile
import time
from pathlib import Path


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--run", action="store_true", help="explicitly open three temporary test popups")
    args = parser.parse_args()
    if not args.run:
        parser.error("this opens real windows; pass --run only when ready")
    if sys.platform != "win32":
        parser.error("the WPF smoke test is Windows-only")

    repo = Path(__file__).resolve().parents[1]
    script = repo / "windows" / "Show-CodexQuotaAlert.ps1"
    powershell = Path(os.environ.get("SystemRoot", r"C:\Windows")) / "System32" / "WindowsPowerShell" / "v1.0" / "powershell.exe"
    if not script.is_file() or not powershell.is_file():
        parser.error("bundled WPF script or Windows PowerShell was not found")

    with tempfile.TemporaryDirectory(prefix="codex-quota-watch-smoke-") as temp:
        root = Path(temp)
        event_dir, receipt_dir = root / "events", root / "receipts"
        event_dir.mkdir()
        receipt_dir.mkdir()
        for index in range(1, 4):
            event_id = f"gui_smoke_{index}"
            timing = {
                "kind": "unknown",
                "published_text": "Synthetic test event",
                "text": "No reset time is being asserted.",
                "basis": "GUI smoke test only",
                "confidence": "test",
            }
            event = {
                "id": event_id,
                "receipt_nonce": secrets.token_hex(16),
                "title": f"Codex Quota Watch test {index}/3",
                "message": "Temporary GUI smoke test. No real post or account data is used.",
                "ack_label": "Test button (do not click)",
                "url": "https://example.invalid/smoke-test",
                "timing": timing,
                "translations": {
                    "zh-CN": {
                        "title": f"Codex Quota Watch 测试 {index}/3",
                        "message": "临时 GUI smoke 测试，不含真实帖子或账户数据。",
                        "ack_label": "测试按钮（不要点击）",
                        "timing": {
                            "kind": "unknown",
                            "published_text": "合成测试事件",
                            "text": "未声明重置时间。",
                            "basis": "仅 GUI smoke 测试",
                            "confidence": "测试",
                        },
                    },
                    "en": {
                        "title": f"Codex Quota Watch test {index}/3",
                        "message": "Temporary GUI smoke test. No real post or account data is used.",
                        "ack_label": "Test button (do not click)",
                        "timing": {
                            "kind": "unknown",
                            "published_text": "Synthetic test event",
                            "text": "No reset time is being asserted.",
                            "basis": "GUI smoke test only",
                            "confidence": "test",
                        },
                    },
                },
            }
            event_path = event_dir / f"{event_id}.json"
            event_path.write_text(json.dumps(event, ensure_ascii=False), encoding="utf-8")
            receipt_path = receipt_dir / f"{event_id}.json"
            command = [
                str(powershell), "-NoProfile", "-STA", "-File", str(script),
                "-EventPath", str(event_path), "-ReceiptDirectory", str(receipt_dir),
                "-SmokeTestCloseAfterSeconds", "3",
            ]
            proc = subprocess.Popen(
                command,
                shell=False,
                close_fds=True,
                creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                text=False,
            )
            deadline = time.monotonic() + 20
            saw_displayed = False
            while time.monotonic() < deadline and proc.poll() is None:
                if receipt_path.exists():
                    try:
                        receipt = json.loads(receipt_path.read_text(encoding="utf-8-sig"))
                        if receipt.get("event_id") == event_id and receipt.get("status") == "displayed":
                            saw_displayed = True
                    except (OSError, json.JSONDecodeError):
                        pass
                time.sleep(0.1)
            try:
                stdout, stderr = proc.communicate(timeout=2)
            except subprocess.TimeoutExpired:
                proc.kill()
                proc.communicate()
                raise RuntimeError(f"smoke popup {index} did not close")
            if proc.returncode != 0:
                error_output = (stderr or stdout or b"").decode("mbcs", errors="replace")
                raise RuntimeError(f"smoke popup {index} exited with {proc.returncode}: {error_output}")
            final = json.loads(receipt_path.read_text(encoding="utf-8-sig")) if receipt_path.exists() else {}
            if not saw_displayed or final.get("event_id") != event_id or final.get("status") != "test_closed":
                raise RuntimeError(f"smoke popup {index} did not report displayed then test_closed: {final!r}")
            print(f"{index}/3: displayed, then test_closed; not acknowledged")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
