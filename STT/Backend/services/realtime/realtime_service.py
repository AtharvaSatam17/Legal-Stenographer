# services/realtime_service.py (Legal Stenographer Version)
import asyncio
import json
import logging
import uuid
from datetime import datetime
from typing import Dict, List, Any
from fastapi import WebSocket

from services.realtime.audio_stream_handler import AudioStreamHandler
from services.realtime.background_processor import BackgroundProcessor
from core.session_manager import SessionManager

from services.sarvam_service import SarvamService
from services.vad_service import VADService
from services.diarization_service import DiarizationService
from services.s3_storage_service import S3StorageService

logger = logging.getLogger(__name__)
logger.setLevel(logging.INFO)


class RealTimeTranscriptionService:
    """
    Real-time legal transcription service using Sarvam AI.
    
    All speech input (any language) is transcribed and translated to English.
    Uses saaras:v3 model with mode="translate" and language_code="unknown"
    for automatic language detection.
    """

    def __init__(self):
        # Core services
        self.sarvam_service = SarvamService()

        # Pass sarvam_service dependency
        self.vad_service = VADService(self.sarvam_service)
        self.diarization_service = DiarizationService(self.sarvam_service)

        self.s3_storage_service = S3StorageService()
        self.session_manager = SessionManager()

        # Audio handler
        self.audio_handler = AudioStreamHandler(
            session_manager=self.session_manager,
            vad_service=self.vad_service,
        )

        # Background processor (handles diarization and legal formatting)
        self.background_processor = BackgroundProcessor(
            diarization_service=self.diarization_service,
            s3_storage_service=self.s3_storage_service
        )

        logger.info("RealTimeTranscriptionService initialized with always-English translation mode")

    async def _test_s3_connection(self):
        """Test S3 connection on service startup"""
        try:
            success = await self.s3_storage_service.check_bucket_access()
            if success:
                logger.info("S3 storage service ready")
            else:
                logger.warning("S3 storage service unavailable - session data will only be saved locally")
        except Exception as e:
            logger.warning(f"S3 connection test failed: {e}")

    def sanitize_for_log(self, input_text: str, max_length: int = 200) -> str:
        """Sanitize input for logging to prevent log injection"""
        if not isinstance(input_text, str):
            return str(input_text)
        return input_text.replace('\r', ' ').replace('\n', ' ').replace('\t', ' ')[:max_length]

    def serialize_datetime_objects(self, obj):
        """Recursively convert datetime objects to ISO format strings for JSON serialization"""
        if isinstance(obj, datetime):
            return obj.isoformat()
        elif isinstance(obj, dict):
            return {key: self.serialize_datetime_objects(value) for key, value in obj.items()}
        elif isinstance(obj, list):
            return [self.serialize_datetime_objects(item) for item in obj]
        else:
            return obj

    async def _cleanup_session(self, session_id: str):
        """Clean up session resources"""
        try:
            # Stop VAD stream if active
            if self.vad_service.is_stream_active(session_id):
                await self.vad_service.stop_vad_stream(session_id)
            
            # Remove from session manager
            if self.session_manager.exists(session_id):
                self.session_manager.delete_session(session_id)
                
            logger.info(f"Session cleanup completed: {session_id}")
        except Exception as e:
            logger.exception(f"Session cleanup error: {e}")

    async def update_session_transcript(self, websocket: WebSocket, data: Dict):
        """
        Update session transcript with edited content.

        Preferred form (Option A): data["paragraphs"] is an ordered list of
        paragraph strings. We rebuild session["segments"] into the equivalent
        content + paragraph-break-marker form so the final petition prose
        (built from segments) matches the edit. Numbering is derived at
        format time, never stored.

        Legacy form: data["transcript"] is a plain string; we just overwrite
        the transcript buffer.
        """
        session_id = data.get('session_id')
        paragraphs = data.get('paragraphs')
        updated_transcript = data.get('transcript')

        logger.debug(f"UPDATE_TRANSCRIPT REQUEST: Session={session_id}")

        if not session_id or not self.session_manager.exists(session_id):
            logger.warning(f"Invalid session for update: {session_id}")
            await websocket.send_text(json.dumps({
                'type': 'error',
                'message': 'Invalid session'
            }))
            return

        session = self.session_manager.get_session(session_id)

        if isinstance(paragraphs, list):
            # Normalize + drop empties
            clean_paras = []
            for p in paragraphs:
                if not isinstance(p, str):
                    continue
                p = " ".join(p.split()).strip()
                if p:
                    clean_paras.append(p)

            # Rebuild segments: one content segment per paragraph, with a
            # paragraph-break marker between consecutive paragraphs.
            rebuilt_segments = []
            for i, text in enumerate(clean_paras):
                if i > 0:
                    rebuilt_segments.append({
                        "segment_id": f"edit_break_{i}_{uuid.uuid4().hex[:6]}",
                        "is_paragraph_break": True,
                        "transcript": "",
                        "timestamp": datetime.now().isoformat(),
                        "start_time_seconds": None,
                        "end_time_seconds": None,
                    })
                rebuilt_segments.append({
                    "segment_id": f"edit_seg_{i}_{uuid.uuid4().hex[:6]}",
                    "transcript": text,
                    "speaker_heuristic": None,
                    "speaker_confidence": 0,
                    "timestamp": datetime.now().isoformat(),
                    "language": session.get("detected_language"),
                    "original_language": session.get("detected_language"),
                    "start_time_seconds": None,
                    "end_time_seconds": None,
                })

            session["segments"] = rebuilt_segments
            joined = " ".join(clean_paras).strip()
            session["transcript_buffer"] = joined
            session["raw_transcript_buffer"] = joined

            logger.info(f"Transcript updated from {len(clean_paras)} paragraph(s), {len(rebuilt_segments)} segments")

            await websocket.send_text(json.dumps({
                'type': 'transcript_updated',
                'session_id': session_id,
                'message': 'Transcript updated successfully',
                'paragraphs': len(clean_paras),
                'transcript_length': len(joined),
            }))
        elif updated_transcript is not None:
            # Legacy plain-string path
            old_length = len(session.get('transcript_buffer', ''))
            session['transcript_buffer'] = updated_transcript.strip()
            new_length = len(session["transcript_buffer"])

            logger.info(f"Transcript updated (legacy string): {old_length} -> {new_length} chars")

            await websocket.send_text(json.dumps({
                'type': 'transcript_updated',
                'session_id': session_id,
                'message': 'Transcript updated successfully',
                'transcript_length': new_length
            }))
        else:
            logger.warning('No transcript provided in update request')
            await websocket.send_text(json.dumps({
                'type': 'error',
                'message': 'No transcript provided'
            }))

    async def handle_websocket_message(self, websocket: WebSocket, message: str):
        """Handle different types of WebSocket messages for legal transcription."""
        try:
            data = json.loads(message)
            message_type = data.get('type')
            session_id = data.get('session_id')

            # Log non-audio messages at INFO level
            if message_type != 'audio_stream':
                logger.debug(f"Received message: Type={message_type}, Session={session_id}")

            if message_type == 'start_session':
                await self.start_real_time_session(websocket, data)
            elif message_type == 'audio_stream':
                await self.audio_handler.process_audio(websocket, data)
            elif message_type == 'end_session':
                await self.end_real_time_session(websocket, data)
            elif message_type == 'update_transcript':
                await self.update_session_transcript(websocket, data)
            elif message_type == 'tag_speaker':
                await self.tag_speaker(websocket, data)
            elif message_type == 'correct_speaker':
                await self.correct_speaker(websocket, data)
            # Session resync on reconnect
            elif message_type == 'session_resync':
                await self._handle_session_resync(websocket, data)
            else:
                logger.warning(f"Unknown message type: {message_type}")
                await websocket.send_text(json.dumps({
                    'type': 'error',
                    'message': 'Unknown message type'
                }))

        except json.JSONDecodeError:
            logger.warning(f"Invalid JSON received")
            await websocket.send_text(json.dumps({
                'type': 'error',
                'message': 'Invalid message format'
            }))
        except Exception as e:
            logger.exception(f"WebSocket message error: {e}")
            await websocket.send_text(json.dumps({
                'type': 'error',
                'message': 'Message processing failed'
            }))

    async def start_real_time_session(self, websocket: WebSocket, data: Dict):
        """
        Start a new real-time transcription session.
        
        Always uses mode="translate" to output English regardless of input language.
        The processing_mode from frontend is accepted but only "transcribe" disables
        translation (kept for backward compatibility, but translate is default).
        """
        # Use SessionManager to create session
        session = self.session_manager.create_session(websocket, data)
        session_id = session["id"]

        # Determine processing mode
        # Default is "translate" (always English output)
        # Only explicit "transcribe" disables translation
        processing_mode = session.get("processing_mode", "translate")
        if processing_mode != "transcribe":
            processing_mode = "translate"

        logger.info(f"Starting session {session_id} with mode={processing_mode}")

        # Start VAD stream with translate mode
        vad_started = await self.vad_service.start_vad_stream(
            session_id=session_id,
            model="saaras:v3",
            mode=processing_mode,
            event_callback=self.audio_handler.handle_vad_event,
        )

        if not vad_started:
            await websocket.send_text(json.dumps({
                "type": "error",
                "message": "Failed to start VAD stream"
            }))
            return

        session["vad_active"] = True

        # Send session_started with language metadata
        await websocket.send_text(json.dumps({
            "type": "session_started",
            "session_id": session_id,
            "vad_enabled": True,
            "client_role": session.get("client_role", "plaintiff"),
            "output_language": "en-IN",  # Always English output
            "auto_detect": True,  # Input language is auto-detected
        }))

        logger.info(f"Started session: {session_id} (client_role={session.get('client_role')}, mode={processing_mode})")

    async def tag_speaker(self, websocket: WebSocket, data: Dict):
        """
        Manually tag which detected speaker channel is the Lawyer vs Client.
        e.g., { type: "tag_speaker", session_id: "...", speaker_id: "SPEAKER_1", role: "LAWYER" }
        """
        session_id = data.get('session_id')
        speaker_id = data.get('speaker_id', '').upper().strip()
        role = data.get('role', '').upper().strip()

        if not session_id or not self.session_manager.exists(session_id):
            await websocket.send_text(json.dumps({
                'type': 'error',
                'message': 'Invalid session'
            }))
            return

        session = self.session_manager.get_session(session_id)

        if not speaker_id or not role:
            await websocket.send_text(json.dumps({
                'type': 'error',
                'message': 'speaker_id and role are required'
            }))
            return

        # Store the manual speaker tag
        session["speaker_tags"][speaker_id] = role

        await websocket.send_text(json.dumps({
            'type': 'speaker_tagged',
            'session_id': session_id,
            'speaker_id': speaker_id,
            'role': role,
            'current_tags': session["speaker_tags"]
        }))

        logger.info(f"Speaker tagged: {speaker_id} → {role} (session={session_id})")

    async def correct_speaker(self, websocket: WebSocket, data: Dict):
        """
        Correct the speaker assignment for a specific transcript segment.
        """
        session_id = data.get('session_id')
        segment_id = data.get('segment_id')
        corrected_speaker = data.get('speaker', '').upper().strip()

        if not session_id or not self.session_manager.exists(session_id):
            await websocket.send_text(json.dumps({
                'type': 'error',
                'message': 'Invalid session'
            }))
            return

        if not segment_id or not corrected_speaker:
            await websocket.send_text(json.dumps({
                'type': 'error',
                'message': 'segment_id and speaker are required'
            }))
            return

        session = self.session_manager.get_session(session_id)

        # Find target segment and get audio-time anchor
        target_segment = next(
            (seg for seg in session.get("segments", []) if seg.get("segment_id") == segment_id),
            None
        )
        start_time_anchor = target_segment.get("start_time_seconds") if target_segment else None

        session["speaker_corrections"][segment_id] = {
            "role": corrected_speaker,
            "start_time_seconds": start_time_anchor,
        }

        await websocket.send_text(json.dumps({
            'type': 'speaker_corrected',
            'session_id': session_id,
            'segment_id': segment_id,
            'corrected_speaker': corrected_speaker,
            'total_corrections': len(session["speaker_corrections"])
        }))

        logger.info(f"Speaker corrected: segment={segment_id} → {corrected_speaker} (session={session_id})")

    async def end_real_time_session(self, websocket: WebSocket, data: Dict):
        """End real-time session immediately and process cleanup in background"""
        session_id = data.get('session_id')
        user_sub = data.get('user_id')
        username = data.get('username')
        user_sub = username or data.get('user_id')

        if not session_id or not self.session_manager.exists(session_id):
            await websocket.send_text(json.dumps({
                'type': 'error',
                'message': 'Invalid session'
            }))
            return

        session = self.session_manager.get_session(session_id)
        context = data.get('context') or session.get('context', 'Legal')
        
        try:
            logger.info(f"Ending session: {session_id}")

            # Step 1: Mark session as "ending" to prevent new audio processing
            session['ending'] = True

            # Step 2: Flush any remaining buffered audio
            await self.vad_service.flush_buffer(session_id)

            # Step 3: Wait briefly for final transcript (up to 2 seconds)
            await asyncio.sleep(min(2.0, 0.5))

            # Step 4: Stop VAD stream
            if session.get('vad_active'):
                await self.vad_service.stop_vad_stream(session_id)
                session['vad_active'] = False
                logger.info(f"VAD stream stopped for session: {session_id}")

            # Step 5: Calculate session duration
            duration = (datetime.now() - session['start_time']).total_seconds()
            
            # Step 6: Send immediate response to frontend
            immediate_response = {
                'type': 'session_ended',
                'data': {
                    'session_id': session_id,
                    'duration': duration,
                    'started_at': session['start_time'].isoformat(),
                    'ended_at': datetime.now().isoformat(),
                    'message': 'Session ended successfully. Processing data in background...',
                    'background_processing': True
                }
            }
            
            await websocket.send_text(json.dumps(immediate_response))
            logger.info(f"Session ended response sent to frontend")

            # Step 7: Create session data copy for background processing
            session_data_copy = {
                'session_id': session_id,
                'user_sub': user_sub,
                'username': username,
                'audio_buffer': session.get('audio_buffer', []).copy(),
                'transcript_buffer': session.get('transcript_buffer', ''),
                'raw_transcript_buffer': session.get('raw_transcript_buffer', ''),
                'start_time': session['start_time'],
                'end_time': datetime.now(),
                'context': context,
                'processing_mode': session.get('processing_mode'),
                'preferred_language': session.get('preferred_language'),
                'detected_language': session.get('detected_language'),
                'case_id': session.get('case_id'),
                'matter_type': session.get('matter_type'),
                'client_role': session.get('client_role', 'plaintiff'),
                'speaker_tags': session.get('speaker_tags', {}),
                'speaker_corrections': session.get('speaker_corrections', {}),
                'segments': session.get('segments', []),
            }
            
            # Step 8: Remove session from active sessions
            self.session_manager.delete_session(session_id)
            logger.info(f"Session removed from active sessions: {session_id}")
            
            # Step 9: Launch background processing task
            asyncio.create_task(
                self.background_processor.process(session_data_copy)
            )
            logger.info(f"Background processing task launched for session: {session_id}")

        except Exception as e:
            logger.exception(f"End session error: {e}")
            await websocket.send_text(json.dumps({
                'type': 'error',
                'message': 'Failed to end session'
            }))

    async def _handle_session_resync(self, websocket: WebSocket, data: Dict):
        """
        Handle session resync request after reconnect.
        """
        session_id = data.get('session_id')

        if not session_id or not self.session_manager.exists(session_id):
            await websocket.send_text(json.dumps({
                'type': 'session_resync_failed',
                'session_id': session_id,
                'reason': 'session_not_found',
                'message': 'Session no longer exists. It may have ended during the disconnect.',
            }))
            return

        session = self.session_manager.get_session(session_id)

        # Update the websocket reference for the session
        session["websocket"] = websocket

        # Build state payload
        state_payload = {
            'type': 'session_state',
            'session_id': session_id,
            'segments': session.get('segments', []),
            'transcript_buffer': session.get('transcript_buffer', ''),
            'session_active': not session.get('ending', False),
        }

        await websocket.send_text(json.dumps(state_payload))
        logger.info(f"Session resync sent for: {session_id}")

    async def get_session_status(self, session_id: str) -> Dict[str, Any]:
        """Get current status of a session"""
        if not self.session_manager.exists(session_id):
            return {'error': 'Session not found'}
        
        session = self.session_manager.get_session(session_id)
        vad_stats = await self.vad_service.get_stream_stats(session_id)
        
        return {
            'session_id': session_id,
            'start_time': session['start_time'].isoformat(),
            'duration': (datetime.now() - session['start_time']).total_seconds(),
            'vad_active': session.get('vad_active', False),
            'speech_in_progress': session.get('speech_in_progress', False),
            'transcript_length': len(session.get('transcript_buffer', '')),
            'audio_chunks_count': len(session.get('audio_buffer', [])),
            'detected_language': session.get('detected_language'),
            'processing_mode': session.get('processing_mode'),
            'context': session.get('context'),
            'vad_stats': vad_stats
        }

    async def list_active_sessions(self) -> List[str]:
        """Get list of all active sessions"""
        return self.session_manager.list_sessions()

    async def force_stop_session(self, session_id: str) -> bool:
        """Force stop a session (admin/debug function)"""
        if not self.session_manager.exists(session_id):
            return False
        
        try:
            await self._cleanup_session(session_id)
            return True
        except Exception as e:
            logger.exception(f"Force stop session error: {e}")
            return False

    async def shutdown(self):
        """Shutdown service and cleanup all resources"""
        logger.info("Shutting down RealTimeTranscriptionService...")
        
        # Stop all VAD streams
        await self.vad_service.stop_all_streams()
        
        # Clear all sessions
        self.session_manager.clear()
        
        logger.info("RealTimeTranscriptionService shutdown complete")
