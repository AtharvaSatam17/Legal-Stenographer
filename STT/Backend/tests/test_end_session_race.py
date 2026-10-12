"""
Test that late-arriving transcripts are rejected after a session is marked
as ending (end-of-session race protection).
"""

import sys
import os
import asyncio
import pytest
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..'))

from unittest.mock import AsyncMock, MagicMock
from datetime import datetime
from core.session_manager import SessionManager
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

    return sm, ws, session, session_id


@pytest.mark.asyncio
async def test_late_transcript_rejected_after_ending():
    """
    After session['ending'] = True, _handle_transcript should return early
    without appending or broadcasting.
    """
    sm, ws, session, session_id = setup()
    audio_handler = AudioStreamHandler(
        session_manager=sm,
        vad_service=MagicMock(),
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


async def main():
    await test_late_transcript_rejected_after_ending()
    print("\n🎉 All end-session race tests passed!")


if __name__ == "__main__":
    asyncio.run(main())
