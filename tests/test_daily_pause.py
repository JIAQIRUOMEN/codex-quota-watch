"""Offline tests for the local daily fetch-pause gate."""

from __future__ import annotations

import io
import json
import tempfile
import unittest
from contextlib import redirect_stdout
from datetime import datetime, timezone
from pathlib import Path
from unittest import mock

from codex_quota_watch import Store, poll_once
from codex_quota_watch.daily import daily_gate, gate_for_alert, settings_defaults


UTC = timezone.utc
NOW = datetime(2026, 10, 26, 15, 59, tzinfo=UTC)  # 23:59 at UTC+08:00
TODAY_POST = "2026-10-26T15:00:00Z"              # 23:00 at UTC+08:00
MIDNIGHT_UTC = "2026-10-26T16:00:00Z"             # 2026-10-27 00:00 at UTC+08:00


def post(post_id: str, text: str, created_at: str | None = TODAY_POST) -> dict:
    value = {"id": post_id, "author": "thsottiaux", "text": text}
    if created_at is not None:
        value["created_at"] = created_at
    return value


class DailyPauseTests(unittest.TestCase):
    def setUp(self) -> None:
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.db_path = Path(self.tmp.name) / "state.sqlite3"
        self.store = Store(self.db_path)

    def baseline(self, store: Store | None = None, posts: list[dict] | None = None) -> None:
        poll_once(store or self.store, posts or [post("baseline-1", "routine post")], now=NOW)

    def make_new_alert(self, stage: str, *, store: Store | None = None, created_at: str | None = TODAY_POST, post_id: str | None = None) -> list[dict]:
        target = store or self.store
        self.baseline(target)
        text = "Codex quota reset is complete." if stage == "confirmed" else "Codex quota reset is planned."
        return poll_once(target, [post(post_id or f"new-{stage}", text, created_at)], now=NOW)

    def test_new_same_day_confirmation_pauses_through_next_local_midnight(self) -> None:
        alerts = self.make_new_alert("confirmed")
        self.assertEqual(len(alerts), 1)
        state = daily_gate(self.store, now=NOW)
        self.assertFalse(state["should_fetch"])
        self.assertEqual(state["resume_at"], MIDNIGHT_UTC)
        self.assertEqual(state["trigger_metadata"]["trigger_stage"], "confirmed")

        before_midnight = datetime(2026, 10, 26, 15, 59, 59, tzinfo=UTC)
        self.assertFalse(daily_gate(self.store, now=before_midnight)["should_fetch"])
        at_midnight = datetime(2026, 10, 26, 16, 0, tzinfo=UTC)
        resumed = daily_gate(self.store, now=at_midnight)
        self.assertTrue(resumed["should_fetch"])
        self.assertIsNone(resumed["resume_at"])

    def test_announcement_mode_can_pause_on_announcement(self) -> None:
        self.store.set_settings(daily_pause="announcement")
        alerts = self.make_new_alert("announcement")
        self.assertEqual(len(alerts), 1)
        self.assertFalse(daily_gate(self.store, now=NOW)["should_fetch"])

    def test_confirmed_mode_does_not_pause_on_announcement(self) -> None:
        self.store.set_settings(daily_pause="confirmed")
        self.make_new_alert("announcement")
        self.assertTrue(daily_gate(self.store, now=NOW)["should_fetch"])

    def test_off_mode_never_pauses(self) -> None:
        self.store.set_settings(daily_pause="off")
        alerts = self.make_new_alert("confirmed")
        self.assertEqual(len(alerts), 1)
        self.assertTrue(daily_gate(self.store, now=NOW)["should_fetch"])
        self.assertEqual(settings_defaults()["daily_pause"], "confirmed")

    def test_baseline_old_missing_naive_and_invalid_dates_never_pause(self) -> None:
        # A matching confirmation in the first snapshot is only baseline data.
        poll_once(self.store, [post("baseline-confirmed", "Codex quota reset is complete.")], now=NOW)
        self.assertTrue(daily_gate(self.store, now=NOW)["should_fetch"])

        invalid_created_at = (
            "2026-10-25T15:00:00Z",  # previous local day
            None,                     # missing
            "2026-10-26T15:00:00",   # naive
            "not-a-time",            # invalid
        )
        for index, created_at in enumerate(invalid_created_at):
            with self.subTest(created_at=created_at):
                path = Path(self.tmp.name) / f"invalid-{index}.sqlite3"
                store = Store(path)
                self.baseline(store)
                alerts = poll_once(
                    store,
                    [post(f"invalid-{index}", "Codex quota reset is complete.", created_at)],
                    now=NOW,
                )
                self.assertEqual(len(alerts), 1)
                self.assertTrue(daily_gate(store, now=NOW)["should_fetch"])

    def test_utc_previous_date_can_be_today_in_configured_beijing_offset(self) -> None:
        now = datetime(2026, 10, 26, 0, 30, tzinfo=UTC)
        post_time = "2026-10-25T18:00:00Z"
        alerts = self.make_new_alert("confirmed", created_at=post_time, post_id="utc-boundary")
        # The source time's UTC date is yesterday; its UTC+08 date matches now's local date.
        metadata = gate_for_alert(alerts[0], self.store.get_settings(), now=now)
        self.assertIsNotNone(metadata)
        self.assertEqual(metadata["local_date"], "2026-10-26")
        self.assertEqual(metadata["resume_at"], "2026-10-26T16:00:00Z")

    def test_gate_persists_across_store_reopen_and_expires_after_restart(self) -> None:
        self.make_new_alert("confirmed")
        reopened = Store(self.db_path)
        self.assertFalse(daily_gate(reopened, now=NOW)["should_fetch"])
        next_midnight = datetime(2026, 10, 26, 16, 0, tzinfo=UTC)
        self.assertTrue(daily_gate(reopened, now=next_midnight)["should_fetch"])

    def test_settings_change_clears_gate_but_preserves_pending_alert(self) -> None:
        alerts = self.make_new_alert("confirmed")
        self.assertFalse(daily_gate(self.store, now=NOW)["should_fetch"])
        self.store.set_settings(daily_pause="off")
        self.assertTrue(daily_gate(self.store, now=NOW)["should_fetch"])
        self.assertEqual([item["id"] for item in self.store.pending()], [alerts[0]["id"]])

    def test_paused_poll_skips_source_but_syncs_ack_and_retries_pending(self) -> None:
        first = self.make_new_alert("confirmed", post_id="receipt-ack")
        second = poll_once(
            self.store,
            [post("still-pending", "Codex quota reset is planned.")],
            now=NOW,
        )
        self.assertEqual(len(first), 1)
        self.assertEqual(len(second), 1)
        self.assertFalse(daily_gate(self.store, now=NOW)["should_fetch"])

        receipts = Path(self.tmp.name) / "receipts"
        receipts.mkdir()
        (receipts / f"{first[0]['id']}.json").write_text(
            json.dumps({"event_id": first[0]["id"], "status": "acknowledged", "receipt_nonce": first[0]["receipt_nonce"]}),
            encoding="utf-8",
        )

        from codex_quota_watch import cli

        args = mock.Mock(state_dir=str(Path(self.tmp.name)), dry_run=True)
        delivered = []

        def notifier(alert, receipt_dir):
            delivered.append(alert["id"])
            return {"status": "failed"}

        with mock.patch.object(cli, "_load_posts", side_effect=AssertionError("paused poll attempted source read")) as source:
            result = cli._poll(args, self.store, now=NOW, notifier=notifier)
        source.assert_not_called()
        self.assertTrue(result["skipped"])
        self.assertTrue(result["daily_pause"])
        self.assertEqual(delivered, [second[0]["id"]])
        self.assertEqual([item["id"] for item in self.store.pending()], [second[0]["id"]])

    def test_gate_and_tick_cli_emit_parseable_json_without_fetching_source(self) -> None:
        from codex_quota_watch import cli

        self.store.set_settings(daily_pause="off")
        for command in ("settings", "gate", "tick"):
            with self.subTest(command=command):
                stdout = io.StringIO()
                argv = ["--state-dir", str(self.tmp.name), command]
                if command == "tick":
                    argv.append("--dry-run")
                with mock.patch.object(cli, "_load_posts", side_effect=AssertionError("gate/tick must not read source")) as source:
                    with redirect_stdout(stdout):
                        code = cli.main(argv)
                self.assertEqual(code, 0)
                self.assertIsInstance(json.loads(stdout.getvalue()), dict)
                source.assert_not_called()


if __name__ == "__main__":
    unittest.main()
