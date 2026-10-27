"""Offline regression tests for bilingual popup payloads and legacy events."""

from __future__ import annotations

import copy
import json
import re
import tempfile
import unittest
from pathlib import Path

from codex_quota_watch import Store, classify_post, poll_once
from codex_quota_watch.notifier import write_event


SOURCE_TIME = "2026-10-27T01:00:00Z"


class PopupLanguageTests(unittest.TestCase):
    def setUp(self) -> None:
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name)

    def alert_for(self, text: str, post_id: str, created_at: str = SOURCE_TIME) -> dict:
        store = Store(self.root / f"{post_id}.sqlite3")
        store.set_settings(daily_pause="off")
        poll_once(store, [{"id": f"base-{post_id}", "author": "thsottiaux", "text": "routine post", "created_at": created_at}])
        alerts = poll_once(
            store,
            [{"id": post_id, "author": "thsottiaux", "text": text, "created_at": created_at}],
        )
        self.assertEqual(len(alerts), 1)
        return alerts[0]

    def assert_translations(self, alert: dict, stage: str, timing_kind: str, source_phrase: str | None = None) -> None:
        self.assertEqual(alert["stage"], stage)
        translations = alert.get("translations")
        self.assertIsInstance(translations, dict)
        self.assertEqual(set(translations), {"zh-CN", "en"})
        self.assertEqual(alert["title"], translations["zh-CN"]["title"])
        self.assertEqual(alert["message"], translations["zh-CN"]["message"])
        self.assertEqual(alert["ack_label"], translations["zh-CN"]["ack_label"])

        for language in ("zh-CN", "en"):
            with self.subTest(language=language, stage=stage, timing=timing_kind):
                translated = translations[language]
                for field in ("title", "message", "ack_label"):
                    self.assertIsInstance(translated[field], str)
                    self.assertTrue(translated[field].strip())
                if language == "en":
                    self.assertIn("confirmed" if stage == "confirmed" else "announcement", translated["title"].lower())
                    self.assertIn("complete" if stage == "confirmed" else "announcement", translated["message"].lower())
                else:
                    self.assertIn("已确认" if stage == "confirmed" else "公告", translated["title"])
                    self.assertIn("已完成" if stage == "confirmed" else "重置", translated["message"])

                timing = translated["timing"]
                self.assertEqual(timing["kind"], timing_kind)
                self.assertEqual(alert["timing"]["kind"], timing_kind)
                self.assertIn("2026-10-27", timing["published_text"])
                self.assertIn("UTC+08:00", timing["published_text"])
                if source_phrase:
                    source_copy = f"{timing['text']} {timing['basis']}"
                    self.assertIn(source_phrase, source_copy)
                if timing_kind == "unknown":
                    # Publication time is separate metadata; the reset-time text must not invent a clock time.
                    self.assertIsNone(re.search(r"\b\d{1,2}(?::\d{2})?\s*(?:am|pm|utc|gmt)\b", timing["text"], re.I))

    def test_both_stages_and_supported_time_kinds_have_consistent_translations(self) -> None:
        fixtures = (
            ("Codex quota reset is planned at 5 UTC.", "announcement", "explicit", "at 5 UTC"),
            ("Codex quota reset is expected tomorrow.", "announcement", "estimated", None),
            ("Codex quota reset update.", "announcement", "unknown", None),
            ("Codex quota reset is complete at 5 UTC.", "confirmed", "explicit", "at 5 UTC"),
            ("Codex quota reset is complete.", "confirmed", "unknown", None),
        )
        for index, (text, stage, kind, phrase) in enumerate(fixtures):
            with self.subTest(text=text):
                alert = self.alert_for(text, f"language-{index}")
                if kind != "unknown":
                    source = classify_post({
                        "id": f"language-{index}",
                        "author": "thsottiaux",
                        "text": text,
                        "created_at": SOURCE_TIME,
                    })
                    phrase = source["timing_phrase"]
                    self.assertTrue(phrase)
                self.assert_translations(alert, stage, kind, phrase)

    def test_unknown_reset_time_stays_unknown_in_both_languages(self) -> None:
        alert = self.alert_for("Codex quota reset is complete.", "unknown-time")
        self.assert_translations(alert, "confirmed", "unknown")
        for language in ("zh-CN", "en"):
            timing = alert["translations"][language]["timing"]
            self.assertEqual(timing["kind"], "unknown")
            self.assertNotIn("5 PM", timing["text"])

    def test_source_time_without_timezone_is_preserved_without_claiming_utc_plus_eight(self) -> None:
        source_time = "2026-10-27T01:00:00"
        alert = self.alert_for("Codex quota reset is complete.", "naive-source-time", created_at=source_time)
        for language in ("zh-CN", "en"):
            published = alert["translations"][language]["timing"]["published_text"]
            self.assertIn(source_time, published)
        english = alert["translations"]["en"]["timing"]["published_text"]
        self.assertIn("source timezone not specified", english)
        self.assertNotIn("UTC+08:00", english)

    def test_invalid_source_time_marker_is_translated_without_changing_original(self) -> None:
        source_time = "raw-date-from-source"
        alert = self.alert_for("Codex quota reset is complete.", "invalid-source-time", created_at=source_time)
        chinese = alert["translations"]["zh-CN"]["timing"]["published_text"]
        english = alert["translations"]["en"]["timing"]["published_text"]
        self.assertIn(source_time, chinese)
        self.assertIn(source_time, english)
        self.assertIn("原始来源时间", chinese)
        self.assertIn("original source time", english)
        self.assertNotIn("UTC+08:00", english)

    def test_legacy_event_without_translations_remains_accepted_unchanged(self) -> None:
        alert = self.alert_for("Codex quota reset is complete.", "legacy-event")
        legacy = copy.deepcopy(alert)
        legacy.pop("translations")
        event_path = write_event(legacy, self.root / "events")
        saved = json.loads(event_path.read_text(encoding="utf-8"))
        self.assertNotIn("translations", saved)
        self.assertEqual(saved["title"], legacy["title"])
        self.assertEqual(saved["message"], legacy["message"])
        self.assertEqual(saved["id"], legacy["id"])
        self.assertEqual(saved["receipt_nonce"], legacy["receipt_nonce"])

    def test_write_event_preserves_identity_and_nonce_with_bilingual_payload(self) -> None:
        alert = self.alert_for("Codex quota reset is complete at 5 UTC.", "identity-event")
        original_id, original_nonce = alert["id"], alert["receipt_nonce"]
        event_path = write_event(alert, self.root / "events")
        saved = json.loads(event_path.read_text(encoding="utf-8"))
        self.assertEqual(saved["id"], original_id)
        self.assertEqual(saved["receipt_nonce"], original_nonce)
        self.assertEqual(set(saved["translations"]), {"zh-CN", "en"})
        self.assertEqual(set(saved["translations"]["en"]), {"title", "message", "ack_label", "timing"})

    def test_write_event_rejects_incomplete_or_malformed_translations(self) -> None:
        valid = self.alert_for("Codex quota reset is expected tomorrow.", "corrupt-event")
        corruptions = []

        missing_language = copy.deepcopy(valid)
        del missing_language["translations"]["en"]
        corruptions.append(missing_language)

        missing_field = copy.deepcopy(valid)
        del missing_field["translations"]["zh-CN"]["message"]
        corruptions.append(missing_field)

        invalid_type = copy.deepcopy(valid)
        invalid_type["translations"]["en"]["title"] = ["not", "text"]
        corruptions.append(invalid_type)

        invalid_kind = copy.deepcopy(valid)
        invalid_kind["translations"]["en"]["timing"]["kind"] = "certain"
        corruptions.append(invalid_kind)

        mismatched_kind = copy.deepcopy(valid)
        mismatched_kind["translations"]["en"]["timing"]["kind"] = "explicit"
        corruptions.append(mismatched_kind)

        basis_type = copy.deepcopy(valid)
        basis_type["timing"]["basis"] = ["not", "text"]
        corruptions.append(basis_type)

        basis_too_long = copy.deepcopy(valid)
        basis_too_long["timing"]["basis"] = "x" * 351
        corruptions.append(basis_too_long)

        confidence_type = copy.deepcopy(valid)
        confidence_type["timing"]["confidence"] = 7
        corruptions.append(confidence_type)

        confidence_too_long = copy.deepcopy(valid)
        confidence_too_long["timing"]["confidence"] = "x" * 351
        corruptions.append(confidence_too_long)

        no_estimate_basis = copy.deepcopy(valid)
        no_estimate_basis["translations"]["en"]["timing"]["basis"] = ""
        corruptions.append(no_estimate_basis)

        for index, alert in enumerate(corruptions):
            with self.subTest(corruption=index):
                with self.assertRaises(ValueError):
                    write_event(alert, self.root / f"bad-{index}")


if __name__ == "__main__":
    unittest.main()
