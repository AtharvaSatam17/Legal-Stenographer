"""
Phase 1, Step 8 — Tests for push-to-command staff override.
Verifies: scratch bypasses pending window, replace goes through pending.
"""

import sys
import os
import asyncio
import json
import pytest
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..'))

from unittest.mock import AsyncMock, MagicMock, patch
from datetime import datetime
from core.session_manager import SessionManager
from services.realtime.content_correction_handler import ContentCorrectionHandler


def setup_session():
    sm = SessionManager()
    ws = AsyncMock()
    session = sm.create_session(ws, {"username": "lawyer", "client_role": "plaintiff"})
    session_id = session["id"]

    session["segments"] = [
        {
            "segment_id": "seg_001",
            "transcript": "First lawyer statement.",
            "speaker_heuristic": "LAWYER",
            "speaker_confidence": 0.75,
            "timestamp": datetime.now().isoformat(),
            "language": "en-IN",
            "start_time_seconds": 0.0,
            "end_time_seconds": 5.0,
        },
        {
            "segment_id": "seg_002",
            "transcript": "Second lawyer statement.",
            "speaker_heuristic": "LAWYER",
            "speaker_confidence": 0.75,
            "timestamp": datetime.now().isoformat(),
            "language": "en-IN",
            "start_time_seconds": 5.0,
            "end_time_seconds": 10.0,
        },
    ]

    handler = ContentCorrectionHandler(session_manager=sm)
    return sm, ws, session, session_id, handler


@pytest.mark.asyncio
async def test_push_scratch_bypasses_pending():
    """Push scratch is proposed and immediately accepted — no pending entry left."""
    sm, ws, session, session_id, handler = setup_session()

    # Simulate push-to-command scratch
    push_command = {"kind": "scratch"}
    push_segment_data = {
        "segment_id": "push_abc",
        "transcript": "[staff push: scratch]",
        "speaker_heuristic": "STAFF",
        "speaker_confidence": 1.0,
        "timestamp": datetime.now().isoformat(),
        "language": "en-IN",
        "start_time_seconds": None,
        "end_time_seconds": None,
    }

    # Propose
    await handler.propose(session_id, push_command, push_segment_data)
    # Immediately accept (simulating what realtime_service does)
    pending_ids = list(session["pending_content_corrections"].keys())
    assert len(pending_ids) == 1
    await handler.accept(session_id, pending_ids[0], "auto_pushed:staff")

    # Result: pending is empty, log has the correction with auto_pushed
    assert len(session["pending_content_corrections"]) == 0
    assert len(session["content_corrections"]) == 1
    entry = session["content_corrections"][0]
    assert entry["kind"] == "scratch"
    assert entry["confirmed_by"] == "auto_pushed:staff"
    assert entry["target_segment_id"] == "seg_002"  # most recent LAWYER

    print("✅ test_push_scratch_bypasses_pending PASSED")


@pytest.mark.asyncio
async def test_push_replace_stays_pending():
    """Push replace creates a pending entry (normal window applies)."""
    sm, ws, session, session_id, handler = setup_session()

    push_command = {"kind": "replace", "replacement": "Corrected lawyer statement."}
    push_segment_data = {
        "segment_id": "push_def",
        "transcript": "[staff push: replace]",
        "speaker_heuristic": "STAFF",
        "speaker_confidence": 1.0,
        "timestamp": datetime.now().isoformat(),
        "language": "en-IN",
        "start_time_seconds": None,
        "end_time_seconds": None,
    }

    await handler.propose(session_id, push_command, push_segment_data)

    # Should be pending (not immediately committed)
    assert len(session["pending_content_corrections"]) == 1
    assert len(session["content_corrections"]) == 0

    corr = list(session["pending_content_corrections"].values())[0]
    assert corr["kind"] == "replace"
    assert corr["replacement_text"] == "Corrected lawyer statement."
    assert corr["target_segment_id"] == "seg_002"

    print("✅ test_push_replace_stays_pending PASSED")


@pytest.mark.asyncio
async def test_push_scratch_no_lawyer_emits_failure():
    """Push scratch with no LAWYER segments emits correction_failed."""
    sm = SessionManager()
    ws = AsyncMock()
    session = sm.create_session(ws, {"username": "lawyer", "client_role": "plaintiff"})
    session_id = session["id"]

    # Only CLIENT segments
    session["segments"] = [
        {"segment_id": "seg_c", "transcript": "client says something",
         "speaker_heuristic": "CLIENT", "speaker_confidence": 0.65,
         "timestamp": "t", "language": "en-IN",
         "start_time_seconds": 0.0, "end_time_seconds": 3.0},
    ]

    handler = ContentCorrectionHandler(session_manager=sm)

    await handler.propose(session_id, {"kind": "scratch"}, {
        "segment_id": "push_x", "transcript": "[push]",
        "speaker_heuristic": "STAFF", "speaker_confidence": 1.0,
        "timestamp": "t", "language": "en-IN",
        "start_time_seconds": None, "end_time_seconds": None,
    })

    msg = json.loads(ws.send_text.call_args_list[-1][0][0])
    assert msg["type"] == "correction_failed"
    assert msg["reason"] == "no_target"

    print("✅ test_push_scratch_no_lawyer_emits_failure PASSED")


if __name__ == "__main__":
    asyncio.run(test_push_scratch_bypasses_pending())
    asyncio.run(test_push_replace_stays_pending())
    asyncio.run(test_push_scratch_no_lawyer_emits_failure())
    print("\n🎉 All push-to-command tests passed!")
