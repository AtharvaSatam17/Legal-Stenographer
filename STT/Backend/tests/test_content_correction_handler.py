"""
Phase 1, Step 3 — Integration tests for ContentCorrectionHandler.
Tests propose, accept, reject, auto-commit, reverse, and target resolution.
"""

import sys
import os
import asyncio
import json
import pytest
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..'))

from unittest.mock import AsyncMock, MagicMock
from core.session_manager import SessionManager
from services.realtime.content_correction_handler import ContentCorrectionHandler


def setup_session_with_segments():
    """Create a session with pre-populated LAWYER and CLIENT segments."""
    sm = SessionManager()
    ws = AsyncMock()
    session = sm.create_session(ws, {"username": "test_lawyer", "client_role": "plaintiff"})
    session_id = session["id"]

    # Simulate 4 segments: LAWYER, CLIENT, LAWYER, CLIENT
    session["segments"] = [
        {
            "segment_id": "seg_aaa111",
            "transcript": "Good afternoon, I have reviewed the documents.",
            "speaker_heuristic": "LAWYER",
            "speaker_confidence": 0.75,
            "timestamp": "2024-01-15T10:00:01Z",
            "language": "en-IN",
            "start_time_seconds": 0.0,
            "end_time_seconds": 5.0,
        },
        {
            "segment_id": "seg_bbb222",
            "transcript": "What happened was they fired me.",
            "speaker_heuristic": "CLIENT",
            "speaker_confidence": 0.65,
            "timestamp": "2024-01-15T10:00:06Z",
            "language": "en-IN",
            "start_time_seconds": 5.0,
            "end_time_seconds": 10.0,
        },
        {
            "segment_id": "seg_ccc333",
            "transcript": "Under the law wrongful termination requires evidence.",
            "speaker_heuristic": "LAWYER",
            "speaker_confidence": 0.75,
            "timestamp": "2024-01-15T10:00:11Z",
            "language": "en-IN",
            "start_time_seconds": 10.0,
            "end_time_seconds": 18.0,
        },
        {
            "segment_id": "seg_ddd444",
            "transcript": "How long will this take?",
            "speaker_heuristic": "CLIENT",
            "speaker_confidence": 0.65,
            "timestamp": "2024-01-15T10:00:19Z",
            "language": "en-IN",
            "start_time_seconds": 18.0,
            "end_time_seconds": 22.0,
        },
    ]

    return sm, ws, session, session_id


@pytest.mark.asyncio
async def test_propose_targets_most_recent_lawyer():
    """propose() should target the most recent LAWYER segment (seg_ccc333)."""
    sm, ws, session, session_id = setup_session_with_segments()
    handler = ContentCorrectionHandler(session_manager=sm)

    command = {"kind": "scratch"}
    command_seg = {
        "segment_id": "seg_cmd001",
        "transcript": "scratch that",
        "speaker_heuristic": "SPEAKER",
        "speaker_confidence": 0.3,
        "timestamp": "2024-01-15T10:00:23Z",
        "language": "en-IN",
        "start_time_seconds": 22.0,
        "end_time_seconds": 23.0,
    }

    await handler.propose(session_id, command, command_seg)

    # Should have one pending correction
    assert len(session["pending_content_corrections"]) == 1
    corr = list(session["pending_content_corrections"].values())[0]
    assert corr["target_segment_id"] == "seg_ccc333", f"Expected seg_ccc333, got {corr['target_segment_id']}"
    assert corr["kind"] == "scratch"
    assert corr["original_text"] == "Under the law wrongful termination requires evidence."

    # Should have sent correction_proposed to the frontend
    calls = ws.send_text.call_args_list
    msg = json.loads(calls[-1][0][0])
    assert msg["type"] == "correction_proposed"
    assert msg["target_segment_id"] == "seg_ccc333"

    print("✅ test_propose_targets_most_recent_lawyer PASSED")


@pytest.mark.asyncio
async def test_propose_no_lawyer_emits_no_target():
    """If no LAWYER segments exist, emit correction_failed reason=no_target."""
    sm = SessionManager()
    ws = AsyncMock()
    session = sm.create_session(ws, {"username": "test", "client_role": "plaintiff"})
    session_id = session["id"]

    # Only CLIENT segments
    session["segments"] = [
        {"segment_id": "seg_x", "transcript": "test", "speaker_heuristic": "CLIENT",
         "speaker_confidence": 0.65, "timestamp": "t", "language": "en-IN",
         "start_time_seconds": 0.0, "end_time_seconds": 3.0}
    ]

    handler = ContentCorrectionHandler(session_manager=sm)
    await handler.propose(session_id, {"kind": "scratch"}, {
        "segment_id": "seg_cmd", "transcript": "scratch that",
        "speaker_heuristic": "SPEAKER", "speaker_confidence": 0.3,
        "timestamp": "t", "language": "en-IN",
        "start_time_seconds": 3.0, "end_time_seconds": 4.0,
    })

    msg = json.loads(ws.send_text.call_args_list[-1][0][0])
    assert msg["type"] == "correction_failed"
    assert msg["reason"] == "no_target"

    print("✅ test_propose_no_lawyer_emits_no_target PASSED")


@pytest.mark.asyncio
async def test_accept_moves_to_log():
    """accept() moves pending → content_corrections and cancels timer."""
    sm, ws, session, session_id = setup_session_with_segments()
    handler = ContentCorrectionHandler(session_manager=sm)

    await handler.propose(session_id, {"kind": "replace", "replacement": "the evidence is strong"}, {
        "segment_id": "seg_cmd2", "transcript": "change that to the evidence is strong",
        "speaker_heuristic": "SPEAKER", "speaker_confidence": 0.3,
        "timestamp": "t", "language": "en-IN",
        "start_time_seconds": 22.0, "end_time_seconds": 25.0,
    })

    correction_id = list(session["pending_content_corrections"].keys())[0]
    ws.send_text.reset_mock()

    await handler.accept(session_id, correction_id, "staff_user")

    # Pending should be empty
    assert len(session["pending_content_corrections"]) == 0
    # Should be in the log
    assert len(session["content_corrections"]) == 1
    entry = session["content_corrections"][0]
    assert entry["correction_id"] == correction_id
    assert entry["kind"] == "replace"
    assert entry["confirmed_by"] == "staff_user"
    assert entry["replacement_text"] == "the evidence is strong"

    # Frontend should have received correction_applied
    msg = json.loads(ws.send_text.call_args_list[-1][0][0])
    assert msg["type"] == "correction_applied"
    assert msg["confirmed_by"] == "staff_user"

    print("✅ test_accept_moves_to_log PASSED")


@pytest.mark.asyncio
async def test_reject_records_in_log():
    """reject() removes from pending and records in log with rejected marker."""
    sm, ws, session, session_id = setup_session_with_segments()
    handler = ContentCorrectionHandler(session_manager=sm)

    await handler.propose(session_id, {"kind": "scratch"}, {
        "segment_id": "seg_cmd3", "transcript": "scratch that",
        "speaker_heuristic": "SPEAKER", "speaker_confidence": 0.3,
        "timestamp": "t", "language": "en-IN",
        "start_time_seconds": 22.0, "end_time_seconds": 23.0,
    })

    correction_id = list(session["pending_content_corrections"].keys())[0]
    ws.send_text.reset_mock()

    await handler.reject(session_id, correction_id, "staff_reviewer")

    assert len(session["pending_content_corrections"]) == 0
    assert len(session["content_corrections"]) == 1
    entry = session["content_corrections"][0]
    assert entry["kind"] == "rejected"
    assert entry["confirmed_by"] == "rejected_by:staff_reviewer"

    msg = json.loads(ws.send_text.call_args_list[-1][0][0])
    assert msg["type"] == "correction_rejected"

    print("✅ test_reject_records_in_log PASSED")


@pytest.mark.asyncio
async def test_auto_commit_fires_after_timeout():
    """Auto-commit fires after the timeout period."""
    sm, ws, session, session_id = setup_session_with_segments()
    handler = ContentCorrectionHandler(session_manager=sm)

    # Monkey-patch timeout for fast testing
    import services.realtime.content_correction_handler as cch_module
    original_timeout = cch_module._AUTO_COMMIT_TIMEOUT_SECONDS
    cch_module._AUTO_COMMIT_TIMEOUT_SECONDS = 0.1  # 100ms for testing

    try:
        await handler.propose(session_id, {"kind": "scratch"}, {
            "segment_id": "seg_cmd4", "transcript": "scratch that",
            "speaker_heuristic": "SPEAKER", "speaker_confidence": 0.3,
            "timestamp": "t", "language": "en-IN",
            "start_time_seconds": 22.0, "end_time_seconds": 23.0,
        })

        assert len(session["pending_content_corrections"]) == 1

        # Wait for auto-commit
        await asyncio.sleep(0.3)

        assert len(session["pending_content_corrections"]) == 0
        assert len(session["content_corrections"]) == 1
        entry = session["content_corrections"][0]
        assert entry["confirmed_by"] == "auto_timeout"

        print("✅ test_auto_commit_fires_after_timeout PASSED")
    finally:
        cch_module._AUTO_COMMIT_TIMEOUT_SECONDS = original_timeout


@pytest.mark.asyncio
async def test_reverse_appends_to_log():
    """reverse() appends a new entry pointing at the original correction."""
    sm, ws, session, session_id = setup_session_with_segments()
    handler = ContentCorrectionHandler(session_manager=sm)

    # First, create and accept a correction
    await handler.propose(session_id, {"kind": "scratch"}, {
        "segment_id": "seg_cmd5", "transcript": "scratch that",
        "speaker_heuristic": "SPEAKER", "speaker_confidence": 0.3,
        "timestamp": "t", "language": "en-IN",
        "start_time_seconds": 22.0, "end_time_seconds": 23.0,
    })
    correction_id = list(session["pending_content_corrections"].keys())[0]
    await handler.accept(session_id, correction_id, "staff")

    assert len(session["content_corrections"]) == 1
    ws.send_text.reset_mock()

    # Now reverse it
    await handler.reverse(session_id, correction_id, "staff")

    assert len(session["content_corrections"]) == 2
    reversal = session["content_corrections"][1]
    assert reversal["kind"] == "reverse"
    assert reversal["reverses_correction_id"] == correction_id

    msg = json.loads(ws.send_text.call_args_list[-1][0][0])
    assert msg["type"] == "correction_reversed"
    assert msg["reverses_correction_id"] == correction_id

    print("✅ test_reverse_appends_to_log PASSED")


@pytest.mark.asyncio
async def test_replace_proposal():
    """Replace command stores the replacement text correctly."""
    sm, ws, session, session_id = setup_session_with_segments()
    handler = ContentCorrectionHandler(session_manager=sm)

    await handler.propose(session_id, {"kind": "replace", "replacement": "the defendant was present"}, {
        "segment_id": "seg_cmd6", "transcript": "change that to the defendant was present",
        "speaker_heuristic": "SPEAKER", "speaker_confidence": 0.3,
        "timestamp": "t", "language": "en-IN",
        "start_time_seconds": 22.0, "end_time_seconds": 25.0,
    })

    corr = list(session["pending_content_corrections"].values())[0]
    assert corr["replacement_text"] == "the defendant was present"
    assert corr["original_text"] == "Under the law wrongful termination requires evidence."

    print("✅ test_replace_proposal PASSED")


async def main():
    await test_propose_targets_most_recent_lawyer()
    await test_propose_no_lawyer_emits_no_target()
    await test_accept_moves_to_log()
    await test_reject_records_in_log()
    await test_auto_commit_fires_after_timeout()
    await test_reverse_appends_to_log()
    await test_replace_proposal()
    print("\n🎉 All ContentCorrectionHandler tests passed!")


if __name__ == "__main__":
    asyncio.run(main())
