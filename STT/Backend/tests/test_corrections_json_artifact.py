"""
Phase 1, Step 6 — Tests for corrections.json S3 artifact and metadata summary.
"""

import sys
import os
import json
import asyncio
import pytest
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..'))

from unittest.mock import AsyncMock, MagicMock, patch
from datetime import datetime
from services.realtime.background_processor import BackgroundProcessor


def make_session_data_with_corrections():
    """Create session_data_copy with content corrections."""
    return {
        "session_id": "realtime_123_abc",
        "user_sub": "test_user",
        "username": "lawyer_1",
        "audio_buffer": [],
        "transcript_buffer": "Good afternoon. Under the law.",
        "start_time": datetime(2024, 1, 15, 10, 0, 0),
        "end_time": datetime(2024, 1, 15, 10, 5, 0),
        "context": "Legal",
        "processing_mode": "transcribe",
        "preferred_language": "en-IN",
        "detected_language": "en-IN",
        "case_id": "CASE-2024-001",
        "matter_type": "consultation",
        "client_role": "plaintiff",
        "speaker_tags": {},
        "speaker_corrections": {},
        "segments": [],
        "content_corrections": [
            {
                "correction_id": "corr_00001",
                "correction_timestamp": "2024-01-15T10:02:00Z",
                "kind": "scratch",
                "target_segment_id": "seg_abc123",
                "target_start_time_seconds": 12.5,
                "original_text": "Under the law.",
                "replacement_text": None,
                "command_segment_id": "seg_cmd001",
                "command_start_time_seconds": 15.0,
                "author_username": "lawyer_1",
                "confirmed_by": "staff",
                "confirmation_timestamp": "2024-01-15T10:02:05Z",
                "stt_confidence": 0.75,
                "reverses_correction_id": None,
            },
            {
                "correction_id": "corr_00002",
                "correction_timestamp": "2024-01-15T10:03:00Z",
                "kind": "replace",
                "target_segment_id": "seg_def456",
                "target_start_time_seconds": 20.0,
                "original_text": "Some text.",
                "replacement_text": "Corrected text.",
                "command_segment_id": "seg_cmd002",
                "command_start_time_seconds": 22.0,
                "author_username": "lawyer_1",
                "confirmed_by": "auto_timeout",
                "confirmation_timestamp": "2024-01-15T10:03:10Z",
                "stt_confidence": 0.75,
                "reverses_correction_id": None,
            },
            {
                "correction_id": "corr_00003",
                "correction_timestamp": "2024-01-15T10:04:00Z",
                "kind": "rejected",
                "target_segment_id": "seg_ghi789",
                "target_start_time_seconds": 25.0,
                "original_text": "Other text.",
                "replacement_text": None,
                "command_segment_id": "seg_cmd003",
                "command_start_time_seconds": 27.0,
                "author_username": "lawyer_1",
                "confirmed_by": "rejected_by:staff",
                "confirmation_timestamp": "2024-01-15T10:04:02Z",
                "stt_confidence": None,
                "reverses_correction_id": None,
            },
        ],
    }


@pytest.mark.asyncio
async def test_background_processor_passes_corrections_to_s3():
    """BackgroundProcessor passes content_corrections to upload_session_data."""
    mock_diarization = MagicMock()
    mock_s3 = MagicMock()
    mock_s3.upload_session_data = AsyncMock(return_value={"success": True, "uploaded_files": {}, "failed_files": {}})

    processor = BackgroundProcessor(
        diarization_service=mock_diarization,
        s3_storage_service=mock_s3,
    )

    session_data = make_session_data_with_corrections()
    await processor.process(session_data)

    # Verify upload_session_data was called with content_corrections
    mock_s3.upload_session_data.assert_called_once()
    call_kwargs = mock_s3.upload_session_data.call_args[1]

    assert "content_corrections" in call_kwargs
    assert len(call_kwargs["content_corrections"]) == 3

    # Verify session_metadata has the summary
    metadata = call_kwargs["session_metadata"]
    assert "content_corrections_summary" in metadata
    summary = metadata["content_corrections_summary"]
    assert summary["total_proposed"] == 2  # scratch + replace (not rejected)
    assert summary["total_auto_committed"] == 1  # auto_timeout
    assert summary["total_rejected"] == 1
    assert summary["total_reversed"] == 0
    assert metadata["content_corrections_language_scope"] == "en-IN,en"

    print("✅ test_background_processor_passes_corrections_to_s3 PASSED")


@pytest.mark.asyncio
async def test_s3_upload_creates_corrections_json():
    """S3StorageService serializes corrections to corrections.json."""
    # We can't actually upload to S3, but we can test the serialization path
    # by mocking _upload_text_to_s3

    from services.s3_storage_service import S3StorageService

    # Patch the init to avoid needing real AWS creds
    with patch.object(S3StorageService, '__init__', lambda self: None):
        svc = S3StorageService()
        svc.bucket_name = "test-bucket"
        svc.region = "ap-south-1"

        # Track what gets uploaded
        uploaded = {}

        def mock_upload_text(text_content, s3_key, content_type="text/plain"):
            uploaded[s3_key] = text_content
            return True

        def mock_upload_file(file_content, s3_key, content_type="application/octet-stream"):
            uploaded[s3_key] = file_content
            return True

        svc._upload_text_to_s3 = mock_upload_text
        svc._upload_file_to_s3 = mock_upload_file
        svc.serialize_datetime_objects = S3StorageService.serialize_datetime_objects.__get__(svc)

        def mock_get_folder(user_sub, session_id):
            return f"{user_sub}/15-01-2024/{session_id}/"

        svc._get_folder_structure = mock_get_folder

        corrections_list = [
            {"correction_id": "corr_00001", "kind": "scratch", "target_segment_id": "seg_x",
             "original_text": "hello", "confirmed_by": "staff"},
        ]

        result = await svc.upload_session_data(
            user_sub="user1",
            session_id="realtime_test",
            transcript="hello world",
            content_corrections=corrections_list,
        )

        # corrections.json should be in the uploads
        corrections_key = "user1/15-01-2024/realtime_test/corrections.json"
        assert corrections_key in uploaded, f"corrections.json not uploaded. Keys: {list(uploaded.keys())}"

        # Parse and verify structure
        corrections_doc = json.loads(uploaded[corrections_key])
        assert corrections_doc["session_id"] == "realtime_test"
        assert corrections_doc["content_corrections_language_scope"] == "en-IN,en"
        assert len(corrections_doc["corrections"]) == 1
        assert corrections_doc["corrections"][0]["correction_id"] == "corr_00001"

        print("✅ test_s3_upload_creates_corrections_json PASSED")


@pytest.mark.asyncio
async def test_no_corrections_skips_upload():
    """When content_corrections is empty/None, no corrections.json is uploaded."""
    from services.s3_storage_service import S3StorageService

    with patch.object(S3StorageService, '__init__', lambda self: None):
        svc = S3StorageService()
        svc.bucket_name = "test-bucket"
        svc.region = "ap-south-1"

        uploaded = {}

        def mock_upload_text(text_content, s3_key, content_type="text/plain"):
            uploaded[s3_key] = text_content
            return True

        def mock_upload_file(file_content, s3_key, content_type="application/octet-stream"):
            uploaded[s3_key] = file_content
            return True

        svc._upload_text_to_s3 = mock_upload_text
        svc._upload_file_to_s3 = mock_upload_file
        svc.serialize_datetime_objects = S3StorageService.serialize_datetime_objects.__get__(svc)
        svc._get_folder_structure = lambda u, s: f"{u}/date/{s}/"

        result = await svc.upload_session_data(
            user_sub="user1",
            session_id="sess_empty",
            transcript="hello",
            content_corrections=None,
        )

        # No corrections.json should exist
        corrections_keys = [k for k in uploaded.keys() if "corrections" in k]
        assert len(corrections_keys) == 0

        print("✅ test_no_corrections_skips_upload PASSED")


if __name__ == "__main__":
    asyncio.run(test_background_processor_passes_corrections_to_s3())
    asyncio.run(test_s3_upload_creates_corrections_json())
    asyncio.run(test_no_corrections_skips_upload())
    print("\n🎉 All corrections.json artifact tests passed!")
