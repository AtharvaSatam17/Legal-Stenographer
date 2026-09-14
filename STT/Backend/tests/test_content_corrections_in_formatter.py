"""
Phase 1, Step 7 — Test that content corrections are applied to legal_transcript.txt
with the † marker, and that scratched lines are omitted.
"""

import sys
import os
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..'))

from services.legal_transcript_formatter import LegalTranscriptFormatter


def make_diarization_segments():
    return [
        {"speaker_id": "SPEAKER_1", "start_time_seconds": 0.0, "end_time_seconds": 5.0,
         "transcript": "Good afternoon, I have reviewed the documents."},
        {"speaker_id": "SPEAKER_2", "start_time_seconds": 5.5, "end_time_seconds": 12.0,
         "transcript": "What happened was they fired me without notice."},
        {"speaker_id": "SPEAKER_1", "start_time_seconds": 12.5, "end_time_seconds": 20.0,
         "transcript": "Under the law wrongful termination requires evidence."},
        {"speaker_id": "SPEAKER_2", "start_time_seconds": 20.5, "end_time_seconds": 25.0,
         "transcript": "How long will this take?"},
    ]


def test_scratch_removes_line_from_txt():
    """A scratch correction removes the line from legal_transcript.txt."""
    formatter = LegalTranscriptFormatter(client_role="PLAINTIFF")
    segments = make_diarization_segments()

    content_corrections = [
        {"correction_id": "corr_00001", "kind": "scratch",
         "target_segment_id": "seg_x", "target_start_time_seconds": 13.0,
         "original_text": "Under the law wrongful termination requires evidence.",
         "replacement_text": None, "confirmed_by": "staff",
         "reverses_correction_id": None},
    ]

    result = formatter.format_legal_transcript(
        segments, content_corrections=content_corrections
    )

    lines = [l for l in result.split('\n') if l.startswith('[')]
    # Original has 4 lines; scratch removes segment at 12.5-20.0, so 3 remain
    assert len(lines) == 3, f"Expected 3 lines, got {len(lines)}: {lines}"
    # The remaining lines should NOT contain the scratched text
    assert "wrongful termination" not in result

    print("✅ test_scratch_removes_line_from_txt PASSED")


def test_replace_changes_text_with_marker():
    """A replace correction changes text and adds † marker."""
    formatter = LegalTranscriptFormatter(client_role="PLAINTIFF")
    segments = make_diarization_segments()

    content_corrections = [
        {"correction_id": "corr_00001", "kind": "replace",
         "target_segment_id": "seg_x", "target_start_time_seconds": 1.0,
         "original_text": "Good afternoon, I have reviewed the documents.",
         "replacement_text": "Good morning, the documents are ready.",
         "confirmed_by": "auto_timeout", "reverses_correction_id": None},
    ]

    result = formatter.format_legal_transcript(
        segments, content_corrections=content_corrections
    )

    lines = [l for l in result.split('\n') if l.startswith('[')]
    assert len(lines) == 4  # all 4 lines still present (replace, not scratch)

    # First line should have the replacement text + † marker
    assert "Good morning, the documents are ready." in lines[0]
    assert "†" in lines[0]
    # Original text should NOT be present
    assert "reviewed the documents" not in result
    # Other lines should NOT have the marker
    assert "†" not in lines[1]
    assert "†" not in lines[2]

    print("✅ test_replace_changes_text_with_marker PASSED")


def test_reversed_correction_not_applied():
    """A correction that was reversed should NOT affect the output."""
    formatter = LegalTranscriptFormatter(client_role="PLAINTIFF")
    segments = make_diarization_segments()

    content_corrections = [
        {"correction_id": "corr_00001", "kind": "scratch",
         "target_segment_id": "seg_x", "target_start_time_seconds": 13.0,
         "original_text": "Under the law wrongful termination requires evidence.",
         "replacement_text": None, "confirmed_by": "staff",
         "reverses_correction_id": None},
        # This reverses the scratch above
        {"correction_id": "corr_00002", "kind": "reverse",
         "target_segment_id": "seg_x", "target_start_time_seconds": 13.0,
         "original_text": "Under the law wrongful termination requires evidence.",
         "replacement_text": None, "confirmed_by": "staff",
         "reverses_correction_id": "corr_00001"},
    ]

    result = formatter.format_legal_transcript(
        segments, content_corrections=content_corrections
    )

    lines = [l for l in result.split('\n') if l.startswith('[')]
    # All 4 lines should be present (reversal undoes the scratch)
    assert len(lines) == 4
    assert "wrongful termination" in result
    # No † marker since the correction was reversed
    assert "†" not in lines[2]

    print("✅ test_reversed_correction_not_applied PASSED")


def test_json_format_with_content_corrections():
    """JSON formatter applies content corrections and marks hidden segments."""
    formatter = LegalTranscriptFormatter(client_role="PLAINTIFF")
    segments = make_diarization_segments()

    content_corrections = [
        {"correction_id": "corr_00001", "kind": "scratch",
         "target_segment_id": "seg_x", "target_start_time_seconds": 21.0,
         "original_text": "How long will this take?",
         "replacement_text": None, "confirmed_by": "staff",
         "reverses_correction_id": None},
    ]

    result = formatter.format_legal_transcript_json(
        segments, content_corrections=content_corrections
    )

    assert result["visible_segments"] == 3
    assert len(result["segments"]) == 3  # visible only
    assert len(result["hidden_segments"]) == 1
    assert result["hidden_segments"][0]["hidden"] is True
    assert result["content_corrections_applied"] == 1

    print("✅ test_json_format_with_content_corrections PASSED")


if __name__ == "__main__":
    test_scratch_removes_line_from_txt()
    test_replace_changes_text_with_marker()
    test_reversed_correction_not_applied()
    test_json_format_with_content_corrections()
    print("\n🎉 All Step 7 content corrections formatter tests passed!")
