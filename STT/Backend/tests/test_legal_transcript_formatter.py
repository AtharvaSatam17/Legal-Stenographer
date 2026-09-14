"""
Phase 0 Step 0.3.3 / 0.3.4 — Unit tests for time-anchored speaker corrections
in LegalTranscriptFormatter.
"""

import sys
import os
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..'))

from services.legal_transcript_formatter import LegalTranscriptFormatter


def make_diarization_segments():
    """Hand-crafted diarization result simulating Sarvam output (no segment_id field)."""
    return [
        {"speaker_id": "SPEAKER_1", "start_time_seconds": 0.0, "end_time_seconds": 5.0,
         "transcript": "Good afternoon, I have reviewed the documents."},
        {"speaker_id": "SPEAKER_2", "start_time_seconds": 5.5, "end_time_seconds": 12.0,
         "transcript": "What happened was they fired me without notice."},
        {"speaker_id": "SPEAKER_1", "start_time_seconds": 12.5, "end_time_seconds": 20.0,
         "transcript": "Under the law, wrongful termination claims require evidence."},
        {"speaker_id": "SPEAKER_2", "start_time_seconds": 20.5, "end_time_seconds": 25.0,
         "transcript": "How long will this take?"},
    ]


def test_new_format_correction_anchors_by_time():
    """New-format corrections (dict with role + start_time_seconds) match correctly."""
    formatter = LegalTranscriptFormatter(client_role="PLAINTIFF")
    segments = make_diarization_segments()

    # Correct segment #2 (start 5.5-12.0) — anchor at 6.0 should land inside it
    corrections = {
        "seg_abc123def456": {
            "role": "LAWYER",
            "start_time_seconds": 6.0,
        }
    }

    result_txt = formatter.format_legal_transcript(segments, speaker_corrections=corrections)
    lines = [l for l in result_txt.split('\n') if l.startswith('[')]

    # Line 0: LAWYER (segment 0, default)
    assert "LAWYER:" in lines[0], f"Expected LAWYER in line 0: {lines[0]}"
    # Line 1: was SPEAKER_2 → should now be LAWYER due to correction
    assert "LAWYER:" in lines[1], f"Expected corrected LAWYER in line 1: {lines[1]}"
    # Line 2: LAWYER (segment 2, default mapping)
    assert "LAWYER:" in lines[2], f"Expected LAWYER in line 2: {lines[2]}"
    # Line 3: PLAINTIFF (segment 3, default mapping)
    assert "PLAINTIFF:" in lines[3], f"Expected PLAINTIFF in line 3: {lines[3]}"

    print("✅ test_new_format_correction_anchors_by_time PASSED")


def test_new_format_correction_json():
    """JSON formatter also uses time-anchored corrections."""
    formatter = LegalTranscriptFormatter(client_role="DEFENDANT")
    segments = make_diarization_segments()

    # Correct segment #3 (start 12.5-20.0) — anchor at 15.0
    corrections = {
        "seg_xyz789": {
            "role": "DEFENDANT",
            "start_time_seconds": 15.0,
        }
    }

    result = formatter.format_legal_transcript_json(
        segments, metadata={"test": True}, speaker_corrections=corrections
    )

    assert result["speaker_corrections_applied"] == 1
    # Segment index 2 (third, 0-based) should be corrected
    seg2 = result["segments"][2]
    assert seg2["speaker_role"] == "DEFENDANT"
    assert seg2["was_corrected"] is True

    # Others should not be corrected
    assert result["segments"][0]["was_corrected"] is False
    assert result["segments"][1]["was_corrected"] is False
    assert result["segments"][3]["was_corrected"] is False

    print("✅ test_new_format_correction_json PASSED")


def test_legacy_format_no_crash():
    """Legacy corrections (plain string, no anchor) don't crash — they just don't match."""
    formatter = LegalTranscriptFormatter(client_role="PLAINTIFF")
    segments = make_diarization_segments()

    # Legacy format — this will NOT match any diarization segment (no anchor)
    corrections = {
        "seg_legacy123": "LAWYER",
    }

    result_txt = formatter.format_legal_transcript(segments, speaker_corrections=corrections)
    lines = [l for l in result_txt.split('\n') if l.startswith('[')]

    # All should use default mapping (no correction applied)
    assert "LAWYER:" in lines[0]
    assert "PLAINTIFF:" in lines[1]
    assert "LAWYER:" in lines[2]
    assert "PLAINTIFF:" in lines[3]

    print("✅ test_legacy_format_no_crash PASSED")


def test_correction_out_of_tolerance_not_applied():
    """Correction with anchor far from any segment is not applied."""
    formatter = LegalTranscriptFormatter(client_role="PLAINTIFF")
    segments = make_diarization_segments()

    # Anchor at 99.0 — far beyond any segment (last ends at 25.0)
    corrections = {
        "seg_far": {
            "role": "LAWYER",
            "start_time_seconds": 99.0,
        }
    }

    result_txt = formatter.format_legal_transcript(segments, speaker_corrections=corrections)
    lines = [l for l in result_txt.split('\n') if l.startswith('[')]

    # No correction should be applied — all default
    assert "PLAINTIFF:" in lines[1]
    assert "PLAINTIFF:" in lines[3]

    print("✅ test_correction_out_of_tolerance_not_applied PASSED")


if __name__ == "__main__":
    test_new_format_correction_anchors_by_time()
    test_new_format_correction_json()
    test_legacy_format_no_crash()
    test_correction_out_of_tolerance_not_applied()
    print("\n🎉 All Phase 0 formatter tests passed!")
