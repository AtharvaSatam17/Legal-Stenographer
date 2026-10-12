# Multi-Language Speech to English Translation Implementation

## Overview

This document describes the implementation of always-English translation for multi-language speech-to-text using the Sarvam AI SDK.

## SDK Version

- **sarvamai**: 0.1.28

## Architecture

### Translation Pipeline

```
Frontend (Browser)
    │
    ▼ base64 PCM (16kHz, mono, int16)
    │
WebSocket /ws/realtime
    │
    ▼
AudioStreamHandler.process_audio()
    │
    ▼ raw PCM bytes
    │
VADService.send_audio_chunk()
    │
    ▼ buffered (0.5s minimum)
    │
pcm_to_wav() conversion
    │
    ▼ WAV format, base64 encoded
    │
Sarvam SDK ws.translate()
    │ (speech_to_text_translate_streaming endpoint)
    │
    ▼
Sarvam saaras:v3 API
    │
    ▼ English transcript + detected language_code
    │
VADService listener → callback
    │
    ▼
AudioStreamHandler.handle_vad_event()
    │
    ▼
Frontend WebSocket
    │
    ▼ transcription_update message
    │
Frontend UI (English text)
```

## Key Implementation Details

### Sarvam Endpoints

The SDK provides TWO streaming endpoints:

| Endpoint | Method | Purpose |
|----------|--------|---------|
| `speech_to_text_streaming` | `ws.transcribe()` | Transcription (preserves language) |
| `speech_to_text_translate_streaming` | `ws.translate()` | Translation (outputs English) |

**We use `speech_to_text_translate_streaming`** for always-English output.

### Connection Configuration

```python
# In sarvam_service.py
self.async_client.speech_to_text_translate_streaming.connect(
    model="saaras:v3",
    mode="translate",
    vad_signals="true",
    input_audio_codec="wav",
)
```

### Audio Sending

```python
# In vad_service.py
await ws.translate(
    audio=audio_b64,  # Base64 WAV
    encoding="audio/wav",
    sample_rate=16000,
)
```

## Key Changes Made

### 1. sarvam_service.py

- `create_vad_stream()`: Now uses `speech_to_text_translate_streaming.connect()` with:
  - `model="saaras:v3"`
  - `mode="translate"` (outputs English regardless of input language)
  - `vad_signals="true"` (VAD events enabled)
  - `input_audio_codec="wav"` (expects WAV format)
- Removed legacy `use_translation` boolean branch
- `transcribe_audio()`: Updated to use `/speech-to-text` endpoint with `mode=translate`
- `create_diarization_job()`: Changed default `language_code` to `"unknown"`

### 2. vad_service.py

- Added `pcm_to_wav()` helper function to wrap raw PCM in WAV headers
- Implemented 0.5-second buffering to improve transcription quality
- Added queue-based sender task for ordered delivery
- Removed 300-second timeout that was silently killing the listener
- Added reconnect logic with 3 retries and exponential backoff
- Added `flush_buffer()` method to ensure final audio is sent
- Changed from `ws.transcribe()` to `ws.translate()` method

### 3. audio_stream_handler.py

- Added `_get()` normalizer to handle both dict and object SDK responses
- Language detection now uses SDK's `language_code` as primary source
- `classify_segment()` now uses `language="en-IN"` since transcript is English
- Added `original_language` field to transcription_update messages
- Added handling for `stream_closed` and `stream_reconnected` events

### 4. realtime_service.py

- Removed `target_language` branching logic
- Always uses `mode="translate"` (only explicit `"transcribe"` disables translation)
- Added `output_language` and `auto_detect` fields to `session_started` message
- Calls `flush_buffer()` before stopping VAD stream

### 5. language_utils.py

- Fixed `detect_actual_language()` to properly count all Indian scripts
- Added compiled regex patterns for efficiency
- Added `count_script_characters()` helper
- Added `is_code_mixed()` detection

## Assumptions and Unverified Behaviors

### Verified

1. **SDK Version**: sarvamai 0.1.28 is installed
2. **Translate Endpoint**: `speech_to_text_translate_streaming` with `ws.translate()` outputs English
3. **WAV Requirement**: SDK's `ws.translate()` expects WAV format, not raw PCM
4. **Method Signature**: `ws.translate(audio, encoding, sample_rate)` confirmed via inspection

### Assumptions (to verify against SDK source/docs)

1. **Event Format**: Assumed SDK events have:
   - `type` field ("data", "events")
   - `data.transcript` for transcription text
   - `data.language_code` for detected input language
   - `data.metrics.audio_duration` for timing

2. **Diarization Compatibility**: Assumed saarika:v2.5 works with `language_code="unknown"`. If not, diarization may need to run with a specific language code.

### Known Limitations

1. **Hindi/Marathi Disambiguation**: Both use Devanagari script, so script-based detection returns `hi-IN` for both. Lexical analysis would be needed to distinguish them.

2. **Diarization Model**: saarika:v2.5 may not support translation. Diarization is used only for speaker labels; the translated text comes from the live stream.

3. **Code-Mixed Speech**: Speech that rapidly switches between languages may produce inconsistent translations.

## Testing

### Unit Tests

```bash
cd Backend
python -m pytest tests/test_hindi_to_english_streaming.py -v
```

### Manual Testing

```bash
# Stream a Hindi WAV file
python tests/test_hindi_to_english_streaming.py path/to/hindi.wav

# Convert audio to required format if needed
ffmpeg -i input.mp3 -ar 16000 -ac 1 -c:a pcm_s16le output.wav
```

## Frontend Contract

### No Breaking Changes

- All existing WebSocket message types preserved
- All existing field names unchanged
- New optional fields added:
  - `session_started`: `output_language`, `auto_detect`
  - `transcription_update`: `original_language`
  - New message type: `stream_status`

### Frontend Notes

1. The `transcript` field is now always English
2. The `language` field represents the SPOKEN language (e.g., "hi-IN" for Hindi input)
3. Any "translate/transcribe" UI toggle can be hidden (backend always translates)
4. Handle new `stream_status` messages gracefully (reconnecting, connected, disconnected)

## Rollback

If issues arise, the key changes to revert are:

1. In `sarvam_service.py`: 
   - Change back to `speech_to_text_streaming.connect()` 
   - Remove `mode` parameter or set to `"transcribe"`
2. In `vad_service.py`: 
   - Change `ws.translate()` back to `ws.transcribe()`
3. In `realtime_service.py`: 
   - Restore `processing_mode` branching logic

Note: The PCM-to-WAV fix should be kept regardless (it's a correctness improvement).

## Quick Reference

| Component | Old | New |
|-----------|-----|-----|
| Streaming endpoint | `speech_to_text_streaming` | `speech_to_text_translate_streaming` |
| Send method | `ws.transcribe()` | `ws.translate()` |
| Mode parameter | `mode="transcribe"` or branching | `mode="translate"` always |
| Language code | `language_code="unknown"` | Not needed (auto-detect) |
| Audio format | Raw PCM | WAV-wrapped PCM |
