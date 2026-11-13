"""SQLite database access layer for CertRadar."""

import json
import sqlite3
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional, Union

from cert_radar.models import (
    AlertChannel,
    AlertType,
    Certification,
    UserProgress,
    VoucherEvent,
)


class Database:
    """Manages local SQLite database with WAL mode and foreign key constraints."""

    def __init__(self, db_path: Union[Path, str] = "data/cert_radar.db") -> None:
        if str(db_path) == ":memory:":
            self.db_path = ":memory:"
        else:
            self.db_path = Path(db_path)
            self.db_path.parent.mkdir(parents=True, exist_ok=True)

        self.conn = sqlite3.connect(str(self.db_path), check_same_thread=False)
        self.conn.row_factory = sqlite3.Row
        self._configure_pragmas()

    def _configure_pragmas(self) -> None:
        cursor = self.conn.cursor()
        cursor.execute("PRAGMA foreign_keys = ON;")
        cursor.execute("PRAGMA journal_mode = WAL;")

    def init_db(self) -> None:
        """Initializes tables for certifications, events, progress, and alert logs."""
        schema = """
        CREATE TABLE IF NOT EXISTS certifications (
            id TEXT PRIMARY KEY,
            title TEXT NOT NULL,
            provider TEXT NOT NULL,
            track TEXT NOT NULL,
            cost_type TEXT NOT NULL,
            discount_pct INTEGER NOT NULL DEFAULT 0,
            normal_price_usd REAL NOT NULL DEFAULT 0.0,
            exam_code TEXT,
            target_roles TEXT NOT NULL DEFAULT '[]',
            skills_covered TEXT NOT NULL DEFAULT '[]',
            level TEXT NOT NULL DEFAULT 'associate',
            effort_hours INTEGER NOT NULL DEFAULT 10,
            recruiter_signal INTEGER NOT NULL DEFAULT 3,
            url TEXT NOT NULL,
            voucher_program_url TEXT,
            is_voucher_active INTEGER NOT NULL DEFAULT 0,
            activation_epoch INTEGER NOT NULL DEFAULT 1,
            deadline_at TEXT,
            liveness_status TEXT NOT NULL DEFAULT 'unverified',
            source_kind TEXT NOT NULL DEFAULT 'seed',
            last_checked_at TEXT,
            notes TEXT NOT NULL DEFAULT ''
        );

        CREATE TABLE IF NOT EXISTS voucher_events (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            cert_id TEXT NOT NULL REFERENCES certifications(id) ON DELETE CASCADE,
            source_name TEXT NOT NULL,
            event_type TEXT NOT NULL,
            payload_json TEXT NOT NULL DEFAULT '{}',
            detected_at TEXT NOT NULL
        );

        CREATE TABLE IF NOT EXISTS user_progress (
            cert_id TEXT PRIMARY KEY REFERENCES certifications(id) ON DELETE CASCADE,
            status TEXT NOT NULL DEFAULT 'radar',
            user_notes TEXT NOT NULL DEFAULT '',
            updated_at TEXT NOT NULL
        );

        CREATE TABLE IF NOT EXISTS alert_log (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            cert_id TEXT NOT NULL REFERENCES certifications(id) ON DELETE CASCADE,
            channel TEXT NOT NULL,
            alert_type TEXT NOT NULL,
            dedup_key TEXT NOT NULL UNIQUE,
            sent_at TEXT NOT NULL,
            delivery_status TEXT NOT NULL DEFAULT 'sent'
        );

        CREATE INDEX IF NOT EXISTS idx_cert_track ON certifications(track);
        CREATE INDEX IF NOT EXISTS idx_cert_active ON certifications(is_voucher_active);
        CREATE INDEX IF NOT EXISTS idx_alert_dedup ON alert_log(dedup_key);
        """
        cursor = self.conn.cursor()
        cursor.executescript(schema)
        self.conn.commit()

    @staticmethod
    def _row_to_certification(row: sqlite3.Row) -> Certification:
        target_roles = json.loads(row["target_roles"]) if row["target_roles"] else []
        skills_covered = json.loads(row["skills_covered"]) if row["skills_covered"] else []
        return Certification(
            id=row["id"],
            title=row["title"],
            provider=row["provider"],
            track=row["track"],
            cost_type=row["cost_type"],
            discount_pct=row["discount_pct"],
            normal_price_usd=row["normal_price_usd"],
            exam_code=row["exam_code"],
            target_roles=target_roles,
            skills_covered=skills_covered,
            level=row["level"],
            effort_hours=row["effort_hours"],
            recruiter_signal=row["recruiter_signal"],
            url=row["url"],
            voucher_program_url=row["voucher_program_url"],
            is_voucher_active=bool(row["is_voucher_active"]),
            activation_epoch=row["activation_epoch"],
            deadline_at=row["deadline_at"],
            liveness_status=row["liveness_status"],
            source_kind=row["source_kind"],
            last_checked_at=row["last_checked_at"],
            notes=row["notes"],
        )

    def upsert_certification(self, cert: Certification) -> None:
        """Inserts or updates a certification record."""
        target_roles_json = json.dumps(cert.target_roles, ensure_ascii=False)
        skills_covered_json = json.dumps(cert.skills_covered, ensure_ascii=False)
        is_active_int = 1 if cert.is_voucher_active else 0

        query = """
        INSERT INTO certifications (
            id, title, provider, track, cost_type, discount_pct, normal_price_usd,
            exam_code, target_roles, skills_covered, level, effort_hours, recruiter_signal,
            url, voucher_program_url, is_voucher_active, activation_epoch, deadline_at,
            liveness_status, source_kind, last_checked_at, notes
        ) VALUES (
            ?, ?, ?, ?, ?, ?, ?,
            ?, ?, ?, ?, ?, ?,
            ?, ?, ?, ?, ?,
            ?, ?, ?, ?
        )
        ON CONFLICT(id) DO UPDATE SET
            title = excluded.title,
            provider = excluded.provider,
            track = excluded.track,
            cost_type = excluded.cost_type,
            discount_pct = excluded.discount_pct,
            normal_price_usd = excluded.normal_price_usd,
            exam_code = excluded.exam_code,
            target_roles = excluded.target_roles,
            skills_covered = excluded.skills_covered,
            level = excluded.level,
            effort_hours = excluded.effort_hours,
            recruiter_signal = excluded.recruiter_signal,
            url = excluded.url,
            voucher_program_url = excluded.voucher_program_url,
            is_voucher_active = excluded.is_voucher_active,
            activation_epoch = excluded.activation_epoch,
            deadline_at = excluded.deadline_at,
            liveness_status = excluded.liveness_status,
            source_kind = excluded.source_kind,
            last_checked_at = excluded.last_checked_at,
            notes = excluded.notes;
        """
        params = (
            cert.id,
            cert.title,
            cert.provider,
            cert.track,
            cert.cost_type,
            cert.discount_pct,
            cert.normal_price_usd,
            cert.exam_code,
            target_roles_json,
            skills_covered_json,
            cert.level,
            cert.effort_hours,
            cert.recruiter_signal,
            cert.url,
            cert.voucher_program_url,
            is_active_int,
            cert.activation_epoch,
            cert.deadline_at,
            cert.liveness_status,
            cert.source_kind,
            cert.last_checked_at,
            cert.notes,
        )
        cursor = self.conn.cursor()
        cursor.execute(query, params)
        self.conn.commit()

    def get_certifications(
        self,
        track: Optional[str] = None,
        is_active: Optional[bool] = None,
    ) -> list[Certification]:
        """Returns certifications matching optional track and is_active filters."""
        query = "SELECT * FROM certifications"
        conditions = []
        params: list[Union[str, int]] = []

        if track is not None:
            conditions.append("track = ?")
            params.append(track)

        if is_active is not None:
            conditions.append("is_voucher_active = ?")
            params.append(1 if is_active else 0)

        if conditions:
            query += " WHERE " + " AND ".join(conditions)

        query += " ORDER BY recruiter_signal DESC, title ASC;"

        cursor = self.conn.cursor()
        cursor.execute(query, params)
        rows = cursor.fetchall()
        return [self._row_to_certification(row) for row in rows]

    def get_certification(self, cert_id: str) -> Optional[Certification]:
        """Fetches a single certification by its slug ID."""
        cursor = self.conn.cursor()
        cursor.execute("SELECT * FROM certifications WHERE id = ?;", (cert_id,))
        row = cursor.fetchone()
        if not row:
            return None
        return self._row_to_certification(row)

    def record_event(self, event: VoucherEvent) -> None:
        """Records a detected voucher event."""
        query = """
        INSERT INTO voucher_events (cert_id, source_name, event_type, payload_json, detected_at)
        VALUES (?, ?, ?, ?, ?);
        """
        cursor = self.conn.cursor()
        cursor.execute(
            query,
            (
                event.cert_id,
                event.source_name,
                event.event_type,
                event.payload_json,
                event.detected_at,
            ),
        )
        self.conn.commit()

    def get_user_progress(self, cert_id: str) -> Optional[UserProgress]:
        """Retrieves user progress for a given certification."""
        cursor = self.conn.cursor()
        cursor.execute(
            "SELECT cert_id, status, user_notes, updated_at FROM user_progress WHERE cert_id = ?;",
            (cert_id,),
        )
        row = cursor.fetchone()
        if not row:
            return None
        return UserProgress(
            cert_id=row["cert_id"],
            status=row["status"],
            user_notes=row["user_notes"],
            updated_at=row["updated_at"],
        )

    def set_user_progress(self, cert_id: str, status: str, notes: str = "") -> None:
        """Upserts user tracking progress."""
        now_iso = datetime.now(timezone.utc).isoformat()
        query = """
        INSERT INTO user_progress (cert_id, status, user_notes, updated_at)
        VALUES (?, ?, ?, ?)
        ON CONFLICT(cert_id) DO UPDATE SET
            status = excluded.status,
            user_notes = excluded.user_notes,
            updated_at = excluded.updated_at;
        """
        cursor = self.conn.cursor()
        cursor.execute(query, (cert_id, status, notes, now_iso))
        self.conn.commit()

    def has_alert_been_sent(self, dedup_key: str) -> bool:
        """Checks if an alert with the given deduplication key has already been logged."""
        cursor = self.conn.cursor()
        cursor.execute("SELECT 1 FROM alert_log WHERE dedup_key = ? LIMIT 1;", (dedup_key,))
        return cursor.fetchone() is not None

    def log_alert(
        self,
        cert_id: str,
        channel: Union[AlertChannel, str],
        alert_type: Union[AlertType, str],
        dedup_key: str,
        status: str = "sent",
    ) -> None:
        """Logs a sent alert for anti-spam deduplication."""
        now_iso = datetime.now(timezone.utc).isoformat()
        query = """
        INSERT INTO alert_log (cert_id, channel, alert_type, dedup_key, sent_at, delivery_status)
        VALUES (?, ?, ?, ?, ?, ?);
        """
        cursor = self.conn.cursor()
        cursor.execute(query, (cert_id, channel, alert_type, dedup_key, now_iso, status))
        self.conn.commit()

    def close(self) -> None:
        """Closes the underlying SQLite connection."""
        self.conn.close()

    def __enter__(self) -> "Database":
        return self

    def __exit__(self, exc_type, exc_val, exc_tb) -> None:
        self.close()
