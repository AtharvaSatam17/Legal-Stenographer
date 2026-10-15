# services/realtime/audio_stream_handler.py

import asyncio
import base64
import json
import time
import uuid
import logging
from datetime import datetime
from typing import Dict, List, Optional, Any
from fastapi import WebSocket

from utils.language_utils import LanguageUtils
from utils.speaker_utils import identify_speaker
from services.realtime.command_parser import classify_segment

logger = logging.getLogger(__name__)
logger.setLevel(logging.INFO)


def _get(obj: Any, key: str, default: Any = None) -> Any:
    """
    Normalize attribute/key access for SDK objects that may be dicts or typed objects.
    
    The Sarvam SDK may deliver events as typed dataclass-like objects (with attributes)
    or as plain dicts depending on version and context. This helper ensures we can
    access fields uniformly without TypeError.
    
    Args:
        obj: The object to access (dict or object with attributes)
        key: The attribute/key name to access
        default: Default value if key doesn't exist
    
    Returns:
        The value at key/attribute, or default if not found
    """
    if obj is None:
        return default
    if isinstance(obj, dict):
        return obj.get(key, default)
    return getattr(obj, key, default)


class AudioStreamHandler:
    """
    Handles audio streaming from frontend and VAD events from Sarvam.
    
    Key responsibilities:
    - Receive base64 PCM audio from frontend WebSocket
    - Forward audio to VADService for transcription
    - Process transcription events and broadcast to frontend
    - Handle voice commands for corrections
    - Track speaker and language metadata
    
    Note: Transcript text is now always English (translated by Sarvam).
    The original spoken language is provided by the SDK in language_code.
    """

    def __init__(self, session_manager, vad_service):
        self.session_manager = session_manager
        self.vad_service = vad_service

    # ============================================================
    # AUDIO INPUT FROM FRONTEND
    # ============================================================
    async def process_audio(self, websocket: WebSocket, data: Dict):
        """
        Process incoming audio data from the frontend.
        
        Frontend sends: {type: "audio_stream", session_id, audio_data: <base64 PCM>}
        Audio is raw int16 PCM, 16kHz, mono.
        """
        session_id = data.get("session_id")
        audio_data = data.get("audio_data")

        if not session_id or not self.session_manager.exists(session_id):
            print(f"[DEBUG][AUDIO] REJECTED: invalid/unknown session_id={session_id} "
                  f"(exists={self.session_manager.exists(session_id) if session_id else 'no_id'})")
            await websocket.send_text(json.dumps({
                "type": "error",
                "message": "Invalid session"
            }))
            return

        session = self.session_manager.get_session(session_id)

        if session.get("ending", False):
            print(f"[DEBUG][AUDIO] DROPPED: session ending, session_id={session_id}")
            return

        if not session.get("vad_active"):
            print(f"[DEBUG][AUDIO] DROPPED: vad_active=False, session_id={session_id}")
            return

        try:
            audio_buffer = base64.b64decode(audio_data)

            if len(audio_buffer) % 2 != 0:
                print(f"[DEBUG][AUDIO] DROPPED: odd byte length {len(audio_buffer)}, session_id={session_id}")
                return

            # Track chunk count
            if '_audio_chunk_count' not in session:
                session['_audio_chunk_count'] = 0
            session['_audio_chunk_count'] += 1

            # Print a heartbeat every 25 blobs so we can see audio flowing in.
            if session['_audio_chunk_count'] % 25 == 0:
                print(f"[DEBUG][AUDIO] blobs in: count={session['_audio_chunk_count']} "
                      f"last_size={len(audio_buffer)}B session_id={session_id}")

            session["current_chunk"].append(audio_buffer)

            await self.vad_service.send_audio_chunk(
                session_id=session_id,
                audio_data=audio_buffer,
                encoding="audio/wav",
                sample_rate=16000
            )

        except Exception as e:
            print(f"[DEBUG][AUDIO] ERROR processing audio for session_id={session_id}: {e}")
            logger.exception(f"Audio processing error: {e}")
            await websocket.send_text(json.dumps({
                "type": "error",
                "message": "Audio processing failed"
            }))

    # ============================================================
    # VAD EVENT CALLBACK
    # ============================================================
    async def handle_vad_event(self, session_id: str, event: Any):
        """
        Handle events from the Sarvam VAD stream.
        
        Events can be typed SDK objects or dicts. We use _get() to handle both.
        
        Event types:
        - "events": VAD signals (START_SPEECH, END_SPEECH)
        - "data": Transcription results
        - "stream_closed": Connection lost (from VADService)
        - "stream_reconnected": Connection restored (from VADService)
        """
        if not self.session_manager.exists(session_id):
            return

        session = self.session_manager.get_session(session_id)
        websocket = session["websocket"]

        try:
            # Get event type using normalizer
            event_type = _get(event, "type", "unknown")

            # ---- RAW EVENT DUMP: print EVERYTHING Sarvam sends, every time ----
            # This is the key debug line: it shows the type and raw content of
            # every message from Sarvam, so no event is ever handled silently.
            try:
                _raw = event if isinstance(event, dict) else getattr(event, "__dict__", str(event))
                _raw_str = str(_raw)
            except Exception:
                _raw_str = str(event)
            print(f"[DEBUG][SARVAM-RAW] session={session_id} py_type={type(event).__name__} "
                  f"event_type='{event_type}' speech_in_progress={session.get('speech_in_progress')} "
                  f"raw={_raw_str[:300]}")

            # Handle synthetic events from VADService
            if event_type == "stream_closed":
                reason = _get(event, "reason", "unknown")
                logger.warning(f"Stream closed for session={session_id}: {reason}")
                await websocket.send_text(json.dumps({
                    "type": "stream_status",
                    "session_id": session_id,
                    "status": "disconnected" if _get(event, "reason") == "reconnect_failed" else "reconnecting",
                    "reason": reason,
                }))
                return

            if event_type == "stream_reconnected":
                logger.info(f"Stream reconnected for session={session_id}")
                await websocket.send_text(json.dumps({
                    "type": "stream_status",
                    "session_id": session_id,
                    "status": "connected",
                }))
                return

            # Handle VAD signal events
            if event_type == "events":
                event_data = _get(event, "data")
                signal_type = _get(event_data, "signal_type")
                print(f"[DEBUG][VAD-SIGNAL] session={session_id} signal_type='{signal_type}'")

                if signal_type == "START_SPEECH":
                    session["speech_in_progress"] = True
                    print(f"[DEBUG][VAD-SIGNAL] 🎙️ SPEECH STARTED session={session_id}")

                elif signal_type == "END_SPEECH":
                    session["speech_in_progress"] = False
                    print(f"[DEBUG][VAD-SIGNAL] 🛑 SPEECH ENDED session={session_id} "
                          f"current_chunk_len={len(session.get('current_chunk', []))}")

                    if session["current_chunk"]:
                        await self._process_vad_chunk(session_id)

            # Handle transcription data events
            elif event_type == "data":
                # Risk D defensive assertion — retroactive VAD refinement
                now_mono = time.monotonic()
                last_data_time = session.get("_last_data_event_mono")
                if last_data_time is not None:
                    gap_ms = (now_mono - last_data_time) * 1000.0
                    if gap_ms < 200.0:
                        logger.warning(
                            f"RISK-D WARNING: Two 'data' events arrived {gap_ms:.1f}ms apart "
                            f"for session={session_id}. Possible interim→final refinement detected."
                        )
                session["_last_data_event_mono"] = now_mono

                event_data = _get(event, "data")
                transcript = _get(event_data, "transcript", "")
                if isinstance(transcript, str):
                    transcript = transcript.strip()

                if transcript:
                    print(f"[DEBUG][SARVAM] ✅ data event WITH TEXT: session={session_id} "
                          f"transcript='{transcript[:80]}' (len={len(transcript)})")
                    await self._handle_transcript(session_id, transcript, event_data)
                else:
                    # Dump the raw event_data so we can see WHY it's empty (maybe
                    # the text lives in another field, or there's an error).
                    try:
                        _ed = event_data if isinstance(event_data, dict) else getattr(event_data, "__dict__", str(event_data))
                    except Exception:
                        _ed = str(event_data)
                    print(f"[DEBUG][SARVAM] ⚠️ EMPTY transcript — not handled, session={session_id} "
                          f"raw_data={str(_ed)[:300]}")

            else:
                print(f"[DEBUG][SARVAM-OTHER] UNHANDLED event_type='{event_type}' session={session_id} "
                      f"(this event produced no transcript and no VAD signal)")

        except Exception as e:
            print(f"[DEBUG][VAD] ❌ handle_vad_event EXCEPTION session_id={session_id}: {type(e).__name__}: {e}")
            import traceback
            traceback.print_exc()
            logger.exception(f"VAD handle_vad_event error for session={session_id}: {e}")

    # ============================================================
    # TRANSCRIPT HANDLING
    # ============================================================
    async def _handle_transcript(self, session_id: str, transcript: str, event_data: Any):
        """
        Process a transcription result from Sarvam.
        
        The transcript is now ALWAYS in English (translated by mode="translate").
        The original spoken language is available from the SDK's language_code field.
        
        Args:
            session_id: Session identifier
            transcript: English transcript text
            event_data: Full event data from SDK (may contain language_code, metrics, etc.)
        """
        session = self.session_manager.get_session(session_id)
        if not session:
            print(f"[DEBUG][TRANSCRIPT] NO SESSION for session_id={session_id} — dropping transcript")
            return

        # Phase 1, Step 5 — reject late-arriving transcripts after end_session
        if session.get("ending", False):
            print(f"[DEBUG][TRANSCRIPT] session ending — dropping transcript, session_id={session_id}")
            return

        websocket = session["websocket"]

        _prev = session.get("segments", [])
        print(f"[DEBUG][TRANSCRIPT] handling: session_id={session_id} text='{transcript[:60]}' "
              f"existing_segments={len(_prev)} "
              f"last_seg_end={_prev[-1].get('end_time_seconds') if _prev else 'none'}")

        # Generate a stable segment_id for this transcript segment
        segment_id = f"seg_{uuid.uuid4().hex[:12]}"

        # ----------------------------------------------------------
        # Language detection: prefer SDK's language_code (the SPOKEN language),
        # fall back to LanguageUtils only if SDK doesn't provide one.
        #
        # Note: The transcript text is now English, but "language" represents
        # what the speaker actually said (e.g., "hi-IN" for Hindi input).
        # ----------------------------------------------------------
        sdk_language = _get(event_data, "language_code")
        if sdk_language and sdk_language != "unknown":
            original_language = sdk_language
        else:
            # Fallback to script detection (only used if SDK gives nothing)
            original_language = LanguageUtils.detect_actual_language(transcript)
            if not original_language:
                original_language = "unknown"

        self._update_language_detection(session, original_language)

        # ----------------------------------------------------------
        # Speaker identification runs on English text now.
        # The identify_speaker heuristic looks for phrases like
        # "my client", "your honor", etc.
        # ----------------------------------------------------------
        speaker_info = identify_speaker(transcript)
        heuristic_speaker = speaker_info.get("speaker")

        # ----------------------------------------------------------
        # Audio-time anchoring (Phase 0, Step 0.3.1)
        # ----------------------------------------------------------
        metrics = _get(event_data, "metrics")
        audio_end_time_seconds = _get(metrics, "audio_duration") if metrics else None

        # Derive start_time from the previous segment's end time.
        # NOTE: segments created by a transcript edit (and paragraph-break
        # markers) carry end_time_seconds=None, so we must coalesce None->0.0
        # everywhere here, otherwise the arithmetic below raises TypeError and
        # the segment is silently dropped (never broadcast). This is what made
        # transcription appear "dead" after editing/AI drafting + save.
        prev_segments = session.get("segments", [])
        prev_end_raw = prev_segments[-1].get("end_time_seconds") if prev_segments else None
        prev_end_val = prev_end_raw if isinstance(prev_end_raw, (int, float)) else 0.0

        start_time_seconds = prev_end_val

        # If the SDK didn't provide audio_duration, fall back to wall-clock offset
        if audio_end_time_seconds is None:
            end_time_seconds = (datetime.now() - session["start_time"]).total_seconds()
            start_time_seconds = prev_end_val
        else:
            end_time_seconds = audio_end_time_seconds

        # Monotonicity assertion for audio-time anchors
        if prev_segments:
            prev_end = prev_end_val
            if start_time_seconds < prev_end - 0.01:  # small epsilon for float precision
                logger.warning(
                    f"MONOTONICITY WARNING: New segment start_time_seconds={start_time_seconds:.3f} "
                    f"is less than previous segment end_time_seconds={prev_end:.3f} "
                    f"for session={session_id}. Clamping start_time to previous end."
                )
                start_time_seconds = prev_end

        # ----------------------------------------------------------
        # "New paragraph" voice command detection (pre-broadcast).
        #
        # Transcript is always English, so classify using language="en-IN".
        # A matched command is NOT content: it inserts a paragraph break and
        # is never broadcast or stored as transcript text.
        # ----------------------------------------------------------
        command = classify_segment(transcript, language="en-IN")

        if command is not None and command.get("kind") == "paragraph_break":
            # Record a lightweight paragraph-break marker in the segment list.
            # It carries no transcript text and is never broadcast as content.
            # It survives into background processing so format_petition_prose
            # honors the paragraph boundary in the final output.
            break_marker = {
                "segment_id": segment_id,
                "is_paragraph_break": True,
                "transcript": "",
                "timestamp": datetime.now().isoformat(),
                "start_time_seconds": start_time_seconds,
                "end_time_seconds": end_time_seconds,
            }
            session["segments"].append(break_marker)

            logger.info(
                f"PARAGRAPH BREAK command in session={session_id} "
                f"(segment_id={segment_id}, text='{transcript[:60]}')"
            )

            # Tell the frontend to start a new paragraph. The command segment
            # itself is never broadcast, so this is how the UI learns of it.
            await websocket.send_text(json.dumps({
                "type": "paragraph_break",
                "session_id": session_id,
                "segment_id": segment_id,
            }))
            return  # Do NOT broadcast as transcription_update

        # ----------------------------------------------------------
        # Normal content path — append and broadcast.
        # ----------------------------------------------------------

        # Add transcript to buffer (English text)
        session["transcript_buffer"] += f" {transcript}"

        # Phase 1, Step 7 — also append to raw_transcript_buffer
        if "raw_transcript_buffer" not in session:
            session["raw_transcript_buffer"] = ""
        session["raw_transcript_buffer"] += f" {transcript}"

        # Store segment in session for later correction support
        segment_data = {
            "segment_id": segment_id,
            "transcript": transcript,
            "speaker_heuristic": heuristic_speaker,
            "speaker_confidence": speaker_info.get("confidence", 0),
            "timestamp": datetime.now().isoformat(),
            "language": original_language,  # Original spoken language
            "original_language": original_language,
            "start_time_seconds": start_time_seconds,
            "end_time_seconds": end_time_seconds,
        }
        session["segments"].append(segment_data)

        # Send real-time transcript to frontend with segment_id
        # Note: "transcript" is English, "language" is the SPOKEN language
        response = {
            "type": "transcription_update",
            "session_id": session_id,
            "segment_id": segment_id,
            "transcript": transcript,  # Always English
            "language": original_language,  # Spoken language (hi-IN, te-IN, etc.)
            "original_language": original_language,  # Optional field for clarity
            "speaker": heuristic_speaker,
            "speaker_confidence": speaker_info.get("confidence", 0),
            "timestamp": datetime.now().isoformat(),
            "start_time_seconds": start_time_seconds,
            "end_time_seconds": end_time_seconds,
            "source": "vad_stream",
        }

        print(f"[DEBUG][TRANSCRIPT] BROADCASTING transcription_update: session_id={session_id} "
              f"segment_id={segment_id} text='{transcript[:60]}' now_segments={len(session['segments'])}")
        try:
            await websocket.send_text(json.dumps(response))
            print(f"[DEBUG][TRANSCRIPT] SENT ok to frontend, session_id={session_id}")
        except Exception as e:
            print(f"[DEBUG][TRANSCRIPT] SEND FAILED session_id={session_id}: {type(e).__name__}: {e}")
            raise

    # ============================================================
    # VAD CHUNK PROCESSING
    # ============================================================
    async def _process_vad_chunk(self, session_id: str):
        """Process accumulated audio chunk on speech end."""
        session = self.session_manager.get_session(session_id)

        if not session["current_chunk"]:
            return

        chunk_data = b"".join(session["current_chunk"])
        session["audio_buffer"].append(chunk_data)
        session["current_chunk"] = []

    # ============================================================
    # LANGUAGE TRACKING
    # ============================================================
    def _update_language_detection(self, session: Dict, detected_language: str):
        """Track language confidence across segments."""
        if not detected_language:
            return

        if detected_language not in session["language_confidence"]:
            session["language_confidence"][detected_language] = 0

        session["language_confidence"][detected_language] += 1

        primary_language = max(
            session["language_confidence"].items(),
            key=lambda x: x[1]
        )[0]

        session["detected_language"] = primary_language
