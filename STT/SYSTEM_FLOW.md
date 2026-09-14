# Legal Stenographer - System Flow

## Overview

This is a **two-party lawyer–client consultation transcription tool**. It records private consultations between an attorney and their client (plaintiff or defendant), transcribes in real-time using Sarvam AI, identifies which speaker is the lawyer vs. the client, and produces formatted transcripts with timestamps.

**This is NOT a courtroom proceeding tool.** There is no judge, no witness, and no multi-party courtroom model. The system is designed exclusively for two-party legal consultations where:
- **Party 1**: Lawyer (Attorney/Counsel)
- **Party 2**: Client — either a **Plaintiff** or **Defendant**, configurable per case

---

## Architecture Diagram

```
┌─────────────────────────────────────────────────────────────┐
│                    BROWSER (Frontend)                        │
│                                                             │
│  ┌──────────────┐   ┌──────────────┐   ┌───────────────┐   │
│  │ Microphone   │──▶│ AudioContext  │──▶│ ScriptProcessor│  │
│  │ (getUserMedia)│   │ (16kHz mono) │   │ (4096 samples)│   │
│  └──────────────┘   └──────────────┘   └───────┬───────┘   │
│                                                 │            │
│                          Float32 → Int16 PCM → base64        │
│                                                 │            │
│  ┌──────────────────────────────────────────────▼────────┐  │
│  │            WebSocket Connection                        │  │
│  │            ws://host:8000/ws/realtime                  │  │
│  └──────────────────────────────────────────────┬────────┘  │
└─────────────────────────────────────────────────┼───────────┘
                                                  │
                                                  ▼
┌─────────────────────────────────────────────────────────────┐
│                    SERVER (Backend - FastAPI)                │
│                                                             │
│  ┌────────────────────────────────────────────────────────┐ │
│  │ main.py (WebSocket endpoint /ws/realtime)              │ │
│  └───────────────────────────┬────────────────────────────┘ │
│                              │                              │
│  ┌───────────────────────────▼────────────────────────────┐ │
│  │ RealTimeTranscriptionService                           │ │
│  │  • Routes messages (start/audio/end/tag/correct)       │ │
│  │  • Manages session lifecycle                           │ │
│  └──┬──────────────┬─────────────────────┬────────────────┘ │
│     │              │                     │                  │
│     ▼              ▼                     ▼                  │
│  ┌──────┐  ┌─────────────┐  ┌─────────────────────────┐    │
│  │ VAD  │  │AudioStream  │  │ BackgroundProcessor     │    │
│  │Service│  │Handler      │  │ (post-session)          │    │
│  └──┬───┘  └──────┬──────┘  └────────────┬────────────┘    │
│     │              │                      │                  │
│     ▼              │                      ▼                  │
│  ┌──────────┐      │         ┌─────────────────────────┐    │
│  │ Sarvam   │◀─────┘         │ DiarizationService      │    │
│  │ AI API   │                │ + LegalTranscriptFormatter│   │
│  └──────────┘                │ + S3StorageService       │    │
│                              └─────────────────────────┘    │
└─────────────────────────────────────────────────────────────┘
```

---

## Speaker Model (2-Party)

### Roles

| Role | Description |
|------|-------------|
| **LAWYER** | The attorney conducting the consultation |
| **PLAINTIFF** or **DEFENDANT** | The client (configurable per session via `client_role` field) |

The `client_role` is set at session start and determines whether SPEAKER_2 maps to PLAINTIFF or DEFENDANT.

### Speaker Assignment Precedence

When generating the final transcript, speaker assignment follows this strict priority:

```
1. Manual correction (per segment_id)     ← HIGHEST PRIORITY
2. Manual speaker tag (per speaker channel)
3. Diarization result (from Sarvam AI)
4. Real-time heuristic guess (keywords)   ← LOWEST PRIORITY
```

Corrections are stored as an **overlay** keyed by `segment_id` and are never overwritten by diarization.

### Diarization Role Mapping

| Sarvam Output | Default Mapping |
|---------------|----------------|
| SPEAKER_1 | LAWYER |
| SPEAKER_2 | Value of `client_role` (PLAINTIFF or DEFENDANT) |

If the user provides manual speaker tags (e.g., "SPEAKER_1 = CLIENT"), those override the defaults.

### Speaker Identification Heuristic

Used as a real-time fallback when diarization isn't available yet:

**Lawyer indicators** (advisory/legal language):
- "under the law", "my advice would be", "your rights are"
- "legally speaking", "the statute says", "your options are"
- "as your counsel", "based on the evidence", "the next step would be"

**Client indicators** (narrative/questioning language):
- "what happened was", "i was told", "i want to file"
- "can i sue", "what are my options", "how long will this take"
- "they promised me", "i have proof", "what should i do"

---

## Step-by-Step Flow

### Phase 1: Connection & Session Start

```
Frontend                          Backend
   │                                 │
   │──── WebSocket connect ─────────▶│  ws://host:8000/ws/realtime
   │◀─── connection accepted ────────│
   │                                 │
   │──── start_session ─────────────▶│  { type: "start_session",
   │     (with consultation metadata)│    username,
   │                                 │    case_id,
   │                                 │    client_role: "plaintiff"|"defendant",
   │                                 │    matter_type: "consultation",
   │                                 │    preferred_language: "en-IN" }
   │                                 │
   │                                 │── SessionManager.create_session()
   │                                 │── VADService.start_vad_stream()
   │                                 │
   │◀─── session_started ───────────│  { type: "session_started",
   │                                 │    session_id, vad_enabled: true,
   │                                 │    client_role: "plaintiff" }
   │                                 │
   │── Start microphone recording    │
```

### Phase 2: Real-Time Transcription Loop

```
Frontend                          Backend                    Sarvam AI
   │                                 │                          │
   │── audio_stream ────────────────▶│                          │
   │   { session_id, audio_data }    │                          │
   │                                 │── decode & buffer ───────│
   │                                 │── send to VAD ──────────▶│
   │                                 │                          │
   │                                 │◀── transcript result ────│
   │                                 │                          │
   │                                 │── Generate segment_id (stable UUID)
   │                                 │── Run heuristic speaker guess
   │                                 │── Store segment in session
   │                                 │
   │◀─── transcription_update ──────│  { type: "transcription_update",
   │                                 │    segment_id: "seg_abc123",
   │                                 │    transcript: "...",
   │                                 │    speaker: "LAWYER",
   │                                 │    speaker_confidence: 0.75 }
   │                                 │
   ▼ ... repeats every ~250ms ...    ▼
```

### Phase 2a: Manual Speaker Tagging (optional)

```
Frontend                          Backend
   │                                 │
   │──── tag_speaker ───────────────▶│  { type: "tag_speaker",
   │    (user clicks "Speaker 1      │    session_id,
   │     = Lawyer" toggle)           │    speaker_id: "SPEAKER_1",
   │                                 │    role: "LAWYER" }
   │                                 │
   │                                 │── session["speaker_tags"]["SPEAKER_1"] = "LAWYER"
   │                                 │
   │◀─── speaker_tagged ────────────│  { speaker_id, role }
```

### Phase 2b: Mid-Session Speaker Correction

```
Frontend                          Backend
   │                                 │
   │──── correct_speaker ───────────▶│  { type: "correct_speaker",
   │    (user clicks speaker badge   │    session_id,
   │     to cycle LAWYER→CLIENT)     │    segment_id: "seg_abc123",
   │                                 │    speaker: "PLAINTIFF" }
   │                                 │
   │                                 │── session["speaker_corrections"]["seg_abc123"] = "PLAINTIFF"
   │                                 │   (stored as overlay, never overwrites raw data)
   │                                 │
   │◀─── speaker_corrected ─────────│  { segment_id, corrected_speaker }
```

### Phase 3: End Session & Background Processing

```
Frontend                          Backend
   │                                 │
   │──── end_session ───────────────▶│  { type: "end_session",
   │                                 │    session_id, username }
   │                                 │
   │◀─── session_ended ─────────────│  (immediate response)
   │                                 │
   │                                 │── Background task:
   │                                 │   1. Combine audio → WAV
   │                                 │   2. Diarization (num_speakers=2)
   │                                 │   3. Apply role mapping:
   │                                 │      - Use manual speaker_tags if set
   │                                 │      - Else default: SPEAKER_1→LAWYER,
   │                                 │        SPEAKER_2→client_role
   │                                 │   4. Apply speaker_corrections overlay
   │                                 │      (corrections > diarization > heuristic)
   │                                 │   5. Format transcript:
   │                                 │      [00:01:23] LAWYER: ...
   │                                 │      [00:01:45] PLAINTIFF: ...
   │                                 │   6. Upload to S3
   │                                 │   7. Cleanup temp files
```

---

## Segment Model & Corrections

Each transcript segment gets a **stable `segment_id`** (UUID-based, e.g., `seg_a1b2c3d4e5f6`). This allows:

1. **Targeted corrections** — correct a single segment's speaker without replacing the whole transcript
2. **Correction overlay** — stored separately from raw STT/diarization output
3. **Audit trail** — the original heuristic/diarization assignment is preserved even after correction

### Segment Data Structure (stored in session)

```json
{
  "segment_id": "seg_abc123def456",
  "transcript": "What are my options here?",
  "speaker_heuristic": "CLIENT",
  "speaker_confidence": 0.65,
  "timestamp": "2024-01-15T10:23:45.123Z",
  "language": "en-IN"
}
```

### Corrections Overlay (stored separately)

```json
{
  "seg_abc123def456": "PLAINTIFF",
  "seg_xyz789ghi012": "LAWYER"
}
```

When the final transcript is generated, each segment checks:
1. Is there a correction for my `segment_id`? → Use it
2. Else, does diarization provide a speaker? → Map via role_mapping
3. Else, use the real-time heuristic guess

---

## WebSocket Message Types

### Client → Server

| Type | Purpose | Key Fields |
|------|---------|------------|
| `start_session` | Begin consultation recording | `username`, `case_id`, `client_role`, `matter_type`, `preferred_language` |
| `audio_stream` | Send audio chunk | `session_id`, `audio_data` (base64), `sample_rate` |
| `end_session` | Stop recording & trigger processing | `session_id`, `username` |
| `update_transcript` | Save edited full transcript | `session_id`, `transcript` |
| `tag_speaker` | Manually assign a speaker channel | `session_id`, `speaker_id`, `role` |
| `correct_speaker` | Correct speaker for a specific segment | `session_id`, `segment_id`, `speaker` |

### Server → Client

| Type | Purpose | Key Fields |
|------|---------|------------|
| `session_started` | Confirm session created | `session_id`, `vad_enabled`, `client_role` |
| `transcription_update` | Real-time segment with stable ID | `segment_id`, `transcript`, `speaker`, `speaker_confidence`, `timestamp` |
| `speaker_tagged` | Confirm manual tag | `speaker_id`, `role`, `current_tags` |
| `speaker_corrected` | Confirm segment correction | `segment_id`, `corrected_speaker`, `total_corrections` |
| `session_ended` | Session closed, background processing started | `duration`, `started_at`, `ended_at` |
| `error` | Error notification | `message` |

---

## Frontend Components

```
pages/index.js
  └── LegalTranscriptionSystem.js    (main orchestrator)
        ├── LegalHeader.js           (title, case info, connection status)
        ├── LegalMetadataPanel.js    (case ID, client role selector, matter type)
        ├── LegalControlsPanel.js    (Start/Pause/Resume/End session buttons)
        ├── LegalTranscriptPanel.js  (live transcript with per-segment speaker correction)
        ├── SpeakerLegend.js         (2-color legend: Lawyer=blue, Client=amber)
        └── LegalExportService.js    (export as PDF/TXT)
```

### Key UI Behaviors

- **Client Role selector** in metadata panel: "Plaintiff" or "Defendant" dropdown. Sets `client_role` for the session.
- **Speaker badges** in transcript: clickable during active session. Clicking cycles: LAWYER → PLAINTIFF/DEFENDANT → SPEAKER → LAWYER. Each click sends a `correct_speaker` message.
- **Speaker Legend**: shows only 2 entries (Lawyer in blue, Client in amber) with dynamic label based on `client_role`.

---

## Key Services & Their Roles

| Service | What It Does |
|---------|-------------|
| **SessionManager** | Stores session state including `client_role`, `speaker_tags`, `speaker_corrections`, and `segments` list |
| **AudioStreamHandler** | Receives audio, feeds VAD, generates `segment_id` per transcript chunk, runs heuristic, sends real-time updates |
| **VADService** | Manages streaming VAD connections to Sarvam AI |
| **SarvamService** | Wrapper for Sarvam AI SDK (STT, VAD, diarization) |
| **DiarizationService** | Post-session: combines audio → runs speaker separation (num_speakers=2) |
| **LegalTranscriptFormatter** | Formats segments with corrections overlay applied. Output: `[HH:MM:SS] ROLE: text` |
| **BackgroundProcessor** | Orchestrates post-session: diarization → apply corrections → format → S3 upload |
| **S3StorageService** | Uploads artifacts to S3 organized by user/date/session |

---

## S3 Storage Structure

```
talekar-stt/                        (S3 bucket)
└── {username}/
    └── {DD-MM-YYYY}/
        └── {session_id}/
            ├── audio.wav               # Full recording
            ├── transcript.txt          # Raw transcript
            ├── consultation_transcript.txt  # Formatted: [HH:MM:SS] ROLE: text
            ├── diarization.json        # Speaker segments with timestamps
            ├── corrections.json        # Speaker corrections overlay
            └── metadata.json           # Session info (case_id, matter_type, client_role, ...)
```

---

## Audio Pipeline Detail

1. **Browser**: `navigator.mediaDevices.getUserMedia()` → mono 16kHz stream
2. **AudioContext**: Creates `ScriptProcessor` with buffer size 4096 samples
3. **Conversion**: Float32 samples → Int16 PCM (`sample * 0x7FFF`)
4. **Encoding**: Int16 buffer → base64 string
5. **Transport**: WebSocket JSON message every ~256ms (4096 samples / 16000 Hz)
6. **Backend decode**: base64 → raw bytes → append to session buffer
7. **VAD stream**: Bytes sent to Sarvam AI via their streaming WebSocket
8. **Sarvam returns**: Transcript text + language detection when speech ends
9. **Backend**: Generates stable `segment_id`, runs heuristic, stores segment
10. **Frontend receives**: `transcription_update` with `segment_id` → displays in UI

---

## Sample Transcript Output

```
================================================================================
CONSULTATION TRANSCRIPT
Roles: LAWYER / PLAINTIFF
================================================================================

[00:00:12] LAWYER: Good afternoon. Thank you for coming in today. I have reviewed the documents you sent over.
[00:00:25] PLAINTIFF: Thank you. What happened was, they fired me without any notice and I had been working there for six years.
[00:00:45] LAWYER: Under the law, wrongful termination claims require us to show that the employer violated either the contract terms or statutory protections. Your options are to file a complaint with the labor commission or pursue civil litigation.
[00:01:10] PLAINTIFF: How long will this take? And can I sue for damages?
[00:01:22] LAWYER: My advice would be to start with the labor commission. It is faster, typically three to six months. If that does not resolve it, we can escalate to court. Based on the evidence you have, I think you have a strong case for compensation.

================================================================================
END OF TRANSCRIPT
================================================================================
```

---

## Environment Variables

### Backend (.env)

```
SARVAM_API_KEY=<your_sarvam_api_key>
AWS_ACCESS_KEY_ID=<your_aws_key>
AWS_SECRET_ACCESS_KEY=<your_aws_secret>
```

### Frontend (.env.local)

```
NEXT_PUBLIC_WS_URL=ws://localhost:8000/ws/realtime
COGNITO_REGION=ap-south-1
COGNITO_USER_POOL_ID=<pool_id>
COGNITO_CLIENT_ID=<client_id>
COGNITO_DOMAIN=<cognito_domain>
CALLBACK_URI=http://localhost:3000/api/auth/callback
```

---

## Running the System

```bash
# Terminal 1 - Backend
cd Backend
.\venv\Scripts\activate
uvicorn main:app --host 0.0.0.0 --port 8000

# Terminal 2 - Frontend
cd Frontend
npm install
npm run dev
```

Open http://localhost:3000 → Fill in case ID + select client role → Start session → Speak → End session.
