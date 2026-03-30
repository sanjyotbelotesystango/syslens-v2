"""
memory/session.py — Stateful conversation memory.

Stores conversation turns and the last AnalysisResult per session.
Supports multiple named sessions so the engine can serve multiple users.
"""

from __future__ import annotations
from typing import Dict, Optional

from ..models import ConversationTurn, SessionContext, AnalysisResult
from ..config import settings


class Session:
    """One user's conversation state."""

    def __init__(self, session_id: str):
        self.session_id = session_id
        self._turns: list[ConversationTurn] = []
        self._last_result: Optional[AnalysisResult] = None

    def add_turn(self, role: str, content: str, mode: str | None = None) -> None:
        self._turns.append(ConversationTurn(role=role, content=content, mode=mode))
        # Keep a rolling window to avoid unbounded memory growth
        max_turns = settings.MAX_HISTORY_TURNS * 2
        if len(self._turns) > max_turns:
            self._turns = self._turns[-max_turns:]

    def set_last_result(self, result: AnalysisResult) -> None:
        self._last_result = result

    def get_context(self) -> SessionContext:
        return SessionContext(
            turns=self._turns[-settings.MAX_HISTORY_TURNS:],
            last_result=self._last_result,
            last_mode=self._turns[-1].mode if self._turns else None,
        )

    def clear(self) -> None:
        self._turns.clear()
        self._last_result = None


class SessionStore:
    """
    In-memory store for all active sessions.
    For multi-user deployments, replace this with Redis or a DB-backed store.
    """

    def __init__(self):
        self._sessions: Dict[str, Session] = {}

    def get(self, session_id: str) -> Session:
        if session_id not in self._sessions:
            self._sessions[session_id] = Session(session_id)
        return self._sessions[session_id]

    def clear(self, session_id: str) -> None:
        if session_id in self._sessions:
            self._sessions[session_id].clear()

    def delete(self, session_id: str) -> None:
        self._sessions.pop(session_id, None)


# Default store — one instance shared across the process
_store = SessionStore()


def get_session(session_id: str = "default") -> Session:
    return _store.get(session_id)


def clear_session(session_id: str = "default") -> None:
    _store.clear(session_id)