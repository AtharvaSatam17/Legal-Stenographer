# services/realtime_service.py (Legal Stenographer Version)
import asyncio
import json
import base64
import uuid
import time
import os
import re
from datetime import datetime
from pathlib import Path
from typing import Dict, List, Any
from fastapi import WebSocket
import aiofiles

from services.realtime.audio_stream_handler import AudioStreamHandler
from services.realtime.background_processor import BackgroundProcessor
from services.realtime.content_correction_handler import ContentCorrectionHandler
from core.session_manager import SessionManager

from services.sarvam_service import SarvamService
from services.vad_service import VADService
from services.diarization_service import DiarizationService
from services.s3_storage_service import S3StorageService


class RealTimeTranscriptionService:
    def __init__(self):

        # Core services
        self.sarvam_service = SarvamService()

        # Pass sarvam_service dependency
        self.vad_service = VADService(self.sarvam_service)
        self.diarization_service = DiarizationService(self.sarvam_service)

        self.s3_storage_service = S3StorageService()
        self.session_manager = SessionManager()

        # Content correction handler (Phase 1, Step 3)
        self.content_correction_handler = ContentCorrectionHandler(
            session_manager=self.session_manager
        )

        # Audio handler — inject the content_correction_handler
        self.audio_handler = AudioStreamHandler(
            session_manager=self.session_manager,
            vad_service=self.vad_service,
            content_correction_handler=self.content_correction_handler,
        )

        # Background processor (handles diarization and legal formatting)
        self.background_processor = BackgroundProcessor(
            diarization_service=self.diarization_service,
            s3_storage_service=self.s3_storage_service
        )
        # Test S3 connection on startup
        # asyncio.create_task(self._test_s3_connection())

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
            
            # Remove from active sessions
            # self.session_manager.delete_session(session_id)
                
            print(f'🧹 Session cleanup completed: {session_id}')
        except Exception as e:
            print(f'Session cleanup error: {e}')

    async def update_session_transcript(self, websocket: WebSocket, data: Dict):
        """Update session transcript buffer with edited content"""
        session_id = data.get('session_id')
        updated_transcript = data.get('transcript')

        print(f'🔄 UPDATE_TRANSCRIPT REQUEST: Session={session_id}')
        print(f'📄 Transcript length: {len(updated_transcript) if updated_transcript else 0}')
        print(f'📝 Transcript preview: "{self.sanitize_for_log(updated_transcript or "", 200)}"')

        if not session_id or not self.session_manager.exists(session_id):
            print(f'❌ Invalid session for update: {session_id}')
            print(f'🔍 Active sessions: {self.session_manager.list_sessions()}')
            await websocket.send_text(json.dumps({
                'type': 'error',
                'message': 'Invalid session'
            }))
            return

        session = self.session_manager.get_session(session_id)


        if updated_transcript is not None:
            # Store the old transcript for comparison
            old_transcript = session.get('transcript_buffer', '')
            
            # Update the session's transcript buffer
            session['transcript_buffer'] = updated_transcript.strip()
            
            print(f'✅ TRANSCRIPT UPDATED IN SESSION:')
            print(f'   Old length: {len(old_transcript)}')
            print(f'   New length: {len(session["transcript_buffer"])}')
            print(f'   Old preview: "{self.sanitize_for_log(old_transcript, 100)}"')
            print(f'   New preview: "{self.sanitize_for_log(session["transcript_buffer"], 100)}"')
            
            await websocket.send_text(json.dumps({
                'type': 'transcript_updated',
                'session_id': session_id,
                'message': 'Transcript updated successfully',
                'transcript_length': len(session['transcript_buffer'])
            }))
        else:
            print('❌ No transcript provided in update request')
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

            # CRITICAL DEBUG: Log ALL incoming messages
            print(f'📨 RECEIVED MESSAGE: Type={message_type}, Session={session_id}')
            
            # Log audio_stream messages with size info
            if message_type == 'audio_stream':
                audio_data = data.get('audio_data', '')
                print(f'🎵 AUDIO_STREAM message received: audio_data length = {len(audio_data)} bytes')

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
            # Phase 1, Step 3 — content correction lifecycle messages
            elif message_type == 'content_correction_accept':
                await self.content_correction_handler.accept(
                    session_id=data.get('session_id'),
                    correction_id=data.get('correction_id'),
                    staff_username=data.get('staff_username', 'staff'),
                )
            elif message_type == 'content_correction_reject':
                await self.content_correction_handler.reject(
                    session_id=data.get('session_id'),
                    correction_id=data.get('correction_id'),
                    staff_username=data.get('staff_username', 'staff'),
                )
            elif message_type == 'content_correction_reverse':
                await self.content_correction_handler.reverse(
                    session_id=data.get('session_id'),
                    correction_id=data.get('correction_id'),
                    staff_username=data.get('staff_username', 'staff'),
                )
            elif message_type == 'content_correction_push':
                # Push-to-command: staff triggers a correction via keyboard shortcut.
                # Phase 1, Step 8:
                #   - scratch: bypasses pending window, applied immediately (auto_pushed)
                #   - replace: goes through normal pending window so staff can verify
                push_command = {
                    "kind": data.get("kind", "scratch"),
                }
                if push_command["kind"] == "replace":
                    push_command["replacement"] = data.get("replacement", "")
                # Build a synthetic command_segment_data for the push
                push_segment_data = {
                    "segment_id": f"push_{uuid.uuid4().hex[:8]}",
                    "transcript": f"[staff push: {push_command['kind']}]",
                    "speaker_heuristic": "STAFF",
                    "speaker_confidence": 1.0,
                    "timestamp": datetime.now().isoformat(),
                    "language": "en-IN",
                    "start_time_seconds": None,
                    "end_time_seconds": None,
                }
                push_session_id = data.get('session_id')
                staff_user = data.get('staff_username', 'staff')

                if push_command["kind"] == "scratch":
                    # Scratch: propose and immediately accept (no pending window)
                    await self.content_correction_handler.propose(
                        session_id=push_session_id,
                        command=push_command,
                        command_segment_data=push_segment_data,
                    )
                    # Find the pending correction we just created and auto-accept it
                    session = self.session_manager.get_session(push_session_id)
                    if session:
                        pending_ids = list(session.get("pending_content_corrections", {}).keys())
                        if pending_ids:
                            latest_cid = pending_ids[-1]
                            await self.content_correction_handler.accept(
                                push_session_id, latest_cid, f"auto_pushed:{staff_user}"
                            )
                else:
                    # Replace: go through normal pending window
                    await self.content_correction_handler.propose(
                        session_id=push_session_id,
                        command=push_command,
                        command_segment_data=push_segment_data,
                    )
            # Phase 1, Step 10 — session resync on reconnect
            elif message_type == 'session_resync':
                await self._handle_session_resync(websocket, data)
            else:
                print(f'❌ UNKNOWN MESSAGE TYPE: {message_type}')
                await websocket.send_text(json.dumps({
                    'type': 'error',
                    'message': 'Unknown message type'
                }))

        except json.JSONDecodeError:
            print(f'Invalid JSON received: {message}')
            await websocket.send_text(json.dumps({
                'type': 'error',
                'message': 'Invalid message format'
            }))
        except Exception as e:
            print(f'WebSocket message error: {e}')
            await websocket.send_text(json.dumps({
                'type': 'error',
                'message': 'Message processing failed'
            }))

    async def start_real_time_session(self, websocket: WebSocket, data: Dict):

        # Use SessionManager to create session
        session = self.session_manager.create_session(websocket, data)
        session_id = session["id"]

        preferred_language = session.get("preferred_language")
        processing_mode = session.get("processing_mode")

        # Start VAD stream
        vad_started = await self.vad_service.start_vad_stream(
            session_id=session_id,
            model="saaras:v3",
            target_language=preferred_language if processing_mode == "translate" else None,
            event_callback=self.audio_handler.handle_vad_event,
            timeout=300
        )

        if not vad_started:
            await websocket.send_text(json.dumps({
                "type": "error",
                "message": "Failed to start VAD stream"
            }))
            return

        session["vad_active"] = True

        await websocket.send_text(json.dumps({
            "type": "session_started",
            "session_id": session_id,
            "vad_enabled": True,
            "client_role": session.get("client_role", "plaintiff")
        }))

        print(f"🎤 Started session: {session_id} (client_role={session.get('client_role')})")

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

        print(f"🏷️ Speaker tagged: {speaker_id} → {role} (session={session_id})")

    async def correct_speaker(self, websocket: WebSocket, data: Dict):
        """
        Correct the speaker assignment for a specific transcript segment.
        e.g., { type: "correct_speaker", session_id: "...", segment_id: "seg_abc123", speaker: "LAWYER" }
        
        Corrections are stored as an overlay and take highest precedence during
        final transcript generation (correction > diarization > heuristic).
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

        # ----------------------------------------------------------
        # Phase 0, Step 0.3.2 — store correction with audio-time anchor.
        #
        # Resolve the target segment from session["segments"] by matching
        # segment_id, pull its start_time_seconds, and store an object so
        # the post-session formatter can match by audio time rather than
        # by (unrelated) diarization segment ids.
        # ----------------------------------------------------------
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

        print(f"✏️ Speaker corrected: segment={segment_id} → {corrected_speaker} (start_t={start_time_anchor}) (session={session_id})")

    async def _test_s3_connection(self):
        """Test S3 connection on service startup"""
        try:
            success = await self.s3_storage_service.check_bucket_access()
            if success:
                print("S3 storage service ready")
            else:
                print("Warning: S3 storage service unavailable - session data will only be saved locally")
        except Exception as e:
            print(f"S3 connection test failed: {e}")

    async def end_real_time_session(self, websocket: WebSocket, data: Dict):
        """End real-time session immediately and process cleanup in background"""
        session_id = data.get('session_id')
        user_sub = data.get('user_id')
        username = data.get('username')
        print(f'🏁 Username is to be saved: {username}')
        user_sub = username or data.get('user_id')  # Use username as user_sub
        print(f'🏁 Username to be saved2: {username}')
        print(f'👤 User_sub: {user_sub}')
        if not session_id or not self.session_manager.exists(session_id):
            await websocket.send_text(json.dumps({
                'type': 'error',
                'message': 'Invalid session'
            }))
            return

        session = self.session_manager.get_session(session_id)
        context = data.get('context') or session.get('context', 'Legal')
        
        try:
            print(f'🔚 Ending session: {session_id}')

            # Step 1: Stop VAD stream immediately
            if session.get('vad_active'):
                await self.vad_service.stop_vad_stream(session_id)
                session['vad_active'] = False
                print(f'✅ VAD stream stopped for session: {session_id}')

            # Step 2: Mark session as "ending" to prevent new audio processing
            session['ending'] = True
            
            # Step 3: Calculate session duration
            duration = (datetime.now() - session['start_time']).total_seconds()
            
            # Step 4: Send immediate response to frontend
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
            print(f'✅ Immediate session_ended response sent to frontend')

            # ----------------------------------------------------------
            # Phase 1, Step 5 — Force-commit any pending content corrections.
            #
            # Deviation from plan: the plan specified a 3-second grace wait
            # inside the background task. Per agreed deviation, we force-commit
            # immediately here (before snapshot) so end_session still returns
            # fast. Any pending corrections are auto-committed with
            # confirmed_by="ended_session_auto". No new commands can arrive
            # because session["ending"] = True blocks process_audio above.
            # ----------------------------------------------------------
            if session.get("pending_content_corrections"):
                print(f'⏱️ Force-committing {len(session["pending_content_corrections"])} pending corrections before snapshot')
                await self.content_correction_handler.force_commit_all_pending(session_id)

            # Step 5: Create a deep copy of session data for background processing
            # This prevents issues if user starts a new session immediately
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
                # Consultation-specific fields
                'case_id': session.get('case_id'),
                'matter_type': session.get('matter_type'),
                'client_role': session.get('client_role', 'plaintiff'),
                'speaker_tags': session.get('speaker_tags', {}),
                'speaker_corrections': session.get('speaker_corrections', {}),
                'segments': session.get('segments', []),
                # Phase 1 — content corrections (append-only log, post-force-commit)
                'content_corrections': session.get('content_corrections', []),
            }
            
            # Step 6: Remove session from active sessions immediately
            # This allows user to start a new session right away
            self.session_manager.delete_session(session_id)

            print(f'✅ Session removed from active sessions: {session_id}')
            
            # Step 7: Launch background processing task (fire and forget)
            asyncio.create_task(
                self.background_processor.process(session_data_copy)
            )
            print(f'🚀 Background processing task launched for session: {session_id}')

        except Exception as e:
            print(f'❌ End session error: {e}')
            import traceback
            traceback.print_exc()
            
            await websocket.send_text(json.dumps({
                'type': 'error',
                'message': 'Failed to end session'
            }))

    # ============================================================================
    # UTILITY METHODS
    # ============================================================================

    async def _handle_session_resync(self, websocket: WebSocket, data: Dict):
        """
        Phase 1, Step 10 — Handle session resync request after reconnect.
        If the session still exists, reply with current state.
        If not, reply session_resync_failed.
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

        # Update the websocket reference for the session (new socket after reconnect)
        session["websocket"] = websocket

        # Build state payload
        state_payload = {
            'type': 'session_state',
            'session_id': session_id,
            'segments': session.get('segments', []),
            'content_corrections': session.get('content_corrections', []),
            'pending_content_corrections': session.get('pending_content_corrections', {}),
            'transcript_buffer': session.get('transcript_buffer', ''),
            'session_active': not session.get('ending', False),
        }

        await websocket.send_text(json.dumps(state_payload))
        print(f"🔄 Session resync sent for: {session_id}")

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
            print(f'Force stop session error: {e}')
            return False

    async def shutdown(self):
        """Shutdown service and cleanup all resources"""
        print('🛑 Shutting down RealTimeTranscriptionService...')
        
        # Stop all VAD streams
        await self.vad_service.stop_all_streams()
        
        # Clear all sessions
        self.session_manager.clear()
        
        print('✅ RealTimeTranscriptionService shutdown complete')