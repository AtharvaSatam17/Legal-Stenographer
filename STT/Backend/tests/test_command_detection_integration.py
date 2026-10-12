"""
Integration test verifying that the "new paragraph" command segment is NOT
broadcast as transcription_update and NOT appended as content to
session["segments"] — instead it records a paragraph-break marker and emits a
paragraph_break message.
"""

import sys
import os
import asyncio
import pytest
import json
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..'))

from unittest.mock import MagicMock, AsyncMock
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

    calls = ws.send_text.call_args_list
    last_msg = json.loads(calls[-1][0][0])
    assert last_msg["type"] == "transcription_update", f"Expected transcription_update, got {last_msg['type']}"

    ws.send_text.reset_mock()

    # --- Test 2: "new paragraph" command does NOT append content and does NOT broadcast transcription_update ---
    event_data_cmd = make_mock_event_data("new paragraph", audio_duration=5.0)
    await handler._handle_transcript(session_id, "new paragraph", event_data_cmd)

    # A break marker is appended, but it is NOT a content segment.
    assert len(session["segments"]) == 2, f"Expected 2 segments (one marker added), got {len(session['segments'])}"
    marker = session["segments"][1]
    assert marker.get("is_paragraph_break") is True, "Second segment should be a paragraph-break marker"
    assert marker.get("transcript") == "", "Break marker must carry no transcript text"

    # The last message should be paragraph_break, NOT transcription_update.
    calls = ws.send_text.call_args_list
    last_msg = json.loads(calls[-1][0][0])
    assert last_msg["type"] == "paragraph_break", f"Expected paragraph_break, got {last_msg['type']}"
    assert last_msg["session_id"] == session_id

    # No transcription_update should have been emitted for the command.
    assert not any(json.loads(c[0][0]).get("type") == "transcription_update" for c in calls), \
        "Command must not broadcast a transcription_update"

    ws.send_text.reset_mock()

    # --- Test 3: Normal content after a break is still appended and broadcast ---
    event_data_content2 = make_mock_event_data("The next step would be to file a complaint.", audio_duration=12.0)
    await handler._handle_transcript(session_id, "The next step would be to file a complaint.", event_data_content2)

    assert len(session["segments"]) == 3, f"Expected 3 segments now, got {len(session['segments'])}"
    assert session["segments"][2]["transcript"] == "The next step would be to file a complaint."

    calls = ws.send_text.call_args_list
    last_msg = json.loads(calls[-1][0][0])
    assert last_msg["type"] == "transcription_update"

    print("✅ All paragraph-break integration tests passed!")


if __name__ == "__main__":
    asyncio.run(run_test())


@pytest.mark.asyncio
async def test_command_detection_integration():
    await run_test()
