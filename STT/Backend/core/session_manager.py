# core/session_manager.py

from typing import Dict, Any, Optional
from fastapi import WebSocket
from datetime import datetime
import uuid
import time
import logging

logger = logging.getLogger(__name__)
logger.setLevel(logging.INFO)


class SessionManager:

    def __init__(self):
        self._sessions: Dict[str, Dict[str, Any]] = {}

    # --------------------------------------------------
    # Create
    # --------------------------------------------------
    def create_session(self, websocket: WebSocket, data: dict) -> Dict[str, Any]:
        try:
            session_id = f"realtime_{int(time.time())}_{uuid.uuid4().hex[:8]}"

            # client_role: "plaintiff" or "defendant" — configurable per case
            client_role = data.get("client_role", "plaintiff").lower()
            if client_role not in ("plaintiff", "defendant"):
                client_role = "plaintiff"

            session = {
                "id": session_id,
                "websocket": websocket,
                "start_time": datetime.now(),
                "audio_buffer": [],
                "current_chunk": [],
                "transcript_buffer": "",
                "raw_transcript_buffer": "",  # Phase 1, Step 7 — verbatim STT, never mutated by corrections
                "speakers": set(),
                "detected_language": None,
                "language_confidence": {},
                "preferred_language": data.get("preferred_language"),
                "processing_mode": data.get("processing_mode", "transcribe"),
                "username": data.get("username"),
                "context": data.get("context", "Legal"),
                # Consultation-specific fields
                "case_id": data.get("case_id"),
                "matter_type": data.get("matter_type", "consultation"),
                "client_role": client_role,  # "plaintiff" or "defendant"
                # Speaker assignment
                "speaker_tags": {},  # Manual: {"SPEAKER_1": "LAWYER", "SPEAKER_2": "PLAINTIFF"}
                # Segment tracking with corrections
                # A segment may also be a lightweight paragraph-break marker:
                # {"segment_id": ..., "is_paragraph_break": True, "transcript": "", ...}
                "segments": [],  # List of {segment_id, transcript, speaker_heuristic, timestamp, start_time_seconds, end_time_seconds}
                "speaker_corrections": {},  # {segment_id: {"role": str, "start_time_seconds": float}}
                # VAD state
                "vad_active": False,
                "speech_in_progress": False,
            }

            self._sessions[session_id] = session

            logger.info(f"Session created: {session_id} (client_role={client_role})")
            return session

        except Exception as e:
            logger.exception("Failed to create session")
            raise

    # --------------------------------------------------
    # Read
    # --------------------------------------------------
    def get_session(self, session_id: str) -> Optional[Dict[str, Any]]:
        session = self._sessions.get(session_id)

        if not session:
            logger.warning(f"Session not found: {session_id}")

        return session

    def exists(self, session_id: str) -> bool:
        exists = session_id in self._sessions

        if not exists:
            logger.debug(f"Session existence check failed: {session_id}")

        return exists

    def list_sessions(self):
        sessions = list(self._sessions.keys())
        logger.debug(f"Listing active sessions: {len(sessions)} sessions")
        return sessions

    # --------------------------------------------------
    # Delete
    # --------------------------------------------------
    def delete_session(self, session_id: str):
        try:
            if session_id in self._sessions:
                del self._sessions[session_id]
                logger.info(f"Session deleted: {session_id}")
            else:
                logger.warning(f"Tried deleting non-existent session: {session_id}")

        except Exception:
            logger.exception(f"Error deleting session: {session_id}")

    # --------------------------------------------------
    # Clear (For shutdown)
    # --------------------------------------------------
    def clear(self):
        try:
            total = len(self._sessions)
            self._sessions.clear()
            logger.info(f"Cleared all sessions. Total removed: {total}")

        except Exception:
            logger.exception("Failed to clear sessions")
