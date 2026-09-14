"""
Phase 1 Step 2 — Integration test verifying that command segments are NOT
broadcast as transcription_update and NOT appended to session["segments"].
"""

import sys
import os
import asyncio
import pytest
import json
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..'))

from unittest.mock import MagicMock, AsyncMock, patch
from datetime import datetime
from core.session_manager import SessionManager
from services.realtime.audio_stream_handler import AudioStreamHandler


def make_mock_event_data(transcript: str, audio_duration: float = 5.0):
    """Create a mock event_data object that mimics SpeechToTextTranscriptionData."""
    metrics = MagicMock()
    metrics.audio_duration = audio_duration

    event_data = MagicMock()
    event_data.transcript = transcript
    event_data.language_code = "en-IN"
    event_data.metrics = metrics
    return event_data


async def run_test():
    # Setup
    sm = SessionManager()
    vad_service = MagicMock()
    handler = AudioStreamHandler(session_manager=sm, vad_service=vad_service)

    ws = AsyncMock()
    session = sm.create_session(ws, {"username": "test_lawyer", "client_role": "plaintiff"})
    session_id = session["id"]

    # --- Test 1: Normal content is appended and broadcast ---
    event_data_content = make_mock_event_data("Good afternoon, I have reviewed the documents.", audio_duration=3.0)
    await handler._handle_transcript(session_id, "Good afternoon, I have reviewed the documents.", event_data_content)

    assert len(session["segments"]) == 1, f"Expected 1 segment, got {len(session['segments'])}"
    assert session["segments"][0]["transcript"] == "Good afternoon, I have reviewed the documents."

    # Check that transcription_update was sent
    calls = ws.send_text.call_args_list
    last_msg = json.loads(calls[-1][0][0])
    assert last_msg["type"] == "transcription_update", f"Expected transcription_update, got {last_msg['type']}"

    ws.send_text.reset_mock()

    # --- Test 2: "scratch that" command is NOT appended and NOT broadcast as transcription_update ---
    event_data_cmd = make_mock_event_data("scratch that", audio_duration=5.0)
    await handler._handle_transcript(session_id, "scratch that", event_data_cmd)

    assert len(session["segments"]) == 1, f"Expected still 1 segment (command not appended), got {len(session['segments'])}"

    # Should have sent a correction_failed (handler not wired yet placeholder)
    calls = ws.send_text.call_args_list
    last_msg = json.loads(calls[-1][0][0])
    assert last_msg["type"] == "correction_failed", f"Expected correction_failed, got {last_msg['type']}"
    assert last_msg["command"]["kind"] == "scratch"
    assert last_msg["reason"] == "handler_not_wired"

    ws.send_text.reset_mock()

    # --- Test 3: "change that to X" command behaves the same way ---
    event_data_cmd2 = make_mock_event_data("change that to the defendant was present at 4 PM", audio_duration=8.0)
    await handler._handle_transcript(session_id, "change that to the defendant was present at 4 PM", event_data_cmd2)

    assert len(session["segments"]) == 1, f"Expected still 1 segment, got {len(session['segments'])}"

    calls = ws.send_text.call_args_list
    last_msg = json.loads(calls[-1][0][0])
    assert last_msg["type"] == "correction_failed"
    assert last_msg["command"]["kind"] == "replace"
    assert last_msg["command"]["replacement"] == "the defendant was present at 4 PM"

    ws.send_text.reset_mock()

    # --- Test 4: Normal content after a command is still appended correctly ---
    event_data_content2 = make_mock_event_data("The next step would be to file a complaint.", audio_duration=12.0)
    await handler._handle_transcript(session_id, "The next step would be to file a complaint.", event_data_content2)

    assert len(session["segments"]) == 2, f"Expected 2 segments now, got {len(session['segments'])}"
    assert session["segments"][1]["transcript"] == "The next step would be to file a complaint."
    # start_time_seconds should chain from the first segment's end
    assert session["segments"][1]["start_time_seconds"] == 3.0  # first segment ended at 3.0

    calls = ws.send_text.call_args_list
    last_msg = json.loads(calls[-1][0][0])
    assert last_msg["type"] == "transcription_update"

    print("✅ All command detection integration tests passed!")


if __name__ == "__main__":
    asyncio.run(run_test())


@pytest.mark.asyncio
async def test_command_detection_integration():
    await run_test()
