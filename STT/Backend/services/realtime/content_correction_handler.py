# services/realtime/content_correction_handler.py
#
# Phase 1, Step 3 — ContentCorrectionHandler
#
# Manages the lifecycle of voice-driven content corrections:
#   propose → (pending) → accept / reject / auto-commit (timeout) → applied
#   reverse → undo a previously applied correction
#
# Target resolution (confirmed decision): always target the most recent
# LAWYER segment. Commands are lawyer-only; no same-speaker matching.

import asyncio
import json
import uuid
from datetime import datetime, timedelta
from typing import Dict, Optional


# Auto-commit timeout in seconds
_AUTO_COMMIT_TIMEOUT_SECONDS = 10


class ContentCorrectionHandler:

    def __init__(self, session_manager):
        self.session_manager = session_manager
        # Track asyncio timers so we can cancel them on accept/reject
        self._timers: Dict[str, asyncio.Task] = {}  # correction_id → timer task

    # ==================================================================
    # PROPOSE — called by AudioStreamHandler when a command is detected
    # ==================================================================
    async def propose(
        self,
        session_id: str,
        command: Dict,
        command_segment_data: Dict,
    ):
        """
        Create a pending content correction proposal.

        Args:
            session_id: Active session id
            command: {"kind": "scratch"} or {"kind": "replace", "replacement": "..."}
            command_segment_data: Full segment metadata for the command utterance
        """
        session = self.session_manager.get_session(session_id)
        if not session:
            return

        websocket = session["websocket"]
        segments = session.get("segments", [])

        # ---------------------------------------------------------------
        # Target resolution: most recent LAWYER segment (hardcoded).
        # ---------------------------------------------------------------
        target_segment = None
        for seg in reversed(segments):
            if seg.get("speaker_heuristic", "").upper() == "LAWYER":
                target_segment = seg
                break

        if target_segment is None:
            await websocket.send_text(json.dumps({
                "type": "correction_failed",
                "session_id": session_id,
                "reason": "no_target",
                "command": command,
                "command_segment_id": command_segment_data["segment_id"],
                "message": "No LAWYER segment found to correct.",
            }))
            return

        # ---------------------------------------------------------------
        # Build the correction proposal
        # ---------------------------------------------------------------
        session["content_correction_seq"] += 1
        seq = session["content_correction_seq"]
        correction_id = f"corr_{seq:05d}"

        kind = command["kind"]
        replacement_text = command.get("replacement") if kind == "replace" else None

        now = datetime.utcnow()
        auto_commit_at = now + timedelta(seconds=_AUTO_COMMIT_TIMEOUT_SECONDS)

        pending_entry = {
            "correction_id": correction_id,
            "proposed_at": now.isoformat() + "Z",
            "auto_commit_at": auto_commit_at.isoformat() + "Z",
            "kind": kind,
            "target_segment_id": target_segment["segment_id"],
            "target_start_time_seconds": target_segment.get("start_time_seconds"),
            "original_text": target_segment["transcript"],
            "replacement_text": replacement_text,
            "command_segment_id": command_segment_data["segment_id"],
            "command_start_time_seconds": command_segment_data.get("start_time_seconds"),
            "author_username": session.get("username"),
            "stt_confidence": target_segment.get("speaker_confidence"),
        }

        session["pending_content_corrections"][correction_id] = pending_entry

        # ---------------------------------------------------------------
        # Notify frontend
        # ---------------------------------------------------------------
        await websocket.send_text(json.dumps({
            "type": "correction_proposed",
            "session_id": session_id,
            "correction_id": correction_id,
            "kind": kind,
            "target_segment_id": target_segment["segment_id"],
            "original_text": target_segment["transcript"],
            "replacement_text": replacement_text,
            "auto_commit_at": auto_commit_at.isoformat() + "Z",
            "command_segment_id": command_segment_data["segment_id"],
        }))

        # ---------------------------------------------------------------
        # Schedule auto-commit timer
        # ---------------------------------------------------------------
        timer_task = asyncio.create_task(
            self._auto_commit_timer(session_id, correction_id)
        )
        self._timers[correction_id] = timer_task

        print(
            f"📋 Correction proposed: {correction_id} kind={kind} "
            f"target={target_segment['segment_id']} session={session_id}"
        )

    # ==================================================================
    # ACCEPT — staff explicitly accepts the proposed correction
    # ==================================================================
    async def accept(self, session_id: str, correction_id: str, staff_username: str):
        """Accept a pending correction (staff action)."""
        await self._commit(session_id, correction_id, confirmed_by=staff_username)

    # ==================================================================
    # REJECT — staff explicitly rejects the proposed correction
    # ==================================================================
    async def reject(self, session_id: str, correction_id: str, staff_username: str):
        """Reject a pending correction (staff action)."""
        session = self.session_manager.get_session(session_id)
        if not session:
            return

        websocket = session["websocket"]
        pending = session["pending_content_corrections"]

        if correction_id not in pending:
            await websocket.send_text(json.dumps({
                "type": "correction_failed",
                "session_id": session_id,
                "reason": "not_pending",
                "correction_id": correction_id,
            }))
            return

        entry = pending.pop(correction_id)
        self._cancel_timer(correction_id)

        # Record the rejection in the append-only log
        rejection_record = {
            "correction_id": entry["correction_id"],
            "correction_timestamp": datetime.utcnow().isoformat() + "Z",
            "kind": "rejected",
            "target_segment_id": entry["target_segment_id"],
            "target_start_time_seconds": entry["target_start_time_seconds"],
            "original_text": entry["original_text"],
            "replacement_text": entry["replacement_text"],
            "command_segment_id": entry["command_segment_id"],
            "command_start_time_seconds": entry["command_start_time_seconds"],
            "author_username": entry["author_username"],
            "confirmed_by": f"rejected_by:{staff_username}",
            "confirmation_timestamp": datetime.utcnow().isoformat() + "Z",
            "stt_confidence": entry.get("stt_confidence"),
            "reverses_correction_id": None,
        }
        session["content_corrections"].append(rejection_record)

        await websocket.send_text(json.dumps({
            "type": "correction_rejected",
            "session_id": session_id,
            "correction_id": correction_id,
            "target_segment_id": entry["target_segment_id"],
            "rejected_by": staff_username,
        }))

        print(f"❌ Correction rejected: {correction_id} by {staff_username} session={session_id}")

    # ==================================================================
    # REVERSE — undo a previously applied correction (append-only)
    # ==================================================================
    async def reverse(self, session_id: str, correction_id: str, staff_username: str):
        """
        Reverse a previously applied correction. Does NOT mutate history —
        appends a new 'reverse' entry pointing at the original.
        """
        session = self.session_manager.get_session(session_id)
        if not session:
            return

        websocket = session["websocket"]

        # Find the original correction in the log
        original = None
        for entry in session["content_corrections"]:
            if entry["correction_id"] == correction_id and entry["kind"] in ("scratch", "replace"):
                original = entry
                break

        if original is None:
            await websocket.send_text(json.dumps({
                "type": "correction_failed",
                "session_id": session_id,
                "reason": "not_found",
                "correction_id": correction_id,
            }))
            return

        # Generate a new correction_id for the reversal entry
        session["content_correction_seq"] += 1
        seq = session["content_correction_seq"]
        reversal_id = f"corr_{seq:05d}"

        reversal_record = {
            "correction_id": reversal_id,
            "correction_timestamp": datetime.utcnow().isoformat() + "Z",
            "kind": "reverse",
            "target_segment_id": original["target_segment_id"],
            "target_start_time_seconds": original["target_start_time_seconds"],
            "original_text": original["original_text"],
            "replacement_text": None,
            "command_segment_id": None,
            "command_start_time_seconds": None,
            "author_username": staff_username,
            "confirmed_by": staff_username,
            "confirmation_timestamp": datetime.utcnow().isoformat() + "Z",
            "stt_confidence": None,
            "reverses_correction_id": correction_id,
        }
        session["content_corrections"].append(reversal_record)

        await websocket.send_text(json.dumps({
            "type": "correction_reversed",
            "session_id": session_id,
            "correction_id": reversal_id,
            "reverses_correction_id": correction_id,
            "target_segment_id": original["target_segment_id"],
        }))

        print(f"↩️ Correction reversed: {reversal_id} reverses {correction_id} session={session_id}")

    # ==================================================================
    # FORCE COMMIT — used by end-of-session grace handling (Step 5)
    # ==================================================================
    async def force_commit_all_pending(self, session_id: str):
        """Force-commit all pending corrections (e.g. on session end)."""
        session = self.session_manager.get_session(session_id)
        if not session:
            return

        pending_ids = list(session["pending_content_corrections"].keys())
        for cid in pending_ids:
            await self._commit(session_id, cid, confirmed_by="ended_session_auto")

    # ==================================================================
    # INTERNAL — commit (shared by accept + auto-timeout + force)
    # ==================================================================
    async def _commit(self, session_id: str, correction_id: str, confirmed_by: str):
        """Move a pending correction to the applied log."""
        session = self.session_manager.get_session(session_id)
        if not session:
            return

        websocket = session["websocket"]
        pending = session["pending_content_corrections"]

        if correction_id not in pending:
            # Already committed/rejected/expired — no-op
            return

        entry = pending.pop(correction_id)
        self._cancel_timer(correction_id)

        now = datetime.utcnow().isoformat() + "Z"

        applied_record = {
            "correction_id": entry["correction_id"],
            "correction_timestamp": now,
            "kind": entry["kind"],
            "target_segment_id": entry["target_segment_id"],
            "target_start_time_seconds": entry["target_start_time_seconds"],
            "original_text": entry["original_text"],
            "replacement_text": entry["replacement_text"],
            "command_segment_id": entry["command_segment_id"],
            "command_start_time_seconds": entry["command_start_time_seconds"],
            "author_username": entry["author_username"],
            "confirmed_by": confirmed_by,
            "confirmation_timestamp": now,
            "stt_confidence": entry.get("stt_confidence"),
            "reverses_correction_id": None,
        }
        session["content_corrections"].append(applied_record)

        await websocket.send_text(json.dumps({
            "type": "correction_applied",
            "session_id": session_id,
            "correction_id": correction_id,
            "kind": entry["kind"],
            "target_segment_id": entry["target_segment_id"],
            "original_text": entry["original_text"],
            "replacement_text": entry["replacement_text"],
            "confirmed_by": confirmed_by,
            "confirmation_timestamp": now,
        }))

        print(
            f"✅ Correction applied: {correction_id} kind={entry['kind']} "
            f"confirmed_by={confirmed_by} session={session_id}"
        )

    # ==================================================================
    # INTERNAL — auto-commit timer
    # ==================================================================
    async def _auto_commit_timer(self, session_id: str, correction_id: str):
        """Wait for timeout then auto-commit if still pending."""
        try:
            await asyncio.sleep(_AUTO_COMMIT_TIMEOUT_SECONDS)
            # Check if still pending (may have been accepted/rejected already)
            session = self.session_manager.get_session(session_id)
            if session and correction_id in session.get("pending_content_corrections", {}):
                await self._commit(session_id, correction_id, confirmed_by="auto_timeout")
        except asyncio.CancelledError:
            pass  # Timer was cancelled (accept/reject arrived before timeout)

    # ==================================================================
    # INTERNAL — cancel a pending timer
    # ==================================================================
    def _cancel_timer(self, correction_id: str):
        """Cancel the auto-commit timer for a correction."""
        task = self._timers.pop(correction_id, None)
        if task and not task.done():
            task.cancel()
