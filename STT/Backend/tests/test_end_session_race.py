"""
Phase 1, Step 5 — Test that pending content corrections are force-committed
before the end-of-session snapshot, and that late-arriving transcripts are rejected.
"""

import sys
import os
import asyncio
import pytest
import json
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..'))

from unittest.mock import AsyncMock, MagicMock
from datetime import datetime
from core.session_manager import SessionManager
from services.realtime.content_correction_handler import ContentCorrectionHandler
from services.realtime.audio_stream_handler import AudioStreamHandler


def setup():
    sm = SessionManager()
    ws = AsyncMock()
    session = sm.create_session(ws, {"username": "lawyer", "client_role": "plaintiff"})
    session_id = session["id"]

    # Add some LAWYER segments
    session["segments"] = [
        {
            "segment_id": "seg_001",
            "transcript": "First statement by lawyer.",
            "speaker_heuristic": "LAWYER",
            "speaker_confidence": 0.75,
            "timestamp": datetime.now().isoformat(),
            "language": "en-IN",
            "start_time_seconds": 0.0,
            "end_time_seconds": 4.0,
        },
        {
            "segment_id": "seg_002",
            "transcript": "Second statement by lawyer.",
            "speaker_heuristic": "LAWYER",
            "speaker_confidence": 0.75,
            "timestamp": datetime.now().isoformat(),
            "language": "en-IN",
            "start_time_seconds": 4.0,
            "end_time_seconds": 8.0,
        },
    ]

    handler = ContentCorrectionHandler(session_manager=sm)
    return sm, ws, session, session_id, handler


@pytest.mark.asyncio
async def test_force_commit_before_snapshot():
    """
    Pending corrections are force-committed with 'ended_session_auto' when
    force_commit_all_pending is called (simulating end_session flow).
    """
    sm, ws, session, session_id, handler = setup()

    # Create a pending correction (don't accept it)
    await handler.propose(session_id, {"kind": "scratch"}, {
        "segment_id": "seg_cmd", "transcript": "scratch that",
        "speaker_heuristic": "SPEAKER", "speaker_confidence": 0.3,
        "timestamp": datetime.now().isoformat(), "language": "en-IN",
        "start_time_seconds": 8.0, "end_time_seconds": 9.0,
    })

    assert len(session["pending_content_corrections"]) == 1
    assert len(session["content_corrections"]) == 0

    # Simulate what end_real_time_session does
    session["ending"] = True
    await handler.force_commit_all_pending(session_id)

    # Pending should be empty, log should have the correction
    assert len(session["pending_content_corrections"]) == 0
    assert len(session["content_corrections"]) == 1
    entry = session["content_corrections"][0]
    assert entry["confirmed_by"] == "ended_session_auto"
    assert entry["kind"] == "scratch"
    assert entry["target_segment_id"] == "seg_002"  # most recent LAWYER

    print("✅ test_force_commit_before_snapshot PASSED")


@pytest.mark.asyncio
async def test_late_transcript_rejected_after_ending():
    """
    After session['ending'] = True, _handle_transcript should return early
    without appending or broadcasting.
    """
    sm, ws, session, session_id, handler = setup()
    audio_handler = AudioStreamHandler(
        session_manager=sm,
        vad_service=MagicMock(),
        content_correction_handler=handler,
    )

    # Mark session as ending
    session["ending"] = True
    ws.send_text.reset_mock()

    # Simulate a late-arriving transcript
    event_data = MagicMock()
    event_data.transcript = "This should be rejected."
    event_data.language_code = "en-IN"
    event_data.metrics = MagicMock()
    event_data.metrics.audio_duration = 10.0

    await audio_handler._handle_transcript(session_id, "This should be rejected.", event_data)

    # Nothing should be added to segments
    assert len(session["segments"]) == 2  # still just the original 2
    # No WS message should be sent
    ws.send_text.assert_not_called()

    print("✅ test_late_transcript_rejected_after_ending PASSED")


@pytest.mark.asyncio
async def test_content_corrections_included_in_snapshot():
    """
    After force-commit, the session['content_corrections'] list is populated
    and ready to be included in the deep copy (session_data_copy).
    """
    sm, ws, session, session_id, handler = setup()

    # Propose and accept one, leave another pending
    await handler.propose(session_id, {"kind": "replace", "replacement": "corrected text"}, {
        "segment_id": "seg_cmd1", "transcript": "change that to corrected text",
        "speaker_heuristic": "SPEAKER", "speaker_confidence": 0.3,
        "timestamp": datetime.now().isoformat(), "language": "en-IN",
        "start_time_seconds": 8.0, "end_time_seconds": 10.0,
    })
    cid = list(session["pending_content_corrections"].keys())[0]
    await handler.accept(session_id, cid, "staff")

    # Now propose another one (pending)
    await handler.propose(session_id, {"kind": "scratch"}, {
        "segment_id": "seg_cmd2", "transcript": "scratch that",
        "speaker_heuristic": "SPEAKER", "speaker_confidence": 0.3,
        "timestamp": datetime.now().isoformat(), "language": "en-IN",
        "start_time_seconds": 10.0, "end_time_seconds": 11.0,
    })

    assert len(session["content_corrections"]) == 1  # only the accepted one
    assert len(session["pending_content_corrections"]) == 1

    # Force-commit
    await handler.force_commit_all_pending(session_id)

    assert len(session["content_corrections"]) == 2
    assert session["content_corrections"][0]["confirmed_by"] == "staff"
    assert session["content_corrections"][1]["confirmed_by"] == "ended_session_auto"

    # Simulate creating the snapshot
    snapshot = session.get("content_corrections", [])
    assert len(snapshot) == 2

    print("✅ test_content_corrections_included_in_snapshot PASSED")


async def main():
    await test_force_commit_before_snapshot()
    await test_late_transcript_rejected_after_ending()
    await test_content_corrections_included_in_snapshot()
    print("\n🎉 All end-session race tests passed!")


if __name__ == "__main__":
    asyncio.run(main())
