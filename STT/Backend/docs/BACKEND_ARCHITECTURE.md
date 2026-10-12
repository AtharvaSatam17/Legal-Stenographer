# Backend Architecture Documentation

## Overview

This is a FastAPI-based real-time legal transcription system that processes multi-language speech input and outputs English transcripts. It uses Sarvam AI for speech-to-text with automatic translation and supports voice-driven corrections.

## System Architecture

```
┌─────────────────────────────────────────────────────────────────────────────┐
│                              FRONTEND (Next.js)                             │
│                     WebSocket: ws://backend:8000/ws/realtime                │
└───────────────────────────────────┬─────────────────────────────────────────┘
                                    │
                    ┌───────────────▼───────────────┐
                    │         main.py               │
                    │    (FastAPI Application)      │
                    │   WebSocket Endpoint Handler  │
                    └───────────────┬───────────────┘
                                    │
                    ┌───────────────▼───────────────┐
                    │   RealTimeTranscriptionService│
                    │    (realtime_service.py)      │
                    │   Session & Message Router    │
                    └───────────────┬───────────────┘
                                    │
        ┌───────────────────────────┼───────────────────────────┐
        │                           │                           │
┌───────▼───────┐         ┌────────▼────────┐         ┌────────▼────────┐
│SessionManager │         │AudioStreamHandler│         │ContentCorrection│
│    (core)     │         │   (realtime)     │         │    Handler      │
│Session State  │         │Audio→Transcript  │         │Voice Commands   │
└───────────────┘         └────────┬─────────┘         └─────────────────┘
                                   │
                          ┌────────▼────────┐
                          │   VADService    │
                          │ (vad_service)   │
                          │ Audio Streaming │
                          └────────┬────────┘
                                   │
                          ┌────────▼────────┐
                          │  SarvamService  │
                          │(sarvam_service) │
                          │  Sarvam AI SDK  │
                          └────────┬────────┘
                                   │
                          ┌────────▼────────┐
                          │   Sarvam AI     │
                          │  Cloud API      │
                          │ (saaras:v3)     │
                          └─────────────────┘
```

## File Structure

```
Backend/
├── main.py                          # FastAPI entry point
├── core/
│   └── session_manager.py           # Session state management
├── services/
│   ├── sarvam_service.py            # Sarvam AI SDK wrapper
│   ├── vad_service.py               # Voice Activity Detection & streaming
│   ├── diarization_service.py       # Speaker diarization (post-session)
│   ├── s3_storage_service.py        # AWS S3 storage
│   ├── legal_transcript_formatter.py# Legal document formatting
│   └── realtime/
│       ├── realtime_service.py      # Main service orchestrator
│       ├── audio_stream_handler.py  # Audio processing & VAD events
│       ├── command_parser.py        # Voice command detection
│       ├── content_correction_handler.py # Correction lifecycle
│       ├── transcript_materializer.py    # Correction overlay engine
│       └── background_processor.py  # Post-session processing
└── utils/
    ├── language_utils.py            # Language/script detection
    ├── speaker_utils.py             # Speaker identification heuristics
    └── audio_utils.py               # Audio format utilities
```

---

## Core Files

### 1. `main.py` - Application Entry Point

**Purpose**: FastAPI application setup and WebSocket endpoint.

**Key Functions**:
- Initializes `RealTimeTranscriptionService`
- Exposes `/ws/realtime` WebSocket endpoint
- Handles WebSocket connections/disconnections
- CORS middleware configuration

**WebSocket Flow**:
```python
@app.websocket("/ws/realtime")
async def websocket_endpoint(websocket: WebSocket):
    await websocket.accept()
    while True:
        message = await websocket.receive_text()
        await realtime_service.handle_websocket_message(websocket, message)
```

---

### 2. `core/session_manager.py` - Session State

**Purpose**: Manages all active transcription sessions in memory.

**Session Data Structure**:
```python
{
    "id": "realtime_1234567890_abc12345",
    "websocket": WebSocket,
    "start_time": datetime,
    "audio_buffer": [],           # Raw audio chunks for recording
    "current_chunk": [],          # Current speech segment
    "transcript_buffer": "",      # Accumulated transcript (with corrections)
    "raw_transcript_buffer": "",  # Original transcript (never modified)
    "segments": [],               # List of transcript segments
    "speaker_corrections": {},    # Manual speaker overrides
    "content_corrections": [],    # Voice correction history
    "pending_content_corrections": {},  # Awaiting accept/reject
    "vad_active": bool,
    "speech_in_progress": bool,
    "client_role": "plaintiff"|"defendant",
    # ... more fields
}
```

**Key Methods**:
| Method | Description |
|--------|-------------|
| `create_session(websocket, data)` | Create new session with initial state |
| `get_session(session_id)` | Retrieve session by ID |
| `delete_session(session_id)` | Remove session on end |
| `list_sessions()` | Get all active session IDs |

---

### 3. `services/sarvam_service.py` - Sarvam AI Integration

**Purpose**: Wrapper for the Sarvam AI Python SDK (`sarvamai`).

**Configuration**:
- **Model**: `saaras:v3` (supports translation mode)
- **Mode**: `translate` (always outputs English)
- **Auto-detect**: Input language detected automatically

**Key Methods**:

| Method | Description |
|--------|-------------|
| `create_vad_stream()` | Create streaming WebSocket for real-time STT |
| `transcribe_audio()` | Batch transcription for file uploads |
| `create_diarization_job()` | Create speaker diarization job |

**Streaming Connection**:
```python
async def create_vad_stream(self, model="saaras:v3", mode="translate", ...):
    return self.async_client.speech_to_text_translate_streaming.connect(
        model=model,
        mode=mode,
        vad_signals="true",
        input_audio_codec="wav",
    )
```

---

### 4. `services/vad_service.py` - Audio Streaming

**Purpose**: Manages the audio streaming pipeline to Sarvam AI.

**Key Features**:
- **PCM to WAV conversion**: Wraps raw PCM in WAV headers (SDK requirement)
- **Buffering**: Accumulates 0.5s minimum before sending (better transcription)
- **Queue-based sender**: Ensures ordered delivery
- **Auto-reconnect**: 3 retries with exponential backoff on disconnect

**Audio Flow**:
```
Frontend PCM → Buffer (0.5s) → pcm_to_wav() → Base64 → ws.translate() → Sarvam
```

**Key Methods**:

| Method | Description |
|--------|-------------|
| `start_vad_stream()` | Initialize streaming connection |
| `send_audio_chunk()` | Queue audio for sending |
| `flush_buffer()` | Send remaining buffered audio |
| `stop_vad_stream()` | Clean shutdown |

**PCM to WAV Helper**:
```python
def pcm_to_wav(pcm_data: bytes, sample_rate=16000, channels=1, sample_width=2):
    buffer = io.BytesIO()
    with wave.open(buffer, 'wb') as wav:
        wav.setnchannels(channels)
        wav.setsampwidth(sample_width)
        wav.setframerate(sample_rate)
        wav.writeframes(pcm_data)
    return buffer.getvalue()
```

---

### 5. `services/realtime/realtime_service.py` - Service Orchestrator

**Purpose**: Main coordinator for all real-time transcription operations.

**WebSocket Message Types**:

| Type | Direction | Description |
|------|-----------|-------------|
| `start_session` | In | Begin new transcription session |
| `audio_stream` | In | Send audio chunk (base64 PCM) |
| `end_session` | In | End session, trigger background processing |
| `tag_speaker` | In | Manually assign speaker role |
| `correct_speaker` | In | Correct speaker for a segment |
| `content_correction_accept` | In | Accept voice correction |
| `content_correction_reject` | In | Reject voice correction |
| `session_resync` | In | Reconnect to existing session |
| `session_started` | Out | Session ready confirmation |
| `transcription_update` | Out | New transcript segment |
| `correction_proposed` | Out | Voice correction detected |
| `correction_applied` | Out | Correction accepted |
| `session_ended` | Out | Session complete |

**Session Lifecycle**:
```
start_session → [audio_stream...] → end_session → background_processing → S3 upload
```

---

### 6. `services/realtime/audio_stream_handler.py` - Audio Processing

**Purpose**: Processes incoming audio and handles Sarvam VAD events.

**Key Functions**:

| Function | Description |
|----------|-------------|
| `process_audio()` | Decode base64 PCM, forward to VADService |
| `handle_vad_event()` | Process Sarvam responses |
| `_handle_transcript()` | Process transcription results |

**Event Normalization**:
```python
def _get(obj, key, default=None):
    """Handle both dict and object SDK responses"""
    if isinstance(obj, dict):
        return obj.get(key, default)
    return getattr(obj, key, default)
```

**Transcript Processing**:
1. Extract English transcript (already translated by Sarvam)
2. Get original language from `language_code` field
3. Run speaker identification heuristics
4. Check for voice commands (scratch/replace)
5. Broadcast to frontend

---

### 7. `services/realtime/command_parser.py` - Voice Commands

**Purpose**: Detect voice correction commands in transcripts.

**Supported Commands** (English only):

| Phrase | Result |
|--------|--------|
| "scratch that" | `{"kind": "scratch"}` - Delete previous segment |
| "change that to X" | `{"kind": "replace", "replacement": "X"}` |

**Detection Logic**:
```python
_SCRATCH_PATTERN = re.compile(r"^scratch\s+that\.?\s*$", re.IGNORECASE)
_REPLACE_PATTERN = re.compile(r"^change\s+that\s+to\s+(?P<replacement>.+?)\.?\s*$", re.IGNORECASE)
```

**Rules**:
- Commands must be at the START of the segment (not mid-segment)
- Only English segments are checked for commands
- Non-English segments are never treated as commands

---

### 8. `services/realtime/content_correction_handler.py` - Correction Lifecycle

**Purpose**: Manages the full lifecycle of voice corrections.

**Correction States**:
```
[proposed] → accept → [applied]
          → reject → [rejected]
          → timeout → [auto-committed]
          → reverse → [reversed]
```

**Key Methods**:

| Method | Description |
|--------|-------------|
| `propose()` | Create pending correction (10s timeout) |
| `accept()` | Staff accepts correction |
| `reject()` | Staff rejects correction |
| `reverse()` | Undo a previously applied correction |
| `force_commit_all_pending()` | Auto-commit on session end |

**Target Resolution**: Always targets the most recent LAWYER segment.

---

### 9. `services/realtime/transcript_materializer.py` - Correction Engine

**Purpose**: Compute effective transcript by overlaying corrections.

**Algorithm**:
1. Build segment state map (all visible initially)
2. Identify reversed correction IDs
3. Replay corrections in order:
   - Skip rejected entries
   - Skip reversed entries
   - Apply scratch (hide segment)
   - Apply replace (update text)
4. Build final transcript from visible segments

**Output**:
```python
(transcript_text, materialized_messages)
# transcript_text: Final concatenated text
# materialized_messages: Segments with effective_text, hidden flag
```

---

### 10. `services/realtime/background_processor.py` - Post-Session

**Purpose**: Async processing after session ends.

**Processing Steps**:
1. Save audio recording as WAV
2. Generate petition prose (lawyer-only continuous text)
3. Upload to S3:
   - `audio_recording.wav`
   - `transcription.txt`
   - `legal_transcript.txt`
   - `corrections.json`
   - `session_metadata.json`

**Note**: Diarization is currently DISABLED. The system outputs petition prose instead of speaker-attributed transcripts.

---

### 11. `services/legal_transcript_formatter.py` - Document Formatting

**Purpose**: Format transcripts into legal document formats.

**Formats**:

| Method | Output |
|--------|--------|
| `format_legal_transcript()` | Text with timestamps and speakers |
| `format_legal_transcript_json()` | Structured JSON |
| `format_petition_prose()` | Continuous prose (no speakers) |

**Speaker Precedence**:
1. Manual speaker correction (by time anchor)
2. Diarization role mapping
3. Heuristic guess

**Content Corrections**:
- Corrections matched to segments by audio time anchor
- Scratched segments hidden from output
- Replaced segments show new text with † marker

---

### 12. `services/diarization_service.py` - Speaker Diarization

**Purpose**: Post-session speaker identification using Sarvam batch API.

**Process**:
1. Convert audio to 16kHz mono WAV
2. Create diarization job (`saarika:v2.5` model)
3. Upload audio file
4. Wait for processing
5. Download and parse results

**Output Formats**:
- `.txt` - Human-readable transcript
- `.json` - Structured data
- `.srt` - Subtitle format

**Note**: Currently disabled in favor of petition prose mode.

---

### 13. `services/s3_storage_service.py` - Cloud Storage

**Purpose**: Upload session artifacts to AWS S3.

**Bucket Structure**:
```
talekar-stt/
├── {user_id}/
│   └── {DD-MM-YYYY}/
│       └── {session_id}/
│           ├── audio_recording.wav
│           ├── transcription.txt
│           ├── legal_transcript.txt
│           ├── legal_transcript.json
│           ├── corrections.json
│           └── session_metadata.json
```

**Additional Features**:
- Feedback CSV storage
- Evaluation results storage
- Automatic local file cleanup after upload

---

### 14. `utils/language_utils.py` - Language Detection

**Purpose**: Detect language from Unicode script analysis.

**Supported Scripts**:
- Hindi (Devanagari): `\u0900-\u097F`
- Telugu: `\u0C00-\u0C7F`
- Tamil: `\u0B80-\u0BFF`
- Kannada: `\u0C80-\u0CFF`
- Malayalam: `\u0D00-\u0D7F`
- Bengali: `\u0980-\u09FF`
- Gujarati: `\u0A80-\u0AFF`
- Punjabi: `\u0A00-\u0A7F`
- English: ASCII `a-zA-Z`

**Note**: This is a FALLBACK. Primary language source is Sarvam's `language_code` field.

---

### 15. `utils/speaker_utils.py` - Speaker Heuristics

**Purpose**: Identify speaker role from transcript content.

**Indicators**:

| Speaker | Example Phrases |
|---------|-----------------|
| LAWYER | "under the law", "my advice would be", "legally speaking" |
| CLIENT | "what happened was", "can i sue", "what are my options" |

**Returns**: `{"speaker": "LAWYER"|"CLIENT"|"SPEAKER", "confidence": 0.0-1.0}`

---

## Data Flow

### Real-Time Transcription Flow

```
1. Frontend sends: {type: "audio_stream", audio_data: "<base64 PCM>"}
                          │
2. AudioStreamHandler.process_audio()
   - Decode base64
   - Validate PCM format
   - Append to current_chunk
   - Forward to VADService
                          │
3. VADService.send_audio_chunk()
   - Buffer until 0.5s
   - Convert PCM → WAV
   - Base64 encode
   - Send via ws.translate()
                          │
4. Sarvam AI processes audio
   - Auto-detect language
   - Translate to English
   - Return transcript
                          │
5. VADService listener receives event
   - Forward to callback
                          │
6. AudioStreamHandler.handle_vad_event()
   - Normalize event format
   - Extract transcript + language
   - Check for voice commands
                          │
7. If voice command:
   - ContentCorrectionHandler.propose()
   - Frontend: {type: "correction_proposed"}
   
   If normal content:
   - Append to buffers
   - Frontend: {type: "transcription_update"}
```

### End Session Flow

```
1. Frontend sends: {type: "end_session"}
                          │
2. RealTimeTranscriptionService.end_real_time_session()
   - Mark session as ending
   - Flush audio buffer
   - Stop VAD stream
   - Force-commit pending corrections
   - Send session_ended to frontend
                          │
3. BackgroundProcessor.process()
   - Save audio as WAV
   - Generate petition prose
   - Upload to S3
   - Cleanup local files
```

---

## Configuration

### Environment Variables

| Variable | Description |
|----------|-------------|
| `SARVAM_API_KEY` | Sarvam AI API subscription key |
| `AWS_ACCESS_KEY_ID` | AWS credentials for S3 |
| `AWS_SECRET_ACCESS_KEY` | AWS credentials for S3 |

### Constants

| Constant | Value | Location |
|----------|-------|----------|
| `MIN_BUFFER_BYTES` | 16000 bytes (0.5s) | vad_service.py |
| `MAX_RECONNECT_ATTEMPTS` | 3 | vad_service.py |
| `_AUTO_COMMIT_TIMEOUT_SECONDS` | 10 | content_correction_handler.py |
| `_TIME_MATCH_TOLERANCE_SECONDS` | 2.0 | legal_transcript_formatter.py |

---

## Frontend WebSocket Contract

### Messages FROM Frontend

```typescript
// Start session
{type: "start_session", client_role?: "plaintiff"|"defendant", username?: string}

// Send audio
{type: "audio_stream", session_id: string, audio_data: string /* base64 PCM */}

// End session
{type: "end_session", session_id: string, username?: string}

// Accept correction
{type: "content_correction_accept", session_id: string, correction_id: string}

// Reject correction
{type: "content_correction_reject", session_id: string, correction_id: string}
```

### Messages TO Frontend

```typescript
// Session started
{type: "session_started", session_id: string, output_language: "en-IN", auto_detect: true}

// New transcript
{
  type: "transcription_update",
  session_id: string,
  segment_id: string,
  transcript: string,        // Always English
  language: string,          // Original spoken language (hi-IN, te-IN, etc.)
  original_language: string, // Same as language
  speaker: string,
  start_time_seconds: number,
  end_time_seconds: number
}

// Correction proposed
{
  type: "correction_proposed",
  correction_id: string,
  kind: "scratch"|"replace",
  target_segment_id: string,
  original_text: string,
  replacement_text?: string,
  auto_commit_at: string
}

// Correction applied
{type: "correction_applied", correction_id: string, kind: string, confirmed_by: string}

// Session ended
{type: "session_ended", data: {session_id, duration, background_processing: true}}
```

---

## Error Handling

All WebSocket errors return:
```json
{type: "error", message: "Error description"}
```

Common errors:
- `"Invalid session"` - Session ID not found
- `"Failed to start VAD stream"` - Sarvam connection failed
- `"Audio processing failed"` - Invalid audio format

---

## Testing

```bash
# Run all tests
cd Backend
python -m pytest tests/ -v

# Run specific test
python -m pytest tests/test_hindi_to_english_streaming.py -v

# Test language detection
python -m pytest tests/test_hindi_to_english_streaming.py::test_language_utils_detects_hindi -v
```

---

## Startup

```bash
cd Backend
source venv/bin/activate  # or .\venv\Scripts\activate on Windows
uvicorn main:app --host 0.0.0.0 --port 8000
```

Server logs:
```
✅ S3 client initialized for bucket: talekar-stt
INFO: SarvamService initialized with saaras:v3 translate mode
INFO: RealTimeTranscriptionService initialized with always-English translation mode
INFO: Uvicorn running on http://0.0.0.0:8000
```
