# services/realtime/audio_stream_handler.py

import asyncio
import base64
import json
import time
import uuid
from datetime import datetime
from typing import Dict, List, Optional
from fastapi import WebSocket

from utils.language_utils import LanguageUtils
from utils.speaker_utils import identify_speaker
from services.realtime.command_parser import classify_segment


class AudioStreamHandler:

    def __init__(self, session_manager, vad_service, content_correction_handler=None):
        self.session_manager = session_manager
        self.vad_service = vad_service
        self.content_correction_handler = content_correction_handler

    # ============================================================
    # AUDIO INPUT FROM FRONTEND
    # ============================================================
    async def process_audio(self, websocket: WebSocket, data: Dict):

        session_id = data.get("session_id")
        audio_data = data.get("audio_data")

        if not session_id or not self.session_manager.exists(session_id):
            await websocket.send_text(json.dumps({
                "type": "error",
                "message": "Invalid session"
            }))
            return

        session = self.session_manager.get_session(session_id)

        if session.get("ending", False):
            return

        if not session.get("vad_active"):
            return

        try:
            audio_buffer = base64.b64decode(audio_data)

            if len(audio_buffer) % 2 != 0:
                return

            # Track chunk count
            if '_audio_chunk_count' not in session:
                session['_audio_chunk_count'] = 0
            session['_audio_chunk_count'] += 1

            if session['_audio_chunk_count'] % 10 == 0:
                print(f"🎤 Audio chunks received: {session['_audio_chunk_count']} (size: {len(audio_buffer)} bytes)")

            session["current_chunk"].append(audio_buffer)

            await self.vad_service.send_audio_chunk(
                session_id=session_id,
                audio_data=audio_buffer,
                encoding="audio/wav",
                sample_rate=16000
            )

        except Exception as e:
            print(f"❌ Audio processing error: {e}")
            await websocket.send_text(json.dumps({
                "type": "error",
                "message": "Audio processing failed"
            }))

    # ============================================================
    # VAD EVENT CALLBACK
    # ============================================================
    async def handle_vad_event(self, session_id: str, event):

        if not self.session_manager.exists(session_id):
            return

        session = self.session_manager.get_session(session_id)
        websocket = session["websocket"]

        try:
            event_type = getattr(event, "type", "unknown")

            if event_type == "events":
                signal_type = getattr(event.data, "signal_type", None)

                if signal_type == "START_SPEECH":
                    session["speech_in_progress"] = True

                elif signal_type == "END_SPEECH":
                    session["speech_in_progress"] = False

                    if session["current_chunk"]:
                        await self._process_vad_chunk(session_id)

            elif event_type == "data":
                # ----------------------------------------------------------
                # Risk D defensive assertion — retroactive VAD refinement.
                #
                # If two 'data' events arrive < 200ms apart, it may indicate
                # Sarvam is sending interim→final corrections (not expected
                # per current SDK docs, but worth surfacing empirically).
                # ----------------------------------------------------------
                now_mono = time.monotonic()
                last_data_time = session.get("_last_data_event_mono")
                if last_data_time is not None:
                    gap_ms = (now_mono - last_data_time) * 1000.0
                    if gap_ms < 200.0:
                        print(
                            f"⚠️ RISK-D WARNING: Two 'data' events arrived {gap_ms:.1f}ms apart "
                            f"for session={session_id}. Possible interim→final refinement detected. "
                            f"Investigate if segment text was retroactively updated."
                        )
                session["_last_data_event_mono"] = now_mono

                transcript = getattr(event.data, "transcript", "").strip()

                if transcript:
                    await self._handle_transcript(session_id, transcript, event.data)

        except Exception as e:
            print(f"❌ VAD handle_vad_event: Exception for session={session_id}: {e}")

    # ============================================================
    # TRANSCRIPT HANDLING
    # ============================================================
    async def _handle_transcript(self, session_id: str, transcript: str, event_data):

        session = self.session_manager.get_session(session_id)
        if not session:
            return

        # Phase 1, Step 5 — reject late-arriving transcripts after end_session
        if session.get("ending", False):
            return

        websocket = session["websocket"]

        # Generate a stable segment_id for this transcript segment
        segment_id = f"seg_{uuid.uuid4().hex[:12]}"

        # Detect language
        detected_language = LanguageUtils.detect_actual_language(transcript)
        if not detected_language:
            detected_language = getattr(event_data, "language_code", "unknown")

        self._update_language_detection(session, detected_language)

        # Run heuristic speaker identification
        speaker_info = identify_speaker(transcript)
        heuristic_speaker = speaker_info.get("speaker")

        # ----------------------------------------------------------
        # Audio-time anchoring (Phase 0, Step 0.3.1)
        #
        # The Sarvam SDK's SpeechToTextTranscriptionData carries
        # metrics.audio_duration — the cumulative seconds of audio
        # processed up to this transcript emission.
        # We use this as the segment's audio-position anchor for
        # time-based matching to post-session diarization segments.
        #
        # start_time_seconds: previous segment's audio_end or 0.0
        # end_time_seconds:   metrics.audio_duration from this event
        # ----------------------------------------------------------
        metrics = getattr(event_data, "metrics", None)
        audio_end_time_seconds = getattr(metrics, "audio_duration", None) if metrics else None

        # Derive start_time from the previous segment's end time
        prev_segments = session.get("segments", [])
        if prev_segments and prev_segments[-1].get("end_time_seconds") is not None:
            start_time_seconds = prev_segments[-1]["end_time_seconds"]
        else:
            start_time_seconds = 0.0

        # If the SDK didn't provide audio_duration, fall back to wall-clock offset.
        # This is a deliberate fallback pending real SDK timestamps — see pre-check
        # investigation in EXECUTION_PLAN.md.
        if audio_end_time_seconds is None:
            end_time_seconds = (datetime.now() - session["start_time"]).total_seconds()
            start_time_seconds = prev_segments[-1].get("end_time_seconds", 0.0) if prev_segments else 0.0
        else:
            end_time_seconds = audio_end_time_seconds

        # ----------------------------------------------------------
        # Monotonicity assertion for audio-time anchors.
        #
        # metrics.audio_duration is documented as cumulative audio
        # processed. If a new segment's derived start_time is less
        # than the previous segment's end_time, something is wrong
        # (stream reconnect, SDK reset, etc.). Log a warning rather
        # than silently trusting a corrupted anchor chain.
        # ----------------------------------------------------------
        if prev_segments:
            prev_end = prev_segments[-1].get("end_time_seconds", 0.0)
            if start_time_seconds < prev_end - 0.01:  # small epsilon for float precision
                print(
                    f"⚠️ MONOTONICITY WARNING: New segment start_time_seconds={start_time_seconds:.3f} "
                    f"is less than previous segment end_time_seconds={prev_end:.3f} "
                    f"for session={session_id}. Possible stream reset or SDK anchor corruption. "
                    f"Clamping start_time to previous end."
                )
                start_time_seconds = prev_end

        # ----------------------------------------------------------
        # Phase 1, Step 2 — Command detection (pre-broadcast).
        #
        # Classify BEFORE appending to segments or broadcasting.
        # If the segment is a voice correction command:
        #   - Do NOT append to session["segments"].
        #   - Do NOT broadcast transcription_update.
        #   - Store the parsed command + segment metadata for Step 3
        #     (ContentCorrectionHandler) to pick up.
        # ----------------------------------------------------------
        command = classify_segment(transcript, language=detected_language)

        if command is not None:
            # This segment is a voice correction command, not content.
            command_segment_data = {
                "segment_id": segment_id,
                "transcript": transcript,
                "speaker_heuristic": heuristic_speaker,
                "speaker_confidence": speaker_info.get("confidence", 0),
                "timestamp": datetime.now().isoformat(),
                "language": detected_language,
                "start_time_seconds": start_time_seconds,
                "end_time_seconds": end_time_seconds,
                "command": command,  # {"kind": "scratch"} or {"kind": "replace", "replacement": ...}
            }

            print(
                f"🎯 COMMAND DETECTED in session={session_id}: {command} "
                f"(segment_id={segment_id}, text='{transcript[:60]}')"
            )

            # Dispatch to ContentCorrectionHandler (Phase 1, Step 3).
            if self.content_correction_handler is not None:
                await self.content_correction_handler.propose(
                    session_id=session_id,
                    command=command,
                    command_segment_data=command_segment_data,
                )
            else:
                # Fallback if handler not yet injected (shouldn't happen post-Step 3)
                await websocket.send_text(json.dumps({
                    "type": "correction_failed",
                    "session_id": session_id,
                    "reason": "handler_not_wired",
                    "command": command,
                    "command_segment_id": segment_id,
                }))
            return  # Do NOT broadcast as transcription_update

        # ----------------------------------------------------------
        # Normal content path — append and broadcast.
        # ----------------------------------------------------------

        # Add transcript to buffer
        session["transcript_buffer"] += f" {transcript}"

        # Phase 1, Step 7 — also append to raw_transcript_buffer (verbatim, never
        # mutated by content corrections). This is what gets uploaded as transcription.txt.
        if "raw_transcript_buffer" not in session:
            session["raw_transcript_buffer"] = ""
        session["raw_transcript_buffer"] += f" {transcript}"

        # Check if manual speaker tags override the heuristic
        speaker_tags = session.get("speaker_tags", {})
        # If manual tags exist, we can't map from heuristic to channel here
        # (that requires diarization). Just pass the heuristic guess for now.

        # Store segment in session for later correction support
        segment_data = {
            "segment_id": segment_id,
            "transcript": transcript,
            "speaker_heuristic": heuristic_speaker,
            "speaker_confidence": speaker_info.get("confidence", 0),
            "timestamp": datetime.now().isoformat(),
            "language": detected_language,
            "start_time_seconds": start_time_seconds,
            "end_time_seconds": end_time_seconds,
        }
        session["segments"].append(segment_data)

        # Send real-time transcript to frontend with segment_id
        response = {
            "type": "transcription_update",
            "session_id": session_id,
            "segment_id": segment_id,
            "transcript": transcript,
            "language": detected_language,
            "speaker": heuristic_speaker,
            "speaker_confidence": speaker_info.get("confidence", 0),
            "timestamp": datetime.now().isoformat(),
            "start_time_seconds": start_time_seconds,
            "end_time_seconds": end_time_seconds,
            "source": "vad_stream",
        }

        await websocket.send_text(json.dumps(response))

    # ============================================================
    # VAD CHUNK PROCESSING
    # ============================================================
    async def _process_vad_chunk(self, session_id: str):

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
