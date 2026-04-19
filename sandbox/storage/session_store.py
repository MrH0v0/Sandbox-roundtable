from __future__ import annotations

import json
import re
from datetime import datetime
from pathlib import Path

from sandbox.schemas.discussion import SessionRecord, SessionStatus, SessionSummary


class SessionStore:
    """Persist session records as local JSON files."""

    SAFE_SESSION_ID = re.compile(r"^[A-Za-z0-9_.-]+$")

    def __init__(self, sessions_dir: Path):
        self.sessions_dir = sessions_dir
        self.sessions_dir.mkdir(parents=True, exist_ok=True)

    def save(self, session: SessionRecord) -> Path:
        target_path = self._session_path(session.session_id)
        payload = session.model_dump(mode="json")
        target_path.write_text(
            json.dumps(payload, ensure_ascii=False, indent=2),
            encoding="utf-8",
        )
        return target_path

    def load(self, session_id: str) -> SessionRecord:
        target_path = self._session_path(session_id)
        if not target_path.exists():
            raise FileNotFoundError(f"Session '{session_id}' was not found.")

        payload = json.loads(target_path.read_text(encoding="utf-8"))
        return SessionRecord.model_validate(payload)

    def delete(self, session_id: str) -> None:
        target_path = self._session_path(session_id)
        if not target_path.exists():
            raise FileNotFoundError(f"Session '{session_id}' was not found.")
        target_path.unlink()

    def _session_path(self, session_id: str) -> Path:
        cleaned = str(session_id or "").strip()
        if not cleaned or cleaned in {".", ".."} or not self.SAFE_SESSION_ID.fullmatch(cleaned):
            raise ValueError("Session id contains unsafe path characters.")

        target_path = (self.sessions_dir / f"{cleaned}.json").resolve()
        sessions_root = self.sessions_dir.resolve()
        if target_path.parent != sessions_root:
            raise ValueError("Session id resolves outside the sessions directory.")
        return target_path

    def list_summaries(self, *, limit: int | None = None) -> list[SessionSummary]:
        paths = sorted(
            self.sessions_dir.glob("*.json"),
            key=lambda current_path: current_path.stat().st_mtime,
            reverse=True,
        )

        if limit is not None:
            paths = paths[:limit]

        return [self._build_summary(path) for path in paths]

    def _build_summary(self, path: Path) -> SessionSummary:
        try:
            payload = json.loads(path.read_text(encoding="utf-8"))
        except Exception as exc:
            return SessionSummary(
                session_id=path.stem,
                title=path.stem,
                config_name="Unknown",
                status="invalid",
                source_path=str(path),
                error=str(exc),
            )

        if not isinstance(payload, dict):
            return SessionSummary(
                session_id=path.stem,
                title=path.stem,
                config_name="Unknown",
                status="invalid",
                source_path=str(path),
                error="Session file does not contain a JSON object.",
            )

        scenario = payload.get("scenario") or {}
        member_memories = payload.get("member_memories") or {}
        rounds = payload.get("rounds") or []
        created_at = self._parse_datetime(payload.get("created_at"))
        completed_at = self._parse_datetime(payload.get("completed_at"))
        stored_status = payload.get("status")
        stored_error = payload.get("error")

        if isinstance(stored_status, str) and stored_status:
            status = stored_status
        else:
            status = SessionStatus.COMPLETED if completed_at else "incomplete"
            if payload.get("markdown_summary") == "" and not completed_at and rounds:
                status = SessionStatus.RUNNING

        return SessionSummary(
            session_id=str(payload.get("session_id") or path.stem),
            title=str(scenario.get("title") or path.stem),
            config_name=str(payload.get("config_name") or "Unknown"),
            status=status,
            source_path=str(path),
            created_at=created_at,
            completed_at=completed_at,
            round_count=len(rounds) if isinstance(rounds, list) else 0,
            member_count=len(member_memories) if isinstance(member_memories, dict) else 0,
            error=str(stored_error) if stored_error else None,
        )

    @staticmethod
    def _parse_datetime(value: object) -> datetime | None:
        if not value or not isinstance(value, str):
            return None

        try:
            return datetime.fromisoformat(value.replace("Z", "+00:00"))
        except ValueError:
            return None
