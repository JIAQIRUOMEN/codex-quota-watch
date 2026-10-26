from __future__ import annotations

import hashlib
import re
import secrets
from datetime import datetime, timezone
from email.utils import parsedate_to_datetime
from typing import Any, Iterable
from urllib.parse import urlparse

from .daily import gate_for_alert

ALLOWED_AUTHORS = frozenset({"thsottiaux"})
_CONFIRMED = re.compile(
    r"\b(?:reset (?:has been |is |was )?(?:completed|complete|done)|quota (?:has(?: been)? |was )reset|quota is reset|quota reset (?:is )?(?:completed|complete|done)|resets? (?:has been |is |was )?(?:completed|complete|done))\b",
    re.I,
)
_ANNOUNCE = re.compile(r"\b(?:reset|resets|resetting)\b", re.I)
_ESTIMATE = re.compile(r"\b(?:probably|likely|expect(?:ed)?|around|about|approximately|maybe|today|tomorrow|next week|~|estimate[ds]?)\b", re.I)
_CODEX_CONTEXT = re.compile(r"\b(?:codex|quota)\b", re.I)


def _field(post: dict[str, Any], *names: str) -> Any:
    for name in names:
        if post.get(name) is not None:
            return post[name]
    return None


def _author(post: dict[str, Any]) -> str:
    value = _field(post, "author", "user", "username", "screen_name", "handle")
    if isinstance(value, dict):
        value = _field(value, "username", "screen_name", "handle", "name")
    return str(value or "").strip().lstrip("@").lower()


def validate_post(post: Any, author_allowlist: Iterable[str] = ALLOWED_AUTHORS) -> dict[str, Any]:
    """Validate and normalize a public-post-shaped object; reject malformed data."""
    if not isinstance(post, dict):
        raise ValueError("post must be a JSON object")
    post_id = _field(post, "id", "rest_id", "post_id")
    author = _author(post)
    text = _field(post, "text", "full_text", "content")
    if post_id is None or not str(post_id).strip():
        raise ValueError("post is missing id")
    post_id = str(post_id).strip()
    if not re.fullmatch(r"[A-Za-z0-9_-]{1,100}", post_id):
        raise ValueError("post id must contain only letters, digits, underscores, or hyphens")
    if not author:
        raise ValueError("post is missing author")
    allow = {str(item).strip().lower().lstrip("@") for item in author_allowlist}
    if author not in allow:
        raise ValueError("post author is not allowlisted")
    if not isinstance(text, str) or not text.strip():
        raise ValueError("post is missing text")
    created = _field(post, "created_at", "createdAt", "published_at", "date")
    url = _field(post, "url", "permalink")
    if not url:
        url = f"https://x.com/{author}/status/{post_id}"
    if not isinstance(url, str):
        raise ValueError("post URL must be http(s)")
    parsed_url = urlparse(url)
    if parsed_url.scheme not in {"http", "https"} or parsed_url.hostname not in {"x.com", "www.x.com", "twitter.com", "www.twitter.com"}:
        raise ValueError("post URL must point to x.com or twitter.com")
    path_parts = [part.lower() for part in parsed_url.path.split("/") if part]
    if path_parts and path_parts[0] not in {author, "i"}:
        raise ValueError("post URL author does not match post author")
    return {"id": str(post_id).strip(), "author": author, "text": text.strip(), "created_at": str(created or ""), "url": url}


def _beijing_time(raw: str) -> str:
    if not raw:
        return ""
    try:
        try:
            parsed = datetime.fromisoformat(raw.replace("Z", "+00:00"))
        except ValueError:
            parsed = parsedate_to_datetime(raw)
        if parsed.tzinfo is None:
            return raw[:180] + " (来源未注明时区)"
        from datetime import timedelta
        local = parsed.astimezone(timezone(timedelta(hours=8)))
        return local.strftime("%Y-%m-%d %H:%M UTC+08:00 (北京时间)")
    except (ValueError, OverflowError):
        return raw[:180] + " (原始来源时间)"


def classify_post(post: Any, author_allowlist: Iterable[str] = ALLOWED_AUTHORS) -> dict[str, Any]:
    """Classify only explicit completion language as a confirmed reset."""
    allow = {str(item).strip().lower().lstrip("@") for item in author_allowlist}
    normalized = validate_post(post, allow)
    text = normalized["text"]
    stage = "irrelevant"
    if normalized["author"] in allow and _CODEX_CONTEXT.search(text):
        # Quoted claims, denials, and conditional/future statements are not completion evidence.
        evidence_text = re.sub(r"“[^”]*”|‘[^’]*’|\"[^\"]*\"|'[^']*'", " ", text, flags=re.S)
        match = _CONFIRMED.search(evidence_text)
        contextual_block = re.search(r"\b(?:if|when|unless|not|never|no longer|not yet|isn't|wasn't|hasn't|won't|wouldn't)\b", evidence_text, re.I)
        estimated_completion = bool(_ESTIMATE.search(evidence_text))
        if match and not contextual_block and not estimated_completion:
            stage = "confirmed"
        elif _CONFIRMED.search(text) and not match:
            stage = "irrelevant"
        elif re.search(r"\breset\b.{0,35}\b(?:not|never|isn't|wasn't|hasn't)\b.{0,25}\b(?:complete|completed|done|live|reset)\b", evidence_text, re.I):
            stage = "irrelevant"
        elif re.search(r"\b(?:if|when|unless)\b.{0,40}\breset\b.{0,35}\b(?:complete|completed|done)\b", evidence_text, re.I):
            stage = "irrelevant"
        elif _ANNOUNCE.search(text):
            stage = "announcement"
    timing_kind = "unknown"
    reset_at = None
    if stage != "irrelevant":
        # An estimate / announcement is never evidence that a reset completed.
        if _ESTIMATE.search(text):
            timing_kind = "estimated"
            reset_at = _ESTIMATE.search(text).group(0)
        else:
            time_match = re.search(r"\b(?:at|on)\s+\d{1,2}(?::\d{2})?\s*(?:am|pm|utc|gmt|pt|et|cet|cest)?\b", text, re.I)
            if time_match:
                timing_kind = "explicit"
                reset_at = time_match.group(0)
        if timing_kind == "estimated" and stage == "confirmed":
            stage = "announcement"
    published = _beijing_time(normalized["created_at"])
    return {**normalized, "stage": stage, "timing": timing_kind, "reset_at": reset_at if timing_kind == "explicit" else None, "timing_phrase": reset_at, "published_beijing": published}


def _safe_id(post_id: str, stage: str) -> str:
    raw = f"{post_id}-{stage}"
    return raw if re.fullmatch(r"[A-Za-z0-9_-]{1,100}", raw) else "a" + hashlib.sha256(raw.encode()).hexdigest()[:32]


def make_alert(classified: dict[str, Any]) -> dict[str, Any]:
    stage = classified["stage"]
    timing_kind = classified["timing"]
    timing = {
        "kind": timing_kind,
        "published_text": f"原帖时间：{classified['published_beijing']}" if classified["published_beijing"] else "原帖时间：来源未提供",
        "text": (f"原帖明确时间：{classified['reset_at']}（保留原帖时区）。" if stage == "confirmed" and classified.get("reset_at") else ("完成时刻未具体说明。" if stage == "confirmed" else (f"原帖明确时间：{classified['reset_at']}（保留原帖时区）；公告不代表重置已完成。" if stage == "announcement" and timing_kind == "explicit" and classified.get("reset_at") else (f"原帖提及：{classified.get('timing_phrase')}；公告不代表重置已完成。" if timing_kind == "estimated" and classified.get("timing_phrase") else ("作者发布了重置相关公告；公告不代表重置已完成。" if stage == "announcement" else "时间未知。"))))),
        "basis": (f"原帖明确给出时间短语：{classified['reset_at']}" if stage == "confirmed" and classified.get("reset_at") else (f"原帖估计/提及“{classified.get('timing_phrase')}”；未推断完成时间。" if timing_kind == "estimated" else ("原帖未提供可核验的生效时刻。" if stage == "confirmed" else "仅依据原帖公告措辞；未推断完成时间。"))),
        "confidence": "来源措辞" if stage == "confirmed" else "未确认",
    }
    return {
        "id": _safe_id(classified["id"], stage),
        "receipt_nonce": secrets.token_hex(16),
        "post_id": classified["id"],
        "source_created_at": classified["created_at"],
        "stage": stage,
        "title": "Codex 配额重置已确认" if stage == "confirmed" else "Codex 配额重置公告",
        "message": "thsottiaux 报告 Codex 配额重置已完成。" if stage == "confirmed" else "thsottiaux 发布了 Codex 配额重置公告。",
        "ack_label": "已知晓",
        "url": classified["url"],
        "timing": timing,
    }


def poll_once(store: Any, posts: Iterable[Any], author_allowlist: Iterable[str] = ALLOWED_AUTHORS, now: datetime | None = None) -> list[dict[str, Any]]:
    """Baseline silently once, then persist new author/stage alerts."""
    allow = {str(x).strip().lower().lstrip("@") for x in author_allowlist}
    normalized = []
    for item in posts:
        # Search results may include unrelated authors; discard those before strict validation.
        if isinstance(item, dict) and _author(item) not in allow:
            continue
        normalized.append(validate_post(item, allow))
    is_baseline = store.is_baseline()
    created: list[dict[str, Any]] = []
    for post in normalized:
        # All items are recorded on first poll to avoid historic notification bursts.
        result = classify_post(post, allow)
        stage = result["stage"] if result["author"] in allow else "irrelevant"
        if stage == "irrelevant":
            store.register(result["id"], stage)
            continue
        key_stage = stage
        if is_baseline:
            store.register(result["id"], key_stage)
        else:
            alert = make_alert(result)
            pause_gate = gate_for_alert(alert, store.get_settings(), now=now)
            if store.register(result["id"], key_stage, alert, pause_gate=pause_gate):
                created.append(alert)
    if is_baseline:
        store.finish_baseline()
    return created
