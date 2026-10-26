from __future__ import annotations

import json
import sqlite3
from contextlib import contextmanager
from pathlib import Path
from typing import Any, Iterator


class Store:
    """SQLite state for seen post/stage keys and alerts pending explicit ack."""

    def __init__(self, path: str | Path):
        self.path = Path(path).expanduser()
        self.path.parent.mkdir(parents=True, exist_ok=True)
        with self._db() as db:
            db.execute("CREATE TABLE IF NOT EXISTS meta (key TEXT PRIMARY KEY, value TEXT NOT NULL)")
            db.execute("CREATE TABLE IF NOT EXISTS seen (post_id TEXT NOT NULL, stage TEXT NOT NULL, PRIMARY KEY(post_id, stage))")
            db.execute("CREATE TABLE IF NOT EXISTS alerts (id TEXT PRIMARY KEY, post_id TEXT NOT NULL, stage TEXT NOT NULL, payload TEXT NOT NULL, acknowledged INTEGER NOT NULL DEFAULT 0, created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP)")

    @contextmanager
    def _db(self) -> Iterator[sqlite3.Connection]:
        db = sqlite3.connect(self.path, timeout=20)
        db.row_factory = sqlite3.Row
        try:
            yield db
            db.commit()
        except Exception:
            db.rollback()
            raise
        finally:
            db.close()

    def is_baseline(self) -> bool:
        with self._db() as db:
            row = db.execute("SELECT value FROM meta WHERE key='baseline_done'").fetchone()
            return row is None

    def finish_baseline(self) -> None:
        with self._db() as db:
            db.execute("INSERT OR REPLACE INTO meta(key,value) VALUES('baseline_done','1')")

    def mark_seen(self, post_id: str, stage: str) -> bool:
        with self._db() as db:
            cursor = db.execute("INSERT OR IGNORE INTO seen(post_id,stage) VALUES(?,?)", (post_id, stage))
            return cursor.rowcount == 1

    def add_alert(self, alert: dict[str, Any]) -> None:
        with self._db() as db:
            db.execute("INSERT OR IGNORE INTO alerts(id,post_id,stage,payload) VALUES(?,?,?,?)", (alert["id"], alert["post_id"], alert["stage"], json.dumps(alert, ensure_ascii=False)))

    def register(self, post_id: str, stage: str, alert: dict[str, Any] | None = None) -> bool:
        """Atomically remember a post/stage and persist its alert, when applicable."""
        with self._db() as db:
            cursor = db.execute("INSERT OR IGNORE INTO seen(post_id,stage) VALUES(?,?)", (post_id, stage))
            if cursor.rowcount != 1:
                return False
            if alert is not None:
                db.execute("INSERT OR IGNORE INTO alerts(id,post_id,stage,payload) VALUES(?,?,?,?)", (alert["id"], post_id, stage, json.dumps(alert, ensure_ascii=False)))
            return True

    def pending(self) -> list[dict[str, Any]]:
        with self._db() as db:
            rows = db.execute("SELECT payload FROM alerts WHERE acknowledged=0 ORDER BY created_at,id").fetchall()
        return [json.loads(row["payload"]) for row in rows]

    def ack(self, alert_id: str) -> bool:
        with self._db() as db:
            cursor = db.execute("UPDATE alerts SET acknowledged=1 WHERE id=? AND acknowledged=0", (alert_id,))
            return cursor.rowcount > 0

    def ack_with_nonce(self, alert_id: str, nonce: str) -> bool:
        """Accept a WPF acknowledgement only for the persisted alert generation."""
        with self._db() as db:
            row = db.execute("SELECT payload,acknowledged FROM alerts WHERE id=?", (alert_id,)).fetchone()
            if row is None or row["acknowledged"] or not nonce:
                return False
            payload = json.loads(row["payload"])
            if payload.get("receipt_nonce") != nonce:
                return False
            cursor = db.execute("UPDATE alerts SET acknowledged=1 WHERE id=? AND acknowledged=0", (alert_id,))
            return cursor.rowcount > 0

    def all_alerts(self) -> list[dict[str, Any]]:
        with self._db() as db:
            rows = db.execute("SELECT payload,acknowledged FROM alerts ORDER BY created_at,id").fetchall()
        return [{**json.loads(row["payload"]), "acknowledged": bool(row["acknowledged"])} for row in rows]
