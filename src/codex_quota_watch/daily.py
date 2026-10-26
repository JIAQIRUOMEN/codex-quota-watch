"""Opt-in local-day pause policy for reset alerts; no timezone database required."""

from __future__ import annotations

from datetime import datetime, time, timedelta, timezone
from email.utils import parsedate_to_datetime
from typing import Any

DAILY_PAUSE_MODES = frozenset({"confirmed", "announcement", "off"})
DEFAULT_DAILY_SETTINGS = {"daily_pause": "confirmed", "utc_offset_minutes": 480}
UTC = timezone.utc


def settings_defaults() -> dict[str, Any]:
    return dict(DEFAULT_DAILY_SETTINGS)


def validate_settings(settings: dict[str, Any]) -> dict[str, Any]:
    mode = settings.get("daily_pause", DEFAULT_DAILY_SETTINGS["daily_pause"])
    offset = settings.get("utc_offset_minutes", DEFAULT_DAILY_SETTINGS["utc_offset_minutes"])
    if mode not in DAILY_PAUSE_MODES:
        raise ValueError("daily_pause must be confirmed, announcement, or off")
    if isinstance(offset, bool) or not isinstance(offset, int) or not -720 <= offset <= 840:
        raise ValueError("utc_offset_minutes must be an integer from -720 through 840")
    return {"daily_pause": mode, "utc_offset_minutes": offset}


def _aware_now(now: datetime | None = None) -> datetime:
    value = now if now is not None else datetime.now(UTC)
    if value.tzinfo is None or value.utcoffset() is None:
        raise ValueError("now must include a timezone")
    return value.astimezone(UTC)


def parse_source_datetime(raw: Any) -> datetime | None:
    """Parse ISO or RFC source timestamps, refusing naive times rather than guessing."""
    if not isinstance(raw, str) or not raw.strip():
        return None
    value = raw.strip()
    try:
        try:
            parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
        except ValueError:
            parsed = parsedate_to_datetime(value)
    except (TypeError, ValueError, OverflowError):
        return None
    if parsed.tzinfo is None or parsed.utcoffset() is None:
        return None
    return parsed.astimezone(UTC)


def _iso_utc(value: datetime) -> str:
    return value.astimezone(UTC).isoformat(timespec="seconds").replace("+00:00", "Z")


def gate_for_alert(
    alert: dict[str, Any],
    settings: dict[str, Any],
    now: datetime | None = None,
) -> dict[str, Any] | None:
    """Return durable gate metadata only for a new matching-stage alert from today."""
    policy = validate_settings(settings)
    mode = policy["daily_pause"]
    stage = alert.get("stage")
    if mode == "off" or stage not in ({"announcement", "confirmed"} if mode == "announcement" else {"confirmed"}):
        return None
    source_time = parse_source_datetime(alert.get("source_created_at"))
    if source_time is None:
        return None
    current_utc = _aware_now(now)
    offset = policy["utc_offset_minutes"]
    local_tz = timezone(timedelta(minutes=offset))
    local_day = current_utc.astimezone(local_tz).date()
    source_local_day = source_time.astimezone(local_tz).date()
    if source_local_day != local_day:
        return None
    next_day = local_day + timedelta(days=1)
    resume_local = datetime.combine(next_day, time.min, tzinfo=local_tz)
    return {
        "resume_at": _iso_utc(resume_local),
        "triggered_at": _iso_utc(current_utc),
        "trigger_stage": stage,
        "trigger_post_id": str(alert.get("post_id", "")),
        "source_created_at": str(alert.get("source_created_at", "")),
        "local_date": local_day.isoformat(),
        "utc_offset_minutes": offset,
        "mode": mode,
    }


def daily_gate(store: Any, now: datetime | None = None) -> dict[str, Any]:
    """Read/expire the persisted gate without contacting a source."""
    settings = validate_settings(store.get_settings())
    gate = store.get_daily_gate()
    result = evaluate_gate(settings, gate, now=now)
    if result["reason"] in {"settings_changed", "invalid_gate_cleared", "pause_expired"}:
        store.clear_daily_gate()
    return result


def evaluate_gate(settings: dict[str, Any], stored_pause: dict[str, Any] | None, now: datetime | None = None) -> dict[str, Any]:
    """Purely evaluate whether a persisted pause still blocks source reads."""
    policy = validate_settings(settings)
    current_utc = _aware_now(now)
    if stored_pause is None:
        return {"should_fetch": True, "resume_at": None, "reason": "no_active_pause", "trigger_metadata": None}
    if policy["daily_pause"] == "off" or stored_pause.get("mode") != policy["daily_pause"] or stored_pause.get("utc_offset_minutes") != policy["utc_offset_minutes"]:
        return {"should_fetch": True, "resume_at": None, "reason": "settings_changed", "trigger_metadata": stored_pause}
    resume = parse_source_datetime(stored_pause.get("resume_at"))
    if resume is None:
        return {"should_fetch": True, "resume_at": None, "reason": "invalid_gate_cleared", "trigger_metadata": stored_pause}
    if current_utc >= resume:
        return {"should_fetch": True, "resume_at": None, "reason": "pause_expired", "trigger_metadata": stored_pause}
    return {"should_fetch": False, "resume_at": _iso_utc(resume), "reason": "daily_pause_active", "trigger_metadata": stored_pause}
