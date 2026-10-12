#!/usr/bin/env python3
"""
Test script for verifying Hindi speech is translated to English.

This script streams a Hindi WAV file in 0.5s chunks through VADService
and verifies the transcripts come back in English.

Usage:
    python -m pytest tests/test_hindi_to_english_streaming.py -v
    
Or run directly:
    python tests/test_hindi_to_english_streaming.py sample_hindi.wav

Requirements:
    - SARVAM_API_KEY environment variable must be set
    - sarvamai SDK must be installed
    - A Hindi WAV file (16kHz mono) for testing
"""

import asyncio
import os
import sys
import wave
import argparse
from pathlib import Path
from typing import List, Dict, Any
from dotenv import load_dotenv

# Add parent directory to path for imports
sys.path.insert(0, str(Path(__file__).parent.parent))

load_dotenv()


async def stream_wav_file(wav_path: str, chunk_duration_seconds: float = 0.5) -> List[Dict[str, Any]]:
    """
    Stream a WAV file through VADService and collect transcripts.
    
    Args:
        wav_path: Path to WAV file (should be 16kHz mono)
        chunk_duration_seconds: Duration of each chunk to send
    
    Returns:
        List of transcript events received
    """
    from services.sarvam_service import SarvamService
    from services.vad_service import VADService
    
    # Verify API key is set
    api_key = os.getenv("SARVAM_API_KEY")
    if not api_key:
        raise ValueError("SARVAM_API_KEY environment variable not set")
    
    # Read WAV file
    with wave.open(wav_path, 'rb') as wav_file:
        channels = wav_file.getnchannels()
        sample_width = wav_file.getsampwidth()
        frame_rate = wav_file.getframerate()
        n_frames = wav_file.getnframes()
        
        print(f"WAV file info:")
        print(f"  Channels: {channels}")
        print(f"  Sample width: {sample_width} bytes")
        print(f"  Frame rate: {frame_rate} Hz")
        print(f"  Total frames: {n_frames}")
        print(f"  Duration: {n_frames / frame_rate:.2f} seconds")
        
        if channels != 1:
            print(f"WARNING: Expected mono audio, got {channels} channels")
        if frame_rate != 16000:
            print(f"WARNING: Expected 16kHz, got {frame_rate}Hz")
        if sample_width != 2:
            print(f"WARNING: Expected 16-bit audio, got {sample_width * 8}-bit")
        
        pcm_data = wav_file.readframes(n_frames)
    
    # Calculate chunk size
    bytes_per_second = frame_rate * channels * sample_width
    chunk_bytes = int(bytes_per_second * chunk_duration_seconds)
    
    print(f"\nStreaming configuration:")
    print(f"  Chunk duration: {chunk_duration_seconds}s")
    print(f"  Chunk size: {chunk_bytes} bytes")
    print(f"  Total chunks: {len(pcm_data) // chunk_bytes + 1}")
    
    # Collect transcripts
    transcripts: List[Dict[str, Any]] = []
    
    async def event_callback(session_id: str, event: Any):
        """Callback to collect events from VADService."""
        event_type = event.get("type") if isinstance(event, dict) else getattr(event, "type", "unknown")
        
        if event_type == "data":
            event_data = event.get("data") if isinstance(event, dict) else getattr(event, "data", {})
            transcript = event_data.get("transcript") if isinstance(event_data, dict) else getattr(event_data, "transcript", "")
            language = event_data.get("language_code") if isinstance(event_data, dict) else getattr(event_data, "language_code", "unknown")
            
            if transcript:
                transcripts.append({
                    "transcript": transcript.strip(),
                    "language_code": language,
                    "event_type": event_type,
                })
                print(f"  📝 Transcript: '{transcript.strip()[:80]}...' (lang={language})")
        
        elif event_type == "events":
            event_data = event.get("data") if isinstance(event, dict) else getattr(event, "data", {})
            signal = event_data.get("signal_type") if isinstance(event_data, dict) else getattr(event_data, "signal_type", "")
            print(f"  🎤 VAD signal: {signal}")
    
    # Initialize services
    print("\nInitializing Sarvam services...")
    sarvam_service = SarvamService()
    vad_service = VADService(sarvam_service)
    
    session_id = "test_hindi_streaming"
    
    try:
        # Start VAD stream with translate mode
        print("\nStarting VAD stream (mode=translate)...")
        started = await vad_service.start_vad_stream(
            session_id=session_id,
            model="saaras:v3",
            mode="translate",
            event_callback=event_callback,
        )
        
        if not started:
            raise RuntimeError("Failed to start VAD stream")
        
        print("VAD stream started successfully")
        
        # Stream audio in chunks
        print(f"\nStreaming audio ({len(pcm_data)} bytes total)...")
        offset = 0
        chunk_num = 0
        
        while offset < len(pcm_data):
            chunk = pcm_data[offset:offset + chunk_bytes]
            offset += chunk_bytes
            chunk_num += 1
            
            success = await vad_service.send_audio_chunk(
                session_id=session_id,
                audio_data=chunk,
                sample_rate=frame_rate,
            )
            
            if not success:
                print(f"  ⚠️ Failed to send chunk {chunk_num}")
            
            # Small delay between chunks to simulate real-time streaming
            await asyncio.sleep(chunk_duration_seconds * 0.8)
        
        print(f"\nAll {chunk_num} chunks sent")
        
        # Flush remaining buffer
        await vad_service.flush_buffer(session_id)
        
        # Wait for final transcripts
        print("Waiting for final transcripts...")
        await asyncio.sleep(3.0)
        
    finally:
        # Stop stream
        print("\nStopping VAD stream...")
        await vad_service.stop_vad_stream(session_id)
    
    return transcripts


def analyze_transcripts(transcripts: List[Dict[str, Any]]) -> Dict[str, Any]:
    """
    Analyze the collected transcripts.
    
    Returns analysis including:
    - Total transcript count
    - Languages detected
    - Whether output appears to be English
    """
    if not transcripts:
        return {
            "total_transcripts": 0,
            "languages": [],
            "appears_english": False,
            "full_text": "",
        }
    
    languages = set()
    full_text_parts = []
    
    for t in transcripts:
        if t.get("language_code"):
            languages.add(t["language_code"])
        if t.get("transcript"):
            full_text_parts.append(t["transcript"])
    
    full_text = " ".join(full_text_parts)
    
    # Simple heuristic: check if output is primarily ASCII (English)
    ascii_chars = sum(1 for c in full_text if ord(c) < 128 and c.isalpha())
    total_alpha = sum(1 for c in full_text if c.isalpha())
    
    appears_english = (ascii_chars / total_alpha > 0.8) if total_alpha > 0 else False
    
    return {
        "total_transcripts": len(transcripts),
        "languages": list(languages),
        "appears_english": appears_english,
        "ascii_ratio": ascii_chars / total_alpha if total_alpha > 0 else 0,
        "full_text": full_text,
    }


async def main():
    """Main entry point for the test script."""
    parser = argparse.ArgumentParser(description="Test Hindi to English streaming translation")
    parser.add_argument("wav_file", nargs="?", help="Path to Hindi WAV file (16kHz mono)")
    parser.add_argument("--chunk-duration", type=float, default=0.5, help="Chunk duration in seconds")
    args = parser.parse_args()
    
    if not args.wav_file:
        print("No WAV file specified. Running in demo mode with a generated test tone.")
        print("For a real test, provide a Hindi WAV file:")
        print(f"  python {sys.argv[0]} sample_hindi.wav")
        print("\nTo create a test file, you can use ffmpeg:")
        print("  ffmpeg -i input.mp3 -ar 16000 -ac 1 -c:a pcm_s16le output.wav")
        return
    
    wav_path = Path(args.wav_file)
    if not wav_path.exists():
        print(f"Error: WAV file not found: {wav_path}")
        sys.exit(1)
    
    print("=" * 60)
    print("Hindi to English Streaming Translation Test")
    print("=" * 60)
    
    transcripts = await stream_wav_file(str(wav_path), args.chunk_duration)
    
    print("\n" + "=" * 60)
    print("Analysis")
    print("=" * 60)
    
    analysis = analyze_transcripts(transcripts)
    
    print(f"Total transcripts received: {analysis['total_transcripts']}")
    print(f"Languages detected by SDK: {analysis['languages']}")
    print(f"Output appears to be English: {analysis['appears_english']}")
    print(f"ASCII character ratio: {analysis['ascii_ratio']:.2%}")
    
    print("\n" + "-" * 60)
    print("Full transcript:")
    print("-" * 60)
    print(analysis['full_text'] or "(no transcripts received)")
    
    print("\n" + "=" * 60)
    if analysis['appears_english']:
        print("✅ TEST PASSED: Output is in English")
    else:
        print("❌ TEST FAILED: Output does not appear to be English")
    print("=" * 60)


# Pytest test functions
import pytest


@pytest.fixture
def sample_hindi_wav(tmp_path):
    """Create a minimal WAV file for testing (silence)."""
    wav_path = tmp_path / "test.wav"
    
    # Create 1 second of silence (16kHz, 16-bit, mono)
    sample_rate = 16000
    duration = 1.0
    n_samples = int(sample_rate * duration)
    silence = b'\x00\x00' * n_samples  # 16-bit silence
    
    with wave.open(str(wav_path), 'wb') as wav_file:
        wav_file.setnchannels(1)
        wav_file.setsampwidth(2)
        wav_file.setframerate(sample_rate)
        wav_file.writeframes(silence)
    
    return str(wav_path)


@pytest.mark.asyncio
async def test_vad_service_starts_with_translate_mode():
    """Test that VADService can start with mode=translate."""
    api_key = os.getenv("SARVAM_API_KEY")
    if not api_key:
        pytest.skip("SARVAM_API_KEY not set")
    
    from services.sarvam_service import SarvamService
    from services.vad_service import VADService
    
    sarvam_service = SarvamService()
    vad_service = VADService(sarvam_service)
    
    session_id = "test_translate_mode"
    
    try:
        started = await vad_service.start_vad_stream(
            session_id=session_id,
            model="saaras:v3",
            mode="translate",
            event_callback=lambda s, e: None,
        )
        
        assert started, "VAD stream should start successfully"
        assert vad_service.is_stream_active(session_id), "Stream should be active"
        
    finally:
        await vad_service.stop_vad_stream(session_id)


@pytest.mark.asyncio
async def test_pcm_to_wav_conversion():
    """Test PCM to WAV conversion helper."""
    from services.vad_service import pcm_to_wav
    
    # Create some test PCM data (1 second of silence)
    sample_rate = 16000
    pcm_data = b'\x00\x00' * sample_rate  # 16-bit silence, 1 second
    
    wav_data = pcm_to_wav(pcm_data, sample_rate=sample_rate)
    
    # WAV should be larger than PCM (due to header)
    assert len(wav_data) > len(pcm_data)
    
    # Should start with RIFF header
    assert wav_data[:4] == b'RIFF'
    
    # Should contain WAVE marker
    assert b'WAVE' in wav_data[:12]


def test_language_utils_detects_hindi():
    """Test that LanguageUtils properly detects Hindi script."""
    from utils.language_utils import LanguageUtils
    
    # Hindi text (Devanagari)
    hindi_text = "नमस्ते दुनिया"
    detected = LanguageUtils.detect_actual_language(hindi_text)
    assert detected == 'hi-IN', f"Expected hi-IN, got {detected}"


def test_language_utils_detects_telugu():
    """Test that LanguageUtils properly detects Telugu script."""
    from utils.language_utils import LanguageUtils
    
    # Telugu text
    telugu_text = "హలో ప్రపంచం"
    detected = LanguageUtils.detect_actual_language(telugu_text)
    assert detected == 'te-IN', f"Expected te-IN, got {detected}"


def test_language_utils_detects_english():
    """Test that LanguageUtils returns en-IN for English text."""
    from utils.language_utils import LanguageUtils
    
    english_text = "Hello world this is a test"
    detected = LanguageUtils.detect_actual_language(english_text)
    assert detected == 'en-IN', f"Expected en-IN, got {detected}"


def test_language_utils_prefers_non_english():
    """Test that non-English scripts are preferred in mixed text."""
    from utils.language_utils import LanguageUtils
    
    # Mixed Hindi and English
    mixed_text = "Hello नमस्ते world दुनिया"
    detected = LanguageUtils.detect_actual_language(mixed_text)
    assert detected == 'hi-IN', f"Expected hi-IN for mixed text, got {detected}"


if __name__ == "__main__":
    asyncio.run(main())
