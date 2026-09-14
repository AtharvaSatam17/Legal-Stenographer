# Legal Stenographer - Backend

Real-time court transcription backend with AI-powered speaker diarization.

## Structure

```
Backend/
├── main.py                          # FastAPI entry point (WebSocket /ws/realtime)
├── requirements_legal.txt           # Python dependencies
│
├── core/
│   └── session_manager.py           # In-memory session state management
│
├── services/
│   ├── sarvam_service.py            # Sarvam AI API (STT, VAD streaming, diarization)
│   ├── vad_service.py               # Voice Activity Detection stream management
│   ├── diarization_service.py       # Speaker diarization pipeline
│   ├── s3_storage_service.py        # AWS S3 storage for recordings & transcripts
│   ├── legal_transcript_formatter.py # Legal transcript formatting [HH:MM:SS] ROLE: text
│   │
│   └── realtime/
│       ├── realtime_service.py      # Main WebSocket message orchestrator
│       ├── audio_stream_handler.py  # Audio decoding, VAD feeding, transcript handling
│       ├── background_processor.py  # Post-session: diarization + S3 upload
│       └── feedback_handler.py      # User feedback storage to S3 CSV
│
└── utils/
    ├── audio_utils.py               # WAV buffer creation
    ├── language_utils.py            # Script-based language detection
    └── speaker_utils.py             # Heuristic speaker role identification
```

## Setup

```bash
pip install -r requirements_legal.txt
```

## Environment Variables

Create a `.env` file:

```
SARVAM_API_KEY=your_sarvam_api_key
AWS_ACCESS_KEY_ID=your_aws_key
AWS_SECRET_ACCESS_KEY=your_aws_secret
```

## Run

```bash
uvicorn main:app --host 0.0.0.0 --port 8000
```
